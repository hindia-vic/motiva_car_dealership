# Car Dealership Management System

A full-stack Django car dealership website with a public shop front (browse cars,
inquiries, orders, test-drive bookings, reviews) and a staff panel (dashboard,
leads pipeline, customers, sales, reports).

## Tech stack

- Python 3.14, Django 6.1, SQLite
- Bootstrap 5 + Bootstrap Icons, Chart.js (reports)
- Pillow for image uploads; ReportLab for PDF reports
- Plain-text email notifications via `django.core.mail`

## Setup

```bash
python -m venv virtual
virtual\Scripts\pip install -r requirements.txt   # or: uv sync
virtual\Scripts\python manage.py migrate
virtual\Scripts\python manage.py populate_sample_data
virtual\Scripts\python manage.py runserver
```

Visit http://127.0.0.1:8000/ (public site) and
http://127.0.0.1:8000/admin/ (Django admin).

## Email / verification

Accounts are registered **inactive** and only become active once the user clicks
the verification link emailed to them (single-use, auto-expiring).

By default Django's **console** email backend is used, so emails are printed to
the terminal where `runserver` runs and are **not actually delivered**. To send
real email:

1. `Copy-Item .env.example .env`
2. Fill in your SMTP settings in `.env` (see `.env.example`):

   ```
   EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_HOST_USER=you@example.com
   EMAIL_HOST_PASSWORD=your-app-password
   EMAIL_USE_TLS=true
   DEFAULT_FROM_EMAIL=Car Dealership <you@example.com>
   DEALERSHIP_NOTIFY_EMAIL=sales@example.com
   ```

3. Restart `runserver`.

Notes:
- `.env` is git-ignored; the same keys can be set as real environment variables
  (env vars take precedence).
- Test mailboxes like Mailtrap work with the same settings and keep real inboxes
  clean during development.

## Features

Public:
- Homepage (featured cars, customer testimonials, latest news), car browse with filters/search/pagination/sorting
- Car detail with photo carousel, favorites, payment calculator, inquiry/order/test-drive booking
- Compare up to 4 vehicles side-by-side (pick them with checkboxes in the browse list)
- Reviews page: logged-in customers submit reviews; staff approve them in the admin
- Contact form, newsletter signup, about page, financing page, FAQ page, "My Activity"
- News/blog with management via the admin
- SEO: per-page meta/Open Graph tags, robots.txt, sitemap.xml
- Saved searches: "email me when a matching car arrives" form on the browse page;
  current matches are emailed immediately and the `check_saved_searches` command
  emails subscribers about newly listed matching cars

Accounts:
- Register (requires email verification), login, logout, password reset
- Favorites, staff account management (temp password, forced password change, activate/deactivate)

Staff panel:
- Dashboard with stats, inquiries/orders/appointments/customers/sales lists with status updates
- Add/edit customers and record sales directly in the panel (invoice number and
  total amount are generated/calculated automatically)
- Review moderation: approve or hide submitted reviews from the staff panel
- CSV exports (with current filters applied) for sales, customers, inquiries, and orders
- PDF sales report export (same filters, downloadable report)
- Edit the "Visit or Call" section on the contact page (address, phone, email, hours)
  from the staff panel or the admin
- Reports (revenue, top models, conversion), customer purchase history

## Testing

```bash
virtual\Scripts\python manage.py test accounts cars
```