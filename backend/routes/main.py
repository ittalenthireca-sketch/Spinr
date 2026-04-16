"""
Main router aggregator
Import all route modules and combine them here
"""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from loguru import logger

from .admin import router as admin_router
from .auth import router as auth_router
from .corporate_accounts import router as corporate_accounts_router
from .drivers import router as drivers_router
from .rides import router as rides_router

# Create the main API router
api_router = APIRouter()

# Include all sub-routers
api_router.include_router(auth_router)
api_router.include_router(rides_router)
api_router.include_router(drivers_router)
api_router.include_router(admin_router)
api_router.include_router(corporate_accounts_router)


# Health check and root endpoints
@api_router.get("/")
async def root():
    return {"message": "Spinr API", "version": "1.0.0"}


@api_router.get("/health")
async def health_check():
    """Shallow liveness probe.

    Intentionally does NOT touch the database. Fly.io (and most load
    balancers) will kill the machine if this endpoint flaps, and a
    transient DB blip should not trigger a restart. Use /health/deep
    for readiness / dependency checks.
    """
    return {"status": "healthy"}


# ── Heartbeat freshness (Phase 1.6 / audit T15) ──────────────────────
# Every background loop writes into bg_task_heartbeat on each tick. A
# row whose last_run_at is older than `STALE_MULTIPLIER * expected_interval`
# is treated as a liveness failure: the worker process is running but
# a specific loop has wedged and user-visible side effects (scheduled
# dispatch, surge recalc, Stripe dispatch, etc.) are missing.
#
# 2x is the default recommended by the audit (doc T15) — tolerates
# one missed tick so a transient slow DB doesn't spuriously flip the
# probe, but flags a loop that missed two intervals in a row.
STALE_MULTIPLIER = 2


@api_router.get("/health/deep")
async def health_deep():
    """Deep readiness probe — exercises downstream dependencies.

    Currently checks the Supabase DB and the freshness of each
    background-task heartbeat. Returns 200 with per-component status
    on success, 503 if any required dependency is degraded or any
    background loop has missed >2 intervals. Wire this to synthetic
    monitors and k8s-style readiness probes, NOT to Fly's
    restart-on-fail liveness.
    """
    try:
        from db_supabase import fetch_bg_task_heartbeats, run_sync
        from supabase_client import supabase
    except ImportError:  # pragma: no cover - import style varies by entrypoint
        from ..db_supabase import fetch_bg_task_heartbeats, run_sync  # type: ignore
        from ..supabase_client import supabase  # type: ignore

    components: dict[str, str] = {}
    overall_ok = True

    # --- Supabase (DB) -----------------------------------------------------
    if supabase is None:
        components["db"] = "unconfigured"
        overall_ok = False
    else:
        try:
            # 2s cap — the probe should fail fast rather than tying up
            # the readiness check while Supabase is degraded.
            await asyncio.wait_for(
                run_sync(lambda: supabase.table("users").select("id").limit(1).execute()),
                timeout=2.0,
            )
            components["db"] = "ok"
        except TimeoutError:
            logger.warning("/health/deep: DB probe timed out after 2s")
            components["db"] = "timeout"
            overall_ok = False
        except Exception as e:
            logger.warning(f"/health/deep: DB probe failed: {e}")
            components["db"] = "error"
            overall_ok = False

    # --- Background task heartbeats (T15) ---------------------------------
    # Empty result ("no rows yet") is treated as healthy — a freshly
    # deployed worker may not have completed its first tick yet, and
    # hard-coding "must have 6 rows" would couple this endpoint to the
    # exact number of background loops, which would silently rot.
    # Operators get a separate signal (the `workers` dict is empty) so
    # synthetic monitors can alert on that case explicitly if they want.
    workers: dict[str, dict[str, object]] = {}
    try:
        hb_rows = await asyncio.wait_for(fetch_bg_task_heartbeats(), timeout=2.0)
    except TimeoutError:
        logger.warning("/health/deep: heartbeat fetch timed out after 2s")
        hb_rows = []
        components["workers"] = "timeout"
        overall_ok = False
    except Exception as e:  # noqa: BLE001
        logger.warning(f"/health/deep: heartbeat fetch failed: {e}")
        hb_rows = []
        components["workers"] = "error"
        overall_ok = False

    if hb_rows:
        now = datetime.now(timezone.utc)
        any_stale = False
        for row in hb_rows:
            name = str(row.get("task_name") or "unknown")
            last_run_raw = row.get("last_run_at")
            interval = int(row.get("expected_interval_seconds") or 0)
            last_status = str(row.get("last_status") or "ok")

            last_run: datetime | None = None
            if isinstance(last_run_raw, str):
                try:
                    last_run = datetime.fromisoformat(last_run_raw.replace("Z", "+00:00"))
                    if last_run.tzinfo is None:
                        last_run = last_run.replace(tzinfo=timezone.utc)
                except ValueError:
                    last_run = None

            if last_run is None or interval <= 0:
                # Row is malformed — treat conservatively as stale so
                # operators notice and fix it rather than having it
                # silently bypass the liveness check.
                workers[name] = {"status": "unknown"}
                any_stale = True
                continue

            age = (now - last_run).total_seconds()
            stale = age > STALE_MULTIPLIER * interval
            workers[name] = {
                "status": last_status,
                "age_seconds": int(age),
                "expected_interval_seconds": interval,
                "stale": stale,
            }
            if stale:
                any_stale = True

        components["workers"] = "stale" if any_stale else "ok"
        if any_stale:
            overall_ok = False
    elif "workers" not in components:
        # No heartbeat rows and no fetch error — tolerate (fresh deploy
        # or self-hosted without the worker process running).
        components["workers"] = "empty"

    payload: dict[str, object] = {
        "status": "healthy" if overall_ok else "degraded",
        "components": components,
    }
    if workers:
        payload["workers"] = workers
    return JSONResponse(status_code=200 if overall_ok else 503, content=payload)
