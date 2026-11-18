"""Lightweight spam protection for public (unauthenticated) forms.

The baseline defence has no third-party dependencies and never asks the user
to do anything extra:

* a hidden "honeypot" text field that humans never see but naive bots fill in;
* a simple link-count heuristic on free-text fields;
* per-IP rate limiting backed by Django's cache.

An optional captcha (hCaptcha or reCAPTCHA) can be switched on by setting a
site/secret key pair; when no key is configured the captcha check is a no-op
so development and tests are unaffected.
"""

import json
import logging
import urllib.parse
import urllib.request
from functools import wraps

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv46_address
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)

#: Name of the hidden honeypot field. Bots that blindly fill every input will
#: populate this; real users never see it.
HONEYPOT_FIELD = 'website'

#: Maximum number of links allowed in a single free-text field.
MAX_URLS = 5

#: Free-text fields scanned by the link heuristic.
TEXT_FIELDS = ('message', 'quote', 'notes', 'subject', 'comments')


def honeypot_field():
    """Build the (CSS-hidden) honeypot form field."""
    return forms.CharField(
        required=False,
        label='',
        widget=forms.TextInput(attrs={
            'autocomplete': 'off',
            'tabindex': '-1',
            'aria-hidden': 'true',
        }),
    )


class AntiSpamMixin:
    """Add a honeypot + link heuristic to a public form.

    Mix in *before* the base form class, e.g.::

        class ContactForm(AntiSpamMixin, forms.ModelForm):
            ...

    The honeypot field is rendered manually by the ``_antispam_fields.html``
    partial (a raw ``<input name="website">``), so nothing has to change in
    templates that render fields individually.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only add the field if a subclass hasn't already declared one.
        if HONEYPOT_FIELD not in self.fields:
            self.fields[HONEYPOT_FIELD] = honeypot_field()

    def clean(self):
        cleaned = super().clean()
        if str(cleaned.get(HONEYPOT_FIELD, '') or '').strip():
            logger.warning('Anti-spam: honeypot triggered')
            raise forms.ValidationError(
                "We couldn't process your submission. Please try again.",
                code='spam',
            )
        for name in TEXT_FIELDS:
            value = cleaned.get(name)
            if isinstance(value, str) and count_urls(value) > MAX_URLS:
                logger.warning('Anti-spam: link heuristic triggered on %r', name)
                raise forms.ValidationError(
                    "Your message contains too many links. "
                    "Please remove some and try again.",
                    code='spam',
                )
        return cleaned


def count_urls(text):
    """Count the number of links in a block of text (cheap heuristic)."""
    lowered = text.lower()
    return (
        lowered.count('http://')
        + lowered.count('https://')
        + lowered.count('www.')
    )


def client_ip(request):
    """Best-effort client IP, honouring trusted proxy hops.

    ``X-Forwarded-For`` is only read when ``TRUST_X_FORWARDED_FOR`` is on (the
    app is behind a proxy that overwrites the header). The header is a
    comma-separated chain that a client can pad, so the hop added by the
    outermost trusted proxy is used instead of the first (spoofable) value.
    """
    remote = request.META.get('REMOTE_ADDR', '') or 'unknown'
    if not getattr(settings, 'TRUST_X_FORWARDED_FOR', False):
        return remote

    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if not forwarded:
        return remote

    hops = [hop.strip() for hop in forwarded.split(',') if hop.strip()]
    if not hops:
        return remote

    proxy_count = max(1, int(getattr(settings, 'X_FORWARDED_FOR_PROXY_COUNT', 1)))
    index = -proxy_count if len(hops) >= proxy_count else 0
    candidate = hops[index]
    try:
        validate_ipv46_address(candidate)
    except ValidationError:
        return remote
    return candidate


def _is_rate_limited(request, scope, limit, window):
    """Record a hit and return True when the caller has exceeded ``limit``."""
    if not getattr(settings, 'ANTISPAM_RATE_LIMITS_ENABLED', True):
        return False

    key = f'antispam:rate:{scope}:{client_ip(request)}'
    count = cache.get(key, 0) + 1
    # A sliding window: each request refreshes the expiry, so a client that
    # keeps hammering stays blocked until it pauses for a full window.
    cache.set(key, count, timeout=window)
    return count > limit


def rate_limit(scope, limit=10, window=600, message=None):
    """Decorator: cap POSTs to a view at ``limit`` per ``window`` seconds/IP.

    Applies to POST only; GET requests always pass through. When the limit is
    exceeded the caller is redirected (with an error message) instead of the
    view being run, so no object is created.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.method == 'POST' and _is_rate_limited(request, scope, limit, window):
                logger.warning(
                    'Anti-spam: rate limit hit for %r from %s',
                    scope, client_ip(request),
                )
                messages.error(
                    request,
                    message or 'Too many submissions from your address. '
                               'Please try again a little later.',
                )
                return redirect(_safe_redirect(request))
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def captcha_required(view_func):
    """Decorator: reject POSTs that fail the optional captcha check."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.method == 'POST' and not verify_captcha(request):
            logger.warning('Anti-spam: captcha check failed')
            messages.error(request, 'Please complete the verification and try again.')
            return redirect(_safe_redirect(request))
        return view_func(request, *args, **kwargs)
    return _wrapped


def verify_captcha(request):
    """Return True when the request passes the captcha (or none is configured).

    Supports hCaptcha (``HCAPTCHA_SECRET_KEY``) and reCAPTCHA
    (``RECAPTCHA_SECRET_KEY``). If no secret key is set this is a no-op and
    always returns True. If the captcha provider can't be reached the check
    fails *open* so a provider outage never blocks real customers.
    """
    hcaptcha = getattr(settings, 'HCAPTCHA_SECRET_KEY', '')
    recaptcha = getattr(settings, 'RECAPTCHA_SECRET_KEY', '')

    if hcaptcha:
        token = request.POST.get('h-captcha-response', '')
        verify_url = 'https://hcaptcha.com/siteverify'
        secret = hcaptcha
    elif recaptcha:
        token = request.POST.get('g-recaptcha-response', '')
        verify_url = 'https://www.google.com/recaptcha/api/siteverify'
        secret = recaptcha
    else:
        return True

    if not token:
        return False

    payload = urllib.parse.urlencode({'secret': secret, 'response': token}).encode()
    try:
        with urllib.request.urlopen(verify_url, data=payload, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
    except Exception:
        logger.warning('Anti-spam: captcha provider unreachable', exc_info=True)
        return True
    return bool(result.get('success'))


def _safe_redirect(request):
    """Where to send a blocked caller: the ``next`` param if it's trusted."""
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}
    ):
        return next_url
    return 'cars:home'
