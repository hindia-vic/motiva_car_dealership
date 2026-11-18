"""Upcoming-booking reminders for service visits, test drives and hires.

A daily task looks one day ahead, emails the customer once, and leaves a
``BookingReminder`` row so a restart (or two gunicorn workers with the same
beat schedule) cannot send the same reminder twice. Moving a booking to a new
date creates a new reminder for that date.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Appointment, BookingReminder, ServiceRecord

logger = logging.getLogger(__name__)


def _claim(kind, booking_id, reminder_date):
    """Record the intent to send, returning False if it was already sent."""
    try:
        with transaction.atomic():
            BookingReminder.objects.create(
                booking_type=kind,
                object_id=booking_id,
                reminder_date=reminder_date,
            )
    except IntegrityError:
        return False
    return True


def _send(kind, recipient, send, *args):
    """Send one reminder, logging failures without stopping the other jobs."""
    try:
        send(*args)
    except Exception:
        logger.exception('Failed to send %s booking reminder to %s', kind, recipient)
        return False
    return True


def send_booking_reminders(now=None):
    """Send tomorrow's reminders. Returns counts by booking type."""
    from .emails import send_appointment_reminder_email, send_service_booking_reminder_email
    from hiring.emails import send_hire_booking_reminder_email
    from hiring.models import HireBooking

    now = now or timezone.now()
    tomorrow = timezone.localdate(now) + timedelta(days=1)
    sent = {'service': 0, 'appointment': 0, 'hire': 0}

    service_bookings = ServiceRecord.objects.filter(
        status='scheduled', service_date__date=tomorrow,
    ).exclude(customer_email='')
    for booking in service_bookings:
        if _claim('service', booking.pk, tomorrow) and _send(
            'service', booking.customer_email,
            send_service_booking_reminder_email, booking,
        ):
            sent['service'] += 1

    appointments = Appointment.objects.filter(
        status='approved', preferred_date=tomorrow,
    ).exclude(customer_email='')
    for appointment in appointments:
        if _claim('appointment', appointment.pk, tomorrow) and _send(
            'appointment', appointment.customer_email,
            send_appointment_reminder_email, appointment,
        ):
            sent['appointment'] += 1

    hires = HireBooking.objects.filter(
        status='confirmed', start_date=tomorrow,
    ).exclude(customer_email='')
    for booking in hires:
        if _claim('hire', booking.pk, tomorrow) and _send(
            'hire', booking.customer_email,
            send_hire_booking_reminder_email, booking,
        ):
            sent['hire'] += 1

    sent['total'] = sum(sent.values())
    return sent
