"""Image processing for vehicle photos.

Staff upload photos straight from a camera roll: several megabytes each,
with EXIF data (camera, GPS, orientation) that is of no use to us and is
uncomfortable to keep. Everything that goes into a ``CarImage`` is run
through this module first, so the site only ever serves a resized,
re-encoded copy, and the small version used in listings is generated at
the same time.

Pillow is already a dependency - Django needs it for ``ImageField`` - so
nothing new is added to the project.
"""

import io
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

#: Image formats we accept. Anything else is rejected before it is stored.
ALLOWED_FORMATS = ('JPEG', 'PNG', 'WEBP')

#: File extensions we accept, checked before the file is opened.
ALLOWED_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')


def _wants_png(image):
    """True when the image has transparency and must stay a PNG.

    Converting a picture with an alpha channel to JPEG would paint the
    transparent parts black.
    """
    if image.mode in ('RGBA', 'LA'):
        return True
    if image.mode == 'P':
        return 'transparency' in image.info
    return False


def _open_image(uploaded_file):
    """Open an uploaded file and apply its EXIF orientation."""
    if hasattr(uploaded_file, 'seek'):
        uploaded_file.seek(0)
    image = Image.open(uploaded_file)
    # exif_transpose rotates the pixels to match the orientation tag and
    # drops that tag, so the re-encoded copy has no EXIF left to leak.
    image = ImageOps.exif_transpose(image)
    return image


def _encode(image, quality):
    """Re-encode an image, returning its bytes and the file extension."""
    buffer = io.BytesIO()
    if _wants_png(image):
        image.convert('RGBA').save(buffer, format='PNG', optimize=True)
        return buffer.getvalue(), '.png'
    image.convert('RGB').save(
        buffer,
        format='JPEG',
        quality=quality,
        optimize=True,
        progressive=True,
    )
    return buffer.getvalue(), '.jpg'


def validate_image_upload(uploaded_file):
    """Raise ``ValidationError`` when the file is not an acceptable image.

    The extension, the real content of the file and the size are all
    checked, so a renamed file or an oversized photo is caught before it
    is stored.
    """
    name = (getattr(uploaded_file, 'name', '') or '').lower()
    if not name.endswith(ALLOWED_EXTENSIONS):
        raise ValidationError(
            'Unsupported file type. Please upload a JPG, PNG or WEBP image.'
        )

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    size = getattr(uploaded_file, 'size', 0) or 0
    if size > max_bytes:
        raise ValidationError(
            f'Image is too large (the limit is {settings.MAX_UPLOAD_SIZE_MB} MB).'
        )

    try:
        image = Image.open(uploaded_file)
        image.verify()
        image_format = image.format
    except Exception:
        raise ValidationError('That file could not be read as an image.')

    if image_format not in ALLOWED_FORMATS:
        raise ValidationError(
            'Unsupported image format. Please upload a JPG, PNG or WEBP image.'
        )

    if hasattr(uploaded_file, 'seek'):
        uploaded_file.seek(0)


def process_image(uploaded_file, max_width=None, quality=None):
    """Resize, re-encode and strip an uploaded image.

    Returns a ``(ContentFile, filename)`` pair. Nothing is written to disk
    until the caller saves it.
    """
    max_width = max_width or settings.CAR_IMAGE_MAX_WIDTH
    quality = quality or settings.CAR_IMAGE_QUALITY

    image = _open_image(uploaded_file)
    # thumbnail() keeps the aspect ratio and never enlarges the picture.
    image.thumbnail((max_width, max_width), Image.LANCZOS)
    data, extension = _encode(image, quality)
    name = f'{uuid.uuid4().hex}{extension}'
    return ContentFile(data, name=name), name


def process_thumbnail(uploaded_file, width=None, quality=None):
    """Same as :func:`process_image`, but at thumbnail size."""
    width = width or settings.CAR_IMAGE_THUMBNAIL_WIDTH
    quality = quality or settings.CAR_IMAGE_QUALITY

    image = _open_image(uploaded_file)
    image.thumbnail((width, width), Image.LANCZOS)
    data, extension = _encode(image, quality)
    name = f'{uuid.uuid4().hex}_thumb{extension}'
    return ContentFile(data, name=name), name
