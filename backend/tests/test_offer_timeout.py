"""
Tests for _offer_timeout_handler — the backend-enforced offer TTL.

routes/rides.py uses the flat db_supabase interface:
  await db.find_one("rides", {...})
  await db.update_one("drivers", {"id": ...}, {...})
  await db.update_one("rides", {"id": ...}, {...})

All mocks use the flat interface (no collection attributes).
"""

from unittest.mock import AsyncMock, patch

import pytest


class TestOfferTimeoutHandler:
    """Tests for routes/rides._offer_timeout_handler."""

    @pytest.fixture
    def ride_still_assigned(self):
        return {
            "id": "ride_1",
            "rider_id": "user_rider_1",
            "driver_id": "driver_1",
            "status": "driver_assigned",
        }

    @pytest.mark.asyncio
    async def test_expires_and_resets(self, ride_still_assigned):
        """Ride still `driver_assigned` after timeout → release driver, reset to searching, re-dispatch."""
        with (
            patch("backend.routes.rides.asyncio.sleep", new_callable=AsyncMock),
            patch("backend.routes.rides.db") as mock_db,
            patch("backend.routes.rides.manager") as mock_manager,  # noqa: F841
            patch("backend.routes.rides.match_driver_to_ride", new_callable=AsyncMock) as mock_redispatch,
        ):
            mock_db.find_one = AsyncMock(return_value=ride_still_assigned)
            mock_db.update_one = AsyncMock()
            mock_manager.send_personal_message = AsyncMock()

            from backend.routes.rides import _offer_timeout_handler

            await _offer_timeout_handler("ride_1", "driver_1", rider_id="user_rider_1", timeout_seconds=30)

            # update_one called twice: once for drivers (release), once for rides (reset)
            assert mock_db.update_one.call_count == 2
            calls = mock_db.update_one.call_args_list

            # First call releases the driver
            driver_call = calls[0]
            assert driver_call[0][0] == "drivers"
            assert driver_call[0][1] == {"id": "driver_1"}

            # Second call resets the ride to searching
            rides_call = calls[1]
            assert rides_call[0][0] == "rides"

            # Rider notified
            mock_manager.send_personal_message.assert_called_once()
            ws_msg = mock_manager.send_personal_message.call_args[0][0]
            assert ws_msg["type"] == "driver_timeout"

            # Re-dispatch triggered
            mock_redispatch.assert_called_once_with("ride_1")

    @pytest.mark.asyncio
    async def test_noop_if_ride_progressed(self):
        """Ride already accepted → handler does nothing."""
        progressed_ride = {
            "id": "ride_1",
            "rider_id": "user_rider_1",
            "driver_id": "driver_1",
            "status": "driver_accepted",  # past assignment
        }
        with (
            patch("backend.routes.rides.asyncio.sleep", new_callable=AsyncMock),
            patch("backend.routes.rides.db") as mock_db,
            patch("backend.routes.rides.manager") as mock_manager,  # noqa: F841
            patch("backend.routes.rides.match_driver_to_ride", new_callable=AsyncMock) as mock_redispatch,
        ):
            mock_db.find_one = AsyncMock(return_value=progressed_ride)
            mock_db.update_one = AsyncMock()

            from backend.routes.rides import _offer_timeout_handler

            await _offer_timeout_handler("ride_1", "driver_1", rider_id="user_rider_1")

            mock_db.update_one.assert_not_called()
            mock_redispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_if_different_driver(self):
        """Ride reassigned to a different driver → handler does nothing."""
        different_driver_ride = {
            "id": "ride_1",
            "rider_id": "user_rider_1",
            "driver_id": "driver_2",  # different from the one we're timing out
            "status": "driver_assigned",
        }
        with (
            patch("backend.routes.rides.asyncio.sleep", new_callable=AsyncMock),
            patch("backend.routes.rides.db") as mock_db,
            patch("backend.routes.rides.match_driver_to_ride", new_callable=AsyncMock) as mock_redispatch,
        ):
            mock_db.find_one = AsyncMock(return_value=different_driver_ride)
            mock_db.update_one = AsyncMock()

            from backend.routes.rides import _offer_timeout_handler

            await _offer_timeout_handler("ride_1", "driver_1", rider_id="user_rider_1")

            mock_db.update_one.assert_not_called()
            mock_redispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_if_ride_gone(self):
        """Ride deleted/not found → handler does nothing."""
        with (
            patch("backend.routes.rides.asyncio.sleep", new_callable=AsyncMock),
            patch("backend.routes.rides.db") as mock_db,
            patch("backend.routes.rides.match_driver_to_ride", new_callable=AsyncMock) as mock_redispatch,
        ):
            mock_db.find_one = AsyncMock(return_value=None)
            mock_db.update_one = AsyncMock()

            from backend.routes.rides import _offer_timeout_handler

            await _offer_timeout_handler("ride_1", "driver_1", rider_id="user_rider_1")

            mock_db.update_one.assert_not_called()
            mock_redispatch.assert_not_called()
