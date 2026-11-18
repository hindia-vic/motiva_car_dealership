"""Delete traffic analytics rows that are older than the retention window.

Raw IP addresses are personal data, so the table is kept deliberately small.
Run this from a schedule (cron, Task Scheduler, a platform cron job) or by
hand:

    python manage.py purge_traffic_data --dry-run
    python manage.py purge_traffic_data --days 30
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from traffic.models import PageView


class Command(BaseCommand):
    help = 'Delete page views older than the traffic retention window.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help='Age in days of the rows to delete (default: TRAFFIC_RETENTION_DAYS).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be deleted without deleting anything.',
        )

    def handle(self, *args, **options):
        days = options.get('days') or getattr(settings, 'TRAFFIC_RETENTION_DAYS', 90)
        cutoff = timezone.now() - timedelta(days=days)

        stale = PageView.objects.filter(created_at__lt=cutoff)
        count = stale.count()

        if options.get('dry_run'):
            self.stdout.write(
                f'Would delete {count} page view(s) older than '
                f'{cutoff:%Y-%m-%d %H:%M} ({days} days).'
            )
            return

        stale.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f'Deleted {count} page view(s) older than {cutoff:%Y-%m-%d %H:%M}.'
            )
        )
