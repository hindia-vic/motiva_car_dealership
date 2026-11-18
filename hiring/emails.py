"""Emails for car hire and tours & travel.

Two kinds of email go out:

* staff are told about a new booking request, so they can pick it up;
* the customer is told when their booking is confirmed, rejected,
  cancelled or completed.

Mail failures are logged but never raised, so a broken email setup never
breaks a booking.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from cars.money import format_money

logger = logging.getLogger(__name__)


def _brand_name():
    """Dealership name for email subjects/sign-offs, with a safe fallback."""
    from cars.models import DealershipInfo
    return DealershipInfo.display_name()


def _send_notification(subject, body):
    """Send a plain-text email to the dealership notification address."""
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
    """Send a plain-text email to the customer, failing soft."""
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


def send_hire_booking_notification(booking, request=None):
    """Notify staff of a new request to hire a car."""
    car = booking.hire_car
    subject = f"[Hire Request] {car.year} {car.make} {car.model} ({booking.reference})"
    lines = [
        "A customer has asked to hire a car.",
        "",
        f"Reference:  {booking.reference}",
        f"Vehicle:    {car.year} {car.make} {car.model}",
        f"Service:    {booking.service_label}",
        f"Dates:      {booking.start_date:%d %b %Y} to {booking.end_date:%d %b %Y} ({booking.days} days)",
        f"Quoted:     {format_money(booking.quoted_price)}",
        f"Deposit:    {format_money(booking.security_deposit)} (security, refundable)",
        "",
        f"Customer:   {booking.customer_name}",
        f"Email:      {booking.customer_email}",
        f"Phone:      {booking.customer_phone}",
        f"Passengers: {booking.passengers}",
        "",
        f"Licence:    {booking.licence_number or 'not needed for a tour'}",
        f"ID number:  {booking.id_number}",
    ]
    extras = list(booking.extras.all())
    if extras:
        lines.extend(["", "Extras:"])
        for extra in extras:
            lines.append(
                f"  {extra.quantity} x {extra.name}: "
                f"{format_money(extra.line_total(booking.days))}"
            )
        lines.append(f"  Extras total: {format_money(booking.extras_total())}")
    if booking.pickup_location:
        lines.append(f"Pick-up:    {booking.pickup_location}")
    if booking.destination:
        lines.append(f"Going to:   {booking.destination}")
    if booking.notes:
        lines.extend(["", "Notes:", booking.notes])
    if request is not None:
        lines.append("")
        lines.append(
            "Review this booking: "
            f"{request.build_absolute_uri(reverse('hiring:staff_hire_booking_review', args=[booking.pk]))}"
        )
    _send_notification(subject, "\n".join(lines))


def send_hire_booking_status_email(booking):
    """Email the customer when their booking changes.

    Only the states the customer can act on are sent; the internal
    'pending' state returns quietly.
    """
    car = booking.hire_car
    vehicle = f"{car.year} {car.make} {car.model}"

    if booking.status == 'confirmed':
        subject = f"[{_brand_name()}] Your hire of the {vehicle} is confirmed"
        body_lines = [
            f"Hi {booking.customer_name},",
            "",
            f"Your request to hire the {vehicle} is confirmed.",
            "",
            f"Reference:  {booking.reference}",
            f"Service:    {booking.service_label}",
            f"Dates:      {booking.start_date:%d %b %Y} to {booking.end_date:%d %b %Y} ({booking.days} days)",
            f"Hire:       {format_money(booking.hire_total())}",
        ]
        extras = list(booking.extras.all())
        for extra in extras:
            body_lines.append(
                f"  {extra.quantity} x {extra.name}: "
                f"{format_money(extra.line_total(booking.days))}"
            )
        if booking.security_deposit:
            body_lines.append(
                f"Deposit:    {format_money(booking.security_deposit)} "
                "(refundable when the car comes back)"
            )
        body_lines.append(f"Total due:  {format_money(booking.total_due())}")
        if booking.driver_name:
            body_lines.append(f"Your driver: {booking.driver_name}")
        body_lines.extend([
            "",
            "Please pay by M-Pesa or bank transfer and send us the reference "
            "so we can settle the booking before you collect the car.",
        ])
    elif booking.status == 'rejected':
        subject = f"[{_brand_name()}] About your hire request for the {vehicle}"
        body_lines = [
            f"Hi {booking.customer_name},",
            "",
            f"Thank you for asking to hire the {vehicle}.",
            "",
            "Unfortunately we are not able to go ahead with this one.",
        ]
        if booking.rejection_reason:
            body_lines.extend(["", "Reason:", booking.rejection_reason])
        body_lines.extend([
            "",
            "If you would like to talk it through, or if there are other dates "
            "that would work, just reply to this email.",
        ])
    elif booking.status == 'cancelled':
        subject = f"[{_brand_name()}] Your hire of the {vehicle} has been cancelled"
        body_lines = [
            f"Hi {booking.customer_name},",
            "",
            f"The booking for the {vehicle} has been cancelled.",
            "",
            f"Reference: {booking.reference}",
        ]
        if booking.staff_notes:
            body_lines.extend(["", booking.staff_notes])
        body_lines.extend([
            "",
            "If that was not what you expected, reply to this email and we "
            "will sort it out.",
        ])
    elif booking.status == 'completed':
        subject = f"[{_brand_name()}] Thank you for hiring the {vehicle}"
        body_lines = [
            f"Hi {booking.customer_name},",
            "",
            f"Thank you for hiring the {vehicle}. We hope the trip went well.",
            "",
            f"Reference: {booking.reference}",
            f"Days hired: {booking.days}",
        ]
        if booking.is_settled():
            body_lines.append(f"Paid:      {format_money(booking.hire_total())}")
        else:
            body_lines.append(
                f"Outstanding: {format_money(booking.hire_total())}"
            )
        if booking.deposit_received_at:
            if booking.deposit_refunded_at:
                body_lines.append(
                    f"Deposit:   {format_money(booking.deposit_to_refund())} refunded"
                    + (
                        f", {format_money(booking.deposit_retained)} kept"
                        if booking.deposit_retained else ""
                    )
                )
            else:
                body_lines.append(
                    f"Deposit:   {format_money(booking.deposit_to_refund())} "
                    "to be refunded"
                )
        body_lines.extend([
            "",
            "We would be glad to book the car for you again.",
        ])
    else:
        return

    _send_email(subject, "\n".join(body_lines), booking.customer_email)


def send_hire_payment_receipt_email(booking, transaction):
    """Send the customer a receipt for a payment received against a booking."""
    car = booking.hire_car
    vehicle = f"{car.year} {car.make} {car.model}"
    reference = transaction.mpesa_receipt_number or transaction.reference
    subject = f"[{_brand_name()}] Payment received - {booking.reference}"

    lines = [
        f"Hi {booking.customer_name},",
        "",
        f"Thank you - we have received your payment for the {vehicle}.",
        "",
        f"Reference:  {booking.reference}",
        f"Amount:     {format_money(transaction.amount)}",
        f"M-Pesa ref: {reference}",
        f"Total due:  {format_money(booking.total_due())}",
    ]
    if booking.is_settled():
        lines.extend([
            "",
            "Your booking is now paid in full. We look forward to seeing you.",
        ])
    else:
        lines.extend([
            "",
            "There is still a balance outstanding. You can pay the rest "
            "through your booking page.",
        ])
    lines.extend([
        "",
        "If anything above looks wrong, just reply to this email.",
    ])
    _send_email(subject, "\n".join(lines), booking.customer_email)


def send_hire_booking_reminder_email(booking):
    """Remind a customer that a confirmed hire starts the next day."""
    vehicle = str(booking.hire_car)
    subject = f"[{_brand_name()}] Hire reminder - {booking.reference}"
    lines = [
        f"Hi {booking.customer_name},",
        "",
        f"This is a reminder that your {booking.service_label.lower()} of the "
        f"{vehicle} starts tomorrow.",
        "",
        f"Reference:  {booking.reference}",
        f"Collect:    {booking.start_date:%A, %d %B %Y}",
        f"Return:     {booking.end_date:%A, %d %B %Y}",
        f"Vehicle:    {vehicle}",
    ]
    if booking.pickup_location:
        lines.append(f"Pickup:     {booking.pickup_location}")
    lines.extend([
        "",
        "Please bring your ID and driving licence when you collect the car.",
        "If your plans have changed, just reply to this email.",
    ])
    _send_email(subject, "\n".join(lines), booking.customer_email)
