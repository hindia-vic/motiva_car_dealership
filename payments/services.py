"""Business rules for M-Pesa payments.

The callback is deliberately thin: it parses the Safaricom payload and
hands it to this module. Everything that decides what a payment *means*
for an order, a listing, a hire booking or a financing application lives
here, so the same code can be reused by the status query fallback, the
management command and the staff reconciliation page.
"""

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from .models import MpesaTransaction
from .utils import initiate_payment

logger = logging.getLogger(__name__)

#: Salt for the signed token that lets a guest see their own payment page.
STATUS_TOKEN_SALT = 'payments.payment-status'

#: Salt for the signed token that lets a guest open their order's payment form.
ORDER_TOKEN_SALT = 'payments.order'

#: How long a payment-status link stays usable (30 days).
DEFAULT_STATUS_TOKEN_MAX_AGE = 60 * 60 * 24 * 30

#: Safaricom result codes that mean the customer did not pay.
FAILED_RESULT_CODES = {
    1,      # insufficient balance
    1001,   # unable to lock subscriber
    1019,   # transaction expired
    1032,   # cancelled by the customer
    1037,   # no response / timeout
    2001,   # wrong PIN
}


def _to_decimal(value):
    if value is None or value == '':
        return Decimal('0')
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _status_token_max_age():
    return int(getattr(
        settings, 'MPESA_STATUS_TOKEN_MAX_AGE', DEFAULT_STATUS_TOKEN_MAX_AGE,
    ))


# ---------------------------------------------------------------------------
# Signed links for guests
# ---------------------------------------------------------------------------

def payment_status_token(txn):
    """A signed, expiring token that authorises one payment-status page."""
    return signing.dumps(
        {'reference': txn.reference},
        salt=STATUS_TOKEN_SALT,
        compress=True,
    )


def read_status_token(token):
    """Return the transaction reference in a valid token, else ``None``."""
    if not token:
        return None
    try:
        data = signing.loads(
            token,
            salt=STATUS_TOKEN_SALT,
            max_age=_status_token_max_age(),
        )
    except signing.BadSignature:
        return None
    except signing.SignatureExpired:
        return None
    if not isinstance(data, dict):
        return None
    return data.get('reference')


def payment_status_url(txn, request=None):
    """The status page URL, including the guest's signed token."""
    path = reverse('payments:payment_status', args=[txn.reference])
    url = f'{path}?token={payment_status_token(txn)}'
    if request is not None:
        return request.build_absolute_uri(url)
    return url


def order_token(order):
    """A signed token that lets a guest come back and pay their deposit."""
    return signing.dumps({'order': order.pk}, salt=ORDER_TOKEN_SALT, compress=True)


def read_order_token(token):
    """Return the order id in a valid token, else ``None``."""
    if not token:
        return None
    try:
        data = signing.loads(
            token,
            salt=ORDER_TOKEN_SALT,
            max_age=_status_token_max_age(),
        )
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    return data.get('order')


def order_payment_url(order, request=None):
    """The deposit form URL, including the guest's signed token."""
    path = reverse('cars:order_pay_deposit', args=[order.pk])
    url = f'{path}?token={order_token(order)}'
    if request is not None:
        return request.build_absolute_uri(url)
    return url


# ---------------------------------------------------------------------------
# Starting a payment
# ---------------------------------------------------------------------------

def _already_settled(links):
    """Return an error message if the related object is already paid."""
    order = links.get('order')
    if order is not None and order.is_settled():
        return 'This order has already been paid in full.'

    listing = links.get('listing_request')
    if listing is not None and listing.is_settled():
        return 'The listing fee has already been settled.'

    booking = links.get('hire_booking')
    if booking is not None and booking.is_settled():
        return 'This hire booking has already been paid in full.'

    return None


def start_payment(request, phone_number, amount, purpose, reference=None, **links):
    """Create the transaction and send the STK push.

    Returns ``(transaction, result, error)`` exactly like
    :func:`payments.utils.initiate_payment`, but refuses to take money for
    something that is already settled or for a non-positive amount.
    """
    amount = _to_decimal(amount)
    if amount <= 0:
        return None, None, 'There is nothing to pay for this request.'

    settled_error = _already_settled(links)
    if settled_error:
        return None, None, settled_error

    phone_number = (phone_number or '').strip()
    if not phone_number:
        return None, None, 'Please give us the phone number to charge.'

    return initiate_payment(
        request,
        phone_number=phone_number,
        amount=amount,
        purpose=purpose,
        reference=reference,
        **links,
    )


# ---------------------------------------------------------------------------
# Applying a callback / query result
# ---------------------------------------------------------------------------

def _apply_to_related(txn, receipt_number='', paid_amount=None):
    """Update whatever the payment was for, now that the money is in."""
    reference = receipt_number or txn.reference
    paid_amount = _to_decimal(paid_amount or txn.amount)

    if txn.order_id:
        order = txn.order
        order.record_payment(paid_amount, reference=reference, at=txn.completed_at)
        try:
            from cars.emails import send_order_payment_receipt_email
            send_order_payment_receipt_email(order, txn)
        except Exception:
            logger.warning(
                'Could not send the order receipt for %s', txn.reference,
                exc_info=True,
            )
        try:
            from notifications.services import notify, notify_staff
            notify(
                order.user,
                'Deposit received',
                f'We have received KSh {paid_amount:,.2f} against order '
                f'#{order.id}. Our team will review it shortly.',
                obj=order,
                url=reverse('cars:my_activity'),
            )
            notify_staff(
                f'Deposit received for order #{order.id}',
                f'{order.customer_name} paid KSh {paid_amount:,.2f} against '
                f'{order.car}.',
                obj=order,
                url=reverse('cars:orders_list'),
            )
        except Exception:
            logger.warning(
                'Could not create notifications for %s', txn.reference,
                exc_info=True,
            )
        return

    if txn.listing_request_id:
        listing = txn.listing_request
        if listing.payment_status in ('paid', 'waived'):
            return
        if paid_amount >= listing.fee_amount:
            listing.payment_status = 'paid'
            listing.payment_reference = reference
            if not listing.payment_received_at:
                listing.payment_received_at = txn.completed_at or timezone.now()
            listing.save(update_fields=[
                'payment_status', 'payment_reference',
                'payment_received_at', 'updated_at',
            ])
            try:
                from cars.emails import send_listing_payment_receipt_email
                send_listing_payment_receipt_email(listing, txn)
            except Exception:
                logger.warning(
                    'Could not send the listing receipt for %s', txn.reference,
                    exc_info=True,
                )
        else:
            logger.warning(
                'Listing %s received %s against a fee of %s; leaving it unpaid.',
                listing.reference, paid_amount, listing.fee_amount,
            )
        return

    if txn.hire_booking_id:
        booking = txn.hire_booking
        if booking.payment_status == 'refunded':
            return
        received = (
            booking.mpesa_transactions
            .filter(status=MpesaTransaction.STATUS_SUCCESS)
            .aggregate(total=Sum('amount'))
            .get('total')
            or Decimal('0')
        )
        if received >= booking.total_due():
            booking.payment_status = 'paid'
        elif received > 0:
            booking.payment_status = 'partial'
        booking.payment_reference = reference
        if not booking.payment_received_at:
            booking.payment_received_at = txn.completed_at or timezone.now()
        booking.save(update_fields=[
            'payment_status', 'payment_reference',
            'payment_received_at', 'updated_at',
        ])
        try:
            from hiring.emails import send_hire_payment_receipt_email
            send_hire_payment_receipt_email(booking, txn)
        except Exception:
            logger.warning(
                'Could not send the hire receipt for %s', txn.reference,
                exc_info=True,
            )
        return

    if txn.financing_application_id:
        # Financing applications do not carry an online fee yet. Record the
        # money on the transaction so staff can see it during reconciliation.
        logger.info(
            'Payment %s received for financing application %s.',
            txn.reference, txn.financing_application_id,
        )


def apply_success(txn, receipt_number='', transaction_date='', raw=None, amount=None):
    """Mark a transaction successful and update the thing it paid for.

    The amount is checked against the requested amount before anything is
    marked paid: a callback claiming KSh 1 must never settle a KSh 3M
    transaction. Returns ``(transaction, outcome)`` where outcome is one of
    ``applied``, ``already`` or ``amount_mismatch``.
    """
    with transaction.atomic():
        txn = MpesaTransaction.objects.select_for_update().get(pk=txn.pk)

        if txn.status == MpesaTransaction.STATUS_SUCCESS:
            return txn, 'already'

        callback_amount = None
        if amount not in (None, ''):
            callback_amount = _to_decimal(amount)

        if callback_amount is not None and callback_amount < txn.amount:
            message = (
                f'Callback amount {callback_amount} is less than the '
                f'requested {txn.amount}; not marking as paid.'
            )
            logger.warning('Payment %s: %s', txn.reference, message)
            txn.result_desc = message
            if raw is not None:
                txn.raw_callback = raw
            txn.save(update_fields=['result_desc', 'raw_callback', 'updated_at'])
            return txn, 'amount_mismatch'

        txn.mark_success(
            receipt_number=str(receipt_number or ''),
            transaction_date=str(transaction_date or ''),
            raw=raw,
        )
        _apply_to_related(
            txn,
            receipt_number=str(receipt_number or ''),
            paid_amount=callback_amount or txn.amount,
        )
        return txn, 'applied'


def apply_failure(txn, result_code=None, result_desc='', raw=None):
    """Mark a transaction failed, unless it already succeeded."""
    with transaction.atomic():
        txn = MpesaTransaction.objects.select_for_update().get(pk=txn.pk)
        if txn.status == MpesaTransaction.STATUS_SUCCESS:
            return txn, 'already'
        txn.mark_failed(result_code=result_code, result_desc=result_desc, raw=raw)
        return txn, 'applied'


# ---------------------------------------------------------------------------
# Querying Safaricom when a callback is lost
# ---------------------------------------------------------------------------

def query_transaction(txn):
    """Ask Safaricom for the latest state of a pending transaction.

    Returns ``(transaction, outcome)`` where outcome is ``success``,
    ``failed``, ``pending``, ``already``, ``no_checkout_id`` or ``error``.
    """
    from .mpesa import MpesaClient, MpesaError

    if txn.status == MpesaTransaction.STATUS_SUCCESS:
        return txn, 'already'
    if not txn.checkout_request_id:
        return txn, 'no_checkout_id'

    try:
        result = MpesaClient().query_status(txn.checkout_request_id)
    except MpesaError as exc:
        logger.warning('Could not query payment %s: %s', txn.reference, exc)
        return txn, 'error'

    code = str(result.get('ResultCode', '')).strip()
    desc = result.get('ResultDesc', '')

    if code == '0':
        receipt = result.get('MpesaReceiptNumber', '')
        apply_success(
            txn,
            receipt_number=receipt,
            transaction_date=result.get('TransactionDate', ''),
            raw=result,
        )
        return txn, 'success'

    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        numeric_code = None

    if numeric_code in FAILED_RESULT_CODES:
        apply_failure(
            txn,
            result_code=numeric_code,
            result_desc=desc,
            raw=result,
        )
        return txn, 'failed'

    return txn, 'pending'


def pending_transactions(older_than_minutes=10):
    """Transactions still waiting for a callback after a given age."""
    cutoff = timezone.now() - timedelta(minutes=int(older_than_minutes))
    return (
        MpesaTransaction.objects
        .filter(
            status=MpesaTransaction.STATUS_PENDING,
            created_at__lte=cutoff,
            checkout_request_id__gt='',
        )
        .order_by('created_at')
    )
