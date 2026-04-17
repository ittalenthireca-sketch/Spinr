"""
Tests for chat message endpoints: GET + POST /rides/{id}/messages.

Implementation notes:
- get_ride_messages uses db_supabase.* calls directly (get_ride, get_rows).
  Patch target: backend.routes.rides.db_supabase
- send_ride_message uses db.* flat interface (find_one, insert_one).
  Patch target: backend.routes.rides.db
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


class TestGetRideMessages:
    """Tests for GET /rides/{ride_id}/messages."""

    @pytest.mark.asyncio
    async def test_rider_can_get_messages(self):
        ride = {"id": "ride_1", "rider_id": "user_1", "driver_id": "driver_1"}
        messages_data = [
            {"id": "m1", "ride_id": "ride_1", "text": "Hello", "sender": "rider", "timestamp": "2026-04-12T10:00:00"},
            {
                "id": "m2",
                "ride_id": "ride_1",
                "text": "On my way",
                "sender": "driver",
                "timestamp": "2026-04-12T10:01:00",
            },
        ]

        async def _get_rows(table, *args, **kwargs):
            if table == "drivers":
                return []  # user_1 is a rider, not a driver
            if table == "ride_messages":
                return messages_data
            return []

        with patch("backend.routes.rides.db_supabase") as mock_dbs:
            mock_dbs.get_ride = AsyncMock(return_value=ride)
            mock_dbs.get_rows = AsyncMock(side_effect=_get_rows)

            from backend.routes.rides import get_ride_messages

            result = await get_ride_messages("ride_1", current_user={"id": "user_1"})
            assert result["success"] is True
            assert len(result["messages"]) == 2

    @pytest.mark.asyncio
    async def test_non_participant_gets_403(self):
        ride = {"id": "ride_1", "rider_id": "user_1", "driver_id": "driver_1"}

        with patch("backend.routes.rides.db_supabase") as mock_dbs:
            mock_dbs.get_ride = AsyncMock(return_value=ride)
            mock_dbs.get_rows = AsyncMock(return_value=[])  # stranger is not a driver

            from backend.routes.rides import get_ride_messages

            with pytest.raises(HTTPException) as exc_info:
                await get_ride_messages("ride_1", current_user={"id": "stranger"})
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_ride_not_found_returns_404(self):
        with patch("backend.routes.rides.db_supabase") as mock_dbs:
            mock_dbs.get_ride = AsyncMock(return_value=None)

            from backend.routes.rides import get_ride_messages

            with pytest.raises(HTTPException) as exc_info:
                await get_ride_messages("nonexistent", current_user={"id": "user_1"})
            assert exc_info.value.status_code == 404


class TestSendRideMessage:
    """Tests for POST /rides/{ride_id}/messages.

    send_ride_message uses db.find_one / db.insert_one (flat interface).
    Patch target: backend.routes.rides.db
    """

    @pytest.mark.asyncio
    async def test_rider_can_send_message(self):
        ride = {"id": "ride_1", "rider_id": "user_1", "driver_id": "driver_1"}
        driver_row = {"id": "driver_1", "user_id": "user_driver_1"}

        def _find_one(table, filter_dict=None, **kw):
            if table == "rides":
                return ride
            if table == "drivers":
                if filter_dict and filter_dict.get("user_id") == "user_1":
                    return None  # user_1 is a rider, not a driver
                if filter_dict and filter_dict.get("id") == "driver_1":
                    return driver_row
            return None

        with (
            patch("backend.routes.rides.db") as mock_db,
            patch("backend.routes.rides.manager") as mock_manager,
        ):
            mock_db.find_one = AsyncMock(side_effect=_find_one)
            mock_db.insert_one = AsyncMock()
            mock_manager.send_personal_message = AsyncMock()

            from backend.routes.rides import SendMessageRequest, send_ride_message

            body = SendMessageRequest(text="I'm at the corner")
            result = await send_ride_message("ride_1", body, current_user={"id": "user_1"})

            assert result["success"] is True
            assert result["message"]["sender"] == "rider"
            assert result["message"]["text"] == "I'm at the corner"
            mock_db.insert_one.assert_called_once()
            # WS forward to driver
            mock_manager.send_personal_message.assert_called_once()
            call_args = mock_manager.send_personal_message.call_args
            assert call_args[0][1] == "driver_user_driver_1"

    @pytest.mark.asyncio
    async def test_non_participant_gets_403(self):
        ride = {"id": "ride_1", "rider_id": "user_1", "driver_id": "driver_1"}

        with patch("backend.routes.rides.db") as mock_db:
            mock_db.find_one = AsyncMock(
                side_effect=lambda table, *a, **kw: ride if table == "rides" else None
            )

            from backend.routes.rides import SendMessageRequest, send_ride_message

            body = SendMessageRequest(text="Hello")
            with pytest.raises(HTTPException) as exc_info:
                await send_ride_message("ride_1", body, current_user={"id": "stranger"})
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_ride_not_found_returns_404(self):
        with patch("backend.routes.rides.db") as mock_db:
            mock_db.find_one = AsyncMock(return_value=None)

            from backend.routes.rides import SendMessageRequest, send_ride_message

            body = SendMessageRequest(text="Hello")
            with pytest.raises(HTTPException) as exc_info:
                await send_ride_message("ride_1", body, current_user={"id": "user_1"})
            assert exc_info.value.status_code == 404
