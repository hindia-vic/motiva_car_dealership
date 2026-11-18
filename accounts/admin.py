from django.contrib import admin

from .models import Favorite, Profile


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ['user', 'car', 'price_at_save', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'user__email', 'car__make', 'car__model']
    autocomplete_fields = ['car']


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'must_change_password', 'notify_price_drops', 'notify_back_in_stock']
    list_filter = ['must_change_password', 'notify_price_drops', 'notify_back_in_stock']
    search_fields = ['user__username', 'user__email']