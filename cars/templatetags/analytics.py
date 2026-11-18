"""Template tag for sending GA4 events from conversion pages.

Usage::

    {% load analytics %}
    {% analytics_event "generate_lead" lead_type="inquiry" value=5000 %}

The tag renders nothing when analytics is not configured, so the same template
works with or without a Measurement ID. Parameters are JSON-encoded and ``</``
is escaped, so a user-supplied string (for example a search term) cannot break
out of the inline script.
"""

import json
from decimal import Decimal

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(
        f'Object of type {type(value).__name__} is not JSON serializable'
    )


def _encode(value):
    encoded = json.dumps(
        value, default=_json_default, separators=(',', ':'), ensure_ascii=True,
    )
    # Escape the characters that can change how the surrounding <script> is
    # parsed. json.dumps alone leaves ``</script>`` and ``<!--`` intact.
    return (
        encoded
        .replace('&', '\\u0026')
        .replace('<', '\\u003C')
        .replace('>', '\\u003E')
    )


@register.simple_tag(takes_context=True)
def analytics_event(context, event, **params):
    """Emit ``dealershipTrack(event, params)`` when GA is enabled."""
    if not context.get('google_analytics_id'):
        return ''
    return mark_safe(
        '<script>window.dealershipTrack&&window.dealershipTrack('
        f'{_encode(event)},{_encode(params)});</script>'
    )
