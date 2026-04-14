# Spinr — Data Retention Policy

Phase 3.1 of the production-readiness audit (audit finding C1).

**Version:** 1.0  
**Effective date:** 2026-04-14  
**Owner:** Privacy Officer (see `docs/compliance/PIPEDA.md`)  
**Review cadence:** Annually, or on any material change to the data
model or applicable law.

---

## Purpose

This policy defines how long Spinr retains each category of personal
data, the lawful basis for that period, and how data is destroyed when
the period expires. It satisfies:

- **PIPEDA Principle 5** — "Limiting Use, Disclosure, and Retention":
  personal information must be retained only as long as necessary
  for the identified purpose.
- **Quebec Law 25 (Bill 64)** — requires destruction or anonymization
  of personal information when the purpose for which it was collected
  is accomplished.
- **CRA / tax requirements** — financial records must be kept for
  7 years under the *Income Tax Act*.

---

## Retention schedule

| Data class | Table(s) | Retention | Basis | Destruction method |
|---|---|---|---|---|
| Ride records (completed, billed) | `rides` | 7 years from completion | Tax / CRA | Anonymize `rider_id`, `driver_id` → NULL; keep fare, distance for accounting |
| Ride records (cancelled, never billed) | `rides` | 90 days from cancellation | Operational | Hard-delete |
| GPS breadcrumbs (in-ride) | `gps_breadcrumbs` | 90 days from ride end | Operational / safety | Drop rows; partition drop once partitioned (Phase 4.6) |
| Chat messages | `chat_messages` | 180 days from ride end | Content moderation SLA | Hard-delete |
| Deactivated / deleted user PII | `users` | 30 days after account deactivation | Fraud dedup window | Hard-delete all columns except a 1-way hash of phone for fraud dedup |
| Driver government-ID document images | Supabase Storage (`driver-documents` bucket) | 30 days after approval or rejection | Processing purpose fulfilled | Delete from Storage; nullify URL in `driver_documents` |
| OTP records | `otp_records` | 24 hours from creation | Authentication | Hard-delete |
| Refresh tokens (expired/revoked) | `refresh_tokens` | 7 days after expiry/revocation | Security audit trail | Hard-delete |
| Background-task heartbeat | `bg_task_heartbeat` | Indefinitely (tiny; one row per task) | Operational | N/A |
| Stripe events (processed) | `stripe_events` | 90 days from processing | Financial reconciliation | Hard-delete |
| Support tickets | Not yet in DB (email only) | 3 years from resolution | Consumer protection | Anonymize reporter identity |
| Consents / ToS acceptances | `users` columns (`accepted_tos_*`) | Life of account + 7 years | Legal proof of consent | Anonymize after account hard-delete |
| Access logs (Fly) | Log drain (BetterStack) | 30 days | Security / SLO | Aggregator auto-purge |

### Retention for minor-related data

Spinr does not knowingly collect data from persons under 18.
If we become aware that a minor's data was collected, it is deleted
within 72 hours. See `docs/compliance/PIPEDA.md#minor-data`.

---

## Implementation: nightly cron

The `data_retention` background loop in `backend/utils/data_retention.py`
runs once per 24 hours (02:00 UTC) and applies the schedule above.
It is registered in `backend/worker.py` alongside the other loops.

Every deletion batch is logged at `INFO` level with:
- `task: data_retention`
- `table` and `clause` for auditability
- `deleted_count` — number of rows affected

A row is logged at `WARNING` if any deletion returns an unexpected
error (the loop continues to the next table; it does not abort).

### Manual run

```bash
# Dry-run (prints what would be deleted, no writes):
RETENTION_DRY_RUN=true python -c "
import asyncio
from utils.data_retention import run_retention_pass
asyncio.run(run_retention_pass(dry_run=True))
"

# Live run (admin only — use with caution):
python -c "
import asyncio
from utils.data_retention import run_retention_pass
asyncio.run(run_retention_pass())
"
```

---

## Data-subject requests (DSR)

Individuals may request deletion of their personal data at any time.
Our retention policy does not override the right to deletion; however,
we may retain anonymized financial records for the tax-mandated 7-year
period.

DSR flow:
1. Rider emails `privacy@spinr.app` or uses the in-app "Delete account"
   button (Phase 3.1 backlog — to be wired to `DELETE /users/me`).
2. Admin confirms identity (phone + OTP), then triggers the deletion
   via the admin dashboard.
3. Within 30 days (Law 25 / GDPR standard), all PII is destroyed
   except tax-required anonymized financial records.
4. Confirmation email sent to the rider's last known email.

---

## Exceptions

| Scenario | Exception | Approver |
|---|---|---|
| Active legal hold / litigation | Suspend deletion for affected rows | Legal counsel |
| Law enforcement production order | Preserve and produce | Legal counsel + CTO |
| Active fraud investigation | Suspend deletion for suspected fraud accounts | Privacy Officer |

Exceptions must be documented in the legal hold register (maintained
offline by Legal).

---

## Related

- Implementation: `backend/utils/data_retention.py`
- PIPEDA posture: `docs/compliance/PIPEDA.md`
- PCI scope: `docs/compliance/PCI.md`
- Roadmap: `docs/audit/production-readiness-2026-04/09_ROADMAP_CHECKLIST.md`
