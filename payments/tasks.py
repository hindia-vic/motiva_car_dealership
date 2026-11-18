"""Celery tasks for M-Pesa payments."""
from celery import shared_task


@shared_task
def check_pending_payments_task():
    """Run the callback fallback query over stale pending payments."""
    from django.core.management import call_command
    call_command('check_mpesa_payments')
    return 'done'
