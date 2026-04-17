import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

try:
    from core.config import settings
    from core.logging_config import configure_logging
    from db_supabase import run_sync
except ImportError:  # pragma: no cover - import style varies by entrypoint
    from ..core.config import settings  # type: ignore
    from ..core.logging_config import configure_logging  # type: ignore
    from ..db_supabase import run_sync  # type: ignore

# Configure structured logging before any other code emits a log line.
configure_logging()

from supabase_client import supabase  # noqa: E402


def _should_run_background_tasks() -> bool:
    """Decide whether this API process should own the background loops.

    We key off Fly's FLY_PROCESS_GROUP env var (automatically injected
    on Fly machines per the [processes] block in fly.toml):

      * FLY_PROCESS_GROUP=app     → a dedicated worker machine owns
                                    the loops; skip here to avoid
                                    double-execution.
      * FLY_PROCESS_GROUP=worker  → the worker entrypoint owns the
                                    loops; skip here too (and this
                                    branch shouldn't be hit — the
                                    worker doesn't mount FastAPI).
      * unset / anything else     → legacy single-process mode (local
                                    dev, single-service Render, etc.).
                                    Run the loops in-process for
                                    backwards compat.

    SPINR_BG_TASKS=force can be set to override and always run
    (useful for ad-hoc scripts); SPINR_BG_TASKS=off to force-skip.
    """
    override = os.environ.get("SPINR_BG_TASKS", "").strip().lower()
    if override == "force":
        return True
    if override == "off":
        return False
    role = os.environ.get("FLY_PROCESS_GROUP", "").strip().lower()
    if role in ("app", "worker"):
        return False
    return True


# Global database reference accessible via app state
async def init_database():
    """Initialize database connection and verify it is reachable.

    The supabase-py client is synchronous; we route the health-check probe
    through run_sync() to avoid blocking the event loop. In production,
    any failure raises — Uvicorn will refuse to serve traffic. In development
    we log a warning so local work without Supabase still boots.
    """
    if not supabase:
        msg = "Supabase client not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing)"
        if settings.ENV.lower() == "production":
            raise RuntimeError(msg)
        logger.warning(f"{msg} — continuing in {settings.ENV} mode")
        return None

    # Active health check — one trivial read against a table that always exists.
    # The `users` table is part of the core schema; a failure here means either
    # the service role key is invalid, the DB is unreachable, or the schema
    # has not been applied.
    try:
        await run_sync(lambda: supabase.table("users").select("id").limit(1).execute())
        logger.info("Supabase connection verified")
    except Exception as e:
        logger.error(f"Supabase health check failed: {e}")
        if settings.ENV.lower() == "production":
            raise
        logger.warning(f"Continuing in {settings.ENV} mode despite health-check failure")

    return supabase


async def cleanup_database(db):
    """Cleanup database connections on shutdown."""
    try:
        # Add any cleanup logic here if needed
        logger.info("Database cleanup completed")
    except Exception as e:
        logger.error(f"Database cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events"""
    # Initialize database
    logger.info("Initializing database connection...")
    try:
        db = await init_database()
        app.state.db = db
        logger.info("Database initialized and attached to app state")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Start background tasks
    import asyncio

    # Track task handles so we can cancel them cleanly on shutdown.
    background_tasks: list[asyncio.Task] = []

    def _spawn(name: str, coro_factory):
        try:
            task = asyncio.create_task(coro_factory(), name=name)
            background_tasks.append(task)
            logger.info(f"Started background task: {name}")
        except Exception as e:
            logger.warning(f"Failed to start background task {name}: {e}")

    # Background loops run either here (legacy single-process mode) or
    # in the dedicated worker process (when FLY_PROCESS_GROUP is set).
    # See backend/worker.py and fly.toml [processes].
    if _should_run_background_tasks():
        # G5: Subscription expiry warning — checks every 6h for subscriptions
        # expiring within 24h and sends push notifications.
        try:
            from routes.drivers import check_expiring_subscriptions

            _spawn("subscription_expiry (6h)", check_expiring_subscriptions)
        except Exception as e:
            logger.warning(f"Failed to import subscription expiry checker: {e}")

        # Automated surge pricing — recalculates demand/supply ratio every 2 min
        # and updates service_areas.surge_multiplier for auto-managed areas.
        try:
            from utils.surge_engine import surge_recalculation_loop

            _spawn("surge_engine (2min)", surge_recalculation_loop)
        except Exception as e:
            logger.warning(f"Failed to import surge pricing engine: {e}")

        # Scheduled ride dispatcher — checks every 60s for rides due for dispatch
        # and sends 10-minute reminder notifications.
        try:
            from utils.scheduled_rides import scheduled_ride_dispatcher_loop

            _spawn("scheduled_dispatcher (60s)", scheduled_ride_dispatcher_loop)
        except Exception as e:
            logger.warning(f"Failed to import scheduled ride dispatcher: {e}")

        # Payment retry — retries failed Stripe payments every 5 minutes
        try:
            from utils.payment_retry import payment_retry_loop

            _spawn("payment_retry (5min)", payment_retry_loop)
        except Exception as e:
            logger.warning(f"Failed to import payment retry service: {e}")

        # Document expiry alerts — notifies drivers about expiring docs every 12h
        try:
            from utils.document_expiry import document_expiry_loop

            _spawn("document_expiry (12h)", document_expiry_loop)
        except Exception as e:
            logger.warning(f"Failed to import document expiry checker: {e}")

        # Stripe event queue drainer (Phase 1.5) — the webhook handler
        # only persists events and returns 200; this loop runs the
        # business-logic dispatch out-of-band. Registered here for
        # legacy single-process deploys; on Fly the dedicated worker
        # process runs it instead (see worker.py).
        try:
            from utils.stripe_worker import stripe_event_worker_loop

            _spawn("stripe_event_worker (5s)", stripe_event_worker_loop)
        except Exception as e:
            logger.warning(f"Failed to import stripe event worker: {e}")
    else:
        role = os.environ.get("FLY_PROCESS_GROUP", "unknown")
        logger.info(
            f"Skipping in-process background tasks (FLY_PROCESS_GROUP={role}); "
            f"they are owned by the dedicated worker process."
        )

    # Phase 2.3c — metrics refresh always runs on the API process,
    # regardless of role. The /metrics endpoint served by this process
    # needs fresh snapshot gauges (stripe_queue_depth, active_rides,
    # bg_task_heartbeat_age_seconds) even when the business-logic
    # background loops live on the dedicated worker. The DB reads it
    # performs are cheap (6 COUNT queries + one SELECT) and the worker
    # runs its own copy of the same loop — both are idempotent.
    try:
        from utils.metrics import metrics_refresh_loop

        _spawn("metrics_refresh (30s)", metrics_refresh_loop)
    except Exception as e:
        logger.warning(f"Failed to import metrics refresh loop: {e}")

    app.state.background_tasks = background_tasks

    # WebSocket pub/sub (audit P0-B3): before this, socket sends were
    # in-process only, so on >1 replica the driver and the rider
    # regularly ended up on different containers and dispatch events
    # silently disappeared. Starting the pub/sub attaches a Redis
    # subscriber to the shared ConnectionManager; every outbound send
    # now fans out across replicas. In dev (no Redis URL configured)
    # this is a no-op and the manager stays in local-only mode.
    try:
        from socket_manager import manager as ws_manager
        from utils.ws_pubsub import pubsub as ws_pubsub
        from utils.ws_pubsub import resolve_ws_redis_url

        ws_redis_url = resolve_ws_redis_url(settings.WS_REDIS_URL, settings.RATE_LIMIT_REDIS_URL)
        ws_started = await ws_pubsub.start(ws_manager, ws_redis_url)
        app.state.ws_pubsub = ws_pubsub
        if not ws_started and settings.ENV.lower() == "production":
            # Production without distributed WS is a correctness
            # hazard, but not a boot-blocker — a single-machine prod
            # deploy is still coherent. Log at WARNING so the operator
            # sees it in the boot logs.
            logger.warning(
                "WS pub/sub did NOT start — WebSocket fan-out will be "
                "limited to the current machine. Set WS_REDIS_URL (or "
                "RATE_LIMIT_REDIS_URL, which will be reused) to enable "
                "cross-machine delivery."
            )
    except Exception as e:
        logger.warning(f"Failed to start WS pub/sub: {e}")

    # Perform startup checks
    logger.info(f"Spinr API startup complete ({len(background_tasks)} background tasks running)")

    yield

    # Cleanup on shutdown — cancel background tasks and await them.
    logger.info("Shutting down Spinr API...")
    # Stop WS pub/sub FIRST so in-flight publishes don't race against
    # a half-torn-down Redis client during the last ~millisecond of
    # shutdown (and so its consumer task isn't left as an orphan when
    # the event loop stops).
    try:
        ws_pubsub_ref = getattr(app.state, "ws_pubsub", None)
        if ws_pubsub_ref is not None:
            await ws_pubsub_ref.stop()
    except Exception as e:
        logger.warning(f"Error stopping WS pub/sub: {e}")

    for task in background_tasks:
        task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)
        logger.info(f"Cancelled {len(background_tasks)} background tasks")

    # Cleanup database
    if hasattr(app.state, "db") and app.state.db:
        await cleanup_database(app.state.db)

    logger.info("Spinr API shutdown complete")
