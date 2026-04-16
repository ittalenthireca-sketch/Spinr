"""rls policy closure — full coverage on public schema

Revision ID: 0002_rls_policy_closure
Revises: 0001_baseline
Create Date: 2026-04-14 00:00:00.000000+00:00

Phase 1.2 of the production-readiness audit (09_ROADMAP_CHECKLIST.md).

Goal
----
Migration 26 enabled RLS on the last six uncovered tables but intentionally
deferred policy authorship ("audit's P1 follow-up is to classify each table
by intended client access and emit the tight policies where appropriate").
This revision closes that gap for every table in ``public`` that has RLS
enabled but zero policies.

Why this is safe to ship without app-side changes
-------------------------------------------------
* The FastAPI backend talks to Postgres using ``SUPABASE_SERVICE_ROLE_KEY``;
  the ``service_role`` role has ``BYPASSRLS`` so these policies cannot
  break production traffic.
* No mobile client imports ``supabase-js`` today (``shared/config/supabase.ts``
  is an unused stub), so the ``authenticated`` role has no in-app callers
  to starve.  Policies are pure defence-in-depth: if a future app ever
  does use the anon key, every RLS-enabled table in ``public`` will
  already be deny-by-default with owner carve-outs where appropriate.

Policy model
------------
PostgreSQL RLS combines permissive policies with OR.  We exploit that:

1.  A baseline ``deny_all`` policy on every gap table:

        CREATE POLICY <t>_deny_all ON public.<t>
            FOR ALL TO anon, authenticated
            USING (false) WITH CHECK (false);

    This ensures that even if someone later writes an accidental
    ``FOR SELECT USING (true)``, the floor is still controlled.  (In
    PostgreSQL, a second permissive policy can only BROADEN access — so
    deny_all alone with no other policies is identical to "no policy
    at all" from the enforcement perspective; the value is documentary
    intent + the pair with the owner-SELECT policies below.)

2.  For user-owned tables, a narrow owner-read carve-out:

        CREATE POLICY <t>_select_own ON public.<t>
            FOR SELECT TO authenticated
            USING (<owner_col>::text = auth.uid()::text);

    Writes are NOT exposed to the client via RLS — all mutations continue
    to flow through the backend (service_role bypass).  This matches the
    existing pattern on tables like ``rides`` and ``wallets`` that already
    ship owner-SELECT policies.

3.  For public-read catalog tables (subscription_plans, quests, area_fees):

        CREATE POLICY <t>_public_read ON public.<t>
            FOR SELECT TO authenticated USING (true);

    These are admin-curated reference data that riders/drivers browse.

4.  For sensitive admin-only tables (driver_notes, driver_location_history,
    driver_activity_log, driver_daily_stats, wallet_transactions,
    loyalty_transactions): deny_all only, no carve-out.  Clients read these
    (if at all) via backend endpoints that do their own authorisation.

Idempotency
-----------
Every ``CREATE POLICY`` is wrapped in
``DROP POLICY IF EXISTS ... ; CREATE POLICY ...`` so re-runs against an
already-migrated database are safe.  ``ALTER TABLE ... ENABLE ROW LEVEL
SECURITY`` is a no-op if already enabled.

Downgrade
---------
Dropping policies is safe (tables remain RLS-enabled with the migration-26
posture).  We do NOT ``DISABLE ROW LEVEL SECURITY`` on downgrade — that
would be a net regression.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_rls_policy_closure"
down_revision: Union[str, Sequence[str], None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ----------------------------------------------------------------------
# Table classification (source: backend/migrations/*.sql + supabase_schema.sql)
# ----------------------------------------------------------------------

# (table, owner column) — user- or driver-owned tables.  Each gets deny_all
# + select_own(owner = auth.uid()).  The owner column resolves to the
# Supabase auth user id (text-compared to auth.uid()::text).
OWNER_TABLES: list[tuple[str, str]] = [
    ("saved_addresses", "user_id"),
    ("wallets", "user_id"),
    ("loyalty_accounts", "user_id"),
    ("fare_splits", "requester_id"),
    ("emergency_contacts", "user_id"),
    ("payouts", "driver_id"),
    ("bank_accounts", "driver_id"),
    ("driver_subscriptions", "driver_id"),
    ("quest_progress", "driver_id"),
]

# Sensitive tables — deny_all only; no client read path.  Backend reads
# through service_role and re-authorises at the HTTP boundary.
SENSITIVE_TABLES: list[str] = [
    "wallet_transactions",
    "loyalty_transactions",
    "fare_split_participants",
    "driver_notes",
    "driver_activity_log",
    "driver_daily_stats",
    "driver_location_history",
]

# Public-read reference catalogues — deny_all + public_read(SELECT true).
PUBLIC_READ_TABLES: list[str] = [
    "subscription_plans",
    "quests",
    "area_fees",
]


# ----------------------------------------------------------------------
# Upgrade: apply policies
# ----------------------------------------------------------------------


def _deny_all_sql(table: str) -> str:
    return f"""
    ALTER TABLE IF EXISTS public.{table} ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS {table}_deny_all ON public.{table};
    CREATE POLICY {table}_deny_all ON public.{table}
        FOR ALL TO anon, authenticated
        USING (false) WITH CHECK (false);
    """


def _select_own_sql(table: str, owner_col: str) -> str:
    return f"""
    DROP POLICY IF EXISTS {table}_select_own ON public.{table};
    CREATE POLICY {table}_select_own ON public.{table}
        FOR SELECT TO authenticated
        USING ({owner_col}::text = auth.uid()::text);
    """


def _public_read_sql(table: str) -> str:
    return f"""
    DROP POLICY IF EXISTS {table}_public_read ON public.{table};
    CREATE POLICY {table}_public_read ON public.{table}
        FOR SELECT TO authenticated
        USING (true);
    """


def upgrade() -> None:
    # Owner tables: deny floor + owner SELECT carve-out.
    for table, owner_col in OWNER_TABLES:
        op.execute(_deny_all_sql(table))
        op.execute(_select_own_sql(table, owner_col))

    # Sensitive tables: deny floor only — no client read path.
    for table in SENSITIVE_TABLES:
        op.execute(_deny_all_sql(table))

    # Public-read catalogue tables: deny floor + SELECT-true.
    for table in PUBLIC_READ_TABLES:
        op.execute(_deny_all_sql(table))
        op.execute(_public_read_sql(table))


# ----------------------------------------------------------------------
# Downgrade: drop the policies created here; leave RLS enabled.
# ----------------------------------------------------------------------


def downgrade() -> None:
    for table, _ in OWNER_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_select_own ON public.{table};")
        op.execute(f"DROP POLICY IF EXISTS {table}_deny_all   ON public.{table};")

    for table in SENSITIVE_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_deny_all ON public.{table};")

    for table in PUBLIC_READ_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_public_read ON public.{table};")
        op.execute(f"DROP POLICY IF EXISTS {table}_deny_all    ON public.{table};")
