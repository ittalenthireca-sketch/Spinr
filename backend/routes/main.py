"""
Main router aggregator
Import all route modules and combine them here
"""

import asyncio

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


@api_router.get("/health/deep")
async def health_deep():
    """Deep readiness probe — exercises downstream dependencies.

    Currently checks the Supabase DB. Returns 200 with per-component
    status on success, 503 if any required dependency is degraded.
    Wire this to synthetic monitors and k8s-style readiness probes,
    NOT to Fly's restart-on-fail liveness.
    """
    try:
        from db_supabase import run_sync
        from supabase_client import supabase
    except ImportError:  # pragma: no cover - import style varies by entrypoint
        from ..db_supabase import run_sync  # type: ignore
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

    payload = {
        "status": "healthy" if overall_ok else "degraded",
        "components": components,
    }
    return JSONResponse(status_code=200 if overall_ok else 503, content=payload)
