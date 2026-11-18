from django.contrib.auth.views import (
    LogoutView, PasswordChangeDoneView,
    PasswordResetView, PasswordResetDoneView, PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.urls import path, reverse_lazy

from . import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('verify/sent/', views.verify_email_sent, name='verify_email_sent'),
    path('verify/resend/', views.resend_verification, name='resend_verification'),
    path('verify/invalid/', views.verify_email_invalid, name='verify_email_invalid'),
    path('verify/<uidb64>/<token>/', views.verify_email, name='verify_email'),
    path('login/', views.StaffAwareLoginView.as_view(), name='login'),
    path('login/verify/', views.StaffTwoFactorView.as_view(), name='staff_2fa'),
    path('google/login/', views.google_login, name='google_login'),
    path('google/callback/', views.google_callback, name='google_callback'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('favorites/', views.FavoritesView.as_view(), name='favorites'),
    path('favorites/compare/', views.FavoritesCompareView.as_view(), name='favorites_compare'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/password/', views.ChangePasswordView.as_view(), name='change_password'),
    path('favorite/<int:car_id>/toggle/', views.toggle_favorite, name='toggle_favorite'),
    path('alerts/preferences/', views.update_alert_preferences, name='alert_preferences'),
    path('staff/', views.StaffUserListView.as_view(), name='staff_list'),
    path('staff/create/', views.StaffUserCreateView.as_view(), name='staff_create'),
    path('staff/<int:pk>/toggle-active/', views.toggle_staff_active, name='toggle_staff_active'),
    path('password-change/', views.PasswordChangeRequiredView.as_view(), name='password_change'),
    path('password-change/done/', PasswordChangeDoneView.as_view(
        template_name='accounts/password_change_done.html',
    ), name='password_change_done'),
    path('password-reset/', PasswordResetView.as_view(
        template_name='accounts/password_reset.html',
        email_template_name='accounts/password_reset_email.txt',
        subject_template_name='accounts/password_reset_subject.txt',
        success_url=reverse_lazy('accounts:password_reset_done'),
    ), name='password_reset'),
    path('password-reset/done/', PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_done.html',
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', PasswordResetConfirmView.as_view(
        template_name='accounts/password_reset_confirm.html',
        success_url=reverse_lazy('accounts:password_reset_complete'),
    ), name='password_reset_confirm'),
    path('reset/done/', PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_complete.html',
    ), name='password_reset_complete'),
]