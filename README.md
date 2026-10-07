# Lumière & Co. — Backend (Django)

The store's API and the engine behind the admin panel.
Django 5 + Django REST Framework + JWT. SQLite on your laptop, PostgreSQL in production. Razorpay for online payments.

What it does:

- **Storefront API**: products, filters, search, reviews, cart coupons, checkout, Razorpay, orders, pincode check, scent quiz, contact form, newsletter. It follows `API_CONTRACT.md` in the frontend exactly, so the React store works with no code changes.
- **Admin API** (`/api/admin/…`): powers the admin panel at `/admin` in the React app: dashboard, orders, products and photos, customers, coupons, reviews, messages, newsletter, collections, quiz, store settings and team.
- **Stock that stays honest**: stock is reserved when an order is placed, returned when it is cancelled, and unpaid online orders are auto-cancelled.
- **Emails**: order confirmation, shipping/delivery updates to customers; new-order and contact alerts to you.

## 1. Run it on your computer

Needs Python 3.11 or newer.

```bash
cd candle-backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env

python manage.py migrate
python manage.py seed_store --owner you@yourmail.com --password "ChooseAStrongOne"
python manage.py runserver
```

The API is now at http://localhost:8000/api/.

`seed_store` loads the 12 candles, collections, coupons and quiz from the original demo, and creates your **owner** login for the admin panel. It is safe to run again; it won't duplicate anything.

Want the dashboard to look alive while you explore? Add fake orders and customers:

```bash
python manage.py seed_demo_orders --count 90 --days 60
```

Don't run that on the live store.

## 2. Connect the React app

In the frontend `.env`:

```
VITE_USE_MOCK=false
VITE_API_BASE=http://localhost:8000/api
VITE_RAZORPAY_KEY=rzp_test_xxxxxxxx
```

Then `npm run dev` and open:

- Store: http://localhost:5173
- Admin panel: http://localhost:5173/admin (sign in with the owner email and password from `seed_store`)

The admin panel always talks to this backend, even if the store is still in demo mode.

## 3. Razorpay

1. Sign up at dashboard.razorpay.com and switch to **Test mode**.
2. Settings → API Keys → Generate. Put the Key ID and Secret in the backend `.env` (`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`) and the Key ID in the frontend `.env` (`VITE_RAZORPAY_KEY`).
3. Settings → Webhooks → Add: URL `https://YOUR-API-DOMAIN/api/payments/webhook/`, events `payment.captured` and `payment.failed`, and a secret you choose → put it in `RAZORPAY_WEBHOOK_SECRET`.
   The webhook catches payments where the customer closed the browser before returning to the site.

Until keys are set, cash on delivery works and online payment shows a friendly "not set up yet" message.
Test cards: https://razorpay.com/docs/payments/payments/test-card-details/

## 4. Scheduled job

Unpaid online orders hold stock. Run this every 15 minutes to release it (the timeout is set in admin → Settings):

```bash
python manage.py release_unpaid_orders
```

- Linux cron: `*/15 * * * * cd /path/to/candle-backend && .venv/bin/python manage.py release_unpaid_orders`
- Render: add a Cron Job with the same command. Railway: a cron service.

## 5. Go live

Any host that runs Python works. Render or Railway are the simplest:

1. Push this folder to GitHub.
2. Create a PostgreSQL database and a Web Service from the repo.
3. Build command: `./build.sh` · Start command: `gunicorn config.wsgi`
4. Environment variables (from `.env.example`):
   - `DEBUG=False`
   - `SECRET_KEY` = a long random string (`python -c "import secrets; print(secrets.token_urlsafe(50))"`)
   - `ALLOWED_HOSTS=api.yourdomain.com`
   - `DATABASE_URL` = the Postgres URL from your host
   - `CORS_ALLOWED_ORIGINS=https://yourdomain.com`
   - Razorpay keys, and SMTP details for real emails (`EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`; for Gmail use an App Password)
5. Open the service shell once and run `python manage.py seed_store --owner you@yourmail.com --password "…"`.
6. Set up the cron job from step 4 and the Razorpay webhook with the live URL.

With `DEBUG=False` the app switches on HTTPS redirects, secure cookies and HSTS.

**Product photos**: uploads are saved to the `media/` folder. Most free hosts wipe local files on each deploy, so either attach a persistent disk mounted at `media/`, or paste image links (from Cloudinary, ImageKit, Shopify CDN, etc.) with the "Add from link" option in the product editor. Photo links need no storage setup at all.

## Useful commands

| Command | What it does |
| --- | --- |
| `python manage.py seed_store --owner EMAIL --password PW` | Load catalogue and create/reset an owner login |
| `python manage.py seed_demo_orders --count 90` | Fake orders, customers, messages for testing |
| `python manage.py release_unpaid_orders` | Cancel stale unpaid online orders, put stock back |
| `python manage.py createsuperuser` | Another owner, from the command line |
| `python manage.py test` | Run the test suite |

A plain Django admin is also available at `/django-admin/` for owners, as a fallback for raw data edits.

## Roles

- **Owner** (`is_superuser`): everything, plus store settings and the team page.
- **Staff** (`is_staff`): orders, products, customers, coupons, reviews, messages. Can view settings but not change them.

Add staff from admin → Settings → Team.

## Project layout

```
config/        settings, URLs
accounts/      customer + staff accounts (email login), JWT auth
catalog/       products, photos, scent families, moods, occasions, reviews
orders/        cart pricing, coupons, orders, Razorpay, order timeline
core/          store settings, contact messages, newsletter, quiz, emails, management commands
adminpanel/    everything under /api/admin/ (permissions, dashboard stats, CSV exports)
seed_data/     starting catalogue (same JSON the React demo used)
```

## Admin API at a glance

All under `/api/admin/`, JWT required, staff only unless marked.

| Endpoint | Notes |
| --- | --- |
| `auth/login/`, `auth/refresh/`, `auth/me/`, `auth/password/` | Staff sign-in and profile |
| `dashboard/?days=30` | KPIs vs previous period, daily revenue, top sellers, low stock, to-do counts |
| `search/?q=` | Quick search across orders, products, customers |
| `products/` (+ `duplicate/`, `images/`, `images/reorder/`, `bulk/`) | Filters: `search, category, status, stock, ordering` |
| `categories/`, `moods/`, `occasions/` | Collections |
| `orders/` (+ `note/`, `export/`) | By order number; PATCH status, payment, courier, tracking |
| `coupons/`, `customers/` (+ `export/`), `reviews/`, `messages/`, `subscribers/` (+ `export/`), `quiz/` | |
| `staff/` | Owner only |
| `settings/` | Everyone reads, owner writes |
