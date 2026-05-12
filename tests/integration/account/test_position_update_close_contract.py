"""
Position update / close contract tests.

Verifies:
- PATCH shares/avg_cost/current_price recalculates derived fields.
- POST close creates a TransactionModel record.
- Observer cannot update or close positions.
"""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.account.infrastructure.models import (
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
    TransactionModel,
)

# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def owner(db):
    return User.objects.create_user(username="pos_contract_owner", password="x")


@pytest.fixture
def observer(db):
    return User.objects.create_user(username="pos_contract_observer", password="x")


@pytest.fixture
def portfolio(owner):
    return PortfolioModel.objects.create(
        user=owner, name="contract_test_portfolio", is_active=True,
    )


@pytest.fixture
def position(portfolio):
    return PositionModel.objects.create(
        portfolio=portfolio,
        asset_code="600000.SH",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=1000,
        avg_cost=Decimal("10.00"),
        current_price=Decimal("12.00"),
        market_value=Decimal("12000.00"),
        unrealized_pnl=Decimal("2000.00"),
        unrealized_pnl_pct=20.0,
        source="manual",
        is_closed=False,
    )


@pytest.fixture
def observer_grant(owner, observer):
    return PortfolioObserverGrantModel.objects.create(
        owner_user_id=owner,
        observer_user_id=observer,
        scope="portfolio_read",
        status="active",
    )


@pytest.fixture
def client():
    return APIClient()


# ── update derived field tests ────────────────────────────────────────────

@pytest.mark.django_db
class TestPositionUpdateRecalculation:
    """PATCH /api/account/positions/{id}/ must recalculate derived fields."""

    def test_patch_shares_recalculates(self, client, owner, position):
        client.force_authenticate(user=owner)
        resp = client.patch(
            f"/api/account/positions/{position.id}/",
            {"shares": 500},
            format="json",
        )
        assert resp.status_code == 200
        position.refresh_from_db()
        # market_value = 500 * 12.00 = 6000
        assert float(position.market_value) == pytest.approx(6000.0)
        # unrealized_pnl = 6000 - 500*10 = 1000
        assert float(position.unrealized_pnl) == pytest.approx(1000.0)
        # unrealized_pnl_pct = 1000/5000*100 = 20%
        assert position.unrealized_pnl_pct == pytest.approx(20.0)

    def test_patch_current_price_recalculates(self, client, owner, position):
        client.force_authenticate(user=owner)
        resp = client.patch(
            f"/api/account/positions/{position.id}/",
            {"current_price": "15.00"},
            format="json",
        )
        assert resp.status_code == 200
        position.refresh_from_db()
        # market_value = 1000 * 15 = 15000
        assert float(position.market_value) == pytest.approx(15000.0)
        # unrealized_pnl = 15000 - 10000 = 5000
        assert float(position.unrealized_pnl) == pytest.approx(5000.0)
        # pnl_pct = 5000/10000*100 = 50%
        assert position.unrealized_pnl_pct == pytest.approx(50.0)

    def test_patch_avg_cost_recalculates(self, client, owner, position):
        client.force_authenticate(user=owner)
        resp = client.patch(
            f"/api/account/positions/{position.id}/",
            {"avg_cost": "8.00"},
            format="json",
        )
        assert resp.status_code == 200
        position.refresh_from_db()
        # market_value = 1000 * 12 = 12000  (unchanged)
        assert float(position.market_value) == pytest.approx(12000.0)
        # unrealized_pnl = 12000 - 8000 = 4000
        assert float(position.unrealized_pnl) == pytest.approx(4000.0)
        # pnl_pct = 4000/8000*100 = 50%
        assert position.unrealized_pnl_pct == pytest.approx(50.0)


# ── close trade record tests ─────────────────────────────────────────────

@pytest.mark.django_db
class TestPositionCloseWritesTransaction:
    """POST /api/account/positions/{id}/close/ must create a transaction record."""

    def test_full_close_creates_sell_transaction(self, client, owner, position):
        client.force_authenticate(user=owner)
        resp = client.post(f"/api/account/positions/{position.id}/close/")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # A sell transaction must exist
        txns = TransactionModel.objects.filter(position_id=position.id, action="sell")
        assert txns.count() == 1
        txn = txns.first()
        assert txn.shares == 1000
        assert float(txn.price) == pytest.approx(12.0)

        # Position is marked closed
        position.refresh_from_db()
        assert position.is_closed is True
        assert position.closed_at is not None

    def test_partial_close_creates_transaction_and_reduces_shares(self, client, owner, position):
        client.force_authenticate(user=owner)
        resp = client.post(
            f"/api/account/positions/{position.id}/close/",
            {"shares": 400},
            format="json",
        )
        assert resp.status_code == 200

        txns = TransactionModel.objects.filter(position_id=position.id, action="sell")
        assert txns.count() == 1
        assert txns.first().shares == 400

        position.refresh_from_db()
        assert position.shares == pytest.approx(600)
        assert position.is_closed is False
        # Derived fields recalculated for remaining 600 shares
        assert float(position.market_value) == pytest.approx(600 * 12.0)

    def test_close_already_closed_returns_400(self, client, owner, position):
        position.is_closed = True
        position.save()
        client.force_authenticate(user=owner)
        resp = client.post(f"/api/account/positions/{position.id}/close/")
        assert resp.status_code == 400


# ── observer permission tests ─────────────────────────────────────────────

@pytest.mark.django_db
class TestObserverCannotMutate:
    """Observers must receive 403 on update and close."""

    def test_observer_cannot_update(self, client, observer, observer_grant, position):
        client.force_authenticate(user=observer)
        resp = client.patch(
            f"/api/account/positions/{position.id}/",
            {"shares": 1},
            format="json",
        )
        assert resp.status_code == 403

    def test_observer_cannot_close(self, client, observer, observer_grant, position):
        client.force_authenticate(user=observer)
        resp = client.post(f"/api/account/positions/{position.id}/close/")
        assert resp.status_code == 403
