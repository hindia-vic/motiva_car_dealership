"""Formatting for prices.

Every price on the site is in Kenyan shillings. The symbol is a setting,
so it can be changed in one place, and the formatting lives here so that
templates, emails, the chatbot and the PDF exports all say the same
thing:

    KSh 3,120,000

Shillings are whole units in practice, so amounts are shown without
decimals unless the caller asks for them - the monthly payment on a
finance agreement is the one place that needs the cents.

Nothing here needs a third-party package.
"""

from decimal import Decimal, InvalidOperation

from django.conf import settings

#: Used when the settings module has no currency configured.
DEFAULT_CURRENCY_SYMBOL = 'KSh'


def currency_symbol():
    """The symbol used in front of an amount, e.g. ``KSh``."""
    return getattr(settings, 'CURRENCY_SYMBOL', DEFAULT_CURRENCY_SYMBOL) or DEFAULT_CURRENCY_SYMBOL


def currency_code():
    """The currency code, e.g. ``KES``."""
    return getattr(settings, 'CURRENCY_CODE', 'KES') or 'KES'


def _to_decimal(value):
    """Best-effort conversion of a value to a Decimal, or None."""
    if value is None or value == '':
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def format_money(value, decimals=0, symbol=None):
    """Format an amount as ``KSh 3,120,000``.

    A missing value gives an empty string, so a template can print the
    result without guarding it. Pass ``symbol=''`` for a bare number, which
    is what the CSV exports want.
    """
    amount = _to_decimal(value)
    if amount is None:
        return ''
    if symbol is None:
        symbol = currency_symbol()
    try:
        if decimals:
            quantized = amount.quantize(Decimal(1).scaleb(-decimals))
        else:
            quantized = amount.quantize(Decimal(1))
    except InvalidOperation:
        # An amount too large to round at this precision is still worth
        # showing - a broken page is worse than a long number.
        quantized = amount
    number = f'{quantized:,.{decimals}f}'
    return f'{symbol} {number}' if symbol else number
