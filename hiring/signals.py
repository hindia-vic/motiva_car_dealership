"""Signals that clean up hire car photos when they are deleted.

Django does not delete files when a ``FileField`` row is removed, so
without this the media folder keeps every photo ever uploaded.
"""

import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import HireCarImage

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=HireCarImage)
def _delete_hire_photo_files(sender, instance, **kwargs):
    """Remove the photo and its thumbnail from disk when the row goes."""
    for field in ('image', 'thumbnail'):
        file = getattr(instance, field, None)
        if not file:
            continue
        try:
            file.storage.delete(file.name)
        except Exception:
            logger.warning(
                'Could not delete %s for %s', file.name, instance.hire_car,
                exc_info=True,
            )
