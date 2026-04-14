# Alembic migrations

This directory holds Alembic revisions for the spinr backend.

## TL;DR

* **All NEW schema changes go here.**
* Legacy raw-SQL migrations under [`backend/migrations/`](../migrations/README.md)
  are frozen — they remain the source of truth for the schema as it
  existed on the cutover date (2026-04-14), but do not add new files
  there.
* On every existing environment (prod, staging, shared dev), run
  [`alembic stamp 0001_baseline`](#one-time-cutover) exactly once.
  That tells Alembic "every schema change up to the cutover is already
  applied; resume from here."

## Why we split the history

spinr has no SQLAlchemy models; the production schema is authored as
raw SQL under `backend/migrations/*.sql` and applied by the small
in-house runner at `backend/scripts/run_migrations.py`. That runner
gave us idempotency + checksums + provenance, but nothing else —
no down-revisions, no branch resolution, no offline `--sql` emission.

Rather than backfill ~24 hand-authored .sql files into a single
Alembic revision (which would either diverge from reality or fail to
apply to already-migrated databases), we use the standard "adopt on
an existing project" pattern:

1. An empty baseline revision (`0001_baseline`) marks the cutover.
2. Operators `alembic stamp 0001_baseline` every existing database
   once, which inserts the revision id into `alembic_version` without
   running any SQL.
3. All subsequent schema changes are authored as Alembic revisions
   that descend from the baseline.
4. The legacy runner keeps working on fresh databases (CI, new
   deploys) exactly as it does today. Alembic and the runner do not
   fight over schema — the runner owns everything ≤ cutover, Alembic
   owns everything > cutover.

## Day-to-day workflow

### Prerequisites

```bash
export DATABASE_URL='postgres://postgres.<ref>:<service-role-pw>@aws-0-<region>.pooler.supabase.com:6543/postgres'
cd backend/
```

`alembic.ini` intentionally leaves `sqlalchemy.url` blank; `env.py`
pulls it from `DATABASE_URL` so CI, prod, and local dev all share
one knob. The env var must be set for every alembic command below
(including `alembic history`, which reads script files, because
`env.py` reads the env var unconditionally at the top).

### Creating a new revision

```bash
alembic revision -m "short_snake_case_description"
```

Filenames follow the template in `alembic.ini`:
`YYYYMMDD_<rev>_<slug>.py`. Edit the new file's `upgrade()` /
`downgrade()` functions; spinr has no ORM models so write the SQL
directly with `op.execute(...)` or the `op.*` helpers. Keep
`downgrade()` correct when it's reasonable — if it genuinely can't
be reversed (e.g. a data backfill), make `downgrade()` raise a
clear error.

### Applying pending revisions

```bash
alembic upgrade head          # apply everything up to the newest revision
alembic upgrade +1            # apply one revision
alembic upgrade head --sql    # dry-run: emit SQL to stdout, do not touch the DB
```

The last form is exactly what CI runs (`--sql` mode does not require
a live database and validates that every revision in the chain
compiles).

### Rolling back

```bash
alembic downgrade -1
alembic downgrade 0001_baseline   # back to the cutover
```

You cannot downgrade past `0001_baseline`. The legacy `.sql`
migrations are immutable and Alembic has no knowledge of them.

### Inspecting history

```bash
alembic history                # chain from base to head
alembic current                # revision currently applied to $DATABASE_URL
alembic show <revision>        # full source of one revision
```

## One-time cutover

For **each existing environment** (prod, staging, shared dev), run
exactly once:

```bash
export DATABASE_URL='…pooler.supabase.com:6543/postgres'
alembic stamp 0001_baseline
```

That creates `alembic_version` with `version_num = '0001_baseline'`.
From that point on, `alembic upgrade head` is a no-op until someone
adds a new revision.

Fresh environments (CI, a newly-provisioned prod from scratch) don't
need a stamp — run the legacy `.sql` migrations first, then
`alembic upgrade head`:

```bash
# 1. Apply the pre-cutover schema via the legacy runner.
python -m backend.scripts.run_migrations

# 2. Stamp the baseline (records "legacy schema is done, we are caught up").
alembic stamp 0001_baseline

# 3. Apply any post-cutover Alembic revisions.
alembic upgrade head
```

The order matters: the legacy runner creates the tables, then the
stamp tells Alembic not to re-run the (empty) baseline.

## CI validation

`.github/workflows/ci.yml` runs `alembic upgrade head --sql` on every
PR. That emits the full SQL for the chain without needing a database,
so it catches three common mistakes:

* A revision with a syntax error (import-time or rendering).
* A broken `down_revision` chain (cycle or missing parent).
* A revision that accidentally requires a live DB connection at
  import time (don't do that — keep imports lazy).

If that step fails, your revision does not merge.

## RLS reviewer guide

Row-Level Security is load-bearing for the "someone ships the anon key
in a mobile build" failure mode. When you add a table to `public`, you
**must** decide its client-role posture and write the policy in the same
Alembic revision that creates the table. Defaults below match what
`0002_rls_policy_closure.py` uses.

### Decision tree

1. **Will `anon` or `authenticated` ever read this table?**
   If no → `ENABLE ROW LEVEL SECURITY` + a single `deny_all` policy.
   Backend keeps working because it uses `service_role` which has
   `BYPASSRLS`.

2. **Is every row owned by one user?**
   → Add a `FOR SELECT TO authenticated USING (<owner>::text =
   auth.uid()::text)` carve-out on top of `deny_all`. Writes stay off
   the client path — all mutations flow through FastAPI.

3. **Is it an admin-curated reference catalogue that everyone can read?**
   → Add `FOR SELECT TO authenticated USING (true)` and register the
   table in the allow-list block of `backend/scripts/rls_audit.sql`
   (section 3) so the audit doesn't flag it as a footgun.

4. **Is it sensitive multi-party data (audit logs, admin notes,
   anything cross-user)?**
   → `deny_all` only. No client SELECT path. Reads happen server-side
   with its own authorisation.

### Running the audit

```bash
psql "$DATABASE_URL" -f backend/scripts/rls_audit.sql
```

A clean run returns zero rows in all three sections. Run it against
staging after every RLS-touching deploy, and against production as part
of the monthly security review. (It is not a CI gate yet because CI
does not run against a live DB; move it to a scheduled GitHub Action
with a read-only service role once that infrastructure exists.)

### Worked example

See `backend/alembic/versions/20260414_0002_rls_policy_closure.py` for
all three shapes applied in one revision (owner, sensitive, public-read).
The constants `OWNER_TABLES`, `SENSITIVE_TABLES`, and
`PUBLIC_READ_TABLES` at the top of that file are a readable index of
the current classification of every table in `public`.

## Gotchas

* **Do not edit applied revisions.** Alembic doesn't have a checksum
  table, but the legacy runner does for the pre-cutover files, and
  editing an Alembic revision after it's been applied in a shared
  environment will silently diverge staging from prod. If you need
  to amend, write a new revision.
* **No autogenerate.** spinr has no SQLAlchemy models; `target_metadata`
  is `None` in `env.py`. `alembic revision --autogenerate` is
  intentionally a no-op — always write the SQL by hand.
* **One head, one branch.** If you get a `Multiple heads are present`
  error, two revisions share the same `down_revision`. Resolve with
  `alembic merge heads` and explain the merge in the revision's
  docstring so future readers understand why it exists.
