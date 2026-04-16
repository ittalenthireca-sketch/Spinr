# Spinr — Compliance Posture

> **Role:** Privacy Officer / Compliance Lead  
> **Audience:** Legal, Finance, Privacy Officer, auditors, CTO

---

## 1. Regulatory landscape

```
┌──────────────────────────────────────────────────────────────┐
│  Spinr operates in Saskatchewan, Canada                      │
│                                                              │
│  Applicable regulations:                                     │
│  ┌────────────────┬─────────────────────────────────────┐    │
│  │  PIPEDA        │  Personal Information Protection and │    │
│  │  (federal)     │  Electronic Documents Act            │    │
│  │                │  → governs collection/use of PII     │    │
│  ├────────────────┼─────────────────────────────────────┤    │
│  │  Quebec Law 25 │  Act respecting the protection of   │    │
│  │  (provincial)  │  personal information in the private │    │
│  │                │  sector (applies to QC operations)   │    │
│  ├────────────────┼─────────────────────────────────────┤    │
│  │  PCI DSS       │  Payment Card Industry Data Security │    │
│  │  SAQ-A         │  Standard — Spinr qualifies for the  │    │
│  │  (industry)    │  simplest self-assessment level      │    │
│  ├────────────────┼─────────────────────────────────────┤    │
│  │  Saskatchewan  │  No provincial TNC Act yet; federal  │    │
│  │  TNC           │  Transport Canada regs + municipal   │    │
│  │  (operational) │  licensing (Saskatoon, Regina)       │    │
│  ├────────────────┼─────────────────────────────────────┤    │
│  │  CRA / Income  │  T4A slips for IC drivers earning    │    │
│  │  Tax Act       │  > CAD 500/year                      │    │
│  └────────────────┴─────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. PIPEDA — 10 principles implementation

```
Principle           Implementation
──────────────────────────────────────────────────────────────────

1. ACCOUNTABILITY    Privacy Officer role designated (see PIPEDA.md).
                     privacy@spinr.app escalation path.
                     Breach notification: 72h to OPC.

2. IDENTIFYING       Data-collection register (see §3 below).
   PURPOSES          Purpose stated at collection point (ToS + Privacy
                     Policy v1.0 required on first login).

3. CONSENT           OTP login = meaningful consent for transport
                     service. ToS + Privacy acceptance persisted with
                     version number + timestamps (users table columns:
                     accepted_tos_version, accepted_tos_at,
                     accepted_privacy_at).

4. LIMITING          No PAN, no raw card data, no biometrics.
   COLLECTION        Minimal fields: phone, name, GPS (ride only),
                     payment token (opaque Stripe ID).

5. LIMITING USE,     Retention schedule enforced nightly:
   DISCLOSURE,       OTP records: 24h, GPS: 90d, chat: 180d,
   RETENTION         billed rides: 7y (CRA), cancelled: 90d.

6. ACCURACY          GET /users/me returns current record.
                     PATCH /users/me allows self-correction.
                     Drivers: PATCH /drivers/me.

7. SAFEGUARDS        • TLS everywhere (Fly-enforced)
                     • RLS deny-all on all tables
                     • SUPABASE_SERVICE_ROLE_KEY rotated
                     • Fly secrets (never in source)
                     • Sentry: no PII in error payloads

8. OPENNESS          Privacy Policy URL in app footer + ToS screen.
                     docs/compliance/PIPEDA.md published internally.

9. INDIVIDUAL        GET /users/me: access own data.
   ACCESS            DELETE /users/me: account deletion (support
                     assisted; 30-day retention for fraud prevention).

10. CHALLENGING      privacy@spinr.app.
    COMPLIANCE       Response within 30 days per PIPEDA.
──────────────────────────────────────────────────────────────────
```

---

## 3. Data collection register

```
Field             Collected from  Stored where           Retention  Purpose
──────────────────────────────────────────────────────────────────────────────
Phone number      Rider/Driver    users.phone            Forever    Identity + OTP
First/last name   Profile setup   users.first/last_name  Forever    UX, receipts
Email             Profile setup   users.email            Forever    Receipts, support
GPS location      In-ride only    gps_breadcrumbs        90 days    Dispute resolution
Pickup/dropoff    Ride creation   rides.pickup/dropoff   7 years    CRA + billing
Card brand/last4  Via Stripe API  rides.payment_          7 years    Receipt display
                                  method_details
Stripe PM ID      Via Stripe SDK  users.default_         Until card User's payment
                                  payment_method_id      removed    preference
ToS version +     First login     users.accepted_        Forever    PIPEDA consent
timestamps                        tos_version/at                     proof
──────────────────────────────────────────────────────────────────────────────
What we NEVER collect:
  • Full card number (PAN)    • CVV / CVC
  • Card expiry               • SIN / SSN
  • Passport / government ID  • Biometrics
```

---

## 4. PCI DSS scope

```
Rider device                   Stripe                 Spinr backend
     │                            │                         │
     │  Stripe PaymentSheet SDK   │                         │
     ├─────── card number ────────►│                         │
     │  (never leaves SDK memory  │                         │
     │   in cleartext)            │  Tokenise → PM ID       │
     │                            ├──────────────────────── ►│
     │                            │    Only PM ID arrives    │
     │                            │    (no PAN, no CVV)      │
     │                            │                         │
     │                            │◄── confirm PaymentIntent─┤
     │                            │    (PI ID only)          │
     │◄────── payment result ─────┤                         │

PAN NEVER TOUCHES SPINR CODE OR INFRASTRUCTURE.

Scope determination:
  SAQ-A qualifies when:
  ✅ All cardholder data functions outsourced to PCI-compliant vendor
  ✅ Company does not electronically store cardholder data
  ✅ No face-to-face channels

  Spinr qualifies: ✅ ✅ ✅ → SAQ-A

What would EXIT SAQ-A scope (do not implement):
  ❌ Custom card input form POSTing to Spinr backend
  ❌ Logging request bodies that could contain card data
  ❌ Storing raw PAN in any table/log/lake
  ❌ Routing webhooks through a Spinr-controlled intermediary
  ❌ Backend proxy between Stripe SDK and Stripe API
```

---

## 5. Driver classification

```
CRA multi-factor test applied to Spinr drivers:

Factor                Spinr's position           IC indicator?
──────────────────────────────────────────────────────────────
Control over work     Driver sets own hours,       ✅ IC
                      accepts/rejects rides,
                      uses own device

Ownership of tools    Driver owns/leases           ✅ IC
                      vehicle + phone + fuel

Chance of profit /    Earnings = fares minus       ✅ IC
risk of loss          platform fee; driver
                      bears fuel/maint costs

Integration into      Platform is marketplace,     ✅ IC
business              not employer; drivers
                      work for multiple platforms

Exclusivity           No exclusivity requirement   ✅ IC
──────────────────────────────────────────────────────────────
Conclusion: IC classification is defensible.

Required safeguards:
  • IC Agreement signed before first ride (v1 template in
    docs/legal/DRIVER_IC_AGREEMENT_TEMPLATE.md)
  • No minimum hours / shift requirements imposed
  • No uniform or appearance requirements
  • T4A issued for drivers earning > CAD 500/year (by Feb 28)
  • Driver has visible access to their earnings data
```

---

## 6. ToS + Privacy consent flow

```
New user — first OTP verification:

  POST /auth/verify-otp
  {
    "phone": "+13065550199",
    "otp":   "123456",
    "accepted_tos_version": "v1.0",   ← REQUIRED for new users
    "accepted_privacy_at": true        ← triggers server timestamp
  }

  Backend:
    ├── Validates OTP
    ├── Looks up user by phone
    ├── If NEW user and accepted_tos_version missing → 422 error
    │     "ToS acceptance is required to create an account"
    └── If accepted_tos_version present:
          users.accepted_tos_version = "v1.0"
          users.accepted_tos_at      = now()
          users.accepted_privacy_at  = now()
          → stored forever as audit trail

Re-acceptance on ToS change:
  → Bump version string in app + backend config
  → On next login: if users.accepted_tos_version < current
    → Show ToS screen again
  → New acceptance recorded with new version + timestamp
```

---

## 7. Data breach response

```
Detection
   │
   ├── Automated: Sentry alert / anomalous query pattern
   └── Manual: user report / security researcher
         │
         ▼
Hour 0: Confirm breach scope
   ├── Identify affected tables + row count
   ├── Identify attack vector
   └── Isolate if ongoing (revoke API keys, rotate secrets)
         │
         ▼
Hour 0-24: Internal escalation
   ├── Notify Privacy Officer + CTO + Legal
   ├── Preserve logs (do NOT delete — evidence)
   └── Begin remediation
         │
         ▼
Hour 24-72: OPC notification (PIPEDA obligation)
   └── Report to Office of the Privacy Commissioner if:
       • Real risk of significant harm to individuals
       • Contains sensitive PII (phone, location, payment tokens)
         │
         ▼
Post-72h: User notification (if required by OPC)
   ├── Direct notification to affected users
   └── Status page update
```

---

## 8. Compliance posture — before / after

```
                     BEFORE AUDIT          AFTER AUDIT
──────────────────────────────────────────────────────────────
PIPEDA               No documentation      PIPEDA.md published
                     No Privacy Officer    PO role designated
                     No breach plan        72h runbook documented
                     No retention policy   Nightly sweep running

Data retention       Unlimited growth      8 table classes, TTLs
                     No deletion           enforced nightly

ToS acceptance       Not recorded          accepted_tos_version +
                                           timestamps in users table
                                           Required for new accounts

PCI SAQ-A            No documentation      SAQ-A scope confirmed
                     Undocumented scope    Negative controls listed
                                           Annual checklist defined

Driver IC status     No documentation      CRA 5-factor test done
                     No IC agreement       v1 IC agreement template
                     No T4A plan           T4A obligations documented

Emergency button     Code existed, no      Twilio SMS dispatched
                     SMS sent              on every call
```
