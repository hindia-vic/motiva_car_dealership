"""Middleware that records page views for the traffic analytics dashboard.

The write happens *after* the response is produced so that both the status
code and the resolved view are known: ``request.resolver_match`` is only
populated once URL resolution has run, which happens while the view is
being called.

Every failure is swallowed. Tracking must never break the page it tracks.
"""

import logging
import secrets

from django.conf import settings
from django.core.cache import cache

from cars.antispam import client_ip

from .analytics import (
    VISITOR_COOKIE, classify_source, dedupe_key, is_bot, is_scanner_path,
    normalize_source, parse_browser, parse_device,
)
from .models import PageView
from .prune import prune_expired

logger = logging.getLogger(__name__)

#: One year, so a returning visitor is still recognised as the same person.
VISITOR_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

#: Path prefixes that never contain a tracked page.
UNTRACKED_PREFIXES = ('/static/', '/media/')

#: Resolved view names that never contain a tracked page.
UNTRACKED_URL_NAMES = {'health', 'sitemap', 'robots'}

#: View names whose page belongs to a specific vehicle.
CAR_URL_NAMES = {'car_detail'}

#: Redirects are skipped: the page they point at is recorded instead.
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class TrafficTrackingMiddleware:
    """Record a ``PageView`` for each public page request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self.record(request, response)
        except Exception:
            logger.warning('Traffic tracking failed', exc_info=True)
        return response

    # -- internals ----------------------------------------------------

    def record(self, request, response):
        """Store one page view, if this request is worth recording."""
        if not getattr(settings, 'TRAFFIC_TRACKING_ENABLED', False):
            return
        if not self._is_trackable(request, response):
            return
        if is_scanner_path(request.path):
            return

        user_agent = request.META.get('HTTP_USER_AGENT', '')
        if is_bot(user_agent):
            return

        visitor_id = self._visitor_id(request, response)
        if not self._should_record(visitor_id, request.path):
            return

        match = getattr(request, 'resolver_match', None)
        url_name = match.url_name if match else ''
        kwargs = match.kwargs if match else {}

        car_id = None
        if url_name in CAR_URL_NAMES:
            car_id = kwargs.get('pk')

        referrer = request.META.get('HTTP_REFERER', '')[:500]
        source = classify_source(referrer, request.get_host())

        # A tagged campaign link tells us more than the referrer, so it wins.
        utm_source = (request.GET.get('utm_source') or '').strip()
        if utm_source:
            source = normalize_source(utm_source)

        PageView.objects.create(
            path=request.path[:255],
            url_name=url_name[:100],
            car_id=car_id,
            visitor_id=visitor_id,
            user_id=request.user.pk if request.user.is_authenticated else None,
            ip_address=self._ip_address(request),
            referrer=referrer,
            source=source[:100],
            utm_source=utm_source[:100],
            utm_medium=(request.GET.get('utm_medium') or '')[:100],
            utm_campaign=(request.GET.get('utm_campaign') or '')[:150],
            device=parse_device(user_agent),
            browser=parse_browser(user_agent),
            status_code=response.status_code,
        )

        self._maybe_prune()

    def _is_trackable(self, request, response):
        """True when this request/response pair should be recorded."""
        if request.method != 'GET':
            return False

        # Staff browsing the staff panel is not customer traffic.
        user = getattr(request, 'user', None)
        if user is not None and user.is_staff:
            return False

        # Background requests (chatbot, autosave) are not page views.
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return False

        if request.path.startswith(UNTRACKED_PREFIXES):
            return False

        # The admin lives at a configurable path, so compare against the
        # setting rather than the historical /admin/ prefix.
        admin_url = getattr(settings, 'ADMIN_URL', '/admin/')
        if request.path.startswith(admin_url):
            return False

        match = getattr(request, 'resolver_match', None)
        if match is not None and match.url_name in UNTRACKED_URL_NAMES:
            return False

        if response.status_code in REDIRECT_STATUS_CODES:
            return False
        if response.status_code >= 400:
            # A request for a URL that does not exist is far more often a
            # scanner than a visitor following a broken link, so 404s are
            # only recorded when they are explicitly asked for.
            if response.status_code != 404 or not getattr(
                settings, 'TRAFFIC_TRACK_404S', False
            ):
                return False

        return 'text/html' in response.get('Content-Type', '')

    def _should_record(self, visitor_id, path):
        """True unless this visitor already hit this path inside the window.

        Refreshing a page or double-clicking a link would otherwise add a
        row each time. The first view always gets through, so unique
        visitors, landing pages and the bounce rate are unaffected.
        """
        window = int(getattr(settings, 'TRAFFIC_DEDUPE_WINDOW', 60))
        if window <= 0:
            return True
        try:
            # cache.add only stores the key when it is missing, so it returns
            # True the first time and False for a repeat inside the window.
            return cache.add(dedupe_key(visitor_id, path), 1, timeout=window)
        except Exception:
            # A broken cache must not stop the page from being counted.
            logger.warning('Traffic dedupe: cache unavailable', exc_info=True)
            return True

    def _maybe_prune(self):
        """Prune expired rows, at most once a day."""
        try:
            prune_expired()
        except Exception:
            logger.warning('Traffic auto-prune failed', exc_info=True)

    def _visitor_id(self, request, response):
        """Return the visitor token, setting the cookie when it is missing.

        The token is a random string, not a security credential: it only has
        to be unguessable enough that one visitor cannot guess another's.
        """
        token = request.COOKIES.get(VISITOR_COOKIE, '')
        if not token or len(token) > 64:
            token = secrets.token_urlsafe(22)
            response.set_cookie(
                VISITOR_COOKIE,
                token,
                max_age=VISITOR_COOKIE_MAX_AGE,
                httponly=True,
                samesite='Lax',
                secure=request.is_secure(),
            )
        return token

    def _ip_address(self, request):
        """The client IP, honouring a single proxy hop."""
        ip = client_ip(request)
        if not ip or ip == 'unknown':
            return None
        return ip
