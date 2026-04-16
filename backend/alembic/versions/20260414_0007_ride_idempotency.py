"""ride_idempotency_keys table for POST /rides dedupe

Revision ID: 0007_ride_idempotency
Revises: 0006_tos_acceptance_columns
Create Date: 2026-04-14 00:00:00.000000+00:00

Phase 4.4 of the production-readiness audit (audit finding F2:
"Offline/idempotent ride request + WS queue").

Why
---
The rider-app's ``createRide`` call is the single most user-visible
non-idempotent write in the system. On flaky LTE, the client may
retry a POST that already succeeded server-side — producing a
duplicate ride charge and a duplicate driver dispatch. A duplicate
cancel-on-rider's-side doesn't refund (different code path) so the
failure mode is very bad for both UX and support load.

The mobile client now mints a UUID per ride *attempt* and sends it
as the ``X-Idempotency-Key`` (and compatible ``Idempotency-Key``)
request header. Any retries of the same attempt reuse the key. The
backend looks up the key, and if it sees a hit, returns the cached
ride response instead of creating a second ride.

This migration adds the lookup table. The wiring in
``backend/routes/rides.py::create_ride`` is the matching code change.

Schema
------
* ``key``         — TEXT primary key. Client-generated v4 UUID in
                    canonical form. We store as TEXT (not UUID) so the
                    dedupe works even if a future client accidentally
                    generates a non-UUID token; the key is opaque to
                    the server.
* ``rider_id``    — UUID of the authenticated rider. We scope the
                    lookup to ``(key, rider_id)`` so one rider's key
                    collision can never surface another rider's ride.
* ``ride_id``     — UUID of the ride we created on the first call.
                    Nullable until we finish creating the ride
                    (race-safe: we UPSERT the key first, then write
                    ride_id, so a duplicate request mid-create
                    returns the in-flight ride once it lands).
* ``response``    — JSONB snapshot of the body we returned on the
                    first call. Returned verbatim on subsequent hits.
* ``created_at``  — timestamptz, used by the retention sweep.

Retention
---------
A 24h sweep purges keys older than that. The keys are write-once
from the client (one per attempt; the client drops the key as soon
as the ride transitions off "pending") so 24h is ample for any sane
retry cycle.

Safety / forward-compat
-----------------------
* No FK to ``rides(id)`` — if a ride gets hard-deleted (rare, e.g.
  fraud cleanup) the idempotency key row stays; it just returns the
  cached response snapshot, which is fine.
* ``created_at`` defaults to ``now()`` so old clients that talk to
  a new backend (and vice versa) still work without migration
  coordination.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision: str = "0007_ride_idempotency"
down_revision: Union[str, Sequence[str], None] = "0006_tos_acceptance_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.ride_idempotency_keys (
            key         TEXT        PRIMARY KEY,
            rider_id    UUID        NOT NULL,
            ride_id     UUID        NULL,
            response    JSONB       NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    # Support the scoped lookup used by the route (WHERE key=? AND rider_id=?).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ride_idempotency_rider
            ON public.ride_idempotency_keys (rider_id, created_at DESC);
        """
    )
    # Retention sweep scans by created_at; single-column index is enough.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ride_idempotency_created_at
            ON public.ride_idempotency_keys (created_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.ride_idempotency_keys;")
