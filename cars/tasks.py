from celery import shared_task

from django.core.mail import send_mail
from django.conf import settings


@shared_task
def send_email_task(subject, message, from_email, recipient_list, html_message=None):
    send_mail(subject, message, from_email or settings.DEFAULT_FROM_EMAIL, recipient_list, html_message=html_message)


@shared_task
def send_car_alerts_task():
    from cars.alerts import send_pending_alerts
    return send_pending_alerts()


@shared_task
def check_saved_searches_task():
    from django.core.management import call_command
    call_command('check_saved_searches')
    return 'done'


@shared_task
def purge_traffic_data_task(days=None):
    from django.core.management import call_command
    kwargs = {}
    if days:
        kwargs['days'] = days
    call_command('purge_traffic_data', **kwargs)
    return 'done'


@shared_task
def send_lead_reminders_task():
    """Nudge owners about follow-ups and staff about unowned leads."""
    from cars.leads import send_lead_reminders
    return send_lead_reminders()


@shared_task
def send_order_deposit_reminders_task():
    """Remind customers whose order is still waiting on the deposit."""
    from cars.orders import send_deposit_reminders
    return send_deposit_reminders()


@shared_task
def send_booking_reminders_task():
    """Email customers about service visits, test drives and hires tomorrow."""
    from cars.bookings import send_booking_reminders
    return send_booking_reminders()


@shared_task
def backup_database_task():
    """Snapshot the database and prune copies past the retention window."""
    from django.core.management import call_command
    call_command('backup_db')
    return 'done'
