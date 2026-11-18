"""Create a consistent database backup and prune old copies.

The daily Celery beat job (``cars.tasks.backup_database_task``) calls this
command, so a production deployment gets a backup without a separate cron
entry.

SQLite databases are snapshotted with the sqlite3 backup API (safe while the
site is serving). PostgreSQL uses ``pg_dump`` in custom format when the client
is installed, which is fast and can be restored with ``pg_restore``; if
``pg_dump`` is unavailable it falls back to a gzipped ``dumpdata`` JSON dump.

When object storage is configured (``USE_S3=true``), the dump is also uploaded
to the bucket under ``BACKUP_S3_PREFIX``. The local ``BACKUP_DIR`` on a PaaS is
ephemeral, so the bucket copy is what survives a redeploy.
"""

import gzip
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import FileSystemStorage, storages
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Back up the database into BACKUP_DIR and prune old copies.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            help='Write the backup to this exact path instead of BACKUP_DIR.',
        )
        parser.add_argument(
            '--keep',
            type=int,
            default=None,
            help='Delete backups older than this many days '
                 '(default: BACKUP_RETENTION_DAYS).',
        )
        parser.add_argument(
            '--no-prune',
            action='store_true',
            help='Keep old backups instead of applying the retention window.',
        )
        parser.add_argument(
            '--no-upload',
            action='store_true',
            help='Skip the object-storage upload even when USE_S3 is on.',
        )

    def handle(self, *args, **options):
        output = options.get('output')
        backup_dir = Path(output).expanduser().parent if output else Path(settings.BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        database = settings.DATABASES['default']
        engine = database.get('ENGINE', '')

        if 'sqlite3' in engine:
            path = Path(output) if output else backup_dir / f'db_backup_{timestamp}.sqlite3'
            self._backup_sqlite(Path(database['NAME']), path)
        else:
            path = self._backup_postgres_or_json(output, backup_dir, timestamp)

        self.stdout.write(self.style.SUCCESS(f'Backup created: {path}'))

        if getattr(settings, 'BACKUP_UPLOAD_TO_S3', False) and not options.get('no_upload'):
            self._upload(path)

        if not options.get('no_prune'):
            self._prune(backup_dir, options.get('keep'))
        return str(path)

    # -- engine-specific dumps ---------------------------------------------

    def _backup_postgres_or_json(self, output, backup_dir, timestamp):
        """Prefer ``pg_dump``; fall back to a portable JSON dump."""
        if output:
            destination = Path(output)
            if destination.name.endswith('.json.gz'):
                self._backup_dumpdata(destination)
                return destination
            if self._backup_postgres(destination):
                return destination
            self._backup_dumpdata(destination)
            return destination

        dump_path = backup_dir / f'db_backup_{timestamp}.dump'
        if self._backup_postgres(dump_path):
            return dump_path

        json_path = backup_dir / f'db_backup_{timestamp}.json.gz'
        self._backup_dumpdata(json_path)
        return json_path

    def _backup_postgres(self, destination):
        """Run ``pg_dump`` into ``destination``; return False when unavailable."""
        pg_dump = shutil.which('pg_dump')
        if not pg_dump:
            self.stdout.write(self.style.WARNING(
                'pg_dump not found; falling back to a gzipped JSON dump '
                '(slower and does not preserve the schema).'
            ))
            return False

        database = settings.DATABASES['default']
        environment = os.environ.copy()
        if database.get('PASSWORD'):
            environment['PGPASSWORD'] = str(database['PASSWORD'])

        command = [pg_dump, '--no-owner', '--no-acl', '--format=custom']
        if database.get('HOST'):
            command += ['--host', str(database['HOST'])]
        if database.get('PORT'):
            command += ['--port', str(database['PORT'])]
        if database.get('USER'):
            command += ['--username', str(database['USER'])]
        command += ['--file', str(destination), str(database.get('NAME', ''))]

        try:
            result = subprocess.run(
                command,
                env=environment,
                capture_output=True,
                text=True,
                timeout=int(getattr(settings, 'BACKUP_PGDUMP_TIMEOUT', 3600)),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            destination.unlink(missing_ok=True)
            self.stdout.write(self.style.WARNING(
                f'pg_dump failed ({exc}); falling back to a JSON dump.'
            ))
            return False

        if result.returncode != 0:
            destination.unlink(missing_ok=True)
            detail = (result.stderr or '').strip().splitlines()
            self.stdout.write(self.style.WARNING(
                'pg_dump failed'
                + (f': {detail[-1]}' if detail else '')
                + '; falling back to a JSON dump.'
            ))
            return False

        return True

    def _backup_sqlite(self, source_path, destination):
        name = str(source_path)
        # The test runner points NAME at a shared in-memory URI rather than a
        # file on disk; sqlite3 understands it with uri=True.
        is_uri = name.startswith('file:')
        if not is_uri and not source_path.exists():
            raise CommandError(f'Database not found: {source_path}')

        source = sqlite3.connect(name, uri=is_uri)
        destination_connection = sqlite3.connect(str(destination))
        try:
            # The backup API takes a consistent snapshot even while the site
            # is writing, unlike a plain file copy.
            source.backup(destination_connection)
        finally:
            destination_connection.close()
            source.close()

    def _backup_dumpdata(self, destination):
        try:
            with gzip.open(destination, 'wt', encoding='utf-8') as stream:
                call_command(
                    'dumpdata',
                    '--natural-foreign',
                    '--natural-primary',
                    '--exclude', 'contenttypes',
                    '--exclude', 'auth.permission',
                    '--exclude', 'sessions',
                    stdout=stream,
                )
        except Exception as exc:  # pragma: no cover - depends on the DB driver
            destination.unlink(missing_ok=True)
            raise CommandError(f'Database dump failed: {exc}') from exc

    # -- off-box copy -------------------------------------------------------

    def _upload(self, path):
        """Copy the dump to object storage; local backup still counts if it fails."""
        backend = storages['default']
        if isinstance(backend, FileSystemStorage):
            self.stdout.write(self.style.WARNING(
                'BACKUP_UPLOAD_TO_S3 is on but the default storage is local; '
                'skipping upload.'
            ))
            return None

        prefix = getattr(settings, 'BACKUP_S3_PREFIX', 'backups').strip('/') or 'backups'
        key = f'{prefix}/{path.name}'
        try:
            with path.open('rb') as stream:
                saved_name = backend.save(key, File(stream))
        except Exception as exc:  # pragma: no cover - depends on the storage
            self.stdout.write(self.style.WARNING(
                f'Backup created locally but upload failed: {exc}'
            ))
            return None

        self.stdout.write(self.style.SUCCESS(f'Backup uploaded: {saved_name}'))
        return saved_name

    # -- retention ----------------------------------------------------------

    def _prune(self, backup_dir, keep_days):
        keep = settings.BACKUP_RETENTION_DAYS if keep_days is None else keep_days
        if keep <= 0:
            return

        cutoff = time.time() - (keep * 24 * 60 * 60)
        for candidate in backup_dir.glob('db_backup_*'):
            if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                candidate.unlink()
                self.stdout.write(f'Pruned old backup: {candidate}')
