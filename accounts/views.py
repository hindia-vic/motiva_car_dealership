import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.encoding import force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views import View
from django.views.generic import CreateView, ListView

from cars.models import Car

from .emails import (
    send_staff_account_email, send_staff_two_factor_email, send_verification_email,
)
from .forms import (
    LoginForm, ProfileForm, RegisterForm, StaffUserCreateForm,
    StyledPasswordChangeForm,
)
from .models import Favorite, Profile


class RegisterView(CreateView):
    """Customer-facing account registration (requires email verification)"""
    form_class = RegisterForm
    template_name = 'accounts/register.html'

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.is_active = False
        self.object.save()
        form.save_m2m()
        send_verification_email(self.object, self.request)
        self.request.session['verification_email'] = self.object.email
        messages.info(
            self.request,
            'Almost there! Check your inbox for a link to verify your email address.',
        )
        return redirect('accounts:verify_email_sent')


def verify_email_sent(request):
    """Confirmation page shown after registration: check your inbox"""
    email = request.session.get('verification_email', '')
    return render(request, 'accounts/verify_email_sent.html', {'email': email})


def verify_email(request, uidb64, token):
    """Activate the account when the emailed verification link is opened.

    Also re-verifies an already-active user who changed their email address.
    """
    user = None
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = get_user_model().objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, ValidationError, ObjectDoesNotExist):
        user = None

    profile = None
    if user is not None:
        profile, _ = Profile.objects.get_or_create(user=user)

    if (
        user is not None
        and profile is not None
        and default_token_generator.check_token(user, token)
        and (not user.is_active or not profile.email_verified)
    ):
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])
        if not profile.email_verified:
            profile.email_verified = True
            profile.save(update_fields=['email_verified'])
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, f'Your email is verified, {user.first_name or user.username}!')
        return redirect('cars:home')

    request.session['verification_email'] = getattr(user, 'email', '') or request.session.get('verification_email', '')
    messages.error(request, 'This verification link is invalid or has expired.')
    return redirect('accounts:verify_email_invalid')


def verify_email_invalid(request):
    """Shown when a verification link is invalid or expired"""
    email = request.session.get('verification_email', '')
    return render(request, 'accounts/verify_email_invalid.html', {'email': email})


def resend_verification(request):
    """Resend the verification email (POST only)"""
    if request.method != 'POST':
        return redirect('accounts:login')

    email = (request.POST.get('email') or '').strip().lower()
    user = None
    if email:
        user = (
            User.objects.filter(email__iexact=email, is_active=False)
            .select_related('profile')
            .first()
        )

    # Same message either way so the form never reveals whether an account exists
    if user is not None and not user.is_staff:
        profile, _ = Profile.objects.get_or_create(user=user)
        if not profile.email_verified:
            send_verification_email(user, request)
            request.session['verification_email'] = user.email

    messages.info(request, 'If that address has a pending account, a new verification link is on its way.')
    return redirect('accounts:verify_email_sent')


# ---- Staff two-factor authentication ---------------------------------------
#
# Staff accounts can read customer records and payment references, so a
# password alone is not enough in production. After the password is accepted
# (or Google has verified the address) the sign-in pauses: a six-digit code is
# emailed to the account, hashed into the session, and must be entered before
# ``login()`` is called. Nothing about the user is trusted from the session
# beyond the primary key.

STAFF_2FA_SESSION_KEY = 'staff_2fa'


def _staff_2fa_required(user):
    """Whether this sign-in must clear the email second factor."""
    return bool(
        settings.STAFF_2FA_ENABLED
        and user is not None
        and user.is_staff
        and (user.email or '').strip()
    )


def _masked_email(email):
    local, _, domain = (email or '').partition('@')
    if not domain:
        return email or ''
    visible = local[:1] or '*'
    return f'{visible}***@{domain}'


def _issue_staff_2fa_code(request, user, next_url=''):
    """Create a fresh code, store only its hash, and email the code."""
    code = f'{secrets.randbelow(1_000_000):06d}'
    now = timezone.now().timestamp()
    request.session[STAFF_2FA_SESSION_KEY] = {
        'user_id': user.pk,
        'code_hash': salted_hmac(
            'accounts.staff-2fa', code, secret=settings.SECRET_KEY,
            algorithm='sha256',
        ).hexdigest(),
        'expires_at': now + settings.STAFF_2FA_TIMEOUT,
        'sent_at': now,
        'attempts': 0,
        'next': next_url or '',
    }
    return send_staff_two_factor_email(user, code)


class StaffAwareLoginView(LoginView):
    """Django's login view, paused for staff who still need their email code."""

    template_name = 'accounts/login.html'
    authentication_form = LoginForm

    def form_valid(self, form):
        user = form.get_user()
        if _staff_2fa_required(user):
            if not _issue_staff_2fa_code(self.request, user, self.get_success_url()):
                messages.error(
                    self.request,
                    'We could not send your sign-in code. Please try again.',
                )
                return redirect('accounts:login')
            messages.info(
                self.request,
                f'A six-digit code was sent to {_masked_email(user.email)}.',
            )
            return redirect('accounts:staff_2fa')
        return super().form_valid(form)


class StaffTwoFactorView(View):
    """Second step of the staff sign-in: check the emailed one-time code."""

    template_name = 'accounts/staff_two_factor.html'

    def _challenge(self, request):
        data = request.session.get(STAFF_2FA_SESSION_KEY)
        return data if isinstance(data, dict) else None

    def _context(self, challenge):
        user = User.objects.filter(pk=challenge.get('user_id')).only('email').first()
        return {'email': _masked_email(user.email) if user else ''}

    def get(self, request):
        challenge = self._challenge(request)
        if challenge is None:
            return redirect('accounts:login')
        return render(request, self.template_name, self._context(challenge))

    def post(self, request):
        challenge = self._challenge(request)
        if challenge is None:
            return redirect('accounts:login')

        now = timezone.now().timestamp()

        if request.POST.get('action') == 'resend':
            return self._resend(request, challenge, now)

        if now > float(challenge.get('expires_at', 0)):
            request.session.pop(STAFF_2FA_SESSION_KEY, None)
            messages.error(request, 'That code has expired. Please sign in again.')
            return redirect('accounts:login')

        attempts = int(challenge.get('attempts', 0)) + 1
        if attempts > settings.STAFF_2FA_MAX_ATTEMPTS:
            request.session.pop(STAFF_2FA_SESSION_KEY, None)
            messages.error(request, 'Too many incorrect codes. Please sign in again.')
            return redirect('accounts:login')

        code = (request.POST.get('code') or '').strip().replace(' ', '')
        expected = salted_hmac(
            'accounts.staff-2fa', code, secret=settings.SECRET_KEY,
            algorithm='sha256',
        ).hexdigest()
        if not constant_time_compare(expected, challenge.get('code_hash', '')):
            challenge['attempts'] = attempts
            request.session[STAFF_2FA_SESSION_KEY] = challenge
            messages.error(request, 'That code is not correct. Please try again.')
            return render(
                request, self.template_name, self._context(challenge),
            )

        user = User.objects.filter(
            pk=challenge.get('user_id'), is_active=True, is_staff=True,
        ).first()
        request.session.pop(STAFF_2FA_SESSION_KEY, None)
        if user is None:
            messages.error(request, 'That account is no longer available.')
            return redirect('accounts:login')

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, f'Welcome back, {user.first_name or user.username}!')

        next_url = challenge.get('next') or ''
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect(settings.LOGIN_REDIRECT_URL)

    def _resend(self, request, challenge, now):
        if now - float(challenge.get('sent_at', 0)) < settings.STAFF_2FA_RESEND_SECONDS:
            messages.info(request, 'Please wait a moment before requesting another code.')
            return redirect('accounts:staff_2fa')

        user = User.objects.filter(
            pk=challenge.get('user_id'), is_active=True, is_staff=True,
        ).first()
        if user is None or not (user.email or '').strip():
            request.session.pop(STAFF_2FA_SESSION_KEY, None)
            messages.error(request, 'That account is no longer available.')
            return redirect('accounts:login')

        if not _issue_staff_2fa_code(request, user, challenge.get('next', '')):
            messages.error(request, 'We could not send another code. Please try again.')
            return redirect('accounts:login')

        messages.info(
            request, f'A new code was sent to {_masked_email(user.email)}.',
        )
        return redirect('accounts:staff_2fa')


# ---- Google Sign-In (OAuth 2.0 Authorization Code flow) --------------------

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
GOOGLE_SCOPE = 'openid email profile'


def _google_redirect_uri(request):
    """The callback URL; must match the redirect URI registered in Google"""
    return request.build_absolute_uri(reverse('accounts:google_callback'))


def _unique_username(email):
    """Build a safe, unique username from the local part of an email address"""
    base = re.sub(r'[^\w.@+-]', '', (email or '').split('@')[0])[:140] or 'user'
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f'{base}{suffix}'
    return username


def google_login(request):
    """Kick off the Google OAuth 2.0 Authorization Code flow"""
    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        messages.error(
            request,
            'Google sign-in is not configured. Please sign in with your username and password.',
        )
        return redirect('accounts:login')

    state = secrets.token_urlsafe(24)
    request.session['google_oauth_state'] = state
    request.session['google_oauth_next'] = redirect_next(request) or ''

    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': _google_redirect_uri(request),
        'response_type': 'code',
        'scope': GOOGLE_SCOPE,
        'state': state,
        'prompt': 'select_account',
    }
    return redirect(f'{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}')


def google_callback(request):
    """Handle Google's redirect, then sign the user in (or create their account)"""
    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        messages.error(request, 'Google sign-in is not configured.')
        return redirect('accounts:login')

    if request.GET.get('error'):
        messages.info(request, 'Google sign-in was cancelled.')
        return redirect('accounts:login')

    state = request.session.pop('google_oauth_state', None)
    if not state or request.GET.get('state') != state:
        messages.error(request, 'Google sign-in failed (invalid session). Please try again.')
        return redirect('accounts:login')

    code = request.GET.get('code')
    if not code:
        messages.error(request, 'Google sign-in failed (no authorization code). Please try again.')
        return redirect('accounts:login')

    token_data = urllib.parse.urlencode({
        'code': code,
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
        'redirect_uri': _google_redirect_uri(request),
        'grant_type': 'authorization_code',
    }).encode()

    try:
        with urllib.request.urlopen(GOOGLE_TOKEN_URL, data=token_data, timeout=10) as response:
            tokens = json.loads(response.read().decode('utf-8'))
        userinfo_request = urllib.request.Request(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f"Bearer {tokens['access_token']}"},
        )
        with urllib.request.urlopen(userinfo_request, timeout=10) as response:
            info = json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, KeyError, ValueError, OSError):
        messages.error(request, 'We could not complete Google sign-in. Please try again.')
        return redirect('accounts:login')

    email = (info.get('email') or '').strip().lower()
    if not email or not info.get('email_verified', False):
        messages.error(request, 'Your Google account does not have a verified email address.')
        return redirect('accounts:login')

    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        user = User(
            username=_unique_username(email),
            email=email,
            first_name=(info.get('given_name') or '')[:150],
            last_name=(info.get('family_name') or '')[:150],
            is_active=True,
        )
        user.set_unusable_password()
        user.save()
    elif not user.is_active:
        # The email is already trusted by Google, so activate the account
        user.is_active = True
        user.save(update_fields=['is_active'])

    profile, _ = Profile.objects.get_or_create(user=user)
    changed = []
    if not profile.email_verified:
        profile.email_verified = True
        changed.append('email_verified')
    if profile.must_change_password:
        profile.must_change_password = False
        changed.append('must_change_password')
    if changed:
        profile.save(update_fields=changed)

    next_url = request.session.pop('google_oauth_next', '')

    # Google proves who owns the address, but staff still need the second
    # factor: a stolen Google session must not become a staff session.
    if _staff_2fa_required(user):
        if not _issue_staff_2fa_code(request, user, next_url):
            messages.error(
                request, 'We could not send your sign-in code. Please try again.',
            )
            return redirect('accounts:login')
        messages.info(
            request, f'A six-digit code was sent to {_masked_email(user.email)}.',
        )
        return redirect('accounts:staff_2fa')

    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, f'Welcome, {user.first_name or user.username}!')

    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('cars:home')


class FavoritesView(LoginRequiredMixin, ListView):
    """Logged-in customer's saved/favorited cars"""
    model = Favorite
    template_name = 'accounts/favorites.html'
    context_object_name = 'favorites'
    paginate_by = 12

    def get_queryset(self):
        return Favorite.objects.filter(user=self.request.user).select_related('car')


class FavoritesCompareView(LoginRequiredMixin, View):
    """Compare favorited cars side by side"""
    template_name = 'accounts/favorites_compare.html'

    def get(self, request):
        favorites = Favorite.objects.filter(user=request.user).select_related('car')
        cars = [fav.car for fav in favorites]
        return render(request, self.template_name, {'cars': cars, 'favorites': favorites})



class StaffUserListView(ListView):
    """Staff view: list all staff accounts"""
    model = User
    template_name = 'accounts/staff_list.html'
    context_object_name = 'staff_users'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        # Ensure legacy staff users (created before Profile existed) have one
        for user in User.objects.filter(is_staff=True):
            Profile.objects.get_or_create(user=user)
        return User.objects.filter(is_staff=True).select_related('profile').order_by('username')


class StaffUserCreateView(CreateView):
    """Staff view: create a staff account and email a temporary password"""
    form_class = StaffUserCreateForm
    template_name = 'accounts/create_staff.html'
    success_url = reverse_lazy('accounts:staff_list')

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('cars:home')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save(commit=False)
        user.is_staff = True
        user.is_active = True
        temporary_password = secrets.token_urlsafe(12)
        user.set_password(temporary_password)
        user.save()

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.must_change_password = True
        profile.save(update_fields=['must_change_password'])

        send_staff_account_email(user, temporary_password, self.request)
        messages.success(
            self.request,
            f'Staff account "{user.username}" created. A temporary password has been emailed to {user.email}.',
        )
        return super().form_valid(form)


class PasswordChangeRequiredView(PasswordChangeView):
    """Password change page that also clears the forced-change flag"""
    template_name = 'accounts/password_change.html'
    success_url = reverse_lazy('accounts:password_change_done')

    def form_valid(self, form):
        response = super().form_valid(form)
        profile = getattr(self.request.user, 'profile', None)
        if profile is not None:
            profile.must_change_password = False
            profile.save(update_fields=['must_change_password'])
        return response


class ChangePasswordView(LoginRequiredMixin, PasswordChangeView):
    """Self-service password change for a signed-in user"""
    template_name = 'accounts/change_password.html'
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy('accounts:profile')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Your password has been changed.')
        return response


class ProfileView(LoginRequiredMixin, View):
    """Let a signed-in user edit their name, email and profile picture"""
    template_name = 'accounts/profile.html'

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        form = ProfileForm(instance=request.user, profile=profile)
        return render(request, self.template_name, {'form': form, 'profile': profile})

    def post(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        old_email = (request.user.email or '').lower()
        form = ProfileForm(
            request.POST, request.FILES, instance=request.user, profile=profile,
        )
        if form.is_valid():
            user = form.save()
            if (user.email or '').lower() != old_email:
                # The address changed: trust it only after the user clicks
                # the link we send to the new address.
                profile.email_verified = False
                profile.save(update_fields=['email_verified'])
                send_verification_email(user, request)
                messages.info(
                    request,
                    'Your profile was updated. Please check your new inbox to '
                    'verify your email address.',
                )
            else:
                messages.success(request, 'Your profile has been updated.')
            return redirect('accounts:profile')
        return render(request, self.template_name, {'form': form, 'profile': profile})


@login_required
def toggle_staff_active(request, pk):
    """Activate or deactivate a staff account (POST only). You cannot
    deactivate your own account."""
    if request.method != 'POST':
        return redirect('accounts:staff_list')
    if not request.user.is_staff:
        return redirect('cars:home')

    user = get_object_or_404(User, pk=pk, is_staff=True)
    if user.pk == request.user.pk:
        messages.info(request, 'You cannot deactivate your own account.')
        return redirect('accounts:staff_list')

    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])
    if user.is_active:
        messages.success(request, f'Staff account "{user.username}" has been activated.')
    else:
        messages.success(request, f'Staff account "{user.username}" has been deactivated.')
    return redirect('accounts:staff_list')


@login_required
def toggle_favorite(request, car_id):
    """Add or remove a car from the user's favorites (POST only)"""
    if request.method != 'POST':
        return redirect('cars:car_detail', pk=car_id)

    car = get_object_or_404(Car, id=car_id)
    favorite, created = Favorite.objects.get_or_create(
        user=request.user,
        car=car,
        defaults={'price_at_save': car.asking_price},
    )
    if created:
        messages.success(request, f'{car.year} {car.make} {car.model} added to your favorites.')
    else:
        favorite.delete()
        messages.info(request, f'{car.year} {car.make} {car.model} removed from your favorites.')

    next_url = redirect_next(request)
    if next_url:
        return redirect(next_url)
    return redirect('cars:car_detail', pk=car_id)


def redirect_next(request):
    """Return the validated ?next= target, or None"""
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return None


@login_required
def update_alert_preferences(request):
    """Save the customer's price-drop / back-in-stock email preferences (POST)"""
    if request.method != 'POST':
        return redirect('cars:my_activity')

    profile, _ = Profile.objects.get_or_create(user=request.user)
    profile.notify_price_drops = request.POST.get('notify_price_drops') == 'on'
    profile.notify_back_in_stock = request.POST.get('notify_back_in_stock') == 'on'
    profile.save(update_fields=['notify_price_drops', 'notify_back_in_stock'])
    messages.success(request, 'Your alert preferences have been updated.')
    return redirect('cars:my_activity')
