"""SMS notifications via Africa's Talking."""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def send_sms(phone_number, message):
    if not getattr(settings, 'SMS_ENABLED', False):
        logger.debug('SMS disabled, skipping to %s', phone_number)
        return False

    username = getattr(settings, 'AT_USERNAME', 'sandbox')
    api_key = getattr(settings, 'AT_API_KEY', '')
    sender_id = getattr(settings, 'AT_SENDER_ID', '')

    if not api_key:
        logger.debug('No AT API key configured')
        return False

    try:
        import africastalking

        africastalking.initialize(username, api_key)
        sms = africastalking.SMS
        kwargs = {}
        if sender_id:
            kwargs['from_'] = sender_id
        response = sms.send(message, [phone_number], **kwargs)
        logger.info('SMS sent to %s: %s', phone_number, response)
        return True
    except Exception as e:
        logger.exception('Failed to send SMS: %s', e)
        return False


def send_hire_booking_sms(booking):
    message = (
        f"Hi {booking.customer_name}, your hire request {booking.reference} for "
        f"{booking.hire_car} ({booking.start_date} to {booking.end_date}) has been received. "
        f"We'll confirm once payment and checks are complete."
    )
    return send_sms(booking.customer_phone, message)


def send_hire_booking_status_sms(booking):
    message = (
        f"Hi {booking.customer_name}, your hire booking {booking.reference} is now "
        f"{booking.get_status_display()}. Ref: {booking.reference}"
    )
    return send_sms(booking.customer_phone, message)


def send_inquiry_status_sms(inquiry):
    message = (
        f"Hi {inquiry.customer_name}, your inquiry for {inquiry.car} is now "
        f"{inquiry.get_status_display()}. Ref: #{inquiry.id}"
    )
    return send_sms(inquiry.customer_phone, message)
