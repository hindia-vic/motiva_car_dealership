"""Rules for financing applications.

The arithmetic that decides whether a loan request is even plausible
lives here, not in the template or the admin. The amounts are copied onto
each application when it is submitted so that changing the rules later
never rewrites a customer's quote.
"""

from decimal import Decimal, InvalidOperation

from django.conf import settings


#: Default annual interest rate (percentage). Env-overridable.
DEFAULT_INTEREST_RATE = Decimal('14.5')

#: A customer must put down at least this fraction of the price.
MIN_DEPOSIT_RATIO = Decimal('0.10')

#: Maximum loan term offered.
MAX_TERM_MONTHS = 72

#: Common loan terms we show to the customer.
LOAN_TERMS = (12, 24, 36, 48, 60, 72)

#: The monthly repayment may not exceed this fraction of monthly income.
AFFORDABILITY_RATIO = Decimal('0.3333')


def _to_decimal(value):
    if value is None or value == '':
        return Decimal('0')
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def interest_rate():
    """The annual interest rate used to estimate repayments."""
    rate = getattr(settings, 'FINANCING_INTEREST_RATE', DEFAULT_INTEREST_RATE)
    return _to_decimal(rate)


def amount_financed(price, deposit, trade_in):
    """What still needs to be borrowed."""
    amount = _to_decimal(price) - _to_decimal(deposit) - _to_decimal(trade_in)
    if amount < 0:
        return Decimal('0')
    return amount


def monthly_payment(principal, annual_rate=None, months=None):
    """The estimated monthly repayment for an amortising loan.

    Returns Decimal('0') if the loan is not plausible.
    """
    principal = _to_decimal(principal)
    months = int(months or 0)
    rate = _to_decimal(annual_rate if annual_rate is not None else interest_rate())
    if principal <= 0 or months <= 0:
        return Decimal('0')
    # Convert annual percentage to a monthly decimal rate.
    monthly_rate = rate / Decimal('100') / Decimal('12')
    if monthly_rate == 0:
        return (principal / Decimal(str(months))).quantize(Decimal('0.01'))
    # PMT = P * r / (1 - (1+r)^(-n))
    numerator = principal * monthly_rate
    denominator = Decimal('1') - (Decimal('1') + monthly_rate) ** (-months)
    if denominator == 0:
        return Decimal('0')
    payment = numerator / denominator
    return payment.quantize(Decimal('0.01'))


def total_repayable(principal, annual_rate=None, months=None):
    """Total amount repaid over the life of the loan."""
    payment = monthly_payment(principal, annual_rate, months)
    months = int(months or 0)
    if payment == 0 or months <= 0:
        return Decimal('0')
    return (payment * Decimal(str(months))).quantize(Decimal('0.01'))


def min_deposit(price):
    """The smallest deposit we will accept for a given price."""
    return (_to_decimal(price) * MIN_DEPOSIT_RATIO).quantize(Decimal('0.01'))


def affordability_ok(income, payment):
    """True if the repayment fits within a third of net income."""
    income = _to_decimal(income)
    payment = _to_decimal(payment)
    if income <= 0:
        return False
    return payment <= income * AFFORDABILITY_RATIO
