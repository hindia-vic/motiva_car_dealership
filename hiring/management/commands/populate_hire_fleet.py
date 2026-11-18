"""Seed the hire fleet with a realistic set of cars.

A fresh install has an empty fleet, which makes the hire pages look
broken. This fills it with the cars a Kenyan dealership would actually
hire out, at the rates they actually charge, and the add-ons a customer
can order with them, so the pages can be looked at and demoed straight
away.

It is safe to run more than once: a car is matched on make, model and
year, so a second run changes nothing.

    python manage.py populate_hire_fleet
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from hiring.models import HireAddOn, HireCar


#: Rates are per day, in shillings. The tour rate includes the driver.
FLEET = [
    {
        'make': 'Toyota',
        'model': 'Prado TX-L',
        'year': 2020,
        'color': 'Pearl White',
        'body_type': 'suv',
        'transmission': 'automatic',
        'fuel_type': 'diesel',
        'seats': 7,
        'luggage_capacity': 4,
        'hire_daily_rate': Decimal('12000.00'),
        'tour_daily_rate': Decimal('18000.00'),
        'allows_tours': True,
        'description': (
            'The car for a safari or a long up-country trip. Four-wheel '
            'drive, plenty of room for luggage and comfortable on rough '
            'roads.'
        ),
    },
    {
        'make': 'Toyota',
        'model': 'Fortuner',
        'year': 2021,
        'color': 'Silver',
        'body_type': 'suv',
        'transmission': 'automatic',
        'fuel_type': 'diesel',
        'seats': 7,
        'luggage_capacity': 3,
        'hire_daily_rate': Decimal('10000.00'),
        'tour_daily_rate': Decimal('15000.00'),
        'allows_tours': True,
        'description': (
            'A seven-seat SUV that handles both the city and the highway. '
            'Popular for family trips and airport runs.'
        ),
    },
    {
        'make': 'Nissan',
        'model': 'X-Trail',
        'year': 2020,
        'color': 'Grey',
        'body_type': 'suv',
        'transmission': 'cvt',
        'fuel_type': 'petrol',
        'seats': 5,
        'luggage_capacity': 3,
        'hire_daily_rate': Decimal('8000.00'),
        'tour_daily_rate': Decimal('12500.00'),
        'allows_tours': True,
        'description': (
            'Comfortable and economical for a small group. Good ground '
            'clearance for the parks without the running cost of a big '
            'diesel.'
        ),
    },
    {
        'make': 'Toyota',
        'model': 'Noah',
        'year': 2019,
        'color': 'Black',
        'body_type': 'van',
        'transmission': 'automatic',
        'fuel_type': 'petrol',
        'seats': 7,
        'luggage_capacity': 4,
        'hire_daily_rate': Decimal('6500.00'),
        'tour_daily_rate': Decimal('10000.00'),
        'allows_tours': True,
        'description': (
            'A roomy people carrier for transfers and city work. Sliding '
            'doors make loading easy.'
        ),
    },
    {
        'make': 'Toyota',
        'model': 'Vitz',
        'year': 2018,
        'color': 'Red',
        'body_type': 'hatchback',
        'transmission': 'automatic',
        'fuel_type': 'petrol',
        'seats': 5,
        'luggage_capacity': 2,
        'hire_daily_rate': Decimal('3500.00'),
        'tour_daily_rate': Decimal('0.00'),
        'allows_tours': False,
        'description': (
            'The cheapest way to get around town. Light on fuel and easy '
            'to park. Self-drive only.'
        ),
    },
    {
        'make': 'Toyota',
        'model': 'Hiace',
        'year': 2017,
        'color': 'White',
        'body_type': 'minibus',
        'transmission': 'manual',
        'fuel_type': 'diesel',
        'seats': 14,
        'luggage_capacity': 8,
        'hire_daily_rate': Decimal('9000.00'),
        'tour_daily_rate': Decimal('14000.00'),
        'allows_tours': True,
        'description': (
            'Fourteen seats for a group, a choir or a company outing. '
            'Comes with a driver on tour bookings.'
        ),
    },
    {
        'make': 'Mercedes-Benz',
        'model': 'C200',
        'year': 2019,
        'color': 'Black',
        'body_type': 'sedan',
        'transmission': 'automatic',
        'fuel_type': 'petrol',
        'seats': 5,
        'luggage_capacity': 2,
        'hire_daily_rate': Decimal('15000.00'),
        'tour_daily_rate': Decimal('22000.00'),
        'allows_tours': True,
        'description': (
            'For weddings, executive visits and airport pickups. Valeted '
            'before every booking.'
        ),
    },
]


#: The extras that go with a hire. The prices are what a Nairobi hirer
#: expects to pay, and the units decide how each one is charged.
ADD_ONS = [
    {
        'name': 'Child seat',
        'description': 'A properly fitted seat for a child under 12.',
        'price': Decimal('500.00'),
        'unit': 'per_day',
        'sort_order': 10,
    },
    {
        'name': 'Extra driver',
        'description': 'Put a second named driver on the cover.',
        'price': Decimal('1000.00'),
        'unit': 'per_booking',
        'sort_order': 20,
    },
    {
        'name': 'Airport delivery',
        'description': 'We bring the car to arrivals and collect it there.',
        'price': Decimal('1500.00'),
        'unit': 'per_booking',
        'sort_order': 30,
    },
    {
        'name': 'Cooler box',
        'description': 'A 24-litre cooler for the road.',
        'price': Decimal('300.00'),
        'unit': 'per_day',
        'sort_order': 40,
    },
    {
        'name': 'Wi-Fi hotspot',
        'description': 'A pocket router with data for the trip.',
        'price': Decimal('700.00'),
        'unit': 'per_day',
        'sort_order': 50,
    },
]


class Command(BaseCommand):
    help = 'Populate the database with a sample car hire fleet'

    def handle(self, *args, **options):
        created_count = 0

        for car_data in FLEET:
            car, created = HireCar.objects.get_or_create(
                make=car_data['make'],
                model=car_data['model'],
                year=car_data['year'],
                defaults=car_data,
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Added to the fleet: {car}')
                )

        if not created_count:
            self.stdout.write('The hire fleet is already populated.')

        for add_on_data in ADD_ONS:
            add_on, created = HireAddOn.objects.get_or_create(
                name=add_on_data['name'],
                defaults=add_on_data,
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Added add-on: {add_on}')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. {HireCar.objects.count()} car'
                f'{"s" if HireCar.objects.count() != 1 else ""} in the fleet, '
                f'{HireAddOn.objects.count()} add-on'
                f'{"s" if HireAddOn.objects.count() != 1 else ""}.'
            )
        )
