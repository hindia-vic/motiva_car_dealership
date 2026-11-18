"""Ask Safaricom what happened to payments whose callback never arrived.

A callback can be lost (a network problem on Safaricom's side, or the site
being briefly unreachable). Without a fallback those payments would sit at
``pending`` for ever even though the customer's money moved.

Run it from cron / Task Scheduler:

    python manage.py check_mpesa_payments

or leave the Celery beat schedule to run it every ten minutes.
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from payments import services


class Command(BaseCommand):
    help = 'Query Safaricom for pending M-Pesa payments and apply the result'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes',
            type=int,
            default=None,
            help=(
                'Only query payments older than this many minutes '
                '(default: MPESA_QUERY_AFTER_MINUTES or 10).'
            ),
        )

    def handle(self, *args, **options):
        minutes = options['minutes']
        if minutes is None:
            minutes = getattr(settings, 'MPESA_QUERY_AFTER_MINUTES', 10)

        outcomes = {
            'success': 0, 'failed': 0, 'pending': 0,
            'error': 0, 'no_checkout_id': 0, 'already': 0,
        }
        queried = 0

        for txn in services.pending_transactions(older_than_minutes=minutes):
            txn, outcome = services.query_transaction(txn)
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            queried += 1

        if not queried:
            self.stdout.write('No pending payments to check.')
            return

        self.stdout.write(self.style.SUCCESS(
            f'Checked {queried} pending payment(s): '
            f'{outcomes["success"]} paid, {outcomes["failed"]} failed, '
            f'{outcomes["pending"]} still pending, {outcomes["error"]} errors.'
        ))
