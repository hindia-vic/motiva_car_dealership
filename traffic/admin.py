from django.contrib import admin

from .models import PageView


@admin.register(PageView)
class PageViewAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'path',
        'url_name',
        'source',
        'device',
        'browser',
        'visitor_id',
        'user',
        'ip_address',
    )
    list_filter = ('source', 'device', 'browser', 'status_code', 'created_at')
    search_fields = ('path', 'visitor_id', 'ip_address', 'referrer', 'utm_campaign')
    date_hierarchy = 'created_at'
    list_select_related = ('user', 'car')
    readonly_fields = (
        'path', 'url_name', 'car', 'visitor_id', 'user', 'ip_address',
        'referrer', 'source', 'utm_source', 'utm_medium', 'utm_campaign',
        'device', 'browser', 'status_code', 'created_at',
    )

    def has_add_permission(self, request):
        # Rows are created by the tracking middleware, never by hand.
        return False

    def has_change_permission(self, request, obj=None):
        return False
