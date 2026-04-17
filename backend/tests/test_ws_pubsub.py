"""Unit tests for utils/ws_pubsub.py — WebSocket Redis fan-out.

Covers:
  - Single-machine mode (no Redis URL) → publish returns False
  - start() with missing redis package → returns False gracefully
  - start() with unreachable Redis URL → returns False gracefully
  - publish() when active → serialises payload and calls redis.publish
  - publish() with non-serialisable payload → returns False, no crash
  - Consumer loop delivers message to local manager via _deliver_local
  - Consumer loop skips non-message Redis events
  - Consumer loop survives a bad JSON frame without crashing
  - stop() cancels consumer and closes connections
  - resolve_ws_redis_url picks WS_REDIS_URL over RATE_LIMIT_REDIS_URL
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pubsub():
    """Return a fresh _WSPubSub with no Redis attached."""
    from utils.ws_pubsub import _WSPubSub
    return _WSPubSub()


def _mock_manager() -> MagicMock:
    mgr = MagicMock()
    mgr._deliver_local = AsyncMock()
    return mgr


# ---------------------------------------------------------------------------
# resolve_ws_redis_url
# ---------------------------------------------------------------------------

def test_resolve_ws_redis_url_prefers_ws_url():
    from utils.ws_pubsub import resolve_ws_redis_url
    assert resolve_ws_redis_url("redis://ws-host/0", "redis://rate-host/0") == "redis://ws-host/0"


def test_resolve_ws_redis_url_falls_back_to_rate_limit():
    from utils.ws_pubsub import resolve_ws_redis_url
    assert resolve_ws_redis_url("", "redis://rate-host/0") == "redis://rate-host/0"


def test_resolve_ws_redis_url_returns_empty_when_neither_set():
    from utils.ws_pubsub import resolve_ws_redis_url
    assert resolve_ws_redis_url("", "") == ""


# ---------------------------------------------------------------------------
# Single-machine / no-Redis mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_no_url_returns_false():
    ps = _make_pubsub()
    result = await ps.start(_mock_manager(), "")
    assert result is False
    assert not ps.active


@pytest.mark.asyncio
async def test_publish_when_inactive_returns_false():
    ps = _make_pubsub()
    result = await ps.publish("rider_abc", {"type": "ping"})
    assert result is False


# ---------------------------------------------------------------------------
# Redis import / connection errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_missing_redis_package_returns_false():
    ps = _make_pubsub()
    with patch.dict("sys.modules", {"redis": None, "redis.asyncio": None}):
        result = await ps.start(_mock_manager(), "redis://localhost:6379/0")
    assert result is False
    assert not ps.active


@pytest.mark.asyncio
async def test_start_unreachable_redis_returns_false():
    ps = _make_pubsub()
    mock_client = AsyncMock()
    mock_client.ping.side_effect = ConnectionRefusedError("refused")

    mock_redis_module = MagicMock()
    mock_redis_module.from_url.return_value = mock_client

    with patch.dict("sys.modules", {"redis": MagicMock(asyncio=mock_redis_module),
                                    "redis.asyncio": mock_redis_module}):
        result = await ps.start(_mock_manager(), "redis://localhost:6379/0")

    assert result is False
    assert not ps.active


# ---------------------------------------------------------------------------
# Active pub/sub — publish
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_serialises_and_calls_redis():
    ps = _make_pubsub()

    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=1)
    ps._redis = mock_redis

    # Simulate an active consumer task
    async def _noop():
        await asyncio.sleep(9999)

    ps._task = asyncio.create_task(_noop())
    ps._manager = _mock_manager()

    try:
        result = await ps.publish("driver_xyz", {"type": "ride_offer", "ride_id": "r1"})
        assert result is True
        mock_redis.publish.assert_called_once()
        channel, body = mock_redis.publish.call_args[0]
        assert channel == "spinr:ws:dispatch"
        data = json.loads(body)
        assert data["client_id"] == "driver_xyz"
        assert data["message"]["type"] == "ride_offer"
    finally:
        ps._task.cancel()
        try:
            await ps._task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_publish_non_serialisable_payload_returns_false():
    ps = _make_pubsub()
    mock_redis = AsyncMock()
    ps._redis = mock_redis

    async def _noop():
        await asyncio.sleep(9999)

    ps._task = asyncio.create_task(_noop())
    ps._manager = _mock_manager()

    try:
        # A set is not JSON-serialisable
        result = await ps.publish("rider_abc", {"data": {1, 2, 3}})  # type: ignore[arg-type]
        assert result is False
        mock_redis.publish.assert_not_called()
    finally:
        ps._task.cancel()
        try:
            await ps._task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_publish_redis_error_returns_false():
    ps = _make_pubsub()
    mock_redis = AsyncMock()
    mock_redis.publish.side_effect = RuntimeError("Redis gone")
    ps._redis = mock_redis

    async def _noop():
        await asyncio.sleep(9999)

    ps._task = asyncio.create_task(_noop())
    ps._manager = _mock_manager()

    try:
        result = await ps.publish("rider_abc", {"type": "ping"})
        assert result is False
    finally:
        ps._task.cancel()
        try:
            await ps._task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# Consumer loop behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consumer_delivers_valid_message_to_manager():
    """Consumer receives a well-formed message and calls _deliver_local."""
    from utils.ws_pubsub import _WSPubSub

    manager = _mock_manager()
    ps = _WSPubSub()
    ps._manager = manager

    payload = {"type": "ride_offer"}
    raw = json.dumps({"client_id": "driver_abc", "message": payload})
    msg = {"type": "message", "data": raw}

    # Provide two iterations: one real message, then CancelledError to exit.
    call_count = 0

    async def fake_get_message(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return msg
        raise asyncio.CancelledError()

    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = fake_get_message
    ps._pubsub = mock_pubsub

    with pytest.raises(asyncio.CancelledError):
        await ps._consumer()

    manager._deliver_local.assert_awaited_once_with(payload, "driver_abc")


@pytest.mark.asyncio
async def test_consumer_skips_non_message_events():
    """Consumer ignores subscribe/unsubscribe confirmation frames."""
    from utils.ws_pubsub import _WSPubSub

    manager = _mock_manager()
    ps = _WSPubSub()
    ps._manager = manager

    call_count = 0

    async def fake_get_message(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"type": "subscribe", "data": 1}
        raise asyncio.CancelledError()

    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = fake_get_message
    ps._pubsub = mock_pubsub

    with pytest.raises(asyncio.CancelledError):
        await ps._consumer()

    manager._deliver_local.assert_not_awaited()


@pytest.mark.asyncio
async def test_consumer_survives_bad_json():
    """Malformed JSON frame is silently dropped; consumer keeps running."""
    from utils.ws_pubsub import _WSPubSub

    manager = _mock_manager()
    ps = _WSPubSub()
    ps._manager = manager

    call_count = 0

    async def fake_get_message(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"type": "message", "data": "NOT_JSON{{{{"}
        raise asyncio.CancelledError()

    mock_pubsub = AsyncMock()
    mock_pubsub.get_message = fake_get_message
    ps._pubsub = mock_pubsub

    with pytest.raises(asyncio.CancelledError):
        await ps._consumer()

    manager._deliver_local.assert_not_awaited()


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_cancels_task_and_closes_redis():
    ps = _make_pubsub()

    async def _noop():
        await asyncio.sleep(9999)

    ps._task = asyncio.create_task(_noop())
    ps._redis = AsyncMock()
    ps._pubsub = AsyncMock()
    ps._manager = _mock_manager()

    await ps.stop()

    assert ps._task is None
    assert ps._redis is None
    assert ps._pubsub is None
    assert ps._manager is None


@pytest.mark.asyncio
async def test_stop_is_safe_when_not_started():
    """Calling stop() before start() must not raise."""
    ps = _make_pubsub()
    await ps.stop()  # Should complete without error
