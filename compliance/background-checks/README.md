# Background Checks

Placeholder module for driver background-check vendor integration
(Checkr, Onfido, Sterling, etc.). No vendor API is wired up yet.

## What already exists in the repo

Driver verification has internal scaffolding — a background-check vendor
just needs to be plugged in as a new step in the existing pipeline.

- **Onboarding state machine** — `backend/onboarding_status.py`
  States: `profile_incomplete` → `vehicle_required` → `documents_required`
  → `pending_review` → `verified` / `suspended` / `documents_rejected` /
  `documents_expired`.
- **Document upload + expiry** — `backend/documents.py`,
  `backend/utils/document_expiry.py`, `backend/tests/test_documents.py`
- **Admin review UI** — `admin-dashboard/src/app/dashboard/drivers/page.tsx`,
  `backend/routes/admin/documents.py`, `backend/routes/admin/drivers.py`
- **Driver classification policy** — `docs/compliance/DRIVER_CLASSIFICATION.md`
- **IC agreement template** — `docs/legal/DRIVER_IC_AGREEMENT_TEMPLATE.md`

## What's missing

- External vendor adapter (Checkr / Onfido / Sterling API client)
- Webhook handler for vendor status callbacks
- New onboarding state `background_check_pending` between `pending_review`
  and `verified`
- Candidate-consent disclosure flow (FCRA in US)
- Periodic re-check scheduling (annual / on-demand)

## Suggested layout when implementing

```
compliance/background-checks/
  adapters/        # checkr.py, onfido.py
  webhooks/        # vendor status callbacks
  consent/         # disclosure + authorization templates
  README.md
```
