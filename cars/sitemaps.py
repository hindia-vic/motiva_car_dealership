"""Sitemap definitions for the public pages of the dealership site"""
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Car, Post


PUBLIC_PAGES = [
    'cars:home',
    'cars:browse_cars',
    'cars:about',
    'cars:contact',
    'cars:reviews',
    'cars:financing',
    'cars:faq',
    'cars:blog_list',
]


class StaticViewSitemap(Sitemap):
    """Static informational pages (home, about, financing, FAQ, blog, ...)"""
    priority = 0.6
    changefreq = 'weekly'

    def items(self):
        return PUBLIC_PAGES

    def location(self, item):
        return reverse(item)


class CarSitemap(Sitemap):
    """Every vehicle detail page"""
    priority = 0.9
    changefreq = 'daily'

    def items(self):
        return Car.objects.all()

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