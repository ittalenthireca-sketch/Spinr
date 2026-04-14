from datetime import datetime
from typing import Dict, Optional

from fastapi import WebSocket
from loguru import logger

try:
    from .db import diag_logger  # type: ignore
except ImportError:
    from db import diag_logger  # type: ignore

# Prometheus gauge for per-role connection counts (Phase 2.3c / audit T3).
# Imported lazily so that socket_manager stays importable from Alembic's
# env.py (which doesn't pull in the metrics package).
try:
    from utils.metrics import ws_connections as _ws_connections_gauge
except Exception:  # pragma: no cover — metrics optional in non-API contexts
    _ws_connections_gauge = None  # type: ignore[assignment]


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.driver_locations: Dict[str, Dict] = {}
        # client_id → role (rider | driver | admin) so disconnect can
        # decrement the correct labelled gauge without re-parsing the
        # connection_key format. Also future-proofs us against a key
        # format change (e.g. dropping the `{role}_` prefix when we
        # move to server-assigned session IDs).
        self._roles: Dict[str, str] = {}

    async def connect(self, websocket: WebSocket, client_id: str, role: Optional[str] = None):
        # WebSocket is already accepted in the endpoint handler
        self.active_connections[client_id] = websocket
        # Fall back to parsing the connection_key prefix when the caller
        # didn't supply a role — keeps the legacy signature working for
        # any direct caller we might have missed.
        if role is None and "_" in client_id:
            role = client_id.split("_", 1)[0]
        if role:
            self._roles[client_id] = role
            if _ws_connections_gauge is not None:
                try:
                    _ws_connections_gauge.labels(role=role).inc()
                except Exception as e:  # pragma: no cover — metrics must never crash
                    logger.debug(f"ws_connections gauge inc failed: {e}")
        logger.info(f"WebSocket connected: {client_id}")
        diag_logger.info(
            f"[WS] CONNECT client_id={client_id} role={role} "
            f"total_connections={len(self.active_connections)} "
            f"all_keys={list(self.active_connections.keys())}"
        )

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        role = self._roles.pop(client_id, None)
        if role and _ws_connections_gauge is not None:
            try:
                _ws_connections_gauge.labels(role=role).dec()
            except Exception as e:  # pragma: no cover
                logger.debug(f"ws_connections gauge dec failed: {e}")
        logger.info(f"WebSocket disconnected: {client_id}")
        diag_logger.info(
            f"[WS] DISCONNECT client_id={client_id} role={role} "
            f"remaining={len(self.active_connections)} "
            f"all_keys={list(self.active_connections.keys())}"
        )

    async def send_personal_message(self, message: dict, client_id: str):
        """Send a message to a client, possibly on a different machine.

        When ``ws_pubsub`` is active (production / multi-machine) the
        message goes onto a shared Redis channel; every machine's
        subscriber receives it and delivers iff the client is in its
        local dict. That includes THIS machine — so we must NOT also
        call ``_deliver_local`` here, or local connections would
        receive the message twice. The Redis round-trip for same-VM
        delivery is sub-millisecond and buys us correctness across the
        fleet.

        When pub/sub is disabled (dev / degraded Redis) we fall back
        to direct local delivery — which is exactly the pre-P0-B3
        behaviour.
        """
        try:
            from utils.ws_pubsub import pubsub
        except ImportError:  # pragma: no cover — package-relative fallback
            from .utils.ws_pubsub import pubsub  # type: ignore

        if await pubsub.publish(client_id, message):
            return
        await self._deliver_local(message, client_id)

    async def _deliver_local(self, message: dict, client_id: str):
        """Write ``message`` to the socket for ``client_id`` on THIS machine only.

        Called by both the direct-send fallback and by the Redis pub/sub
        subscriber. Keeping it as a single method means diagnostics and
        error handling stay consistent regardless of which path
        triggered the delivery.
        """
        msg_type = message.get("type", "?") if isinstance(message, dict) else "?"
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message)
                diag_logger.info(f"[WS] SEND ok client_id={client_id} type={msg_type}")
            except Exception as e:
                diag_logger.info(f"[WS] SEND FAILED client_id={client_id} type={msg_type} err={e}")
        else:
            # In multi-machine mode this is expected for every message
            # whose target happens to live on another VM — don't treat
            # it as a drop unless we're the only machine serving the
            # fleet.
            diag_logger.debug(
                f"[WS] not local client_id={client_id} type={msg_type} "
                f"(message may have been delivered by another machine)"
            )

    async def broadcast(self, message: dict):
        """Broadcast to every socket connected to THIS machine.

        Intentionally local-only: broadcast() has no current callers
        outside of legacy test paths, and cross-machine broadcast is a
        different feature (room-based fan-out) that we haven't yet had
        a real use for. When we do, add a ``pubsub.publish_broadcast``
        helper rather than changing this method's semantics.
        """
        for connection in self.active_connections.values():
            await connection.send_json(message)

    def update_driver_location(self, driver_id: str, lat: float, lng: float):
        self.driver_locations[driver_id] = {"lat": lat, "lng": lng, "updated_at": datetime.utcnow().isoformat()}

    def get_driver_location(self, driver_id: str):
        return self.driver_locations.get(driver_id)


manager = ConnectionManager()
