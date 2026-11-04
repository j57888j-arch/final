# WeraqamBot V2

Modular Telegram commerce/operations bot built with Python 3.12, aiogram 3, FastAPI, PostgreSQL, Redis and SQLAlchemy async.

> Security note: the bot is designed for lawful telecommunications services. It must never request, collect, store or forward Telegram login OTP codes, passwords or 2FA secrets.

## Implemented modules

- User registration, profile, referral links and block state; activity timestamps refresh on user interactions (throttled to one DB write per five minutes).
- Countries/services catalogue, country activation, service price/status editing and inventory management.
- Optional individually tracked telecom resources: encrypted with Fernet at rest, fingerprinted for duplicate prevention, reserved atomically and delivered only after order completion.
- Atomic inventory reservation with row locking on PostgreSQL.
- Wallet purchase for services that are not classified as digital goods/services.
- Double-entry wallet ledger and idempotency keys.
- Telegram Stars invoice/pre-checkout/successful-payment flow for services with a Stars price.
- Manual top-up proof submission and admin review.
- Order queue, single-admin claim, completion, cancellation and wallet refund.
- Promo codes (percentage/fixed, global limit, per-user limit, minimum amount and expiry fields).
- Referral bonus after the referred user's first completed order.
- CRM lookup/blocking, recent order/payment history and balance adjustment command.
- Support tickets and admin replies.
- Text/photo/video/document broadcast queue through transactional outbox worker, with an optional URL button.
- Date-range order reports exported to CSV, XLSX and PDF.
- Role/permission schema with Super Admin, Manager, Operator, Finance, Support, Order Manager, Finance Admin, Support Admin and Catalogue Manager roles; `/set_role` assigns a role to a registered user.
- Audit log, health/readiness endpoints, webhook and local polling modes.

## Important integrations and boundaries

1. **Telegram Stars:** Telegram's current Payments guidance requires digital goods and services sold inside Telegram to be paid in Telegram Stars (`XTR`). Each digital service must have an integer `stars_price`, and `TELEGRAM_STARS_ENABLED=true` must be set. The code checks the payload, payer, currency and amount before accepting pre-checkout/successful-payment updates. Refunds of paid Stars orders call Telegram's refund method before the order is rejected.
2. **CLICK:** the adapter and callback routes exist but deliberately fail closed (HTTP 503). Merchant Prepare/Complete signature verification must be implemented against the exact current merchant contract before enabling real payments. The project does not invent a signature formula or mark unverified callbacks as paid.
3. **Manual card payments:** only available with `PAYMENT_MODE=manual` and configured card details. It is a manual account top-up flow; admins must review the uploaded proof. Do not use it for in-Telegram digital goods/services where Telegram Stars are mandatory.
4. There is no third-party telecom vendor fulfilment API. Admins complete lawful orders manually in the admin queue. Individual resources can be added with `/inventory_add SERVICE_ID RESOURCE`; the resource value is encrypted at rest and is revealed to the customer only after an admin marks the order complete.
5. Broadcast accepts text, photos, videos, documents and animations. It copies the original admin message and optionally adds one URL button. Telegram rate limits are respected by the worker.
6. Reports can be exported using `/report YYYY-MM-DD YYYY-MM-DD csv|xlsx|pdf` (maximum 366 calendar dates). The role assignment command remains `/set_role TELEGRAM_ID Manager` (or Operator, Finance, Support); bootstrap Super Admins are configured with `ADMIN_IDS`.
7. CRM search provides order and payment history buttons. Full customer lifetime-value segmentation and a self-service permission editor are not part of this release.
8. The dashboard shows UZS totals, today/month totals and Stars totals in XTR. Mixed currencies are not converted; reports preserve each currency separately.

## Quick start (local)

```bash
# Python 3.12
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at least:

```env
BOT_TOKEN=your_real_bot_token
ADMIN_IDS=your_telegram_numeric_id
DATABASE_URL=sqlite+aiosqlite:///./weraqambot.db
REDIS_URL=
AUTO_CREATE_TABLES=true
ENVIRONMENT=development
```

For individual resource inventory, generate a Fernet key and set `PHONE_ENCRYPTION_KEY`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set the same key on both Render web and worker services. Keep it stable and secret. If you lose or rotate it without re-encrypting stored resources and pending outbox messages, those values cannot be decrypted. The bot does not collect SMS/OTP codes, Telegram login codes or 2FA passwords. Telegram ReplyKeyboard buttons cannot be assigned custom colors by the Bot API; the sample layout, labels, emojis and two-column grouping are reproduced instead.

Start the bot in long-polling mode:

```bash
python -m app.main
```

Local polling starts the bot and the outbox worker together. SQLite is intended only for development/smoke testing; production must use PostgreSQL and Redis.

## Run database migrations

```bash
alembic upgrade head
```

For new schema changes, generate a revision after updating ORM models:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

`AUTO_CREATE_TABLES=true` is a convenience for a fresh local setup. Set it to `false` in production and use Alembic migrations.

## Render deployment

The included `render.yaml` describes a FastAPI web service, a background worker, PostgreSQL and Redis. Set `BOT_TOKEN`, `ADMIN_IDS`, `REDIS_URL` and `WEBHOOK_URL` in Render. The web service command is:

```bash
alembic upgrade head && uvicorn app.api.server:app --host 0.0.0.0 --port $PORT
```

The background worker command is:

```bash
python -m app.workers.runner
```

`WEBHOOK_SECRET` is required in production. `WEBHOOK_URL` must be the public Render web-service URL. Do not run polling and webhook simultaneously for the same bot token.

Health endpoints:
- `GET /healthz` — process health.
- `GET /readyz` — database and Redis readiness.

## Admin workflow

1. Add your Telegram numeric ID to `ADMIN_IDS`.
2. Send `/start` to the bot, then `/admin`.
3. Create a country, then create a service.
4. Use **📦 Zaxira** for aggregate stock, or set aggregate AVAILABLE to zero and add individually encrypted resources with `/inventory_add SERVICE_ID RESOURCE`.
5. Configure a Stars price for every digital service and enable Stars only after reviewing the product's Telegram payment classification.
6. For manual top-ups, set `PAYMENT_MODE=manual`, `PAYMENT_CARD_NUMBER` and `PAYMENT_CARD_HOLDER`.
7. Admin commands:

```text
/admin
/adjust_balance TELEGRAM_ID +/-SUMMA SABAB
/reply_ticket TICKET_ID javob matni
/inventory_add SERVICE_ID RESURS
/inventory_list SERVICE_ID
/inventory_import SERVICE_ID
/inventory_export SERVICE_ID
/inventory_retire ITEM_ID
/report 2026-10-01 2026-11-04 xlsx
```

## Broadcast workflow

1. Open **📢 Xabar yuborish**.
2. Send a text, photo, video, document or animation.
3. Enter an optional inline button label, or `-` to skip.
4. If a label was entered, send an `https://` or `http://` URL.
5. The worker copies the source message to active users and records per-recipient results.

## Order states

`awaiting_payment → paid → processing → completed`

Unpaid orders expire and release reserved inventory. A rejected wallet order is refunded to the user's wallet using an idempotent ledger transaction. A paid or processing Stars order is marked `refund_pending`, refunded through Telegram, then rejected/released. If the external refund succeeds but the following database commit fails, reconcile the payment against Telegram before retrying.

## Security and operational notes

- Never commit `.env` or real tokens to Git.
- Rotate any token accidentally exposed in logs or a repository.
- Restrict admin IDs and Render service access.
- Do not log payment secrets, card data or proof contents.
- Take database backups and test restore procedures.
- Use HTTPS for webhook endpoints.
- Keep PostgreSQL and Redis private/internal where possible.
- The outbox provides retryable at-least-once delivery; after a crash between Telegram send and DB acknowledgement, a notification may be delivered twice. Business payments remain protected by payment idempotency.
- A Stars order in `refund_pending` means Telegram refund orchestration started. If the process crashes during this external call, verify the charge in Telegram and reconcile the payment/order before attempting another refund.

## Tests

```bash
pytest -q
python -m compileall -q app
```

The working-container verification for this package produced **12 passed, 1 skipped**. The skipped test is the async DB integration module because `aiosqlite` was not installed in that isolated verification environment; it is pinned in `requirements.txt`. Migration upgrade logic was checked separately against a pre-change SQLite schema. Live Telegram, Render, PostgreSQL/Redis and payment-provider sandbox testing must still be completed after deployment.

The tests cover money parsing, order transition rules, metadata schema creation and async SQLite integration flows for wallet purchase, inventory reservation, admin claim/completion, ledger idempotency and Telegram Stars settlement. The async integration module skips when `aiosqlite` is not installed; it is included in `requirements.txt`. For a production release, also run integration tests against disposable PostgreSQL and Redis instances and provider sandbox tests.
