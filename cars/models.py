from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone

def upload_to_cars(instance, filename):
    return f"cars/car_{instance.car_id}/{filename}"


class Car(models.Model):
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
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    asking_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    
    # Status and Condition
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='used')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    
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
    
    def is_available(self):
        return self.status == 'available'


class CarImage(models.Model):
    """Photo for a car, uploaded by staff"""
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to=upload_to_cars)
    caption = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(default=False, help_text="Main photo shown on car cards")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'id']
        verbose_name = "Car Image"
        verbose_name_plural = "Car Images"

    def __str__(self):
        return f"Image for {self.car} ({self.caption or 'no caption'})"

    def save(self, *args, **kwargs):
        if self.is_primary:
            CarImage.objects.filter(car=self.car, is_primary=True)\
                            .exclude(pk=self.pk)\
                            .update(is_primary=False)
        super().save(*args, **kwargs)


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
    salesperson = models.CharField(max_length=200, blank=True, help_text="Name of salesperson")
    
    # Transaction Details
    sale_date = models.DateTimeField(default=timezone.now)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2)
    trade_in_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    down_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Payment
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Financing (if applicable)
    financed_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Annual interest rate %")
    loan_term_months = models.IntegerField(null=True, blank=True)
    
    # Documentation
    invoice_number = models.CharField(max_length=50, unique=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-sale_date']
    
    def __str__(self):
        return f"Sale #{self.invoice_number} - {self.car} to {self.customer}"
    
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
    
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='service_records')
    service_date = models.DateTimeField(default=timezone.now)
    service_type = models.CharField(max_length=50, choices=SERVICE_TYPE_CHOICES)
    description = models.TextField()
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    odometer_reading = models.IntegerField()
    technician = models.CharField(max_length=200, blank=True)
    
    class Meta:
        ordering = ['-service_date']
    
    def __str__(self):
        return f"Service for {self.car} on {self.service_date.date()}"


class Inquiry(models.Model):
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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Inquiries"
    
    def __str__(self):
        return f"Inquiry for {self.car} from {self.customer_name}"


class Order(models.Model):
    """Customer order/purchase request for a vehicle"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing'),
        ('ready_for_pickup', 'Ready for Pickup'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
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
    price = models.DecimalField(max_digits=10, decimal_places=2)
    trade_in_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    financing_needed = models.BooleanField(default=False)
    down_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Contact/Notes
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-order_date']
    
    def __str__(self):
        return f"Order #{self.id} - {self.car} by {self.customer_name}"
    
    def get_total_price(self):
        """Calculate total price after trade-in"""
        return self.price - self.trade_in_value


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


class Appointment(models.Model):
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
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=150)
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']

    def __str__(self):
        return f"{self.subject} - {self.name}"


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
    hours = models.TextField(default='Mon – Sat: 9:00 AM – 7:00 PM\nSunday: Closed')

    class Meta:
        verbose_name = 'Contact Info'

    def __str__(self):
        return f'Contact Info ({self.phone})'

    @classmethod
    def get_solo(cls):
        """Return the singleton row, creating it with defaults if missing"""
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance


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
    price_min = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    body_type = models.CharField(max_length=50, blank=True)
    fuel_type = models.CharField(max_length=20, blank=True)
    transmission = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Saved search for {self.email} ({self.summary()})'

    def summary(self):
        """"Year 2020–2024, Toyota, under $25000" style one-line description"""
        parts = []
        if self.make:
            parts.append(self.make)
        if self.model:
            parts.append(self.model)
        if self.year_min or self.year_max:
            parts.append(f"year {self.year_min or '…'}–{self.year_max or '…'}")
        if self.price_min or self.price_max:
            parts.append(f"${self.price_min or '…'}–${self.price_max or '…'}")
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
