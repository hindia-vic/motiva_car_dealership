import logging

from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

logger = logging.getLogger(__name__)


def send_verification_email(user, request=None):
    """Email a newly registered user a link to verify their address.

    The account stays inactive until the link is clicked. Failures are
    logged but never raised so registration still succeeds.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    verify_url = reverse('accounts:verify_email', kwargs={'uidb64': uid, 'token': token})
    if request is not None:
        verify_url = request.build_absolute_uri(verify_url)

    subject = "[Car Dealership] Verify your email address"
    lines = [
        f"Hi {user.first_name or user.username},",
        "",
        "Thanks for registering! Please confirm this email address by "
        "opening the link below:",
        "",
        verify_url,
        "",
        "The link expires in a few days and can only be used once. "
        "You will not be able to sign in until your email is verified.",
        "",
        "If you did not create an account, you can safely ignore this email.",
        "",
        "The Car Dealership Team",
    ]
    try:
        send_mail(
            subject,
            "\n".join(lines),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except Exception:
        logger.warning("Failed to send verification email to %s", user.username, exc_info=True)


def send_staff_account_email(user, temporary_password, request=None):
    """Email a newly created staff user their credentials and a notice that
    they must set their own password on the first login.

    Failures are logged but never raised so account creation still succeeds.
    """
    login_url = reverse('accounts:login')
    if request is not None:
        login_url = request.build_absolute_uri(login_url)

    subject = "[Car Dealership] Your new staff account"
    lines = [
        f"Hi {user.first_name or user.username},",
        "",
        "An administrator has created a staff account for you "
        f"({user.first_name} {user.last_name}).".strip(),
        "",
        f"Username:   {user.username}",
        f"Password:   {temporary_password}",
        "",
        f"Sign in at: {login_url}",
        "",
        "For security, you must change this temporary password after your "
        "first login. Your new password should be at least 8 characters "
        "long and not entirely numeric.",
        "",
        "If you did not expect this email, please contact the dealership.",
    ]
    try:
        send_mail(
            subject,
            "\n".join(lines),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except Exception:
        logger.warning("Failed to send staff account email to %s", user.username, exc_info=True)