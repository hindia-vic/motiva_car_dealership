"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include
from django.views.generic import TemplateView

from cars.sitemaps import CarSitemap, PostSitemap, StaticViewSitemap
from config.views import health, preview_404
from hiring.sitemaps import HireCarSitemap

sitemaps = {
    'pages': StaticViewSitemap,
    'cars': CarSitemap,
    'posts': PostSitemap,
    'hire': HireCarSitemap,
}

urlpatterns = [
    # The path comes from ADMIN_URL so production can move it somewhere
    # unguessable; the reverse name stays ``admin:index`` everywhere else.
    path(settings.ADMIN_URL.lstrip('/'), admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('notifications/', include('notifications.urls')),
    path('payments/', include('payments.urls')),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),
    # Liveness probe for platform/uptime monitors (no trailing slash on purpose,
    # so /health returns 200 directly instead of a redirect).
    path('health', health, name='health'),
    path('traffic/', include('traffic.urls')),
    path('', include('hiring.urls')),
    path('', include('cars.urls')),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    # Lets you see the branded 404 while developing; Django's technical 404
    # page replaces it whenever DEBUG is on. Not exposed in production.
    urlpatterns += [path('404-preview/', preview_404, name='preview_404')]

