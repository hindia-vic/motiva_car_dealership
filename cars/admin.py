from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Car, CarImage, Inventory, Customer, SalesTransaction, ServiceRecord, Inquiry, Order,
    Appointment, ContactMessage, NewsletterSubscription, Testimonial, ContactInfo,
    SavedSearch, Post, AboutInfo,
)


class CarImageInline(admin.TabularInline):
    model = CarImage
    extra = 1
    fields = ('image', 'caption', 'is_primary')


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
            'fields': ('customer', 'car')
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
    list_display = ('customer_name', 'car', 'customer_email', 'status', 'created_at')
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
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer_name', 'car', 'order_date', 'status', 'price')
    list_filter = ('status', 'order_date', 'financing_needed')
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
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('order_date',)


@admin.register(CarImage)
class CarImageAdmin(admin.ModelAdmin):
    list_display = ('thumbnail', 'car', 'caption', 'is_primary', 'uploaded_at')
    list_filter = ('is_primary', 'uploaded_at')
    search_fields = ('car__make', 'car__model', 'car__vin', 'caption')
    list_display_links = ('thumbnail',)

    def thumbnail(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 80px; height: 60px; object-fit: cover; border-radius: 4px;" />',
                obj.image.url,
            )
        return "No image"
    thumbnail.short_description = 'Preview'


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('car', 'customer_name', 'preferred_date', 'preferred_time', 'status', 'created_at')
    list_filter = ('status', 'preferred_date')
    search_fields = ('customer_name', 'customer_email', 'customer_phone', 'car__make', 'car__model')
    readonly_fields = ('created_at', 'updated_at')


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
    list_display = ('phone', 'email', 'address')


@admin.register(AboutInfo)
class AboutInfoAdmin(admin.ModelAdmin):
    list_display = ('page_tagline', 'value_one_title', 'value_two_title', 'value_three_title')


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ('email', 'summary', 'is_active', 'created_at', 'last_checked_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('email', 'make', 'model')


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

