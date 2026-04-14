"""
Spinr background worker entrypoint.

Runs the five long-running loops that used to live inside the API
lifespan:

  * subscription expiry check (every 6h)
  * surge-pricing recalculation (every 2 min)
  * scheduled-ride dispatcher (every 60s)
  * payment retry (every 5 min)
  * document expiry alerts (every 12h)

Background loops were previously spawned in core/lifespan.py, which
meant they ran inside each API machine. When `auto_stop_machines`
was on (or the machine was drained for a deploy) every loop stopped
with it — scheduled rides silently missed their dispatch window,
failed payments were never retried, and expired documents never
alerted the driver.

Splitting them into a dedicated process lets Fly's [processes] block
(fly.toml) schedule a single always-on worker machine independent of
the API pool. The API lifespan still spawns the loops when the
process role is unset (local dev / legacy single-process deploys),
so nothing changes for developers running `uvicorn server:app`.

Process-role contract:
  FLY_PROCESS_GROUP=app     → API machine; lifespan skips bg tasks
  FLY_PROCESS_GROUP=worker  → worker machine; runs THIS file
  (unset)                   → legacy single-process; lifespan runs
                              everything (backwards compat)

Health / liveness:
  This process exposes no HTTP server. Fly's process health for
  `worker` should fall back to machine-process liveness (i.e. the
  script must not exit). Each loop catches its own exceptions so a
  single loop dying does not take the worker down. We log at ERROR
  and let asyncio restart on next boot if the whole process crashes.
"""

from __future__ import annotations

import asyncio
import signal
import sys

from loguru import logger


async def _run_all_loops() -> None:
    """Start every background loop and keep them alive until SIGTERM."""
    from core.config import settings  # lazy import so module import is cheap
    from db_supabase import run_sync
    from supabase_client import supabase

    # Boot-time DB probe — fail fast if the worker can't reach Supabase.
    # Mirrors the check in core/lifespan.init_database so the worker has
    # the same production guarantees as the API.
    if not supabase:
        msg = "Supabase client not configured — worker cannot start"
        if settings.ENV.lower() == "production":
            raise RuntimeError(msg)
        logger.warning(f"{msg} (continuing in {settings.ENV} mode)")
    else:
        try:
            await run_sync(lambda: supabase.table("users").select("id").limit(1).execute())
            logger.info("Worker: Supabase connection verified")
        except Exception as e:
            logger.error(f"Worker: Supabase health check failed: {e}")
            if settings.ENV.lower() == "production":
                raise

    tasks: list[asyncio.Task] = []

    def _spawn(name: str, coro_factory) -> None:
        try:
            task = asyncio.create_task(coro_factory(), name=name)
            tasks.append(task)
            logger.info(f"Worker: started background task: {name}")
        except Exception as e:
            logger.warning(f"Worker: failed to start {name}: {e}")

    try:
        from routes.drivers import check_expiring_subscriptions

        _spawn("subscription_expiry (6h)", check_expiring_subscriptions)
    except Exception as e:
        logger.warning(f"Worker: failed to import subscription expiry checker: {e}")

    try:
        from utils.surge_engine import surge_recalculation_loop

        _spawn("surge_engine (2min)", surge_recalculation_loop)
    except Exception as e:
        logger.warning(f"Worker: failed to import surge pricing engine: {e}")

    try:
        from utils.scheduled_rides import scheduled_ride_dispatcher_loop

        _spawn("scheduled_dispatcher (60s)", scheduled_ride_dispatcher_loop)
    except Exception as e:
        logger.warning(f"Worker: failed to import scheduled ride dispatcher: {e}")

    try:
        from utils.payment_retry import payment_retry_loop

        _spawn("payment_retry (5min)", payment_retry_loop)
    except Exception as e:
        logger.warning(f"Worker: failed to import payment retry service: {e}")

    try:
        from utils.document_expiry import document_expiry_loop

        _spawn("document_expiry (12h)", document_expiry_loop)
    except Exception as e:
        logger.warning(f"Worker: failed to import document expiry checker: {e}")

    logger.info(f"Worker: {len(tasks)} background tasks running; waiting for shutdown signal")

    # Block until a shutdown signal arrives. asyncio.Event is set by the
    # SIGTERM/SIGINT handler registered in main().
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            # add_signal_handler is not supported on Windows — fall back
            # to default signal handling (the process will exit on SIGINT).
            pass

    await shutdown_event.wait()
    logger.info("Worker: shutdown signal received; cancelling background tasks")

    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(f"Worker: cancelled {len(tasks)} background tasks; exiting")


def main() -> int:
    """Module entrypoint; invoked by `python -m worker`."""
    try:
        asyncio.run(_run_all_loops())
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        logger.error(f"Worker crashed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
