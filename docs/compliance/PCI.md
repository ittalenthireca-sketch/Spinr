# Spinr — PCI DSS Scope and SAQ-A Attestation

Phase 3.5 of the production-readiness audit (audit finding C5).

**Version:** 1.0  
**Effective date:** 2026-04-14  
**Owner:** Head of Engineering / Privacy Officer  
**Review cadence:** Annually, or on any change to the payment
integration or Stripe product configuration.

---

## Executive summary

Spinr uses **Stripe** exclusively for payment processing. Stripe
handles all cardholder data (PAN, CVV, expiry) within its own
PCI-compliant environment. Spinr's infrastructure never sees, stores,
transmits, or processes raw cardholder data. This limits Spinr's
PCI DSS scope to **Self-Assessment Questionnaire A (SAQ-A)**, the
simplest possible attestation level.

---

## How cardholder data flows

```
Rider device                   Stripe                      Spinr backend
   │                              │                              │
   ├─ Stripe SDK (PaymentSheet) ──►│                              │
   │  (card details stay in SDK)  │                              │
   │                              ├─ Tokenises card → PaymentMethod ID
   │                              │                              │
   │                              │◄─── PaymentIntent confirm ───┤
   │                              │     (only PM ID, no PAN)     │
   │                              │                              │
   │◄── payment result ───────────┤                              │
```

**Key point:** The rider's card number, CVV, and expiry date are
entered directly into Stripe's hosted UI component
(`PaymentSheet` / `@stripe/stripe-react-native`). This data is
encrypted by the Stripe SDK before it ever reaches the rider's app
memory in a form accessible to Spinr code, and it is transmitted
directly from the SDK to Stripe's servers. Spinr's backend receives
only a `PaymentIntent` ID and `PaymentMethod` ID — opaque tokens
that Stripe uses to charge the card.

---

## What Spinr stores

| Field | Stored? | Where | Notes |
|---|---|---|---|
| Full card number (PAN) | **No** | — | Never touches Spinr |
| CVV / CVC | **No** | — | Never touches Spinr |
| Card expiry date | **No** | — | Never touches Spinr |
| `card_brand` (Visa, MC…) | Yes | `rides.payment_method_details` | Returned by Stripe; not PCI-sensitive |
| `card_last4` | Yes | `rides.payment_method_details` | Returned by Stripe; not PCI-sensitive |
| `payment_intent_id` | Yes | `rides.stripe_payment_intent_id` | Opaque Stripe token; not PCI-sensitive |
| `payment_method_id` | Yes | `users.default_payment_method_id` | Opaque Stripe token; not PCI-sensitive |

`card_brand` and `card_last4` are returned by Stripe's API as part
of the PaymentMethod object — they are not raw cardholder data and
are explicitly permitted under PCI DSS SAQ-A.

---

## Negative controls — do not break SAQ-A eligibility

The following changes would **exit SAQ-A scope** and require a
full PCI DSS assessment (SAQ-D or QSA engagement). Do not implement
these without first engaging a Qualified Security Assessor:

1. **Collecting card data on a Spinr-controlled page or form** —
   e.g., custom payment input fields that POST to our own backend.
2. **Logging request bodies that could contain card data** —
   e.g., logging the full Stripe webhook payload before stripping it.
3. **Storing raw PAN, CVV, or track data** in any DB table, log file,
   or data lake.
4. **Routing Stripe webhook events through a third-party intermediary**
   that Spinr controls — all webhooks must come direct from Stripe.
5. **Adding a backend proxy** between the rider's SDK and Stripe's API.

---

## Stripe configuration checklist

Confirm these settings in the Stripe Dashboard before launch:

- [ ] Webhook endpoint registered for `https://spinr-api.fly.dev/webhooks/stripe`.
- [ ] Webhook signing secret is stored as a Fly secret (`STRIPE_WEBHOOK_SECRET`),
      not in source code.
- [ ] Payment method types: `card` only (no direct bank debit, which
      carries its own compliance obligations).
- [ ] Stripe Radar (fraud rules) enabled on the Spinr account.
- [ ] Stripe Elements / PaymentSheet `confirmPayment` used — no
      server-side card confirmation that requires raw PAN transmission.
- [ ] `stripe.com` is whitelisted in the admin-dashboard CSP
      `connect-src` directive (already set in `core/middleware.py`).

---

## Responsibility matrix (PCI shared responsibility)

| Requirement | Stripe responsible | Spinr responsible |
|---|---|---|
| Encrypt cardholder data in transit | ✅ | Ensure TLS to our own API (enforced by Fly) |
| Store cardholder data securely | ✅ | Don't store it ourselves |
| Access control to cardholder data | ✅ | Restrict Stripe Dashboard access to authorized staff |
| Penetration testing of payment pages | ✅ | Include payment flow in annual pen test scope |
| Vulnerability management | ✅ | Keep `@stripe/stripe-react-native` and `stripe` PyPI up to date |
| Security policy | Both | This document + Stripe's Shared Responsibility doc |

Stripe's full SAQ-A eligibility criteria and shared responsibility
statement: https://stripe.com/docs/security/guide

---

## Annual review checklist

- [ ] Re-confirm no PAN is stored in any Supabase table or log drain.
- [ ] Confirm Stripe SDK versions are current in rider-app and driver-app
      `package.json`.
- [ ] Confirm `stripe` PyPI package is current in `backend/requirements.txt`.
- [ ] Confirm Stripe webhook signature verification is still active
      (`backend/routes/webhooks.py` — `stripe.webhook.construct_event`).
- [ ] Review Stripe Radar rules for false-positive / false-negative rate.
- [ ] Confirm no new payment method types added without PCI review.
- [ ] Sign a new SAQ-A (Stripe provides a template on the Dashboard).

---

## Related

- Payment routes: `backend/routes/payments.py`
- Webhook idempotency: `backend/routes/webhooks.py`
- Stripe queue worker: `backend/utils/stripe_worker.py`
- Security headers (CSP): `backend/core/middleware.py`
- PIPEDA data collection register: `docs/compliance/PIPEDA.md`
