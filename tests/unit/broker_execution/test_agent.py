"""Standalone Agent local idempotency and uncertainty behavior."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from apps.risk_center.application.execution_submission_v2 import (
    EvaluateExecutionSubmissionV2UseCase,
)
from apps.risk_center.application.execution_trading_constraints import (
    EvaluateExecutionTradingConstraintsUseCase,
)
from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionMarketV2,
    ExecutionSubmissionRuleV2,
)
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionMarketEvidence,
    ExecutionOrder,
    ExecutionQuantityConstraint,
    ExecutionSide,
    PriceBoundaryMode,
    SecurityTradingState,
    SellOddLotMode,
    SessionState,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
    QuoteValue,
    QuoteValueState,
)
from qmt_agent.config import AgentConfig
from qmt_agent.execution_constraints import ExecutionConstraintViolation
from qmt_agent.executor import QmtAgentExecutor
from qmt_agent.fake_adapter import FakeQmtAdapter
from qmt_agent.health import run_preflight, run_qmt_read_probe
from qmt_agent.qmt_adapter import (
    _qmt_event_time,
    _qmt_order_status_map,
    decode_order_remark,
    encode_order_remark,
)
from qmt_agent.state_store import AgentStateStore


class _Api:
    def __init__(
        self,
        *,
        ack_response: dict[str, Any] | None = None,
        ack_error: Exception | None = None,
        ack_hook: Any | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.ack_response = ack_response
        self.ack_error = ack_error
        self.ack_hook = ack_hook

    def post(self, endpoint: str, payload: dict):
        self.calls.append((endpoint, payload))
        if endpoint == "orders/submitting/":
            if self.ack_hook is not None:
                self.ack_hook()
            if self.ack_error is not None:
                raise self.ack_error
            if self.ack_response is not None:
                return self.ack_response
            return {"accepted": True, "order": _default_ack_order()}
        return {}


FIXED_NOW = datetime(2026, 10, 16, 1, 45, tzinfo=UTC)


class _FrozenDateTime(datetime):
    values: list[datetime] = [FIXED_NOW]
    index: int = 0

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        value = cls.values[min(cls.index, len(cls.values) - 1)]
        cls.index += 1
        if tz is None:
            return value.replace(tzinfo=None)
        return value.astimezone(tz)


@pytest.fixture(autouse=True)
def _fixed_executor_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    _FrozenDateTime.values = [FIXED_NOW]
    _FrozenDateTime.index = 0
    monkeypatch.setattr("qmt_agent.executor.datetime", _FrozenDateTime)


class _StaticRuleProvider:
    def __init__(self, rule: AShareExecutionRule) -> None:
        self.rule = rule

    def get_rule(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> AShareExecutionRule:
        return self.rule


class _StaticMarketProvider:
    def __init__(self, market: ExecutionMarketEvidence) -> None:
        self.market = market

    def get_market_evidence(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionMarketEvidence:
        return self.market


class _StaticSubmissionRuleProvider:
    def __init__(self, rule: ExecutionSubmissionRuleV2) -> None:
        self.rule = rule

    def get_submission_rule(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionRuleV2:
        return self.rule


class _StaticSubmissionMarketProvider:
    def __init__(self, market: ExecutionSubmissionMarketV2) -> None:
        self.market = market

    def get_submission_market(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionMarketV2:
        return self.market


def _execution_constraints_v1(
    order: dict[str, Any], *, market_valid_until: datetime | None = None
) -> dict[str, object]:
    """Create a test-only envelope through the real Domain and Application."""

    as_of = FIXED_NOW
    security_id = str(order["asset_code"])
    rule = AShareExecutionRule(
        rule_id="fixture-agent-rule",
        rule_version="TEST_FIXTURE_ONLY",
        security_id=security_id,
        market="SH",
        board="TEST_FIXTURE_ONLY_MAIN",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("10"), step=Decimal("10"), maximum=Decimal("1000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("10"), step=Decimal("10"), maximum=Decimal("1000")
        ),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.01"),
        rule_source_id="fixture-agent-rule-source",
        rule_source_version="TEST_FIXTURE_ONLY",
        rule_source_hash="a" * 64,
        source_observed_at=as_of - timedelta(hours=1),
        source_available_at=as_of - timedelta(minutes=1),
        effective_from=as_of - timedelta(days=1),
        valid_until=as_of + timedelta(hours=1),
    )
    market = ExecutionMarketEvidence(
        security_id=security_id,
        market="SH",
        board="TEST_FIXTURE_ONLY_MAIN",
        trading_date=as_of.date(),
        calendar_id="fixture-agent-calendar",
        calendar_version="TEST_FIXTURE_ONLY",
        calendar_source_hash="b" * 64,
        calendar_observed_at=as_of - timedelta(days=1),
        calendar_available_at=as_of - timedelta(minutes=1),
        calendar_valid_until=as_of + timedelta(days=1),
        session_id="fixture-agent-session",
        session_timezone="Asia/Shanghai",
        session_open_at=as_of - timedelta(minutes=15),
        session_close_at=as_of + timedelta(hours=4),
        session_state=SessionState.OPEN,
        security_state=SecurityTradingState.TRADING,
        market_source_id="fixture-agent-market-source",
        market_source_version="TEST_FIXTURE_ONLY",
        market_source_hash="c" * 64,
        price_boundary_mode=PriceBoundaryMode.LIMITED,
        lower_limit_price=Decimal("3"),
        upper_limit_price=Decimal("5"),
        reference_price=Decimal("3.90"),
        market_observed_at=as_of - timedelta(seconds=2),
        market_available_at=as_of - timedelta(seconds=1),
        market_valid_until=market_valid_until or as_of + timedelta(hours=1),
    )
    domain_order = ExecutionOrder(
        order_id=str(order["client_order_id"]),
        account_id=order["account_id"],
        security_id=security_id,
        side=ExecutionSide(str(order["side"])),
        quantity=Decimal(str(order["quantity"])),
        limit_price=Decimal(str(order["limit_price"])),
        sell_position_evidence=None,
    )
    use_case = EvaluateExecutionTradingConstraintsUseCase(
        rule_provider=_StaticRuleProvider(rule),
        market_evidence_provider=_StaticMarketProvider(market),
    )
    return use_case.execute(order=domain_order, as_of=as_of).to_payload()


def _execution_constraints(
    order: dict[str, Any],
    *,
    market_valid_until: datetime | None = None,
    price_boundary_mode: PriceBoundaryMode = PriceBoundaryMode.LIMITED,
    session_state: SessionState = SessionState.OPEN,
    security_state: SecurityTradingState = SecurityTradingState.TRADING,
) -> dict[str, object]:
    """Create a v2 test envelope through the real Domain and Application."""

    as_of = FIXED_NOW
    security_id = str(order["asset_code"])
    rule_v1 = AShareExecutionRule(
        rule_id="fixture-agent-rule-v2",
        rule_version="TEST_FIXTURE_ONLY",
        security_id=security_id,
        market="SH",
        board="TEST_FIXTURE_ONLY_MAIN",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("10"), step=Decimal("10"), maximum=Decimal("1000")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("10"), step=Decimal("10"), maximum=Decimal("1000")
        ),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=Decimal("0.01"),
        rule_source_id="fixture-agent-rule-source",
        rule_source_version="TEST_FIXTURE_ONLY",
        rule_source_hash="a" * 64,
        source_observed_at=as_of - timedelta(hours=1),
        source_available_at=as_of - timedelta(minutes=1),
        effective_from=as_of - timedelta(days=1),
        valid_until=as_of + timedelta(hours=1),
    )
    rule = ExecutionSubmissionRuleV2(
        execution_rule_v1=rule_v1,
        price_submission_range=PriceSubmissionRangeRule(
            market="SH",
            board="TEST_FIXTURE_ONLY_MAIN",
            price_tick=Decimal("0.01"),
            buy_deviation_ratio=Decimal("0.02"),
            sell_deviation_ratio=Decimal("0.02"),
            buy_widening_ticks=10,
            sell_widening_ticks=10,
            minimum_distance_ticks=1,
            lower_floor_ticks=1,
            rounding_mode=PriceRoundingMode.HALF_UP,
        ),
        allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
    )
    market_v1 = ExecutionMarketEvidence(
        security_id=security_id,
        market="SH",
        board="TEST_FIXTURE_ONLY_MAIN",
        trading_date=as_of.date(),
        calendar_id="fixture-agent-calendar",
        calendar_version="TEST_FIXTURE_ONLY",
        calendar_source_hash="b" * 64,
        calendar_observed_at=as_of - timedelta(days=1),
        calendar_available_at=as_of - timedelta(minutes=1),
        calendar_valid_until=as_of + timedelta(days=1),
        session_id="fixture-agent-session",
        session_timezone="Asia/Shanghai",
        session_open_at=as_of - timedelta(minutes=15),
        session_close_at=as_of + timedelta(hours=4),
        session_state=session_state,
        security_state=security_state,
        market_source_id="fixture-agent-market-source",
        market_source_version="TEST_FIXTURE_ONLY",
        market_source_hash="c" * 64,
        price_boundary_mode=price_boundary_mode,
        lower_limit_price=(
            Decimal("3") if price_boundary_mode is PriceBoundaryMode.LIMITED else None
        ),
        upper_limit_price=(
            Decimal("5") if price_boundary_mode is PriceBoundaryMode.LIMITED else None
        ),
        reference_price=Decimal("3.90"),
        market_observed_at=as_of - timedelta(seconds=2),
        market_available_at=as_of - timedelta(seconds=1),
        market_valid_until=market_valid_until or as_of + timedelta(hours=1),
    )
    market = ExecutionSubmissionMarketV2(
        market_evidence_v1=market_v1,
        stage=PriceSubmissionStage.CONTINUOUS,
        ask=QuoteValue(QuoteValueState.PRESENT, Decimal("3.90")),
        bid=QuoteValue(QuoteValueState.PRESENT, Decimal("3.90")),
        latest=QuoteValue(QuoteValueState.CONFIRMED_ABSENT, None),
        previous_close=QuoteValue(QuoteValueState.CONFIRMED_ABSENT, None),
    )
    domain_order = ExecutionOrder(
        order_id=str(order["client_order_id"]),
        account_id=order["account_id"],
        security_id=security_id,
        side=ExecutionSide(str(order["side"])),
        quantity=Decimal(str(order["quantity"])),
        limit_price=Decimal(str(order["limit_price"])),
        sell_position_evidence=None,
    )
    use_case = EvaluateExecutionSubmissionV2UseCase(
        rule_provider=_StaticSubmissionRuleProvider(rule),
        market_provider=_StaticSubmissionMarketProvider(market),
    )
    return use_case.execute(order=domain_order, as_of=as_of).to_payload()


def _mutable_object(parent: dict[str, object], key: str) -> dict[str, object]:
    """Return a nested JSON object from a test envelope."""

    value = parent.get(key)
    assert type(value) is dict
    return cast(dict[str, object], value)


def _seal_envelope_object(value: dict[str, object]) -> None:
    """Recompute one canonical SHA-256 after a test-only envelope mutation."""

    content = {key: item for key, item in value.items() if key != "content_hash"}
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    value["content_hash"] = hashlib.sha256(encoded).hexdigest()


def _remove_market_observation(envelope: dict[str, object]) -> None:
    """Remove market observation time while preserving valid v2 hash bindings."""

    market = _mutable_object(envelope, "market_evidence")
    base_market = _mutable_object(market, "market_evidence_v1")
    base_market["market_observed_at"] = None
    _seal_envelope_object(base_market)
    _seal_envelope_object(market)
    decision = _mutable_object(envelope, "decision")
    decision["market_evidence_content_hash"] = market["content_hash"]


def _default_ack_order() -> dict[str, Any]:
    return {
        "client_order_id": "00000000-0000-0000-0000-000000000001",
        "account_id": 7,
        "asset_code": "510300.SH",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "100",
        "limit_price": "3.9",
    }


def _epoch_milliseconds(value: datetime) -> int:
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def _local_market_snapshot(
    *,
    asset_code: str = "510300.SH",
    tick_time: datetime = FIXED_NOW - timedelta(seconds=1),
    last_price: str = "3.90",
) -> dict[str, Any]:
    tick_time_ms = _epoch_milliseconds(tick_time)
    return {
        "asset_code": asset_code,
        "captured_at_utc": FIXED_NOW.isoformat(),
        "metadata_observed_at": None,
        "metadata_freshness": "UNKNOWN",
        "last_price": last_price,
        "upper_limit": None,
        "lower_limit": None,
        "tick_time_ms": tick_time_ms,
        "boundary_mode": "UNKNOWN",
        "boundary_usable_for_submission": False,
        "field_evidence": {
            "last_price": {
                "state": "PRESENT",
                "value": last_price,
                "source_api": "xtdata.get_full_tick",
                "source_field": "lastPrice",
                "reason_code": None,
            },
            "tick_time_ms": {
                "state": "PRESENT",
                "value": tick_time_ms,
                "source_api": "xtdata.get_full_tick",
                "source_field": "time",
                "reason_code": None,
            },
        },
    }


class _FixtureQmtAdapter(FakeQmtAdapter):
    def __init__(
        self,
        scenario: str,
        *,
        local_snapshot: dict[str, Any] | None = None,
        market_snapshot_hook: Any | None = None,
        account_snapshot_hook: Any | None = None,
    ) -> None:
        super().__init__(scenario)
        self.local_snapshot = local_snapshot
        self.market_snapshot_hook = market_snapshot_hook
        self.account_snapshot_hook = account_snapshot_hook
        self.market_snapshot_calls = 0
        self.account_snapshot_calls = 0
        self.submit_calls = 0

    def market_snapshot(self, asset_code: str) -> dict[str, Any]:
        self.market_snapshot_calls += 1
        if self.local_snapshot is None:
            snapshot = _local_market_snapshot(asset_code=asset_code)
        else:
            snapshot = dict(self.local_snapshot)
        if self.market_snapshot_hook is not None:
            self.market_snapshot_hook(self.market_snapshot_calls)
        return snapshot

    def account_snapshot(self) -> dict[str, Any]:
        self.account_snapshot_calls += 1
        snapshot = super().account_snapshot()
        if self.account_snapshot_hook is not None:
            self.account_snapshot_hook(self.account_snapshot_calls)
        return snapshot

    def submit_order(self, order: dict[str, Any]) -> Any:
        self.submit_calls += 1
        return super().submit_order(order)


def _ack_response(order: dict[str, Any], **changes: object) -> dict[str, Any]:
    acknowledged = {
        field_name: order[field_name]
        for field_name in (
            "client_order_id",
            "account_id",
            "asset_code",
            "side",
            "order_type",
            "quantity",
            "limit_price",
        )
    }
    acknowledged.update(changes)
    return {"accepted": True, "order": acknowledged}


def _order() -> dict:
    order = {
        "client_order_id": "00000000-0000-0000-0000-000000000001",
        "account_id": 7,
        "asset_code": "510300.SH",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "100",
        "limit_price": "3.9",
        "lease_token": "lease-token",
        "expires_at": "2026-10-16T03:00:00+00:00",
        "lease_expires_at": "2026-10-16T02:30:00Z",
    }
    order["execution_constraints"] = _execution_constraints(order)
    return order


def _live_executor(
    tmp_path: Path,
    api: _Api,
    *,
    order: dict | None = None,
    local_snapshot: dict[str, Any] | None = None,
    market_snapshot_hook: Any | None = None,
    account_snapshot_hook: Any | None = None,
) -> tuple[QmtAgentExecutor, AgentStateStore, _FixtureQmtAdapter, dict]:
    leased_order = order or _order()
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=False,
        enforce_trading_session=False,
    )
    broker = _FixtureQmtAdapter(
        "success",
        local_snapshot=local_snapshot,
        market_snapshot_hook=market_snapshot_hook,
        account_snapshot_hook=account_snapshot_hook,
    )
    broker.connect()
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)
    return executor, state, broker, leased_order


def test_heartbeat_publishes_agent_source_observation_time(tmp_path: Path) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=True,
    )
    api = _Api()
    broker = FakeQmtAdapter("success")
    broker.connect()
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)

    executor.heartbeat()

    endpoint, payload = api.calls[0]
    assert endpoint == "heartbeat/"
    assert payload["contract_version"] == "1.0"
    assert payload["observed_at"].endswith("+00:00")
    assert payload["execution_constraint_schemas"] == ["a-share-execution-constraints.v2"]
    state.close()


def test_agent_records_submitting_before_broker_and_does_not_duplicate(tmp_path: Path) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=False,
        enforce_trading_session=False,
    )
    api = _Api()
    broker = _FixtureQmtAdapter("success")
    broker.connect()
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)
    executor.execute_order(_order())
    assert state.get(_order()["client_order_id"])["status"] == "SUBMITTED"
    assert [endpoint for endpoint, _payload in api.calls] == [
        "orders/submitting/",
        "events/",
    ]
    try:
        executor.execute_order(_order())
    except RuntimeError as exc:
        assert "idempotency" in str(exc)
    else:
        raise AssertionError("duplicate local submission should fail")
    state.close()


def test_v1_only_constraints_are_rejected_before_state_ack_or_vendor(
    tmp_path: Path,
) -> None:
    api = _Api()
    order = _order()
    order["execution_constraints"] = _execution_constraints_v1(order)
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    with pytest.raises(ExecutionConstraintViolation) as captured:
        executor.execute_order(order)

    assert captured.value.code == "SCHEMA_UNSUPPORTED"
    assert api.calls == []
    assert state.get(order["client_order_id"]) is None
    assert broker.orders == {}
    state.close()


def test_v2_session_evidence_cannot_be_disabled_by_local_window_setting(
    tmp_path: Path,
) -> None:
    api = _Api()
    order = _order()
    order["execution_constraints"] = _execution_constraints(
        order, session_state=SessionState.CLOSED
    )
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    with pytest.raises(ExecutionConstraintViolation) as captured:
        executor.execute_order(order)

    assert captured.value.code == "SERVER_DECISION_DENIED"
    assert api.calls == []
    assert state.get(order["client_order_id"]) is None
    assert broker.orders == {}
    state.close()


def test_v2_server_allowed_claim_cannot_override_local_cage_rejection(
    tmp_path: Path,
) -> None:
    api = _Api()
    order = _order()
    order["limit_price"] = "4.20"
    envelope = _execution_constraints(order)
    decision_value = envelope["decision"]
    assert isinstance(decision_value, dict)
    assert decision_value["status"] == "DENIED"
    decision_value["status"] = "ALLOWED"
    decision_value["reason_codes"] = []
    order["execution_constraints"] = envelope
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    with pytest.raises(ExecutionConstraintViolation) as captured:
        executor.execute_order(order)

    assert captured.value.code == "LIMIT_PRICE_OUTSIDE_SUBMISSION_RANGE"
    assert api.calls == []
    assert state.get(order["client_order_id"]) is None
    assert broker.orders == {}
    state.close()


@pytest.mark.parametrize("tick_offset_seconds", (1, -3))
def test_local_tick_cannot_be_future_or_older_than_approved_evidence(
    tmp_path: Path, tick_offset_seconds: int
) -> None:
    api = _Api()
    snapshot = _local_market_snapshot(tick_time=FIXED_NOW + timedelta(seconds=tick_offset_seconds))
    executor, state, broker, order = _live_executor(tmp_path, api, local_snapshot=snapshot)

    with pytest.raises(RuntimeError, match="no older than approved market evidence"):
        executor.execute_order(order)

    assert api.calls == []
    assert state.get(order["client_order_id"]) is None
    assert broker.orders == {}
    state.close()


@pytest.mark.parametrize(
    "mutation", ("unknown_price", "invalid_price", "missing_tick", "wrong_source")
)
def test_local_market_requires_present_exact_source_and_tick_evidence(
    tmp_path: Path, mutation: str
) -> None:
    api = _Api()
    snapshot = _local_market_snapshot()
    fields = snapshot["field_evidence"]
    assert isinstance(fields, dict)
    if mutation in {"unknown_price", "invalid_price"}:
        last_price = fields["last_price"]
        assert isinstance(last_price, dict)
        last_price["state"] = "UNKNOWN" if mutation == "unknown_price" else "INVALID"
    elif mutation == "missing_tick":
        snapshot.pop("tick_time_ms")
    else:
        tick_time = fields["tick_time_ms"]
        assert isinstance(tick_time, dict)
        tick_time["source_field"] = "captured_at_utc"
    executor, state, broker, order = _live_executor(tmp_path, api, local_snapshot=snapshot)

    with pytest.raises(RuntimeError, match="Local"):
        executor.execute_order(order)

    assert api.calls == []
    assert state.get(order["client_order_id"]) is None
    assert broker.orders == {}
    state.close()


def test_v2_unrestricted_boundary_does_not_require_local_limit_metadata(
    tmp_path: Path,
) -> None:
    api = _Api()
    order = _order()
    order["execution_constraints"] = _execution_constraints(
        order, price_boundary_mode=PriceBoundaryMode.UNRESTRICTED
    )
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    executor.execute_order(order)

    assert state.get(order["client_order_id"])["status"] == "SUBMITTED"
    assert broker.orders[order["client_order_id"]]["status"] == "SUBMITTED"
    state.close()


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("missing", "ENVELOPE_INVALID"),
        ("unknown_schema", "SCHEMA_UNSUPPORTED"),
        ("missing_market_observation", "TIMESTAMP_INVALID"),
        ("expired", "SERVER_DECISION_DENIED"),
    ),
)
def test_constraints_are_required_and_current_before_ack_or_state_write(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    api = _Api()
    order = _order()
    if mutation == "missing":
        del order["execution_constraints"]
    elif mutation == "unknown_schema":
        constraints = order["execution_constraints"]
        assert isinstance(constraints, dict)
        constraints["schema"] = "a-share-execution-constraints.v99"
    elif mutation == "missing_market_observation":
        constraints = _execution_constraints(order)
        _remove_market_observation(constraints)
        order["execution_constraints"] = constraints
    else:
        order["execution_constraints"] = _execution_constraints(order, market_valid_until=FIXED_NOW)

    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    with pytest.raises(ExecutionConstraintViolation) as captured:
        executor.execute_order(order)

    assert captured.value.code == expected_code
    assert api.calls == []
    assert state.get(order["client_order_id"]) is None
    assert broker.orders == {}
    state.close()


@pytest.mark.parametrize(
    ("field_name", "mutation", "value"),
    (
        ("expires_at", "missing", None),
        ("expires_at", "none", None),
        ("expires_at", "value", "2026-10-16T02:00:00"),
        ("expires_at", "value", "2026-10-16T01:45:00+00:00"),
        ("lease_expires_at", "missing", None),
        ("lease_expires_at", "none", None),
        ("lease_expires_at", "value", "2026-10-16T02:00:00"),
        ("lease_expires_at", "value", "2026-10-16T01:45:00+00:00"),
    ),
)
def test_lease_deadlines_must_be_present_aware_and_future_before_ack(
    tmp_path: Path, field_name: str, mutation: str, value: object
) -> None:
    api = _Api()
    order = _order()
    if mutation == "missing":
        order.pop(field_name)
    else:
        order[field_name] = value
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    with pytest.raises(RuntimeError, match=field_name):
        executor.execute_order(order)

    assert api.calls == []
    assert state.get(order["client_order_id"]) is None
    assert broker.orders == {}
    state.close()


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("client_order_id", "00000000-0000-0000-0000-000000000099"),
        ("account_id", 8),
        ("asset_code", "000001.SZ"),
        ("side", "SELL"),
        ("quantity", "40"),
        ("limit_price", "3.91"),
        ("order_type", "MARKET"),
    ),
)
def test_order_outer_fields_must_bind_to_constraint_envelope_before_ack(
    tmp_path: Path, field_name: str, value: object
) -> None:
    api = _Api()
    order = _order()
    order[field_name] = value
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    with pytest.raises(RuntimeError, match="binding|limit orders"):
        executor.execute_order(order)

    assert api.calls == []
    assert state.get(order["client_order_id"]) is None
    assert broker.orders == {}
    state.close()


@pytest.mark.parametrize(
    ("field_name", "value"),
    (("account_id", True), ("quantity", 30.0), ("limit_price", Decimal("NaN"))),
)
def test_order_numeric_bindings_reject_coercion_and_nonfinite_values(
    tmp_path: Path, field_name: str, value: object
) -> None:
    api = _Api()
    order = _order()
    order[field_name] = value
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    with pytest.raises(RuntimeError, match="positive integer|binding|must be|finite"):
        executor.execute_order(order)

    assert api.calls == []
    assert state.get(str(order["client_order_id"])) is None
    assert broker.orders == {}
    state.close()


@pytest.mark.parametrize(
    "ack_response",
    (
        {"accepted": 1, "order": _default_ack_order()},
        {"accepted": False, "order": _default_ack_order()},
        {"accepted": True},
        {
            "accepted": True,
            "order": {
                **_default_ack_order(),
                "client_order_id": "00000000-0000-0000-0000-000000000099",
            },
        },
        {"accepted": True, "order": {**_default_ack_order(), "account_id": 8}},
        {"accepted": True, "order": {**_default_ack_order(), "asset_code": "000001.SZ"}},
        {"accepted": True, "order": {**_default_ack_order(), "side": "SELL"}},
        {"accepted": True, "order": {**_default_ack_order(), "quantity": 30.0}},
        {"accepted": True, "order": {**_default_ack_order(), "limit_price": "3.91"}},
        {"accepted": True, "order": {**_default_ack_order(), "order_type": "MARKET"}},
    ),
)
def test_invalid_server_ack_never_reaches_vendor(
    tmp_path: Path, ack_response: dict[str, Any]
) -> None:
    api = _Api(ack_response=ack_response)
    executor, state, broker, order = _live_executor(tmp_path, api)

    executor.execute_order(order)

    record = state.get(order["client_order_id"])
    assert record is not None
    assert record["status"] == "FAILED"
    assert broker.orders == {}
    event = api.calls[-1][1]["events"][0]
    assert event["event_type"] == "LOCAL_SUBMIT_VALIDATION_FAILED"
    assert event["status"] == "FAILED"
    assert event["payload"]["broker_submit_attempted"] is False
    state.close()


def test_ack_transport_uncertainty_is_reconciled_without_vendor_call(tmp_path: Path) -> None:
    api = _Api(ack_error=TimeoutError("ack transport timed out"))
    executor, state, broker, order = _live_executor(tmp_path, api)

    executor.execute_order(order)

    record = state.get(order["client_order_id"])
    assert record is not None
    assert record["status"] == "RECONCILIATION_REQUIRED"
    assert broker.orders == {}
    event = api.calls[-1][1]["events"][0]
    assert event["event_type"] == "SERVER_ACK_OUTCOME_UNKNOWN"
    assert event["payload"]["broker_submit_attempted"] is False
    state.close()


def test_local_stop_rechecked_after_ack_blocks_vendor_call(tmp_path: Path) -> None:
    stop_file = tmp_path / "STOP"
    api = _Api(ack_hook=lambda: stop_file.write_text("STOP", encoding="utf-8"))
    executor, state, broker, order = _live_executor(tmp_path, api)

    executor.execute_order(order)

    record = state.get(order["client_order_id"])
    assert record is not None
    assert record["status"] == "FAILED"
    assert broker.orders == {}
    event = api.calls[-1][1]["events"][0]
    assert event["event_type"] == "LOCAL_SUBMIT_VALIDATION_FAILED"
    assert event["payload"]["broker_submit_attempted"] is False
    state.close()


def test_execution_evidence_is_revalidated_at_the_actual_vendor_boundary(
    tmp_path: Path,
) -> None:
    order = _order()
    order["execution_constraints"] = _execution_constraints(
        order, market_valid_until=FIXED_NOW + timedelta(minutes=5)
    )
    api = _Api()
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)
    expiry = FIXED_NOW + timedelta(minutes=5)
    _FrozenDateTime.values = [FIXED_NOW, FIXED_NOW, FIXED_NOW, FIXED_NOW, FIXED_NOW, expiry]

    executor.execute_order(order)

    record = state.get(order["client_order_id"])
    assert record is not None
    assert record["status"] == "FAILED"
    assert broker.orders == {}
    event = api.calls[-1][1]["events"][0]
    assert event["event_type"] == "LOCAL_SUBMIT_VALIDATION_FAILED"
    assert "expired" in event["payload"]["message"]
    assert event["payload"]["broker_submit_attempted"] is False
    state.close()


def test_qmt_tick_created_during_market_read_uses_post_read_clock(
    tmp_path: Path,
) -> None:
    order = _order()
    api = _Api()
    tick_time = FIXED_NOW + timedelta(seconds=1)
    executor, state, broker, order = _live_executor(
        tmp_path,
        api,
        order=order,
        local_snapshot=_local_market_snapshot(tick_time=tick_time),
    )
    _FrozenDateTime.values = [
        FIXED_NOW,
        tick_time + timedelta(seconds=1),
        tick_time + timedelta(seconds=1),
        tick_time + timedelta(seconds=1),
        tick_time + timedelta(seconds=1),
        tick_time + timedelta(seconds=1),
    ]

    executor.execute_order(order)

    record = state.get(order["client_order_id"])
    assert record is not None
    assert record["status"] == "SUBMITTED"
    assert broker.submit_calls == 1
    state.close()


@pytest.mark.parametrize("expiry_target", ("market", "expires_at", "lease_expires_at"))
def test_account_read_expiry_is_rechecked_before_vendor_call(
    tmp_path: Path,
    expiry_target: str,
) -> None:
    order = _order()
    expiry = FIXED_NOW + timedelta(minutes=5)
    if expiry_target == "market":
        order["execution_constraints"] = _execution_constraints(order, market_valid_until=expiry)
    else:
        order[expiry_target] = expiry.isoformat()
    account_reads = 0

    def advance_clock_after_post_ack_account_read(read_count: int) -> None:
        nonlocal account_reads
        account_reads += 1
        if read_count == 2:
            _FrozenDateTime.index = 5

    api = _Api()
    executor, state, broker, order = _live_executor(
        tmp_path,
        api,
        order=order,
        account_snapshot_hook=advance_clock_after_post_ack_account_read,
    )
    _FrozenDateTime.values = [FIXED_NOW, FIXED_NOW, FIXED_NOW, FIXED_NOW, FIXED_NOW, expiry]

    executor.execute_order(order)

    record = state.get(order["client_order_id"])
    assert record is not None
    assert record["status"] == "FAILED"
    assert broker.submit_calls == 0
    event = api.calls[-1][1]["events"][0]
    assert event["event_type"] == "LOCAL_SUBMIT_VALIDATION_FAILED"
    assert expiry_target in event["payload"]["message"] or expiry_target == "market"
    assert event["payload"]["broker_submit_attempted"] is False
    state.close()


def test_post_ack_market_read_expiry_is_rechecked_before_account_read(
    tmp_path: Path,
) -> None:
    order = _order()
    expiry = FIXED_NOW + timedelta(minutes=5)
    order["execution_constraints"] = _execution_constraints(order, market_valid_until=expiry)

    def advance_clock_after_post_ack_market_read(read_count: int) -> None:
        if read_count == 2:
            _FrozenDateTime.index = 5

    api = _Api()
    executor, state, broker, order = _live_executor(
        tmp_path,
        api,
        order=order,
        market_snapshot_hook=advance_clock_after_post_ack_market_read,
    )
    _FrozenDateTime.values = [FIXED_NOW, FIXED_NOW, FIXED_NOW, FIXED_NOW, FIXED_NOW, expiry]

    executor.execute_order(order)

    record = state.get(order["client_order_id"])
    assert record is not None
    assert record["status"] == "FAILED"
    assert broker.submit_calls == 0
    assert broker.account_snapshot_calls == 1
    event = api.calls[-1][1]["events"][0]
    assert event["event_type"] == "LOCAL_SUBMIT_VALIDATION_FAILED"
    assert "expired" in event["payload"]["message"]
    assert event["payload"]["broker_submit_attempted"] is False
    state.close()


def test_stop_created_during_post_ack_account_read_blocks_vendor_call(
    tmp_path: Path,
) -> None:
    stop_file = tmp_path / "STOP"

    def create_stop_after_post_ack_account_read(read_count: int) -> None:
        if read_count == 2:
            stop_file.write_text("STOP", encoding="utf-8")

    api = _Api()
    executor, state, broker, order = _live_executor(
        tmp_path,
        api,
        account_snapshot_hook=create_stop_after_post_ack_account_read,
    )

    executor.execute_order(order)

    record = state.get(order["client_order_id"])
    assert record is not None
    assert record["status"] == "FAILED"
    assert broker.submit_calls == 0
    event = api.calls[-1][1]["events"][0]
    assert event["event_type"] == "LOCAL_SUBMIT_VALIDATION_FAILED"
    assert "STOP" in event["payload"]["message"]
    assert event["payload"]["broker_submit_attempted"] is False
    state.close()


@pytest.mark.parametrize("deadline_field", ("expires_at", "lease_expires_at"))
def test_original_lease_deadlines_are_rechecked_after_ack(
    tmp_path: Path, deadline_field: str
) -> None:
    order = _order()
    expiry = FIXED_NOW + timedelta(minutes=5)
    order[deadline_field] = expiry.isoformat()
    api = _Api()
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)
    _FrozenDateTime.values = [FIXED_NOW, FIXED_NOW, FIXED_NOW, FIXED_NOW, FIXED_NOW, expiry]

    executor.execute_order(order)

    record = state.get(order["client_order_id"])
    assert record is not None
    assert record["status"] == "FAILED"
    assert broker.orders == {}
    event = api.calls[-1][1]["events"][0]
    assert event["event_type"] == "LOCAL_SUBMIT_VALIDATION_FAILED"
    assert deadline_field in event["payload"]["message"]
    assert event["payload"]["broker_submit_attempted"] is False
    state.close()


def test_order_binding_is_rechecked_after_server_ack(tmp_path: Path) -> None:
    order = _order()

    def change_quantity_after_ack() -> None:
        order["quantity"] = "200"

    api = _Api(ack_hook=change_quantity_after_ack)
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    executor.execute_order(order)

    record = state.get(order["client_order_id"])
    assert record is not None
    assert record["status"] == "FAILED"
    assert broker.orders == {}
    event = api.calls[-1][1]["events"][0]
    assert event["event_type"] == "LOCAL_SUBMIT_VALIDATION_FAILED"
    assert event["payload"]["broker_submit_attempted"] is False
    state.close()


def test_effective_constraints_replace_the_hard_coded_buy_lot_size(
    tmp_path: Path,
) -> None:
    order = _order()
    order["quantity"] = "30"
    order["execution_constraints"] = _execution_constraints(order)
    api = _Api(ack_response=_ack_response(order))
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    executor.execute_order(order)

    assert broker.orders[order["client_order_id"]]["quantity"] == "30"
    assert state.get(order["client_order_id"])["status"] == "SUBMITTED"
    assert [endpoint for endpoint, _payload in api.calls] == [
        "orders/submitting/",
        "events/",
    ]
    state.close()


def test_exact_integer_and_decimal_outer_values_are_supported(tmp_path: Path) -> None:
    order = _order()
    order["quantity"] = 100
    order["limit_price"] = Decimal("3.90")
    order["execution_constraints"] = _execution_constraints(order)
    api = _Api(ack_response=_ack_response(order))
    executor, state, broker, order = _live_executor(tmp_path, api, order=order)

    executor.execute_order(order)

    assert broker.orders[order["client_order_id"]]["quantity"] == "100"
    assert state.get(order["client_order_id"])["status"] == "SUBMITTED"
    state.close()


def test_dry_run_reports_idempotent_validation_without_qmt_submission(
    tmp_path: Path,
) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=True,
        enforce_trading_session=False,
    )
    api = _Api()
    broker = _FixtureQmtAdapter("success")
    broker.connect()
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    order = {**_order(), "approval_digest": "approval-v1"}
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)

    executor.execute_order(order)
    executor.execute_order(order)

    assert broker.orders == {}
    assert state.get(order["client_order_id"]) is None
    first_event = api.calls[0][1]["events"][0]
    second_event = api.calls[1][1]["events"][0]
    assert first_event["event_type"] == "DRY_RUN_VALIDATED"
    assert first_event["status"] == ""
    assert first_event["event_id"] == second_event["event_id"]
    state.close()


def test_unknown_broker_outcome_requires_reconciliation(tmp_path: Path) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=False,
        enforce_trading_session=False,
    )
    api = _Api()
    broker = _FixtureQmtAdapter("unknown")
    broker.connect()
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)
    executor.execute_order(_order())
    assert state.get(_order()["client_order_id"])["status"] == "RECONCILIATION_REQUIRED"
    assert api.calls[-1][1]["events"][0]["status"] == "RECONCILIATION_REQUIRED"
    with pytest.raises(RuntimeError, match="idempotency"):
        executor.execute_order(_order())
    assert broker.submit_calls == 1
    state.close()


def test_restart_recovery_preserves_authoritative_final_broker_status(
    tmp_path: Path,
) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=False,
    )
    api = _Api()
    broker = FakeQmtAdapter("success")
    broker.connect()
    broker.orders[_order()["client_order_id"]] = {
        "broker_order_id": "FAKE-RECOVERED-1",
        "status": "FILLED",
        "asset_code": _order()["asset_code"],
        "side": _order()["side"],
        "quantity": _order()["quantity"],
        "limit_price": _order()["limit_price"],
    }
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    state.mark_submitting(_order()["client_order_id"], _order())
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)

    executor.recover_uncertain_submissions()

    assert api.calls[-1][1]["events"][0]["status"] == "FILLED"
    assert state.get(_order()["client_order_id"])["status"] == "FILLED"
    state.close()


def test_agent_reports_polled_broker_events(tmp_path: Path) -> None:
    config = SimpleNamespace(
        kill_switch_file=tmp_path / "STOP",
        system_account_id=7,
        dry_run=False,
    )
    api = _Api()
    broker = FakeQmtAdapter("success")
    broker.poll_events = lambda: [
        {
            "event_id": "qmt-order-1",
            "client_order_id": _order()["client_order_id"],
            "event_type": "QMT_ORDER_STATUS",
            "status": "FILLED",
            "occurred_at": "2026-07-21T00:00:00+00:00",
        }
    ]
    state = AgentStateStore(tmp_path / "agent.sqlite3")
    executor = QmtAgentExecutor(config=config, api=api, broker=broker, state=state)

    executor.sync_broker_events()

    assert api.calls == [
        (
            "events/",
            {
                "contract_version": "1.0",
                "events": broker.poll_events(),
            },
        )
    ]
    state.close()


def test_fake_adapter_reports_fill_before_final_order_status() -> None:
    broker = FakeQmtAdapter("filled")
    broker.connect()
    result = broker.submit_order(_order())

    events = broker.poll_events()

    assert result.accepted is True
    assert [event["event_type"] for event in events] == [
        "FAKE_TRADE",
        "FAKE_ORDER_STATUS",
    ]
    assert events[0]["status"] == ""
    assert events[1]["status"] == "FILLED"


def test_agent_refuses_disabled_tls_verification_for_remote_vps(tmp_path: Path) -> None:
    config = AgentConfig(
        agent_id="agent-1",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path,
        broker_account_id="broker-1",
        broker_account_type="STOCK",
        system_account_id=7,
        verify_tls=False,
    )

    with pytest.raises(ValueError, match="loopback"):
        config.validate()


def test_qmt_order_remark_round_trips_uuid_within_vendor_limit() -> None:
    client_order_id = "00000000-0000-0000-0000-000000000001"

    remark = encode_order_remark(client_order_id)

    assert len(remark.encode("ascii")) <= 24
    assert decode_order_remark(remark) == client_order_id
    assert decode_order_remark(client_order_id) == client_order_id
    assert decode_order_remark("foreign-strategy-order") is None


def test_agent_rejects_unimplemented_credit_account_semantics(tmp_path: Path) -> None:
    config = AgentConfig(
        agent_id="agent-1",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path,
        broker_account_id="broker-1",
        broker_account_type="CREDIT",
        system_account_id=7,
    )

    with pytest.raises(ValueError, match="STOCK accounts only"):
        config.validate()


def test_qmt_documented_order_states_are_not_silently_dropped() -> None:
    constants = SimpleNamespace(
        ORDER_UNREPORTED=48,
        ORDER_WAIT_REPORTING=49,
        ORDER_REPORTED=50,
        ORDER_REPORTED_CANCEL=51,
        ORDER_PARTSUCC_CANCEL=52,
        ORDER_PART_CANCEL=53,
        ORDER_CANCELED=54,
        ORDER_PART_SUCC=55,
        ORDER_SUCCEEDED=56,
        ORDER_JUNK=57,
        ORDER_UNKNOWN=255,
    )

    mapping = _qmt_order_status_map(constants)

    assert mapping[51] == "CANCEL_PENDING"
    assert mapping[53] == "CANCELED"
    assert mapping[57] == "BROKER_REJECTED"
    assert mapping[255] == "RECONCILIATION_REQUIRED"


def test_qmt_event_time_preserves_broker_timestamp() -> None:
    assert _qmt_event_time(0, "fallback") == "fallback"
    assert _qmt_event_time(1_700_000_000, "fallback").startswith("2023-11-14T22:13:20")


def test_agent_preflight_reports_supported_local_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qmt_userdata = tmp_path / "userdata_mini"
    qmt_userdata.mkdir()
    config = AgentConfig(
        agent_id="agent-1",
        server_url="https://vps.example.com",
        qmt_userdata_path=qmt_userdata,
        broker_account_id="broker-1",
        broker_account_type="STOCK",
        system_account_id=7,
        qmt_client_version="QMT-2026.1",
        xtquant_version="xtquant-2026.1",
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )
    monkeypatch.setattr("qmt_agent.health.platform.system", lambda: "Windows")
    monkeypatch.setattr("qmt_agent.health.importlib.util.find_spec", lambda _name: object())

    report = run_preflight(config)

    assert report["python_supported"] is True
    assert report["xtquant_installed"] is True
    assert report["qmt_client_version_recorded"] is True
    assert report["xtquant_version_recorded"] is True
    assert report["ready"] is True


def test_qmt_read_probe_queries_all_facts_without_trading(tmp_path: Path) -> None:
    config = AgentConfig(
        agent_id="agent-read-probe",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path / "userdata_mini",
        broker_account_id="must-not-appear-in-report",
        broker_account_type="STOCK",
        system_account_id=7,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )
    broker = FakeQmtAdapter("success")

    report = run_qmt_read_probe(config, broker, adapter_name="fake")

    assert report["ready"] is True
    assert report["read_only"] is True
    assert report["submitted_order"] is False
    assert report["canceled_order"] is False
    assert report["checks"]["asset_query"] is True
    assert report["checks"]["positions_query"] is True
    assert report["checks"]["orders_query"] is True
    assert report["checks"]["trades_query"] is True
    assert "must-not-appear-in-report" not in str(report)


def test_qmt_read_probe_fails_closed_on_disconnect(tmp_path: Path) -> None:
    config = AgentConfig(
        agent_id="agent-read-probe-failure",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path / "userdata_mini",
        broker_account_id="broker-1",
        broker_account_type="STOCK",
        system_account_id=7,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )

    report = run_qmt_read_probe(
        config,
        FakeQmtAdapter("disconnect"),
        adapter_name="fake",
    )

    assert report["ready"] is False
    assert report["checks"] == {
        "qmt_connected": False,
        "failure_type": "RuntimeError",
        "failure_code": "BROKER_READ_FAILED",
    }


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        ("QMT trader connection failed", "QMT_CONNECTION_FAILED"),
        ("QMT account subscription failed", "QMT_ACCOUNT_SUBSCRIPTION_FAILED"),
    ],
)
def test_qmt_read_probe_reports_secret_free_failure_stage(
    tmp_path: Path,
    message: str,
    expected_code: str,
) -> None:
    class FailingBroker(FakeQmtAdapter):
        def connect(self) -> None:
            raise RuntimeError(message)

    config = AgentConfig(
        agent_id="agent-read-probe-stage",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path / "userdata_mini",
        broker_account_id="must-not-appear-in-report",
        broker_account_type="STOCK",
        system_account_id=7,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )

    report = run_qmt_read_probe(config, FailingBroker("success"))

    assert report["ready"] is False
    assert report["checks"]["failure_code"] == expected_code
    assert "must-not-appear-in-report" not in str(report)
    assert message not in str(report)


def test_qmt_read_probe_detects_vendor_server_authorization_denial(
    tmp_path: Path,
) -> None:
    class FailingBroker(FakeQmtAdapter):
        def connect(self) -> None:
            raise RuntimeError("QMT trader connection failed")

    userdata = tmp_path / "userdata"
    log_dir = userdata / "log"
    log_dir.mkdir(parents=True)
    (log_dir / "XtClient_20260722.log").write_text(
        "The XtQuantServer is not allowed to start.\n",
        encoding="utf-8",
    )
    config = AgentConfig(
        agent_id="agent-server-denial",
        server_url="https://vps.example.com",
        qmt_userdata_path=userdata,
        broker_account_id="must-not-appear-in-report",
        broker_account_type="STOCK",
        system_account_id=7,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )

    report = run_qmt_read_probe(config, FailingBroker("success"))

    assert report["ready"] is False
    assert report["checks"]["failure_code"] == "QMT_SERVER_NOT_ALLOWED"
    assert "must-not-appear-in-report" not in str(report)
    assert "XtQuantServer" not in str(report)


def test_real_qmt_read_probe_requires_recorded_version_matrix(tmp_path: Path) -> None:
    config = AgentConfig(
        agent_id="agent-version-probe",
        server_url="https://vps.example.com",
        qmt_userdata_path=tmp_path / "userdata_mini",
        broker_account_id="broker-1",
        broker_account_type="STOCK",
        system_account_id=7,
        log_dir=tmp_path / "logs",
        state_dir=tmp_path / "state",
    )

    report = run_qmt_read_probe(
        config,
        FakeQmtAdapter("success"),
        adapter_name="xtquant",
    )

    assert report["ready"] is False
    assert report["checks"]["qmt_client_version_recorded"] is False
    assert report["checks"]["xtquant_version_recorded"] is False
