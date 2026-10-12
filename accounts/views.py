import secrets

from django.contrib import messages
from django.contrib.auth import login, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordChangeView
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views import View
from django.views.generic import CreateView, ListView

from cars.models import Car

from .emails import send_staff_account_email, send_verification_email
from .forms import RegisterForm, StaffUserCreateForm
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
    """Activate the account when the emailed verification link is opened"""
    user = None
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = get_user_model().objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, ValidationError, ObjectDoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token) and not user.is_active:
        user.is_active = True
        user.save(update_fields=['is_active'])
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.email_verified = True
        profile.save(update_fields=['email_verified'])
        login(request, user)
        messages.success(request, f'Your email is verified, {user.first_name or user.username}! Your account is now active.')
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


class FavoritesView(LoginRequiredMixin, ListView):
    """Logged-in customer's saved/favorited cars"""
    model = Favorite
    template_name = 'accounts/favorites.html'
    context_object_name = 'favorites'
    paginate_by = 12

    def get_queryset(self):
        return Favorite.objects.filter(user=self.request.user).select_related('car')


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
    favorite, created = Favorite.objects.get_or_create(user=request.user, car=car)
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
