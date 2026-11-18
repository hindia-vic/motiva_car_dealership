"""M-Pesa Daraja payment models."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class MpesaTransaction(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    PURPOSE_HIRE = 'hire'
    PURPOSE_LISTING = 'listing'
    PURPOSE_FINANCING = 'financing'
    PURPOSE_ORDER = 'order'

    PURPOSE_CHOICES = [
        (PURPOSE_HIRE, 'Hire Booking'),
        (PURPOSE_LISTING, 'Listing Request'),
        (PURPOSE_FINANCING, 'Financing Application'),
        (PURPOSE_ORDER, 'Order'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mpesa_transactions',
    )
    phone_number = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[])
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    reference = models.CharField(max_length=100, unique=True)

    checkout_request_id = models.CharField(max_length=100, blank=True, db_index=True)
    merchant_request_id = models.CharField(max_length=100, blank=True)
    mpesa_receipt_number = models.CharField(max_length=50, blank=True)
    transaction_date = models.CharField(max_length=50, blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.TextField(blank=True)

    # Link to related objects
    hire_booking = models.ForeignKey(
        'hiring.HireBooking', on_delete=models.SET_NULL, null=True, blank=True, related_name='mpesa_transactions'
    )
    listing_request = models.ForeignKey(
        'cars.ListingRequest', on_delete=models.SET_NULL, null=True, blank=True, related_name='mpesa_transactions'
    )
    order = models.ForeignKey(
        'cars.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='mpesa_transactions'
    )
    financing_application = models.ForeignKey(
        'cars.FinancingApplication', on_delete=models.SET_NULL, null=True, blank=True, related_name='mpesa_transactions'
    )

    raw_callback = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'M-Pesa Transaction'
        verbose_name_plural = 'M-Pesa Transactions'

    def __str__(self):
        return f"{self.reference} - {self.phone_number} - {self.amount} ({self.status})"

    def mark_success(self, receipt_number='', transaction_date='', raw=None):
        if self.status == self.STATUS_SUCCESS:
            return
        self.status = self.STATUS_SUCCESS
        self.mpesa_receipt_number = receipt_number or self.mpesa_receipt_number
        self.transaction_date = transaction_date or self.transaction_date
        self.completed_at = timezone.now()
        if raw is not None:
            self.raw_callback = raw
        self.save(update_fields=[
            'status', 'mpesa_receipt_number', 'transaction_date', 'completed_at', 'raw_callback', 'updated_at'
        ])

    def mark_failed(self, result_code=None, result_desc='', raw=None):
        # A late failure must never overwrite money we already have.
        if self.status == self.STATUS_SUCCESS:
            return
        self.status = self.STATUS_FAILED
        if result_code is not None:
            self.result_code = result_code
        self.result_desc = result_desc
        if raw is not None:
            self.raw_callback = raw
        self.completed_at = timezone.now()
        self.save(update_fields=[
            'status', 'result_code', 'result_desc', 'completed_at', 'raw_callback', 'updated_at'
        ])

    @property
    def is_success(self):
        return self.status == self.STATUS_SUCCESS

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING

    def related_object(self):
        """The order, booking, listing or application this payment is for."""
        return (
            self.order
            or self.hire_booking
            or self.listing_request
            or self.financing_application
        )

    def related_description(self):
        """A short human-readable description of what was paid for."""
        if self.order_id:
            return f'Order #{self.order_id}'
        if self.hire_booking_id:
            return f'Hire {self.hire_booking.reference}'
        if self.listing_request_id:
            return f'Listing {self.listing_request.reference}'
        if self.financing_application_id:
            return f'Financing application #{self.financing_application_id}'
        return '-'
