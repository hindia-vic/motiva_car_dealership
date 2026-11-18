"""Custom admin site: only superusers may sign in to or use Django admin.

Staff accounts (``is_staff=True``) are used by the site's own staff area but
must not be able to reach the admin. This subclass tightens the admin gate
from ``is_staff`` to ``is_superuser`` and rejects non-superusers at the admin
login form as well.

When staff two-factor authentication is enabled, the admin login form is
bypassed entirely: anonymous visitors are sent through the site's own sign-in
so a superuser cannot skip the emailed one-time code by using the admin login.

This module is imported lazily by Django (via ``SuperuserAdminConfig.default_site``
in config/apps.py) once the app registry is ready, so importing auth/admin
forms at module level here is safe.
"""
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse


class SuperuserAdminAuthenticationForm(AdminAuthenticationForm):
    """Reject non-superusers at the admin login form."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_superuser:
            raise ValidationError(
                self.error_messages["invalid_login"],
                code="invalid_login",
                params={"username": self.username_field.verbose_name},
            )


class SuperuserAdminSite(AdminSite):
    """Admin site restricted to active superusers."""

    login_form = SuperuserAdminAuthenticationForm

    def has_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def login(self, request, extra_context=None):
        """Route anonymous admin sign-ins through the 2FA-aware site login."""
        if not request.user.is_authenticated and settings.STAFF_2FA_ENABLED:
            target = request.GET.get('next') or reverse('admin:index')
            return redirect(
                f"{reverse('accounts:login')}?{urlencode({'next': target})}"
            )
        return super().login(request, extra_context)
