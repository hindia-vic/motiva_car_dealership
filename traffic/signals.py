"""SQLite tuning for the traffic write path.

Every tracked page view writes a row. In SQLite's default journal mode
("delete") a write takes an exclusive lock on the database file, so readers
block while it happens - and the pages being counted are exactly the pages
being read at the same time.

WAL (Write-Ahead Logging) lets readers and the writer work at the same
time, which keeps the per-request insert from slowing down the site.

The pragma is best effort: on a filesystem that cannot support WAL the
project simply stays in the current journal mode.
"""

import logging

from django.db.backends.signals import connection_created
from django.dispatch import receiver

logger = logging.getLogger(__name__)

#: Switches SQLite into write-ahead logging mode.
WAL_PRAGMA = 'PRAGMA journal_mode=WAL'


@receiver(connection_created)
def enable_sqlite_wal(sender, connection, **kwargs):
    """Turn on WAL mode for SQLite connections, ignoring refusals."""
    if connection.vendor != 'sqlite':
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute(WAL_PRAGMA)
    except Exception as exc:
        # Network filesystems and some container volumes cannot do WAL.
        # That is not fatal - the site just keeps the default journal mode.
        logger.warning(
            'Could not enable SQLite WAL mode (%s); staying on the default '
            'journal mode.',
            exc,
        )
