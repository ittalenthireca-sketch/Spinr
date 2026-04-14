"""Async dispatch of Stripe webhook events.

Phase 1.5 of the production-readiness audit (P1-P7). The HTTP webhook
handler in ``routes/webhooks.py`` used to verify the signature AND run
the business-logic dispatch (DB writes, push notifications, Spinr Pass
activation) inline. That pushed the handler right up against Stripe's
20-second retry deadline whenever a downstream (FCM, supabase) was slow.

The fix: the webhook handler now only (a) verifies the signature and
(b) persists the raw event via ``claim_stripe_event``. The durable
``stripe_events`` table (migration 22 + alembic 0004) is the queue.
``utils.stripe_worker`` polls it from the worker process and calls
``dispatch_stripe_event`` below for each unprocessed row.

This module intentionally holds NO retry logic, NO DB polling, and NO
signature handling — that separation is what keeps the worker loop and
the HTTP handler independently testable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def dispatch_stripe_event(event_type: str, payload: Dict[str, Any]) -> None:
    """Run the business-logic side effects for one Stripe event.

    Called by the worker loop *after* the event has been persisted and
    claimed. The caller is responsible for (a) idempotency gating
    (already done by ``stripe_events`` PK), (b) stamping ``processed_at``
    on success, and (c) bumping ``attempt_count`` / backoff on failure.

    Parameters
    ----------
    event_type:
        The Stripe event ``type`` string, e.g. ``payment_intent.succeeded``.
    payload:
        The event object as a plain dict — typically the full event envelope
        as returned by ``stripe.Webhook.construct_event(...).to_dict_recursive()``.
        The handler reads ``data.object`` from it; other envelope fields
        are ignored.

    Raises
    ------
    Exception
        Any unhandled exception propagates so the worker can classify
        it (transient vs. permanent) and schedule a retry or give up.
        This module does NOT swallow errors silently.
    """
    # Lazy imports so this module can be imported from contexts (e.g.
    # tests) that don't have the full backend wired up.
    try:
        from ..db import db
        from ..features import send_push_notification
    except ImportError:
        from db import db  # type: ignore[no-redef]
        from features import send_push_notification  # type: ignore[no-redef]

    data_object = payload.get("data", {}).get("object", {})

    if event_type == "payment_intent.succeeded":
        ride_id = data_object.get("metadata", {}).get("ride_id")
        user_id = data_object.get("metadata", {}).get("user_id")
        payment_intent_id = data_object.get("id")

        if ride_id:
            await db.rides.update_one(
                {"id": ride_id},
                {
                    "$set": {
                        "payment_status": "paid",
                        "payment_intent_id": payment_intent_id,
                        "paid_at": datetime.now(timezone.utc),
                    }
                },
            )
            logger.info(f"Payment confirmed via webhook for ride {ride_id}")

        if user_id:
            await send_push_notification(
                user_id,
                "Payment Confirmed ✅",
                "Your payment has been processed successfully.",
                {"type": "payment_confirmed", "ride_id": ride_id or ""},
            )

    elif event_type == "payment_intent.payment_failed":
        ride_id = data_object.get("metadata", {}).get("ride_id")
        user_id = data_object.get("metadata", {}).get("user_id")
        payment_intent_id = data_object.get("id")
        failure_message = data_object.get("last_payment_error", {}).get("message", "Payment failed")

        if ride_id:
            await db.rides.update_one(
                {"id": ride_id},
                {
                    "$set": {
                        "payment_status": "failed",
                        "payment_intent_id": payment_intent_id,
                        "payment_failure_reason": failure_message,
                    }
                },
            )
            logger.warning(f"Payment failed for ride {ride_id}: {failure_message}")

        if user_id:
            await send_push_notification(
                user_id,
                "Payment Failed ❌",
                f"Your payment could not be processed: {failure_message}",
                {"type": "payment_failed", "ride_id": ride_id or ""},
            )

    elif event_type == "checkout.session.completed":
        # ── Spinr Pass subscription payment confirmed ──────────
        # The /drivers/subscription/subscribe endpoint creates a pending
        # subscription row and a Stripe Checkout Session with the
        # subscription_id in the metadata. This event fires after the
        # driver completes payment — we activate the subscription here.
        metadata = data_object.get("metadata", {})
        subscription_id = metadata.get("subscription_id")
        plan_id = metadata.get("plan_id")
        driver_id = metadata.get("driver_id")

        if subscription_id and data_object.get("payment_status") == "paid":
            try:
                from ..routes.drivers import _activate_subscription  # type: ignore
            except ImportError:
                from routes.drivers import _activate_subscription  # type: ignore

            await _activate_subscription(subscription_id, plan_id)
            logger.info(
                "[STRIPE-DISPATCH] Spinr Pass activated via checkout.session.completed: "
                f"subscription={subscription_id} driver={driver_id} plan={plan_id}"
            )
        else:
            logger.info(
                "[STRIPE-DISPATCH] checkout.session.completed but payment not yet paid: "
                f"status={data_object.get('payment_status')} subscription={subscription_id}"
            )

    else:
        logger.info(f"[STRIPE-DISPATCH] Unhandled Stripe event type: {event_type}")
