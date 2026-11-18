from simple_history.models import HistoricalRecords
import logging
import random
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from urllib.parse import quote

from .tradein import BODY_TYPES as TRADE_IN_BODY_TYPES
from .tradein import CONDITION_CHOICES as TRADE_IN_CONDITION_CHOICES
from .money import format_money
from .listing import DEFAULT_LISTING_FEE
from .financing import DEFAULT_INTEREST_RATE, LOAN_TERMS
from .deposits import amount_payable as order_amount_payable
from .deposits import order_deposit

#: Body styles a customer can say their trade-in is.
TRADE_IN_BODY_TYPE_CHOICES = [
    (value, value.replace('_', ' ').title()) for value in TRADE_IN_BODY_TYPES
]

logger = logging.getLogger(__name__)


class ConversionTracking(models.Model):
    """Records where a conversion came from.

    Every lead, order and test drive carries a copy of the anonymous
    visitor token and of the source the visitor arrived from. The values
    are copied rather than looked up later, because page views are pruned
    after the retention window and the history has to outlive that.
    """

    visitor_id = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Anonymous visitor token, copied from the tracking cookie",
    )
    source = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Where the visitor came from, e.g. Google",
    )

    class Meta:
        abstract = True


def upload_to_cars(instance, filename):
    return f"cars/car_{instance.car_id}/{filename}"


def upload_to_cars_thumbnails(instance, filename):
    return f"cars/car_{instance.car_id}/thumbs/{filename}"


class Branch(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10, unique=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Car(models.Model):
    history = HistoricalRecords()
    """Model representing a car in the dealership"""
    CONDITION_CHOICES = [
        ('new', 'New'),
        ('used', 'Used'),
        ('certified', 'Certified Pre-Owned'),
    ]
    
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('sold', 'Sold'),
        ('reserved', 'Reserved'),
        ('maintenance', 'In Maintenance'),
    ]

    #: Statuses shown on the public inventory pages. Vehicles that are
    #: reserved (someone is negotiating) or in maintenance are deliberately
    #: not advertised; sold vehicles stay visible so the page a visitor
    #: already has open does not turn into a 404.
    PUBLIC_STATUSES = ('available', 'sold')

    #: Bootstrap badge class per status.
    STATUS_BADGE_CLASSES = {
        'available': 'bg-success',
        'sold': 'bg-secondary',
        'reserved': 'bg-warning text-dark',
        'maintenance': 'bg-info text-dark',
    }

    # Basic Information
    make = models.CharField(max_length=100, help_text="Vehicle manufacturer")
    model = models.CharField(max_length=100, help_text="Vehicle model")
    year = models.IntegerField(validators=[MinValueValidator(1900)])
    vin = models.CharField(max_length=17, unique=True, help_text="Vehicle Identification Number")
    
    # Physical Characteristics
    color = models.CharField(max_length=50)
    body_type = models.CharField(max_length=50, choices=[
        ('sedan', 'Sedan'),
        ('suv', 'SUV'),
        ('truck', 'Truck'),
        ('coupe', 'Coupe'),
        ('hatchback', 'Hatchback'),
        ('wagon', 'Wagon'),
        ('van', 'Van'),
        ('convertible', 'Convertible'),
    ])
    transmission = models.CharField(max_length=20, choices=[
        ('manual', 'Manual'),
        ('automatic', 'Automatic'),
        ('cvt', 'CVT'),
    ])
    fuel_type = models.CharField(max_length=20, choices=[
        ('gasoline', 'Gasoline'),
        ('diesel', 'Diesel'),
        ('hybrid', 'Hybrid'),
        ('electric', 'Electric'),
    ])
    
    # Performance
    mileage = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    engine_size = models.CharField(max_length=20, blank=True, help_text="e.g., 3.0L")
    horsepower = models.IntegerField(null=True, blank=True)
    
    # Pricing
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    asking_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    
    # Status and Condition
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='used')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available', db_index=True)
    
    # Features
    air_conditioning = models.BooleanField(default=True)
    power_steering = models.BooleanField(default=True)
    power_windows = models.BooleanField(default=True)
    power_locks = models.BooleanField(default=True)
    cruise_control = models.BooleanField(default=False)
    backup_camera = models.BooleanField(default=False)
    bluetooth = models.BooleanField(default=False)
    navigation_system = models.BooleanField(default=False)
    leather_seats = models.BooleanField(default=False)
    sunroof = models.BooleanField(default=False)
    all_wheel_drive = models.BooleanField(default=False)
    
    # Admin/Internal
    description = models.TextField(blank=True)
    date_added = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date_added']
        verbose_name_plural = "Cars"
    
    def __str__(self):
        return f"{self.year} {self.make} {self.model} ({self.vin})"

    @property
    def display_name(self):
        """Customer-facing name without the VIN (used in analytics/feeds)."""
        return f"{self.year} {self.make} {self.model}"

    def is_available(self):
        return self.status == 'available'

    def is_publicly_listed(self):
        """True when the vehicle appears on the public inventory pages.

        Sold vehicles stay visible: the page a visitor already has open
        should not turn into a 404, and the similar-vehicles block gives
        them something to look at instead.
        """
        return self.status in self.PUBLIC_STATUSES

    def status_badge_class(self):
        """The Bootstrap badge class used to show this status."""
        return self.STATUS_BADGE_CLASSES.get(self.status, 'bg-secondary')


class CarImage(models.Model):
    """Photo for a car, uploaded by staff"""
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=upload_to_cars)
    thumbnail = models.ImageField(
        upload_to=upload_to_cars_thumbnails,
        blank=True,
        help_text="Small copy used in listings; generated when the photo is uploaded.",
    )
    caption = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(default=False, help_text="Main photo shown on car cards")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'id']
        verbose_name = "Car Image"
        verbose_name_plural = "Car Images"

    def __str__(self):
        return f"Image for {self.car} ({self.caption or 'no caption'})"

    def thumbnail_url(self):
        """The small version of the photo, falling back to the full one.

        Photos uploaded before the image pipeline existed have no
        thumbnail, and the listings still have to work for those.
        """
        if self.thumbnail:
            return self.thumbnail.url
        return self.image.url if self.image else ''

    def srcset(self):
        """Responsive candidates for ``<img srcset>``.

        A listing only needs the small copy on a phone but can use the full
        photo on a wide screen. Legacy photos without a generated thumbnail
        have just one candidate, so the browser falls back to ``src``.
        """
        if not self.image:
            return ''
        if not self.thumbnail:
            return ''
        return '{thumb} {thumb_width}w, {full} {full_width}w'.format(
            thumb=self.thumbnail.url,
            thumb_width=settings.CAR_IMAGE_THUMBNAIL_WIDTH,
            full=self.image.url,
            full_width=settings.CAR_IMAGE_MAX_WIDTH,
        )

    def save(self, *args, **kwargs):
        if self.is_primary:
            CarImage.objects.filter(car=self.car, is_primary=True)\
                            .exclude(pk=self.pk)\
                            .update(is_primary=False)
        self._process_new_upload()
        super().save(*args, **kwargs)

    def _process_new_upload(self):
        """Resize and re-encode a freshly uploaded photo.

        Only a file that has not been written to storage yet is touched,
        so saving a caption or re-ordering photos never re-processes the
        picture. A file that cannot be processed is kept as it is rather
        than breaking the upload.
        """
        from .images import process_image, process_thumbnail

        if not self.image or self.image._committed:
            return

        try:
            thumbnail_file, thumbnail_name = process_thumbnail(self.image)
            full_file, full_name = process_image(self.image)
        except Exception:
            logger.warning(
                'Could not process the photo for %s; storing it unchanged.',
                self.car,
                exc_info=True,
            )
            return

        self.image.save(full_name, full_file, save=False)
        self.thumbnail.save(thumbnail_name, thumbnail_file, save=False)

    def reprocess(self):
        """Rebuild the resized copy and the thumbnail from the stored file.

        Used by the ``reprocess_images`` command to bring photos that were
        uploaded before the image pipeline existed up to date.
        """
        from .images import process_image, process_thumbnail

        if not self.image:
            return False

        old_image = self.image.name
        old_thumbnail = self.thumbnail.name if self.thumbnail else ''

        with self.image.open('rb') as handle:
            thumbnail_file, thumbnail_name = process_thumbnail(handle)
            full_file, full_name = process_image(handle)

        self.image.save(full_name, full_file, save=False)
        self.thumbnail.save(thumbnail_name, thumbnail_file, save=False)
        super().save()

        # The originals are replaced by the processed copies.
        if old_image and old_image != self.image.name:
            self.image.storage.delete(old_image)
        if old_thumbnail and old_thumbnail != self.thumbnail.name:
            self.thumbnail.storage.delete(old_thumbnail)
        return True


class CarPriceHistory(models.Model):
    """Log of a car's asking-price changes.

    A row is created whenever staff lower the asking price. Rows with
    ``notified_at`` unset form the work queue for the price-drop alert command.
    """
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='price_history')
    old_price = models.DecimalField(max_digits=12, decimal_places=2)
    new_price = models.DecimalField(max_digits=12, decimal_places=2)
    changed_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-changed_at']
        verbose_name = "Car price history"
        verbose_name_plural = "Car price history"

    def __str__(self):
        return f"{self.car} price {self.old_price} -> {self.new_price}"

    @property
    def is_drop(self):
        return self.new_price < self.old_price


class CarStatusHistory(models.Model):
    """Log of a car's status changes.

    A row is created when a car transitions back to ``available`` (e.g. it was
    sold/reserved/in maintenance and returned to the lot). Rows with
    ``notified_at`` unset form the work queue for back-in-stock alerts.
    """
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='status_history')
    old_status = models.CharField(max_length=20, choices=Car.STATUS_CHOICES)
    new_status = models.CharField(max_length=20, choices=Car.STATUS_CHOICES)
    changed_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-changed_at']
        verbose_name = "Car status history"
        verbose_name_plural = "Car status history"

    def __str__(self):
        return f"{self.car} status {self.old_status} -> {self.new_status}"


class Inventory(models.Model):
    """Track inventory levels and stock information"""
    car = models.OneToOneField(Car, on_delete=models.CASCADE, related_name='inventory')
    quantity_in_stock = models.IntegerField(default=1, validators=[MinValueValidator(0)])
    reorder_level = models.IntegerField(default=3)
    location = models.CharField(max_length=200, blank=True, help_text="Storage location")
    last_counted = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Inventories"
    
    def __str__(self):
        return f"Inventory for {self.car}"
    
    def is_low_stock(self):
        return self.quantity_in_stock <= self.reorder_level


class Customer(models.Model):
    """Model representing a customer"""
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
    ]
    
    # Personal Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    
    # Address
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=50)
    zip_code = models.CharField(max_length=10)
    country = models.CharField(max_length=100, default='USA')
    
    # Financial/Credit
    credit_score = models.IntegerField(null=True, blank=True)
    preferred_financing = models.BooleanField(default=False)
    
    # Account Info
    date_registered = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['last_name', 'first_name']
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    def get_full_address(self):
        return f"{self.address}, {self.city}, {self.state} {self.zip_code}"


class SalesTransaction(models.Model):
    """Model representing a car sale"""
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('financing', 'Financing'),
        ('lease', 'Lease'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Relationships
    car = models.ForeignKey(Car, on_delete=models.PROTECT)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='purchases')
    order = models.ForeignKey(
        'cars.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales',
        help_text="The online order this sale came from, when there was one",
    )
    salesperson = models.CharField(max_length=200, blank=True, help_text="Name of salesperson")
    
    # Transaction Details
    sale_date = models.DateTimeField(default=timezone.now)
    sale_price = models.DecimalField(max_digits=12, decimal_places=2)
    trade_in_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    down_payment = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Payment
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Financing (if applicable)
    financed_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Annual interest rate %")
    loan_term_months = models.IntegerField(null=True, blank=True)
    
    # Documentation
    invoice_number = models.CharField(max_length=50, unique=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-sale_date']
    
    def __str__(self):
        return f"Sale #{self.invoice_number} - {self.car} to {self.customer}"
    
    @property
    def amount_due(self):
        """What the customer still owes once the down payment is taken off.

        ``total_amount`` is the sale price less the trade-in credit; the
        down payment comes off that, so this is the amount left to settle.
        """
        return (self.total_amount or Decimal('0')) - (self.down_payment or Decimal('0'))

    def calculate_monthly_payment(self):
        """Calculate monthly payment for financed amount"""
        if self.financed_amount <= 0 or self.loan_term_months is None:
            return 0
        
        monthly_rate = (self.interest_rate / 100) / 12
        if monthly_rate == 0:
            return self.financed_amount / self.loan_term_months
        
        numerator = self.financed_amount * monthly_rate * ((1 + monthly_rate) ** self.loan_term_months)
        denominator = ((1 + monthly_rate) ** self.loan_term_months) - 1
        return numerator / denominator


class ServiceRecord(models.Model):
    """Track maintenance and service history"""
    SERVICE_TYPE_CHOICES = [
        ('maintenance', 'Regular Maintenance'),
        ('repair', 'Repair'),
        ('inspection', 'Inspection'),
        ('oil_change', 'Oil Change'),
        ('tire_service', 'Tire Service'),
        ('battery_service', 'Battery Service'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='service_records', null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_bookings',
    )
    service_date = models.DateTimeField(default=timezone.now)
    service_type = models.CharField(max_length=50, choices=SERVICE_TYPE_CHOICES)
    description = models.TextField(blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    odometer_reading = models.IntegerField(null=True, blank=True)
    technician = models.CharField(max_length=200, blank=True)
    customer_name = models.CharField(max_length=100, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ['-service_date']

    def __str__(self):
        if self.car:
            return f"Service for {self.car} on {self.service_date.date()}"
        return f"Service booking ({self.customer_name}) on {self.service_date.date()}"


class BookingReminder(models.Model):
    """One reminder sent for one booking on one date.

    Service visits, test drives and car hires are separate models, so a small
    log avoids adding a near-identical field to all three. The date is part of
    the key: if staff move a booking, the customer gets a fresh reminder for
    the new date instead of being skipped forever.
    """
    BOOKING_TYPES = (
        ('service', 'Service booking'),
        ('appointment', 'Test drive'),
        ('hire', 'Car hire'),
    )

    booking_type = models.CharField(max_length=20, choices=BOOKING_TYPES)
    object_id = models.PositiveIntegerField()
    reminder_date = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Booking reminder'
        verbose_name_plural = 'Booking reminders'
        constraints = [
            models.UniqueConstraint(
                fields=['booking_type', 'object_id', 'reminder_date'],
                name='unique_booking_reminder_per_date',
            )
        ]

    def __str__(self):
        return f'{self.get_booking_type_display()} reminder for #{self.object_id}'


class Inquiry(ConversionTracking):
    """Customer inquiry about a vehicle"""
    STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('interested', 'Interested'),
        ('not_interested', 'Not Interested'),
        ('closed', 'Closed'),
    ]
    
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='inquiries')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inquiries',
    )
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)
    message = models.TextField()
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='crm_assigned_inquiries')
    follow_up_date = models.DateField(null=True, blank=True)
    last_contacted_at = models.DateTimeField(null=True, blank=True)
    reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the last follow-up reminder was sent, so it is not repeated",
    )
    notes = models.TextField(blank=True)
    lead_source = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Inquiries"
        indexes = [
            models.Index(fields=['assigned_to', 'follow_up_date']),
            models.Index(fields=['status', 'follow_up_date']),
        ]
    
    def __str__(self):
        return f"Inquiry for {self.car} from {self.customer_name}"

    #: Statuses where the lead still needs work.
    OPEN_STATUSES = ('new', 'contacted', 'interested')

    def is_open(self):
        return self.status in self.OPEN_STATUSES


class Order(ConversionTracking):
    """Customer order/purchase request for a vehicle"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing'),
        ('ready_for_pickup', 'Ready for Pickup'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Not paid'),
        ('partial', 'Part paid'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded'),
    ]
    
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='orders')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)
    customer_address = models.TextField()
    
    # Order Details
    order_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Purchase Details
    price = models.DecimalField(max_digits=12, decimal_places=2)
    trade_in_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    financing_needed = models.BooleanField(default=False)
    down_payment = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Online payment. Only the deposit is payable on the website for now;
    # the balance is settled with staff when the order is completed.
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='pending',
    )
    deposit_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Deposit quoted when the order was placed",
    )
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Everything received against this order so far",
    )
    deposit_paid_at = models.DateTimeField(null=True, blank=True)
    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="M-Pesa or bank reference for the latest payment",
    )
    deposit_reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the customer was last reminded about the deposit",
    )
    released_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When staff released this order and freed the vehicle",
    )
    release_reason = models.CharField(max_length=255, blank=True)

    # The vehicle the customer is trading in, as they described it. The
    # details are kept so staff can see what the customer thought their
    # car was worth when the order was placed.
    trade_in_year = models.IntegerField(null=True, blank=True)
    trade_in_make = models.CharField(max_length=100, blank=True)
    trade_in_model = models.CharField(max_length=100, blank=True)
    trade_in_mileage = models.IntegerField(null=True, blank=True)
    trade_in_condition = models.CharField(
        max_length=20,
        choices=TRADE_IN_CONDITION_CHOICES,
        blank=True,
    )
    trade_in_body_type = models.CharField(
        max_length=20,
        choices=TRADE_IN_BODY_TYPE_CHOICES,
        blank=True,
        help_text="Body style the customer said their car was",
    )
    trade_in_estimate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Online estimate the customer was shown",
    )
    
    # Contact/Notes
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-order_date']
        indexes = [
            models.Index(fields=['status', 'payment_status', 'order_date']),
        ]
    
    def __str__(self):
        return f"Order #{self.id} - {self.car} by {self.customer_name}"
    
    def get_total_price(self):
        """Calculate total price after trade-in"""
        return self.price - self.trade_in_value

    def amount_payable(self):
        """What is owed after the trade-in, never below zero."""
        return order_amount_payable(self.price, self.trade_in_value)

    def deposit_due(self):
        """The deposit quoted for this order.

        The amount is copied onto the order when it is placed. Orders made
        before the field existed fall back to the rule, so they still show
        a sensible figure.
        """
        if self.deposit_amount and self.deposit_amount > 0:
            return self.deposit_amount
        return order_deposit(self.price, self.trade_in_value)

    def balance_due(self):
        """What is still owed after the payments received so far."""
        balance = self.amount_payable() - (self.amount_paid or Decimal('0'))
        if balance < 0:
            return Decimal('0.00')
        return balance.quantize(Decimal('0.01'))

    def is_deposit_paid(self):
        """True once enough has been received to cover the deposit."""
        deposit = self.deposit_due()
        if deposit <= 0:
            return False
        return bool(self.deposit_paid_at) or (self.amount_paid or 0) >= deposit

    def is_awaiting_deposit(self):
        """A live order whose deposit has not been received yet."""
        return self.status == 'pending' and not self.is_deposit_paid()

    def is_settled(self):
        """True once the order has been paid in full."""
        return self.payment_status == 'paid'

    def record_payment(self, amount, reference='', at=None):
        """Add a payment to the order and work out where it now stands.

        A deposit payment leaves the order ``partial``; staff still review
        the order and confirm it by hand. Paying the balance marks it
        ``paid``.
        """
        amount = Decimal(str(amount or 0))
        if amount <= 0:
            return self

        self.amount_paid = (self.amount_paid or Decimal('0')) + amount
        payable = self.amount_payable()

        if self.amount_paid >= payable:
            self.payment_status = 'paid'
        elif self.amount_paid > 0:
            self.payment_status = 'partial'

        if not self.deposit_paid_at and self.amount_paid >= self.deposit_due():
            self.deposit_paid_at = at or timezone.now()

        if reference:
            self.payment_reference = reference

        self.save(update_fields=[
            'amount_paid', 'payment_status', 'deposit_paid_at',
            'payment_reference',
        ])
        return self


class Testimonial(models.Model):
    """Customer review shown on the homepage"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='testimonials',
    )
    customer_name = models.CharField(max_length=100)
    vehicle = models.CharField(max_length=100, blank=True, help_text="e.g. 2023 Toyota Camry")
    quote = models.TextField()
    rating = models.PositiveSmallIntegerField(default=5)
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.customer_name} - {self.vehicle or 'General'}: {self.quote[:40]}"


class Appointment(ConversionTracking):
    """Customer test-drive appointment request"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='appointments')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='appointments',
    )
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)
    preferred_date = models.DateField()
    preferred_time = models.TimeField()
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['preferred_date', 'preferred_time']

    def __str__(self):
        return f"Test drive {self.car} on {self.preferred_date} by {self.customer_name}"


class ContactMessage(models.Model):
    """Message submitted through the public contact page"""
    STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('closed', 'Closed'),
    ]

    #: Statuses where the lead still needs work.
    OPEN_STATUSES = ('new', 'contacted')

    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=150)
    message = models.TextField()
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='crm_assigned_contact_messages')
    follow_up_date = models.DateField(null=True, blank=True)
    last_contacted_at = models.DateTimeField(null=True, blank=True)
    reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the last follow-up reminder was sent, so it is not repeated",
    )
    notes = models.TextField(blank=True)
    lead_source = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['assigned_to', 'follow_up_date']),
            models.Index(fields=['status', 'follow_up_date']),
        ]

    def __str__(self):
        return f"{self.subject} - {self.name}"

    def is_open(self):
        return self.status in self.OPEN_STATUSES


class NewsletterSubscription(models.Model):
    """Email subscribed via the newsletter form"""
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-subscribed_at']

    def __str__(self):
        return self.email


class ContactInfo(models.Model):
    """Editable 'Visit or Call' details shown on the contact page (singleton)"""
    address = models.TextField(default='123 Main Street\nAnytown, USA')
    phone = models.CharField(max_length=50, default='(555) 123-4567')
    email = models.EmailField(default='sales@car-dealership.local')
    whatsapp = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="WhatsApp number with country code, digits only (e.g. 14155551234). Leave blank to hide the button.",
    )
    hours = models.TextField(default='Mon – Sat: 9:00 AM – 7:00 PM\nSunday: Closed')

    class Meta:
        verbose_name = 'Contact Info'

    def __str__(self):
        return f'Contact Info ({self.phone})'

    @property
    def whatsapp_url(self):
        """A wa.me link with a pre-filled message, or '' when no number is set"""
        digits = ''.join(ch for ch in self.whatsapp if ch.isdigit())
        if not digits:
            return ''
        message = quote("Hi, I'd like to ask about a vehicle.")
        return f'https://wa.me/{digits}?text={message}'

    @classmethod
    def get_solo(cls):
        """Return the singleton row, creating it with defaults if missing"""
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance


class AboutInfo(models.Model):
    """Editable 'About Us' page content (singleton)"""
    page_tagline = models.CharField(
        max_length=200,
        default='Vision, mission, and the values that guide us',
    )
    vision_text = models.TextField(default=(
        "To be the region's most trusted dealership — known for honest pricing, "
        "quality vehicles, and a buying experience customers recommend to friends and family."
    ))
    mission_text = models.TextField(default=(
        "To help every customer find the right vehicle for their life and budget through "
        "transparent pricing, thorough inspections, flexible financing, and support that "
        "continues long after the sale."
    ))
    value_one_title = models.CharField(max_length=100, default='Quality You Can Trust')
    value_one_text = models.TextField(
        default='Every vehicle is inspected and certified before it reaches our lot.'
    )
    value_two_title = models.CharField(max_length=100, default='Honest Pricing')
    value_two_text = models.TextField(
        default='Clear, competitive pricing with no surprises — from quote to keys.'
    )
    value_three_title = models.CharField(max_length=100, default='Support For Life')
    value_three_text = models.TextField(
        default='Flexible financing and a dedicated team ready to help long after the sale.'
    )

    class Meta:
        verbose_name = 'About Page Content'

    def __str__(self):
        return 'About Page Content'

    @classmethod
    def get_solo(cls):
        """Return the singleton row, creating it with defaults if missing"""
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance


def logo_upload_to(instance, filename):
    return f"branding/{filename}"


class DealershipInfo(models.Model):
    """Editable dealership name and logo used across the site (singleton)"""
    DEFAULT_NAME = 'Car Dealership'

    name = models.CharField(
        max_length=120,
        default=DEFAULT_NAME,
        help_text="Shown in the navigation bar, footer, page titles, and emails.",
    )
    logo = models.ImageField(
        upload_to=logo_upload_to,
        blank=True,
        help_text="PNG or JPG, up to 5 MB. Shown in the navigation bar.",
    )

    class Meta:
        verbose_name = 'Dealership Info'
        verbose_name_plural = 'Dealership Info'

    def __str__(self):
        return self.name or self.DEFAULT_NAME

    @classmethod
    def get_solo(cls):
        """Return the singleton row, creating it with defaults if missing"""
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance

    @classmethod
    def display_name(cls):
        """Return the dealership name, falling back to the default if unreadable"""
        try:
            info = cls.get_solo()
        except Exception:
            return cls.DEFAULT_NAME
        return info.name or cls.DEFAULT_NAME


class SavedSearch(models.Model):
    """A saved vehicle search; matching cars are emailed to the subscriber"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='saved_searches',
    )
    email = models.EmailField()
    make = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    year_min = models.IntegerField(null=True, blank=True)
    year_max = models.IntegerField(null=True, blank=True)
    price_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    body_type = models.CharField(max_length=50, blank=True)
    fuel_type = models.CharField(max_length=20, blank=True)
    transmission = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    notify_price_drops = models.BooleanField(
        default=True,
        help_text="Email me when a car matching this search drops in price",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Saved search for {self.email} ({self.summary()})'

    def summary(self):
        """"Year 2020–2024, Toyota, under KSh 3,500,000" style one-line description"""
        parts = []
        if self.make:
            parts.append(self.make)
        if self.model:
            parts.append(self.model)
        if self.year_min or self.year_max:
            parts.append(f"year {self.year_min or '…'}–{self.year_max or '…'}")
        if self.price_min or self.price_max:
            low = format_money(self.price_min) if self.price_min is not None else '…'
            high = format_money(self.price_max) if self.price_max is not None else '…'
            parts.append(f"{low}–{high}")
        if self.body_type:
            parts.append(self.body_type)
        if self.fuel_type:
            parts.append(self.fuel_type)
        if self.transmission:
            parts.append(self.transmission)
        return ", ".join(parts) or "All cars"

    def match_cars(self, only_new_since=None):
        """Return available cars matching this search's criteria"""
        queryset = Car.objects.filter(status='available')
        if self.make:
            queryset = queryset.filter(make__iexact=self.make)
        if self.model:
            queryset = queryset.filter(model__icontains=self.model)
        if self.year_min:
            queryset = queryset.filter(year__gte=self.year_min)
        if self.year_max:
            queryset = queryset.filter(year__lte=self.year_max)
        if self.price_min:
            queryset = queryset.filter(asking_price__gte=self.price_min)
        if self.price_max:
            queryset = queryset.filter(asking_price__lte=self.price_max)
        if self.body_type:
            queryset = queryset.filter(body_type=self.body_type)
        if self.fuel_type:
            queryset = queryset.filter(fuel_type=self.fuel_type)
        if self.transmission:
            queryset = queryset.filter(transmission=self.transmission)
        if only_new_since is not None:
            queryset = queryset.filter(date_added__gte=only_new_since)
        return queryset


class Post(models.Model):
    """Blog/news article published on the public site"""
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, help_text="URL-friendly version of the title")
    excerpt = models.CharField(max_length=300, blank=True, help_text="Short summary shown in listings")
    body = models.TextField()
    cover_image = models.ImageField(upload_to='posts/', blank=True)
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at']

    def __str__(self):
        return self.title


class ChatSession(models.Model):
    """A visitor's chatbot conversation (one row per browser, keyed by a token
    stored client-side so it works without an account)."""
    STATUS_CHOICES = [
        ('bot', 'Bot Only'),
        ('waiting', 'Waiting for Agent'),
        ('active', 'Live Chat Active'),
        ('closed', 'Closed'),
    ]
    session_key = models.CharField(max_length=40, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_sessions',
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_live_chats',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='bot')
    is_escalated = models.BooleanField(default=False)
    contact_message = models.ForeignKey(
        ContactMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_sessions',
        help_text="The contact message created when the visitor asked for a human.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_activity_at']

    def __str__(self):
        who = self.user.get_username() if self.user_id else self.session_key[:8]
        return f'Chat session {who} ({self.message_count} messages)'

    @property
    def message_count(self):
        return self.messages.count()

    @property
    def unread_for_staff(self):
        return self.messages.filter(sender='user', is_read=False).count()

    @property
    def unread_for_user(self):
        return self.messages.filter(sender__in=['bot', 'staff'], is_read=False).count()


class ChatMessage(models.Model):
    """A single message within a chatbot conversation"""
    SENDER_CHOICES = [
        ('user', 'Visitor'),
        ('bot', 'Chatbot'),
        ('staff', 'Staff'),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.CharField(max_length=8, choices=SENDER_CHOICES)
    sender_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_messages_sent')
    text = models.TextField()
    intent = models.CharField(max_length=50, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.get_sender_display()}: {self.text[:40]}'


# ==================== LIST YOUR CAR ====================

def upload_to_listing_photos(instance, filename):
    return f"listing_requests/request_{instance.request_id}/{filename}"


def upload_to_listing_thumbnails(instance, filename):
    return f"listing_requests/request_{instance.request_id}/thumbs/{filename}"


class ListingRequest(models.Model):
    """A customer's request to have their car listed on the website.

    The owner fills in the vehicle details and uploads the logbook and the
    photos. Staff verify the car and the logbook, confirm the listing fee
    has been received, and only then publish the listing - on the owner's
    behalf - which is what creates the ``Car`` record.

    Nothing goes live on the owner's say-so alone: ``can_be_published()``
    has to be true, which means the vehicle was inspected, the logbook was
    verified, and the fee was settled.
    """

    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('awaiting_documents', 'Awaiting Documents'),
        ('awaiting_payment', 'Awaiting Payment'),
        ('listed', 'Listed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('waived', 'Waived'),
        ('refunded', 'Refunded'),
    ]

    #: Statuses that mean the request is still being worked on.
    OPEN_STATUSES = ('submitted', 'under_review', 'awaiting_documents', 'awaiting_payment')

    #: Statuses staff can set by hand. 'listed' is not among them: that one
    #: is set by publishing the listing, and never by a dropdown.
    MANUAL_STATUSES = (
        'submitted', 'under_review', 'awaiting_documents',
        'awaiting_payment', 'rejected',
    )

    #: Payment states that let a listing go live.
    SETTLED_PAYMENT_STATUSES = ('paid', 'waived')

    #: Bootstrap badge class per status.
    STATUS_BADGE_CLASSES = {
        'submitted': 'bg-info text-dark',
        'under_review': 'bg-primary',
        'awaiting_documents': 'bg-warning text-dark',
        'awaiting_payment': 'bg-warning text-dark',
        'listed': 'bg-success',
        'rejected': 'bg-danger',
        'cancelled': 'bg-secondary',
    }

    # Who is asking
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='listing_requests',
        help_text="The account that made the request",
    )
    owner_name = models.CharField(max_length=100)
    owner_email = models.EmailField()
    owner_phone = models.CharField(max_length=20)

    # The vehicle, as the owner described it
    make = models.CharField(max_length=100, db_index=True)
    model = models.CharField(max_length=100)
    year = models.IntegerField(validators=[MinValueValidator(1900)])
    vin = models.CharField(max_length=17, help_text="Vehicle Identification Number")
    color = models.CharField(max_length=50, blank=True)
    body_type = models.CharField(
        max_length=50,
        blank=True,
        choices=Car._meta.get_field('body_type').choices,
    )
    transmission = models.CharField(
        max_length=20,
        blank=True,
        choices=Car._meta.get_field('transmission').choices,
    )
    fuel_type = models.CharField(
        max_length=20,
        blank=True,
        choices=Car._meta.get_field('fuel_type').choices,
    )
    mileage = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    engine_size = models.CharField(max_length=20, blank=True)
    description = models.TextField(blank=True)

    # The logbook, which staff check against the car
    logbook_number = models.CharField(max_length=60, blank=True)
    logbook_owner_name = models.CharField(max_length=100, blank=True)

    # Money
    asking_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="The price the owner wants the car advertised at",
    )
    fee_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=DEFAULT_LISTING_FEE,
        help_text="The listing fee quoted when the request was made",
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='pending',
    )
    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="M-Pesa or bank reference for the fee",
    )
    payment_received_at = models.DateTimeField(null=True, blank=True)

    # Where the request has got to
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    vehicle_verified = models.BooleanField(
        default=False,
        help_text="A staff member has inspected the vehicle",
    )
    logbook_verified = models.BooleanField(
        default=False,
        help_text="A staff member has checked the logbook against the vehicle",
    )
    staff_notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_listing_requests',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    car = models.ForeignKey(
        Car,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='listing_requests',
        help_text="The listing created when the request was approved",
    )
    reference = models.CharField(max_length=30, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.reference} - {self.vehicle_description()}'

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._generate_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_reference():
        """Return a unique reference like LSR-20261022-4821"""
        stamp = timezone.now().strftime('%Y%m%d')
        while True:
            candidate = f'LSR-{stamp}-{random.randint(1000, 9999)}'
            if not ListingRequest.objects.filter(reference=candidate).exists():
                return candidate

    def vehicle_description(self):
        """\"2019 Toyota Hilux\" - the vehicle as the owner described it."""
        return f'{self.year} {self.make} {self.model}'

    def is_open(self):
        """True while the request is still being worked on."""
        return self.status in self.OPEN_STATUSES

    def is_settled(self):
        """True once the listing fee has been settled."""
        return self.payment_status in self.SETTLED_PAYMENT_STATUSES

    def can_be_published(self):
        """True when everything we require before going live is in place.

        The vehicle was inspected, the logbook was verified, and the fee
        was paid. Staff publish the listing on the owner's behalf, so this
        is the gate that stops an unverified car reaching the site.
        """
        return self.vehicle_verified and self.logbook_verified and self.is_settled()

    def status_badge_class(self):
        """The Bootstrap badge class used to show this status."""
        return self.STATUS_BADGE_CLASSES.get(self.status, 'bg-secondary')

    def vehicle_photos(self):
        """The photos of the car the owner uploaded."""
        return self.photos.filter(kind=ListingRequestPhoto.KIND_VEHICLE)

    def logbook_photos(self):
        """The scans of the logbook the owner uploaded."""
        return self.photos.filter(kind=ListingRequestPhoto.KIND_LOGBOOK)

    @property
    def is_listed(self):
        """True when the request has been published on the website."""
        return self.status == 'listed' and self.car_id is not None


class ListingRequestPhoto(models.Model):
    """A photo the owner uploaded with a listing request.

    The vehicle photos end up on the listing when staff publish it. The
    logbook scan stays with the request: it is a private document, and it
    is what staff check the car against.
    """

    KIND_VEHICLE = 'vehicle'
    KIND_LOGBOOK = 'logbook'

    KIND_CHOICES = [
        (KIND_VEHICLE, 'Vehicle photo'),
        (KIND_LOGBOOK, 'Logbook scan'),
    ]

    request = models.ForeignKey(
        ListingRequest,
        on_delete=models.CASCADE,
        related_name='photos',
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_VEHICLE)
    photo = models.ImageField(upload_to=upload_to_listing_photos)
    thumbnail = models.ImageField(
        upload_to=upload_to_listing_thumbnails,
        blank=True,
        help_text="Small copy used in listings; generated when the photo is uploaded.",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.get_kind_display()} for {self.request}'

    def thumbnail_url(self):
        """The small version of the photo, falling back to the full one."""
        if self.thumbnail:
            return self.thumbnail.url
        return self.photo.url if self.photo else ''

    def save(self, *args, **kwargs):
        self._process_new_upload()
        super().save(*args, **kwargs)

    def _process_new_upload(self):
        """Resize and re-encode a freshly uploaded photo.

        The owner's photos go through the same pipeline as staff photos:
        they are straightened, resized and have their EXIF data (which
        includes the GPS coordinates of where the photo was taken)
        stripped, so the site only ever serves copies it made itself.
        """
        from .images import process_image, process_thumbnail

        if not self.photo or self.photo._committed:
            return

        try:
            thumbnail_file, thumbnail_name = process_thumbnail(self.photo)
            full_file, full_name = process_image(self.photo)
        except Exception:
            logger.warning(
                'Could not process the photo for %s; storing it unchanged.',
                self.request,
                exc_info=True,
            )
            return

        self.photo.save(full_name, full_file, save=False)
        self.thumbnail.save(thumbnail_name, thumbnail_file, save=False)


class FinancingApplication(ConversionTracking):
    """A customer's request to finance a vehicle.

    The customer tells us what they earn and what they can put down; we
    work out what they would need to borrow and what the monthly
    repayment would be, and staff then review it by hand. Nothing is
    approved automatically: an approval is a credit decision, and the
    website is not a credit reference bureau.

    The price and the estimate are copied onto the application when it is
    submitted, so a later change to the asking price or to the interest
    rate never rewrites what a customer was quoted.
    """

    EMPLOYMENT_CHOICES = [
        ('employed', 'Employed'),
        ('self_employed', 'Self-employed'),
        ('business_owner', 'Business owner'),
        ('student', 'Student'),
        ('retired', 'Retired'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('reviewing', 'Under Review'),
        ('approved', 'Approved'),
        ('declined', 'Declined'),
        ('withdrawn', 'Withdrawn'),
    ]

    #: Statuses that mean the application is still being worked on.
    OPEN_STATUSES = ('submitted', 'reviewing')

    #: Statuses staff can set from the review page.
    MANUAL_STATUSES = ('reviewing', 'approved', 'declined')

    #: A decision has been made.
    DECIDED_STATUSES = ('approved', 'declined')

    #: Bootstrap badge class per status.
    STATUS_BADGE_CLASSES = {
        'submitted': 'bg-info text-dark',
        'reviewing': 'bg-primary',
        'approved': 'bg-success',
        'declined': 'bg-danger',
        'withdrawn': 'bg-secondary',
    }

    TERM_CHOICES = [(months, f'{months} months') for months in LOAN_TERMS]

    # Who is asking
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='financing_applications',
        help_text="The account that made the application",
    )
    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)

    # Which car. Kept as a snapshot too, because a car can be sold (or
    # deleted) long before the credit decision is made.
    car = models.ForeignKey(
        Car,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='financing_applications',
    )
    car_label = models.CharField(
        max_length=200,
        blank=True,
        help_text="The vehicle as it was described when the application was made",
    )

    # What they do for a living
    employment_status = models.CharField(
        max_length=20,
        choices=EMPLOYMENT_CHOICES,
        default='employed',
    )
    employer_name = models.CharField(max_length=150, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    monthly_income = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Net monthly income",
    )
    monthly_expenses = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="What they already spend each month",
    )

    # The deal, as quoted at submission
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="The vehicle price when the application was made",
    )
    deposit_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    trade_in_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    loan_term_months = models.PositiveSmallIntegerField(default=36)
    interest_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=DEFAULT_INTEREST_RATE,
        help_text="Annual interest rate used for the estimate",
    )
    requested_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Price less the deposit and the trade-in, at submission",
    )
    estimated_monthly = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Estimated monthly repayment at submission",
    )

    # Where it has got to
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    decision_notes = models.TextField(
        blank=True,
        help_text="Internal notes for your colleagues",
    )
    decline_reason = models.TextField(
        blank=True,
        help_text="Shown to the customer when the application is declined",
    )
    approved_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="The amount actually approved, if different from what was requested",
    )
    approved_term_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="The term actually approved, if different from what was requested",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_financing_applications',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    reference = models.CharField(max_length=30, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Financing Application"
        verbose_name_plural = "Financing Applications"

    def __str__(self):
        return f'{self.reference} - {self.customer_name} ({self.car_label or "no car"})'

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._generate_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_reference():
        """Return a unique reference like FIN-20261023-4821"""
        stamp = timezone.now().strftime('%Y%m%d')
        while True:
            candidate = f'FIN-{stamp}-{random.randint(1000, 9999)}'
            if not FinancingApplication.objects.filter(reference=candidate).exists():
                return candidate

    def recalculate(self):
        """Work out what is being borrowed and what it costs each month.

        Called before saving, so the stored figures always match the
        deposit, trade-in, term and rate the customer applied with.
        """
        from .financing import amount_financed, monthly_payment

        self.requested_amount = amount_financed(
            self.price, self.deposit_amount, self.trade_in_value
        )
        self.estimated_monthly = monthly_payment(
            self.requested_amount, self.interest_rate, self.loan_term_months
        )
        return self

    def vehicle_label(self):
        """The vehicle the application is for, as it was described."""
        if self.car_label:
            return self.car_label
        if self.car_id:
            return str(self.car)
        return ''

    def is_open(self):
        """True while the application is still being worked on."""
        return self.status in self.OPEN_STATUSES

    def is_decided(self):
        """True once a decision has been made."""
        return self.status in self.DECIDED_STATUSES

    def status_badge_class(self):
        """The Bootstrap badge class used to show this status."""
        return self.STATUS_BADGE_CLASSES.get(self.status, 'bg-secondary')





def testimonial_photo_upload_to(instance, filename):
    return "testimonials/" + str(getattr(instance, "testimonial_id", None) or "tmp") + "/" + filename


class TestimonialPhoto(models.Model):
    testimonial = models.ForeignKey(Testimonial, on_delete=models.CASCADE, related_name="photos")
    photo = models.ImageField(upload_to=testimonial_photo_upload_to)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return "Photo for " + str(self.testimonial)
