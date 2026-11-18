"""Send price-drop and back-in-stock alerts to interested customers.

Run regularly (e.g. hourly via cron / Task Scheduler) alongside
``check_saved_searches``:

    python manage.py send_car_alerts

Use ``--dry-run`` to preview what would be sent without emailing anyone.
"""
from django.core.management.base import BaseCommand

from cars.alerts import send_pending_alerts


class Command(BaseCommand):
    help = 'Email customers about price drops and vehicles back in stock'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be sent without sending or marking alerts',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        result = send_pending_alerts(dry_run=dry_run)

        prefix = '[dry-run] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Sent {result["price_emails"]} price-drop and '
            f'{result["stock_emails"]} back-in-stock alert(s) covering '
            f'{result["price_events"]} price change(s) and '
            f'{result["stock_events"]} restock(s).'
        ))
