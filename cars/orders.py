"""Abandoned-order recovery.

An order is a request, not a sale: it stays ``pending`` until staff review
it, and the deposit is paid online afterwards. This module owns the two
time-based rules around that gap:

* remind the customer about an unpaid deposit (once, after a day);
* let staff release a stale order and put the vehicle back on the lot.

Nothing here cancels an order automatically. Releasing is an explicit
staff action, because cancelling a customer's order is not a decision a
cron job should make.
"""

from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from notifications.services import notify, notify_staff

from .models import Order

#: How long after ordering the customer is reminded about the deposit.
DEPOSIT_REMINDER_AFTER_HOURS = 24

#: How old an unpaid order must be before staff see it as stale.
STALE_AFTER_DAYS = 7

#: Order statuses that still hold a vehicle.
OPEN_STATUSES = ('pending', 'confirmed', 'processing', 'ready_for_pickup')


def awaiting_deposit(queryset=None):
    """Live orders whose deposit has not been received yet."""
    queryset = queryset if queryset is not None else Order.objects.all()
    return queryset.filter(status='pending', deposit_paid_at__isnull=True)


def stale_orders(days=STALE_AFTER_DAYS, queryset=None, now=None):
    """Orders waiting on a deposit for longer than ``days``."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=days)
    return awaiting_deposit(queryset).filter(order_date__lt=cutoff)


def is_stale(order, days=STALE_AFTER_DAYS, now=None):
    now = now or timezone.now()
    return (
        order.is_awaiting_deposit()
        and order.order_date is not None
        and order.order_date < now - timedelta(days=days)
    )


def send_deposit_reminder(order):
    """Email one customer about their unpaid deposit. Returns True if sent."""
    if not order.is_awaiting_deposit():
        return False
    from .emails import send_order_deposit_reminder_email

    send_order_deposit_reminder_email(order)
    order.deposit_reminder_sent_at = timezone.now()
    order.save(update_fields=['deposit_reminder_sent_at'])
    return True


def send_deposit_reminders(now=None):
    """Send each waiting customer one reminder. Returns how many went out."""
    now = now or timezone.now()
    cutoff = now - timedelta(hours=DEPOSIT_REMINDER_AFTER_HOURS)
    due = awaiting_deposit().filter(
        order_date__lte=cutoff,
        deposit_reminder_sent_at__isnull=True,
    )
    return sum(1 for order in due if send_deposit_reminder(order))


@transaction.atomic
def release_order(order, actor=None, reason=''):
    """Cancel a pending order and put the car back on the lot.

    Only a ``pending`` order can be released: once staff have confirmed it,
    cancelling is a deliberate conversation, not a cleanup action. Returns
    True when the order was released.
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != 'pending':
        return False

    order.status = 'cancelled'
    order.released_at = timezone.now()
    order.release_reason = (reason or '').strip()[:255]
    order.save(update_fields=['status', 'released_at', 'release_reason'])

    _free_car(order)
    _tell_everyone(order, actor)
    return True


def _free_car(order):
    """Return the vehicle to the lot if no other live order still holds it."""
    car = order.car
    if car.status != 'reserved':
        return
    still_held = (
        Order.objects.filter(car=car, status__in=OPEN_STATUSES)
        .exclude(pk=order.pk)
        .exists()
    )
    if not still_held:
        car.status = 'available'
        car.save(update_fields=['status'])


def _tell_everyone(order, actor=None):
    from .emails import send_order_status_email

    send_order_status_email(order)
    notify(
        order.user,
        f'Order #{order.id} was released',
        f'Your order for {order.car} has been cancelled. '
        'Contact us if you would like to reopen it.',
        level='warning',
        obj=order,
        url=reverse('cars:my_activity'),
    )
    reason = f': {order.release_reason}' if order.release_reason else '.'
    notify_staff(
        f'Order #{order.id} released',
        f"{order.customer_name}'s order for {order.car} was released{reason}",
        obj=order,
        url=reverse('cars:orders_list'),
        exclude_user=actor if getattr(actor, 'is_authenticated', False) else None,
    )
