# Spinr — Database Architecture

> **Role:** Database Architect / DBA  
> **Audience:** Backend engineers, DevOps, auditors

---

## 1. Migration lineage

Every schema change since the audit is tracked in Alembic. The chain
is strictly linear — each revision has exactly one parent.

```
 [pre-audit manual SQL files]
           │
           │  alembic stamp head
           ▼
  0001_baseline  ──────────────────────────────────────────────────
  "Captures the existing schema as a known-good starting          │
   point. No DDL changes."                                        │
           │                                                      │
           ▼                                                      │
  0002_rls_policy_closure                                         │
  "Close the RLS gap on 19 tables in public schema.              │
   3 categories: owner-owned, sensitive, catalogue."             │
           │                                                      │
           ▼                                                      │
  0003_critical_indexes                                           │
  "4× CREATE INDEX CONCURRENTLY (no write stall):                │
   dispatcher queue, ride history ×2, OTP lookup."              │
           │                                                      │
           ▼                                                      │
  0004_stripe_event_queue_columns                                 │
  "Upgrade stripe_events from dedup table to                     │
   durable work-queue (attempt_count, last_error,               │
   next_attempt_at, partial index on unprocessed)."             │
           │                                                      │
           ▼                                                      │
  0005_bg_task_heartbeat                                          │
  "New table: bg_task_heartbeat (task_name PK,                   │
   last_run_at, last_status, last_error,                        │
   expected_interval_seconds)."                                 │
           │                                                      │
           ▼                                                      │
  0006_tos_acceptance_columns                                     │
  "Add accepted_tos_version, accepted_tos_at,                    │
   accepted_privacy_at to users (nullable)."                    │
           │                                                      │
           ▼                                                      │
  0007_ride_idempotency  ◄────────────────────────────── Phase 4 │
  "New table: ride_idempotency_keys (key PK,                     │
   rider_id, ride_id, response JSONB, created_at)."            │
           │                                                      │
           ▼                                                      │
  0008_gps_breadcrumbs_partition                                  │
  "Convert gps_breadcrumbs heap → PARTITION BY                   │
   RANGE (created_at). Monthly children, legacy                 │
   heap retained as rollback safety net."                       │
           │                                                      │
           ▼                                                      │
  0009_postgis_geography  ──────────────────────── current HEAD  │
  "Add geography(Point,4326) to drivers.location_geo,           │
   rides.pickup_geo, rides.dropoff_geo. Backfill triggers.     │
   GiST indexes. Enables ST_DWithin dispatch queries."         │
                                                                 │
  ─────────────────────────────────────────────────────────────┘
  All migrations: forward-only. No destructive downgrade().
  New columns are nullable or carry defaults.
```

---

## 2. Critical indexes

```
TABLE: rides
┌──────────────────────────────────────────────────────────────────┐
│  Index                        Type    Covers                     │
│  ─────────────────────────────────────────────────────────────  │
│  idx_rides_area_status_active  btree   WHERE status IN           │
│  (partial)                             ('searching','accepted',  │
│                                        'en_route','arrived',     │
│                                        'in_progress')            │
│                                        → dispatcher queue        │
│                                                                  │
│  idx_rides_driver_created      btree   (driver_id, created_at)   │
│                                        → driver ride history     │
│                                                                  │
│  idx_rides_rider_created       btree   (rider_id, created_at)    │
│                                        → rider ride history      │
│                                                                  │
│  (existing)  drivers_location_idx  GIST  (lat, lng)             │
│  + idx_drivers_available       btree   WHERE is_online=true      │
└──────────────────────────────────────────────────────────────────┘

TABLE: otp_records
┌──────────────────────────────────────────────────────────────────┐
│  idx_otp_records_phone_created  btree  (phone, created_at DESC)  │
│                                        → OTP lookup by phone     │
└──────────────────────────────────────────────────────────────────┘

TABLE: gps_breadcrumbs  (partitioned)
┌──────────────────────────────────────────────────────────────────┐
│  Index created on parent, propagated to all children:            │
│  (ride_id, created_at DESC)  →  breadcrumbs for a ride          │
│  (driver_id, created_at DESC) → driver location history          │
└──────────────────────────────────────────────────────────────────┘

TABLE: drivers  (PostGIS — revision 0009)
┌──────────────────────────────────────────────────────────────────┐
│  idx_drivers_location_geo  GiST  (location_geo)                  │
│                                  → ST_DWithin dispatch query     │
│                                    O(log n) instead of O(n)      │
└──────────────────────────────────────────────────────────────────┘

TABLE: ride_idempotency_keys
┌──────────────────────────────────────────────────────────────────┐
│  idx_ride_idempotency_rider    btree  (rider_id, created_at)     │
│  idx_ride_idempotency_created  btree  (created_at)  → retention  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. `gps_breadcrumbs` partitioning

This is the highest-ingest table: every driver emits a GPS point
every 3–5 seconds while online (~1 M rows/day at 10 active drivers;
~100 M/day at 1 000).

```
BEFORE (heap):
┌─────────────────────────────────┐
│  gps_breadcrumbs  (one heap)    │
│  ─────────────────────────────  │
│  row 1: 2025-01-01              │
│  row 2: 2025-01-01              │
│  ...                            │
│  row N: 2026-04-14  ← 90M rows  │
└─────────────────────────────────┘
Retention sweep: DELETE WHERE created_at < now()-90d LIMIT 500
→ 180,000 DELETE batches to clear one month
→ autovacuum pressure, table bloat


AFTER (monthly partitions):
┌─────────────────────────────────┐
│  gps_breadcrumbs  (parent)      │
│  PARTITION BY RANGE(created_at) │
└───┬────────────┬────────────────┘
    │            │            │
    ▼            ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ 2026_03  │ │ 2026_04  │ │ 2026_05  │  ← pre-provisioned
│ (prev)   │ │(current) │ │  (next)  │
└──────────┘ └──────────┘ └──────────┘
     │
     ▼  After 90 days:
  DETACH PARTITION gps_breadcrumbs_2026_03;
  DROP TABLE gps_breadcrumbs_2026_03;
  → O(1) metadata operation
  → zero autovacuum pressure
  → zero table bloat
```

**Monthly partition maintenance** (run by cron or ad-hoc):
```sql
SELECT ensure_gps_breadcrumbs_partition('2026-06-01'::date);
-- Creates gps_breadcrumbs_2026_06 if it doesn't exist.
-- Idempotent (CREATE TABLE IF NOT EXISTS).
```

---

## 4. PostGIS dispatch query evolution

```
BEFORE (Python Haversine — O(n)):

  every dispatcher tick:
  ┌────────────────────────────────────────────────────┐
  │  SELECT * FROM drivers WHERE is_online = true      │
  │  -- returns ALL online drivers (no spatial filter) │
  └────────────────────────────────────────────────────┘
       │
       ▼  Python loop
  for driver in all_online_drivers:  # could be 1000+
      dist = haversine(pickup, driver.lat, driver.lng)
      if dist < radius:
          candidates.append(driver)
  → O(n) per dispatch tick


AFTER (PostGIS ST_DWithin — O(log n)):

  ┌────────────────────────────────────────────────────┐
  │  SELECT *                                          │
  │  FROM   drivers                                    │
  │  WHERE  is_online = true                           │
  │    AND  ST_DWithin(                                │
  │           location_geo,                            │
  │           ST_MakePoint(:lng, :lat)::geography,     │
  │           :radius_metres                           │
  │         )                                          │
  │  ORDER BY location_geo <-> ST_MakePoint(...)       │
  │  LIMIT 10;                                         │
  └────────────────────────────────────────────────────┘
       │
       GiST index on location_geo: O(log n)
       All filtering inside Postgres: zero Python loop
       Zero per-row round-trips to the app
```

**Trigger keeps `location_geo` in sync automatically:**
```sql
CREATE OR REPLACE FUNCTION sync_driver_location_geo()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.lat IS NOT NULL AND NEW.lng IS NOT NULL THEN
    NEW.location_geo := ST_MakePoint(NEW.lng, NEW.lat)::geography;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Fires on every INSERT or UPDATE to drivers:
CREATE TRIGGER trg_sync_driver_location_geo
  BEFORE INSERT OR UPDATE ON drivers
  FOR EACH ROW EXECUTE FUNCTION sync_driver_location_geo();
```

Existing write paths (`PATCH /drivers/me`, ride-completion updates)
require **zero code changes** — the trigger handles it transparently.

---

## 5. Connection routing

```
                    ┌────────────────────┐
                    │   Application code │
                    │  (supabase-py)     │
                    └────────┬───────────┘
                             │  HTTPS (PostgREST REST API)
                             │  No direct TCP to Postgres
                             ▼
                    ┌────────────────────┐
                    │    PostgREST       │
                    │ (Supabase managed) │
                    └────────┬───────────┘
                             │  Internal
                             ▼
          ┌──────────────────────────────────────┐
          │         Supavisor Pooler             │
          │  (connection multiplexing)           │
          │                                      │
          │  session mode  :5432  ← migrations   │
          │  transaction   :6543  ← reads/writes │
          └──────────────────┬───────────────────┘
                             │
                             ▼
                    ┌────────────────────┐
                    │  PostgreSQL 15     │
                    │  (Supabase)        │
                    └────────────────────┘

Guard (backend/scripts/db_url.py):
  • Rejects db.<ref>.supabase.co (direct, bypasses pooler)
  • Warns if :6543 used for migrations (should be :5432)
  • Override: SPINR_ALLOW_DIRECT_DATABASE_URL=1
```

---

## 6. Data retention schedule

```
Table                   TTL         Sweep method
─────────────────────────────────────────────────────────────────
otp_records             24 hours    DELETE WHERE created_at < now()-1d
ride_idempotency_keys   24 hours    DELETE WHERE created_at < now()-1d
refresh_tokens (exp.)    7 days     DELETE WHERE expires_at < now()-7d
gps_breadcrumbs         90 days    DETACH + DROP PARTITION (monthly)
cancelled rides         90 days    DELETE WHERE status='cancelled'
chat_messages          180 days    DELETE WHERE created_at < now()-180d
stripe_events (proc.)   90 days    DELETE WHERE processed_at < now()-90d
billed rides             7 years    No automatic deletion (CRA req.)
─────────────────────────────────────────────────────────────────
Sweep runs: 02:00 UTC nightly  |  Batch size: 500 rows / DELETE
Monitored: bg_task_heartbeat.data_retention_loop
```

---

## 7. New tables added by the audit

### `bg_task_heartbeat`
```sql
CREATE TABLE bg_task_heartbeat (
  task_name               TEXT PRIMARY KEY,
  last_run_at             TIMESTAMPTZ,
  last_status             TEXT,           -- 'ok' | 'error'
  last_error              TEXT,
  expected_interval_secs  INTEGER
);
```
*Used by:* `GET /health/deep` — flags stale loops.

### `ride_idempotency_keys`
```sql
CREATE TABLE ride_idempotency_keys (
  key         TEXT PRIMARY KEY,       -- client-generated UUID
  rider_id    UUID NOT NULL,
  ride_id     UUID,                   -- NULL until ride created
  response    JSONB,                  -- NULL until ride created
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
*Used by:* `POST /rides` deduplication.

### `refresh_tokens`
```sql
CREATE TABLE refresh_tokens (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id),
  token_hash  TEXT NOT NULL UNIQUE,
  expires_at  TIMESTAMPTZ NOT NULL,
  revoked_at  TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
*Used by:* `POST /auth/refresh` / `POST /auth/logout`.

### `stripe_events` (upgraded)
```sql
-- Added columns:
attempt_count   INTEGER NOT NULL DEFAULT 0,
last_error      TEXT,
next_attempt_at TIMESTAMPTZ,
-- Partial index for the queue worker:
CREATE INDEX idx_stripe_events_queue
  ON stripe_events (next_attempt_at)
  WHERE processed_at IS NULL;
```

### `users` (columns added)
```sql
-- ToS acceptance trail:
accepted_tos_version  TEXT,
accepted_tos_at       TIMESTAMPTZ,
accepted_privacy_at   TIMESTAMPTZ,
-- Revocation:
token_version         INTEGER NOT NULL DEFAULT 0
```
