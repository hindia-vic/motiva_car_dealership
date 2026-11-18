"""The deposit rule for online vehicle orders.

A customer reserves a car by paying a deposit online; the rest is settled
with staff when the paperwork is done. The rule lives here as plain code
constants, for the same reason the trade-in and listing rules do: a number
that anyone can quietly change in the admin is a number nobody can rely on.

The rule
--------
* 10% of what is payable after the trade-in,
* rounded *up* to the next KSh 1,000,
* but never less than KSh 50,000,
* and never more than the amount payable.

The amount is copied onto the order when the order is placed, so raising
the minimum later never rewrites what a customer was already quoted.
"""

from decimal import Decimal, InvalidOperation, ROUND_CEILING

from django.conf import settings

#: Fraction of the amount payable that we ask for up front.
DEFAULT_DEPOSIT_RATIO = Decimal('0.10')

#: The smallest deposit we accept, whatever the arithmetic says.
DEFAULT_DEPOSIT_MINIMUM = Decimal('50000.00')

#: Deposits are quoted in round thousands.
DEFAULT_DEPOSIT_ROUNDING = Decimal('1000.00')


def _to_decimal(value):
    """Best-effort conversion of a value to a Decimal."""
    if value is None or value == '':
        return Decimal('0')
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _setting(name, default):
    return _to_decimal(getattr(settings, name, default))


def deposit_ratio():
    """The fraction of the amount payable asked for up front."""
    return _setting('ORDER_DEPOSIT_RATIO', DEFAULT_DEPOSIT_RATIO)


def deposit_minimum():
    """The smallest deposit accepted."""
    return _setting('ORDER_DEPOSIT_MINIMUM', DEFAULT_DEPOSIT_MINIMUM)


def deposit_rounding():
    """The step deposits are rounded up to."""
    return _setting('ORDER_DEPOSIT_ROUNDING', DEFAULT_DEPOSIT_ROUNDING)


def amount_payable(price, trade_in_value=0):
    """What the customer still owes after their trade-in."""
    payable = _to_decimal(price) - _to_decimal(trade_in_value)
    if payable < 0:
        return Decimal('0.00')
    return payable.quantize(Decimal('0.01'))


def order_deposit(price, trade_in_value=0):
    """The deposit to ask for on an order.

    Ten percent of the amount payable, rounded up to the next thousand,
    with a floor of KSh 50,000 and a ceiling of the amount payable itself.
    A car worth less than the floor is paid for in full rather than
    asking for more than it costs.
    """
    payable = amount_payable(price, trade_in_value)
    if payable <= 0:
        return Decimal('0.00')

    deposit = (payable * deposit_ratio()).quantize(Decimal('0.01'))

    step = deposit_rounding()
    if step > 0:
        deposit = (
            (deposit / step).to_integral_value(rounding=ROUND_CEILING) * step
        )

    deposit = max(deposit, deposit_minimum())
    deposit = min(deposit, payable)
    return deposit.quantize(Decimal('0.01'))
