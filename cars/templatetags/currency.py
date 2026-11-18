"""Template tags for prices.

    {% load currency %}
    {{ car.asking_price|money }}       -> KSh 3,120,000
    {{ car.asking_price|money:2 }}     -> KSh 3,120,000.00
    {% currency %}                      -> KSh
    {% currency_code %}                 -> KES

The symbol comes from the settings, so changing it there changes every
price on the site.
"""

from django import template

from cars.money import (
    currency_code as money_currency_code,
    currency_symbol as money_currency_symbol,
    format_money,
)

register = template.Library()


@register.filter
def money(value, decimals=0):
    """Format an amount as a price, e.g. ``KSh 3,120,000``."""
    try:
        decimals = int(decimals)
    except (TypeError, ValueError):
        decimals = 0
    if decimals < 0:
        decimals = 0
    return format_money(value, decimals=decimals)


@register.simple_tag
def currency():
    """The currency symbol on its own, e.g. ``KSh``."""
    return money_currency_symbol()


@register.simple_tag
def currency_code():
    """The currency code on its own, e.g. ``KES``."""
    return money_currency_code()
