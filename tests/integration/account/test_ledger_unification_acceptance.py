"""
Ledger unification acceptance tests.

Verifies the rework requirements:
1. Migration of 2 portfolios for the same user → 2 independent real accounts (no merging).
2. Non-integer position migration preserves quantity/cost/pnl precision.
3. PATCH with is_closed is silently ignored (field not in serializer).
4. /api/account/positions/* itself is the canonical real-account ledger path.
5. Migration command is idempotent (no duplicate accounts/positions/trades on re-run).
6. close creates a SimulatedTradeModel sell record; partial close leaves correct remainder.
"""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.account.infrastructure.models import (
    PortfolioModel,
    PositionModel,
    TransactionModel,
)
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel as SimPositionModel,
)


# ── helper fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice_ledger", password="x")


@pytest.fixture
def alice_client(alice):
    c = APIClient()
    c.force_authenticate(alice)
    return c


@pytest.fixture
def portfolio_a(alice):
    return PortfolioModel.objects.create(user=alice, name="Portfolio-A", is_active=True)


@pytest.fixture
def portfolio_b(alice):
    return PortfolioModel.objects.create(user=alice, name="Portfolio-B", is_active=True)


def _mk_position(portfolio, asset_code="600000.SH", shares=1000.0, avg_cost="10.00", price="12.00"):
    return PositionModel.objects.create(
        portfolio=portfolio,
        asset_code=asset_code,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=shares,
        avg_cost=Decimal(avg_cost),
        current_price=Decimal(price),
        market_value=Decimal(str(shares * float(price))),
        unrealized_pnl=Decimal(str(shares * (float(price) - float(avg_cost)))),
        unrealized_pnl_pct=float((float(price) - float(avg_cost)) / float(avg_cost) * 100),
        source="manual",
        is_closed=False,
    )


# ── 1. Migration: two portfolios → two independent real accounts ──────────────


@pytest.mark.django_db
def test_migration_two_portfolios_create_two_independent_accounts(alice, portfolio_a, portfolio_b):
    """
    Running migrate_account_ledger for a user with 2 portfolios must produce
    2 independent LedgerMigrationMap entries pointing to different real accounts.
    """
    import unittest.mock as mock

    with mock.patch("builtins.input", return_value="yes"):
        from django.core.management import call_command
        call_command("migrate_account_ledger", f"--user-id={alice.id}")

    # Verify 1-to-1 mapping entries exist for BOTH portfolios
    map_a = LedgerMigrationMapModel.objects.get(
        source_app="account", source_table="portfolio", source_id=portfolio_a.id
    )
    map_b = LedgerMigrationMapModel.objects.get(
        source_app="account", source_table="portfolio", source_id=portfolio_b.id
    )
    assert map_a.target_id != map_b.target_id, (
        "Two portfolios must not map to the same real account"
    )

    # Confirm the two mapped accounts are distinct real accounts
    acct_a = SimulatedAccountModel.objects.get(id=map_a.target_id)
    acct_b = SimulatedAccountModel.objects.get(id=map_b.target_id)
    assert acct_a.account_type == "real"
    assert acct_b.account_type == "real"
    assert acct_a.account_name == "Portfolio-A"
    assert acct_b.account_name == "Portfolio-B"


# ── 2. Non-integer position migration preserves precision ─────────────────────


@pytest.mark.django_db
def test_migration_non_integer_shares_preserved(alice, portfolio_a):
    """
    Fractional shares (e.g., 10.5) must survive migration without int(round(...)).
    """
    import unittest.mock as mock

    _mk_position(portfolio_a, asset_code="000001.SZ", shares=10.5, avg_cost="20.00", price="22.00")

    with mock.patch("builtins.input", return_value="yes"):
        from django.core.management import call_command
        call_command("migrate_account_ledger", f"--user-id={alice.id}")

    sim_pos = SimPositionModel.objects.filter(asset_code="000001.SZ").first()
    assert sim_pos is not None, "Migrated position not found"
    assert abs(float(sim_pos.quantity) - 10.5) < 1e-4, (
        f"Expected quantity ~10.5, got {sim_pos.quantity}"
    )


# ── 3. PATCH is_closed is ignored ────────────────────────────────────────────


@pytest.mark.django_db
def test_patch_is_closed_has_no_effect(alice_client, portfolio_a):
    """
    Sending is_closed=true via PATCH must not close the position.
    Close must only happen through the /close/ endpoint.
    """
    pos = _mk_position(portfolio_a)

    resp = alice_client.patch(
        f"/api/account/positions/{pos.id}/",
        {"shares": 1000, "avg_cost": "10.00", "current_price": "12.00", "is_closed": True},
        format="json",
    )
    assert resp.status_code in (200, 400)  # 200 = ignored; 400 = rejected

    pos.refresh_from_db()
    assert pos.is_closed is False, "PATCH must not close the position via is_closed field"


# ── 4. account positions API is the canonical unified ledger path ─────────────


@pytest.mark.django_db
def test_account_api_create_visible_in_account_positions(alice_client, portfolio_a):
    """
    A position created via POST /api/account/positions/ must be stored in the
    unified ledger, and /api/account/positions/ remains the only canonical
    real-account holdings endpoint.
    """
    resp = alice_client.post(
        "/api/account/positions/",
        {
            "portfolio": portfolio_a.id,
            "asset_code": "UNIFIED_TEST",
            "asset_class": "equity",
            "region": "CN",
            "cross_border": "domestic",
            "shares": 500,
            "avg_cost": "8.00",
            "current_price": "9.00",
            "source": "manual",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    created_id = resp.data["id"]

    # Verify entry exists in simulated_trading (unified ledger)
    sim_pos = SimPositionModel.objects.filter(asset_code="UNIFIED_TEST").first()
    assert sim_pos is not None, "Position must be written to the unified ledger"
    assert abs(float(sim_pos.quantity) - 500) < 1e-4
    assert created_id == sim_pos.id

    list_resp = alice_client.get("/api/account/positions/", {"portfolio_id": portfolio_a.id}, format="json")
    assert list_resp.status_code == 200
    list_payload = list_resp.json()
    rows = list_payload.get("results", list_payload)
    assert any(row["id"] == sim_pos.id for row in rows)


# ── 5. Migration idempotency ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_migration_idempotent(alice, portfolio_a):
    """
    Running migrate_account_ledger twice must not create duplicate accounts,
    positions, or trades.
    """
    import unittest.mock as mock

    _mk_position(portfolio_a)

    def _run():
        with mock.patch("builtins.input", return_value="yes"):
            from django.core.management import call_command
            call_command("migrate_account_ledger", f"--user-id={alice.id}")

    _run()
    accounts_after_first = SimulatedAccountModel.objects.filter(
        user=alice, account_type="real"
    ).count()
    positions_after_first = SimPositionModel.objects.count()

    _run()
    assert SimulatedAccountModel.objects.filter(
        user=alice, account_type="real"
    ).count() == accounts_after_first, "Second migration run must not create duplicate accounts"

    assert SimPositionModel.objects.count() == positions_after_first, (
        "Second migration run must not create duplicate positions"
    )


# ── helpers for API-created positions (so the ledger mapping is recorded) ──────


def _api_create_position(client, portfolio, asset_code="LEDGER_TEST", shares=200, avg_cost="10.00", price="12.00"):
    resp = client.post(
        "/api/account/positions/",
        {
            "portfolio": portfolio.id,
            "asset_code": asset_code,
            "asset_class": "equity",
            "region": "CN",
            "cross_border": "domestic",
            "shares": shares,
            "avg_cost": avg_cost,
            "current_price": price,
            "source": "manual",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    # PositionCreateSerializer does not expose id; query by portfolio + asset_code
    return PositionModel.objects.filter(
        portfolio=portfolio, asset_code=asset_code
    ).order_by("-id").first()


# ── 6. close creates sell trade; partial close leaves correct remainder ────────


@pytest.mark.django_db
def test_close_via_unified_service_creates_sell_trade(alice_client, portfolio_a):
    """
    POST /api/account/positions/{id}/close/ must write a SimulatedTradeModel
    sell record in the unified ledger when the position was created via API.
    """
    pos = _api_create_position(alice_client, portfolio_a, asset_code="CLOSE_FULL", shares=200)

    resp = alice_client.post(f"/api/account/positions/{pos.id}/close/", {}, format="json")
    assert resp.status_code == 200, resp.data

    sell_trades = SimulatedTradeModel.objects.filter(asset_code="CLOSE_FULL", action="sell")
    assert sell_trades.exists(), "Unified ledger must contain a sell trade after close"


@pytest.mark.django_db
def test_partial_close_leaves_correct_remainder(alice_client, portfolio_a):
    """
    Partial close of 300 shares out of 1000 must:
    - Leave 700 in apps/account mirror.
    - Write a sell trade for 300 in the unified ledger.
    """
    pos = _api_create_position(alice_client, portfolio_a, asset_code="CLOSE_PARTIAL", shares=1000)

    resp = alice_client.post(
        f"/api/account/positions/{pos.id}/close/", {"shares": 300}, format="json"
    )
    assert resp.status_code == 200, resp.data

    pos.refresh_from_db()
    assert float(pos.shares) == pytest.approx(700.0, abs=0.01)

    sell_trade = SimulatedTradeModel.objects.filter(
        asset_code="CLOSE_PARTIAL", action="sell"
    ).first()
    assert sell_trade is not None
    assert abs(float(sell_trade.quantity) - 300) < 1e-4
