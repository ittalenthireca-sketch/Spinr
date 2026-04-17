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

## 5. Quarterly restore drill — step-by-step procedure

This section is the operator runbook for executing the drill described in
section 4. Follow it in order. Do not skip steps to save time — the whole
point of the drill is to prove that no step has rotted.

### 5.1 Pre-drill checklist

Complete before opening a terminal:

- [ ] **Notify the team.** Post in `#spinr-ops`: "Starting QN restore drill.
      Staging Supabase project will be created and destroyed. No production
      impact expected."
- [ ] **Pick a staging environment.** The drill target is always a fresh
      Supabase project named `spinr-prod-restore-YYYYMMDD`. Never use the
      live `spinr-prod` or `spinr-staging` projects as the restore target.
- [ ] **Have a rollback plan ready.** If the drill procedure requires touching
      any shared resource (e.g., a staging Fly app), confirm you can revert
      to the previous config within 5 minutes. Dry-run `fly secrets list` on
      the drill app before starting.
- [ ] **Check your tooling.** Verify you have `psql` ≥ 15, `supabase` CLI
      ≥ 1.170, `flyctl`, and access to the Supabase dashboard with owner
      role on `spinr-prod`.
- [ ] **Record the start time.** The RTO clock starts now. Target: restored
      DB reachable + `/health/deep` green in ≤ 60 minutes.

### 5.2 Step-by-step restore to staging

**Step 1 — Export a point-in-time backup from the Supabase dashboard**

1. Open the Supabase dashboard and navigate to the `spinr-prod` project.
2. Database → Backups → Point-in-Time Recovery.
3. Pick a recovery timestamp of `now() - interval '10 min'` (UTC). Record
   the exact timestamp in the drill log.
4. Select "Restore to a new project" (not "Restore in place" — never run
   drills in place on `spinr-prod`).

For quarterly drills you may also use the daily snapshot instead of PITR.
Snapshot-based restores take roughly the same time and exercise the same
Supabase restore path.

**Step 2 — Create a fresh Supabase project (staging clone)**

1. In the Supabase dashboard, create a new project:
   - Name: `spinr-prod-restore-YYYYMMDD`
   - Region: `ca-central-1` (same region as production to match latency
     characteristics).
   - Plan: Pro (required for PITR and connection limits that match prod).
2. Note the new project's **reference ID** (`<drill-ref>`) and wait for the
   project to finish provisioning (typically 1-2 minutes).
3. Enter the project URL and target project ID into the PITR restore dialog
   from Step 1. Confirm and start the restore.

Expected restore duration: 10-25 minutes for a DB under 20 GB.
Watch the status panel in the Supabase dashboard.

**Step 3 — Restore schema and data**

The Supabase PITR restore is fully managed — no manual `pg_restore` invocation
is needed when using "Restore to a new project" in the dashboard. The restored
project will contain the schema and data at the chosen recovery point.

If you are testing a manual restore path (e.g., from an off-site S3 dump), use:

```bash
export DRILL_DB_URL='postgres://postgres:<pw>@db.<drill-ref>.supabase.co:5432/postgres'

# Restore schema first, then data
pg_restore \
  --dbname="$DRILL_DB_URL" \
  --no-owner \
  --no-privileges \
  --verbose \
  spinr-prod-YYYYMMDD.dump
```

For the standard managed-restore path, skip this step and proceed to Step 4.

**Step 4 — Verify: run smoke tests against the restored DB**

```bash
export DRILL_DB_URL='postgres://postgres:<pw>@db.<drill-ref>.supabase.co:5432/postgres'

# 4a. Confirm connectivity
psql "$DRILL_DB_URL" -c "SELECT now();"

# 4b. Alembic migration state — must match production
cd backend
alembic -x url="$DRILL_DB_URL" current
# Expected: the same revision hash as `alembic current` on spinr-prod.

# 4c. Run the backend smoke test against a throwaway Fly app
#     (spinr-backend-drill) pointed at the drill DB.
#     See section 3.c for the Fly secret-swap procedure.
fly secrets set \
  SUPABASE_URL="https://<drill-ref>.supabase.co" \
  SUPABASE_SERVICE_ROLE_KEY="<drill-service-role-key>" \
  --app spinr-backend-drill

fly logs --app spinr-backend-drill &   # watch for startup banner
sleep 20

curl -sSf https://spinr-backend-drill.fly.dev/health | jq
curl -sSf https://spinr-backend-drill.fly.dev/health/deep | jq

# 4d. Scripted smoke scenario (create user, request ride, cancel ride)
bash scripts/ops/smoke_test.sh https://spinr-backend-drill.fly.dev
```

Both `/health` and `/health/deep` must return 200. `smoke_test.sh` must exit 0.

**Step 5 — Verify: check row counts match original snapshot**

```bash
export DRILL_DB_URL='postgres://postgres:<pw>@db.<drill-ref>.supabase.co:5432/postgres'
export PROD_DB_URL='postgres://postgres:<pw>@db.<prod-ref>.supabase.co:5432/postgres'

# Row counts on canary tables
psql "$DRILL_DB_URL" -c "
  SELECT 'users'         AS t, count(*) FROM users
  UNION ALL
  SELECT 'rides',            count(*) FROM rides
  UNION ALL
  SELECT 'stripe_events',    count(*) FROM stripe_events
  UNION ALL
  SELECT 'refresh_tokens',   count(*) FROM refresh_tokens;
"

# Compare against production at the recovery point.
# Delta should be ≤ 1% for each table (some rows created after the
# recovery timestamp will be missing — that is expected and correct).
```

Record the row counts in the drill log template (section 4).

**Step 6 — Document the result**

1. Record pass/fail, elapsed time, and any issues in
   `docs/ops/incidents/drill-YYYY-QN.md` using the template in section 4.
2. Update the drill log table at the bottom of this section.
3. **Destroy the drill project:** Supabase dashboard → drill project →
   Settings → Danger zone → Delete project. This stops billing immediately.
4. **Revert the Fly app:** restore `spinr-backend-drill` to its pre-drill
   secrets (or pause the app if it is only used for drills):
   ```bash
   fly apps suspend spinr-backend-drill
   ```
5. Post the result in `#spinr-ops`: "QN restore drill complete. Result: PASS/FAIL.
   RTO achieved: N min. Details: link-to-drill-doc."

### 5.3 Success criteria

A drill passes when ALL of the following hold:

- [ ] Restored DB is reachable within **60 minutes** of the drill start (RTO).
- [ ] Row counts in `users`, `rides`, `stripe_events`, `refresh_tokens` are
      within **1%** of expected at the recovery point.
- [ ] `alembic current` on the restored DB matches the production migration hash.
- [ ] `/health` and `/health/deep` both return **200** from `spinr-backend-drill`.
- [ ] `smoke_test.sh` exits **0** (create user, request ride, cancel ride all succeed).
- [ ] Drill log written to `docs/ops/incidents/drill-YYYY-QN.md`.
- [ ] Drill project destroyed and billing stopped before the drill log is filed.

Missing any criterion = **drill fails**.

### 5.4 Failure escalation

If the drill fails:

1. **Open an incident** in `docs/ops/incidents/drill-YYYY-QN.md` with status
   `FAIL` and a description of which criterion was not met.
2. **Assign an owner** (the backend on-call for the month) to diagnose and
   fix the root cause. Common causes:
   - Stale command (flag renamed, CLI version bump) — update this doc.
   - Missing IAM permission or revoked token — rotate the credential.
   - Supabase PITR disabled or plan downgraded — restore the Pro plan.
   - RTO exceeded — profile where time was lost; reduce via automation.
3. **File a P2** in the issue tracker linking the drill doc. Label it
   `dr-failure` and `p2`.
4. **Re-drill within 1 week** after the fix is merged. The re-drill must
   cover the same scenario as the failed drill (not a lighter one).
5. If the re-drill also fails, escalate to P1 and convene a post-mortem
   within 48 hours.

Do not mark the quarterly slot as complete until a drill passes.

### 5.5 Drill log

| Date | Operator | Duration (min) | Scenario | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| — | — | — | — | pending | No drills run yet |

---

## 6. Dependencies & gaps  <!-- was section 5 before the drill runbook was added -->

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

## 7. Related

- `docs/runbooks/api-down.md` — first stop when the API is unreachable;
  escalate into this doc only after ruling out transient failures.
- `docs/ops/SLOs.md` — RTO/RPO targets here are chosen to fit inside
  the API-availability SLO budget.
- `docs/ops/SECRETS_ROTATION.md` — the secret-swap half of 3.c reuses
  the same `fly secrets set` procedures.
- `docs/ops/logging.md` — where to look for the audit trail of a
  bad migration or deletion that triggered the restore.
