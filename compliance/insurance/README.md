# Insurance & Liability

Placeholder module for rideshare insurance / liability coverage integration
(commercial auto, per-trip TNC coverage, occupational accident).
No insurer API is wired up yet.

## What already exists in the repo

- **Data retention policy** — `docs/compliance/DATA_RETENTION.md`
- **PCI scope notes** — `docs/compliance/PCI.md`
- **IC agreement template** — `docs/legal/DRIVER_IC_AGREEMENT_TEMPLATE.md`
  (references liability allocation)
- **Trip lifecycle hooks** — `backend/routes/rides.py` state transitions
  (`requested` → `assigned` → `in_progress` → `completed`) are the natural
  integration points for per-phase coverage (Phase 1 / 2 / 3).
- **Disputes flow** — `backend/routes/disputes.py` for claim handoff

## What's missing

- Insurer API adapter (e.g. Buckle, Slice, INSHUR)
- Per-trip coverage token attached to ride records
- Certificate-of-insurance (COI) storage + driver-side retrieval endpoint
- Claim-filing workflow that links ride + dispute + insurer claim ID
- Regulatory reporting export (state TNC filings)

## Suggested layout when implementing

```
compliance/insurance/
  adapters/        # insurer API clients
  policies/        # coverage tier config per jurisdiction
  claims/          # claim lifecycle + linkage to disputes
  README.md
```
