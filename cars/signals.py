"""Signals that record car price/status changes for customer alerts.

When staff edit a car and lower its asking price, or move it back to
``available``, we log a history row. The ``send_car_alerts`` command later
reads the un-notified rows and emails interested customers.

The same module also cleans up photo files when a photo is deleted, so
the media folder does not fill up with orphans.
"""
import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import (
    Car, CarImage, CarPriceHistory, CarStatusHistory,
    ListingRequestPhoto,
)

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Car)
def _stash_previous_car_state(sender, instance, **kwargs):
    """Remember the stored price/status so post_save can compare."""
    if not instance.pk:
        instance._previous_state = None
        return
    try:
        previous = Car.objects.get(pk=instance.pk)
    except Car.DoesNotExist:
        instance._previous_state = None
        return
    instance._previous_state = {
        'asking_price': previous.asking_price,
        'status': previous.status,
    }


@receiver(post_save, sender=Car)
def _record_car_change(sender, instance, created, raw, update_fields, **kwargs):
    """Create a price-drop or back-in-stock history row when appropriate."""
    if created or raw:
        return

    previous = getattr(instance, '_previous_state', None)
    if not previous:
        return

    # Respect partial saves: only look at fields that were actually written.
    if update_fields is not None:
        written = set(update_fields)
        check_price = 'asking_price' in written
        check_status = 'status' in written
    else:
        check_price = check_status = True

    if check_price and instance.asking_price < previous['asking_price']:
        CarPriceHistory.objects.create(
            car=instance,
            old_price=previous['asking_price'],
            new_price=instance.asking_price,
        )

    if check_status and instance.status != previous['status'] and instance.status == 'available':
        CarStatusHistory.objects.create(
            car=instance,
            old_status=previous['status'],
            new_status=instance.status,
        )


@receiver(post_delete, sender=CarImage)
def _delete_photo_files(sender, instance, **kwargs):
    """Remove the photo and its thumbnail from disk when the row goes.

    Django does not delete files when a FileField row is removed, so
    without this the media folder keeps every photo ever uploaded.
    """
    for field in ('image', 'thumbnail'):
        file = getattr(instance, field, None)
        if not file:
            continue
        try:
            file.storage.delete(file.name)
        except Exception:
            logger.warning(
                'Could not delete %s for %s', file.name, instance.car,
                exc_info=True,
            )


@receiver(post_delete, sender=ListingRequestPhoto)
def _delete_listing_photo_files(sender, instance, **kwargs):
    """Remove an owner's uploaded photo from disk when the row goes.

    The owner's photos are stored under their own folder, so they are
    cleaned up the same way the dealership's photos are.
    """
    for field in ('photo', 'thumbnail'):
        file = getattr(instance, field, None)
        if not file:
            continue
        try:
            file.storage.delete(file.name)
        except Exception:
            logger.warning(
                'Could not delete %s for %s', file.name, instance.request,
                exc_info=True,
            )
