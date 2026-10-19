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
from rest_framework.response import Response
from rest_framework.test import APIClient

from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
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
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.trade_mapper import SimulatedTradeMapper
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

    rows = SimulatedTradeModel.objects.filter(account=owned_account)
    assert rows.count() == 1
    row = rows.get()
    assert row.action == action
    assert row.asset_type == "equity"
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
