"""Sitemap definitions for the public pages of the dealership site"""
from django.contrib.sitemaps import Sitemap
from django.db.models import Max
from django.urls import reverse

from .models import Car, Post


PUBLIC_PAGES = [
    'cars:home',
    'cars:browse_cars',
    'cars:advanced_search',
    'cars:about',
    'cars:contact',
    'cars:reviews',
    'cars:financing',
    'cars:financing_apply',
    'cars:faq',
    'cars:blog_list',
    'cars:trade_in',
    'cars:service_booking',
    'cars:privacy_policy',
    'cars:terms_of_service',
    'hiring:hire_car_list',
    'hiring:hire_tours',
]


def latest_public_content_update():
    """When the public site last changed, or ``None`` when it is empty.

    Static pages have no row of their own to date, so they borrow the newest
    inventory or article change. A crawler revisits them after a new car or
    post goes live rather than on a made-up weekly schedule.
    """
    newest_car = Car.objects.filter(
        status__in=Car.PUBLIC_STATUSES
    ).aggregate(Max('last_updated'))['last_updated__max']
    newest_post = Post.objects.filter(
        is_published=True
    ).aggregate(Max('updated_at'))['updated_at__max']
    return max((value for value in (newest_car, newest_post) if value), default=None)


class StaticViewSitemap(Sitemap):
    """Static informational pages (home, about, financing, FAQ, blog, ...)"""
    priority = 0.6
    changefreq = 'weekly'

    def items(self):
        return PUBLIC_PAGES

    def location(self, item):
        return reverse(item)

    def lastmod(self, item):
        # Resolved once per sitemap instance, not once per URL.
        if not hasattr(self, '_lastmod'):
            self._lastmod = latest_public_content_update()
        return self._lastmod


class CarSitemap(Sitemap):
    """Every vehicle detail page"""
    priority = 0.9
    changefreq = 'daily'

    def items(self):
        # Reserved and maintenance vehicles are not advertised, so they must
        # not be handed to search engines either. Sold cars stay in the map so
        # old links keep resolving.
        return Car.objects.filter(status__in=Car.PUBLIC_STATUSES)

    def location(self, obj):
        return reverse('cars:car_detail', args=[obj.pk])

    def lastmod(self, obj):
        return obj.last_updated


class PostSitemap(Sitemap):
    """Published blog/news articles"""
    priority = 0.5
    changefreq = 'weekly'

    def items(self):
        return Post.objects.filter(is_published=True)

    def location(self, obj):
        return reverse('cars:blog_detail', args=[obj.slug])

    def lastmod(self, obj):
        return obj.updated_at