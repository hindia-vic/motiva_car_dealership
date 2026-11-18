"""The rules for listing a customer's car on the website.

A customer asks us to advertise their vehicle for a fee. The fee, and what
that fee buys (verification of the car and of the logbook before anything
goes live), live here as plain code constants - for the same reason the
trade-in valuation rules do: a rule anyone can change from the admin is a
rule nobody trusts.

The amount is copied onto each request when the request is created, so
raising the fee later never rewrites what a customer was quoted.
"""

from decimal import Decimal, InvalidOperation

from django.conf import settings

#: What we charge to have a customer's car listed on the website.
DEFAULT_LISTING_FEE = Decimal('2500.00')


def listing_fee():
    """The fee charged to have a customer's car listed on the website."""
    fee = getattr(settings, 'LISTING_FEE', DEFAULT_LISTING_FEE)
    try:
        return Decimal(str(fee))
    except (InvalidOperation, TypeError, ValueError):
        return DEFAULT_LISTING_FEE
