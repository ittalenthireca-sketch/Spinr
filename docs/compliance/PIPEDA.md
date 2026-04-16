# Spinr — PIPEDA Compliance Posture

Phase 3.2 of the production-readiness audit (audit finding C2).

**Version:** 1.0  
**Effective date:** 2026-04-14  
**Jurisdiction:** Canada (federal PIPEDA + Quebec Law 25 / Bill 64)

---

## Designated Privacy Officer

| Role | Name | Contact |
|---|---|---|
| Privacy Officer | *[To be designated by CTO before launch]* | privacy@spinr.app |

The Privacy Officer is responsible for:
- Overseeing PIPEDA compliance and this document.
- Receiving and responding to privacy complaints and access requests.
- Notifying the Privacy Commissioner of Canada of material breaches
  (within 72 hours of discovery; shorter if riders are at risk of harm).
- Quarterly Privacy Impact Assessment (PIA) reviews.

---

## Principles

PIPEDA's 10 fair-information principles, applied to Spinr:

### 1. Accountability
Spinr is responsible for all personal information in its custody,
including information shared with service providers (Supabase,
Stripe, Firebase, Fly.io). Each provider is bound by a Data
Processing Agreement (DPA). DPAs are maintained by the Privacy Officer.

### 2. Identifying purposes
We collect personal information only for the purposes identified in
the Privacy Policy published in the app. Primary purposes:

| Purpose | Data collected |
|---|---|
| Rider identity & authentication | Phone number, OTP records |
| Ride request & dispatch | Pickup/dropoff coordinates, time |
| Payment processing | Stripe PaymentMethod (no raw PAN) |
| Driver onboarding & verification | Name, DOB, SIN/BN, driver's licence, vehicle docs (images) |
| Safety & support | Trip history, in-ride GPS breadcrumbs (90-day retention) |
| Push notifications | Firebase device token |
| Account management | Name, email, profile photo |

### 3. Consent
- Consent is obtained at sign-up via explicit click-through acceptance
  of the Terms of Service and Privacy Policy.
- Acceptance is recorded in `users.accepted_tos_version`,
  `users.accepted_tos_at`, and `users.accepted_privacy_at`
  (see migration `0006_tos_acceptance_columns`).
- On any version bump to the ToS or Privacy Policy, the app blocks
  further access until the user re-accepts.
- Consent is **not** pre-ticked or bundled — riders and drivers
  accept separately and on a named document version.

### 4. Limiting collection
We do not collect data beyond what is necessary for the purposes above.
Specifically:
- No raw card number (PAN) is processed or stored — Stripe handles
  this (SAQ-A scope; see `docs/compliance/PCI.md`).
- No sensitive data (health, religion, ethnicity) is collected.
- Location tracking occurs only during an active or requested ride;
  the app does not track location in the background when not on a trip.

### 5. Limiting use, disclosure, and retention
Personal information is used only for the purpose for which it was
collected. Retention periods are defined in
`docs/compliance/DATA_RETENTION.md` and enforced nightly by
`backend/utils/data_retention.py`.

Disclosure to third parties:

| Recipient | Disclosed data | Basis |
|---|---|---|
| Stripe | Rider/driver name for payment | Contractual necessity |
| Supabase | All DB data (storage processor) | DPA |
| Firebase / FCM | Device token for push notifications | User consent |
| Fly.io | Application logs (anonymized) | DPA |
| Law enforcement | Per production order only | Legal obligation |

We do **not** sell personal information. We do not share with
advertising networks.

### 6. Accuracy
Users may update their profile information via the app at any time.
Driver documents must be re-uploaded on expiry; stale documents are
flagged by the nightly expiry loop.

### 7. Safeguards
Technical safeguards:
- All data in transit: TLS 1.2+ enforced by Fly.io and Supabase.
- Data at rest: Supabase AES-256 encryption at the storage layer.
- Access control: Row-Level Security (RLS) on all `public` schema
  tables (migration `0002_rls_policy_closure`).
- Driver document images stored in a private Supabase Storage bucket;
  only the service role key can access them.
- OWASP Top-10 controls: security-headers middleware, Redis-backed
  rate limiting, refresh-token rotation.

Organizational safeguards:
- Access to production credentials is restricted to on-call engineers.
- Secrets are managed via Fly Secrets (never in source code).
- Annual security training for all staff with production access.

### 8. Openness
The Privacy Policy is linked from:
- The rider app sign-up screen.
- The driver onboarding screen.
- The website footer.

This document is maintained in the Spinr GitHub repository as the
internal compliance record.

### 9. Individual access
Individuals may request:
- **Access** to their personal data — fulfilled within 30 days via
  admin "Export user data" (Phase 3 backlog item).
- **Correction** of inaccurate data — via in-app profile edit or
  email to privacy@spinr.app.
- **Deletion** of their data — via "Delete account" in app settings
  or email to privacy@spinr.app.

Response SLA: 30 calendar days (Law 25 / PIPEDA standard).

### 10. Challenging compliance
Individuals may direct complaints to the Privacy Officer at
privacy@spinr.app. Unresolved complaints may be escalated to the
Office of the Privacy Commissioner of Canada (OPC) or, for Quebec
residents, the Commission d'accès à l'information du Québec (CAI).

---

## Quebec Law 25 (Bill 64) specifics

Quebec Law 25 applies to any business collecting data from Quebec
residents. Key obligations beyond federal PIPEDA:

| Requirement | Spinr status |
|---|---|
| Privacy Officer designation | Pending (pre-launch blocker) |
| Privacy policy published + accessible | Partial — app screen exists; website update needed |
| Confidentiality incident register | Not yet implemented |
| Anonymization / destruction on purpose fulfilment | Implemented via nightly cron |
| Privacy Impact Assessment for new projects involving PI | Process to be established (Privacy Officer owns) |
| Right to portability (machine-readable export) | Backlog (admin "Export user data") |

---

## Breach notification runbook

1. **Detect:** Security alert (Sentry, Prometheus, log anomaly) OR
   user report.
2. **Contain:** Revoke compromised credentials, disable affected API
   surface, isolate the affected machines.
3. **Assess (within 24 h):** Determine scope — how many users, what
   data classes, what risk of harm.
4. **Notify OPC (within 72 h of discovery):** File a breach report at
   [priv.gc.ca](https://www.priv.gc.ca) if there is "real risk of
   significant harm" to individuals. Simultaneously notify CAI if
   Quebec residents are affected.
5. **Notify affected users:** As soon as practicable; include what
   happened, what data, what Spinr is doing, and user protective steps.
6. **Post-incident review:** RCA within 5 business days; corrective
   controls documented.

---

## Privacy Impact Assessment (PIA) schedule

| Trigger | Action |
|---|---|
| New feature collecting personal data | Privacy Officer completes PIA before feature ships |
| New third-party service provider | DPA signed; PIA on data flows |
| Quarterly review | Privacy Officer reviews retention logs, incident register, open DSRs |
| Annual review | Full PIA; update this document |

---

## Minor data policy

Spinr is a transportation network for adults. We do not knowingly
allow users under 18 to create accounts. If we discover a minor's
account:
1. Account suspended immediately.
2. Personal data deleted within 72 hours.
3. Incident documented in the breach register.

---

## Related

- Retention policy: `docs/compliance/DATA_RETENTION.md`
- PCI scope: `docs/compliance/PCI.md`
- Driver classification: `docs/compliance/DRIVER_CLASSIFICATION.md`
- ToS acceptance trail: migration `0006_tos_acceptance_columns`
