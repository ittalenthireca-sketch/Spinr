from fastapi import APIRouter, HTTPException, Request

try:
    from ..db_supabase import claim_stripe_event
    from .. import db_supabase
    from ..features import send_push_notification
    from ..settings_loader import get_app_settings
except ImportError:
    from db_supabase import claim_stripe_event
    import db_supabase
    from features import send_push_notification
    from settings_loader import get_app_settings
import logging

logger = logging.getLogger(__name__)
# IMPORTANT: This router does NOT have a /api/ prefix in the original server.py
# In server.py: app.post("/webhooks/stripe")
# So we should probably mount it at root or handle it carefully.
# However, for consistency with other modules, let's define the router here.
# The user will need to mount it appropriately in server.py.
api_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# ============================================================
# Phase 1.5 of the production-readiness audit (P1-P7):
#
# This handler used to verify + persist + DISPATCH inline, which put
# Stripe's 20-second retry deadline in the hands of FCM/supabase.
# Now the HTTP path is minimal:
#
#   1. Verify signature.
#   2. Persist the raw event into `stripe_events` (migration 22 —
#      PK on event_id gives us idempotency).
#   3. Return 200 immediately.
#
# Business-logic side effects (ride payment status updates, push
# notifications, Spinr Pass activation) run asynchronously on the
# worker process via `utils.stripe_worker` which polls
# `stripe_events WHERE processed_at IS NULL` and calls
# `utils.stripe_dispatcher.dispatch_stripe_event` for each row.
#
# Failure modes:
#   * Signature invalid → 400, Stripe treats as client error, no retry.
#   * Persistence fails → 500, Stripe retries (event stays out of DB).
#   * Dispatch fails    → not our problem here — the worker records
#                          last_error + schedules the next retry.
# ============================================================


@api_router.post("/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events: verify signature, persist, return 200.

    Business-logic dispatch is handled asynchronously by the worker
    process; this endpoint must remain fast (Stripe retries on any reply
    taking >20s) so we do NOT run side effects here.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    settings = await get_app_settings()
    webhook_secret = settings.get("stripe_webhook_secret", "")
    stripe_secret = settings.get("stripe_secret_key", "")

    if not webhook_secret:
        logger.error("stripe_webhook_secret not set — rejecting unverified webhook")
        raise HTTPException(
            status_code=500,
            detail="Webhook signature verification not configured",
        )

    if not stripe_secret:
        logger.error("Stripe secret key not configured in app settings")
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        import stripe

        stripe.api_key = stripe_secret
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload") from None
    except Exception as e:
        logger.error(f"Stripe webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature") from e

    event_id = event.get("id", "")
    event_type = event.get("type", "")

    if not event_id:
        # Should never happen for real Stripe events, but guard anyway —
        # we cannot dedup without a stable key.
        logger.error("Stripe webhook event missing id — cannot dedup")
        raise HTTPException(status_code=400, detail="Missing event id")

    # ── Idempotent persistence ─────────────────────────────────────────
    # Stripe retries every event (network blip, >20s handler, any non-2xx)
    # so we MUST treat a replay of the same event.id as a no-op. The
    # stripe_events table (migration 22) has event_id as PRIMARY KEY;
    # claim_stripe_event returns False on a unique-violation replay.
    # Stripe objects are dict subclasses but nested values (e.g. data.object)
    # remain as StripeObject instances. to_dict_recursive() flattens the whole
    # tree into plain dicts so it can be stored in jsonb without surprises.
    try:
        event_payload = event.to_dict_recursive()  # type: ignore[attr-defined]
    except AttributeError:
        event_payload = dict(event)

    try:
        is_new = await claim_stripe_event(event_id, event_type, event_payload)
    except Exception as e:
        logger.error(f"Failed to persist stripe event {event_id}: {e}")
        # Let Stripe retry — 5xx keeps the event in their queue.
        raise HTTPException(status_code=500, detail="Event persistence failed") from e

    if not is_new:
        return {"received": True, "duplicate": True, "event_id": event_id}

    # Dispatch happens asynchronously on the worker process — see
    # utils/stripe_worker.py. We return 200 immediately so Stripe
    # doesn't retry while the side effects run out-of-band.
    logger.info(f"[webhook] enqueued stripe event {event_id} (type={event_type})")
    return {"received": True, "event_id": event_id, "queued": True}
