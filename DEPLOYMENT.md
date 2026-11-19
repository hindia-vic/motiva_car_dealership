# Deployment guide (Vercel web + Render Celery)

The site is deployed as a split service:

| Service | Runs where | Purpose |
|---|---|---|
| Django web | **Vercel** | WSGI function, public site, staff panel, `/health`, static CDN |
| Postgres | **Supabase** | Shared database for web, worker and beat |
| Redis | **Render Key Value** | Celery broker/result backend plus shared Django cache |
| Celery worker | **Render** | Reminders, payment polling, backups |
| Celery beat | **Render** | Exactly one scheduler instance |
| Media/backups | **S3 or Cloudflare R2** | Files that must survive redeploys |

`render.yaml` no longer defines a web service or a Render database. Keep any old
Render web/database resources disabled until the Vercel cutover is verified.

Vercel uses the checked-in [`vercel.json`](vercel.json) (`config/wsgi.py` as the
entrypoint, 60-second function timeout) and [`.vercelignore`](.vercelignore).
Django is detected from `manage.py`; Vercel installs `requirements.txt`,
discovers `WSGI_APPLICATION` from `config/settings.py`, and runs `collectstatic`
automatically because `STATIC_ROOT` is set. Do **not** add a custom build
command that calls `collectstatic` again.

## 1. One-time setup

You need:

- a GitHub repository containing this project;
- a Supabase project (resumed, not paused);
- a Vercel project connected to that repository (Pro is recommended for static
  egress IPs);
- a Render account for the Redis instance and the two Celery services;
- an S3-compatible bucket (AWS S3 or Cloudflare R2);
- SMTP credentials for verification links and staff 2FA.

Generate a fresh secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Use the same `SECRET_KEY` in Vercel and Render so signed links and tokens work
in both processes. `ADMIN_URL` must be an unguessable path such as
`manage-<random-token>/`; `/admin/` returns a 404.

## 2. Supabase database

Use Supabase's **shared pooler, session mode** connection string. Do not use the
direct `db.<project-ref>.supabase.co:5432` host: it is IPv6-only and will not
connect from Vercel or Render's IPv4 networks.

```dotenv
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

- The username includes the project reference: `postgres.<project-ref>`.
- Port `5432` selects session mode. Port `6543` is transaction mode and is not
  suitable for Django's persistent connections.
- URL-encode special characters in the password (`@` becomes `%40`, `#` becomes
  `%23`).

Set this value in **both** Vercel and the Render `dealership-shared` environment
group. Apply migrations once from a trusted machine with that variable set:

```bash
python manage.py migrate --noinput
```

No sample data is needed. If you run the test suite locally, explicitly point
`DATABASE_URL` at SQLite so Django does not try to create `test_postgres` in
Supabase. Setting the variable to an empty string is not enough: PowerShell
removes empty variables, so settings would load the Supabase URL from `.env`
again.

```powershell
$env:DATABASE_URL='sqlite:///:memory:'
python manage.py test
```

## 3. Render: Redis, worker and beat

Deploy [`render.yaml`](render.yaml) as a Render Blueprint. It creates:

- `dealership-redis` (Valkey/Redis, `noeviction`, internal-only by default);
- `dealership-worker`: `celery -A config worker --loglevel=info --concurrency=2`;
- `dealership-beat`: `celery -A config beat --loglevel=info`.

Fill in every `sync: false` value when prompted, including the Supabase
`DATABASE_URL`. The workers receive Render's **internal** Redis URL through
`fromService`.

Render's internal Redis URL cannot be reached from Vercel. To let the web
process enqueue Celery tasks and share the cache:

1. Enable **Static IPs** for the Vercel project (Vercel Pro) and note the egress
   IPs for the deployment region.
2. In Render, open `dealership-redis` → **Access Control** and add those IPs.
3. Copy the Redis dashboard's **external** `rediss://...` URL into Vercel's
   `REDIS_URL`.

If you stay on a Vercel plan without static egress IPs, use a separately hosted
TLS Redis (for example Upstash) and set the same external URL as `REDIS_URL`
for both Vercel and the Render workers. Avoid opening Render Redis to
`0.0.0.0/0` unless you accept the exposure.

Run exactly one beat instance. Two beats double-schedule every periodic job.

## 4. Vercel project

1. Import the repository in Vercel. Leave **Root Directory** empty because
   `manage.py` is at the repository root.
2. Framework detection should show **Django**. Leave the build command at its
   default; Vercel handles dependency installation and `collectstatic`.
3. Confirm the Python version is 3.14 (`pyproject.toml` requires `>=3.14`).
4. Add the environment variables below. Set production values on **Production**
   and, ideally, a separate Supabase database on **Preview**. Preview builds
   that share the production `DATABASE_URL` can write to production data.

### Required variables

```dotenv
DEBUG=false
SECRET_KEY=<same-random-value-as-Render>
ALLOWED_HOSTS=www.example.com,example.com,.vercel.app
CSRF_TRUSTED_ORIGINS=https://www.example.com,https://example.com,https://*.vercel.app
SITE_BASE_URL=https://www.example.com
ADMIN_URL=manage-<random-token>/

# Supabase pooler (session mode)
DATABASE_URL=postgresql://postgres.<ref>:<encoded-password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require

# Render Redis external URL
REDIS_URL=rediss://...

# Uploads and backups
USE_S3=true
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=...
AWS_S3_REGION_NAME=auto
AWS_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
AWS_S3_CUSTOM_DOMAIN=media.example.com
AWS_S3_ADDRESSING_STYLE=virtual
AWS_QUERYSTRING_AUTH=false

# SMTP (verification and staff 2FA depend on it)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=Car Dealership <noreply@example.com>
DEALERSHIP_NOTIFY_EMAIL=sales@example.com

STAFF_2FA_ENABLED=true
DJANGO_ADMINS=Ops <ops@example.com>
# or SENTRY_DSN=https://...

MPESA_ENVIRONMENT=production
MPESA_CALLBACK_URL=https://www.example.com/payments/mpesa/callback/
MPESA_CONSUMER_KEY=...
MPESA_CONSUMER_SECRET=...
MPESA_SHORTCODE=...
MPESA_PASSKEY=...
```

Vercel-injected hostnames are added automatically to `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS`. Custom domains still need to be listed explicitly.

Optional features: `GOOGLE_ANALYTICS_ID`,
`GOOGLE_ANALYTICS_REQUIRE_CONSENT=true`, `GOOGLE_SITE_VERIFICATION`,
`BING_SITE_VERIFICATION`, `GOOGLE_OAUTH_CLIENT_ID`,
`GOOGLE_OAUTH_CLIENT_SECRET`, captcha keys, `CHATBOT_PROVIDER` /
`CHATBOT_API_KEY`, SMS keys and `BACKUP_RETENTION_DAYS`. See `.env.example`.

With `DEBUG=false`, secure cookies, HTTPS redirect, HSTS and CSP default to
their safe values. Vercel's proxy headers are trusted automatically; setting
`USE_X_FORWARDED_PROTO=true` and `TRUST_X_FORWARDED_FOR=true` explicitly is also
fine. Never put `.env` in the repository — `.vercelignore` excludes local
environment files and generated artifacts from the function bundle.

Migrations are deliberately **not** part of the Vercel build. Run them as a
separate release step (see section 2) before routing traffic to a new schema.

## 5. Deploy order

1. Supabase: confirm the pooler URL works and migrations are applied.
2. Render: deploy the blueprint; confirm worker and beat are healthy.
3. Vercel: add environment variables, deploy to Preview, and smoke-test with a
   non-production database.
4. Add the custom domain in Vercel and point DNS at the Vercel assignment.
5. Update `SITE_BASE_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
   `MPESA_CALLBACK_URL` and Google OAuth redirect URIs to the final domain.
6. Deploy to Production. Disable/delete the old Render web service and Render
   Postgres after the new web service is verified.
7. Create the first superuser from a trusted shell with the production
   environment loaded:

   ```bash
   python manage.py createsuperuser
   ```

Give every staff account a real email address. Staff without an email skip the
second factor, so 2FA is only effective when addresses are present.

## 6. Static files, media and backups

- Vercel serves collected static files from its CDN. `Whitenoise` is used for
  local `vercel dev`; manifest storage keeps URLs cache-busted.
- Vercel's filesystem is ephemeral. Keep `USE_S3=true` for car photos, avatars,
  documents and backups. Confirm a test upload survives a redeploy.
- Supabase PITR/backups are the primary database backup. The Render worker's
  nightly `backup-database` job also calls `python manage.py backup_db` and
  uploads the dump to the bucket.
- The Celery beat schedule runs: M-Pesa polling every 10 minutes, lead reminders
  at 08:00, deposit reminders at 08:15, booking reminders at 08:30, and backups
  at 02:00.

## 7. Pre-flight checks

Run locally with production-like variables (use a non-production database):

```bash
python manage.py check
python manage.py check --deploy
python manage.py security_check
python manage.py makemigrations --check --dry-run
pip-audit -r requirements.txt
python manage.py test
```

`security_check` verifies DEBUG, the secret key, hosts, HTTPS/HSTS, secure
cookies, CSP, staff 2FA, email, database engine, backup directory, admin path,
`SITE_BASE_URL`, the M-Pesa callback, shared Redis, error reporting, object
storage and Django's deployment checks.

## 8. Post-deploy verification

- [ ] `GET /health` returns `200 {"status": "ok"}` on the Vercel domain and
      custom domain.
- [ ] `/robots.txt`, `/sitemap.xml` and the home page load over HTTPS.
- [ ] Static assets load from the CDN with hashed URLs.
- [ ] A test upload lands in S3/R2 and survives a redeploy.
- [ ] Public forms work through the HTTPS proxy; CSRF is not rejected.
- [ ] Cookie banner works: Accept loads GA4, Decline keeps it off; one
      `cookie_consent` event fires after opt-in.
- [ ] Staff login sends a 2FA code; superuser-only admin works at `ADMIN_URL`;
      `/admin/` returns 404.
- [ ] Render worker and beat logs are healthy; periodic jobs appear in the
      schedule.
- [ ] Submitting a booking/test-drive creates the next-day reminder record.
- [ ] M-Pesa callback reaches the production domain and is accepted.
- [ ] Supabase backups/PITR are enabled and a restore has been rehearsed.
- [ ] Monitoring points at `/health`; Vercel and Render alerts are configured.
- [ ] No preview deployment uses the production `DATABASE_URL`.

## 9. Operations notes

- Vercel runs one Django function, not gunicorn. There is no local shell and no
  long-running background process on Vercel; keep those on Render.
- Never run database migrations from multiple preview builds against the same
  database at once.
- Static assets are rebuilt for each deployment; media is not.
- Rotate any credential that was ever used locally, and remove `.env` from any
  server or image that still has it.
