"""Integration tests for the loyalty rewards endpoints.

Routes under test (backend/routes/loyalty.py):
  GET  /api/v1/loyalty             — get loyalty status
  GET  /api/v1/loyalty/history     — transaction history
  POST /api/v1/loyalty/earn        — award points for a ride
  POST /api/v1/loyalty/redeem      — redeem points for wallet credit
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLE_USER = {"id": "user_123", "phone": "+1234567890", "role": "rider", "is_driver": False}

SAMPLE_ACCOUNT = {
    "id": "acct_123",
    "user_id": "user_123",
    "points": 250,
    "lifetime_points": 750,
    "tier": "silver",
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

SAMPLE_RIDE = {
    "id": "ride_123",
    "rider_id": "user_123",
    "status": "completed",
    "total_fare": 20.00,
}


def make_mock_db():
    """Build a mock matching the flat db_supabase interface used by routes/loyalty.py."""
    mock = MagicMock()
    mock.find_one = AsyncMock(return_value=None)
    mock.insert_one = AsyncMock(return_value=None)
    mock.update_one = AsyncMock(return_value=None)
    mock.get_rows = AsyncMock(return_value=[])
    return mock


def _find_one_dispatch(**table_returns):
    """Return an AsyncMock that dispatches find_one calls by table name."""

    def _dispatch(table, *args, **kwargs):
        return table_returns.get(table)

    return AsyncMock(side_effect=_dispatch)


@pytest.fixture
def client():
    import dependencies  # same module the routes use (routes use relative '..dependencies')
    from backend.server import app  # ensures server.py sys.path setup runs first

    app.dependency_overrides[dependencies.get_current_user] = lambda: SAMPLE_USER
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestGetLoyaltyStatus:
    """GET /api/v1/loyalty"""

    def test_new_user_gets_bronze_account(self, client):
        """First-time call auto-creates a bronze account."""
        mock_db = make_mock_db()
        # Default find_one returns None → auto-create path

        with patch("routes.loyalty.db", mock_db):
            resp = client.get("/api/v1/loyalty")

        assert resp.status_code == 200
        data = resp.json()
        assert data["points"] == 0
        assert data["lifetime_points"] == 0
        assert data["tier"] == "bronze"
        assert data["multiplier"] == 1.0
        assert data["redemption_rate"] == 100

    def test_existing_silver_account(self, client):
        """Existing account data is returned as-is."""
        mock_db = make_mock_db()
        mock_db.find_one = AsyncMock(return_value=SAMPLE_ACCOUNT)

        with patch("routes.loyalty.db", mock_db):
            resp = client.get("/api/v1/loyalty")

        assert resp.status_code == 200
        data = resp.json()
        assert data["points"] == 250
        assert data["tier"] == "silver"
        assert data["multiplier"] == 1.25

    def test_unauthenticated_request_rejected(self):
        from fastapi.testclient import TestClient

        from backend.server import app

        # No dependency_overrides — real auth should reject the request
        with TestClient(app) as c:
            resp = c.get("/api/v1/loyalty")
        assert resp.status_code == 401


class TestGetLoyaltyHistory:
    """GET /api/v1/loyalty/history"""

    def test_empty_history(self, client):
        mock_db = make_mock_db()
        # Route calls get_rows("loyalty_transactions", ...) — no find_one needed
        mock_db.get_rows = AsyncMock(return_value=[])

        with patch("routes.loyalty.db", mock_db):
            resp = client.get("/api/v1/loyalty/history")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_returns_transactions(self, client):
        txns = [
            {"id": "t1", "points": 20, "type": "ride_earned", "created_at": "2026-01-02T10:00:00"},
            {"id": "t2", "points": -100, "type": "redeemed", "created_at": "2026-01-01T10:00:00"},
        ]
        mock_db = make_mock_db()
        mock_db.get_rows = AsyncMock(return_value=txns)

        with patch("routes.loyalty.db", mock_db):
            resp = client.get("/api/v1/loyalty/history?limit=10")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_limit_validation(self, client):
        mock_db = make_mock_db()

        with patch("routes.loyalty.db", mock_db):
            # limit=0 is below ge=1 — FastAPI rejects before hitting db
            resp = client.get("/api/v1/loyalty/history?limit=0")
        assert resp.status_code == 422


class TestEarnPoints:
    """POST /api/v1/loyalty/earn"""

    def test_earn_points_for_completed_ride(self, client):
        mock_db = make_mock_db()
        # Route: find_one("rides"), find_one("loyalty_transactions") → None, find_one("loyalty_accounts")
        mock_db.find_one = _find_one_dispatch(
            rides=SAMPLE_RIDE,
            loyalty_transactions=None,
            loyalty_accounts=SAMPLE_ACCOUNT,
        )

        with patch("routes.loyalty.db", mock_db):
            resp = client.post("/api/v1/loyalty/earn?ride_id=ride_123")

        assert resp.status_code == 200
        data = resp.json()
        assert "points_earned" in data
        assert data["points_earned"] > 0
        assert "tier" in data

    def test_earn_applies_silver_multiplier(self, client):
        """Silver tier (1.25×) earns bonus points."""
        mock_db = make_mock_db()
        mock_db.find_one = _find_one_dispatch(
            rides=SAMPLE_RIDE,  # $20 fare
            loyalty_transactions=None,
            loyalty_accounts=SAMPLE_ACCOUNT,
        )

        with patch("routes.loyalty.db", mock_db):
            resp = client.post("/api/v1/loyalty/earn?ride_id=ride_123")

        data = resp.json()
        # $20 × 1 pt/$ = 20 base + 5 bonus (1.25-1.0 = 0.25 × 20)
        assert data["base_points"] == 20
        assert data["bonus_points"] == 5
        assert data["points_earned"] == 25

    def test_ride_not_found_returns_404(self, client):
        mock_db = make_mock_db()
        # Default find_one returns None → ride not found

        with patch("routes.loyalty.db", mock_db):
            resp = client.post("/api/v1/loyalty/earn?ride_id=bad_ride")

        assert resp.status_code == 404

    def test_ride_not_completed_returns_400(self, client):
        pending_ride = {**SAMPLE_RIDE, "status": "in_progress"}
        mock_db = make_mock_db()
        mock_db.find_one = AsyncMock(return_value=pending_ride)

        with patch("routes.loyalty.db", mock_db):
            resp = client.post("/api/v1/loyalty/earn?ride_id=ride_123")

        assert resp.status_code == 400
        assert "not completed" in resp.json()["detail"].lower()

    def test_already_awarded_returns_idempotent(self, client):
        existing_txn = {"id": "txn_existing", "type": "ride_earned"}
        mock_db = make_mock_db()
        # Route: find_one("rides") → ride, find_one("loyalty_transactions") → existing → already awarded
        mock_db.find_one = _find_one_dispatch(
            rides=SAMPLE_RIDE,
            loyalty_transactions=existing_txn,
        )

        with patch("routes.loyalty.db", mock_db):
            resp = client.post("/api/v1/loyalty/earn?ride_id=ride_123")

        assert resp.status_code == 200
        assert resp.json()["already_awarded"] is True

    def test_unauthorized_ride_returns_403(self, client):
        other_user_ride = {**SAMPLE_RIDE, "rider_id": "other_user"}
        mock_db = make_mock_db()
        mock_db.find_one = AsyncMock(return_value=other_user_ride)

        with patch("routes.loyalty.db", mock_db):
            resp = client.post("/api/v1/loyalty/earn?ride_id=ride_123")

        assert resp.status_code == 403


class TestRedeemPoints:
    """POST /api/v1/loyalty/redeem"""

    def test_redeem_points_for_wallet_credit(self, client):
        rich_account = {**SAMPLE_ACCOUNT, "points": 500}
        mock_db = make_mock_db()
        # Route: find_one("loyalty_accounts") → rich_account.
        # Wallet credit is in a try/except, so only loyalty_accounts matters for assertions.
        mock_db.find_one = AsyncMock(return_value=rich_account)

        with patch("routes.loyalty.db", mock_db):
            resp = client.post("/api/v1/loyalty/redeem", json={"points": 100})

        assert resp.status_code == 200
        data = resp.json()
        assert data["redeemed_points"] == 100
        assert data["credit_amount"] == 1.0  # 100 pts / 100 rate = $1
        assert data["remaining_points"] == 400

    def test_below_minimum_redemption_returns_400(self, client):
        mock_db = make_mock_db()
        # Minimum check (< 100 pts) happens before any db call

        with patch("routes.loyalty.db", mock_db):
            resp = client.post("/api/v1/loyalty/redeem", json={"points": 50})

        assert resp.status_code == 400
        assert "minimum" in resp.json()["detail"].lower()

    def test_insufficient_points_returns_400(self, client):
        low_balance_account = {**SAMPLE_ACCOUNT, "points": 50}
        mock_db = make_mock_db()
        mock_db.find_one = AsyncMock(return_value=low_balance_account)

        with patch("routes.loyalty.db", mock_db):
            resp = client.post("/api/v1/loyalty/redeem", json={"points": 200})

        assert resp.status_code == 400
        assert "insufficient" in resp.json()["detail"].lower()
