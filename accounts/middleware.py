from django.shortcuts import redirect
from django.urls import reverse


class MustChangePasswordMiddleware:
    """Force users flagged with must_change_password to change it before
    going anywhere else. Interrupts every request for affected users except
    the password-change flow itself and logout."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile = getattr(request.user, 'profile', None)
            if profile is not None and profile.must_change_password:
                change_url = reverse('accounts:password_change')
                logout_url = reverse('accounts:logout')
                if request.path not in (change_url, logout_url):
                    return redirect(change_url)
        return self.get_response(request)