"""Creating notifications.

Everything that wants to tell a user something goes through :func:`notify`
so there is one place that decides what a notification looks like, and one
place to change if the model grows.
"""

from django.contrib.auth import get_user_model

from .models import Notification


def notify(user, title, message, level='info', obj=None, url=''):
    """Create a notification for ``user``.

    Returns ``None`` when there is nobody to notify (guest orders, a
    deactivated account) so callers never have to guard the call.
    """
    if user is None or not getattr(user, 'is_active', True):
        return None
    return Notification.objects.create(
        user=user,
        title=title[:200],
        message=message,
        level=level,
        content_object=obj,
        url=url or '',
    )


def notify_staff(title, message, level='info', obj=None, url='', exclude_user=None):
    """Create the same notification for every active staff member."""
    User = get_user_model()
    staff = User.objects.filter(is_staff=True, is_active=True)
    if exclude_user is not None and exclude_user.is_authenticated:
        staff = staff.exclude(pk=exclude_user.pk)
    return [
        notify(user, title, message, level=level, obj=obj, url=url)
        for user in staff
    ]
