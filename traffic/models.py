"""Models for the traffic analytics app.

One row per tracked page view. Unique visitors are derived with a ``DISTINCT``
on ``visitor_id`` rather than a second table, so there is nothing extra to keep
in sync when a visitor comes back.
"""

from django.conf import settings
from django.db import models


class PageView(models.Model):
    """A single page view recorded by the traffic tracking middleware.

    Only public pages are recorded. Staff browsing the staff panel is
    skipped, and bot user agents are filtered out, so the numbers on the
    Traffic dashboard reflect prospective customers.
    """

    path = models.CharField(
        max_length=255,
        help_text="Requested path, e.g. /browse/",
    )
    url_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Resolved view name, e.g. car_detail",
    )
    car = models.ForeignKey(
        'cars.Car',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='page_views',
        help_text="Set for vehicle detail pages so staff can see the most viewed cars",
    )

    # Who was watching
    visitor_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Anonymous visitor token from the first-party cookie",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='page_views',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)

    # Where they came from
    referrer = models.CharField(max_length=500, blank=True)
    source = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Google, Direct, Facebook, ...",
    )
    utm_source = models.CharField(max_length=100, blank=True)
    utm_medium = models.CharField(max_length=100, blank=True)
    utm_campaign = models.CharField(max_length=150, blank=True)

    # What they were on
    device = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        help_text="Desktop, Mobile or Tablet",
    )
    browser = models.CharField(max_length=40, blank=True)

    status_code = models.PositiveSmallIntegerField(default=200)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Page view'
        verbose_name_plural = 'Page views'
        indexes = [
            models.Index(fields=['visitor_id', 'created_at']),
            models.Index(fields=['source', 'created_at']),
        ]

    def __str__(self):
        who = self.user.get_username() if self.user_id else self.visitor_id[:8]
        return f'{self.path} by {who} at {self.created_at:%Y-%m-%d %H:%M}'
