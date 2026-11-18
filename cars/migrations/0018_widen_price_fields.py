"""Widen the money columns so shilling amounts fit.

Every price in the database was seeded in dollars, and the site now deals
in Kenyan shillings. A shilling amount needs more room than the 10 digits
the columns were sized for: ``max_digits=10`` with two decimal places
caps a price at 99,999,999.99, which is under a hundred thousand dollars.

This is a schema change only. The values are **not** rewritten here: a
data migration that multiplied every price by the exchange rate would also
multiply the prices of any vehicle that had already been entered in
shillings, and no migration can tell the difference. Converting a
dollar-priced database is an explicit, deliberate act instead:

    python manage.py convert_prices_to_shillings --dry-run
    python manage.py convert_prices_to_shillings
"""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cars', '0017_order_trade_in_body_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='car',
            name='asking_price',
            field=models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AlterField(
            model_name='car',
            name='purchase_price',
            field=models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AlterField(
            model_name='carpricehistory',
            name='new_price',
            field=models.DecimalField(decimal_places=2, max_digits=12),
        ),
        migrations.AlterField(
            model_name='carpricehistory',
            name='old_price',
            field=models.DecimalField(decimal_places=2, max_digits=12),
        ),
        migrations.AlterField(
            model_name='order',
            name='down_payment',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AlterField(
            model_name='order',
            name='price',
            field=models.DecimalField(decimal_places=2, max_digits=12),
        ),
        migrations.AlterField(
            model_name='order',
            name='trade_in_estimate',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Online estimate the customer was shown', max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name='order',
            name='trade_in_value',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AlterField(
            model_name='salestransaction',
            name='down_payment',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AlterField(
            model_name='salestransaction',
            name='financed_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AlterField(
            model_name='salestransaction',
            name='sale_price',
            field=models.DecimalField(decimal_places=2, max_digits=12),
        ),
        migrations.AlterField(
            model_name='salestransaction',
            name='total_amount',
            field=models.DecimalField(decimal_places=2, max_digits=12),
        ),
        migrations.AlterField(
            model_name='salestransaction',
            name='trade_in_value',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AlterField(
            model_name='savedsearch',
            name='price_max',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name='savedsearch',
            name='price_min',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name='servicerecord',
            name='cost',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
    ]
