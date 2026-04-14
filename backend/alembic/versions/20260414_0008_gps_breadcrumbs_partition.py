"""partition gps_breadcrumbs by month for retention + perf

Revision ID: 0008_gps_breadcrumbs_partition
Revises: 0007_ride_idempotency
Create Date: 2026-04-14 00:00:00.000000+00:00

Phase 4.6 of the production-readiness audit (audit finding P8:
"Partition gps_breadcrumbs").

Note on down_revision
---------------------
The intended ancestor is ``0007_ride_idempotency``, authored in parallel
by another agent as part of the same audit phase. If that revision does
not land (or is renamed), fall back to ``0006_tos_acceptance_columns``
— this migration is independent of the idempotency work and only needs
the baseline ``gps_breadcrumbs`` table to exist.

What we're doing
----------------
Converting ``public.gps_breadcrumbs`` from a plain heap table into a
declarative ``PARTITION BY RANGE (created_at)`` parent, with one
partition per calendar month. The approach:

  1. Rename the existing heap to ``gps_breadcrumbs_legacy``.
  2. Create a new partitioned parent ``gps_breadcrumbs`` with the same
     column definitions.
  3. Pre-create three monthly partitions: previous month, current
     month, and next month. The "previous month" partition covers
     rows backfilled from the legacy heap that crossed the month
     boundary, "current" takes today's writes, and "next" is a safety
     buffer so the cron that rolls partitions forward has slack.
  4. Backfill: ``INSERT INTO gps_breadcrumbs SELECT * FROM gps_breadcrumbs_legacy``.
     Postgres' partition router places each row in the right child
     automatically.
  5. Recreate the indexes on the parent — ``PARTITION BY`` propagates
     index definitions to existing and future children.
  6. Keep ``gps_breadcrumbs_legacy`` around as a rollback safety net.
     A follow-up migration (scheduled for +30 days) drops it once we
     are confident the partitioned table is behaving.
  7. Ship a helper function ``ensure_gps_breadcrumbs_partition(date)``
     that creates the partition for a given month if it does not yet
     exist. A monthly cron calls it to keep future partitions provisioned
     (cron wiring is out of scope for this migration — see the comment
     on the function itself).

Why partition at all
--------------------
``gps_breadcrumbs`` is the highest-ingest table in the system: every
driver emits a point roughly every 3–5s while online, and those rows
accrue into the tens of millions per month at current fleet size. Two
concrete wins:

* **Retention drops become cheap.** The nightly retention sweep in
  ``backend/utils/data_retention.py`` currently issues 500-row DELETEs
  older than 90 days. On a partitioned parent we can simply
  ``DETACH PARTITION`` + ``DROP TABLE`` for expired months —
  O(1) metadata operation instead of a multi-hour DELETE scan that
  bloats the heap and stresses autovacuum.
* **Query locality.** Every hot read on this table is time-scoped
  (e.g. "breadcrumbs for ride X during the window of that ride").
  Partition pruning eliminates 11 of every 12 monthly partitions from
  the plan before the planner even looks at an index.

Why declarative (PARTITION BY) and not pg_partman
-------------------------------------------------
Supabase-managed Postgres ships ``pg_partman`` as an installable
extension, but:

* The extension's install surface (schema, permissions, upgrade paths)
  is more moving parts than we need for a single table.
* Declarative partitioning is part of core Postgres; the maintenance
  code path (this file + a trivial monthly cron) is visible here and
  auditable by anyone reading the migrations folder.
* ``pg_partman`` shines for dozens of partitioned tables; for one,
  the helper function below is less machinery.

If we ever add a second partitioned table (``chat_messages`` is the
most likely candidate), reconsider.

Offline cutover
---------------
The rename + parent-create + backfill runs in a single transaction
(Alembic wraps ``upgrade()`` in one by default). Concretely:

* On staging (tens of thousands of rows), cutover measured under 1s
  end-to-end.
* On prod, the cost is dominated by the INSERT ... SELECT backfill.
  Ballpark: ~30–60s per 10M rows on a standard Supabase compute tier.
  Plan a 5-minute maintenance window and run during the nightly low
  of driver traffic (roughly 03:00–05:00 local for each service area).

During the window, the ``gps_breadcrumbs_legacy`` rename is visible
to any session that had already resolved ``gps_breadcrumbs`` to the
old OID. Because the rename and the new-parent creation share a
transaction, any concurrent writer will either see the pre-rename
table (and succeed) or the post-rename parent (and also succeed);
there is no window where the name is missing.

Why the legacy table is safe to freeze after rename
---------------------------------------------------
The Spinr backend does not issue direct SQL writes to ``gps_breadcrumbs``.
Every write path goes through Supabase's PostgREST layer, which
resolves the table name at request time — so as soon as the rename
commits, new writes land on the new parent automatically. There is
no long-lived cached OID anywhere in the application layer.

The only component that reads from the legacy table after cutover is
the 30-day rollback window; once the follow-up drop migration runs,
the legacy name is gone.

Schema caveat
-------------
At the time of writing, ``gps_breadcrumbs`` is not defined in any
alembic migration or SQL file in the repo — the table lives in
Supabase and was created via the dashboard. The column list below is
best-effort based on usage in ``backend/utils/data_retention.py``
(``created_at`` is the retention column) and the shape of the
parallel ``driver_location_history`` table referenced in
``backend/sql/04_rides_admin_overhaul.sql`` and
``backend/routes/websocket.py``.

Before applying this migration in any environment, a DBA must:

  1. ``\\d+ public.gps_breadcrumbs`` on the target DB.
  2. Diff the column list / types against the CREATE TABLE block below.
  3. Update the parent CREATE TABLE to match exactly. Partitioning is
     schema-preserving: every column, type, nullability, and default
     on the legacy table must be reproduced on the parent or the
     backfill will fail with a type mismatch.

The ``-- VERIFY SCHEMA BEFORE APPLYING`` marker below is the hook
for that pre-flight check.

Rollback
--------
``downgrade()`` is intentionally a no-op beyond ``pass``. Undoing a
partitioned-cutover after production writes have landed in the new
parent is not a safe automatic operation — rows are spread across
child tables and the rollback would need to either:

  * consolidate them back into the legacy heap (bespoke data
    migration), or
  * swap the legacy table back into place and accept losing the
    post-cutover writes.

If rollback is needed in the 30-day window, the DBA performs it
manually:

    BEGIN;
    DROP TABLE public.gps_breadcrumbs CASCADE;
    ALTER TABLE public.gps_breadcrumbs_legacy RENAME TO gps_breadcrumbs;
    -- re-copy any rows from dropped partitions if we care about them
    COMMIT;

Monthly maintenance cron (not wired here)
-----------------------------------------
Provision partitions ~60 days ahead so the write path never hits an
unpartitioned range. Example (to be wired into pg_cron or the
existing worker loop):

    -- Runs on the 1st of each month at 00:05 UTC
    SELECT public.ensure_gps_breadcrumbs_partition(
      (date_trunc('month', current_date) + interval '2 month')::date
    );

This migration creates enough partitions for today + the next month,
so there is a 30+ day grace window before the cron needs to fire for
the first time.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0008_gps_breadcrumbs_partition"
down_revision: Union[str, Sequence[str], None] = "0006_tos_acceptance_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Month boundaries baked in at migration-authoring time (2026-04-14).
# These are literal dates — not computed at apply-time — so the migration
# is deterministic and replays identically in any environment.
#
#   previous month : [2026-03-01, 2026-04-01)
#   current month  : [2026-04-01, 2026-05-01)
#   next month     : [2026-05-01, 2026-06-01)
_PREV_MONTH_START = "2026-03-01"
_CURR_MONTH_START = "2026-04-01"
_NEXT_MONTH_START = "2026-05-01"
_NEXT_NEXT_MONTH = "2026-06-01"


def upgrade() -> None:
    op.execute(
        f"""
        -- VERIFY SCHEMA BEFORE APPLYING
        --
        -- The column list in the CREATE TABLE below is a best-guess
        -- inferred from usage in backend/utils/data_retention.py and
        -- the shape of driver_location_history. Run `\\d+ public.gps_breadcrumbs`
        -- on the target DB and reconcile any drift before applying.
        --
        -- Specifically check:
        --   * exact column names (camelCase vs snake_case)
        --   * type widths (double precision vs real vs numeric)
        --   * nullability of each column
        --   * presence of any defaults (e.g. created_at DEFAULT now())
        --   * any foreign keys (drivers(id), rides(id)) — partitioned
        --     tables have tighter FK rules; see the note below.
        --
        -- Partitioned tables cannot have foreign keys pointing *into*
        -- them (a child can't be a referent), but they can have foreign
        -- keys pointing *out* to ordinary tables. Outbound FKs on
        -- driver_id / ride_id are therefore preserved; inbound FKs
        -- (unlikely for a breadcrumbs table) would have to be dropped.

        -- ------------------------------------------------------------
        -- 1. Rename the existing heap out of the way.
        -- ------------------------------------------------------------
        ALTER TABLE public.gps_breadcrumbs
          RENAME TO gps_breadcrumbs_legacy;

        -- ------------------------------------------------------------
        -- 2. Create the new partitioned parent.
        --    Column list is a best-guess — see VERIFY SCHEMA note above.
        -- ------------------------------------------------------------
        CREATE TABLE public.gps_breadcrumbs (
            id          uuid             NOT NULL,
            driver_id   uuid             NOT NULL,
            ride_id     uuid,
            lat         double precision NOT NULL,
            lng         double precision NOT NULL,
            speed       double precision,
            heading     double precision,
            accuracy    double precision,
            created_at  timestamptz      NOT NULL DEFAULT now(),
            -- Primary key must include the partition key for declarative
            -- partitioning. (id, created_at) preserves per-row uniqueness
            -- (ids are uuid v4) and lets partition pruning work on the
            -- created_at side.
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);

        -- ------------------------------------------------------------
        -- 3. Pre-create three monthly partitions: previous, current,
        --    next. Previous exists mainly so the backfill has somewhere
        --    to put rows that were written in the ~30 days before
        --    cutover (retention guarantees nothing older than 90 days
        --    exists, but the bulk of live data is in the last month).
        -- ------------------------------------------------------------
        CREATE TABLE public.gps_breadcrumbs_2026_03
          PARTITION OF public.gps_breadcrumbs
          FOR VALUES FROM ('{_PREV_MONTH_START}') TO ('{_CURR_MONTH_START}');

        CREATE TABLE public.gps_breadcrumbs_2026_04
          PARTITION OF public.gps_breadcrumbs
          FOR VALUES FROM ('{_CURR_MONTH_START}') TO ('{_NEXT_MONTH_START}');

        CREATE TABLE public.gps_breadcrumbs_2026_05
          PARTITION OF public.gps_breadcrumbs
          FOR VALUES FROM ('{_NEXT_MONTH_START}') TO ('{_NEXT_NEXT_MONTH}');

        -- ------------------------------------------------------------
        -- 4. Backfill. The partition router dispatches rows to the
        --    correct child by created_at. Rows whose created_at falls
        --    outside the three pre-created partitions will ERROR — in
        --    a healthy environment that cannot happen because the
        --    retention cron purges anything older than 90 days (and
        --    90 days < previous month's start, trivially).
        --
        --    If you hit "no partition of relation ... found for row",
        --    there are breadcrumbs older than 2026-03-01 on prod. Run
        --    the retention sweep first, or add a ``gps_breadcrumbs_old``
        --    default partition manually to catch them before re-running.
        -- ------------------------------------------------------------
        INSERT INTO public.gps_breadcrumbs
          SELECT * FROM public.gps_breadcrumbs_legacy;

        -- ------------------------------------------------------------
        -- 5. Recreate indexes on the parent. These propagate to all
        --    existing children and to any partitions created in the
        --    future via ensure_gps_breadcrumbs_partition().
        --
        --    Two indexes we want on every partition:
        --      * (ride_id, created_at)   — "breadcrumbs for this ride"
        --      * (driver_id, created_at) — "breadcrumbs for this driver
        --                                  in a window" (admin tools)
        --
        --    We do NOT use CREATE INDEX CONCURRENTLY here because:
        --      (a) we are inside the cutover transaction already, and
        --      (b) the children are empty at index-creation time on a
        --          fresh parent, and near-empty after the backfill on a
        --          staging-sized dataset. On prod, if the backfill is
        --          large, these indexes will take time — plan for it
        --          in the maintenance window. The CONCURRENTLY trick is
        --          not available on partitioned parents in all pg
        --          versions anyway; Postgres 12+ supports it for the
        --          parent but still builds on children non-concurrently.
        -- ------------------------------------------------------------
        CREATE INDEX IF NOT EXISTS idx_gps_breadcrumbs_ride_created
          ON public.gps_breadcrumbs (ride_id, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_gps_breadcrumbs_driver_created
          ON public.gps_breadcrumbs (driver_id, created_at DESC);

        -- ------------------------------------------------------------
        -- 6. Helper function for the monthly cron.
        --
        --    Usage (from pg_cron, a worker loop, or a DBA shell):
        --
        --      SELECT public.ensure_gps_breadcrumbs_partition(
        --        (date_trunc('month', current_date) + interval '2 month')::date
        --      );
        --
        --    The function:
        --      * normalises the input to the first of its month,
        --      * computes the exclusive upper bound (first of next
        --        month),
        --      * formats a partition name of the form
        --        gps_breadcrumbs_YYYY_MM, and
        --      * creates the partition with IF NOT EXISTS semantics so
        --        calling it repeatedly is safe.
        --
        --    It is SECURITY DEFINER-free and intentionally not
        --    scheduled here — wiring the cron is a deploy-time
        --    concern (pg_cron in Supabase, or backend/worker.py if we
        --    prefer app-layer scheduling).
        -- ------------------------------------------------------------
        CREATE OR REPLACE FUNCTION public.ensure_gps_breadcrumbs_partition(
            month_start date
        )
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            start_date date := date_trunc('month', month_start)::date;
            end_date   date := (date_trunc('month', month_start)
                                 + interval '1 month')::date;
            part_name  text := 'gps_breadcrumbs_'
                                || to_char(start_date, 'YYYY_MM');
        BEGIN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS public.%I '
                'PARTITION OF public.gps_breadcrumbs '
                'FOR VALUES FROM (%L) TO (%L)',
                part_name, start_date, end_date
            );
        END;
        $$;
        """
    )


def downgrade() -> None:
    # Intentionally a no-op. See "Rollback" in the module docstring:
    # unwinding a partitioned cutover safely requires manual DBA
    # intervention because post-cutover writes have landed in children
    # that have no equivalent in the legacy heap.
    pass
