from django.contrib import admin, messages

from . import services
from .models import MpesaTransaction


@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'reference', 'phone_number', 'amount', 'purpose', 'status',
        'mpesa_receipt_number', 'checkout_request_id', 'created_at'
    ]
    list_filter = ['status', 'purpose', 'created_at']
    search_fields = [
        'reference', 'phone_number', 'mpesa_receipt_number',
        'checkout_request_id', 'merchant_request_id'
    ]
    readonly_fields = [
        'reference', 'phone_number', 'amount', 'purpose', 'user',
        'checkout_request_id', 'merchant_request_id', 'mpesa_receipt_number',
        'transaction_date', 'status', 'result_code', 'result_desc',
        'hire_booking', 'listing_request', 'order', 'financing_application',
        'raw_callback', 'created_at', 'updated_at', 'completed_at'
    ]
    date_hierarchy = 'created_at'
    actions = ['query_selected']

    @admin.action(description='Query selected pending payments with Safaricom')
    def query_selected(self, request, queryset):
        queried = 0
        for txn in queryset.filter(status=MpesaTransaction.STATUS_PENDING):
            services.query_transaction(txn)
            queried += 1
        self.message_user(
            request,
            f'Queried {queried} pending payment(s) with Safaricom.',
            messages.INFO,
        )
