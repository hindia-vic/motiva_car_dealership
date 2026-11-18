"""Sitemap entries for the public car hire pages."""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import HireCar


class HireCarSitemap(Sitemap):
    """Every hire car detail page"""
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return HireCar.objects.filter(status__in=HireCar.PUBLIC_STATUSES)

    def location(self, obj):
        return reverse('hiring:hire_car_detail', args=[obj.pk])

    def lastmod(self, obj):
        return obj.updated_at
