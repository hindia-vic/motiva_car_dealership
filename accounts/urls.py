from django.contrib.auth.views import (
    LoginView, LogoutView, PasswordChangeDoneView,
    PasswordResetView, PasswordResetDoneView, PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.urls import path, reverse_lazy

from . import views
from .forms import LoginForm

app_name = 'accounts'

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('verify/sent/', views.verify_email_sent, name='verify_email_sent'),
    path('verify/resend/', views.resend_verification, name='resend_verification'),
    path('verify/invalid/', views.verify_email_invalid, name='verify_email_invalid'),
    path('verify/<uidb64>/<token>/', views.verify_email, name='verify_email'),
    path('login/', LoginView.as_view(
        template_name='accounts/login.html',
        authentication_form=LoginForm,
    ), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('favorites/', views.FavoritesView.as_view(), name='favorites'),
    path('favorite/<int:car_id>/toggle/', views.toggle_favorite, name='toggle_favorite'),
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