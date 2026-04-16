"""critical indexes for hot-path queries

Revision ID: 0003_critical_indexes
Revises: 0002_rls_policy_closure
Create Date: 2026-04-14 00:00:00.000000+00:00

Phase 1.4 of the production-readiness audit (09_ROADMAP_CHECKLIST.md,
row P4 in 07_PERFORMANCE_SCALABILITY.md).

What we're adding
-----------------
Four targeted btree indexes on tables that carry the lion's share of
application traffic:

1. ``rides (service_area_id, status)`` partial on active statuses —
   primary index for the dispatcher queue scan.
2. ``rides (driver_id, created_at DESC)`` — earnings history / "my
   rides" on the driver app.
3. ``rides (rider_id, created_at DESC)`` — "My trips" list on the
   rider app.
4. ``otp_records (phone, created_at DESC)`` — OTP verification +
   rate-limit window lookup.

What the audit listed that we didn't add (and why)
--------------------------------------------------
* ``payments WHERE ride_id=?`` — there is no ``payments`` table in
  spinr. Payment intent / status fields live inline on ``rides``
  (columns ``payment_intent_id``, ``payment_status``). No index
  change required.
* ``notifications WHERE user_id=? AND read=false`` — there is no
  ``notifications`` table either. Push delivery uses ``push_tokens``
  which already carries ``(user_id, platform)`` as a UNIQUE index.
* ``gps_breadcrumbs WHERE ride_id=? ORDER BY ts`` — the table is
  actually ``driver_location_history`` and it already ships
  ``idx_dlh_ride ON (ride_id, timestamp)``.
* ``drivers WHERE is_online AND is_available`` + ``ST_DWithin`` —
  already covered by ``drivers_location_idx`` (GIST on
  ``location``) plus ``idx_drivers_available (is_available,
  is_online)``.

So the "7-query list" in the audit maps to four net-new indexes once
cross-checked against what's actually in the schema.

Why ``CREATE INDEX CONCURRENTLY``
---------------------------------
The tables being indexed are write-hot (``rides`` fires on every ride
state transition; ``otp_records`` on every phone-auth attempt). A
non-concurrent index build takes an ACCESS EXCLUSIVE lock and stalls
every write until it completes. ``CONCURRENTLY`` lets writes proceed
in parallel at the cost of two passes over the heap and a slightly
longer build time.

Gotchas
-------
* ``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction. We
  therefore wrap each statement in ``op.get_context().autocommit_block()``
  which commits the surrounding Alembic transaction, issues the
  DDL under autocommit, then reopens a transaction for the next step.
* If the build fails mid-way (e.g. statement timeout, deadlock), the
  resulting index is marked INVALID and must be dropped manually
  before re-running this migration.  Query the catalog:

      SELECT indexrelid::regclass
        FROM pg_index
       WHERE NOT indisvalid;

  then ``DROP INDEX CONCURRENTLY <name>;`` and re-run.
* ``IF NOT EXISTS`` makes the CREATE itself idempotent on success —
  we still use it as a belt-and-suspenders guard.

Downgrade policy
----------------
Drop the indexes concurrently on downgrade so that rolling back doesn't
cause a write stall either.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_critical_indexes"
down_revision: Union[str, Sequence[str], None] = "0002_rls_policy_closure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (index_name, table, create_body) — create_body is everything after
# "CREATE INDEX CONCURRENTLY IF NOT EXISTS <name> " so we can emit the
# matching DROP without duplicating the predicate.
INDEXES: list[tuple[str, str, str]] = [
    (
        "idx_rides_area_status_active",
        "rides",
        # Partial index: only "in-flight" statuses are interesting to
        # the dispatcher. Keeps the index small even as completed rides
        # accumulate into the millions.
        "ON public.rides (service_area_id, status) WHERE status IN ('searching', 'driver_assigned')",
    ),
    (
        "idx_rides_driver_created",
        "rides",
        "ON public.rides (driver_id, created_at DESC)",
    ),
    (
        "idx_rides_rider_created",
        "rides",
        "ON public.rides (rider_id, created_at DESC)",
    ),
    (
        "idx_otp_records_phone_created",
        "otp_records",
        "ON public.otp_records (phone, created_at DESC)",
    ),
]


def upgrade() -> None:
    # CONCURRENTLY cannot run inside a transaction; autocommit_block()
    # commits Alembic's transaction, runs the DDL standalone, then
    # reopens a fresh transaction for the next iteration.
    for name, _table, body in INDEXES:
        with op.get_context().autocommit_block():
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} {body}")


def downgrade() -> None:
    # Reverse order so that any cross-dependencies (none today, but
    # future revisions may add some) unwind cleanly.
    for name, _table, _body in reversed(INDEXES):
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS public.{name}")
