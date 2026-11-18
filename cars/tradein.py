"""Trade-in valuation rules.

The numbers live in code rather than in a table staff can edit from the
admin: an appraisal is only as good as its rules, and rules that anyone
can change without review are rules nobody trusts. Adjust them here,
review the change, and deploy it.

The estimate is deliberately simple and explainable:

    value = indicative new price (body type)
          x make factor
          x model factor
          x depreciation (age)
          x mileage factor
          x condition factor

Every step can be shown to the customer, which is what makes an online
estimate worth anything: the dealer sees the same arithmetic the visitor
does, and can argue with the numbers instead of the promise.

Nothing here needs a third-party package.
"""

from datetime import date

#: Indicative new-vehicle price by body type, in shillings.
NEW_PRICE_BY_BODY_TYPE = {
    'hatchback': 2730000,
    'sedan': 3510000,
    'coupe': 4030000,
    'wagon': 3510000,
    'suv': 4550000,
    'pickup': 4810000,
    'truck': 4810000,
    'van': 4290000,
    'minivan': 4290000,
    'convertible': 5460000,
}

#: Used when the body type is unknown or not in the table.
DEFAULT_NEW_PRICE = 3510000

#: The body types the estimate knows about.
BODY_TYPES = tuple(sorted(NEW_PRICE_BY_BODY_TYPE))

#: Brand factor applied to the indicative new price. Premium brands hold
#: their value better, budget brands less so.
MAKE_FACTORS = {
    'acura': 1.12,
    'audi': 1.22,
    'bmw': 1.25,
    'buick': 0.9,
    'cadillac': 0.95,
    'chevrolet': 0.92,
    'chrysler': 0.88,
    'dodge': 0.9,
    'ford': 0.95,
    'gmc': 0.97,
    'honda': 1.04,
    'hyundai': 0.88,
    'infiniti': 1.1,
    'jeep': 1.05,
    'kia': 0.88,
    'land rover': 1.35,
    'lexus': 1.18,
    'lincoln': 1.05,
    'mazda': 1.0,
    'mercedes-benz': 1.28,
    'mercedes': 1.28,
    'mitsubishi': 0.82,
    'nissan': 0.95,
    'porsche': 1.9,
    'ram': 1.0,
    'subaru': 1.02,
    'tesla': 1.35,
    'toyota': 1.05,
    'volkswagen': 1.0,
    'volvo': 1.1,
}

#: Used for makes that are not in the table.
DEFAULT_MAKE_FACTOR = 1.0

#: Model factor for the models this dealership sells most. Models that are
#: not listed simply use the make factor.
MODEL_FACTORS = {
    'altima': 0.9,
    'avalon': 1.15,
    'camry': 1.0,
    'canyon': 0.95,
    'civic': 0.9,
    'colorado': 1.0,
    'compass': 0.9,
    'corolla': 0.85,
    'cr-v': 1.1,
    'cruze': 0.75,
    'elantra': 0.78,
    'equinox': 0.85,
    'escape': 0.85,
    'explorer': 1.0,
    'f-150': 1.05,
    'fusion': 0.8,
    'grand cherokee': 0.85,
    'highlander': 1.08,
    'impala': 0.78,
    'malibu': 0.8,
    'mustang': 1.2,
    'odyssey': 1.05,
    'optima': 0.82,
    'outback': 1.0,
    'pilot': 1.15,
    'ranger': 0.95,
    'rav4': 1.05,
    'rogue': 0.9,
    'sentra': 0.75,
    'sienna': 1.05,
    'silverado': 1.0,
    'sonata': 0.8,
    'tacoma': 1.05,
    'tahoe': 1.35,
    'tiguan': 0.95,
    'traverse': 1.0,
    'tucson': 0.92,
    'wrangler': 1.3,
}

#: Share of the new price a vehicle is still worth as it ages. The value
#: between two entries is interpolated.
AGE_VALUES = (
    (0, 1.00),
    (1, 0.86),
    (2, 0.75),
    (3, 0.66),
    (4, 0.58),
    (5, 0.51),
    (6, 0.45),
    (7, 0.40),
    (8, 0.35),
    (9, 0.31),
    (10, 0.27),
    (12, 0.21),
    (15, 0.15),
    (20, 0.09),
    (25, 0.05),
)

#: Factor applied for the condition of the vehicle.
CONDITION_FACTORS = {
    'excellent': 1.00,
    'good': 0.92,
    'fair': 0.80,
    'poor': 0.62,
}

#: Used for conditions that are not in the table.
DEFAULT_CONDITION_FACTOR = 0.90

#: The condition choices offered on the trade-in form.
CONDITION_CHOICES = (
    ('excellent', 'Excellent - like new'),
    ('good', 'Good - normal wear'),
    ('fair', 'Fair - visible wear'),
    ('poor', 'Poor - needs work'),
)

#: Miles a vehicle is expected to cover in a year.
AVERAGE_ANNUAL_MILEAGE = 12000

#: The range the midpoint is quoted over.
LOW_FACTOR = 0.85
HIGH_FACTOR = 1.15

#: Estimates are rounded to the nearest 1,000 shillings.
ROUNDING_STEP = 1000


def _round_to(value, step=ROUNDING_STEP):
    """Round a value to the nearest step, never below zero."""
    if value <= 0:
        return 0
    return int(round(value / step) * step)


def current_year():
    """The year an estimate is based on."""
    return date.today().year


def age_of(year, today=None):
    """The age of a vehicle in years, or ``None`` when the year is unusable."""
    today = today or date.today()
    try:
        year = int(year)
    except (TypeError, ValueError):
        return None
    if year < 1900 or year > today.year + 1:
        return None
    return max(0, today.year - year)


def new_price(body_type=''):
    """The indicative price of the vehicle when it was new."""
    key = (body_type or '').strip().lower()
    return NEW_PRICE_BY_BODY_TYPE.get(key, DEFAULT_NEW_PRICE)


def make_factor(make):
    """The factor applied for the brand of the vehicle."""
    key = (make or '').strip().lower()
    return MAKE_FACTORS.get(key, DEFAULT_MAKE_FACTOR)


def model_factor(model):
    """The factor applied for the model of the vehicle."""
    key = (model or '').strip().lower()
    return MODEL_FACTORS.get(key, 1.0)


def age_factor(age):
    """The share of the new price the vehicle is still worth."""
    if age is None:
        return 0.0
    table = AGE_VALUES
    if age <= table[0][0]:
        return table[0][1]
    if age >= table[-1][0]:
        return table[-1][1]
    for (low_age, low_value), (high_age, high_value) in zip(table, table[1:]):
        if low_age <= age <= high_age:
            span = high_age - low_age
            ratio = (age - low_age) / span if span else 0.0
            return low_value + (high_value - low_value) * ratio
    return table[-1][1]


def mileage_factor(mileage, age):
    """The factor applied for how the mileage compares to the average.

    A vehicle that has covered less than average is worth a little more,
    one that has covered much more is worth noticeably less.
    """
    try:
        mileage = int(mileage or 0)
    except (TypeError, ValueError):
        return 1.0
    if mileage <= 0:
        return 1.0

    expected = max(AVERAGE_ANNUAL_MILEAGE * max(age or 1, 1), 3000)
    ratio = mileage / expected
    if ratio <= 1.0:
        # Under the average: a bonus, but a small one.
        return min(1.05, 1.0 + (1.0 - ratio) * 0.25)
    # Over the average: every 10% over costs 5% of the value.
    return max(0.55, 1.0 - (ratio - 1.0) / 0.1 * 0.05)


def condition_factor(condition):
    """The factor applied for the condition of the vehicle."""
    key = (condition or '').strip().lower()
    return CONDITION_FACTORS.get(key, DEFAULT_CONDITION_FACTOR)


def estimate(year, make, model='', mileage=0, condition='good', body_type=''):
    """Return a ``(low, high, mid)`` trade-in estimate in shillings.

    ``mid`` is the number an appraisal would be based on, ``low`` and
    ``high`` are the range it is quoted over. ``(0, 0, 0)`` comes back
    when the year is missing or impossible, because there is nothing
    sensible to say then.
    """
    age = age_of(year)
    if age is None:
        return (0, 0, 0)

    mid = (
        new_price(body_type)
        * make_factor(make)
        * model_factor(model)
        * age_factor(age)
        * mileage_factor(mileage, age)
        * condition_factor(condition)
    )
    mid = _round_to(mid)
    if mid <= 0:
        return (0, 0, 0)

    low = _round_to(mid * LOW_FACTOR)
    high = _round_to(mid * HIGH_FACTOR)
    if high <= low:
        high = low + ROUNDING_STEP
    return (low, high, mid)


def breakdown(year, make, model='', mileage=0, condition='good', body_type=''):
    """The steps of the calculation, for showing to the customer.

    Returns a dictionary with every factor that went into the estimate,
    so the page can show the arithmetic instead of just a number.
    """
    age = age_of(year)
    low, high, mid = estimate(
        year, make, model=model, mileage=mileage,
        condition=condition, body_type=body_type,
    )
    return {
        'age': age,
        'year': year,
        'make': make or '',
        'model': model or '',
        'body_type': body_type or '',
        'new_price': new_price(body_type),
        'make_factor': make_factor(make),
        'model_factor': model_factor(model),
        'age_factor': age_factor(age) if age is not None else 0.0,
        'mileage_factor': mileage_factor(mileage, age) if age is not None else 1.0,
        'condition_factor': condition_factor(condition),
        'low': low,
        'high': high,
        'mid': mid,
        'valid': bool(mid),
    }
