from simple_history.models import HistoricalRecords
"""The models behind car hire and tours & travel.

A hire car is not sale inventory, so it lives in its own models rather
than being flagged up on ``Car``: the sale browse, the compare page, the
favourites and the price alerts all assume a car on the lot is for sale.

Each car in the fleet can be offered two ways:

* **self-drive hire**, where the customer drives it themselves, and
* **tours and travel**, where it goes out with one of our drivers.

Both are priced per day. The two rates are set by staff on the car, so a
tour can cost more per day than the same car would to drive yourself.

A booking is a *request*. Staff check the dates, check the customer's
licence and ID, take the money and then confirm it. Nothing in this
module confirms a booking on its own.
"""

import logging
import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from cars.models import ConversionTracking

from . import rules

logger = logging.getLogger(__name__)


#: The customer drives the car themselves.
SERVICE_SELF_DRIVE = 'self_drive'

#: The car goes out with one of our drivers.
SERVICE_TOUR = 'tour'

SERVICE_CHOICES = [
    (SERVICE_SELF_DRIVE, 'Self-drive hire'),
    (SERVICE_TOUR, 'Tours and travel'),
]


#: How an extra is charged: every day of the hire, or once.
ADD_ON_UNIT_CHOICES = [
    ('per_day', 'Per day'),
    ('per_booking', 'Once per booking'),
]


def upload_to_hire_photos(instance, filename):
    return f"hiring/car_{instance.hire_car_id}/{filename}"


def upload_to_hire_thumbnails(instance, filename):
    return f"hiring/car_{instance.hire_car_id}/thumbs/{filename}"


def upload_to_package_photos(instance, filename):
    return f"hiring/package_{instance.package_id}/{filename}"


def upload_to_package_thumbnails(instance, filename):
    return f"hiring/package_{instance.package_id}/thumbs/{filename}"


class HireCar(models.Model):
    """A car in the hire fleet."""

    BODY_TYPE_CHOICES = [
        ('sedan', 'Sedan'),
        ('hatchback', 'Hatchback'),
        ('suv', 'SUV'),
        ('wagon', 'Wagon'),
        ('van', 'Van'),
        ('minibus', 'Minibus'),
        ('pickup', 'Pickup'),
    ]

    TRANSMISSION_CHOICES = [
        ('manual', 'Manual'),
        ('automatic', 'Automatic'),
        ('cvt', 'CVT'),
    ]

    FUEL_TYPE_CHOICES = [
        ('petrol', 'Petrol'),
        ('diesel', 'Diesel'),
        ('hybrid', 'Hybrid'),
        ('electric', 'Electric'),
    ]

    STATUS_CHOICES = [
        ('available', 'Available'),
        ('maintenance', 'In Maintenance'),
        ('retired', 'Retired'),
    ]

    #: Only these cars are offered to the public.
    PUBLIC_STATUSES = ('available',)

    #: Bootstrap badge class per status.
    STATUS_BADGE_CLASSES = {
        'available': 'bg-success',
        'maintenance': 'bg-warning text-dark',
        'retired': 'bg-secondary',
    }

    make = models.CharField(max_length=100, help_text="Vehicle manufacturer")
    model = models.CharField(max_length=100, help_text="Vehicle model")
    year = models.IntegerField(validators=[MinValueValidator(1900)])
    color = models.CharField(max_length=50, blank=True)
    body_type = models.CharField(max_length=50, choices=BODY_TYPE_CHOICES)
    transmission = models.CharField(max_length=20, choices=TRANSMISSION_CHOICES)
    fuel_type = models.CharField(max_length=20, choices=FUEL_TYPE_CHOICES)

    seats = models.PositiveSmallIntegerField(
        default=4,
        help_text="How many passengers the car carries, the driver included.",
    )
    luggage_capacity = models.PositiveSmallIntegerField(
        default=2,
        help_text="How many suitcases the boot takes.",
    )

    #: What a customer pays per day to drive the car themselves.
    hire_daily_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Per day, self-drive.",
    )
    #: What a customer pays per day to have the car and a driver.
    tour_daily_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        default=0,
        help_text="Per day, with one of our drivers.",
    )
    allows_tours = models.BooleanField(
        default=True,
        help_text="Tick to offer this car for tours and travel.",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Hire Car"
        verbose_name_plural = "Hire Cars"

    def __str__(self):
        return f"{self.year} {self.make} {self.model}"

    def rate_for(self, service_type):
        """The daily rate for the service the customer wants."""
        if service_type == SERVICE_TOUR:
            return self.tour_daily_rate
        return self.hire_daily_rate

    def is_publicly_listed(self):
        """True when the car appears on the public hire pages."""
        return self.status in self.PUBLIC_STATUSES

    def status_badge_class(self):
        """The Bootstrap badge class used to show this status."""
        return self.STATUS_BADGE_CLASSES.get(self.status, 'bg-secondary')

    def primary_photo(self):
        """The photo shown on the hire cards."""
        return self.images.filter(is_primary=True).first() or self.images.first()

    def next_free_from(self):
        """The first day the car is free again, if it is out now."""
        today = timezone.localdate()
        latest = self.bookings.filter(
            start_date__lte=today,
            end_date__gte=today,
        ).exclude(status__in=rules.FREE_STATUSES).order_by('-end_date').first()
        if not latest:
            return None
        return latest.end_date + timedelta(days=1)


class HireCarImage(models.Model):
    """Photo of a hire car, uploaded by staff."""

    hire_car = models.ForeignKey(HireCar, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=upload_to_hire_photos)
    thumbnail = models.ImageField(
        upload_to=upload_to_hire_thumbnails,
        blank=True,
        help_text="Small copy used in listings; generated when the photo is uploaded.",
    )
    caption = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(default=False, help_text="Main photo shown on hire cards")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'uploaded_at']

    def __str__(self):
        return f"Image for {self.hire_car} ({self.caption or 'no caption'})"

    @property
    def thumbnail_url(self):
        """The small version of the photo, falling back to the full one."""
        if self.thumbnail:
            return self.thumbnail.url
        return self.image.url if self.image else ''

    def save(self, *args, **kwargs):
        if self.is_primary:
            HireCarImage.objects.filter(hire_car=self.hire_car, is_primary=True)\
                                .exclude(pk=self.pk)\
                                .update(is_primary=False)
        self._process_new_upload()
        super().save(*args, **kwargs)

    def _process_new_upload(self):
        """Resize and re-encode a freshly uploaded photo.

        Only a file that has not been written to storage yet is touched,
        so saving a caption never re-processes the picture.
        """
        from cars.images import process_image, process_thumbnail

        if not self.image or self.image._committed:
            return

        try:
            thumbnail_file, thumbnail_name = process_thumbnail(self.image)
            full_file, full_name = process_image(self.image)
        except Exception:
            logger.warning(
                'Could not process the photo for %s; storing it unchanged.',
                self.hire_car,
                exc_info=True,
            )
            return

        self.image.save(full_name, full_file, save=False)
        self.thumbnail.save(thumbnail_name, thumbnail_file, save=False)


class TourPackage(models.Model):
    """A ready-made tour: an itinerary, a duration and a price per person.

    A package is not a car. The customer picks a package and then picks one
    of the cars we take out with a driver; the car still goes through the
    same overlap, seat and confirmation rules as any other tour booking.
    The package adds the itinerary and its own per-person price.
    """

    name = models.CharField(max_length=150)
    slug = models.SlugField(
        max_length=170,
        unique=True,
        blank=True,
        help_text="Leave blank to build it from the name.",
    )
    destination = models.CharField(
        max_length=150,
        help_text="Where the tour goes, e.g. Maasai Mara.",
    )
    summary = models.CharField(
        max_length=300,
        blank=True,
        help_text="One line shown on the package card.",
    )
    description = models.TextField(
        blank=True,
        help_text="The pitch: what makes this tour worth taking.",
    )
    duration_days = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="How many days the package runs.",
    )
    price_per_person = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="What one passenger pays, the car and driver included.",
    )
    min_passengers = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="The fewest passengers the tour runs with.",
    )
    includes = models.TextField(
        blank=True,
        help_text="One item per line: park fees, meals, guide, fuel.",
    )
    excludes = models.TextField(
        blank=True,
        help_text="One item per line: drinks, tips, souvenirs.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Untick to take the package off the public pages.",
    )
    is_featured = models.BooleanField(
        default=False,
        help_text="Show it first on the package list.",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Lower numbers are shown first.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_featured', 'sort_order', 'name']
        verbose_name = "Tour Package"
        verbose_name_plural = "Tour Packages"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:160] or 'tour'
            slug = base
            suffix = 2
            while TourPackage.objects.filter(slug=slug).exclude(
                pk=self.pk
            ).exists():
                slug = f'{base}-{suffix}'
                suffix += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('hiring:tour_package_detail', args=[self.slug])

    def primary_photo(self):
        """The photo shown on the package card."""
        return self.images.filter(is_primary=True).first() or self.images.first()

    def day_count(self):
        """How many itinerary days have actually been written."""
        return self.days.count()


class TourPackageDay(models.Model):
    """One day of a package itinerary."""

    package = models.ForeignKey(
        TourPackage,
        on_delete=models.CASCADE,
        related_name='days',
    )
    day_number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
    )
    title = models.CharField(max_length=150)
    description = models.TextField(
        blank=True,
        help_text="Where you go and what you do that day.",
    )

    class Meta:
        ordering = ['day_number']
        constraints = [
            models.UniqueConstraint(
                fields=['package', 'day_number'],
                name='unique_day_per_package',
            ),
        ]
        verbose_name = "Itinerary Day"
        verbose_name_plural = "Itinerary Days"

    def __str__(self):
        return f"Day {self.day_number}: {self.title}"


class TourPackageImage(models.Model):
    """Photo of a tour package, uploaded by staff."""

    package = models.ForeignKey(
        TourPackage,
        on_delete=models.CASCADE,
        related_name='images',
    )
    image = models.ImageField(upload_to=upload_to_package_photos)
    thumbnail = models.ImageField(
        upload_to=upload_to_package_thumbnails,
        blank=True,
        help_text="Small copy used in listings; generated when the photo is uploaded.",
    )
    caption = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(
        default=False,
        help_text="Main photo shown on the package card",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'uploaded_at']
        verbose_name = "Tour Package Photo"
        verbose_name_plural = "Tour Package Photos"

    def __str__(self):
        return f"Photo for {self.package} ({self.caption or 'no caption'})"

    @property
    def thumbnail_url(self):
        """The small version of the photo, falling back to the full one."""
        if self.thumbnail:
            return self.thumbnail.url
        return self.image.url if self.image else ''

    def save(self, *args, **kwargs):
        if self.is_primary:
            TourPackageImage.objects.filter(
                package=self.package, is_primary=True
            ).exclude(pk=self.pk).update(is_primary=False)
        self._process_new_upload()
        super().save(*args, **kwargs)

    def _process_new_upload(self):
        """Resize and re-encode a freshly uploaded photo."""
        from cars.images import process_image, process_thumbnail

        if not self.image or self.image._committed:
            return

        try:
            thumbnail_file, thumbnail_name = process_thumbnail(self.image)
            full_file, full_name = process_image(self.image)
        except Exception:
            logger.warning(
                'Could not process the photo for %s; storing it unchanged.',
                self.package,
                exc_info=True,
            )
            return

        self.image.save(full_name, full_file, save=False)
        self.thumbnail.save(thumbnail_name, thumbnail_file, save=False)


class HireAddOn(models.Model):
    """An extra a customer can add to a hire, such as a child seat.

    The catalogue is set by staff in the admin, because what we can offer
    depends on what is in the store cupboard. The price and the unit are
    copied onto the booking when it is made, so changing the catalogue
    later never rewrites a booking that has already been quoted.
    """

    name = models.CharField(max_length=100)
    description = models.CharField(
        max_length=200,
        blank=True,
        help_text="Shown to the customer next to the tick box.",
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="What the customer pays, in shillings.",
    )
    unit = models.CharField(
        max_length=20,
        choices=ADD_ON_UNIT_CHOICES,
        default='per_day',
        help_text="Charged for every day of the hire, or once.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Untick to stop offering it without deleting past bookings.",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Lower numbers are shown first.",
    )

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = "Hire Add-on"
        verbose_name_plural = "Hire Add-ons"

    def __str__(self):
        return self.name

    @property
    def unit_label(self):
        """How the price is charged, in words."""
        return dict(ADD_ON_UNIT_CHOICES).get(self.unit, self.unit)


class HireBooking(ConversionTracking):
    history = HistoricalRecords()
    """A customer's request to hire a car, and the record of what happened."""

    SERVICE_CHOICES = SERVICE_CHOICES
    SERVICE_SELF_DRIVE = SERVICE_SELF_DRIVE
    SERVICE_TOUR = SERVICE_TOUR

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('active', 'Out with the customer'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    #: Statuses where the booking is still live.
    OPEN_STATUSES = ('pending', 'confirmed', 'active')

    #: Statuses staff set by hand. 'completed' is set when the car comes
    #: back, so it is not one of the states a dropdown offers.
    MANUAL_STATUSES = (
        'pending', 'confirmed', 'active', 'rejected', 'cancelled',
    )

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Not paid'),
        ('partial', 'Part paid'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded'),
    ]

    #: Payment states where the money has been settled.
    SETTLED_PAYMENT_STATUSES = ('paid',)

    hire_car = models.ForeignKey(
        HireCar,
        on_delete=models.PROTECT,
        related_name='bookings',
        help_text="A car with bookings on it cannot be deleted, only retired.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hire_bookings',
    )

    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)

    service_type = models.CharField(
        max_length=20,
        choices=SERVICE_CHOICES,
        default=SERVICE_SELF_DRIVE,
    )
    #: Set when the customer booked one of the ready-made tours.
    tour_package = models.ForeignKey(
        TourPackage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bookings',
        help_text="The package this booking came from, if any.",
    )
    #: The package name is copied onto the booking so a retired package
    #: never leaves an old booking looking like an ordinary hire.
    package_name = models.CharField(max_length=150, blank=True)
    start_date = models.DateField(help_text="The day the car is collected")
    end_date = models.DateField(help_text="The day the car is brought back")
    passengers = models.PositiveSmallIntegerField(default=1)
    destination = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where the car is going, for tours and travel",
    )
    pickup_location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where the car is collected from",
    )

    # Who is driving. Staff check both of these before they confirm.
    # A tour comes with one of our drivers, so the customer only gives a
    # licence number when they are driving themselves; the form enforces
    # that, and the model allows the blank.
    licence_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="Driving licence number, for self-drive hires",
    )
    id_number = models.CharField(
        max_length=50,
        help_text="National ID or passport number",
    )

    notes = models.TextField(blank=True)

    #: What the customer was quoted. Staff may change it, because the
    #: real cost of a trip depends on the route, the fuel and the driver.
    quoted_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Security deposit. The deposit is not part of the hire price: it is
    # held while the car is out and given back when it comes home.
    security_deposit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Held while the car is out, and refunded when it comes back.",
    )
    deposit_received_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the deposit was handed over.",
    )
    deposit_refunded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the deposit was given back.",
    )
    deposit_retained = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Part of the deposit kept back for damage or fuel.",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='pending',
    )
    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="M-Pesa or bank transfer reference",
    )
    payment_received_at = models.DateTimeField(null=True, blank=True)

    driver_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="The driver we send with the car, for tours",
    )
    staff_notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)

    reference = models.CharField(max_length=30, unique=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_hire_bookings',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Hire Booking"
        verbose_name_plural = "Hire Bookings"

    def __str__(self):
        return f"{self.reference or 'Hire booking'} - {self.hire_car} by {self.customer_name}"

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._generate_reference()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_reference():
        """Return a unique reference like HIRE-20261022-4821"""
        stamp = timezone.now().strftime('%Y%m%d')
        while True:
            candidate = f'HIRE-{stamp}-{random.randint(1000, 9999)}'
            if not HireBooking.objects.filter(reference=candidate).exists():
                return candidate

    @property
    def days(self):
        """The number of days the booking covers."""
        return rules.rental_days(self.start_date, self.end_date)

    @property
    def service_label(self):
        """The service the customer asked for, in words."""
        return dict(SERVICE_CHOICES).get(self.service_type, self.service_type)

    def price_quote(self):
        """What this booking costs at the car's own daily rate.

        A package has its own per-person price, so it is quoted from that
        instead of from the car's day rate. The car is still the vehicle
        the tour runs in; its rate is simply not what the package sells.
        """
        if self.tour_package_id and self.passengers:
            return (
                self.tour_package.price_per_person * self.passengers
            ).quantize(Decimal('0.01'))
        return rules.quote(self.hire_car.rate_for(self.service_type), self.days)

    @property
    def package_label(self):
        """The package name to show on the booking, if it was one."""
        if self.package_name:
            return self.package_name
        if self.tour_package_id:
            return self.tour_package.name
        return ''

    def extras_total(self):
        """What the add-ons on this booking come to."""
        total = sum(
            (extra.line_total(self.days) for extra in self.extras.all()),
            Decimal('0.00'),
        )
        return Decimal(total).quantize(Decimal('0.01'))

    def hire_total(self):
        """The hire itself: the agreed price plus the extras."""
        base = self.quoted_price
        if not base:
            base = self.price_quote()
        return (Decimal(base) + self.extras_total()).quantize(Decimal('0.01'))

    def total_due(self):
        """Everything the customer hands over, the refundable deposit included."""
        return (self.hire_total() + self.security_deposit).quantize(Decimal('0.01'))

    def deposit_state(self):
        """Where the security deposit has got to, in one word."""
        if self.deposit_refunded_at:
            return 'refunded'
        if self.deposit_received_at:
            return 'held'
        return 'due'

    def deposit_to_refund(self):
        """What the customer gets back when the car comes home."""
        refundable = self.security_deposit - self.deposit_retained
        return max(refundable, Decimal('0.00')).quantize(Decimal('0.01'))

    def is_settled(self):
        """True once the money for the booking has been received."""
        return self.payment_status in self.SETTLED_PAYMENT_STATUSES

    @classmethod
    def overlapping(cls, hire_car, start_date, end_date, exclude_pk=None):
        """Bookings on this car that clash with the given dates.

        Rejected and cancelled bookings are left out: they never took
        the car off the yard.
        """
        if not hire_car or not start_date or not end_date:
            return cls.objects.none()
        queryset = cls.objects.filter(
            hire_car=hire_car,
            start_date__lte=end_date,
            end_date__gte=start_date,
        ).exclude(status__in=rules.FREE_STATUSES)
        if exclude_pk:
            queryset = queryset.exclude(pk=exclude_pk)
        return queryset

    @classmethod
    def blocking(cls, hire_car, start_date, end_date, exclude_pk=None):
        """The clashes that stop a booking being made or confirmed.

        A request that clashes with another *request* is allowed: staff
        sort those out themselves. A clash with a booking that is already
        confirmed means the car is already out.
        """
        return cls.overlapping(
            hire_car, start_date, end_date, exclude_pk
        ).filter(status__in=rules.BLOCKING_STATUSES)


class HireBookingAddOn(models.Model):
    """An add-on on one booking, with the price that was quoted.

    The name, price and unit are copied from the catalogue, so a booking
    keeps the price the customer agreed to even if the catalogue changes.
    """

    booking = models.ForeignKey(
        HireBooking,
        on_delete=models.CASCADE,
        related_name='extras',
    )
    add_on = models.ForeignKey(
        HireAddOn,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='booking_lines',
        help_text="Where this line came from; it may be deleted later.",
    )
    name = models.CharField(max_length=100, help_text="The name as quoted.")
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    unit = models.CharField(
        max_length=20,
        choices=ADD_ON_UNIT_CHOICES,
        default='per_day',
    )
    quantity = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )

    class Meta:
        ordering = ['pk']
        verbose_name = "Booking Add-on"
        verbose_name_plural = "Booking Add-ons"

    def __str__(self):
        return f"{self.quantity} x {self.name}"

    def save(self, *args, **kwargs):
        # A new line takes its snapshot from the catalogue; an existing
        # one keeps the price it was quoted at.
        if self.add_on_id and not self.pk:
            add_on = self.add_on
            self.name = add_on.name
            self.unit_price = add_on.price
            self.unit = add_on.unit
        super().save(*args, **kwargs)

    def line_total(self, days=None):
        """What this line adds to the bill."""
        if days is None:
            days = self.booking.days if self.booking_id else 0
        multiplier = days if self.unit == 'per_day' else 1
        total = self.unit_price * max(self.quantity, 0) * max(int(multiplier), 0)
        return Decimal(total).quantize(Decimal('0.01'))
