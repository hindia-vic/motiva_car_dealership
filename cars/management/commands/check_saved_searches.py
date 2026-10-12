"""Check saved searches and email subscribers about newly arrived matching cars.

Run regularly (e.g. hourly via cron / Task Scheduler):

    python manage.py check_saved_searches
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from cars.emails import send_saved_search_alert_email
from cars.models import SavedSearch


class Command(BaseCommand):
    help = 'Email subscribers about new vehicles matching their saved searches'

    def handle(self, *args, **options):
        now = timezone.now()
        alerts_sent = 0
        matches_sent = 0

        for search in SavedSearch.objects.filter(is_active=True).iterator():
            last_check = search.last_checked_at or search.created_at
            matches = list(search.match_cars(only_new_since=last_check)[:10])
            if matches:
                send_saved_search_alert_email(search, matches, None)
                alerts_sent += 1
                matches_sent += len(matches)
            search.last_checked_at = now
            search.save(update_fields=['last_checked_at'])

        self.stdout.write(self.style.SUCCESS(
            f'Checked saved searches: {alerts_sent} alert(s) sent covering '
            f'{matches_sent} vehicle(s).'
        ))