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

When dependencies change (`pyproject.toml` gains a package), re-run the install
step in your environment: `virtual\Scripts\pip install -r requirements.txt`
or `uv sync --active` so the change lands in `virtual` rather than `.venv`.

Visit http://127.0.0.1:8000/ (public site) and the Django admin. The admin
path is configurable with `ADMIN_URL` (default `/admin/`); set it to something
unguessable in production, e.g. `ADMIN_URL=manage-<random>/`.

## Currency

Every price on the site is in **Kenyan shillings**. The asking price, the
purchase price, the trade-in estimate, sale totals, down payments and the
revenue in the staff reports are all stored and shown in KSh - `KSh
3,120,000`, not `$3,120`.

The symbol comes from two settings, so changing it changes the whole site:

```bash
CURRENCY_SYMBOL=KSh     # shown in front of an amount
CURRENCY_CODE=KES       # used in export column headers
```

The formatting lives in `cars/money.py` (`format_money()`) and is used by
the `|money` template filter, the emails, the chatbot and the saved-search
summaries, so there is one place that decides what a price looks like.
Amounts are shown as whole shillings with thousands separators; the monthly
payment on a finance agreement is the one place that shows cents.

The seeded prices were originally in dollars. Migrations `cars/0018` and
`accounts/0006` widen the money columns so a shilling amount fits
(`max_digits` 10 -> 12); they deliberately **do not** rewrite the stored
values, because no migration can tell a dollar amount from a shilling
amount that was typed in by hand.

Converting a database that is entirely dollar-priced is an explicit act:

```bash
python manage.py convert_prices_to_shillings --dry-run   # preview
python manage.py convert_prices_to_shillings             # do it
```

The rate is a **constant of 130 shillings to the dollar** inside the
command, not a setting, so a conversion always happens at the rate that
was reviewed and tested. A fresh install needs neither: `populate_sample_data`
seeds shillings directly.

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

## Google sign-in

The login and registration pages can offer a **"Sign in with Google"** button
(OAuth 2.0 Authorization Code flow, no extra dependencies). To enable it:

1. In the [Google Cloud Console](https://console.cloud.google.com/apis/credentials),
   create an **OAuth 2.0 Client ID** of type *Web application*.
2. Add an **Authorized redirect URI** pointing at the callback:
   `http://127.0.0.1:8000/accounts/google/callback/`
   (use your real domain in production).
3. Put the credentials in `.env`:

   ```
   GOOGLE_OAUTH_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
   GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
   ```

4. Restart `runserver`.

While these are blank the button is hidden. Google accounts arrive with a
verified email, so they skip the usual verification email: an existing account
with the same address is linked and activated, and a new address creates an
active account with no password (the user signs in with Google).

## Anti-spam on public forms

Public forms (contact, newsletter, saved searches, inquiries, orders and
test-drive bookings) are protected without adding any friction for real users:

- a hidden **honeypot** field that only bots fill in;
- a **link-count heuristic** that rejects messages stuffed with URLs;
- **per-IP rate limiting** backed by Django's cache.

A captcha is **optional and off by default**. To turn one on, set the site and
secret keys for a single provider in `.env` (see `.env.example`); the widget
then appears on the public forms and submissions are verified server-side.

Rate limiting uses Django's cache. The default `LocMemCache` is per-process, so
when you run more than one worker (or process) deploy a shared cache
(Redis, Memcached or the database) in the `CACHES` setting. Rate limiting is
automatically disabled while the test suite runs - the anti-spam tests switch it
back on explicitly.

## Status update emails

When staff change an order or inquiry status, the customer is emailed
automatically - but only on transitions they care about:

- Orders: `confirmed`, `processing`, `ready_for_pickup`, `completed`, `cancelled`
- Inquiries: `contacted`, `interested`

Internal statuses (`pending`, `new`, `not_interested`, `closed`) never email the
customer, and re-selecting the current status sends nothing. Emails fail soft:
if the mail server is unreachable the status change still succeeds.

## Site chatbot

A floating chat widget answers common questions about financing, trade-ins,
test drives, hours, location, and what's in stock. It appears on every page
for visitors and staff alike (staff can try it while logged in).

It works **out of the box with no keys and no network access**: a small,
built-in keyword/intent engine reads live site data (contact details, dealership
name, and available inventory) and links visitors to the right pages. Set
`CHATBOT_ENABLED=false` in `.env` to hide the widget.

To upgrade answers to an **LLM**, set a provider and key in `.env` (see
`.env.example`):

```
CHATBOT_PROVIDER=openai        # or openai_compatible / gemini / anthropic
CHATBOT_API_KEY=your-key
CHATBOT_MODEL=gpt-4o-mini
```

If the provider is unreachable or no key is set, answers silently fall back to
the built-in engine, so the widget never breaks. Only the visitor's message and
public site facts are sent to the provider - no account or personal data.

Conversations are stored locally and are visible only to staff in the
**Staff -> Chat Transcripts** panel. When the bot can't help, it offers to pass
the question to a person; submitting that form creates a contact message
(emailed to the staff notify address) linked to the conversation.

## Images

Photos are processed when they are uploaded, not when they are served. Every
upload is:

- rotated upright if the camera recorded an orientation, and the EXIF data
  (which includes the GPS coordinates of where the photo was taken) is
  stripped from the saved file
- resized so the longest side is at most `CAR_IMAGE_MAX_WIDTH` pixels
- re-encoded as a JPEG at `CAR_IMAGE_QUALITY` (85 by default), or kept as a
  PNG when the picture has transparency
- given a random filename, so an uploaded `photo.jpg` never ends up on disk
  under that name

A thumbnail (`CAR_IMAGE_THUMBNAIL_WIDTH`, 600 pixels) is generated at the same
time and stored next to the original. The browse and compare pages use the
thumbnail; the detail page uses the full-size image.

The rules live in `cars/images.py`. A file that is not an image, or is not
one of the allowed formats, is rejected with a message rather than being
saved and broken later. Files that are already in the database are not
re-validated when you edit a record, so an old large photo does not stop you
from changing the price.

If processing fails for any reason the original file is kept and the error is
logged - a bad photo must never cost you a listing.

Existing photos can be reprocessed with:

```bash
python manage.py reprocess_images --dry-run   # preview
python manage.py reprocess_images             # do it
python manage.py reprocess_images --car 42    # just one vehicle
```

## Trade-in valuation

`/trade-in/` gives visitors an instant estimate of what their car is worth
as a trade-in. They enter the year, make, model, mileage and condition, and
get a number plus the arithmetic behind it.

The rules live in `cars/tradein.py` as plain code constants, not in a table
staff can edit from the admin. An appraisal is only as good as its rules, and
rules anyone can change without review are rules nobody trusts. Adjust them
there, review the change, and deploy it.

The estimate is:

```
value = indicative new price (body type)
      x brand factor
      x model factor
      x depreciation (age)
      x mileage factor
      x condition factor
```

Every step is shown on the page, so the dealer and the customer are arguing
about the same numbers.

The indicative new prices and the estimates are in **shillings**, and the
result is rounded to the nearest 1,000 so a customer is not quoted a
shilling they cannot argue about. Mileage is still read in miles.

The same rules are used in two more places:

- the order form has a **"Trading in a vehicle?"** widget that fills the
  trade-in value box with the midpoint of the estimate (the customer can
  change it), and stores what they claimed on the order. The estimate we
  keep is worked out again on the server, so it is our number and not
  something typed into a hidden field.
- the staff sale form can link a sale to the online order it came from, and
  then pre-fills the trade-in value from what the customer told us

A trade-in value is an estimate, not an offer. The final number is agreed
after the vehicle has been seen.

## List your car

`/list-your-car/` lets a signed-in customer ask us to advertise their own
vehicle. They send the details of the car, the price they want it advertised
at, **at least one photo of the car** and **a photo of the logbook's front
page**. We then do the work and publish the listing on their behalf.

The fee is **KSh 2,500**. When M-Pesa is configured the customer is sent an
STK push as soon as the request is made, and can retry from the request page
if it fails; otherwise they pay by bank transfer and quote the reference,
and staff record it. The amount is copied onto the request when the request
is made, so changing the fee later never rewrites what a customer was quoted.

The fee and the rules for what it buys live in `cars/listing.py` as plain
code constants, for the same reason the trade-in rules do: a rule anyone can
change from the admin is a rule nobody trusts. The amount itself can be
overridden with the `LISTING_FEE` environment variable.

### Nothing goes live unchecked

A listing request has to clear three checks before it can be published, and
all three are recorded against the request:

| Check | Who does it | What it means |
| --- | --- | --- |
| Vehicle verified | staff | the car has been inspected and is as described |
| Logbook verified | staff | the logbook has been checked against the vehicle |
| Fee settled | staff | the listing fee is recorded as paid (or waived) |

`ListingRequest.can_be_published()` is the gate, and the staff publish screen
enforces it. Staff cannot tick the boxes until they have actually seen the
car and the logbook, and the owner's photos are copied onto the listing so
the listing carries the pictures the customer sent.

### How a request moves

```
submitted -> under_review -> awaiting_documents -> awaiting_payment -> listed
                                                          \-> rejected
```

- The customer sees the request and its reference number under
  **My Listings** (also linked from My Activity), and is emailed when the
  request changes in a way that affects them.
- Staff work through **Staff -> Listing Requests**: a list with a search box
  and a status filter, and a review page showing the customer's photos, the
  logbook scan, the verification and payment fields, and the listing details
  that will go live.
- Publishing creates the ordinary `Car` record, so the listing behaves like
  every other vehicle on the site (photos, inquiries, orders, alerts).

The logbook scan stays with the request and is never shown publicly.

## Financing

`/financing/` explains how a car loan works and `/financing/apply/` takes an
application. It is open to guests as well as signed-in customers, because
somebody working out whether they can afford a car should not have to make
an account first. A signed-in applicant's applications are linked to their
account and listed under **My Financing**; a guest gets a reference number
on the thank-you page and by email.

The numbers live in `cars/financing.py` as plain code constants:

| Rule | Value |
| --- | --- |
| Interest rate | **14.5 % per year**, flat, on the amount financed |
| Minimum deposit | **10 %** of the car price |
| Payment ceiling | **one third** of net monthly income |
| Terms | 12, 24, 36, 48, 50, 60 or 72 months |

The rate can be overridden for a deployment with `FINANCING_INTEREST_RATE`.
Everything else — the deposit floor, the affordability ceiling and the term
list — is fixed in code, so two customers asking on the same day are quoted
on the same terms.

The application form shows a live estimate as the customer types: deposit,
amount financed, monthly payment and total repayable. When the application
is submitted, the rate, the amount requested and the estimated monthly
payment are **copied onto the application**. A later rate change therefore
never rewrites what a customer was quoted.

Affordability is a hard check, not a warning: the estimated monthly payment
must be no more than a third of the net monthly income the applicant
declares. An application that fails it is not saved, and the form says why.

Staff work through **Staff -> Financing Applications**. The decision is
manual: staff look at the application, approve it (optionally for a
different amount), decline it with a reason, or leave the status alone while
they make enquiries. The customer is emailed only when the application is
approved or declined.

## Car hire and tours & travel

Two services share one fleet, because they share the same cars:

- **Self-drive hire** — the customer drives the car themselves, at the
  car's `hire_daily_rate`.
- **Tours and travel** — the car goes out with one of our drivers, at the
  car's `tour_daily_rate`.

They are separate apps on purpose. A hire car is not sale inventory: the
browse page, the compare table, favourites, saved-search alerts and the
sitemap all assume a car on the lot is for sale, so hire cars live in
`hiring/models.py` (`HireCar`, `HireCarImage`, `HireBooking`) instead of
being flagged up on `Car`. Staff can therefore hire out a car that is not
for sale, and sell a car that is not in the hire fleet.

The hire pages are `/hire/` (the whole fleet), `/hire/tours/` (only the
cars that take a driver) and `/hire/car/<id>/` (one car, with the booking
form). **My Hires** lists a signed-in customer's own bookings. Staff work
from **Staff -> Hire Fleet** and **Staff -> Hire Bookings**.

### A booking is a request, not a reservation

Nothing is confirmed on the customer's word:

```
pending -> confirmed -> active -> completed
       \-> rejected
       \-> cancelled
```

1. The customer picks a car and dates, and gives their **driving licence
   number** and **national ID or passport number**. No documents are
   uploaded; staff check the numbers against the originals before the car
   goes out.
2. The quote is worked out from the days and the car's own rate, and
   stored on the booking. Staff can override it, because a real trip costs
   what the route, the fuel and the driver cost.
3. Staff record the payment. Confirm is refused while the payment is
   `pending`: the money — or at least a deposit, which is recorded as
   `partial` — has to be in first.
4. Confirming the booking is what takes the car out of the diary.

Two overlap checks use one rule (`hiring/rules.py`). A *request* only
clashes with a booking that is already `confirmed` or `active`, so several
customers may ask for the same car on the same weekend and staff pick one.
Confirming then checks the same set again, so a second booking cannot be
confirmed over the first. `rejected` and `cancelled` bookings never block
anything.

The number of days is `(return - pick-up) + 1`, so a car collected and
returned on the same day is one day, and a booking ending on the 5th
blocks a booking starting on the 5th. It is computed, never stored, so it
can never drift out of step with the dates.

A car that has bookings on it cannot be deleted — `on_delete=PROTECT` —
because the booking history and the payments have to stay on file. Staff
retire it instead.

### Extras and the security deposit

A car can be hired with extras: a child seat, an extra driver, airport
delivery, a cooler box. Staff keep the catalogue in **Admin -> Hire
Add-ons**. Each one is charged either **per day** of the hire or **once per
booking**, which is all the pricing it needs.

When a customer ticks an extra, the booking stores a copy of its **name,
price and unit**. Editing or retiring the catalogue later never changes a
booking that has already been quoted; only new bookings see the new price.
Staff adjust quantities on the booking review page, and can add or remove
lines there when the customer asks by phone.

A hire also carries a **security deposit**, which is not part of the hire
price. It is suggested at **20 % of the hire, rounded up to the next KSh
500** (`hiring/rules.py`), and staff can change it. The deposit has four
dates and amounts recorded against it:

- `security_deposit` — what was asked for;
- `deposit_received_at` — when it was handed over;
- `deposit_refunded_at` — when it was given back;
- `deposit_retained` — the part kept for damage or fuel.

So the customer's bill is `hire + extras + deposit`, and what they get back
is `deposit - kept`. The deposit never counts as hire income.

To fill an empty fleet with a realistic starting set of cars, rates and
extras:

```
python manage.py populate_hire_fleet
```

## M-Pesa payments

The site takes money through Safaricom's Daraja API (STK push). Three things
are payable online:

| What | When | Amount |
| --- | --- | --- |
| **Order deposit** | after the customer places an order | the deposit rule below |
| **Listing fee** | when a car is submitted for listing | `LISTING_FEE` (default KSh 2,500) |
| **Hire booking** | from the booking page | the total due |

Only the **deposit** is payable online on an order. The balance is settled
with staff when the paperwork is done; the site does not take the full
purchase price.

### The deposit rule

The rule lives in `cars/deposits.py` as code constants, not a table in the
admin:

1. **10 %** of the amount payable after the trade-in;
2. rounded **up** to the next **KSh 1,000**;
3. never less than **KSh 50,000**;
4. never more than the amount payable.

The amount is copied onto the order when it is placed, so raising the
minimum later never rewrites what a customer was already quoted. The three
numbers can be overridden with `ORDER_DEPOSIT_RATIO`,
`ORDER_DEPOSIT_MINIMUM` and `ORDER_DEPOSIT_ROUNDING`.

Paying the deposit does **not** confirm the order. The order stays `pending`
for staff review; the deposit only reserves the car. A successful payment
moves the order's `payment_status` to `partial` and emails the customer a
receipt.

### Configuration

Set these in `.env` (see `.env.example`):

```bash
MPESA_CONSUMER_KEY=...
MPESA_CONSUMER_SECRET=...
MPESA_SHORTCODE=174379
MPESA_PASSKEY=...
MPESA_CALLBACK_URL=https://your-site.example.com/payments/mpesa/callback/
MPESA_ENVIRONMENT=sandbox
```

When `MPESA_CONSUMER_KEY` is empty the payment forms are hidden and the
site falls back to "our team will contact you", so nothing breaks before the
credentials are in place.

### Callbacks and reconciliation

`/payments/mpesa/callback/` receives Safaricom's result. It is deliberately
thin: the payload is parsed and handed to `payments/services.py`, which owns
the rules. The callback:

- is idempotent — a replayed success does nothing twice;
- never lets a late failure overwrite a success;
- refuses to settle a transaction when the callback amount is less than the
  amount requested;
- always answers `200`, even for a payload it cannot match, so Safaricom
  stops retrying.

If a callback is lost, the status query fallback asks Safaricom what
happened:

```bash
python manage.py check_mpesa_payments          # pending older than 10 minutes
python manage.py check_mpesa_payments --minutes 30
```

The same job is in the Celery beat schedule as
`payments.tasks.check_pending_payments_task` (every ten minutes).

Staff work through **Staff -> Payments**: every transaction with filters,
totals, a CSV export, and a **Query** button that asks Safaricom for the
latest state. Staff can query but **cannot mark a payment successful by
hand** — only Safaricom's result does that. The same query is available as
an admin action.

### Guest access

A guest order, hire or listing has no account to sign in to. The link in
the confirmation email carries a signed, expiring token
(`django.core.signing`) that authorises the guest's own payment-status page
and order payment form. Without it the page is not reachable; staff can
always see every transaction.

## Lead follow-up

Every lead - an inquiry from a car page or the chatbot, or a message sent
through the contact page - carries the ownership fields that existed but
were never used (`assigned_to`, `follow_up_date`, `notes`). The lead engine
in `cars/leads.py` turns those fields into a real work queue:

- **Staff -> Inquiries** is the inquiry lead queue at `/inquiries/`. Staff can
  filter by status, owner ("me" or unassigned) and follow-up state
  (overdue / due today / next 7 days).
- **Staff -> Contact Messages** (`/contact-messages/`) is a parallel
  queue for public contact-form and chatbot-handoff messages. These got a
  first-class status workflow too: `new`, `contacted`, `closed`.
- **Assigning a lead** (`/leads/<kind>/<pk>/assign/`, with a `kind` segment
  for inquiry vs message) sets the owner and the next follow-up date. Assigning
  to another staff member notifies them through the in-app notification
  center (a re-assign to yourself sends nothing, and clearing the date is
  allowed). Notes are appended to the lead's notes with a timestamped entry.
- **Logging a contact** (`cars:lead_contact`) stamps `last_contacted_at`
  and moves a `new` lead forward to `contacted`; the status-update flow can
  move it to `interested` / `not_interested` / `closed` as before.

### Follow-up reminders

`cars/tasks.py` runs two Celery beat jobs:

| Job | Task | Schedule | Purpose |
| --- | --- | --- | --- |
| Lead reminders | `cars.tasks.send_lead_reminders_task` | daily | Staff are nudged about leads nobody owns (24h grace), and owners of due leads get a notification (at most one per lead per day). |
| Deposit reminders | `cars.tasks.send_order_deposit_reminders_task` | daily | Customers whose order has been waiting on the deposit for over 24h are emailed once. |

The lead job reads from the same helpers the list pages use
(`leads.overdue`, `leads.due_today`, `leads.due_within`, `leads.unassigned`),
so the dashboard, the queue pages and the reminder task can never disagree
about what "due" means.

### Booking reminders

`cars.tasks.send_booking_reminders_task` runs daily at 08:30 and emails
customers about service visits, approved test drives and confirmed hires
starting the next day. `BookingReminder` records one reminder per booking per
date, so a beat restart cannot send the same email twice; moving a booking to
a new date creates a fresh reminder for that date. Mail failures are logged and
never stop the other reminders.

## Abandoned order recovery

An order is a request, not a sale: it stays `pending` until staff review it,
and the deposit is paid online afterwards (see "M-Pesa payments" above). Two
rules in `cars/orders.py` close that gap without turning into a cancellation
machine:

- **Deposit reminders**: `send_deposit_reminders()` emails a customer whose
  order is still `pending` and un-paid once the order is older than
  `DEPOSIT_REMINDER_AFTER_HOURS` (24 hours). It marks `deposit_reminder_sent_at`
  so the same customer is never emailed twice. Paid or cancelled orders are
  skipped entirely, and fresh orders are not reminded yet.
- **Stale orders**: `stale_orders()` flags orders that have been waiting on
  a deposit for more than `STALE_AFTER_DAYS` (7 days).

Releasing a stale order is an **explicit staff action** (`cars:order_release`
on the orders list page, or the service call `cars.orders.release_order`).
Only a `pending` order with no deposit received can be released: the release
cancels the order, frees the vehicle (only if no other live order is holding
it), and notifies the customer (in-app + email) and staff. Staff are never
emailed a self-notification, and a confirmed order cannot be released through
the UI — once staff have moved the order on, cancelling is a deliberate
conversation, not a cleanup button.

## Traffic analytics

The staff panel records one page view per public page request and turns it
into a **Staff -> Traffic** report: unique visitors, page views, pages per
visit, bounce rate, and how each of those compares with the previous period.

The report also shows:

- traffic over time (page views and unique visitors per day)
- where visitors come from (Google, Facebook, direct, internal, referral...)
- devices, browsers, top pages and top landing pages
- the most viewed vehicles, so you know which cars are pulling people in
- top external referrers, and any tagged campaign links (UTM)

Who is counted:

- **everyone** - anonymous visitors get a first-party `vid` cookie so a
  returning visitor is recognised as the same person; logged-in customers
  are linked to their account
- **staff browsing is not counted**, so the numbers reflect prospective
  customers only
- bots, redirects, background requests and static files are not counted
- raw visitor IP addresses are stored

Because raw IP addresses are personal data, the table is kept deliberately
small. Rows older than `TRAFFIC_RETENTION_DAYS` (default 90) are deleted
automatically, at most once a day, so there is nothing to schedule.

The prune can also be run by hand, for a different window, or as a dry run:

```bash
python manage.py purge_traffic_data --dry-run   # preview
python manage.py purge_traffic_data             # delete now
python manage.py purge_traffic_data --days 30   # override the window
```

The automatic prune can be switched off with `TRAFFIC_AUTO_PRUNE=false`; the
command above still works either way.

### Keeping the numbers honest

A few controls keep the table (and the report) free of noise:

- **Repeat views are collapsed.** The same visitor hitting the same page
  again within `TRAFFIC_DEDUPE_WINDOW` seconds (default 60) is not recorded
  twice, so refreshing a page or double-clicking a link does not inflate the
  numbers. Unique visitors, landing pages and the bounce rate are unaffected.
  Set the window to `0` to count every single request.
- **404s are not recorded** by default (`TRAFFIC_TRACK_404S=false`). A
  request for a URL that does not exist is far more often a scanner than a
  visitor following a broken link. Switch it on to study broken links.
- **Scanner probes are never recorded**, whatever the status code. Paths
  such as `/.env`, `/.git`, `/wp-login`, `/phpmyadmin`, `/cgi-bin`,
  `/vendor/`, `/api/`, `/v1/` and `/xmlrpc.php` are ignored, as are requests
  that look like bots.
- **SQLite runs in WAL mode**, so the per-request insert does not block the
  pages being counted. The setting is best effort: on a filesystem that
  cannot support WAL the site simply keeps the default journal mode.

The dedupe window uses Django's cache. With the default `LocMemCache` it is
per-process, so on a multi-worker setup a visitor hitting the same page on
two workers can be counted twice. It only ever under-counts repeats, never
drops a genuine first view. Point `CACHES` at a shared backend (Redis,
Memcached) if you run more than one worker.

Recording can be switched off entirely with `TRAFFIC_TRACKING_ENABLED=false`
in `.env`. It is switched off automatically while the test suite runs.

### Conversion funnel

Page views tell you how many people came; the funnel tells you what they did
once they were here. Every inquiry, order and test drive records the visitor
token and the source the visitor arrived from, so the funnel is worked out
from the conversions themselves.

The **Staff -> Traffic** report gains a *Conversion funnel* section:

- **visitors -> inquiries -> orders -> sales**, with the rate at each step
- **conversions by source**: visitors, inquiries, orders, sales, lead rate and
  revenue per source. The lead rate is the share of visitors who became a
  lead (an inquiry or an order), so a visitor who inquires and then orders
  counts once, not twice
- **vehicles that convert**: page views, viewers, leads and lead rate per
  vehicle

A visitor is credited to the source they *arrived* from, not the last page
they looked at, so someone who lands from Google and browses for an hour is
still a Google lead when they order.

The source and the token are copied onto the conversion rather than looked up
later, because page views are pruned after the retention window and a lead
has to keep its history.

Revenue is only counted for sales that were linked back to the online order
they came from. Sales recorded in the office without an order have no source
and are left out of the revenue column on purpose - they were not won online.

The funnel can be downloaded as a CSV from the button on the Traffic page
(`/export/traffic/`).

## Google Analytics 4 (optional)

The first-party traffic report above answers "what happened on my site". GA4
is the second opinion: it puts the same journey next to your ad and Search
Console data, and it is what most agencies and marketing partners expect.

It is off unless you ask for it. Set a Measurement ID in `.env`:

```dotenv
GOOGLE_ANALYTICS_ID=G-XXXXXXXXXX
```

Nothing is loaded when the ID is blank - no gtag.js request, no cookies, and
the Content-Security-Policy is left exactly as it was. `GOOGLE_ANALYTICS_ENABLED=false`
switches tracking off without deleting the ID (useful on staging).

Tracking is also **opt-in**. When an ID is configured, a cookie banner asks the
visitor to accept or decline analytics. The decision is stored in the
first-party `cookie_consent` cookie, and gtag.js is not requested until it says
`granted`; declining is a real opt-out, not just a hidden setting. Visitors can
change their mind later with the "Cookie Settings" link in the footer. Set
`GOOGLE_ANALYTICS_REQUIRE_CONSENT=false` only where you have a lawful basis for
analytics that does not require consent.

What is sent:

- **page views** for every public page, automatically
- `view_item` on a vehicle page, with make, body type, condition and price
- `search` when someone submits a search on the browse page
- `begin_checkout` on the order thank-you page, with the order value
- `generate_lead` on each conversion page (inquiry, test drive, financing,
  service booking, listing request, trade-in, hire booking), tagged with
  `lead_type`
- `contact` with `method=phone` or `method=whatsapp` when a visitor taps a
  phone or WhatsApp link, delegated across the whole site
- `cookie_consent` once, with `status=granted`, after a visitor accepts the
  banner and gtag.js loads on the next request (declining sends no analytics)

Staff and admin pages are deliberately excluded: the context processor blanks
the ID for logged-in staff and for anything under `ADMIN_URL`, so internal
usage does not pollute the reports and the admin path is never handed to
Google. Tracking is also off while the test suite runs.

The CSP only allows `googletagmanager.com` and the analytics collection hosts
when an ID is configured (see `config/security_middleware.py`). Events are
emitted through the `{% analytics_event %}` template tag, which renders
nothing when analytics is unconfigured, so templates stay valid either way.

After deploying, open GA4 -> **Realtime** and load the site: you should see
your own page view (use a private window, and a customer account rather than a
staff one), then browse a vehicle and submit a test inquiry to confirm the
events arrive.

## Search console and social sharing

Verification tokens are plain settings, rendered as meta tags by `base.html`.
Add the contents of Google's `google-site-verification` tag and Bing's
`msvalidate.01` tag to `.env` when you claim the site:

```dotenv
GOOGLE_SITE_VERIFICATION=your-google-token
BING_SITE_VERIFICATION=your-bing-token
```

Both are empty by default, so no token is published until an owner sets one.
The dealership logo also becomes the default `og:image` (with
`twitter:card=summary_large_image`) on pages without their own photo; a vehicle
page still uses its primary photo.

Sitemap static pages carry a `lastmod` taken from the newest public car or
published post, so crawlers revisit them after real content changes. The home
page now emits a `WebSite`/`SearchAction` node and the FAQ page an `FAQPage`
node alongside the existing vehicle/dealer/blog schema. Listing photos use
`srcset` with the existing full and thumbnail files, plus lazy loading, so a
phone does not download every full-size image.

## Features

Public:
- Homepage (featured cars, customer testimonials, latest news), car browse with filters/search/pagination/sorting
- Every price is shown and stored in Kenyan shillings, formatted in one place (see "Currency" above)
- Car detail with photo gallery (thumbnail picker, hover zoom), similar vehicles, recently viewed, favorites, payment calculator, inquiry/order/test-drive booking
- Sold vehicles stay visible with a "Sold" badge, and the detail page still suggests similar vehicles that are available now
- Trade-in value estimator: an instant estimate of what your car is worth, with the arithmetic shown (see "Trade-in valuation" above)
- "List Your Car": a signed-in customer asks us to advertise their car for a
  fee; we inspect the car, verify the logbook, take the fee and publish the
  listing on their behalf (see "List your car" above)
- Car hire and tours & travel: browse the hire fleet (with filters and a
  "your dates" search that hides cars already out), hire a car self-drive or
  with a driver, send a booking request, and follow it under "My Hires" (see
  "Car hire and tours & travel" above)
- Compare up to 4 vehicles side-by-side (pick them with checkboxes in the browse list or on any car's detail page)
- Reviews page: logged-in customers submit reviews; staff approve them in the admin
- Contact form, newsletter signup, about page, financing page, FAQ page, "My Activity"
- News/blog with management via the admin
- SEO: per-page meta/Open Graph tags, schema.org JSON-LD (Vehicle/Offer,
  AutoDealer/Review, WebSite/SearchAction, FAQPage, BlogPosting,
  BreadcrumbList), robots.txt, sitemap.xml with dynamic `lastmod`, and
  machine-readable vehicle feeds at `/feeds/vehicles.json` and
  `/feeds/vehicles.xml` (see "Structured data and vehicle feeds" above)
- Saved searches: "email me when a matching car arrives" form on the browse page;
  current matches are emailed immediately and the `check_saved_searches` command
  emails subscribers about newly listed matching cars; edit a saved search and
  preview matching vehicles from your My Account page
- Price-drop & back-in-stock alerts: get an email when a car you favorited (or
  one matching a saved search) drops in price or returns to the lot; manage these
  alerts from the "Alert Preferences" card on your My Account page
- Automatic status-update emails: customers are notified when their order or
  inquiry reaches a meaningful status (see "Status update emails" above)
- Spam protection on every public form: hidden honeypot, link heuristic, and
  per-IP rate limiting, plus optional captcha (see "Anti-spam" above)
- Site chatbot: a floating assistant that answers common questions from live
  site data and hands off to staff when it can't help (see "Site chatbot" above)
- In-app notifications: a bell in the navbar with an unread badge, a list of
  updates, and mark-read/mark-all-read; fed by order, payment, review and hire
  booking events (see "Notifications" above)

Accounts:
- Register (requires email verification), login, logout, password reset
- Optional "Sign in with Google" on the login and registration pages (see above)
- Favorites, staff account management (temp password, forced password change, activate/deactivate)

Staff panel:
- Staff dashboard quick actions and the "Staff" navbar dropdown give admins one
  place to reach the day-to-day screens: Add Car, Edit About Page, Edit Contact
  Info, Reviews, Chat Transcripts, Hire Fleet, Hire Bookings, Orders and Payments
- Dashboard with stats, inquiries/orders/appointments/customers/sales lists with status updates
- Lead follow-up engine: assign owners and follow-up dates to inquiries and contact
  messages, log contacts, filter by overdue/due-today/unassigned, and work the daily
  follow-up reminders from the Celery beat schedule (see "Lead follow-up" above)
- Abandoned-order recovery: staff work through orders awaiting the deposit, are
  reminded once after 24 hours, and can release a stale (7+ days waiting) order to
  cancel it and free the vehicle for a new enquiry (see "Abandoned order recovery"
  above)
- Add/edit customers and record sales directly in the panel (invoice number and
  total amount are generated/calculated automatically)
- Review moderation: approve or hide submitted reviews from the staff panel
- CSV exports (with current filters applied) for sales, customers, inquiries, and orders
- CSV export of the conversion funnel from the Traffic page
- Vehicle photos are resized, straightened and stripped of their EXIF data when
  they are uploaded, with a thumbnail generated at the same time (see "Images"
  above)
- PDF sales report export (same filters, downloadable report)
- Edit the "Visit or Call" section on the contact page (address, phone, email, WhatsApp
  number, hours) from the staff panel or the admin; when a WhatsApp number is set, the
  contact page shows a "Chat on WhatsApp" button
- Edit the About page content (tagline, vision, mission, and the three value cards)
  from the staff panel or the admin
- Reports (revenue, top models, conversion), customer purchase history
- Chat Transcripts: read chatbot conversations, filter to those that asked for a
  person, and follow up via the linked contact message
- Traffic analytics: unique visitors, page views, bounce rate, traffic sources,
  devices, top pages and the most viewed vehicles, for the last week, month or
  quarter (see "Traffic analytics" above)
- Conversion funnel: visitors -> inquiries -> orders -> sales, conversions and
  revenue per source, and the vehicles that convert best (see "Traffic
  analytics" above)
- Record a sale against the online order it came from, so the trade-in value
  the customer claimed is carried across
- Price-drop / back-in-stock alerts: "Send Alerts Now" button on the dashboard
  (with a pending count), or run `python manage.py send_car_alerts` on a schedule
  (`--dry-run` previews without emailing); price and status changes are logged for audit
- Listing requests: work through the requests customers make to have their
  cars advertised, verify the car and the logbook, record the fee, and publish
  the listing on the owner's behalf (see "List your car" above)
- Hire fleet and hire bookings: post the cars in the fleet with a self-drive
  and a tour rate, and work through the booking requests — check the licence
  and ID, record the payment, confirm, or turn down — with a clash check on
  every confirmation (see "Car hire and tours & travel" above)

## Structured data and vehicle feeds

Every public page that describes a thing also describes it in JSON-LD, so
search engines and social previews understand it without scraping the HTML:

| Page | schema.org type |
|------|-----------------|
| Home | `AutoDealer` |
| Car detail | `Vehicle` + `Offer` + `BreadcrumbList` |
| Reviews | `AutoDealer` with `aggregateRating` and `Review` items |
| News article | `BlogPosting` + `BreadcrumbList` |

The builders live in `cars/structured_data.py` as plain functions, and
`json_ld()` escapes `<`, `>`, `&` and the line separators before anything is
written into a `<script>` tag — a car description can never break out of the
block. Sold cars still get a `Vehicle` node, but their `Offer.availability` is
`SoldOut`, so a stale listing is not advertised as available.

Two feeds expose the same inventory to partners and crawlers:

- `GET /feeds/vehicles.json` — `application/json`
- `GET /feeds/vehicles.xml` — `application/xml`

Only **available** cars appear in a feed (a feed is a sales channel; the
sitemap keeps sold cars so old links do not 404). Both endpoints send
`Cache-Control: public, max-age=900` and support `ETag` / `Last-Modified`
conditional GET, so a polling partner gets a cheap `304`. Photos are absolute
URLs, and the price is always a string in the configured currency (`KES` by
default, from `cars/money.py`).

## Notifications

The navbar bell is backed by `notifications.Notification` (the app existed but
was unused). `notifications/services.py` has one entry point, `notify()`, and a
staff fan-out helper, `notify_staff()`; both skip guests and deactivated
accounts. The context processor exposes the unread count and the five most
recent notifications to every template, and swallows lookup errors so a
notification problem never takes a page down.

Customers are notified when an order changes status, a deposit is received, a
review is approved, or a hire booking changes status. Staff are notified about
new orders and received deposits — deliberately not every inquiry, so the bell
stays useful. The daily lead-reminder and deposit-reminder jobs push owners and
staff through the same `notify()` / `notify_staff()` fan-out, so follow-up
reminders arrive in the bell as well as by email. Clicking a notification marks
it read and follows its stored `url` only when it points back to this site.

## Health check

`GET /health` returns `200 {"status": "ok"}` whenever the web process is
serving. It does no database access, session work, or template rendering, so
platform health checks and uptime monitors can poll it cheaply. The endpoint is
intentionally public and has **no trailing slash** (so the probe gets a `200`
rather than a redirect).

## Deployment

The project targets a managed PaaS. [`render.yaml`](render.yaml) is a Render
blueprint that creates a web service, a Celery worker, a Celery beat instance,
managed Postgres and Redis. See [DEPLOYMENT.md](DEPLOYMENT.md) for the full
pre-deployment checklist (secrets, HTTPS/HSTS, SMTP, static files, Celery,
backups and go-live checks).

Things worth calling out:

- **Managed services** — set `DATABASE_URL` (Postgres) and `REDIS_URL`. The app
  refuses to boot if `DATABASE_URL` is set but cannot be parsed, rather than
  silently falling back to SQLite. Redis backs both the cache and Celery, so
  rate limits and axes lockouts are shared across workers.
- **Object storage** — a PaaS filesystem is ephemeral. Set `USE_S3=true` and the
  `AWS_*` variables (S3 or Cloudflare R2) so uploads survive a deploy. Static
  files are served by Whitenoise and built with `collectstatic`.
- **Staff two-factor authentication** — outside development, a staff sign-in
  pauses after the password and emails a six-digit one-time code
  (`STAFF_2FA_ENABLED`, on by default when `DEBUG=false`). Staff accounts
  without an email address skip the second factor, so give every staff member a
  real address. Customers are unaffected.
- **Admin URL** — Django admin is restricted to active superusers and lives at
  `ADMIN_URL` (default `/admin/`). Set it to an unguessable path in production;
  the navbar link follows the setting and admin responses are marked
  `noindex`. When staff 2FA is on, the admin login form is bypassed so
  superusers go through the same emailed-code flow.
- **Daily backups** — the `backup-database` Celery beat job snapshots the
  database at 02:00 and prunes copies older than `BACKUP_RETENTION_DAYS`. On
  Postgres it uses `pg_dump` when available (falling back to a JSON dump) and
  uploads the result to the bucket when `USE_S3=true`. Run
  `python manage.py backup_db` by hand at any time.

Before going live, run the project's audit:

```bash
virtual\Scripts\python manage.py security_check
```

It checks DEBUG, the secret key, hosts, HTTPS/HSTS, secure cookies, CSP, staff
2FA, the email backend, the database engine, the backup directory, the admin
path, `SITE_BASE_URL`, the M-Pesa callback, shared Redis, error reporting,
object storage and Django's own deployment checks, and exits non-zero when
something must be fixed.

## Testing

```bash
virtual\Scripts\python manage.py test accounts cars hiring notifications payments traffic
```