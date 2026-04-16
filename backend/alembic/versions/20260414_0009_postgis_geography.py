"""PostGIS geography columns for drivers + rides.

Revision ID: 0009_postgis_geography
Revises: 0006_tos_acceptance_columns
Create Date: 2026-04-14 00:00:00.000000+00:00

Phase 4.5 of the production-readiness audit (audit findings B10 / P5 /
P6: "Move surge/dispatch to PostGIS").

Note on down_revision
---------------------
At the time of writing, the intended ancestor is
``0008_gps_breadcrumbs_partition``. That migration has not landed on
``main`` yet, so this revision chains to the actual current head,
``0006_tos_acceptance_columns``. If 0007 / 0008 land before this is
merged, bump ``down_revision`` to match the new head before merging —
the migration itself is independent of the intervening schema changes.

What we're adding
-----------------
PostGIS geography columns + GiST indexes on the two tables that drive
every dispatch and surge computation:

* ``drivers.location_geo     geography(Point,4326)`` — the canonical
  location for "which drivers are within 5 km of this pickup". Backfilled
  from the existing ``drivers.lat`` / ``drivers.lng`` columns.
* ``rides.pickup_geo         geography(Point,4326)`` — surge demand
  counts and dispatcher pickup proximity. Backfilled from
  ``rides.pickup_lat`` / ``rides.pickup_lng``.
* ``rides.dropoff_geo        geography(Point,4326)`` — destination
  clustering, drop-off heatmaps, driver go-home filters. Backfilled
  from ``rides.dropoff_lat`` / ``rides.dropoff_lng``.

Each new column is shadowed by a ``BEFORE INSERT OR UPDATE`` trigger
that recomputes it from the float lat/lng columns. This lets all the
existing write paths (``UPDATE drivers SET lat=?, lng=?...`` and friends)
keep working without code changes — the triggers silently populate the
geography column on every write.

Why PostGIS
-----------
Current dispatch (``backend/routes/drivers.py::available_drivers_near``)
and surge (``backend/utils/surge_engine.py``) both fetch *all* online
drivers / open ride requests, then compute Haversine distances in Python.
That is O(n) per dispatcher tick and O(n) per rider pickup query — it
already shows up in p95 latency at the current driver count and will
fall over at fleet-scale.

``ST_DWithin(location_geo, ST_MakePoint(lng, lat)::geography, radius)``
backed by a GiST index is O(log n) and keeps the filter entirely in
Postgres — no round-trip of every online driver's row to the app.

Why we keep lat/lng
-------------------
1. Backwards compatibility: every read path today (mobile apps over the
   REST API, admin dashboard, analytics jobs) projects ``lat`` / ``lng``
   as floats. Dropping them would require a coordinated client rollout.
2. Write compatibility: the existing writers (``PATCH /drivers/me``,
   ride creation) are unchanged. Triggers keep the geography column in
   sync transparently.
3. Easy rollback: if PostGIS misbehaves, we drop the columns + indexes
   and fall back to the Python Haversine path with zero data loss.

Longitude first
---------------
``ST_MakePoint`` takes ``(x, y)`` which is ``(longitude, latitude)``.
This trips up everyone who stores coords as ``(lat, lng)`` tuples in
application code. Every backfill statement and every trigger below puts
**longitude first**. If you see ``ST_MakePoint(lat, lng)`` anywhere in
this file, that's a bug.

Why ``CREATE INDEX CONCURRENTLY``
---------------------------------
``drivers`` and ``rides`` are both write-hot. A blocking GiST build on
``rides`` (potentially millions of rows) would stall every ride write
for the duration of the index build. ``CONCURRENTLY`` lets writes
continue at the cost of two heap passes.

``CONCURRENTLY`` cannot run inside a transaction, so we use
``op.get_context().autocommit_block()`` — same pattern as
``20260414_0003_critical_indexes.py``.

Rollback
--------
``downgrade()`` drops the triggers, the indexes (concurrently), the
geography columns, and leaves the extension installed (other schemas
may depend on it). lat/lng are untouched so no data is lost.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_postgis_geography"
down_revision: Union[str, Sequence[str], None] = "0008_gps_breadcrumbs_partition"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# GiST indexes to build concurrently. (name, create-body).
GIST_INDEXES: list[tuple[str, str]] = [
    (
        "idx_drivers_location_geo",
        "ON public.drivers USING GIST (location_geo)",
    ),
    (
        "idx_rides_pickup_geo",
        "ON public.rides USING GIST (pickup_geo)",
    ),
    (
        "idx_rides_dropoff_geo",
        "ON public.rides USING GIST (dropoff_geo)",
    ),
]


def upgrade() -> None:
    # 1. Enable PostGIS. No-op if already installed (it lives in public,
    #    Supabase ships it preinstalled on managed Postgres).
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    # 2. Add geography columns. Nullable so existing rows without
    #    coordinates (rare, but drivers pre-first-location-ping exist)
    #    don't block the migration.
    op.execute(
        """
        ALTER TABLE public.drivers
          ADD COLUMN IF NOT EXISTS location_geo geography(Point, 4326);

        ALTER TABLE public.rides
          ADD COLUMN IF NOT EXISTS pickup_geo  geography(Point, 4326),
          ADD COLUMN IF NOT EXISTS dropoff_geo geography(Point, 4326);
        """
    )

    # 3. Backfill. Note: ST_MakePoint takes (lng, lat) — longitude first.
    #    We guard against NULLs so rows without coordinates (legacy data)
    #    just stay NULL rather than erroring.
    op.execute(
        """
        UPDATE public.drivers
           SET location_geo = ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography
         WHERE lat IS NOT NULL
           AND lng IS NOT NULL
           AND location_geo IS NULL;

        UPDATE public.rides
           SET pickup_geo = ST_SetSRID(ST_MakePoint(pickup_lng, pickup_lat), 4326)::geography
         WHERE pickup_lat IS NOT NULL
           AND pickup_lng IS NOT NULL
           AND pickup_geo IS NULL;

        UPDATE public.rides
           SET dropoff_geo = ST_SetSRID(ST_MakePoint(dropoff_lng, dropoff_lat), 4326)::geography
         WHERE dropoff_lat IS NOT NULL
           AND dropoff_lng IS NOT NULL
           AND dropoff_geo IS NULL;
        """
    )

    # 4. Sync triggers. These fire on every INSERT or UPDATE that touches
    #    the lat/lng columns and recompute the geography column. This is
    #    what preserves backwards compatibility: every existing writer
    #    keeps updating lat/lng only, and PostGIS gets kept in sync for
    #    free.
    #
    #    The trigger functions are idempotent: running them on a row
    #    that already has a correct location_geo produces the same value.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.drivers_sync_geo()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.lat IS NOT NULL AND NEW.lng IS NOT NULL THEN
                NEW.location_geo :=
                    ST_SetSRID(ST_MakePoint(NEW.lng, NEW.lat), 4326)::geography;
            ELSE
                NEW.location_geo := NULL;
            END IF;
            RETURN NEW;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_drivers_sync_geo ON public.drivers;
        CREATE TRIGGER trg_drivers_sync_geo
            BEFORE INSERT OR UPDATE OF lat, lng ON public.drivers
            FOR EACH ROW
            EXECUTE FUNCTION public.drivers_sync_geo();

        CREATE OR REPLACE FUNCTION public.rides_sync_geo()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.pickup_lat IS NOT NULL AND NEW.pickup_lng IS NOT NULL THEN
                NEW.pickup_geo :=
                    ST_SetSRID(ST_MakePoint(NEW.pickup_lng, NEW.pickup_lat), 4326)::geography;
            ELSE
                NEW.pickup_geo := NULL;
            END IF;

            IF NEW.dropoff_lat IS NOT NULL AND NEW.dropoff_lng IS NOT NULL THEN
                NEW.dropoff_geo :=
                    ST_SetSRID(ST_MakePoint(NEW.dropoff_lng, NEW.dropoff_lat), 4326)::geography;
            ELSE
                NEW.dropoff_geo := NULL;
            END IF;

            RETURN NEW;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_rides_sync_geo ON public.rides;
        CREATE TRIGGER trg_rides_sync_geo
            BEFORE INSERT OR UPDATE OF pickup_lat, pickup_lng, dropoff_lat, dropoff_lng
            ON public.rides
            FOR EACH ROW
            EXECUTE FUNCTION public.rides_sync_geo();
        """
    )

    # 5. GiST indexes. CONCURRENTLY cannot run in a transaction, so each
    #    index build gets its own autocommit block. See
    #    20260414_0003_critical_indexes.py for the same pattern.
    for name, body in GIST_INDEXES:
        with op.get_context().autocommit_block():
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} {body}")


def downgrade() -> None:
    # Drop triggers + functions first so no writer depends on the
    # geography columns while we tear them down.
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_drivers_sync_geo ON public.drivers;
        DROP TRIGGER IF EXISTS trg_rides_sync_geo   ON public.rides;
        DROP FUNCTION IF EXISTS public.drivers_sync_geo();
        DROP FUNCTION IF EXISTS public.rides_sync_geo();
        """
    )

    # Indexes in reverse order so the drop ordering mirrors the build.
    for name, _body in reversed(GIST_INDEXES):
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS public.{name}")

    op.execute(
        """
        ALTER TABLE public.rides
          DROP COLUMN IF EXISTS pickup_geo,
          DROP COLUMN IF EXISTS dropoff_geo;

        ALTER TABLE public.drivers
          DROP COLUMN IF EXISTS location_geo;
        """
    )

    # Leave the PostGIS extension installed. Other schemas / future
    # migrations may depend on it, and dropping an extension on
    # downgrade is almost always the wrong move.
