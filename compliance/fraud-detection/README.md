# Fraud Detection

Placeholder module for automated fraud / risk scoring. Today the platform
has manual review tooling but no automated risk engine.

## What already exists in the repo

Manual / reactive tooling:

- **Ride flags** —
  `admin-dashboard/src/app/dashboard/rides/_components/ride-flag-form.tsx`
- **Ride complaints** —
  `admin-dashboard/src/app/dashboard/rides/_components/ride-complaint-form.tsx`
- **Support flags tab** —
  `admin-dashboard/src/app/dashboard/support/_tabs/flags.tsx`
- **Admin support routes** — `backend/routes/admin/support.py`,
  `backend/routes/admin/rides.py`
- **Input sanitization + validators** — `backend/validators.py`,
  `backend/tests/test_sanitize_string.py`
- **Refresh-token revocation** — `backend/utils/refresh_tokens.py`
- **Idempotency for rides** —
  `backend/alembic/versions/20260414_0007_ride_idempotency.py`
- **Payment safety** — Stripe Payment Intents in `backend/routes/payments.py`
  (3DS + webhook signature verification)

## What's missing

- Automated risk scoring on signup, ride request, payout
- Device / fingerprint signals (install ID, IP reputation)
- Velocity rules (cancels/hour, new-card + new-device + high-fare, etc.)
- Collusion detection (rider ↔ driver repeated pairing, promo abuse rings)
- Chargeback ingestion from Stripe webhooks → fraud feature store
- Rules engine + review queue feeding the existing flags UI

## Suggested layout when implementing

```
compliance/fraud-detection/
  rules/           # declarative velocity / pattern rules
  signals/         # feature extractors (device, payment, geo)
  scoring/         # composite risk score + model hooks
  queue/           # review queue → admin flags integration
  README.md
```
