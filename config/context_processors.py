from django.conf import settings


def google_oauth(request):
    """Expose whether Google sign-in is configured so templates can decide
    whether to render the "Sign in with Google" button."""
    return {
        'google_oauth_enabled': bool(
            getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
            and getattr(settings, 'GOOGLE_OAUTH_CLIENT_SECRET', '')
        ),
    }


def seo(request):
    """Expose owner-controlled verification tokens and the default OG image.

    Search-console tokens are public by design (they are meta tags), but they
    are still configuration rather than markup so a token can be changed
    without editing templates.
    """
    return {
        'google_site_verification': getattr(settings, 'GOOGLE_SITE_VERIFICATION', ''),
        'bing_site_verification': getattr(settings, 'BING_SITE_VERIFICATION', ''),
    }


def antispam(request):
    """Expose the optional captcha site key so public forms can render the
    widget. Empty when no captcha is configured (the default)."""
    hcaptcha = getattr(settings, 'HCAPTCHA_SITE_KEY', '')
    recaptcha = getattr(settings, 'RECAPTCHA_SITE_KEY', '')
    if hcaptcha:
        return {'captcha_site_key': hcaptcha, 'captcha_provider': 'hcaptcha'}
    if recaptcha:
        return {'captcha_site_key': recaptcha, 'captcha_provider': 'recaptcha'}
    return {'captcha_site_key': '', 'captcha_provider': ''}


def branding(request):
    """Expose the editable dealership name/logo (see cars.models.DealershipInfo)
    to every template. Falls back to None if the row can't be read so a missing
    database row never breaks page rendering."""
    from cars.models import DealershipInfo
    try:
        info = DealershipInfo.get_solo()
    except Exception:
        info = None
    logo_url = ''
    if info is not None and getattr(info, 'logo', None):
        try:
            logo_url = request.build_absolute_uri(info.logo.url)
        except Exception:
            logo_url = ''
    return {'dealership': info, 'default_og_image': logo_url}


def chatbot(request):
    """Expose whether the site chatbot is switched on so base.html can decide
    whether to render the chat widget."""
    return {'chatbot_enabled': getattr(settings, 'CHATBOT_ENABLED', True)}


CONSENT_COOKIE = 'cookie_consent'
CONSENT_GRANTED = 'granted'
CONSENT_DENIED = 'denied'


def analytics(request):
    """Expose the GA4 Measurement ID when tracking is configured and allowed.

    Staff and admin pages are excluded: internal usage would pollute the
    reports, and the admin lives on an unguessable path that should not be
    handed to a third party.

    Tracking is opt-in. ``cookie_consent`` is a first-party cookie written by
    the banner (see cars/templates/cars/_cookie_consent.html); until it says
    ``granted`` the template receives no Measurement ID, so no request ever
    reaches Google. The banner itself is shown only while a configured site
    has no decision recorded yet.
    """
    ga_id = getattr(settings, 'GOOGLE_ANALYTICS_ID', '').strip()
    if not getattr(settings, 'GOOGLE_ANALYTICS_ENABLED', bool(ga_id)):
        ga_id = ''

    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated and user.is_staff:
        ga_id = ''
    admin_url = getattr(settings, 'ADMIN_URL', '/admin/')
    if ga_id and request.path.startswith(admin_url):
        ga_id = ''

    consent_required = getattr(settings, 'GOOGLE_ANALYTICS_REQUIRE_CONSENT', True)
    consent_state = request.COOKIES.get(CONSENT_COOKIE, '')
    configured = bool(ga_id)
    consent_pending = bool(
        configured
        and consent_required
        and consent_state not in (CONSENT_GRANTED, CONSENT_DENIED)
    )
    allowed = (not consent_required) or consent_state == CONSENT_GRANTED

    return {
        'google_analytics_id': ga_id if allowed else '',
        'analytics_configured': configured,
        'analytics_consent_required': consent_required,
        'analytics_consent_state': consent_state,
        'analytics_consent_pending': consent_pending,
    }

