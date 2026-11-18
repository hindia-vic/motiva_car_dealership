from django import forms
from django.contrib import admin
from django.utils.html import format_html
from .images import validate_image_upload
from .models import (
    Car, CarImage, Inventory, Customer, SalesTransaction, ServiceRecord, Inquiry, Order,
    Appointment, ContactMessage, NewsletterSubscription, Testimonial, ContactInfo,
    SavedSearch, Post, AboutInfo, CarPriceHistory, CarStatusHistory, DealershipInfo,
    ChatSession, ChatMessage, ListingRequest, ListingRequestPhoto,
    FinancingApplication,
)


class CarImageAdminForm(forms.ModelForm):
    """Checks a newly uploaded photo before it is stored.

    The thumbnail is not editable: it is generated from the photo itself.
    """

    class Meta:
        model = CarImage
        fields = ('image', 'caption', 'is_primary')

    def clean_image(self):
        image = self.cleaned_data.get('image')
        # Only a file that was just chosen is checked; an existing photo
        # that was uploaded before the limits existed is left alone.
        if image and 'image' in self.changed_data:
            validate_image_upload(image)
        return image


class CarImageInline(admin.TabularInline):
    model = CarImage
    extra = 1
    fields = ('image', 'caption', 'is_primary')
    form = CarImageAdminForm


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    list_display = ('year', 'make', 'model', 'vin', 'condition', 'status', 'asking_price', 'mileage')
    list_filter = ('status', 'condition', 'year', 'body_type', 'fuel_type')
    search_fields = ('make', 'model', 'vin', 'color')
    inlines = [CarImageInline]
    fieldsets = (
        ('Basic Information', {
            'fields': ('make', 'model', 'year', 'vin', 'color', 'body_type')
        }),
        ('Transmission & Engine', {
            'fields': ('transmission', 'fuel_type', 'engine_size', 'horsepower', 'mileage')
        }),
        ('Pricing', {
            'fields': ('purchase_price', 'asking_price')
        }),
        ('Status', {
            'fields': ('condition', 'status')
        }),
        ('Features', {
            'fields': ('air_conditioning', 'power_steering', 'power_windows', 'power_locks',
                      'cruise_control', 'backup_camera', 'bluetooth', 'navigation_system',
                      'leather_seats', 'sunroof', 'all_wheel_drive'),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('description',),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('date_added', 'last_updated')


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('car', 'quantity_in_stock', 'reorder_level', 'location', 'is_low_stock')
    list_filter = ('quantity_in_stock',)
    search_fields = ('car__make', 'car__model', 'location')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'email', 'phone_number', 'city', 'is_active')
    list_filter = ('is_active', 'date_registered', 'state')
    search_fields = ('first_name', 'last_name', 'email', 'phone_number')
    fieldsets = (
        ('Personal Information', {
            'fields': ('first_name', 'last_name', 'email', 'phone_number', 'gender', 'date_of_birth')
        }),
        ('Address', {
            'fields': ('address', 'city', 'state', 'zip_code', 'country')
        }),
        ('Financial Information', {
            'fields': ('credit_score', 'preferred_financing'),
            'classes': ('collapse',)
        }),
        ('Account Information', {
            'fields': ('is_active', 'date_registered', 'notes'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('date_registered',)


@admin.register(SalesTransaction)
class SalesTransactionAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'customer', 'car', 'sale_date', 'sale_price', 'status')
    list_filter = ('status', 'payment_method', 'sale_date')
    search_fields = ('invoice_number', 'customer__first_name', 'customer__last_name', 'car__vin')
    fieldsets = (
        ('Sale Information', {
            'fields': ('invoice_number', 'sale_date', 'status', 'salesperson')
        }),
        ('Parties', {
            'fields': ('customer', 'car', 'order')
        }),
        ('Pricing', {
            'fields': ('sale_price', 'trade_in_value', 'down_payment', 'total_amount')
        }),
        ('Payment', {
            'fields': ('payment_method',)
        }),
        ('Financing', {
            'fields': ('financed_amount', 'interest_rate', 'loan_term_months'),
            'classes': ('collapse',)
        }),
        ('Additional Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('sale_date',)


@admin.register(ServiceRecord)
class ServiceRecordAdmin(admin.ModelAdmin):
    list_display = ('car', 'service_date', 'service_type', 'cost', 'technician')
    list_filter = ('service_type', 'service_date')
    search_fields = ('car__make', 'car__model', 'car__vin', 'technician', 'description')
    fieldsets = (
        ('Service Information', {
            'fields': ('car', 'service_date', 'service_type')
        }),
        ('Details', {
            'fields': ('description', 'odometer_reading', 'cost', 'technician')
        }),
    )
    readonly_fields = ('service_date',)


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ('customer_name', 'car', 'customer_email', 'status', 'created_at', 'source')
    list_filter = ('status', 'created_at', 'car')
    search_fields = ('customer_name', 'customer_email', 'customer_phone', 'car__make', 'car__model')
    fieldsets = (
        ('Inquiry Information', {
            'fields': ('car', 'status')
        }),
        ('Customer Information', {
            'fields': ('customer_name', 'customer_email', 'customer_phone')
        }),
        ('Message', {
            'fields': ('message',)
        }),
        ('Attribution', {
            'description': 'Where this inquiry came from.',
            'fields': ('source', 'visitor_id'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('created_at', 'updated_at', 'source', 'visitor_id')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'customer_name', 'car', 'order_date', 'status',
        'price', 'payment_status', 'amount_paid', 'source',
    )
    list_filter = ('status', 'payment_status', 'order_date', 'financing_needed')
    search_fields = ('customer_name', 'customer_email', 'customer_phone', 'car__make', 'car__model')
    fieldsets = (
        ('Order Information', {
            'fields': ('car', 'order_date', 'status')
        }),
        ('Customer Information', {
            'fields': ('customer_name', 'customer_email', 'customer_phone', 'customer_address')
        }),
        ('Purchase Details', {
            'fields': ('price', 'trade_in_value', 'financing_needed', 'down_payment')
        }),
        ('Payment', {
            'description': (
                'The deposit is quoted when the order is placed. Payments are '
                'recorded by M-Pesa; staff cannot mark one successful by hand.'
            ),
            'fields': (
                'payment_status', 'deposit_amount', 'amount_paid',
                'deposit_paid_at', 'payment_reference',
            ),
        }),
        ('Trade-In Claim', {
            'description': 'What the customer told us about the vehicle they are trading in.',
            'fields': (
                'trade_in_year', 'trade_in_make', 'trade_in_model',
                'trade_in_mileage', 'trade_in_condition', 'trade_in_body_type',
                'trade_in_estimate',
            ),
            'classes': ('collapse',),
        }),
        ('Attribution', {
            'description': 'Where this order came from.',
            'fields': ('source', 'visitor_id'),
            'classes': ('collapse',),
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = (
        'order_date', 'trade_in_estimate', 'source', 'visitor_id',
        'payment_status', 'amount_paid', 'deposit_paid_at', 'payment_reference',
    )


@admin.register(CarImage)
class CarImageAdmin(admin.ModelAdmin):
    list_display = ('thumbnail', 'car', 'caption', 'is_primary', 'uploaded_at')
    list_filter = ('is_primary', 'uploaded_at')
    search_fields = ('car__make', 'car__model', 'car__vin', 'caption')
    list_display_links = ('thumbnail',)
    form = CarImageAdminForm

    def thumbnail(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 80px; height: 60px; object-fit: cover; border-radius: 4px;" />',
                obj.thumbnail_url(),
            )
        return "No image"
    thumbnail.short_description = 'Preview'


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('car', 'customer_name', 'preferred_date', 'preferred_time', 'status', 'created_at', 'source')
    list_filter = ('status', 'preferred_date')
    search_fields = ('customer_name', 'customer_email', 'customer_phone', 'car__make', 'car__model')
    readonly_fields = ('created_at', 'updated_at', 'source', 'visitor_id')


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('subject', 'name', 'email', 'sent_at')
    list_filter = ('sent_at',)
    search_fields = ('name', 'email', 'subject', 'message')
    readonly_fields = ('sent_at',)


@admin.register(NewsletterSubscription)
class NewsletterSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('email', 'is_active', 'subscribed_at')
    list_filter = ('is_active', 'subscribed_at')
    search_fields = ('email',)


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ('customer_name', 'vehicle', 'rating', 'is_visible', 'created_at')
    list_filter = ('is_visible', 'rating')
    search_fields = ('customer_name', 'vehicle', 'quote')


@admin.register(ContactInfo)
class ContactInfoAdmin(admin.ModelAdmin):
    list_display = ('phone', 'email', 'whatsapp', 'address')


@admin.register(AboutInfo)
class AboutInfoAdmin(admin.ModelAdmin):
    list_display = ('page_tagline', 'value_one_title', 'value_two_title', 'value_three_title')


@admin.register(DealershipInfo)
class DealershipInfoAdmin(admin.ModelAdmin):
    list_display = ('name', 'logo')


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    can_delete = False
    fields = ('sender', 'text', 'intent', 'created_at')
    readonly_fields = ('sender', 'text', 'intent', 'created_at')


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('session_key', 'user', 'is_escalated', 'message_count', 'created_at', 'last_activity_at')
    list_filter = ('is_escalated', 'created_at')
    search_fields = ('session_key', 'user__username', 'user__email')
    readonly_fields = ('session_key', 'user', 'ip_address', 'created_at', 'last_activity_at')
    inlines = [ChatMessageInline]


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ('email', 'summary', 'is_active', 'notify_price_drops', 'created_at', 'last_checked_at')
    list_filter = ('is_active', 'notify_price_drops', 'created_at')
    search_fields = ('email', 'make', 'model')


@admin.register(CarPriceHistory)
class CarPriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('car', 'old_price', 'new_price', 'changed_at', 'notified_at')
    list_filter = ('changed_at', 'notified_at')
    search_fields = ('car__make', 'car__model', 'car__vin')
    readonly_fields = ('car', 'old_price', 'new_price', 'changed_at', 'notified_at')


@admin.register(CarStatusHistory)
class CarStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('car', 'old_status', 'new_status', 'changed_at', 'notified_at')
    list_filter = ('old_status', 'new_status', 'changed_at', 'notified_at')
    search_fields = ('car__make', 'car__model', 'car__vin')
    readonly_fields = ('car', 'old_status', 'new_status', 'changed_at', 'notified_at')


class ListingRequestPhotoInline(admin.TabularInline):
    model = ListingRequestPhoto
    extra = 0
    fields = ('kind', 'photo', 'thumbnail', 'uploaded_at')
    readonly_fields = ('thumbnail', 'uploaded_at')


@admin.register(ListingRequest)
class ListingRequestAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'year', 'make', 'model', 'owner_name', 'status',
        'payment_status', 'created_at',
    )
    list_filter = ('status', 'payment_status', 'vehicle_verified', 'logbook_verified')
    search_fields = ('reference', 'vin', 'make', 'model', 'owner_name', 'owner_email')
    readonly_fields = ('reference', 'created_at', 'updated_at')
    inlines = [ListingRequestPhotoInline]
    fieldsets = (
        ('Reference', {
            'fields': ('reference', 'user', 'status', 'created_at', 'updated_at')
        }),
        ('The owner', {
            'fields': ('owner_name', 'owner_email', 'owner_phone')
        }),
        ('The car', {
            'fields': ('make', 'model', 'year', 'vin', 'color', 'body_type',
                       'transmission', 'fuel_type', 'mileage', 'engine_size',
                       'asking_price', 'description')
        }),
        ('The logbook', {
            'fields': ('logbook_number', 'logbook_owner_name', 'logbook_verified')
        }),
        ('Verification', {
            'fields': ('vehicle_verified', 'staff_notes')
        }),
        ('The fee', {
            'fields': ('fee_amount', 'payment_status', 'payment_reference', 'payment_received_at')
        }),
        ('The listing', {
            'fields': ('car', 'rejection_reason', 'reviewed_by', 'reviewed_at')
        }),
    )


@admin.register(ListingRequestPhoto)
class ListingRequestPhotoAdmin(admin.ModelAdmin):
    list_display = ('preview', 'request', 'kind', 'uploaded_at')
    list_filter = ('kind', 'uploaded_at')
    search_fields = ('request__reference', 'request__vin')
    readonly_fields = ('thumbnail', 'uploaded_at')

    def preview(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="width: 80px; height: 60px; object-fit: cover; border-radius: 4px;" />',
                obj.thumbnail_url(),
            )
        return "No image"
    preview.short_description = 'Preview'


@admin.register(FinancingApplication)
class FinancingApplicationAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'customer_name', 'vehicle_label', 'requested_amount',
        'status', 'created_at',
    )
    list_filter = ('status', 'employment_status', 'created_at')
    search_fields = ('reference', 'customer_name', 'customer_email',
                     'customer_phone', 'car_label')
    readonly_fields = (
        'reference', 'requested_amount', 'estimated_monthly', 'interest_rate',
        'created_at', 'updated_at',
    )
    fieldsets = (
        ('Reference', {
            'fields': ('reference', 'user', 'status', 'created_at', 'updated_at')
        }),
        ('The customer', {
            'fields': ('customer_name', 'customer_email', 'customer_phone')
        }),
        ('Employment', {
            'fields': ('employment_status', 'employer_name', 'job_title',
                       'monthly_income', 'monthly_expenses')
        }),
        ('The deal', {
            'fields': ('car', 'car_label', 'price', 'deposit_amount',
                       'trade_in_value', 'loan_term_months', 'interest_rate',
                       'requested_amount', 'estimated_monthly')
        }),
        ('The decision', {
            'fields': ('approved_amount', 'approved_term_months',
                       'decision_notes', 'decline_reason',
                       'reviewed_by', 'reviewed_at')
        }),
    )


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'published_at', 'is_published')
    list_filter = ('is_published', 'published_at')
    search_fields = ('title', 'excerpt', 'body')
    prepopulated_fields = {'slug': ('title',)}
    fieldsets = (
        ('Content', {
            'fields': ('title', 'slug', 'excerpt', 'body', 'cover_image')
        }),
        ('Publication', {
            'fields': ('is_published', 'published_at'),
        }),
    )

