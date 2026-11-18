"""Admin for car hire and tours & travel."""

from django.contrib import admin

from .models import HireAddOn, HireBooking, HireBookingAddOn, HireCar, HireCarImage


class HireCarImageInline(admin.TabularInline):
    model = HireCarImage
    extra = 1


@admin.register(HireCar)
class HireCarAdmin(admin.ModelAdmin):
    list_display = [
        'make', 'model', 'year', 'body_type', 'transmission',
        'hire_daily_rate', 'tour_daily_rate', 'allows_tours', 'status',
    ]
    list_filter = ['status', 'allows_tours', 'body_type', 'transmission', 'fuel_type']
    search_fields = ['make', 'model']
    inlines = [HireCarImageInline]


@admin.register(HireAddOn)
class HireAddOnAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'unit', 'is_active', 'sort_order']
    list_filter = ['is_active', 'unit']
    search_fields = ['name', 'description']
    ordering = ['sort_order', 'name']


class HireBookingAddOnInline(admin.TabularInline):
    model = HireBookingAddOn
    extra = 0
    fields = ['add_on', 'name', 'unit_price', 'unit', 'quantity']
    readonly_fields = ['name', 'unit_price', 'unit']


@admin.register(HireBooking)
class HireBookingAdmin(admin.ModelAdmin):
    list_display = [
        'reference', 'hire_car', 'customer_name', 'service_type',
        'start_date', 'end_date', 'quoted_price', 'security_deposit',
        'status', 'payment_status',
    ]
    list_filter = ['status', 'payment_status', 'service_type']
    search_fields = [
        'reference', 'customer_name', 'customer_email', 'customer_phone',
        'hire_car__make', 'hire_car__model',
    ]
    readonly_fields = ['reference', 'created_at', 'updated_at', 'reviewed_at']
    date_hierarchy = 'start_date'
    inlines = [HireBookingAddOnInline]
