"""Convert a dollar-priced database to shillings.

The site deals in Kenyan shillings, but the prices that were seeded into
an existing database were in dollars. This command multiplies every
stored price by the exchange rate so the numbers become shillings.

It is a command rather than a migration on purpose. A data migration
runs by itself on every database that is brought up to date, and it
cannot tell a dollar amount from a shilling amount that was typed in by
hand - so it would quietly multiply a real vehicle's price by 130.
Running this deliberately means nobody's real prices are changed by
accident.

The rate is a constant, not a setting, so a conversion always happens at
the rate that was reviewed and tested.

    python manage.py convert_prices_to_shillings --dry-run   # preview
    python manage.py convert_prices_to_shillings             # do it
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Favorite
from cars.models import (
    Car, CarPriceHistory, Order, SalesTransaction, SavedSearch, ServiceRecord,
)

#: Kenyan shillings per US dollar - the rate the seeded prices came from.
RATE = Decimal('130')

#: (model, field names) for every money column.
MONEY_FIELDS = (
    (Car, ('purchase_price', 'asking_price')),
    (CarPriceHistory, ('old_price', 'new_price')),
    (SalesTransaction, (
        'sale_price', 'trade_in_value', 'total_amount', 'down_payment',
        'financed_amount',
    )),
    (ServiceRecord, ('cost',)),
    (Order, ('price', 'trade_in_value', 'down_payment', 'trade_in_estimate')),
    (SavedSearch, ('price_min', 'price_max')),
    (Favorite, ('price_at_save',)),
)

#: How many rows to write per statement.
BATCH_SIZE = 500


class Command(BaseCommand):
    help = 'Convert every stored price from dollars to Kenyan shillings'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would change without writing anything',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        self.stdout.write(
            f'Converting prices at {RATE} shillings to the dollar'
            + (' (dry run - nothing is written)' if dry_run else '')
        )

        with transaction.atomic():
            for model, fields in MONEY_FIELDS:
                for field_name in fields:
                    self._convert_field(model, field_name, dry_run)

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run: nothing was changed'))
        else:
            self.stdout.write(self.style.SUCCESS('Prices converted to shillings'))

    def _convert_field(self, model, field_name, dry_run):
        """Multiply one money column by the rate."""
        rows = list(
            model.objects
            .filter(**{f'{field_name}__isnull': False})
            .values_list('pk', field_name)
        )
        if not rows:
            return

        label = f'{model._meta.label}.{field_name}'
        self.stdout.write(f'  {label}: {len(rows)} row(s)')

        if dry_run:
            for pk, value in rows[:3]:
                converted = self._convert(value)
                self.stdout.write(f'    row {pk}: {value} -> {converted}')
            if len(rows) > 3:
                self.stdout.write(f'    ... and {len(rows) - 3} more')
            return

        for start in range(0, len(rows), BATCH_SIZE):
            batch = rows[start:start + BATCH_SIZE]
            updates = [
                model(pk=pk, **{field_name: self._convert(value)})
                for pk, value in batch
            ]
            model.objects.bulk_update(updates, [field_name], batch_size=BATCH_SIZE)

    @staticmethod
    def _convert(value):
        """One amount, converted and rounded to the nearest cent."""
        return (Decimal(value) * RATE).quantize(Decimal('0.01'))
