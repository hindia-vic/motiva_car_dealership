"""Audit the settings that matter before a production deployment.

Run it with the production environment loaded:

    python manage.py security_check

It exits non-zero when a check fails, so it can gate a deploy pipeline. Django's
own ``check --deploy`` findings are folded in, which keeps this command from
drifting away from the framework's advice.
"""

from pathlib import Path

from django.conf import settings
from django.core.checks import ERROR, run_checks
from django.core.management.base import BaseCommand

OK = 'OK'
WARN = 'WARN'
FAIL = 'FAIL'


class Command(BaseCommand):
    help = 'Check production security settings before deploying.'

    def handle(self, *args, **options):
        results = []
        results.extend(self._custom_checks())
        results.extend(self._django_deploy_checks())

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Pre-deployment security check'))
        self.stdout.write('')

        for level, label, detail in results:
            if level == OK:
                style = self.style.SUCCESS
                marker = '[ OK ]'
            elif level == WARN:
                style = self.style.WARNING
                marker = '[WARN]'
            else:
                style = self.style.ERROR
                marker = '[FAIL]'
            self.stdout.write(style(f'{marker} {label}'))
            if detail:
                self.stdout.write(f'       {detail}')

        failures = sum(1 for level, _, _ in results if level == FAIL)
        warnings = sum(1 for level, _, _ in results if level == WARN)
        self.stdout.write('')
        self.stdout.write(
            f'{len(results)} checks: '
            f'{failures} failed, {warnings} warning(s).'
        )

        if failures:
            raise SystemExit(1)

    # -- project-specific checks -------------------------------------------

    def _custom_checks(self):
        checks = []

        def add(condition, label, detail='', level=FAIL):
            checks.append((OK if condition else level, label, '' if condition else detail))

        add(not settings.DEBUG, 'DEBUG is off',
            'Set DEBUG=False in production.')
        add(
            bool(settings.SECRET_KEY) and not settings.SECRET_KEY.startswith('django-insecure-'),
            'SECRET_KEY is not the development default',
            'Generate a long random SECRET_KEY and keep it out of version control.',
        )
        add(bool(settings.ALLOWED_HOSTS), 'ALLOWED_HOSTS names the real domain(s)',
            'Set ALLOWED_HOSTS=www.example.com,example.com.')
        add(settings.SECURE_SSL_REDIRECT, 'HTTPS redirect is on',
            'Set SECURE_SSL_REDIRECT=True.')
        add(settings.SESSION_COOKIE_SECURE, 'Session cookie is HTTPS-only',
            'Set SESSION_COOKIE_SECURE=True.')
        add(settings.CSRF_COOKIE_SECURE, 'CSRF cookie is HTTPS-only',
            'Set CSRF_COOKIE_SECURE=True.')
        add(settings.SECURE_HSTS_SECONDS > 0, 'HSTS is enabled',
            'Set SECURE_HSTS_SECONDS=31536000 once HTTPS is confirmed working.',
            level=WARN)
        add(bool(settings.CSRF_TRUSTED_ORIGINS), 'CSRF_TRUSTED_ORIGINS is set',
            'Set CSRF_TRUSTED_ORIGINS=https://www.example.com.',
            level=WARN)
        add(settings.CONTENT_SECURITY_POLICY_ENABLED, 'Content Security Policy is enabled',
            'Set CONTENT_SECURITY_POLICY_ENABLED=True.',
            level=WARN)
        add(settings.STAFF_2FA_ENABLED, 'Staff two-factor authentication is on',
            'Set STAFF_2FA_ENABLED=True so a password alone cannot open the staff panel.')
        add(
            'console' not in settings.EMAIL_BACKEND.lower(),
            'Email uses a real backend',
            'Set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend '
            'and configure the SMTP settings; staff 2FA codes need delivery.',
        )
        add(
            'sqlite3' not in settings.DATABASES['default'].get('ENGINE', ''),
            'Database is not SQLite',
            'Use PostgreSQL (DATABASE_URL) for concurrent production traffic.',
            level=WARN,
        )

        backup_dir = Path(settings.BACKUP_DIR)
        parent = backup_dir if backup_dir.exists() else backup_dir.parent
        add(
            parent.exists() and parent.is_dir(),
            'Backup directory is writable',
            f'Create {backup_dir} and make sure the app user can write to it.',
            level=WARN,
        )

        admin_url = getattr(settings, 'ADMIN_URL', '/admin/')
        add(
            admin_url.rstrip('/') != '/admin',
            'Admin is not on the default /admin/ path',
            'Set ADMIN_URL to an unguessable path such as /manage-<random>/.',
            level=WARN,
        )

        site_base_url = getattr(settings, 'SITE_BASE_URL', '')
        add(
            site_base_url.startswith('https://'),
            'SITE_BASE_URL is an https URL',
            'Set SITE_BASE_URL=https://www.example.com so emailed links are absolute.',
            level=WARN,
        )

        if getattr(settings, 'MPESA_ENVIRONMENT', 'sandbox').lower() == 'production':
            add(
                getattr(settings, 'MPESA_CALLBACK_URL', '').startswith('https://'),
                'M-Pesa callback uses https',
                'Register a public https callback URL with Daraja and set MPESA_CALLBACK_URL.',
            )

        redis_url = getattr(settings, 'REDIS_URL', '')
        add(
            bool(redis_url),
            'Cache and Celery share a Redis instance',
            'Set REDIS_URL so rate limits and axes lockouts are shared across workers.',
            level=WARN,
        )

        add(
            bool(getattr(settings, 'ADMINS', [])) or bool(getattr(settings, 'SENTRY_DSN', '')),
            'Production errors are reported somewhere',
            'Set DJANGO_ADMINS or SENTRY_DSN so 500s are not silent.',
            level=WARN,
        )

        use_s3 = getattr(settings, 'USE_S3', False)
        if use_s3:
            add(
                bool(getattr(settings, 'AWS_STORAGE_BUCKET_NAME', '')),
                'Object storage bucket is configured',
                'Set AWS_STORAGE_BUCKET_NAME (and credentials) for uploads.',
            )
        else:
            add(
                settings.DEBUG,
                'Uploads use durable storage',
                'Set USE_S3=true and configure a bucket; a PaaS filesystem is '
                'wiped on every deploy, losing car photos and documents.',
                level=WARN,
            )

        if not settings.DEBUG and str(settings.BACKUP_DIR).startswith(str(settings.BASE_DIR)):
            add(
                False,
                'Backups are written outside the app directory',
                'BACKUP_DIR is inside the app tree, which is ephemeral on a '
                'PaaS. Use managed Postgres backups/PITR and copy dumps off-box.',
                level=WARN,
            )

        add(
            not settings.SECURE_HSTS_PRELOAD,
            'HSTS preload is off',
            'Only enable SECURE_HSTS_PRELOAD once all subdomains are HTTPS; '
            'the preload list is hard to undo.',
            level=WARN,
        )

        return checks

    # -- Django's own deployment checks ------------------------------------

    def _django_deploy_checks(self):
        messages = run_checks(include_deployment_checks=True)
        errors = [m for m in messages if m.level >= ERROR]
        warnings = [m for m in messages if m.level < ERROR]

        results = []
        if errors:
            detail = '; '.join(f'{m.id}: {m.msg}' for m in errors)
            results.append((FAIL, "Django's deployment checks report errors", detail))
        elif warnings:
            detail = '; '.join(f'{m.id}: {m.msg}' for m in warnings[:5])
            if len(warnings) > 5:
                detail += f' (+{len(warnings) - 5} more)'
            results.append((WARN, "Django's deployment checks report warnings", detail))
        else:
            results.append((OK, "Django's deployment checks are clean", ''))
        return results
