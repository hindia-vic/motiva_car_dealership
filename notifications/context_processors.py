"""Expose the signed-in user's unread notifications to every template."""

from .models import Notification

#: How many notifications the navbar dropdown shows.
RECENT_LIMIT = 5


def notification_center(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {'unread_notification_count': 0, 'recent_notifications': []}

    try:
        queryset = Notification.objects.filter(user=user)
        return {
            'unread_notification_count': queryset.filter(is_read=False).count(),
            'recent_notifications': list(queryset[:RECENT_LIMIT]),
        }
    except Exception:
        # A notification lookup must never take a page down with it.
        return {'unread_notification_count': 0, 'recent_notifications': []}
