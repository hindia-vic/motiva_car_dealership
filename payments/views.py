"""M-Pesa payment views."""
import json
import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from cars.exports import stream_csv
from cars.money import currency_code

from . import services
from .models import MpesaTransaction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Customer-facing
# ---------------------------------------------------------------------------

@require_http_methods(['GET'])
def payment_status(request, reference):
    """Show one payment.

    The owner and staff can always see it. A guest gets in with the signed
    token we put in the link after starting a payment - without that, a
    guest order or hire booking would have no way back to its own status.
    """
    txn = get_object_or_404(MpesaTransaction, reference=reference)

    is_owner = (
        txn.user_id
        and request.user.is_authenticated
        and txn.user_id == request.user.pk
    )
    is_staff = request.user.is_staff
    has_token = services.read_status_token(request.GET.get('token')) == txn.reference

    if not (is_owner or is_staff or has_token):
        return redirect('cars:home')

    return render(request, 'payments/payment_status.html', {
        'transaction': txn,
        'can_query': is_staff,
        'status_token': request.GET.get('token', ''),
    })


# ---------------------------------------------------------------------------
# Safaricom callback
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def mpesa_callback(request):
    """Receive the STK push result from Safaricom.

    Safaricom expects a 200 with ``ResultCode: 0`` for every callback it
    sends, even one we cannot match, otherwise it retries. Anything that
    goes wrong is logged rather than raised.
    """
    accepted = JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})
    try:
        body = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        logger.warning('M-Pesa callback with an unreadable body')
        return accepted

    try:
        callback = body.get('Body', {}).get('stkCallback', {})
        checkout_request_id = callback.get('CheckoutRequestID')
        result_code = callback.get('ResultCode')
        result_desc = callback.get('ResultDesc', '')

        logger.info(
            'M-Pesa callback for %s: ResultCode=%s %s',
            checkout_request_id, result_code, result_desc,
        )

        if not checkout_request_id:
            return accepted

        txn = MpesaTransaction.objects.filter(
            checkout_request_id=checkout_request_id
        ).first()
        if txn is None:
            logger.warning(
                'M-Pesa callback for unknown CheckoutRequestID %s',
                checkout_request_id,
            )
            return accepted

        try:
            numeric_code = int(result_code)
        except (TypeError, ValueError):
            numeric_code = None

        if numeric_code == 0:
            items = {}
            metadata = callback.get('CallbackMetadata', {}).get('Item', [])
            for item in metadata:
                name = item.get('Name')
                if name in ('MpesaReceiptNumber', 'TransactionDate', 'PhoneNumber', 'Amount'):
                    items[name] = item.get('Value')
            services.apply_success(
                txn,
                receipt_number=items.get('MpesaReceiptNumber', ''),
                transaction_date=items.get('TransactionDate', ''),
                raw=body,
                amount=items.get('Amount'),
            )
        else:
            services.apply_failure(
                txn,
                result_code=numeric_code,
                result_desc=result_desc,
                raw=body,
            )
    except Exception:
        logger.exception('Error processing M-Pesa callback')

    return accepted


# ---------------------------------------------------------------------------
# Staff reconciliation
# ---------------------------------------------------------------------------

def _staff_required(request):
    return request.user.is_authenticated and request.user.is_staff


def _filtered_transactions(request):
    """The transaction list, narrowed by the staff filters in the query string."""
    queryset = MpesaTransaction.objects.select_related(
        'user', 'order__car', 'hire_booking', 'listing_request',
        'financing_application',
    )

    status = request.GET.get('status', '').strip()
    if status:
        queryset = queryset.filter(status=status)

    purpose = request.GET.get('purpose', '').strip()
    if purpose:
        queryset = queryset.filter(purpose=purpose)

    search = request.GET.get('search', '').strip()
    if search:
        queryset = queryset.filter(
            Q(reference__icontains=search)
            | Q(phone_number__icontains=search)
            | Q(mpesa_receipt_number__icontains=search)
            | Q(checkout_request_id__icontains=search)
            | Q(order__customer_name__icontains=search)
            | Q(order__customer_email__icontains=search)
            | Q(hire_booking__reference__icontains=search)
            | Q(hire_booking__customer_name__icontains=search)
            | Q(listing_request__reference__icontains=search)
            | Q(listing_request__owner_name__icontains=search)
        )

    date_from = parse_date(request.GET.get('date_from', ''))
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)

    date_to = parse_date(request.GET.get('date_to', ''))
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    return queryset.order_by('-created_at')


def transactions_list(request):
    """Staff view: every M-Pesa transaction, with filters and totals."""
    if not _staff_required(request):
        return redirect('cars:home')

    queryset = _filtered_transactions(request)
    paginator = Paginator(queryset, 50)
    page = paginator.get_page(request.GET.get('page'))

    # Totals for the filter, not just the page on screen.
    collected = queryset.filter(
        status=MpesaTransaction.STATUS_SUCCESS
    ).aggregate(total=Sum('amount')).get('total') or 0

    filters = request.GET.copy()
    filters.pop('page', None)

    return render(request, 'payments/transactions_list.html', {
        'filter_query': filters.urlencode(),
        'page_obj': page,
        'transactions': page.object_list,
        'status_choices': MpesaTransaction.STATUS_CHOICES,
        'purpose_choices': MpesaTransaction.PURPOSE_CHOICES,
        'status_filter': request.GET.get('status', ''),
        'purpose_filter': request.GET.get('purpose', ''),
        'search': request.GET.get('search', ''),
        'date_from': request.GET.get('date_from', ''),
        'date_to': request.GET.get('date_to', ''),
        'collected': collected,
        'pending_count': queryset.filter(
            status=MpesaTransaction.STATUS_PENDING
        ).count(),
    })


@require_POST
def transaction_query(request, reference):
    """Staff view: ask Safaricom for the latest state of one transaction."""
    if not _staff_required(request):
        return redirect('cars:home')

    txn = get_object_or_404(MpesaTransaction, reference=reference)
    txn, outcome = services.query_transaction(txn)

    if outcome == 'success':
        messages.success(request, f'{txn.reference} is paid.')
    elif outcome == 'failed':
        messages.warning(request, f'{txn.reference} did not go through: {txn.result_desc}')
    elif outcome == 'already':
        messages.info(request, f'{txn.reference} was already marked successful.')
    elif outcome == 'no_checkout_id':
        messages.error(request, 'That transaction has no Safaricom checkout id to query.')
    elif outcome == 'error':
        messages.error(request, 'Safaricom could not be reached. Try again in a moment.')
    else:
        messages.info(request, f'{txn.reference} is still pending at Safaricom.')

    next_url = request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect('payments:transactions_list')


def transactions_export(request):
    """Staff view: download the filtered reconciliation list as CSV."""
    if not _staff_required(request):
        return redirect('cars:home')

    rows = (
        [
            txn.reference,
            txn.created_at.strftime('%Y-%m-%d %H:%M') if txn.created_at else '',
            txn.get_purpose_display(),
            txn.related_description(),
            txn.phone_number,
            txn.amount,
            txn.get_status_display(),
            txn.mpesa_receipt_number,
            txn.result_desc,
        ]
        for txn in _filtered_transactions(request)
    )
    return stream_csv(
        'mpesa-transactions.csv',
        ['Reference', 'Created', 'Purpose', 'For', 'Phone',
         f'Amount ({currency_code()})', 'Status', 'M-Pesa Receipt', 'Result'],
        rows,
    )
