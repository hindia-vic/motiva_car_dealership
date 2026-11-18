"""The rules behind a hire booking: how long it runs and what it costs.

The daily rate itself is set on the car by staff, so this module only
says how a rate becomes a price and how a booking takes a car out of
service.

The rules live in code, like the trade-in valuation rules, because a
pricing rule anybody can change without a review is a pricing rule
nobody can quote.
"""

from decimal import Decimal, InvalidOperation, ROUND_CEILING


#: A hire that starts and ends on the same day is still a day's hire.
#: The customer has the car for that day.
MINIMUM_DAYS = 1

#: What we ask a customer to leave as security for the car. It is not part
#: of the hire price: it is held and given back when the car comes home.
SECURITY_DEPOSIT_RATIO = Decimal('0.20')

#: The deposit is rounded up to a round figure, because it is handed over
#: in cash or by M-Pesa and nobody wants to count shillings.
DEPOSIT_ROUNDING = Decimal('500')

#: The statuses that take a car out of service. A booking that clashes
#: with one of these cannot be made or confirmed.
BLOCKING_STATUSES = ('confirmed', 'active')

#: The statuses that do NOT take a car out of service. A request that was
#: never confirmed, was rejected, or was cancelled leaves the car free.
FREE_STATUSES = ('rejected', 'cancelled')

#: Payment states that let a booking be confirmed. A deposit counts: staff
#: can confirm on a part payment and collect the balance before collection.
CONFIRMABLE_PAYMENT_STATUSES = ('paid', 'partial')


def rental_days(start_date, end_date):
    """The number of days a booking covers, counting both ends.

    Picking a car up on Monday and bringing it back on Monday is one
    day of hire, not zero: the car was out of the yard.
    """
    if not start_date or not end_date:
        return 0
    days = (end_date - start_date).days + 1
    return max(days, MINIMUM_DAYS)


def quote(daily_rate, days):
    """What a booking costs at the given daily rate."""
    try:
        rate = Decimal(str(daily_rate))
    except (InvalidOperation, TypeError, ValueError):
        rate = Decimal('0')
    return (rate * max(int(days), 0)).quantize(Decimal('0.01'))


def suggested_security_deposit(price):
    """The deposit we suggest for a hire of the given price.

    A fifth of the hire, rounded up to the next 500 shillings. Staff can
    change it on the booking: a long tour in a new car may need more.
    """
    try:
        price = Decimal(str(price))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0.00')
    if price <= 0:
        return Decimal('0.00')
    amount = price * SECURITY_DEPOSIT_RATIO
    rounded = (amount / DEPOSIT_ROUNDING).to_integral_value(
        rounding=ROUND_CEILING
    ) * DEPOSIT_ROUNDING
    return rounded.quantize(Decimal('0.01'))
