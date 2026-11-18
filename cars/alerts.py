"""Gather alert recipients and send pending price-drop / back-in-stock emails.

Both the ``send_car_alerts`` management command and the staff "Send alerts now"
button call :func:`send_pending_alerts`, so the behaviour stays in one place.
"""
from django.utils import timezone

from .emails import send_back_in_stock_email, send_price_drop_email
from .models import CarPriceHistory, CarStatusHistory, SavedSearch


def _profile_allows(user, flag):
    """Return False only when the user's profile explicitly opted out."""
    profile = getattr(user, 'profile', None)
    return profile is None or getattr(profile, flag)


def price_drop_recipients(car):
    """Map recipient email -> price when they favorited the car (or None).

    Includes users who favorited the car (respecting their opt-out) and active
    saved searches whose criteria the car matches.
    """
    # Imported lazily; accounts.Favorite imports cars.Car by string reference.
    from accounts.models import Favorite

    recipients = {}
    favorites = Favorite.objects.filter(car=car).select_related('user')
    for favorite in favorites:
        user = favorite.user
        if not user.email or not user.is_active:
            continue
        if not _profile_allows(user, 'notify_price_drops'):
            continue
        # Keep the earliest saved price if somehow favorited twice.
        recipients.setdefault(user.email, favorite.price_at_save)

    for search in SavedSearch.objects.filter(is_active=True, notify_price_drops=True):
        if search.email in recipients:
            continue
        if search.match_cars().filter(pk=car.pk).exists():
            recipients[search.email] = None

    return recipients


def back_in_stock_recipients(car):
    """Set of emails to notify when ``car`` returns to the available lot."""
    from accounts.models import Favorite

    recipients = set()
    favorites = Favorite.objects.filter(car=car).select_related('user')
    for favorite in favorites:
        user = favorite.user
        if not user.email or not user.is_active:
            continue
        if not _profile_allows(user, 'notify_back_in_stock'):
            continue
        recipients.add(user.email)

    for search in SavedSearch.objects.filter(is_active=True):
        if search.email in recipients:
            continue
        if search.match_cars().filter(pk=car.pk).exists():
            recipients.add(search.email)

    return recipients


def send_pending_alerts(dry_run=False):
    """Send all un-notified price-drop and back-in-stock alerts.

    Returns a summary dict and marks processed history rows as notified so the
    same event is never emailed twice.
    """
    now = timezone.now()
    price_emails = 0
    stock_emails = 0
    price_events = 0
    stock_events = 0

    for change in CarPriceHistory.objects.filter(notified_at__isnull=True).select_related('car'):
        recipients = price_drop_recipients(change.car)
        for email, saved_price in recipients.items():
            if not dry_run:
                send_price_drop_email(
                    email, change.car,
                    change.old_price, change.new_price,
                    saved_price=saved_price,
                )
            price_emails += 1
        price_events += 1
        if not dry_run:
            change.notified_at = now
            change.save(update_fields=['notified_at'])

    for change in CarStatusHistory.objects.filter(notified_at__isnull=True).select_related('car'):
        recipients = back_in_stock_recipients(change.car)
        for email in recipients:
            if not dry_run:
                send_back_in_stock_email(email, change.car)
            stock_emails += 1
        stock_events += 1
        if not dry_run:
            change.notified_at = now
            change.save(update_fields=['notified_at'])

    return {
        'price_events': price_events,
        'price_emails': price_emails,
        'stock_events': stock_events,
        'stock_emails': stock_emails,
    }
