"""Rebuild the resized copy and the thumbnail of every vehicle photo.

Photos uploaded before the image pipeline existed are stored at their
original size, with their EXIF data, and have no small copy. This command
rebuilds both from what is already on disk:

    python manage.py reprocess_images --dry-run
    python manage.py reprocess_images
"""

from django.core.management.base import BaseCommand

from cars.models import CarImage


class Command(BaseCommand):
    help = 'Resize existing vehicle photos and generate their thumbnails.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be processed without changing anything.',
        )
        parser.add_argument(
            '--car',
            type=int,
            default=None,
            help='Only process the photos of this vehicle id.',
        )

    def handle(self, *args, **options):
        photos = CarImage.objects.select_related('car').all()
        if options.get('car'):
            photos = photos.filter(car_id=options['car'])

        photos = photos.order_by('pk')
        total = photos.count()

        if options.get('dry_run'):
            self.stdout.write(f'Would process {total} photo(s).')
            for photo in photos:
                self.stdout.write(
                    f'  {photo.car} - {photo.image.name} '
                    f'({photo.image.size // 1024} KB)'
                )
            return

        done = 0
        failed = 0
        for photo in photos:
            try:
                if photo.reprocess():
                    done += 1
                else:
                    failed += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'Skipped {photo.pk}: no photo file on disk.'
                        )
                    )
            except Exception as exc:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(f'Could not process photo {photo.pk}: {exc}')
                )

        self.stdout.write(
            self.style.SUCCESS(f'Processed {done} photo(s), {failed} failed.')
        )
