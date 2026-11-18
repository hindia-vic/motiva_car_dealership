"""Widen the saved-at price so shilling amounts fit.

``Favorite.price_at_save`` is the asking price at the moment a customer
saved a car, and it is compared against the current asking price to
decide whether to send a price-drop alert. It has to be converted along
with the rest of the prices, or every saved car would look like it had
dropped by 99%.

This is a schema change only. The values are converted by
``python manage.py convert_prices_to_shillings`` rather than by the
migration, because a migration cannot tell a dollar amount from a
shilling amount that has already been entered by hand.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_profile_avatar'),
    ]

    operations = [
        migrations.AlterField(
            model_name='favorite',
            name='price_at_save',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Asking price when the car was favorited, used for price-drop alerts', max_digits=12, null=True),
        ),
    ]
