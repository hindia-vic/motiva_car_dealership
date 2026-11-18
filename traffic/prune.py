"""Automatic pruning of expired traffic rows.

Raw visitor IP addresses are personal data, so the table is deliberately
kept small. Rows older than ``TRAFFIC_RETENTION_DAYS`` are removed
automatically, at most once a day, so the site does not depend on an
external scheduled job to stay tidy.

The ``purge_traffic_data`` management command remains available for manual
runs and for a different retention window.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import PageView

logger = logging.getLogger(__name__)

#: Cache key holding the date the automatic prune last ran.
PRUNE_FLAG_KEY = 'traffic:pruned:{date}'


def prune_expired(force=False, days=None):
    """Delete page views older than the retention window.

    Returns the number of rows deleted. Unless *force* is true the delete
    runs at most once a day per process, guarded by a cache flag, so it is
    cheap to call from the request path.
    """
    if not force and not getattr(settings, 'TRAFFIC_AUTO_PRUNE', True):
        return 0

    days = days or getattr(settings, 'TRAFFIC_RETENTION_DAYS', 90)
    cutoff = timezone.now() - timedelta(days=days)

    if not force:
        key = PRUNE_FLAG_KEY.format(date=timezone.localtime().date().isoformat())
        try:
            # cache.add only stores the key when it is missing, so the first
            # caller of the day wins and the rest are a no-op.
            if not cache.add(key, 1, timeout=86400):
                return 0
        except Exception:
            # A broken cache must not stop the prune from happening.
            logger.warning('Traffic auto-prune: cache unavailable', exc_info=True)

    deleted, _ = PageView.objects.filter(created_at__lt=cutoff).delete()
    logger.info('Traffic auto-prune: deleted %s expired page view(s)', deleted)
    return deleted
