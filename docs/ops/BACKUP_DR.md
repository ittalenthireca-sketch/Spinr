# Backup & Disaster Recovery

Phase 4.8 of the production-readiness audit (audit finding D2).

This document is the operator runbook for backing up Spinr's stateful
systems and restoring them after data loss. It is paired with the
quarterly restore drill: if a procedure here has not been executed
in anger within the last 90 days, assume it is stale and run the
drill before trusting it.

---

## 1. Scope & objectives

### What we protect

| Asset | Why it's in scope |
| --- | --- |
| Supabase Postgres (primary DB) | Every ride, payment, user record. Canonical source of truth. |
| Supabase Storage buckets | Driver license photos, vehicle docs, profile avatars — PII that is painful to re-collect. |
| Stripe webhook event queue (`stripe_events` table) | In-flight payment events awaiting processing. Loss = silent double-charge risk on retry. |
| Fly.io app config + secrets | `fly.toml` in git; secrets only in Fly. Loss = cannot redeploy. |
| Source code | Backend (`backend/`), mobile apps (`rider-app/`, `driver-app/`, `admin-dashboard/`), infra (`ops/`). |
| Stripe config | Webhook endpoints, product/price IDs, Connect platform settings. |

Out of scope: mobile build artifacts on EAS (rebuild from source), Sentry
events (observability, not source of truth), Prometheus TSDB (alerts re-fire
on new data).

### Targets

| SLO | Target | Rationale |
| --- | --- | --- |
| **RTO** (time from declared disaster to accepting traffic again) | **≤ 60 min** | Matches the 43.2 min/month availability budget in `SLOs.md` — one incident should not consume a full quarter. |
| **RPO** (acceptable data loss window) | **≤ 15 min** for Postgres; **≤ 24 h** for Storage; **0** for source code (git) | Supabase Pro PITR resolves to ~1 min; 15 min is the SLO we commit to operators. |
| **Drill cadence** | Quarterly | See section 4. |

A breach of RTO during a real incident is a P1 post-mortem trigger. A
drill that misses RTO is a P2 — fix the runbook, re-drill inside 30 days.

---

## 2. Backup inventory

| Component | Mechanism | Retention | Cadence |
| --- | --- | --- | --- |
| Supabase Postgres — snapshots | Supabase managed daily snapshot | 7 days (Pro plan) | Daily at 04:00 UTC |
| Supabase Postgres — PITR | Supabase WAL archival | 7 days (Pro plan) | Continuous (~1 min granularity) |
| Supabase Storage buckets | Supabase managed replication | Tied to project lifetime | Continuous |
| Supabase Storage — off-site copy | `scripts/ops/backup_storage.sh` → S3 bucket `spinr-storage-backup` | 30 days | Nightly 03:30 UTC (cron on ops host) |
| Fly.io `fly.toml` | Tracked in git (`backend/fly.toml`) | Forever | On every commit |
| Fly.io secrets manifest | `flyctl secrets list --app spinr-backend -j > secrets-manifest-$(date +%F).json` | 90 days in encrypted ops bucket | Weekly, plus after every rotation |
| Source code | GitHub remote + 2 developer clones minimum | Forever | On every push |
| Stripe config | Dashboard JSON export (Developers → Webhooks → …; Products → Export CSV) | 90 days | Monthly + after every material change |
| Stripe events (in-flight) | Covered by Postgres snapshot — `stripe_events` is a table | 7 days (PITR) | With Postgres |

### Notes on the inventory

- PITR is the primary DR mechanism. Daily snapshots are a fallback
  for Supabase region outages that also affect WAL storage.
- The secrets manifest stores only secret *names*, not values. Re-fetch
  values from upstream (Stripe, Supabase) during restore — see
  `SECRETS_ROTATION.md`.
- Storage buckets are NOT in PITR. Logical deletes are only recoverable
  from the nightly S3 copy — worst-case RPO 24h.

---

## 3. Restore procedures

All procedures assume you have:

- `flyctl` authenticated as the ops user (`fly auth whoami`)
- Supabase dashboard access with owner role on the `spinr-prod` project
- `psql` / `pg_dump` ≥ 15 installed locally
- A secure workstation — these commands handle production secrets

### 3.a) Full Postgres restore to a new project (PITR)

Use when: the primary project is unrecoverable (region outage,
catastrophic data corruption, ransomware) OR a drill.

1. **Pick the target recovery timestamp.** For a corruption event,
   this is "1 minute before the bad migration ran" — check
   `docs/ops/incidents/` or `fly logs` for the exact time. For a
   drill, pick `now() - interval '10 min'`.

2. **Create a new Supabase project** named `spinr-prod-restore-YYYYMMDD`
   in the same region (`ca-central-1`). Use the same Pro plan tier so
   PITR / connection limits match.

3. **Restore from PITR:**
   - Supabase dashboard → source project → Database → Backups →
     **Restore to a new project** → enter the target project ID and
     recovery timestamp (UTC).
   - Supabase runs the restore async. Expected duration: 10-25 min
     for a DB under 20 GB. Watch the status panel.

4. **Verify data integrity on the restored project:**

   ```bash
   export RESTORE_DB_URL='postgres://postgres:<pw>@db.<ref>.supabase.co:5432/postgres'

   # Row counts on the tables that matter most
   psql "$RESTORE_DB_URL" -c "
     SELECT 'users' AS t, count(*) FROM users
     UNION ALL SELECT 'rides', count(*) FROM rides
     UNION ALL SELECT 'stripe_events', count(*) FROM stripe_events
     UNION ALL SELECT 'refresh_tokens', count(*) FROM refresh_tokens;
   "

   # Latest row timestamps — should be within RPO of the recovery point
   psql "$RESTORE_DB_URL" -c "
     SELECT max(created_at) FROM rides;
     SELECT max(created_at) FROM stripe_events;
   "
   ```

5. **Re-create service-role + anon keys** on the new project
   (Supabase auto-generates fresh ones — the old project's keys do
   NOT carry over). Capture them for step 3.c.

6. **Run migrations state check:**

   ```bash
   cd backend
   alembic -x url="$RESTORE_DB_URL" current
   ```

   Should match the `alembic current` of the production backend. If it
   does not, the restore landed at a point before a migration — decide
   whether to re-apply that migration or pick a later recovery point.

### 3.b) Partial restore of a single table (pg_dump --table)

Use when: a specific table was accidentally truncated or UPDATE'd
without a WHERE clause. Full project restore is overkill.

1. **Spin up a temp Supabase project at the bad timestamp** using
   steps 3.a.1–3.a.3. Label it `spinr-partial-restore-YYYYMMDD`.

2. **Dump the affected table from the temp project:**

   ```bash
   export TEMP_DB_URL='postgres://postgres:<pw>@db.<ref>.supabase.co:5432/postgres'
   export TABLE=rides   # or users, stripe_events, etc.

   pg_dump "$TEMP_DB_URL" \
     --table="public.${TABLE}" \
     --data-only \
     --column-inserts \
     --no-owner \
     --file="${TABLE}-restore-$(date +%F).sql"
   ```

3. **Review the dump** — always spot-check before loading into prod:

   ```bash
   wc -l ${TABLE}-restore-*.sql
   head -40 ${TABLE}-restore-*.sql
   ```

4. **Load into production** inside a transaction so you can abort:

   ```bash
   export PROD_DB_URL='postgres://postgres:<pw>@db.<prod-ref>.supabase.co:5432/postgres'

   psql "$PROD_DB_URL" <<'SQL'
   BEGIN;
   -- Stage into a scratch table first
   CREATE TABLE IF NOT EXISTS _restore_rides (LIKE rides INCLUDING ALL);
   \i rides-restore-2026-04-14.sql
   -- Merge only rows missing from the live table
   INSERT INTO rides
   SELECT * FROM _restore_rides r
   WHERE NOT EXISTS (SELECT 1 FROM rides WHERE rides.id = r.id);
   DROP TABLE _restore_rides;
   COMMIT;
   SQL
   ```

   Modify the `\i` step if the dump targets a different table name,
   and adapt the merge predicate to the table's primary key.

5. **Destroy the temp project** (Supabase dashboard → Settings →
   Danger zone) to stop the billing clock.

### 3.c) Re-point backend to a restored DB (Fly secret swap)

Use when: you have restored to a new Supabase project and need the
backend pointed at it. This is the step that actually ends the outage.

1. **Collect new connection details** from the restored project:
   - Project URL: `https://<new-ref>.supabase.co`
   - Service-role key (Project Settings → API)
   - Anon key (Project Settings → API) — only needed if the mobile
     apps also point to Supabase directly (currently they do not).

2. **Swap Fly secrets:**

   ```bash
   fly secrets set \
     SUPABASE_URL='https://<new-ref>.supabase.co' \
     SUPABASE_SERVICE_ROLE_KEY='eyJ...new...' \
     --app spinr-backend
   ```

   Fly rolls machines automatically. Watch `fly logs --app spinr-backend`
   for the startup banner and the `users table health check passed`
   line from `backend/core/lifespan.py`.

3. **Smoke-test against the live domain:**

   ```bash
   curl -sSf https://api.spinr.app/health | jq
   curl -sSf https://api.spinr.app/health/deep | jq
   ```

   Both must return 200. `health/deep` exercises Supabase, Redis, and
   background task freshness — if it's green, you've successfully
   re-pointed.

4. **Run the post-restore checklist** (section 4 — "Pass criteria").

5. **Archive the old project** rather than deleting it. Keep it
   read-only for 14 days so a post-mortem can cross-reference state.

---

## 4. Restore drill

Drilling the restore is the only way to know the numbers in section 1
are real. Untested backups are superstition.

### Schedule

- **Cadence:** quarterly (Q1: Feb, Q2: May, Q3: Aug, Q4: Nov — second
  Wednesday of the month, 10:00 ET).
- **Owner:** backend on-call for the month.
- **Scope:** alternating quarters run 3.a (full restore) vs. 3.b
  (partial restore). Run 3.c in every drill — the secret swap is the
  step most likely to rust.
- **Environment:** drill against a temp project. Never point the live
  `spinr-backend` Fly app at the drill project (use a throwaway Fly
  app `spinr-backend-drill` if you need to exercise 3.c end-to-end).

### Pass criteria

A drill passes when ALL of the following hold:

- [ ] Restored DB is reachable within **60 min** of starting the drill (RTO).
- [ ] Row counts in the 4 canary tables (`users`, `rides`,
      `stripe_events`, `refresh_tokens`) are within 1% of live at
      the recovery point.
- [ ] `alembic current` on the restored DB matches the expected
      migration hash.
- [ ] `/health/deep` returns 200 when `spinr-backend-drill` is pointed
      at the restored project.
- [ ] A scripted smoke test (`scripts/ops/smoke_test.sh`) against the
      drill backend passes: create user, request ride, cancel ride.
- [ ] Drill log written to `docs/ops/incidents/drill-YYYY-QN.md`
      using the template below.

Missing any criterion = drill fails. File a P2 to fix the gap
(usually a stale command in this doc, a missing IAM permission, or
an unrealistic RTO) and re-drill within 30 days.

### Drill log template

Copy into `docs/ops/incidents/drill-YYYY-QN.md`:

```markdown
# Restore drill — YYYY-QN

- **Date:** YYYY-MM-DD
- **Operator:** <name> (<github handle>)
- **Observer:** <name>
- **Scenario:** [ ] full restore (3.a) / [ ] partial table restore (3.b)
- **Target recovery point:** YYYY-MM-DDTHH:MM:SSZ
- **Start:** HH:MM ET
- **DB reachable:** HH:MM ET (duration: N min)
- **`/health/deep` green:** HH:MM ET (duration: N min — this is the RTO number)
- **Smoke test green:** HH:MM ET
- **Pass / fail:** <value>

## Row-count deltas (restored vs. expected-at-recovery-point)

| Table | Restored | Expected | Delta |
| --- | --- | --- | --- |
| users | | | |
| rides | | | |
| stripe_events | | | |
| refresh_tokens | | | |

## Issues found

1. ...

## Follow-ups

- [ ] ticket / PR link
```

---

## 5. Dependencies & gaps

Known issues that would impede a successful restore today. Each is
tracked in `docs/audit/production-readiness-2026-04/09_ROADMAP_CHECKLIST.md`.

- **Stripe webhook re-delivery.** After a full restore, Stripe will
  retry events it thinks went un-ack'd. The `stripe_events`
  idempotency table (audit P0-B2) dedupes on `event.id`, so
  double-processing is prevented — but events created between the
  recovery point and the restore completion will be replayed. Expected;
  monitor `spinr_stripe_queue_depth` for the post-restore spike.
- **Mobile DNS pinning.** `api.spinr.app` has a 300s TTL; do not raise
  it. Any domain / cert change during restore depends on this.
- **Refresh token invalidation.** If `JWT_SECRET` is rotated during
  restore, users on old builds without refresh tokens will re-login.
- **Supabase Storage PITR gap.** Bucket deletes recoverable only from
  the nightly S3 copy — 24h RPO. Revisit if product needs parity.
- **No cross-region replica.** Supabase cross-region is Enterprise
  only. Accepted risk while on Pro; revisit past $50k/mo revenue.
- **Secrets manifest not versioned.** Weekly export is overwritten.
  Always capture new values in a password manager before
  `fly secrets set`.

---

## 6. Related

- `docs/runbooks/api-down.md` — first stop when the API is unreachable;
  escalate into this doc only after ruling out transient failures.
- `docs/ops/SLOs.md` — RTO/RPO targets here are chosen to fit inside
  the API-availability SLO budget.
- `docs/ops/SECRETS_ROTATION.md` — the secret-swap half of 3.c reuses
  the same `fly secrets set` procedures.
- `docs/ops/logging.md` — where to look for the audit trail of a
  bad migration or deletion that triggered the restore.
