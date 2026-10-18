"""HTTP, authorization and no-sync contracts for Account recorded facts."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from apps.account.application.portfolio_api_services import (
    resolve_portfolio_for_user,
)
from apps.account.infrastructure.account_read_repository import AccountReadRepository
from apps.account.infrastructure.models import (
    AssetCategoryModel,
    CapitalFlowModel,
    CurrencyModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    PositionModel,
    TransactionModel,
)
from apps.audit.infrastructure.models import OperationLogModel
from apps.simulated_trading.infrastructure import models as ledger_models
from apps.simulated_trading.infrastructure.models import (
    AccountPositionValuationSnapshotModel,
    LedgerMigrationMapModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)


def _recorded_facts_url(portfolio_id: object, query: str = "") -> str:
    """Build the detail action URL without accepting a client user ID."""

    return f"/api/account/portfolios/{portfolio_id}/recorded-facts/{query}"


@pytest.fixture(autouse=True)
def forbid_recorded_facts_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail even a swallowed network attempt during the owned API tests."""

    attempts: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        attempts.append("network")
        raise AssertionError("Recorded-facts API tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    yield
    assert not attempts, "The read attempted network I/O, even if an owner masked it"


@pytest.fixture
def recorded_facts_data(db: Any) -> dict[str, Any]:
    """Create one owner, one observer, and one unrelated portfolio."""

    owner = User.objects.create_user(username="recorded_owner", password="owner-pass")
    observer = User.objects.create_user(username="recorded_observer", password="observer-pass")
    foreign = User.objects.create_user(username="recorded_foreign", password="foreign-pass")
    currency, _ = CurrencyModel._default_manager.get_or_create(
        code="CNY",
        defaults={"name": "人民币", "symbol": "¥", "is_base": True},
    )
    category, _ = AssetCategoryModel._default_manager.get_or_create(
        code="equity",
        defaults={"name": "股票", "level": 1, "path": "股票"},
    )
    portfolio = PortfolioModel._default_manager.create(
        user=owner,
        name="记录组合",
        base_currency=currency,
        is_active=True,
    )
    foreign_portfolio = PortfolioModel._default_manager.create(
        user=foreign,
        name="外部组合",
        base_currency=currency,
        is_active=True,
    )
    position = PositionModel._default_manager.create(
        portfolio=portfolio,
        asset_code="000001.SZ",
        category=category,
        currency=currency,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=100.0,
        avg_cost=Decimal("10.50"),
        current_price=Decimal("12.00"),
        market_value=Decimal("1200.00"),
        unrealized_pnl=Decimal("150.00"),
        unrealized_pnl_pct=14.29,
        source="manual",
        source_id=None,
        is_closed=False,
    )
    grant = PortfolioObserverGrantModel._default_manager.create(
        owner_user_id=owner,
        observer_user_id=observer,
        scope="portfolio_read",
        status="active",
        expires_at=None,
    )
    return {
        "owner": owner,
        "observer": observer,
        "foreign": foreign,
        "portfolio": portfolio,
        "foreign_portfolio": foreign_portfolio,
        "position": position,
        "grant": grant,
        "currency": currency,
        "category": category,
    }


def _authenticated_get(user: User, url: str) -> Any:
    """Issue one authenticated read request."""

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get(url, HTTP_ACCEPT="application/json")
    assert response["Content-Type"].split(";", 1)[0] == "application/json"
    assert response.json() == response.data
    return response


@pytest.mark.django_db
def test_owner_gets_typed_recorded_facts_and_separate_read_clocks(
    recorded_facts_data: dict[str, Any],
) -> None:
    """Owner output keeps identity, native rows, and non-source read clocks."""
    portfolio = recorded_facts_data["portfolio"]
    legacy_position = recorded_facts_data["position"]
    ledger = SimulatedAccountModel._default_manager.create(
        user=recorded_facts_data["owner"],
        account_name="Known valuation source",
        account_type="real",
        initial_capital=Decimal("10000"),
        current_cash=Decimal("8800"),
        current_market_value=Decimal("1200"),
        total_value=Decimal("10000"),
        auto_trading_enabled=False,
    )
    unified_position = ledger_models.PositionModel._default_manager.create(
        account=ledger,
        asset_code=legacy_position.asset_code,
        asset_name=legacy_position.asset_code,
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("100"),
        avg_cost=Decimal("10.5"),
        total_cost=Decimal("1050"),
        current_price=Decimal("12"),
        market_value=Decimal("1200"),
        valuation_known=True,
        first_buy_date=timezone.now().date(),
    )
    LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.id,
        target_table="simulated_account",
        target_id=ledger.id,
    )
    LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="position",
        source_id=legacy_position.id,
        target_table="simulated_position",
        target_id=unified_position.id,
    )

    response = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )

    assert response.status_code == 200
    assert response.data["success"] is True
    assert response.data["portfolio_id"] == recorded_facts_data["portfolio"].id
    assert response.data["portfolio_name"] == "记录组合"
    assert response.data["access_role"] == "owner"
    assert response.data["owner_user_id"] == recorded_facts_data["owner"].id
    assert response.data["owner_username"] == "recorded_owner"
    assert response.data["positions"]["count"] == 1
    item = response.data["positions"]["items"][0]
    assert item["asset_code"] == "000001.SZ"
    assert item["currency_code"] == "CNY"
    assert item["currency_name"] == "人民币"
    assert item["currency_symbol"] == "¥"
    assert item["avg_cost"] == "10.5000"
    assert item["current_price"] == "12.0000"
    assert item["market_value"] == "1200.00"
    assert item["valuation_known"] is True
    assert item["valuation_status"] == "unconfirmed"
    assert item["opened_at"] is not None
    assert item["updated_at"] is not None
    assert response.data["position_read_clock"]["clock_kind"] == ("application_read_boundary")
    assert response.data["statistics_read_clock"]["source_time_status"] == "not_provided"
    assert "source_observed_at" not in response.data["position_read_clock"]
    assert response.data["statistics"]["currency_status"] == (
        "stored_values_without_fx_normalization"
    )
    assert response.data["statistics"]["valuation_known"] is True
    assert response.data["statistics"]["valuation_status"] == "unconfirmed"
    assert response.data["statistics"]["total_value"] == "1200.00"
    for key in ("position_read_clock", "statistics_read_clock"):
        clock = response.json()[key]
        start = datetime.fromisoformat(clock["read_started_at"])
        finish = datetime.fromisoformat(clock["read_finished_at"])
        assert start.utcoffset() is not None
        assert finish >= start
    for key in ("opened_at", "updated_at"):
        assert datetime.fromisoformat(item[key]).utcoffset() is not None


@pytest.mark.django_db
def test_observer_gets_read_facts_and_owner_resource_audit(
    recorded_facts_data: dict[str, Any],
) -> None:
    """Observer reads retain the existing portfolio observer audit context."""

    before_ids = set(OperationLogModel.objects.values_list("id", flat=True))

    response = _authenticated_get(
        recorded_facts_data["observer"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )

    assert response.status_code == 200
    assert response.data["access_role"] == "observer"
    audit = OperationLogModel.objects.exclude(id__in=before_ids).get(
        resource_type="portfolio_via_observer_grant",
        resource_id=str(recorded_facts_data["portfolio"].id),
        action="READ",
    )
    assert audit.user_id == recorded_facts_data["observer"].id
    assert audit.username == "recorded_observer"
    assert audit.source == "API"
    assert audit.operation_type == "API_ACCESS"
    assert audit.module == "account"
    assert audit.request_method == "GET"
    assert audit.request_path == _recorded_facts_url(recorded_facts_data["portfolio"].id)
    assert audit.response_status == 200
    assert audit.request_params["access_action"] == "recorded_facts"
    assert audit.request_params["portfolio_owner"] == "recorded_owner"


@pytest.mark.django_db
def test_endpoint_uses_authenticated_actor_not_query_user_id(
    recorded_facts_data: dict[str, Any],
) -> None:
    """A supplied user_id query value cannot change the authorization actor."""

    response = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(
            recorded_facts_data["portfolio"].id,
            f"?user_id={recorded_facts_data['foreign'].id}",
        ),
    )

    assert response.status_code == 200
    assert response.data["access_role"] == "owner"
    assert response.data["owner_user_id"] == recorded_facts_data["owner"].id


@pytest.mark.django_db
def test_unauthenticated_foreign_missing_and_malformed_requests_are_bounded(
    recorded_facts_data: dict[str, Any],
) -> None:
    """Authentication, access, lookup, and input failures stay distinct."""

    unauthenticated = APIClient().get(_recorded_facts_url(recorded_facts_data["portfolio"].id))
    assert unauthenticated.status_code == 403
    assert unauthenticated["Content-Type"].split(";", 1)[0] == "application/json"

    foreign = _authenticated_get(
        recorded_facts_data["foreign"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )
    assert foreign.status_code == 403

    missing = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(999999999),
    )
    assert missing.status_code == 404

    malformed = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url("not-an-integer"),
    )
    assert malformed.status_code == 400
    for denied in (unauthenticated, foreign, missing, malformed):
        assert "positions" not in denied.data
        assert "statistics" not in denied.data


@pytest.mark.django_db
def test_expired_and_revoked_observer_grants_are_forbidden(
    recorded_facts_data: dict[str, Any],
) -> None:
    """The existing active/expired/revoked observer policy remains authoritative."""

    grant = recorded_facts_data["grant"]
    grant.expires_at = timezone.now() - timedelta(seconds=1)
    grant.save(update_fields=["expires_at"])
    expired = _authenticated_get(
        recorded_facts_data["observer"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )
    assert expired.status_code == 403

    grant.status = "revoked"
    grant.expires_at = None
    grant.save(update_fields=["status", "expires_at"])
    revoked = _authenticated_get(
        recorded_facts_data["observer"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )
    assert revoked.status_code == 403
    for denied in (expired, revoked):
        assert "positions" not in denied.data
        assert "statistics" not in denied.data


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["owner", "observer"])
def test_empty_portfolio_is_complete_empty_result(
    recorded_facts_data: dict[str, Any],
    role: str,
) -> None:
    """An authorized portfolio with no open rows is not treated as an error."""

    empty_portfolio = PortfolioModel._default_manager.create(
        user=recorded_facts_data["owner"],
        name="空组合",
        base_currency=recorded_facts_data["currency"],
        is_active=True,
    )
    response = _authenticated_get(
        recorded_facts_data[role],
        _recorded_facts_url(empty_portfolio.id),
    )

    assert response.status_code == 200
    assert response.data["access_role"] == role
    assert response.data["positions"] == {
        "count": 0,
        "page": 1,
        "page_size": 20,
        "has_next": False,
        "items": [],
    }
    assert response.data["statistics"]["position_count"] == 0


@pytest.mark.django_db
def test_native_currency_nulls_and_unknown_zero_placeholders_are_preserved(
    recorded_facts_data: dict[str, Any],
) -> None:
    """Missing native currency, zero values, and null prices are not inferred."""

    PositionModel._default_manager.create(
        portfolio=recorded_facts_data["portfolio"],
        asset_code="000002.SZ",
        category=recorded_facts_data["category"],
        currency=None,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=0.0,
        avg_cost=Decimal("0"),
        current_price=None,
        market_value=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_pct=0.0,
        source="manual",
        source_id=None,
        is_closed=False,
    )
    response = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )

    assert response.status_code == 200
    item = response.data["positions"]["items"][1]
    assert item["shares"] == 0.0
    assert item["current_price"] is None
    assert item["market_value"] is None
    assert item["unrealized_pnl"] is None
    assert item["valuation_known"] is False
    assert item["valuation_status"] == "unknown"
    assert item["avg_cost"] == "0.0000"
    assert item["currency_code"] is None
    assert item["currency_name"] is None
    assert item["currency_symbol"] is None


@pytest.mark.django_db
def test_position_pagination_exposes_all_rows_without_silent_truncation(
    recorded_facts_data: dict[str, Any],
) -> None:
    """Pages expose count and continuation for more than the default 20 rows."""

    for index in range(2, 23):
        PositionModel._default_manager.create(
            portfolio=recorded_facts_data["portfolio"],
            asset_code=f"{index:06d}.SZ",
            category=recorded_facts_data["category"],
            currency=recorded_facts_data["currency"],
            asset_class="equity",
            region="CN",
            cross_border="domestic",
            shares=1.0,
            avg_cost=Decimal("1"),
            current_price=Decimal("1"),
            market_value=Decimal("1"),
            unrealized_pnl=Decimal("0"),
            unrealized_pnl_pct=0.0,
            source="manual",
            source_id=None,
            is_closed=False,
        )

    first = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id, "?page=1&page_size=20"),
    )
    second = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id, "?page=2&page_size=20"),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.data["positions"]["count"] == 22
    assert len(first.data["positions"]["items"]) == 20
    assert first.data["positions"]["has_next"] is True
    assert len(second.data["positions"]["items"]) == 2
    assert second.data["positions"]["has_next"] is False
    expected = set(
        PositionModel.objects.filter(
            portfolio=recorded_facts_data["portfolio"],
            is_closed=False,
        ).values_list("id", flat=True)
    )
    rows = first.data["positions"]["items"] + second.data["positions"]["items"]
    assert len(rows) == len({row["id"] for row in rows}) == len(expected)
    assert {row["id"] for row in rows} == expected
    assert all(row["portfolio"] == recorded_facts_data["portfolio"].id for row in rows)
    assert second.data["positions"]["page"] == 2
    assert second.data["positions"]["page_size"] == 20
    beyond = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id, "?page=3&page_size=20"),
    )
    assert beyond.status_code == 200
    assert beyond.data["positions"] == {
        "count": 22,
        "page": 3,
        "page_size": 20,
        "has_next": False,
        "items": [],
    }


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["?page=0", "?page=bad", "?page_size=0", "?page_size=101"])
def test_pagination_input_is_rejected_as_bad_request(
    recorded_facts_data: dict[str, Any], query: str
) -> None:
    """The interface and application both enforce positive bounded pagination."""

    response = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id, query),
    )

    assert response.status_code == 400
    assert response.data["success"] is False


@pytest.mark.django_db
def test_read_does_not_create_ledger_rows_or_call_sync_path(
    recorded_facts_data: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing mapped ledger values and full business rows survive the read."""

    ledger = SimulatedAccountModel.objects.create(
        user=recorded_facts_data["owner"],
        account_name="Existing real ledger",
        account_type="real",
        initial_capital=Decimal("10000"),
        current_cash=Decimal("8000"),
        total_value=Decimal("9200"),
        current_market_value=Decimal("1200"),
        auto_trading_enabled=False,
    )
    LedgerMigrationMapModel.objects.create(
        source_app="account",
        source_table="portfolio",
        source_id=recorded_facts_data["portfolio"].id,
        target_table="simulated_account",
        target_id=ledger.id,
    )
    ledger_models.PositionModel.objects.create(
        account=ledger,
        asset_code="000001.SZ",
        asset_name="Existing ledger row",
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("60"),
        avg_cost=Decimal("10.5"),
        total_cost=Decimal("1050"),
        current_price=Decimal("12"),
        market_value=Decimal("1200"),
        first_buy_date=timezone.now().date(),
    )
    AccountPositionValuationSnapshotModel.objects.create(
        account=ledger,
        record_date=timezone.now().date(),
        asset_code="000001.SZ",
        asset_type="equity",
        quantity=Decimal("100"),
        market_value=Decimal("1100"),
    )
    TransactionModel.objects.create(
        portfolio=recorded_facts_data["portfolio"],
        position=recorded_facts_data["position"],
        action="buy",
        asset_code="000001.SZ",
        shares=100,
        price=Decimal("10.5"),
        notional=Decimal("1050"),
        traded_at=timezone.now(),
    )

    def fail_sync(*args: object, **kwargs: object) -> int:
        raise AssertionError("recorded-facts must not synchronize the ledger")

    monkeypatch.setattr(
        "apps.simulated_trading.infrastructure.account_portfolio_repository.PortfolioApiRepository.ensure_real_account",
        fail_sync,
    )
    models = (
        PortfolioModel,
        PositionModel,
        CapitalFlowModel,
        TransactionModel,
        SimulatedAccountModel,
        ledger_models.PositionModel,
        SimulatedTradeModel,
        LedgerMigrationMapModel,
        AccountPositionValuationSnapshotModel,
    )
    before = {
        model._meta.label: list(model._default_manager.order_by("pk").values()) for model in models
    }

    response = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )

    after = {
        model._meta.label: list(model._default_manager.order_by("pk").values()) for model in models
    }
    assert response.status_code == 200
    assert after == before


@pytest.mark.django_db
def test_repository_failure_returns_bounded_503_without_partial_rows(
    recorded_facts_data: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed read never returns positions as if statistics also succeeded."""

    def fail_read(*args: object, **kwargs: object) -> list[dict[str, Any]]:
        raise RuntimeError("synthetic repository outage")

    monkeypatch.setattr(
        "apps.account.infrastructure.account_read_repository.AccountReadRepository.list_open_legacy_position_payloads",
        fail_read,
    )
    response = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )

    assert response.status_code == 503
    assert response.data == {"success": False, "error": "组合事实暂不可用"}


@pytest.mark.django_db
def test_foreign_position_row_returns_503_without_foreign_payload(
    recorded_facts_data: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repository row for another portfolio cannot cross the response boundary."""

    original = AccountReadRepository.list_open_legacy_position_payloads

    def foreign_rows(repository: AccountReadRepository, portfolio: Any) -> list[dict[str, Any]]:
        rows = original(repository, portfolio)
        assert rows
        rows[0] = {
            **rows[0],
            "portfolio": recorded_facts_data["foreign_portfolio"].id,
        }
        return rows

    monkeypatch.setattr(
        AccountReadRepository,
        "list_open_legacy_position_payloads",
        foreign_rows,
    )

    response = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )

    assert response.status_code == 503
    assert response.data == {"success": False, "error": "组合事实暂不可用"}


@pytest.mark.django_db
@pytest.mark.parametrize("grant_change", ["revoked", "expired"])
def test_scope_revoked_between_reads_returns_forbidden_without_prior_payload(
    recorded_facts_data: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    grant_change: str,
) -> None:
    """A second authorization failure cannot leak the first read's components."""

    calls = 0

    def resolve_then_revoke(*, user_id: int, portfolio_id: int | str) -> Any:
        nonlocal calls
        calls += 1
        context = resolve_portfolio_for_user(user_id=user_id, portfolio_id=portfolio_id)
        if calls == 1:
            changes = (
                {"status": "revoked"}
                if grant_change == "revoked"
                else {
                    "expires_at": timezone.now() - timedelta(seconds=1),
                }
            )
            PortfolioObserverGrantModel.objects.filter(pk=recorded_facts_data["grant"].pk).update(
                **changes
            )
        return context

    monkeypatch.setattr(
        "apps.account.application.portfolio_recorded_facts.resolve_portfolio_for_user",
        resolve_then_revoke,
    )

    response = _authenticated_get(
        recorded_facts_data["observer"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )

    assert calls == 2
    assert response.status_code == 403
    assert response.data.get("success") is not True
    assert "positions" not in response.data
    assert "statistics" not in response.data
    assert not OperationLogModel.objects.filter(
        resource_type="portfolio_via_observer_grant",
        resource_id=str(recorded_facts_data["portfolio"].id),
    ).exists()


@pytest.mark.django_db
def test_portfolio_identity_change_during_read_discards_prior_facts(
    recorded_facts_data: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real name change between authorization reads invalidates the result."""

    calls = 0

    def resolve_then_rename(*, user_id: int, portfolio_id: int | str) -> Any:
        nonlocal calls
        calls += 1
        context = resolve_portfolio_for_user(user_id=user_id, portfolio_id=portfolio_id)
        if calls == 1:
            PortfolioModel.objects.filter(pk=portfolio_id).update(name="Changed during read")
        return context

    monkeypatch.setattr(
        "apps.account.application.portfolio_recorded_facts.resolve_portfolio_for_user",
        resolve_then_rename,
    )
    response = _authenticated_get(
        recorded_facts_data["owner"],
        _recorded_facts_url(recorded_facts_data["portfolio"].id),
    )
    assert calls == 2
    assert response.status_code == 503
    assert response.data == {"success": False, "error": "组合事实暂不可用"}


@pytest.mark.django_db
def test_recorded_facts_rejects_mutating_methods_without_writes(
    recorded_facts_data: dict[str, Any],
) -> None:
    """The read action exposes no POST/PUT/PATCH/DELETE mutation path."""

    client = APIClient()
    client.force_authenticate(user=recorded_facts_data["owner"])
    url = _recorded_facts_url(recorded_facts_data["portfolio"].id)
    before = {
        "portfolios": PortfolioModel._default_manager.count(),
        "positions": PositionModel._default_manager.count(),
        "capital_flows": CapitalFlowModel._default_manager.count(),
        "simulated_accounts": SimulatedAccountModel._default_manager.count(),
        "ledger_maps": LedgerMigrationMapModel._default_manager.count(),
    }

    responses = [
        client.post(url, data={}),
        client.put(url, data={}),
        client.patch(url, data={}),
        client.delete(url),
    ]

    assert all(response.status_code == 405 for response in responses)
    after = {
        "portfolios": PortfolioModel._default_manager.count(),
        "positions": PositionModel._default_manager.count(),
        "capital_flows": CapitalFlowModel._default_manager.count(),
        "simulated_accounts": SimulatedAccountModel._default_manager.count(),
        "ledger_maps": LedgerMigrationMapModel._default_manager.count(),
    }
    assert after == before
