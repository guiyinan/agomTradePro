"""Real HTTP and ledger contracts for current-reference manual trades.

The identity, Risk V3 bundle, and calendar below are test-owned synthetic
ports. They exercise caller wiring and the real simulated-ledger UOW; they do
not qualify a production identity source or market configuration.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from importlib import import_module, util
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from django.contrib.auth.models import AbstractBaseUser
from django.db import DatabaseError
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.test import APIClient

from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
)
from apps.simulated_trading.application.manual_trade_execution import (
    SimulatedTradeExecutionReadbackUnknown,
)
from apps.simulated_trading.domain.entities import SimulatedTrade
from apps.simulated_trading.domain.execution_current_reference import (
    CurrentReferenceSelectionV1,
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionCalendarEvidence,
    SimulatedTradeExecutionReceipt,
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderFillReceiptModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.trade_mapper import SimulatedTradeMapper
from apps.simulated_trading.interface import sdk_contract_views as sdk_contract_view_module
from apps.simulated_trading.interface import views as view_module
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _bundle,
    _calendar,
    _IdentityReader,
    _RuleReader,
    _seed_fee_policy,
)

# HTTP wiring uses rollback isolation; lock/concurrent-commit cases live in
# the native repository component suite, which owns its isolated schema.
pytestmark = pytest.mark.django_db

_TRADE_RESPONSE_FIELDS = frozenset(
    {
        "trade_id",
        "account_id",
        "asset_code",
        "asset_name",
        "asset_type",
        "action",
        "quantity",
        "price",
        "amount",
        "commission",
        "slippage",
        "total_cost",
        "fee_amounts_known",
        "fee_amounts_status",
        "cost_basis_known",
        "cost_basis_status",
        "realized_pnl_known",
        "realized_pnl_status",
        "realized_pnl_pct_known",
        "realized_pnl",
        "realized_pnl_pct",
        "reason",
        "signal_id",
        "order_date",
        "execution_date",
        "execution_time",
        "status",
    }
)


class _FixedClock:
    """Return one exact fixture cutoff for reads and locked ledger work."""

    def now(self) -> datetime:
        return AS_OF


class _SyntheticCurrentIdentityReader:
    """Supply the test-owned explicit mapping without a provider or DB read."""

    def __init__(self, *, available: bool) -> None:
        self.evidence = _current_identity() if available else None
        self.resolve_calls = 0
        self.read_calls = 0

    def resolve_current_reference_identity(
        self,
        *,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        assert asset_code == "600000.SH"
        assert as_of == AS_OF
        self.resolve_calls += 1
        return self.evidence

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        assert security_id == "SH.UOW.SECURITY"
        assert asset_code == "600000.SH"
        assert as_of == AS_OF
        self.read_calls += 1
        return self.evidence


class _SyntheticCalendarReader:
    """Return a complete test-owned publication-bound exchange calendar."""

    def __init__(self) -> None:
        self.evidence = _calendar(
            as_of=AS_OF,
            open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
            exchange="SSE",
        )
        self.calls = 0

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence:
        assert exchange == "SSE"
        assert as_of == AS_OF
        self.calls += 1
        self.evidence.validate_for(as_of)
        return self.evidence


class _OwnedTradeReader:
    """Read an exact persisted trade only inside the authenticated owner scope."""

    def get_owned_trade_by_id(
        self,
        *,
        trade_id: int,
        account_id: int,
        user_id: int,
    ) -> SimulatedTrade | None:
        row = (
            SimulatedTradeModel._default_manager.using("default")
            .filter(pk=trade_id, account_id=account_id, account__user_id=user_id)
            .first()
        )
        return SimulatedTradeMapper.to_entity(row) if row is not None else None


class _CapturingExecutionUseCase:
    """Preserve the exact caller cutoff while delegating to the real ledger UOW."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.intents: list[object] = []

    def execute(
        self,
        intent: SimulatedTradeIntent,
        *,
        as_of: datetime | None = None,
    ) -> SimulatedTradeExecutionReceipt:
        assert as_of == AS_OF
        self.intents.append(intent)
        return self.delegate.execute(intent, as_of=as_of)


class _CallerState:
    def __init__(self, *, source_available: bool) -> None:
        self.repository = DjangoSimulatedTradeExecutionRepository(using="default")
        self.identity_reader = _SyntheticCurrentIdentityReader(available=source_available)
        self.calendar_reader = _SyntheticCalendarReader()
        self.clock = _FixedClock()
        self.bundle = _bundle(as_of=AS_OF)
        self.rule_reader = _RuleReader(self.bundle)
        self.execution = _CapturingExecutionUseCase(
            ExecuteSettlementBoundSimulatedTradeUseCase(
                rule_reader=self.rule_reader,
                identity_reader=self.identity_reader,
                calendar_reader=self.calendar_reader,
                fee_policy_reader=self.repository,
                repository=self.repository,
                clock=self.clock,
            )
        )
        self.builder_calls = 0

    def build_service(self) -> object:
        self.builder_calls += 1
        module_name = "apps.simulated_trading.application.manual_trade_execution"
        if util.find_spec(module_name) is None:
            pytest.fail("current-reference manual application service is not implemented")
        module = import_module(module_name)
        use_case_type = getattr(module, "ExecuteCurrentReferenceManualTradeUseCase", None)
        assert use_case_type is not None, "current-reference manual use case is not exported"
        return use_case_type(
            identity_reader=self.identity_reader,
            repository=self.repository,
            trade_reader=_OwnedTradeReader(),
            execution_use_case=self.execution,
            clock=self.clock,
        )


def _current_identity() -> ExecutionInstrumentIdentityEvidenceV2:
    """Build a self-consistent explicit synthetic selector and source pair."""

    source = _IdentityReader("SSE").get_execution_instrument_identity(
        security_id="SH.UOW.SECURITY",
        asset_code="600000.SH",
        as_of=AS_OF,
    )
    assert source is not None
    occurrence_at = AS_OF - timedelta(hours=2)
    source = replace(
        source,
        identity_valid_from=AS_OF - timedelta(hours=1),
        identity_valid_until=AS_OF + timedelta(hours=1),
    )
    selection = CurrentReferenceSelectionV1(
        purpose="normal_simulated_current_reference",
        profile_id="fixture-profile-id",
        profile_key="simulated-current-reference.v1",
        environment="test",
        profile_version=1,
        profile_content_hash="a" * 64,
        runtime_snapshot_id="fixture-runtime-snapshot",
        runtime_snapshot_hash="b" * 64,
        selector_content_hash="c" * 64,
        profile_activated_at=AS_OF - timedelta(hours=4),
        runtime_snapshot_generated_at=AS_OF - timedelta(hours=3),
        selected_at=AS_OF,
        max_local_reference_age_seconds=10_800,
    )
    return ExecutionInstrumentIdentityEvidenceV2(
        source_evidence=source,
        selection=selection,
        source_occurrence_id=uuid4(),
        reference_response_completed_at=occurrence_at,
    )


def _install_manual_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    account: SimulatedAccountModel,
    source_available: bool = True,
) -> _CallerState:
    _backdate_account_for_fixture_cutoff(account)
    state = _CallerState(source_available=source_available)
    monkeypatch.setattr(
        view_module,
        "build_current_reference_manual_trade_use_case",
        state.build_service,
        raising=False,
    )
    return state


def _install_close_manual_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    account: SimulatedAccountModel,
    source_available: bool = True,
) -> _CallerState:
    """Inject the same real-UOW fixture into both manual and close API views."""

    state = _install_manual_service(
        monkeypatch,
        account=account,
        source_available=source_available,
    )
    monkeypatch.setattr(
        sdk_contract_view_module,
        "build_current_reference_manual_trade_use_case",
        state.build_service,
        raising=False,
    )
    return state


def _install_legacy_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    calls: list[str] = []

    def legacy_factory(*_args: object, **_kwargs: object) -> object:
        def execute(**_params: object) -> None:
            calls.append("legacy")
            raise ValueError("legacy buy/sell caller must not handle this request")

        return SimpleNamespace(execute=execute)

    monkeypatch.setattr(view_module, "ExecuteBuyOrderUseCase", legacy_factory)
    monkeypatch.setattr(view_module, "ExecuteSellOrderUseCase", legacy_factory)
    return calls


def _seed_fee(account: SimulatedAccountModel) -> None:
    row = FeeConfigModel.objects.create(
        config_name=f"current-manual-{account.pk}-{uuid4()}",
        asset_type="equity",
        min_commission=1.0,
        is_default=False,
        is_active=False,
    )
    _seed_fee_policy(row)


def _backdate_account_for_fixture_cutoff(account: SimulatedAccountModel) -> None:
    """Keep persisted owner/account knowledge clocks before the fixed test cutoff."""

    SimulatedAccountModel._default_manager.using("default").filter(pk=account.pk).update(
        created_at=AS_OF - timedelta(days=30),
        updated_at=AS_OF - timedelta(days=1),
        start_date=AS_OF.date() - timedelta(days=30),
    )
    account.refresh_from_db()


def _position(account: SimulatedAccountModel) -> PositionModel:
    account.current_market_value = Decimal("10000.00")
    account.total_value = Decimal("110000.00")
    account.save(update_fields=["current_market_value", "total_value"])
    position = PositionModel.objects.create(
        account=account,
        asset_code="600000.SH",
        asset_name="浦发银行",
        asset_type="equity",
        quantity=Decimal("1000"),
        available_quantity=Decimal("1000"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("10000.00"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("10000.00"),
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 1),
    )
    PositionModel._default_manager.using("default").filter(pk=position.pk).update(
        created_at=AS_OF - timedelta(days=10),
        last_update_date=AS_OF.date() - timedelta(days=1),
    )
    return position


def _body(
    *, action: str = "buy", quantity: int = 100, asset_type: str = "equity"
) -> dict[str, Any]:
    return {
        "asset_code": "600000.SH",
        "asset_name": "浦发银行",
        "asset_type": asset_type,
        "action": action,
        "quantity": quantity,
        "price": "10.00",
    }


def _post(
    client: APIClient,
    *,
    account_id: int,
    body: dict[str, Any] | None = None,
    idempotency_key: str | None = "manual-current-ref-key-001",
) -> Response:
    headers = {"HTTP_IDEMPOTENCY_KEY": idempotency_key} if idempotency_key is not None else {}
    return client.post(
        f"/api/simulated-trading/accounts/{account_id}/trade/",
        body if body is not None else _body(),
        format="json",
        **headers,
    )


def _close_financial_snapshot(account_id: int) -> tuple[tuple[dict[str, Any], ...], ...]:
    """Read every financial field, including receipts linked through either owner parent."""

    scopes = (
        SimulatedAccountModel._base_manager.filter(pk=account_id),
        PositionModel._base_manager.filter(account_id=account_id),
        SimulatedTradeModel._base_manager.filter(account_id=account_id),
        SimulatedOrderReservationModel._base_manager.filter(account_id=account_id),
        SimulatedOrderFillReceiptModel._base_manager.filter(
            Q(reservation__account_id=account_id) | Q(trade__account_id=account_id)
        ),
    )
    return tuple(tuple(rows.order_by("pk").values()) for rows in scopes)


def _close_body(
    *,
    shares: int = 1000,
    price: str = "12.0000",
    reason: str | None = None,
) -> dict[str, Any]:
    """Build the exact simulated close body without deriving inputs from Position."""

    body: dict[str, Any] = {
        "asset_code": "600000.SH",
        "close_shares": shares,
        "close_price": price,
    }
    if reason is not None:
        body["reason"] = reason
    return body


def _close_post(
    client: APIClient,
    *,
    account_id: int,
    body: dict[str, Any] | None = None,
    idempotency_key: str | None = "manual-close-key-001",
) -> Response:
    """Post one exact close request with its caller-owned operation key."""

    headers = {"HTTP_IDEMPOTENCY_KEY": idempotency_key} if idempotency_key is not None else {}
    return client.post(
        f"/api/simulated-trading/accounts/{account_id}/positions/close/",
        body if body is not None else _close_body(),
        format="json",
        **headers,
    )


@pytest.mark.parametrize("action", ["buy", "sell"])
def test_current_manual_trade_executes_both_sides_through_the_real_uow(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    auth_user: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    _seed_fee(owned_account)
    if action == "sell":
        _position(owned_account)
    state = _install_manual_service(
        monkeypatch,
        account=owned_account,
    )
    legacy_calls = _install_legacy_guards(monkeypatch)

    response = _post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_body(action=action),
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert set(payload) == {"success", "message", "trade", "replayed"}
    assert payload["success"] is True
    assert isinstance(payload["message"], str)
    assert payload["replayed"] is False
    assert set(payload["trade"]) == _TRADE_RESPONSE_FIELDS
    assert payload["trade"]["action"] == action
    assert payload["trade"]["asset_type"] == "equity"
    assert payload["trade"]["quantity"] == 100
    assert Decimal(payload["trade"]["price"]) == Decimal("10.00")
    trade_payload = payload["trade"]
    assert trade_payload["fee_amounts_known"] is True
    assert trade_payload["fee_amounts_status"] == "known"
    if action == "buy":
        assert trade_payload["cost_basis_known"] is True
        assert trade_payload["cost_basis_status"] == "known"
        assert trade_payload["realized_pnl_known"] is None
        assert trade_payload["realized_pnl_status"] == "not_applicable"
        assert trade_payload["realized_pnl_pct_known"] is None
        assert trade_payload["realized_pnl"] is None
        assert trade_payload["realized_pnl_pct"] is None
    else:
        assert trade_payload["cost_basis_known"] is None
        assert trade_payload["cost_basis_status"] == "unknown"
        assert trade_payload["realized_pnl_known"] is False
        assert trade_payload["realized_pnl_status"] == "unknown"
        assert trade_payload["realized_pnl_pct_known"] is False
        assert trade_payload["realized_pnl"] is None
        assert trade_payload["realized_pnl_pct"] is None

    rows = SimulatedTradeModel.objects.filter(account=owned_account)
    assert rows.count() == 1
    row = rows.get()
    assert row.action == action
    assert row.asset_type == "equity"
    assert row.fee_amounts_known is True
    if action == "buy":
        assert row.cost_basis_known is True
    else:
        assert row.cost_basis_known is None
    assert row.idempotency_key == "manual-current-ref-key-001"
    assert row.settlement_plan_binding_version == 3
    assert len(state.execution.intents) == 1
    intent = state.execution.intents[0]
    assert intent.side is SimulatedTradeSide(action)
    assert intent.quantity == Decimal("100")
    assert type(intent.quantity) is Decimal
    assert intent.price == Decimal("10.00")
    assert type(intent.price) is Decimal
    assert intent.reason == ""
    assert intent.signal_id is None
    assert intent.account_id == owned_account.pk
    assert intent.user_id == auth_user.id
    assert legacy_calls == []


def test_same_key_replays_exact_saved_trade_without_second_source_or_ledger_write(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    auth_user: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_fee(owned_account)
    state = _install_manual_service(
        monkeypatch,
        account=owned_account,
    )
    legacy_calls = _install_legacy_guards(monkeypatch)

    first = _post(authenticated_client, account_id=owned_account.pk)
    source_reads_after_first = (
        state.identity_reader.resolve_calls,
        state.identity_reader.read_calls,
    )
    execution_count_after_first = len(state.execution.intents)
    second = _post(authenticated_client, account_id=owned_account.pk)

    assert first.status_code == second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["replayed"] is False
    assert second_payload["replayed"] is True
    assert second_payload["trade"] == first_payload["trade"]
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 1
    assert (
        state.identity_reader.resolve_calls,
        state.identity_reader.read_calls,
    ) == source_reads_after_first
    assert len(state.execution.intents) == execution_count_after_first == 1
    assert legacy_calls == []


def test_same_key_with_changed_intent_conflicts_before_a_second_source_read(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    auth_user: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_fee(owned_account)
    state = _install_manual_service(
        monkeypatch,
        account=owned_account,
    )
    legacy_calls = _install_legacy_guards(monkeypatch)
    first = _post(authenticated_client, account_id=owned_account.pk)
    source_reads_after_first = (
        state.identity_reader.resolve_calls,
        state.identity_reader.read_calls,
    )

    conflict = _post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_body(quantity=200),
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    payload = conflict.json()
    assert set(payload) == {"success", "error", "code"}
    assert payload["success"] is False
    assert payload["code"] == "SIMULATED_TRADE_IDEMPOTENCY_CONFLICT"
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 1
    assert (
        state.identity_reader.resolve_calls,
        state.identity_reader.read_calls,
    ) == source_reads_after_first
    assert len(state.execution.intents) == 1
    assert legacy_calls == []


def test_missing_idempotency_header_is_a_400_before_factory_or_ledger_access(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    auth_user: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_manual_service(
        monkeypatch,
        account=owned_account,
    )
    legacy_calls = _install_legacy_guards(monkeypatch)

    response = _post(
        authenticated_client,
        account_id=owned_account.pk,
        idempotency_key=None,
    )

    assert response.status_code == 400
    payload = response.json()
    assert set(payload) == {"success", "error", "code"}
    assert payload["success"] is False
    assert isinstance(payload["code"], str) and payload["code"]
    assert state.builder_calls == 0
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 0
    assert state.identity_reader.resolve_calls == state.identity_reader.read_calls == 0
    assert legacy_calls == []


def test_foreign_owner_keeps_the_existing_access_status_and_envelope(
    authenticated_client: APIClient,
    django_user_model: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = django_user_model.objects.create_user(username="manual-trade-foreign-owner")
    foreign_account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name="foreign-manual-account",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
    )
    builder_calls: list[str] = []
    monkeypatch.setattr(
        view_module,
        "build_current_reference_manual_trade_use_case",
        lambda: builder_calls.append("called"),
        raising=False,
    )
    legacy_calls = _install_legacy_guards(monkeypatch)

    response = _post(authenticated_client, account_id=foreign_account.pk)

    assert response.status_code == 403
    assert response.json() == {"success": False, "error": "无权操作该账户"}
    assert builder_calls == []
    assert SimulatedTradeModel.objects.filter(account=foreign_account).count() == 0
    assert legacy_calls == []


def test_unavailable_current_identity_returns_typed_400_without_legacy_write(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    auth_user: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_fee(owned_account)
    owned_account.refresh_from_db()
    cash_before = owned_account.current_cash
    state = _install_manual_service(
        monkeypatch,
        account=owned_account,
        source_available=False,
    )
    legacy_calls = _install_legacy_guards(monkeypatch)

    response = _post(authenticated_client, account_id=owned_account.pk)

    assert response.status_code == 400
    payload = response.json()
    assert set(payload) == {"success", "error", "code"}
    assert payload["success"] is False
    assert payload["code"] == "EXECUTION_INSTRUMENT_IDENTITY_UNAVAILABLE"
    assert state.identity_reader.resolve_calls == 1
    assert state.execution.intents == []
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 0
    owned_account.refresh_from_db()
    assert owned_account.current_cash == cash_before
    assert owned_account.total_trades == 0
    assert legacy_calls == []


def test_non_equity_is_rejected_without_being_misclassified_as_a_trade(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    auth_user: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_manual_service(
        monkeypatch,
        account=owned_account,
    )
    legacy_calls = _install_legacy_guards(monkeypatch)

    response = _post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_body(asset_type="fund"),
    )

    assert response.status_code == 400
    payload = response.json()
    assert set(payload) == {"success", "error", "code"}
    assert payload["success"] is False
    assert isinstance(payload["code"], str) and payload["code"]
    assert state.identity_reader.resolve_calls == state.identity_reader.read_calls == 0
    assert state.execution.intents == []
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 0
    assert legacy_calls == []


def test_default_manual_factory_returns_unavailable_without_legacy_write(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real factory rejects absent current selection without a legacy write."""

    legacy_calls = _install_legacy_guards(monkeypatch)
    owned_account.refresh_from_db()
    cash_before = owned_account.current_cash

    response = _post(authenticated_client, account_id=owned_account.pk)

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["code"] == "EXECUTION_INSTRUMENT_IDENTITY_UNAVAILABLE"
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 0
    owned_account.refresh_from_db()
    assert owned_account.current_cash == cash_before
    assert legacy_calls == []


@pytest.mark.parametrize(("field", "value"), [("quantity", 0), ("price", None)])
def test_invalid_manual_body_returns_typed_400_before_any_factory(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    """Financial input errors keep the documented error contract and cause no writes."""

    builder_calls: list[str] = []
    monkeypatch.setattr(
        view_module,
        "build_current_reference_manual_trade_use_case",
        lambda: builder_calls.append("called"),
        raising=False,
    )
    body = _body()
    body[field] = value
    legacy_calls = _install_legacy_guards(monkeypatch)

    response = _post(authenticated_client, account_id=owned_account.pk, body=body)

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert set(payload) == {"success", "error", "code"}
    assert payload["success"] is False
    assert isinstance(payload["error"], str) and payload["error"]
    assert isinstance(payload["code"], str) and payload["code"]
    assert builder_calls == legacy_calls == []
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 0


_CLOSE_RECEIPT_FIELDS = frozenset(
    {
        "trade_id",
        "account_id",
        "idempotency_key",
        "request_payload_hash",
        "side",
        "asset_code",
        "quantity",
        "price",
        "amount",
        "commission",
        "transfer_fee",
        "stamp_duty",
        "slippage",
        "total_cost",
        "settlement_status",
        "settlement_release_date",
        "replayed",
    }
)


@pytest.mark.django_db
def test_exact_close_returns_fee_receipt_and_replays_after_full_close_and_reentry(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    auth_user: AbstractBaseUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full close is one fee-aware SELL, and replay ignores a newer Position."""

    _seed_fee(owned_account)
    original_position = _position(owned_account)
    state = _install_close_manual_service(monkeypatch, account=owned_account)
    legacy_calls: list[str] = []

    def legacy_close(**_kwargs: object) -> dict[str, object]:
        legacy_calls.append("legacy")
        return {
            "account_id": owned_account.pk,
            "asset_code": "600000.SH",
            "closed": True,
            "remaining_quantity": "0",
        }

    monkeypatch.setattr(
        sdk_contract_view_module.interface_services,
        "close_account_position",
        legacy_close,
    )
    key = "exact-full-close-001"
    first = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_close_body(shares=1000, price="12.0000"),
        idempotency_key=key,
    )

    assert first.status_code == 200
    assert first["Content-Type"].startswith("application/json")
    payload = first.json()
    assert set(payload) == {"success", "trade", "receipt", "replayed"}
    assert payload["success"] is True
    assert payload["replayed"] is False
    assert payload["trade"]["trade_id"] == payload["receipt"]["trade_id"]
    assert payload["trade"]["action"] == "sell"
    assert payload["trade"]["asset_code"] == "600000.SH"
    assert payload["trade"]["asset_name"] == "600000.SH"
    assert payload["trade"]["asset_type"] == "equity"
    assert payload["trade"]["quantity"] == 1000
    assert Decimal(payload["trade"]["price"]) == Decimal("12.0000")
    assert Decimal(payload["trade"]["amount"]) == Decimal("12000.00")
    assert Decimal(payload["trade"]["commission"]) == Decimal("3.60")
    assert Decimal(payload["trade"]["slippage"]) == Decimal("12.00")
    assert Decimal(payload["trade"]["total_cost"]) == Decimal("27.84")
    assert payload["trade"]["fee_amounts_known"] is True
    assert payload["trade"]["cost_basis_known"] is None
    assert payload["trade"]["cost_basis_status"] == "unknown"
    assert payload["trade"]["realized_pnl_known"] is False
    assert payload["trade"]["realized_pnl_status"] == "unknown"
    assert payload["trade"]["realized_pnl_pct_known"] is False
    assert payload["trade"]["realized_pnl"] is None
    assert payload["trade"]["realized_pnl_pct"] is None
    assert payload["trade"]["reason"] == "平仓"
    receipt = payload["receipt"]
    assert set(receipt) == _CLOSE_RECEIPT_FIELDS
    assert receipt["trade_id"] == payload["trade"]["trade_id"]
    assert receipt["account_id"] == owned_account.pk
    assert receipt["idempotency_key"] == key
    assert len(receipt["request_payload_hash"]) == 64
    assert receipt["side"] == "sell"
    assert receipt["asset_code"] == "600000.SH"
    assert Decimal(receipt["quantity"]) == Decimal("1000")
    assert Decimal(receipt["price"]) == Decimal("12.0000")
    assert Decimal(receipt["amount"]) == Decimal("12000.00")
    assert Decimal(receipt["commission"]) == Decimal("3.60")
    assert Decimal(receipt["transfer_fee"]) == Decimal("0.24")
    assert Decimal(receipt["stamp_duty"]) == Decimal("12.00")
    assert Decimal(receipt["slippage"]) == Decimal("12.00")
    assert Decimal(receipt["total_cost"]) == Decimal("27.84")
    assert receipt["settlement_status"] is None
    assert receipt["settlement_release_date"] is None
    assert receipt["replayed"] is False
    assert "closed" not in payload
    assert "remaining_quantity" not in payload
    assert not PositionModel.objects.filter(pk=original_position.pk).exists()
    assert SimulatedTradeModel.objects.filter(account=owned_account, action="sell").count() == 1
    owned_account.refresh_from_db()
    assert owned_account.current_cash == Decimal("111972.16")
    assert owned_account.current_market_value == Decimal("0.00")
    assert owned_account.total_value == Decimal("111972.16")
    assert owned_account.total_trades == 1
    assert len(state.execution.intents) == 1
    assert state.execution.intents[0].side is SimulatedTradeSide.SELL
    assert state.execution.intents[0].quantity == Decimal("1000")
    assert state.execution.intents[0].price == Decimal("12.0000")
    assert state.execution.intents[0].asset_name == "600000.SH"
    assert state.execution.intents[0].signal_id is None
    assert legacy_calls == []

    reentry = _post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_body(action="buy", quantity=100),
        idempotency_key="manual-reentry-after-close-001",
    )
    assert reentry.status_code == 200
    reentered_position = PositionModel.objects.get(account=owned_account, asset_code="600000.SH")
    assert reentered_position.quantity == Decimal("100.000000")
    owned_account.refresh_from_db()
    account_before_replay = (
        owned_account.current_cash,
        owned_account.current_market_value,
        owned_account.total_value,
    )
    intents_before_replay = len(state.execution.intents)
    identity_calls_before_replay = (
        state.identity_reader.resolve_calls,
        state.identity_reader.read_calls,
    )
    monkeypatch.setattr(state.clock, "now", lambda: pytest.fail("replay read the current clock"))
    monkeypatch.setattr(
        state.identity_reader,
        "resolve_current_reference_identity",
        lambda **_kwargs: pytest.fail("replay read current identity"),
    )
    monkeypatch.setattr(
        state.identity_reader,
        "get_execution_instrument_identity",
        lambda **_kwargs: pytest.fail("replay reread current identity"),
    )

    financial_before_replay = _close_financial_snapshot(owned_account.pk)
    replay = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_close_body(shares=1000, price="12.0000"),
        idempotency_key=key,
    )

    assert replay.status_code == 200
    replay_payload = replay.json()
    assert replay_payload["replayed"] is True
    assert replay_payload["trade"] == payload["trade"]
    assert replay_payload["receipt"] == {**receipt, "replayed": True}
    assert SimulatedTradeModel.objects.filter(account=owned_account, action="sell").count() == 1
    assert len(state.execution.intents) == intents_before_replay == 2
    assert (
        state.identity_reader.resolve_calls,
        state.identity_reader.read_calls,
    ) == identity_calls_before_replay
    assert PositionModel.objects.filter(pk=reentered_position.pk).values_list(
        "quantity", flat=True
    ).get() == Decimal("100.000000")
    owned_account.refresh_from_db()
    assert (
        owned_account.current_cash,
        owned_account.current_market_value,
        owned_account.total_value,
    ) == account_before_replay
    assert legacy_calls == []
    assert _close_financial_snapshot(owned_account.pk) == financial_before_replay


@pytest.mark.parametrize(
    ("field", "value"),
    [("close_shares", 101), ("close_price", "12.0001"), ("reason", "changed reason")],
)
def test_close_same_key_with_changed_body_conflicts_without_new_reads_or_writes(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    """Shares, explicit price, and reason are all part of the replayed intent."""

    _seed_fee(owned_account)
    position = _position(owned_account)
    state = _install_close_manual_service(monkeypatch, account=owned_account)
    key = "close-body-conflict-001"
    first = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_close_body(shares=100, price="12.0000"),
        idempotency_key=key,
    )
    assert first.status_code == 200
    owned_account.refresh_from_db()
    position.refresh_from_db()
    snapshot_before_conflict = (
        owned_account.current_cash,
        owned_account.current_market_value,
        owned_account.total_value,
        position.quantity,
        position.available_quantity,
        SimulatedTradeModel.objects.filter(account=owned_account).count(),
    )
    source_calls_before_conflict = (
        state.identity_reader.resolve_calls,
        state.identity_reader.read_calls,
    )
    intents_before_conflict = len(state.execution.intents)
    changed_body = _close_body(shares=100, price="12.0000")
    changed_body[field] = value

    financial_before_conflict = _close_financial_snapshot(owned_account.pk)
    conflict = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=changed_body,
        idempotency_key=key,
    )

    assert conflict.status_code == 409
    assert conflict["Content-Type"].startswith("application/json")
    assert conflict.json()["code"] == "SIMULATED_TRADE_IDEMPOTENCY_CONFLICT"
    owned_account.refresh_from_db()
    position.refresh_from_db()
    assert (
        owned_account.current_cash,
        owned_account.current_market_value,
        owned_account.total_value,
        position.quantity,
        position.available_quantity,
        SimulatedTradeModel.objects.filter(account=owned_account).count(),
    ) == snapshot_before_conflict
    assert (
        state.identity_reader.resolve_calls,
        state.identity_reader.read_calls,
    ) == source_calls_before_conflict
    assert len(state.execution.intents) == intents_before_conflict == 1
    assert _close_financial_snapshot(owned_account.pk) == financial_before_conflict


@pytest.mark.parametrize(
    ("unknown_type", "expected_code"),
    [
        (SimulatedTradeExecutionReadbackUnknown, "SIMULATED_TRADE_EXECUTION_READBACK_UNKNOWN"),
        (DatabaseError, "SIMULATED_TRADE_EXECUTION_UNAVAILABLE"),
    ],
)
@pytest.mark.django_db
def test_close_unknown_after_real_uow_write_is_retryable_with_same_key(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    unknown_type: type[SimulatedTradeExecutionReadbackUnknown] | type[DatabaseError],
    expected_code: str,
) -> None:
    """A lost readback response is unknown, then the committed receipt replays once."""

    _seed_fee(owned_account)
    original_position = _position(owned_account)
    state = _install_close_manual_service(monkeypatch, account=owned_account)
    build_real_use_case = state.build_service
    unknown_pending = True

    def build_unknown_once_service() -> object:
        nonlocal unknown_pending
        service = build_real_use_case()
        execute = service.execute

        def execute_with_lost_readback(*args: object, **kwargs: object) -> object:
            nonlocal unknown_pending
            result = execute(*args, **kwargs)
            if unknown_pending:
                unknown_pending = False
                raise unknown_type("postgresql://admin:raw-secret@example.test/ledger")
            return result

        return SimpleNamespace(execute=execute_with_lost_readback)

    monkeypatch.setattr(
        sdk_contract_view_module,
        "build_current_reference_manual_trade_use_case",
        build_unknown_once_service,
    )
    key = "close-readback-unknown-001"
    body = _close_body(shares=1000, price="12.0000")
    unknown = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=body,
        idempotency_key=key,
    )

    assert unknown.status_code == 503
    assert unknown["Content-Type"].startswith("application/json")
    assert unknown.json() == {
        "success": False,
        "error": "平仓结果暂无法确认，请使用相同请求和幂等键重试。",
        "code": expected_code,
        "effects_indeterminate": True,
    }
    assert "raw-secret" not in unknown.content.decode("utf-8")
    assert "postgresql://" not in caplog.text
    assert SimulatedTradeModel.objects.filter(account=owned_account, action="sell").count() == 1
    assert not PositionModel.objects.filter(pk=original_position.pk).exists()
    owned_account.refresh_from_db()
    cash_after_first_write = owned_account.current_cash
    assert cash_after_first_write == Decimal("111972.16")
    assert len(state.execution.intents) == 1

    financial_before_retry = _close_financial_snapshot(owned_account.pk)
    retry = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=body,
        idempotency_key=key,
    )

    assert retry.status_code == 200
    assert retry["Content-Type"].startswith("application/json")
    retry_payload = retry.json()
    assert retry_payload["replayed"] is True
    assert retry_payload["receipt"]["replayed"] is True
    assert retry_payload["trade"]["trade_id"] == retry_payload["receipt"]["trade_id"]
    assert SimulatedTradeModel.objects.filter(account=owned_account, action="sell").count() == 1
    assert len(state.execution.intents) == 1
    owned_account.refresh_from_db()
    assert owned_account.current_cash == cash_after_first_write
    assert _close_financial_snapshot(owned_account.pk) == financial_before_retry


@pytest.mark.django_db
def test_close_uow_result_unknown_after_real_write_preserves_code_and_replays(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An invalid post-write UOW result is unknown and the committed receipt replays."""

    _seed_fee(owned_account)
    original_position = _position(owned_account)
    state = _install_close_manual_service(monkeypatch, account=owned_account)
    real_execute_trade = state.repository.execute_trade
    return_invalid_once = True
    repository_calls: list[str] = []

    def execute_then_return_invalid_result(*args: Any, **kwargs: Any) -> Any:
        nonlocal return_invalid_once
        repository_calls.append("execute_trade")
        result = real_execute_trade(*args, **kwargs)
        if return_invalid_once:
            return_invalid_once = False
            return object()
        return result

    monkeypatch.setattr(state.repository, "execute_trade", execute_then_return_invalid_result)
    key = "close-uow-result-unknown-001"
    body = _close_body(shares=1000, price="12.0000")
    unknown = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=body,
        idempotency_key=key,
    )

    assert unknown.status_code == 503
    assert unknown["Content-Type"].startswith("application/json")
    assert unknown.json() == {
        "success": False,
        "error": "平仓结果暂无法确认，请使用相同请求和幂等键重试。",
        "code": "SIMULATED_TRADE_EXECUTION_RESULT_UNKNOWN",
        "effects_indeterminate": True,
    }
    assert "exception_type=SimulatedTradeExecutionResultUnknown" in caplog.text
    assert SimulatedTradeModel.objects.filter(account=owned_account, action="sell").count() == 1
    assert not PositionModel.objects.filter(pk=original_position.pk).exists()
    owned_account.refresh_from_db()
    cash_after_first_write = owned_account.current_cash
    assert cash_after_first_write == Decimal("111972.16")
    assert len(state.execution.intents) == 1
    assert repository_calls == ["execute_trade"]

    financial_before_retry = _close_financial_snapshot(owned_account.pk)
    retry = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=body,
        idempotency_key=key,
    )

    assert retry.status_code == 200
    assert retry["Content-Type"].startswith("application/json")
    payload = retry.json()
    assert payload["replayed"] is True
    assert payload["receipt"]["replayed"] is True
    assert payload["trade"]["trade_id"] == payload["receipt"]["trade_id"]
    assert SimulatedTradeModel.objects.filter(account=owned_account, action="sell").count() == 1
    assert len(state.execution.intents) == 1
    assert repository_calls == ["execute_trade"]
    owned_account.refresh_from_db()
    assert owned_account.current_cash == cash_after_first_write
    assert _close_financial_snapshot(owned_account.pk) == financial_before_retry


@pytest.mark.django_db
def test_close_with_no_available_shares_blocks_without_financial_mutation(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact close reuses the UOW's current available-share and T+1 guard."""

    _seed_fee(owned_account)
    position = _position(owned_account)
    PositionModel._default_manager.using("default").filter(pk=position.pk).update(
        available_quantity=Decimal("0.000000")
    )
    position.refresh_from_db()
    state = _install_close_manual_service(monkeypatch, account=owned_account)
    owned_account.refresh_from_db()
    snapshot_before = (
        owned_account.current_cash,
        owned_account.current_market_value,
        owned_account.total_value,
        owned_account.total_trades,
        position.quantity,
        position.available_quantity,
        position.total_cost,
    )

    financial_before = _close_financial_snapshot(owned_account.pk)
    response = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_close_body(shares=100, price="12.0000"),
        idempotency_key="close-blocked-by-available-001",
    )

    assert response.status_code == 422
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["code"] == "SELLABLE_BALANCE_INSUFFICIENT"
    owned_account.refresh_from_db()
    position.refresh_from_db()
    assert (
        owned_account.current_cash,
        owned_account.current_market_value,
        owned_account.total_value,
        owned_account.total_trades,
        position.quantity,
        position.available_quantity,
        position.total_cost,
    ) == snapshot_before
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 0
    assert state.execution.intents
    assert _close_financial_snapshot(owned_account.pk) == financial_before


@pytest.mark.parametrize(
    ("body", "idempotency_key"),
    [
        (
            {"asset_code": "600000.SH", "close_shares": 10},
            "close-input-missing-price",
        ),
        (
            {"asset_code": "600000.SH", "close_price": "12.00"},
            "close-input-missing-shares",
        ),
        (
            {
                "asset_code": "600000.SH",
                "quantity": 10,
                "price": "12.00",
            },
            "close-input-legacy-alias",
        ),
        (
            {
                "asset_code": "600000.SH",
                "close_shares": 10.5,
                "close_price": "12.00",
            },
            "close-input-fractional-shares",
        ),
        (
            {
                "asset_code": "600000.SH",
                "close_shares": 10.0,
                "close_price": "12.00",
            },
            "close-input-float-shares",
        ),
        (
            {
                "asset_code": "600000.SH",
                "close_shares": "10",
                "close_price": "12.00",
            },
            "close-input-string-shares",
        ),
        (
            {
                "asset_code": "600000.SH",
                "close_shares": True,
                "close_price": "12.00",
            },
            "close-input-boolean-shares",
        ),
        (
            {
                "asset_code": "600000.SH",
                "close_shares": 10,
                "close_price": 12.00,
            },
            "close-input-numeric-price",
        ),
        (
            {
                "asset_code": "600000.SH",
                "close_shares": 10,
                "close_price": "1.2e1",
            },
            "close-input-exponent-price",
        ),
        (
            {
                "asset_code": "600000.SH",
                "close_shares": 10,
                "close_price": " 12.00 ",
            },
            "close-input-whitespace-price",
        ),
        (
            {
                "asset_code": "600000.SH",
                "close_shares": 10,
                "close_price": "0.001",
            },
            "close-input-price-too-small",
        ),
        (
            {
                "asset_code": "600000.SH",
                "close_shares": 10,
                "close_price": "12.00",
                "signal_id": 7,
            },
            "close-input-unsupported-field",
        ),
        (
            {
                "asset_code": "600000.SH",
                "close_shares": 10,
                "close_price": "12.00",
            },
            "close input bad key",
        ),
    ],
)
def test_close_requires_explicit_exact_body_and_idempotency_key(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any],
    idempotency_key: str,
) -> None:
    """Reject incomplete or ambiguous close requests before composition or ledger reads."""

    factory_calls: list[str] = []
    monkeypatch.setattr(
        sdk_contract_view_module,
        "build_current_reference_manual_trade_use_case",
        lambda: factory_calls.append("called"),
        raising=False,
    )
    legacy_calls: list[str] = []
    monkeypatch.setattr(
        sdk_contract_view_module.interface_services,
        "close_account_position",
        lambda **_kwargs: legacy_calls.append("called"),
    )
    headers = {"HTTP_IDEMPOTENCY_KEY": idempotency_key}
    response = authenticated_client.post(
        f"/api/simulated-trading/accounts/{owned_account.pk}/positions/close/",
        body,
        format="json",
        **headers,
    )

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": False,
        "error": "平仓请求无效。",
        "code": "SIMULATED_TRADE_INPUT_INVALID",
    }
    assert factory_calls == legacy_calls == []
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 0


@pytest.mark.django_db
def test_close_missing_idempotency_key_is_rejected_before_any_factory(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require the caller-owned idempotency key independently from a valid body."""

    factory_calls: list[str] = []
    monkeypatch.setattr(
        sdk_contract_view_module,
        "build_current_reference_manual_trade_use_case",
        lambda: factory_calls.append("called"),
        raising=False,
    )
    response = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_close_body(shares=10, price="12.00"),
        idempotency_key=None,
    )

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["code"] == "SIMULATED_TRADE_INPUT_INVALID"
    assert factory_calls == []
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 0


@pytest.mark.django_db
def test_close_missing_current_identity_does_not_fall_back_to_legacy_service(
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable current mapping blocks without consulting the legacy close service."""

    _seed_fee(owned_account)
    position = _position(owned_account)
    state = _install_close_manual_service(
        monkeypatch,
        account=owned_account,
        source_available=False,
    )
    legacy_calls: list[str] = []

    def legacy_close(**_kwargs: object) -> dict[str, object]:
        legacy_calls.append("called")
        return {"closed": True, "remaining_quantity": "0"}

    monkeypatch.setattr(
        sdk_contract_view_module.interface_services,
        "close_account_position",
        legacy_close,
    )
    owned_account.refresh_from_db()
    account_before = (
        owned_account.current_cash,
        owned_account.current_market_value,
        owned_account.total_value,
    )

    financial_before = _close_financial_snapshot(owned_account.pk)
    response = _close_post(
        authenticated_client,
        account_id=owned_account.pk,
        body=_close_body(shares=100, price="12.00"),
        idempotency_key="close-current-identity-missing-001",
    )

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["code"] == "EXECUTION_INSTRUMENT_IDENTITY_UNAVAILABLE"
    assert SimulatedTradeModel.objects.filter(account=owned_account).count() == 0
    position.refresh_from_db()
    assert position.quantity == Decimal("1000.000000")
    owned_account.refresh_from_db()
    assert (
        owned_account.current_cash,
        owned_account.current_market_value,
        owned_account.total_value,
    ) == account_before
    assert state.identity_reader.resolve_calls == 1
    assert state.execution.intents == []
    assert legacy_calls == []
    assert _close_financial_snapshot(owned_account.pk) == financial_before
