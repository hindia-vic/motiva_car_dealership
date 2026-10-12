import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

logger = logging.getLogger(__name__)


def _send_notification(subject, body, request=None):
    """Send a plain-text email to the dealership notification address.

    Mail failures are logged but never raised, so a broken email setup never
    breaks a customer's inquiry/order submission.
    """
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEALERSHIP_NOTIFY_EMAIL],
            fail_silently=False,
        )
    except Exception:
        logger.warning("Failed to send notification email '%s'", subject, exc_info=True)


def _send_email(subject, body, to):
    """Send a plain-text email to an arbitrary recipient, failing soft."""
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [to],
            fail_silently=False,
        )
    except Exception:
        logger.warning("Failed to send email '%s' to %s", subject, to, exc_info=True)


def send_inquiry_notification(inquiry, request=None):
    """Notify staff of a new customer inquiry about a vehicle"""
    car = inquiry.car
    subject = f"[New Inquiry] {car.year} {car.make} {car.model}"
    lines = [
        f"A new inquiry has been submitted.",
        "",
        f"Vehicle:  {car.year} {car.make} {car.model}",
        f"VIN:      {car.vin}",
        f"Price:    ${car.asking_price}",
        "",
        f"Customer: {inquiry.customer_name}",
        f"Email:    {inquiry.customer_email}",
        f"Phone:    {inquiry.customer_phone}",
        "",
        f"Message:",
        inquiry.message,
    ]
    if request is not None:
        lines.append("")
        lines.append(f"Review this inquiry: {request.build_absolute_uri(reverse('cars:inquiries_list'))}")
    _send_notification(subject, "\n".join(lines), request)


def send_order_notification(order, request=None):
    """Notify staff of a new customer order for a vehicle"""
    car = order.car
    subject = f"[New Order] {car.year} {car.make} {car.model}"
    lines = [
        f"A new order has been submitted.",
        "",
        f"Vehicle:  {car.year} {car.make} {car.model}",
        f"VIN:      {car.vin}",
        f"Order Price: ${order.price}",
    ]
    if order.trade_in_value:
        lines.append(f"Trade-In: -${order.trade_in_value}")
    if order.down_payment:
        lines.append(f"Down Payment: ${order.down_payment}")
    lines.extend([
        f"Financing Needed: {'Yes' if order.financing_needed else 'No'}",
        "",
        f"Customer: {order.customer_name}",
        f"Email:    {order.customer_email}",
        f"Phone:    {order.customer_phone}",
        f"Address:  {order.customer_address}",
    ])
    if order.notes:
        lines.extend(["", "Notes:", order.notes])
    if request is not None:
        lines.append("")
        lines.append(f"Review this order: {request.build_absolute_uri(reverse('cars:orders_list'))}")
    _send_notification(subject, "\n".join(lines), request)


def send_appointment_notification(appointment, request=None):
    """Notify staff of a new test-drive appointment request"""
    car = appointment.car
    subject = f"[Test Drive Request] {car.year} {car.make} {car.model}"
    lines = [
        "A new test-drive appointment has been requested.",
        "",
        f"Vehicle:    {car.year} {car.make} {car.model}",
        f"VIN:        {car.vin}",
        "",
        f"Customer:   {appointment.customer_name}",
        f"Email:      {appointment.customer_email}",
        f"Phone:      {appointment.customer_phone}",
        f"Preferred:  {appointment.preferred_date} at {appointment.preferred_time}",
    ]
    if appointment.message:
        lines.extend(["", "Message:", appointment.message])
    if request is not None:
        lines.append("")
        lines.append(f"Review appointments: {request.build_absolute_uri(reverse('cars:appointments_list'))}")
    _send_notification(subject, "\n".join(lines), request)


def send_appointment_status_email(appointment):
    """Email the customer when their test-drive appointment is approved or rejected"""
    car = appointment.car
    vehicle = f"{car.year} {car.make} {car.model}"
    if appointment.status == 'approved':
        subject = "[Car Dealership] Your test drive is confirmed"
        body_lines = [
            f"Hi {appointment.customer_name},",
            "",
            f"Great news! Your test drive of the {vehicle} has been approved.",
            "",
            f"When:       {appointment.preferred_date} at {appointment.preferred_time}",
            f"Vehicle:    {vehicle}",
            "",
            "Please arrive a few minutes early with a valid driver's license.",
            "We look forward to seeing you!",
        ]
    elif appointment.status == 'rejected':
        subject = "[Car Dealership] Your test drive request"
        body_lines = [
            f"Hi {appointment.customer_name},",
            "",
            f"Unfortunately we are unable to schedule your test drive of the {vehicle} "
            "at the requested time.",
            "",
            "Please contact us to pick a different slot, and thank you for your interest.",
        ]
    else:
        return
    _send_email(subject, "\n".join(body_lines), appointment.customer_email)


def send_contact_notification(message):
    """Notify staff of a message submitted through the contact page"""
    subject = f"[Contact Message] {message.subject}"
    lines = [
        f"Name:    {message.name}",
        f"Email:   {message.email}",
        "",
        "Message:",
        message.message,
    ]
    _send_notification(subject, "\n".join(lines))


def send_testimonial_notification(testimonial):
    """Notify staff of a new customer review awaiting moderation"""
    subject = f"[New Review] {testimonial.customer_name} ({testimonial.rating}/5)"
    lines = [
        "A new customer review has been submitted and is awaiting approval.",
        "",
        f"Reviewer: {testimonial.customer_name}",
        f"Vehicle:  {testimonial.vehicle or 'General'}",
        f"Rating:   {testimonial.rating}/5",
        "",
        "Review:",
        testimonial.quote,
        "",
        "Approve it via the admin (Testimonials -> Is visible).",
    ]
    _send_notification(subject, "\n".join(lines))


def send_saved_search_alert_email(search, cars, request=None):
    """Email a subscriber about vehicles that match their saved search"""
    subject = f"[Car Alert] {len(cars)} matching vehicle{'s' if len(cars) != 1 else ''} for your search"
    lines = [
        "Hi there,",
        "",
        f"Here {'is a vehicle' if len(cars) == 1 else 'are the vehicles'} matching your saved search ({search.summary()}):",
        "",
    ]
    for car in cars:
        detail = f"  * {car.year} {car.make} {car.model} - ${car.asking_price}"
        if request is not None:
            detail += f"  ({request.build_absolute_uri(reverse('cars:car_detail', args=[car.pk]))})"
        lines.append(detail)
    lines.extend([
        "",
        "Visit us online or call to schedule a test drive!",
        "To manage your alerts, reply to this message or contact the dealership.",
    ])
    _send_email(subject, "\n".join(lines), search.email)