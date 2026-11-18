"""Classification helpers for the traffic analytics app.

Nothing here needs a third-party package: the user agent is parsed with a
handful of regular expressions and the referrer with :mod:`urllib.parse`,
mirroring the dependency-free approach already used by ``cars.chatbot``.
"""

from urllib.parse import urlparse

import hashlib

#: Name of the first-party cookie holding the anonymous visitor token.
VISITOR_COOKIE = 'vid'

#: Path fragments that scanners and bots hammer on. Requests to these are
#: never recorded, whatever status they return - they are noise, not
#: traffic. Matched case-insensitively as a substring of the path.
SCANNER_PATHS = (
    '/.env',
    '/.git',
    '/.aws',
    '/.ssh',
    '/wp-admin',
    '/wp-login',
    '/wp-content',
    '/wp-includes',
    '/wp-json',
    '/xmlrpc.php',
    '/phpmyadmin',
    '/adminer',
    '/cgi-bin',
    '/node_modules/',
    '/vendor/',
    '/api/',
    '/v1/',
    '/v2/',
    '/graphql',
    '/actuator',
    '/server-status',
    '/server-info',
    '/config.json',
)

#: Exact referrer host -> readable source name (checked first).
EXACT_SOURCES = {
    'mail.google.com': 'Gmail',
    'outlook.live.com': 'Outlook',
    'mail.office365.com': 'Outlook',
    'mail.yahoo.com': 'Yahoo Mail',
    'duckduckgo.com': 'DuckDuckGo',
    'search.yahoo.com': 'Yahoo',
    'yandex.ru': 'Yandex',
    't.co': 'X (Twitter)',
    'x.com': 'X (Twitter)',
    'lnkd.in': 'LinkedIn',
    'l.facebook.com': 'Facebook',
    'm.facebook.com': 'Facebook',
    'lm.facebook.com': 'Facebook',
    'youtube.com': 'YouTube',
    'youtu.be': 'YouTube',
    'wa.me': 'WhatsApp',
    't.me': 'Telegram',
    'web.telegram.org': 'Telegram',
    'discord.com': 'Discord',
}

#: Token -> readable source name, matched against the referrer host.
#: The first hit wins, so more specific tokens come first.
TOKEN_SOURCES = {
    'duckduckgo': 'DuckDuckGo',
    'startpage': 'Startpage',
    'ecosia': 'Ecosia',
    'brave': 'Brave',
    'baidu': 'Baidu',
    'yandex': 'Yandex',
    'yahoo': 'Yahoo',
    'bing': 'Bing',
    'google': 'Google',
    'facebook': 'Facebook',
    'fbclid': 'Facebook',
    'instagram': 'Instagram',
    'twitter': 'X (Twitter)',
    'linkedin': 'LinkedIn',
    'tiktok': 'TikTok',
    'youtube': 'YouTube',
    'pinterest': 'Pinterest',
    'reddit': 'Reddit',
    'threads.net': 'Threads',
    'quora': 'Quora',
    'discord': 'Discord',
    'slack': 'Slack',
}

#: Referrer prefixes used by mobile apps instead of a normal URL.
APP_REFERRER_PREFIXES = (
    'android-app:',
    'ios-app:',
    'fbav://',
    'fb://',
    'instagram://',
    'snapchat://',
    'tg://',
)

#: User agent fragments that identify a non-human client.
BOT_MARKERS = (
    'bot',
    'crawler',
    'crawling',
    'spider',
    'slurp',
    'archiver',
    'facebookexternalhit',
    'feedfetcher',
    'mediapartners',
    'headlesschrome',
    'phantomjs',
    'lighthouse',
    'pingdom',
    'uptimerobot',
    'ahrefs',
    'semrush',
    'mj12',
    'dotbot',
    'petalbot',
    'bytespider',
    'bingpreview',
    'curl/',
    'wget/',
    'python-requests',
    'python-urllib',
    'httpclient',
    'scrapy',
    'go-http-client',
    'libwww-perl',
    'okhttp',
    'monitoring',
    'validator',
)

#: User agent fragments that mean the client is a tablet.
TABLET_MARKERS = ('ipad', 'tablet', 'playbook', 'silk', 'kindle')

#: User agent fragments that mean the client is a phone.
MOBILE_MARKERS = (
    'mobi',
    'iphone',
    'ipod',
    'android',
    'windows phone',
    'opera mini',
    'opera mobi',
    'blackberry',
    'webos',
)

#: Friendly names for the site's pages, used in the "Top pages" table.
URL_NAME_LABELS = {
    'home': 'Homepage',
    'browse_cars': 'Browse cars',
    'car_detail': 'Vehicle detail',
    'compare': 'Compare vehicles',
    'reviews': 'Customer reviews',
    'contact': 'Contact us',
    'about': 'About us',
    'financing': 'Financing',
    'faq': 'FAQ',
    'blog_list': 'News / blog',
    'blog_detail': 'News article',
    'saved_search_create': 'Saved search',
    'login': 'Sign in',
    'register': 'Create an account',
    'my_activity': 'My activity',
    'chatbot_message': 'Chatbot',
}


def _clean_host(host):
    """Return the bare lowercase hostname, without credentials or port."""
    host = (host or '').strip().lower()
    if '@' in host:
        host = host.rsplit('@', 1)[-1]
    if host.startswith('['):          # IPv6 literal
        return host.split(']')[0] + ']'
    return host.split(':')[0]


def _same_site(ref_host, own_host):
    """True when the referrer points back at this site."""
    if not ref_host or not own_host:
        return False
    if ref_host == own_host:
        return True
    return ref_host == 'www.' + own_host or own_host == 'www.' + ref_host


def classify_source(referrer, host=''):
    """Turn a raw referrer header into a readable traffic source.

    Returns one of Google, Bing, Facebook, Direct, Internal, App or
    Referral (for anything unrecognised).
    """
    referrer = (referrer or '').strip()
    if not referrer:
        return 'Direct'

    if referrer.lower().startswith(APP_REFERRER_PREFIXES):
        return 'App'

    parsed = urlparse(referrer)
    ref_host = _clean_host(parsed.netloc)
    if not ref_host:
        return 'Referral'

    if _same_site(ref_host, _clean_host(host)):
        return 'Internal'

    if ref_host in EXACT_SOURCES:
        return EXACT_SOURCES[ref_host]

    for token, name in TOKEN_SOURCES.items():
        if token in ref_host:
            return name

    return 'Referral'


def normalize_source(value):
    """Map a raw source token (a UTM value, for instance) to a readable name.

    Unknown values are returned unchanged so campaign names stay visible.
    """
    token = (value or '').strip()
    if not token:
        return ''
    lowered = token.lower()
    if lowered in EXACT_SOURCES:
        return EXACT_SOURCES[lowered]
    for key, name in TOKEN_SOURCES.items():
        if key in lowered:
            return name
    return token[:100]


def parse_device(user_agent):
    """Return Desktop, Mobile, Tablet or Unknown for a user agent string."""
    ua = (user_agent or '').lower()
    if not ua.strip():
        return 'Unknown'
    if any(marker in ua for marker in TABLET_MARKERS):
        return 'Tablet'
    if any(marker in ua for marker in MOBILE_MARKERS):
        return 'Mobile'
    return 'Desktop'


def parse_browser(user_agent):
    """Return a readable browser name for a user agent string."""
    ua = (user_agent or '').lower()
    if not ua.strip():
        return 'Unknown'
    # Order matters: Edge, Opera and Samsung all mention Chrome.
    if 'edg/' in ua or 'edge/' in ua or 'edga/' in ua or 'edgios/' in ua:
        return 'Edge'
    if 'opr/' in ua or 'opera' in ua:
        return 'Opera'
    if 'firefox/' in ua or 'fxios' in ua:
        return 'Firefox'
    if 'samsungbrowser' in ua:
        return 'Samsung Internet'
    if 'chrome' in ua or 'crios' in ua:
        return 'Chrome'
    if 'safari' in ua:
        return 'Safari'
    if 'msie' in ua or 'trident' in ua:
        return 'Internet Explorer'
    return 'Other'


def is_bot(user_agent):
    """True when the user agent looks like a crawler rather than a person."""
    ua = (user_agent or '').lower()
    if not ua.strip():
        return False
    return any(marker in ua for marker in BOT_MARKERS)


def page_label(url_name, path=''):
    """A friendly name for a page, falling back to the raw path."""
    if url_name in URL_NAME_LABELS:
        return URL_NAME_LABELS[url_name]
    return path or url_name or '(unknown)'


def is_scanner_path(path):
    """True when the path looks like a scanner probing for something."""
    lowered = (path or '').lower()
    return any(marker in lowered for marker in SCANNER_PATHS)


def dedupe_key(visitor_id, path):
    """A short, cache-safe key for a visitor and path pair.

    The path is hashed rather than embedded because cache keys have a
    length limit and paths can be long.
    """
    digest = hashlib.sha256(f'{visitor_id}:{path}'.encode('utf-8')).hexdigest()
    return f'traffic:seen:{digest}'


#: Periods the staff panel offers, in days.
PERIODS = (7, 30, 90)

#: The period used when the query string asks for something unexpected.
DEFAULT_PERIOD = 30


def parse_period(raw):
    """Return one of the supported periods from a query string value."""
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PERIOD
    return days if days in PERIODS else DEFAULT_PERIOD
