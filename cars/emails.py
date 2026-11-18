import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from .money import format_money

logger = logging.getLogger(__name__)


def _brand_name():
    """Dealership name for email subjects/sign-offs, with a safe fallback."""
    from .models import DealershipInfo
    return DealershipInfo.display_name()


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
        f"Price:    {format_money(car.asking_price)}",
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
        f"Order Price: {format_money(order.price)}",
    ]
    if order.trade_in_value:
        lines.append(f"Trade-In: -{format_money(order.trade_in_value)}")
    if order.down_payment:
        lines.append(f"Down Payment: {format_money(order.down_payment)}")
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


def send_order_confirmation_email(order, request=None):
    """Send the customer their order summary and a link to pay the deposit."""
    car = order.car
    vehicle = f"{car.year} {car.make} {car.model}"
    subject = f"[{_brand_name()}] We have your order for the {vehicle}"

    lines = [
        f"Hi {order.customer_name},",
        "",
        f"Thank you for your order for the {vehicle}.",
        "",
        f"Order #:   {order.id}",
        f"Vehicle:   {vehicle}",
        f"Price:     {format_money(order.price)}",
    ]
    if order.trade_in_value:
        lines.append(f"Trade-in: -{format_money(order.trade_in_value)}")
        lines.append(f"Payable:   {format_money(order.amount_payable())}")

    deposit = order.deposit_due()
    if deposit and not order.is_deposit_paid():
        lines.extend([
            "",
            f"Deposit to reserve the car: {format_money(deposit)}",
            "Pay it online with M-Pesa here:",
        ])
        try:
            from payments import services as payment_services
            lines.append(payment_services.order_payment_url(order, request))
        except Exception:
            logger.warning('Could not build the order payment link', exc_info=True)
        lines.extend([
            "",
            "The order stays pending until our team has reviewed it - the "
            "deposit reserves the car, it does not confirm the sale.",
        ])
    elif deposit:
        lines.append("")
        lines.append("We have received your deposit. Our team will be in touch shortly.")

    lines.extend([
        "",
        "If you have any questions, just reply to this email.",
    ])
    _send_email(subject, "\n".join(lines), order.customer_email)


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
        subject = f"[{_brand_name()}] Your test drive is confirmed"
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
        subject = f"[{_brand_name()}] Your test drive request"
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


def send_service_booking_reminder_email(booking):
    """Remind a customer about a service visit booked for the next day."""
    when = timezone.localtime(booking.service_date)
    service = booking.get_service_type_display()
    vehicle = str(booking.car) if booking.car_id else None
    subject = f'[{_brand_name()}] Service reminder for {when:%d %b %Y}'
    lines = [
        f'Hi {booking.customer_name or "there"},',
        '',
        f'This is a reminder that your {service.lower()} appointment is tomorrow.',
        '',
        f'When:    {when:%A, %d %B %Y at %H:%M}',
        f'Service: {service}',
    ]
    if vehicle:
        lines.append(f'Vehicle: {vehicle}')
    if booking.description:
        lines.extend(['', 'Notes:', booking.description])
    lines.extend(['', 'Need to change it? Just reply to this email.'])
    lines.extend(_contact_lines())
    _send_email(subject, '\n'.join(lines), booking.customer_email)


def send_appointment_reminder_email(appointment):
    """Remind a customer about an approved test drive the next day."""
    car = appointment.car
    vehicle = f'{car.year} {car.make} {car.model}'
    subject = f'[{_brand_name()}] Test drive reminder for {appointment.preferred_date:%d %b %Y}'
    lines = [
        f'Hi {appointment.customer_name},',
        '',
        f'This is a reminder that your test drive of the {vehicle} is tomorrow.',
        '',
        f'When:    {appointment.preferred_date:%A, %d %B %Y} at {appointment.preferred_time:%H:%M}',
        f'Vehicle: {vehicle}',
        '',
        "Please bring a valid driver's license and arrive a few minutes early.",
    ]
    lines.extend(_contact_lines())
    _send_email(subject, '\n'.join(lines), appointment.customer_email)


def _contact_lines():
    """Return the dealership's address/phone/hours as a list of lines.

    Returns an empty list if the details can't be read, so a status email
    never fails just because the ContactInfo row is missing.
    """
    try:
        from .models import ContactInfo
        info = ContactInfo.get_solo()
    except Exception:
        return []
    lines = []
    if info.address:
        lines.append(info.address)
    if info.phone:
        lines.append(f"Phone: {info.phone}")
    if info.email:
        lines.append(f"Email: {info.email}")
    if info.hours:
        lines.append(f"Hours: {info.hours}")
    return lines


def send_order_status_email(order):
    """Email the customer when their order reaches a meaningful status.

    Only transitions a customer cares about are sent; other statuses return
    quietly so staff can move orders around internally without emailing.
    """
    car = order.car
    vehicle = f"{car.year} {car.make} {car.model}"

    if order.status == 'confirmed':
        subject = f"[{_brand_name()}] Order #{order.id} confirmed - {vehicle}"
        body_lines = [
            f"Hi {order.customer_name},",
            "",
            f"Good news - your order for the {vehicle} has been confirmed.",
            "",
            f"Order #:  {order.id}",
            f"Vehicle:  {vehicle}",
            f"Price:    {format_money(order.price)}",
            "",
            "Our team will be in touch shortly with the next steps.",
        ]
    elif order.status == 'processing':
        subject = f"[{_brand_name()}] Order #{order.id} is being prepared - {vehicle}"
        body_lines = [
            f"Hi {order.customer_name},",
            "",
            f"We're getting your {vehicle} ready.",
            "",
            f"Order #:  {order.id}",
            f"Vehicle:  {vehicle}",
            "",
            "We'll email you again as soon as it's ready for pickup.",
        ]
    elif order.status == 'ready_for_pickup':
        subject = f"[{_brand_name()}] Order #{order.id} is ready for pickup - {vehicle}"
        body_lines = [
            f"Hi {order.customer_name},",
            "",
            f"Great news - your {vehicle} is ready for pickup!",
            "",
            f"Order #:  {order.id}",
            f"Vehicle:  {vehicle}",
        ]
        contact = _contact_lines()
        if contact:
            body_lines.extend(["", "Pickup location:", *contact])
    elif order.status == 'completed':
        subject = f"[{_brand_name()}] Thank you for your purchase (Order #{order.id} - {vehicle})"
        body_lines = [
            f"Hi {order.customer_name},",
            "",
            f"Thank you for your purchase of the {vehicle}!",
            "",
            "We hope you enjoy your new vehicle. If you have any questions, "
            "just reply to this email or give us a call.",
        ]
    elif order.status == 'cancelled':
        subject = f"[{_brand_name()}] Order #{order.id} cancelled - {vehicle}"
        body_lines = [
            f"Hi {order.customer_name},",
            "",
            f"Your order for the {vehicle} has been cancelled.",
            "",
            "If this wasn't expected, or you'd like to explore other options, "
            "please contact us - we're happy to help.",
        ]
    else:
        return

    _send_email(subject, "\n".join(body_lines), order.customer_email)


def send_order_deposit_reminder_email(order):
    """Remind a customer that their order is still waiting on the deposit."""
    car = order.car
    vehicle = f"{car.year} {car.make} {car.model}"
    subject = (
        f"[{_brand_name()}] Your order #{order.id} is waiting on a deposit "
        f"- {vehicle}"
    )
    body_lines = [
        f"Hi {order.customer_name},",
        "",
        f"We're holding your order for the {vehicle}.",
        "",
        f"Order #:  {order.id}",
        f"Vehicle:  {vehicle}",
        f"Deposit:  {format_money(order.deposit_due())}",
        "",
        "Pay the deposit online from your order page, or reply to this email "
        "and we'll help you finish it.",
        "",
        "If you've changed your mind, just let us know and we'll release the "
        "vehicle.",
    ]
    contact = _contact_lines()
    if contact:
        body_lines.extend(["", "Need a hand?", *contact])
    _send_email(subject, "\n".join(body_lines), order.customer_email)


def send_inquiry_status_email(inquiry):
    """Email the customer when their inquiry reaches a meaningful status.

    Only 'contacted' and 'interested' are customer-facing; internal statuses
    (new, not_interested, closed) return quietly.
    """
    car = inquiry.car
    vehicle = f"{car.year} {car.make} {car.model}"

    if inquiry.status == 'contacted':
        subject = f"[{_brand_name()}] We received your inquiry about the {vehicle}"
        body_lines = [
            f"Hi {inquiry.customer_name},",
            "",
            f"Thanks for your interest in the {vehicle}. One of our team members "
            "has your inquiry and will reach out to you shortly.",
            "",
            "If you'd like to talk sooner, just reply to this email or give us a call.",
        ]
    elif inquiry.status == 'interested':
        subject = f"[{_brand_name()}] Let's take the next step on the {vehicle}"
        body_lines = [
            f"Hi {inquiry.customer_name},",
            "",
            f"We're glad you're interested in the {vehicle}!",
            "",
            "Let's take the next step - whether that's a test drive, more details, "
            "or a trade-in estimate. Reply to this email or call us and we'll set it up.",
        ]
    else:
        return

    _send_email(subject, "\n".join(body_lines), inquiry.customer_email)


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


def send_listing_request_notification(listing_request, request=None):
    """Notify staff of a new request to list a customer's car on the website."""
    subject = f"[Listing Request] {listing_request.vehicle_description()} ({listing_request.reference})"
    lines = [
        "A customer has asked us to list their car on the website.",
        "",
        f"Reference: {listing_request.reference}",
        f"Vehicle:   {listing_request.vehicle_description()}",
        f"VIN:       {listing_request.vin}",
        f"Year:      {listing_request.year}",
        f"Mileage:   {listing_request.mileage:,} km",
        f"Asking:    {format_money(listing_request.asking_price)}",
        f"Fee:       {format_money(listing_request.fee_amount)}",
        "",
        f"Owner:     {listing_request.owner_name}",
        f"Email:     {listing_request.owner_email}",
        f"Phone:     {listing_request.owner_phone}",
        f"Logbook:   {listing_request.logbook_number or 'not given'}",
        "",
        "The car and the logbook both have to be verified, and the fee "
        "recorded, before the listing can be published.",
    ]
    if listing_request.description:
        lines.extend(["", "Owner's description:", listing_request.description])
    if request is not None:
        lines.append("")
        lines.append(
            "Review this request: "
            f"{request.build_absolute_uri(reverse('cars:listing_request_review', args=[listing_request.pk]))}"
        )
    _send_notification(subject, "\n".join(lines), request)


def send_listing_request_status_email(listing_request, car=None):
    """Email the owner when their listing request moves on.

    Only the statuses the owner can act on are sent; internal statuses
    ('submitted', 'under_review') return quietly.
    """
    vehicle = listing_request.vehicle_description()
    fee = format_money(listing_request.fee_amount)

    if listing_request.status == 'awaiting_documents':
        subject = f"[{_brand_name()}] We need more details for your {vehicle}"
        body_lines = [
            f"Hi {listing_request.owner_name},",
            "",
            f"Thank you for asking us to list your {vehicle}.",
            "",
            "We need a little more from you before we can go ahead:",
            "",
            "  * a clear photo of the logbook's front page, showing the owner's "
            "name and the logbook number;",
            "  * at least one clear photo of the car.",
            "",
            f"Your request reference is {listing_request.reference}.",
            "Reply to this email or sign in to add the missing items.",
        ]
    elif listing_request.status == 'awaiting_payment':
        subject = f"[{_brand_name()}] Listing fee due for your {vehicle}"
        body_lines = [
            f"Hi {listing_request.owner_name},",
            "",
            f"Your {vehicle} has passed our checks and is ready to go on the website.",
            "",
            f"The listing fee is {fee}. Please pay it by M-Pesa or bank transfer "
            "and send us the reference so we can publish your car.",
            "",
            f"Your request reference is {listing_request.reference}.",
            "Reply to this email with the payment reference and we will take it "
            "from there.",
        ]
    elif listing_request.status == 'listed':
        subject = f"[{_brand_name()}] Your {vehicle} is now listed on our website"
        body_lines = [
            f"Hi {listing_request.owner_name},",
            "",
            f"Good news - your {vehicle} is now live on our website.",
            "",
            f"Reference: {listing_request.reference}",
            f"Price:     {format_money(listing_request.asking_price)}",
        ]
        if car is not None:
            link = _car_link(car)
            if link:
                body_lines.extend(["", f"View it here: {link}"])
        body_lines.extend([
            "",
            "Buyers can now find your car and get in touch. We will let you know "
            "as soon as someone is interested.",
        ])
    elif listing_request.status == 'rejected':
        subject = f"[{_brand_name()}] About your listing request for the {vehicle}"
        body_lines = [
            f"Hi {listing_request.owner_name},",
            "",
            f"Thank you for asking us to list your {vehicle}.",
            "",
            "Unfortunately we are not able to go ahead with this one.",
        ]
        if listing_request.rejection_reason:
            body_lines.extend(["", "Reason:", listing_request.rejection_reason])
        body_lines.extend([
            "",
            "If you would like to talk it through, or if you have more "
            "information that might change our mind, just reply to this email.",
        ])
    else:
        return

    _send_email(subject, "\n".join(body_lines), listing_request.owner_email)


def send_order_payment_receipt_email(order, transaction):
    """Send the customer a receipt for a payment received against an order."""
    car = order.car
    vehicle = f"{car.year} {car.make} {car.model}"
    reference = transaction.mpesa_receipt_number or transaction.reference
    subject = f"[{_brand_name()}] Payment received - Order #{order.id}"

    lines = [
        f"Hi {order.customer_name},",
        "",
        f"Thank you - we have received your payment for the {vehicle}.",
        "",
        f"Order #:   {order.id}",
        f"Vehicle:   {vehicle}",
        f"Amount:    {format_money(transaction.amount)}",
        f"Reference: {reference}",
        f"Paid so far: {format_money(order.amount_paid)}",
        f"Balance:     {format_money(order.balance_due())}",
    ]
    if order.is_deposit_paid() and not order.is_settled():
        lines.extend([
            "",
            "Your deposit is in and the car is being held for you. The order "
            "stays pending until our team has reviewed it - the deposit does "
            "not confirm the sale on its own.",
        ])
    elif order.is_settled():
        lines.extend([
            "",
            "Your order is now paid in full. Our team will be in touch about "
            "collecting the car.",
        ])

    lines.extend([
        "",
        "If anything above looks wrong, just reply to this email.",
    ])
    _send_email(subject, "\n".join(lines), order.customer_email)


def send_listing_payment_receipt_email(listing_request, transaction):
    """Send the owner a receipt for the listing fee."""
    vehicle = listing_request.vehicle_description()
    reference = transaction.mpesa_receipt_number or transaction.reference
    subject = f"[{_brand_name()}] Listing fee received - {listing_request.reference}"

    lines = [
        f"Hi {listing_request.owner_name},",
        "",
        f"Thank you - we have received the listing fee for your {vehicle}.",
        "",
        f"Reference:  {listing_request.reference}",
        f"Amount:     {format_money(transaction.amount)}",
        f"M-Pesa ref: {reference}",
        "",
        "We will finish checking the car and the logbook and let you know as "
        "soon as your listing is live.",
    ]
    _send_email(subject, "\n".join(lines), listing_request.owner_email)


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
        detail = f"  * {car.year} {car.make} {car.model} - {format_money(car.asking_price)}"
        if request is not None:
            detail += f"  ({request.build_absolute_uri(reverse('cars:car_detail', args=[car.pk]))})"
        lines.append(detail)
    lines.extend([
        "",
        "Visit us online or call to schedule a test drive!",
        "To manage your alerts, reply to this message or contact the dealership.",
    ])
    _send_email(subject, "\n".join(lines), search.email)


def _car_link(car, request=None):
    """Absolute URL to a car's detail page, or '' if we can't build one."""
    path = reverse('cars:car_detail', args=[car.pk])
    if request is not None:
        return request.build_absolute_uri(path)
    base = getattr(settings, 'SITE_BASE_URL', '').rstrip('/')
    return f'{base}{path}' if base else ''


def send_price_drop_email(email, car, old_price, new_price, saved_price=None, request=None):
    """Email a customer that a car they care about dropped in price."""
    vehicle = f"{car.year} {car.make} {car.model}"
    subject = f"[Car Alert] Price drop: {vehicle}"
    lines = [
        "Hi there,",
        "",
        "Good news - the price of a vehicle you are watching just dropped.",
        "",
        f"Vehicle:  {vehicle}",
        f"Was:      {format_money(old_price)}",
        f"Now:      {format_money(new_price)}",
    ]

    if saved_price is not None and saved_price > new_price:
        lines.append(
            f"You saved it at {format_money(saved_price)}"
            f" - that's {format_money(saved_price - new_price)} off."
        )

    link = _car_link(car, request)
    if link:
        lines.extend(["", f"View it here: {link}"])

    lines.extend([
        "",
        "Visit us online or call to schedule a test drive!",
        "You can turn these alerts off from the My Account page.",
    ])
    _send_email(subject, "\n".join(lines), email)


def send_back_in_stock_email(email, car, request=None):
    """Email a customer that a car they care about is available again."""
    vehicle = f"{car.year} {car.make} {car.model}"
    subject = f"[Car Alert] Back in stock: {vehicle}"
    lines = [
        "Hi there,",
        "",
        "A vehicle you are watching is available again.",
        "",
        f"Vehicle:  {vehicle}",
        f"Price:    {format_money(car.asking_price)}",
    ]

    link = _car_link(car, request)
    if link:
        lines.extend(["", f"View it here: {link}"])

    lines.extend([
        "",
        "Visit us online or call to schedule a test drive!",
        "You can turn these alerts off from the My Account page.",
    ])
    _send_email(subject, "\n".join(lines), email)


def send_financing_notification(application, request=None):
    """Notify the finance team that a customer has applied for finance."""
    vehicle = application.vehicle_label() or 'a vehicle'
    subject = f"[Financing] {application.customer_name} - {vehicle} ({application.reference})"
    lines = [
        "A customer has applied for vehicle financing.",
        "",
        f"Reference:   {application.reference}",
        f"Vehicle:     {vehicle}",
        f"Price:       {format_money(application.price)}",
        f"Deposit:     {format_money(application.deposit_amount)}",
        f"Trade-in:    {format_money(application.trade_in_value)}",
        f"Borrowing:   {format_money(application.requested_amount)}",
        f"Term:        {application.loan_term_months} months",
        f"Rate:        {application.interest_rate}% p.a.",
        f"Monthly:     {format_money(application.estimated_monthly)}",
        "",
        f"Customer:    {application.customer_name}",
        f"Email:       {application.customer_email}",
        f"Phone:       {application.customer_phone}",
        f"Employment:  {application.get_employment_status_display()}",
    ]
    if application.employer_name:
        lines.append(f"Employer:    {application.employer_name}")
    if application.job_title:
        lines.append(f"Job title:   {application.job_title}")
    lines.extend([
        f"Income:      {format_money(application.monthly_income)} a month",
        f"Commitments: {format_money(application.monthly_expenses)} a month",
        "",
        "Nothing is approved automatically: a decision has to be recorded "
        "by hand.",
    ])
    if request is not None:
        lines.append("")
        lines.append(
            "Review this application: "
            f"{request.build_absolute_uri(reverse('cars:financing_application_review', args=[application.pk]))}"
        )
    _send_notification(subject, "\n".join(lines), request)


def send_financing_status_email(application):
    """Email the customer when their financing application is decided."""
    vehicle = application.vehicle_label() or 'the vehicle'

    if application.status == 'approved':
        amount = application.approved_amount or application.requested_amount
        months = application.approved_term_months or application.loan_term_months
        subject = f"[{_brand_name()}] Your financing application has been approved"
        body_lines = [
            f"Hi {application.customer_name},",
            "",
            f"Good news - we can finance your {vehicle}.",
            "",
            f"Reference:   {application.reference}",
            f"Amount:      {format_money(amount)}",
            f"Term:        {months} months",
        ]
        if application.estimated_monthly:
            body_lines.append(
                f"Estimated monthly repayment: {format_money(application.estimated_monthly)}"
            )
        body_lines.extend([
            "",
            "This is an indication based on the figures you gave us; the final "
            "agreement is signed at the dealership. Reply to this email to arrange "
            "a time to come in.",
        ])
    elif application.status == 'declined':
        subject = f"[{_brand_name()}] About your financing application"
        body_lines = [
            f"Hi {application.customer_name},",
            "",
            f"Thank you for your application to finance your {vehicle}.",
            "",
            "Unfortunately we are not able to approve it on the figures you gave us.",
        ]
        if application.decline_reason:
            body_lines.extend(["", "Reason:", application.decline_reason])
        body_lines.extend([
            "",
            "If your circumstances change, or if you would like to talk it "
            "through, just reply to this email.",
        ])
    else:
        return

    _send_email(subject, "\n".join(body_lines), application.customer_email)