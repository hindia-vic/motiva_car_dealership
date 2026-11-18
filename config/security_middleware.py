"""Security headers that Django does not send on its own.

The Content-Security-Policy is assembled here rather than in a third-party
package so the allowed origins stay in step with the optional captcha widgets.
Every directive is deliberately narrow: the site loads its Bootstrap/Chart.js
assets from its own static files, Google Fonts for typography, and a captcha
script only when that provider is configured.
"""

from django.conf import settings
from django.http import HttpResponse
from django.utils.cache import patch_vary_headers


def _default_content_security_policy():
    # Inline scripts/styles are still used throughout the templates, so
    # 'unsafe-inline' stays until they are moved behind a nonce. eval() is not
    # used anywhere, so it stays blocked.
    script_src = ["'self'", "'unsafe-inline'"]
    style_src = ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"]
    font_src = ["'self'", "https://fonts.gstatic.com", "data:"]
    img_src = ["'self'", "data:", "https:"]
    connect_src = ["'self'"]
    frame_src = ["'self'"]

    if getattr(settings, 'HCAPTCHA_SITE_KEY', ''):
        script_src.append('https://js.hcaptcha.com')
        frame_src.extend(['https://js.hcaptcha.com', 'https://newassets.hcaptcha.com'])
        connect_src.extend(['https://hcaptcha.com', 'https://*.hcaptcha.com'])

    if getattr(settings, 'RECAPTCHA_SITE_KEY', ''):
        script_src.extend(['https://www.google.com', 'https://www.gstatic.com'])
        frame_src.extend(['https://www.google.com', 'https://recaptcha.google.com'])

    # GA4 loads gtag.js from Tag Manager and sends beacons to the analytics
    # collection hosts. Only widen the policy when a Measurement ID is set.
    if (
        getattr(settings, 'GOOGLE_ANALYTICS_ID', '')
        and getattr(settings, 'GOOGLE_ANALYTICS_ENABLED', True)
    ):
        script_src.append('https://www.googletagmanager.com')
        connect_src.extend([
            'https://www.googletagmanager.com',
            'https://*.google-analytics.com',
            'https://*.analytics.google.com',
        ])

    directives = [
        "default-src 'self'",
        f"script-src {' '.join(dict.fromkeys(script_src))}",
        f"style-src {' '.join(dict.fromkeys(style_src))}",
        f"font-src {' '.join(dict.fromkeys(font_src))}",
        f"img-src {' '.join(dict.fromkeys(img_src))}",
        f"connect-src {' '.join(dict.fromkeys(connect_src))}",
        f"frame-src {' '.join(dict.fromkeys(frame_src))}",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
    return '; '.join(directives)


class ContentSecurityPolicyMiddleware:
    """Add the CSP and the small set of hardening headers Django leaves out."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if getattr(settings, 'CONTENT_SECURITY_POLICY_ENABLED', True):
            policy = (
                getattr(settings, 'CONTENT_SECURITY_POLICY', '')
                or _default_content_security_policy()
            )
            header = (
                'Content-Security-Policy-Report-Only'
                if getattr(settings, 'CONTENT_SECURITY_POLICY_REPORT_ONLY', False)
                else 'Content-Security-Policy'
            )
            if not response.get(header):
                response[header] = policy

        response.setdefault('X-Content-Type-Options', 'nosniff')
        response.setdefault('X-Frame-Options', 'DENY')
        response.setdefault('Referrer-Policy', 'same-origin')
        response.setdefault(
            'Permissions-Policy',
            'camera=(), microphone=(), geolocation=(), payment=()',
        )
        response.setdefault(
            'Cross-Origin-Opener-Policy',
            getattr(settings, 'SECURE_CROSS_ORIGIN_OPENER_POLICY', 'same-origin'),
        )
        response.setdefault(
            'Cross-Origin-Resource-Policy',
            getattr(settings, 'CROSS_ORIGIN_RESOURCE_POLICY', 'same-origin'),
        )
        # The admin may live at an unguessable path, so do not rely on
        # robots.txt to keep it out of search results.
        if request.path.startswith(getattr(settings, 'ADMIN_URL', '/admin/')):
            response.setdefault('X-Robots-Tag', 'noindex, nofollow')
        return response


class CorsMiddleware:
    """A small, allowlist-only CORS layer.

    Nothing is sent unless the request Origin exactly matches an entry in
    ``CORS_ALLOWED_ORIGINS``. Credentials are never allowed, so a browser on an
    allowed origin can read public responses (feeds, the health check) but
    cannot act as the signed-in user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        allowed = getattr(settings, 'CORS_ALLOWED_ORIGINS', [])
        origin = request.headers.get('Origin')
        if not allowed or not origin or origin not in allowed:
            return self.get_response(request)

        is_preflight = (
            request.method == 'OPTIONS'
            and request.headers.get('Access-Control-Request-Method')
        )
        if is_preflight:
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        response['Access-Control-Allow-Origin'] = origin
        patch_vary_headers(response, ['Origin'])
        response['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Accept, Content-Type'
        response['Access-Control-Max-Age'] = '600'
        return response
