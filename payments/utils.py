"""M-Pesa payment utilities."""
import random
import string
from decimal import Decimal

from django.conf import settings
from django.urls import reverse

from .models import MpesaTransaction


def generate_payment_reference(prefix='MP'):
    stamp = __import__('django').utils.timezone.now().strftime('%Y%m%d%H%M%S')
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f'{prefix}-{stamp}-{suffix}'


def initiate_payment(request, phone_number, amount, purpose, reference, **links):
    from .mpesa import MpesaClient, MpesaError

    amount_decimal = Decimal(str(amount))
    ref = reference or generate_payment_reference()

    txn = MpesaTransaction.objects.create(
        user=request.user if request.user.is_authenticated else None,
        phone_number=phone_number,
        amount=amount_decimal,
        purpose=purpose,
        reference=ref,
        **links,
    )

    if not getattr(settings, 'MPESA_CONSUMER_KEY', ''):
        # In dev/test without credentials, mark as pending and let caller handle
        return txn, None, 'M-Pesa not configured. Contact staff to complete payment.'

    try:
        client = MpesaClient()
        result = client.stk_push(
            phone_number=phone_number,
            amount=amount_decimal,
            account_reference=ref,
            transaction_desc=f'{purpose} payment',
        )
        txn.checkout_request_id = result.get('CheckoutRequestID', '')
        txn.merchant_request_id = result.get('MerchantRequestID', '')
        txn.save(update_fields=['checkout_request_id', 'merchant_request_id', 'updated_at'])
        return txn, result, None
    except MpesaError as e:
        txn.mark_failed(result_desc=str(e))
        return txn, None, str(e)
