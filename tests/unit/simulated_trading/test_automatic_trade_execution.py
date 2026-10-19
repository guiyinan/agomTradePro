"""Unit-port contracts for the automatic current-reference trade bridge.

These tests use typed source evidence and a stub manual executor. They verify
preflight and intent boundaries only; they do not prove database atomicity or
financial integration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from apps.data_center.application.price_service import PriceLookupResult
from apps.simulated_trading.application import (
    execution_settlement_uow as settlement_uow_application,
)
from apps.simulated_trading.application.automatic_trade_execution import (
    AutomaticTradeExecutionBridge,
    AutomaticTradeExecutionPreflightBlocked,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.manual_trade_execution import (
    ExecuteCurrentReferenceManualTradeUseCase,
    ManualSimulatedTradeRequest,
    ManualSimulatedTradeResult,
    SimulatedTradeExecutionReadbackUnknown,
)
from apps.simulated_trading.domain.entities import (
    OrderStatus,
    Position,
    SimulatedTrade,
    TradeAction,
)
from apps.simulated_trading.domain.execution_current_reference import (
    CurrentReferenceSelectionV1,
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeExecutionReceipt,
    SimulatedTradeSide,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
TRADE_DATE = date(2026, 10, 16)
ACCOUNT_ID = 7
USER_ID = 11
ASSET_CODE = "600000.SH"
RUN_ID = UUID("8a69505d-103f-4b43-a9c4-d244a0d61c72")


def _current_identity(as_of: datetime) -> ExecutionInstrumentIdentityEvidenceV2:
    """Build the exact V2 identity receipt while preserving unknown source clocks."""

    response_completed_at = as_of - timedelta(minutes=30)
    profile_activated_at = as_of - timedelta(days=2)
    snapshot_recorded_at = as_of - timedelta(minutes=20)
    mapping_recorded_at = as_of - timedelta(minutes=25)
    max_age_seconds = 7_200
    selection = CurrentReferenceSelectionV1(
        purpose="normal_simulated_current_reference",
        profile_id="unit-profile-1",
        profile_key="instrument_reference_selector",
        environment="unit-test",
        profile_version=1,
        profile_content_hash="a" * 64,
        runtime_snapshot_id="unit-runtime-snapshot-1",
        runtime_snapshot_hash="b" * 64,
        selector_content_hash="c" * 64,
        profile_activated_at=profile_activated_at,
        runtime_snapshot_generated_at=as_of - timedelta(days=1),
        selected_at=as_of,
        max_local_reference_age_seconds=max_age_seconds,
    )
    source_evidence = ExecutionInstrumentIdentityEvidenceV1(
        security_id="SH.UNIT.SECURITY",
        asset_code=ASSET_CODE,
        source_code="600000.SH",
        source_exchange="SSE",
        source_market="MAIN",
        rule_market="SH",
        board="MAIN",
        snapshot_id=UUID("1d7a01a9-5dc4-476b-aa8a-80dce07e7e39"),
        snapshot_content_hash="sha256:" + "1" * 64,
        snapshot_record_digest="sha256:" + "2" * 64,
        first_seen_at=response_completed_at,
        snapshot_recorded_at=snapshot_recorded_at,
        mapping_record_id=UUID("66d1d827-0bba-4e90-b70f-d57a82895a4d"),
        mapping_id="unit-market-mapping",
        mapping_version="unit-v1",
        mapping_content_hash="sha256:" + "3" * 64,
        mapping_record_digest="sha256:" + "4" * 64,
        mapping_recorded_at=mapping_recorded_at,
        response_completed_at=response_completed_at,
        source_observed_at=None,
        source_available_at=None,
        identity_valid_from=max(
            profile_activated_at,
            snapshot_recorded_at,
            mapping_recorded_at,
        ),
        identity_valid_until=response_completed_at + timedelta(seconds=max_age_seconds),
        must_not_use_for_decision=True,
        must_not_execute=True,
    )
    return ExecutionInstrumentIdentityEvidenceV2(
        source_evidence=source_evidence,
        selection=selection,
        source_occurrence_id=UUID("f2d263f7-4c0b-4e31-9235-6e64427d58c0"),
        reference_response_completed_at=response_completed_at,
    )


def _formal_calendar(as_of: datetime) -> ExecutionCalendarEvidence:
    """Build a typed, formally published one-day fixture for the cutoff's exchange date."""

    exchange_date = as_of.astimezone(ZoneInfo("Asia/Shanghai")).date()
    response_completed_at = as_of - timedelta(minutes=40)
    day = ExchangeCalendarDay(
        exchange="SSE",
        calendar_date=exchange_date,
        is_open=True,
        previous_open_date=exchange_date - timedelta(days=1),
    )
    raw_reference = RawCalendarReference(
        payload_id="8147d2f1-776e-43bd-89c8-b38909057da9",
        payload_hash="sha256:" + "5" * 64,
        record_digest="sha256:" + "6" * 64,
        body_sha256="7" * 64,
        retained_content_sha256="7" * 64,
        request_scope_sha256="8" * 64,
        original_body_retained=True,
        response_completed_at=response_completed_at,
        provider_name="unit-calendar-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="430606cb-c70c-4ea7-aef6-43086e017c78",
        exchange="SSE",
        coverage_start=exchange_date,
        coverage_end=exchange_date,
        days=(day,),
        provider_name="unit-calendar-provider",
        raw_reference=raw_reference,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed_at,
        recorded_at=as_of - timedelta(minutes=20),
        source_published_at=None,
    )
    publication = CalendarPublicationReference(
        publication_id="unit-calendar-publication-1",
        member_id=snapshot.snapshot_id,
        publication_hash="9" * 64,
        fact_content_hash="a" * 64,
        policy_hash="b" * 64,
        published_at=as_of - timedelta(minutes=10),
        recorded_at=as_of - timedelta(minutes=5),
        reference_valid_from=as_of - timedelta(days=1),
        reference_valid_until=as_of + timedelta(days=1),
        timezone_name="Asia/Shanghai",
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


def _price_result(
    *,
    asset_code: str = ASSET_CODE,
    trade_date: date = TRADE_DATE,
) -> PriceLookupResult:
    """Return one typed historical price result for the exact requested code/date."""

    return PriceLookupResult(
        requested_code=asset_code,
        normalized_code=asset_code,
        price=10.0,
        as_of=trade_date,
        source="unit-price-source",
        freshness="historical",
        is_fallback=False,
    )


def _position() -> Position:
    """Return an exact persisted-position-shaped SELL input."""

    return Position(
        account_id=ACCOUNT_ID,
        asset_code=ASSET_CODE,
        asset_name="Unit Security",
        asset_type="equity",
        quantity=100.0,
        available_quantity=100.0,
        avg_cost=9.0,
        total_cost=900.0,
        current_price=10.0,
        market_value=1_000.0,
        unrealized_pnl=100.0,
        unrealized_pnl_pct=11.11,
        first_buy_date=TRADE_DATE - timedelta(days=1),
        last_update_date=TRADE_DATE,
        signal_id=23,
    )


class _Clock:
    """Return one aware fixed cutoff and retain the count of captured cutoffs."""

    def __init__(self, as_of: datetime) -> None:
        self.as_of = as_of
        self.calls = 0

    def now(self) -> datetime:
        """Return the fixed aware cutoff used to compare all evidence ports."""

        self.calls += 1
        return self.as_of


class _OwnerReader:
    """Record owner reads and return the persisted test owner."""

    def __init__(self) -> None:
        self.account_ids: list[int] = []

    def get_owner_id(self, *, account_id: int) -> int | None:
        """Return one owner only after recording the exact account lookup."""

        self.account_ids.append(account_id)
        return USER_ID


class _PositionReader:
    """Record SELL position reads and return one exact typed entity."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def get_position(self, account_id: int, asset_code: str) -> Position | None:
        """Return a typed position only for the fixture's exact key."""

        self.calls.append((account_id, asset_code))
        if account_id == ACCOUNT_ID and asset_code == ASSET_CODE:
            return _position()
        return None


class _IdentityReader:
    """Return typed V2 current-reference evidence at the exact supplied cutoff."""

    def __init__(self, identity: ExecutionInstrumentIdentityEvidenceV2) -> None:
        self.identity = identity
        self.calls: list[tuple[str, datetime]] = []

    def resolve_current_reference_identity(
        self,
        *,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Record the caller cutoff and resolve only the exact fixture asset."""

        self.calls.append((asset_code, as_of))
        return self.identity if asset_code == self.identity.asset_code else None

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        """Expose the complete identity reader protocol for manual composition."""

        if security_id != self.identity.security_id or asset_code != self.identity.asset_code:
            return None
        self.identity.validate_at(as_of=as_of)
        return self.identity


class _CalendarReader:
    """Return formally published typed calendar evidence at the supplied cutoff."""

    def __init__(self, evidence: ExecutionCalendarEvidence) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, datetime, date | None]] = []

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        """Record exact exchange, cutoff, and optional requested coverage start."""

        self.calls.append((exchange, as_of, coverage_start))
        return self.evidence


class _PriceLookup:
    """Record canonical Data Center lookup arguments and return one exact object."""

    def __init__(self, result: PriceLookupResult) -> None:
        self.result = result
        self.calls: list[tuple[str, date | None, str | None]] = []

    def get_price_result(
        self,
        asset_code: str,
        trade_date: date | None = None,
        asset_type: str | None = None,
    ) -> PriceLookupResult | None:
        """Record the lookup scope without replacing its source evidence."""

        self.calls.append((asset_code, trade_date, asset_type))
        return self.result


class _ManualExecutor:
    """Stub the write boundary while retaining exact typed requests and outcomes."""

    def __init__(
        self,
        *,
        execution_date: date,
        error: Exception | None = None,
    ) -> None:
        self.execution_date = execution_date
        self.error = error
        self.requests: list[ManualSimulatedTradeRequest] = []
        self.cutoffs: list[datetime | None] = []

    def execute(
        self,
        request: ManualSimulatedTradeRequest,
        *,
        as_of: datetime | None = None,
    ) -> ManualSimulatedTradeResult:
        """Record each request and return a typed trade result unless configured to fail."""

        self.requests.append(request)
        self.cutoffs.append(as_of)
        if self.error is not None:
            raise self.error
        amount = (request.quantity * request.price).quantize(Decimal("0.01"))
        is_buy = request.side is SimulatedTradeSide.BUY
        receipt_total_cost = amount if is_buy else Decimal("0.00")
        receipt = SimulatedTradeExecutionReceipt(
            trade_id=len(self.requests),
            account_id=request.account_id,
            idempotency_key=request.idempotency_key,
            request_payload_hash="c" * 64,
            side=request.side,
            asset_code=request.asset_code,
            quantity=request.quantity,
            price=request.price,
            amount=amount,
            commission=Decimal("0.00"),
            transfer_fee=Decimal("0.00"),
            stamp_duty=Decimal("0.00"),
            slippage=Decimal("0.00"),
            total_cost=receipt_total_cost,
            settlement_status="pending" if is_buy else None,
            settlement_release_date=(self.execution_date + timedelta(days=2) if is_buy else None),
            replayed=False,
        )
        trade = SimulatedTrade(
            trade_id=len(self.requests),
            account_id=request.account_id,
            asset_code=request.asset_code,
            asset_name=request.asset_name,
            asset_type=request.asset_type,
            action=TradeAction(request.side.value),
            quantity=float(request.quantity),
            price=float(request.price),
            amount=float(amount),
            order_date=self.execution_date,
            execution_date=self.execution_date,
            execution_time=as_of if as_of is not None else AS_OF,
            total_cost=float(amount),
            reason=request.reason,
            signal_id=request.signal_id,
            status=OrderStatus.EXECUTED,
        )
        return ManualSimulatedTradeResult(trade=trade, receipt=receipt)


@dataclass
class _Harness:
    """Hold typed ports and their observations for one isolated bridge test."""

    bridge: AutomaticTradeExecutionBridge
    clock: _Clock
    owner_reader: _OwnerReader
    position_reader: _PositionReader
    identity_reader: _IdentityReader
    calendar_reader: _CalendarReader
    price_lookup: _PriceLookup
    manual_executor: _ManualExecutor


def _harness(
    *,
    execution_date: date = TRADE_DATE,
    account_ids: tuple[int, ...] = (ACCOUNT_ID,),
    price_result: PriceLookupResult | None = None,
    manual_error: Exception | None = None,
) -> _Harness:
    """Build a bridge from exact typed source fixtures and observed stub ports."""

    identity_reader = _IdentityReader(_current_identity(AS_OF))
    calendar_reader = _CalendarReader(_formal_calendar(AS_OF))
    clock = _Clock(AS_OF)
    owner_reader = _OwnerReader()
    position_reader = _PositionReader()
    lookup = _PriceLookup(price_result or _price_result(trade_date=execution_date))
    manual = _ManualExecutor(execution_date=execution_date, error=manual_error)
    bridge = AutomaticTradeExecutionBridge(
        run_id=RUN_ID,
        execution_date=execution_date,
        account_ids=account_ids,
        owner_reader=owner_reader,
        position_repository=position_reader,
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        manual_use_case=cast(ExecuteCurrentReferenceManualTradeUseCase, manual),
        clock=clock,
        price_lookup=lookup,
    )
    return _Harness(
        bridge=bridge,
        clock=clock,
        owner_reader=owner_reader,
        position_reader=position_reader,
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        price_lookup=lookup,
        manual_executor=manual,
    )


def test_buy_and_sell_share_aware_cutoff_and_unique_run_scoped_keys() -> None:
    """Use typed V2 identity/calendar, one cutoff, and one shared BUY/SELL key sequence."""

    harness = _harness()
    buy_price = harness.bridge.price_provider.require_price(ASSET_CODE, TRADE_DATE)
    buy_trade = harness.bridge.buy_use_case.execute(
        account_id=ACCOUNT_ID,
        asset_code=ASSET_CODE,
        asset_name="Unit Security",
        asset_type="equity",
        quantity=100,
        price=buy_price,
        reason="buy fixture",
        execution_date=TRADE_DATE,
    )
    sell_price = harness.bridge.price_provider.require_price(ASSET_CODE, TRADE_DATE)
    sell_trade = harness.bridge.sell_use_case.execute(
        account_id=ACCOUNT_ID,
        asset_code=ASSET_CODE,
        quantity=100,
        price=sell_price,
        reason="sell fixture",
        execution_date=TRADE_DATE,
    )

    assert buy_trade.action is TradeAction.BUY
    assert sell_trade.action is TradeAction.SELL
    assert type(harness.identity_reader.identity) is ExecutionInstrumentIdentityEvidenceV2
    assert type(harness.calendar_reader.evidence) is ExecutionCalendarEvidence
    assert type(harness.price_lookup.result) is PriceLookupResult
    assert harness.identity_reader.identity.source_evidence.source_observed_at is None
    assert harness.identity_reader.identity.source_evidence.source_available_at is None
    assert harness.identity_reader.identity.source_evidence.must_not_use_for_decision is True
    assert harness.identity_reader.identity.source_evidence.must_not_execute is True
    assert harness.price_lookup.calls == [(ASSET_CODE, TRADE_DATE, "equity")]
    assert harness.owner_reader.account_ids == [ACCOUNT_ID, ACCOUNT_ID]
    assert harness.position_reader.calls == [(ACCOUNT_ID, ASSET_CODE)]
    assert harness.identity_reader.calls == [(ASSET_CODE, AS_OF), (ASSET_CODE, AS_OF)]
    assert harness.calendar_reader.calls == [
        ("SSE", AS_OF, None),
        ("SSE", AS_OF, None),
    ]
    assert harness.manual_executor.cutoffs == [AS_OF, AS_OF]
    assert all(
        value is not None and value.utcoffset() == timedelta(0)
        for value in harness.manual_executor.cutoffs
    )
    assert [request.idempotency_key for request in harness.manual_executor.requests] == [
        f"auto:{RUN_ID.hex}:1:buy",
        f"auto:{RUN_ID.hex}:2:sell",
    ]
    assert harness.manual_executor.requests[1].asset_name == "Unit Security"
    assert harness.manual_executor.requests[1].signal_id == 23


def test_wrong_frozen_account_blocks_before_any_port_read() -> None:
    """Reject an account outside the persisted run scope without reading downstream ports."""

    harness = _harness(account_ids=(ACCOUNT_ID,))

    with pytest.raises(AutomaticTradeExecutionPreflightBlocked) as captured:
        harness.bridge.buy_use_case.execute(
            account_id=ACCOUNT_ID + 1,
            asset_code=ASSET_CODE,
            asset_name="Unit Security",
            asset_type="equity",
            quantity=100,
            price=10.0,
            reason="out-of-scope fixture",
            execution_date=TRADE_DATE,
        )

    assert captured.value.code == "AUTO_TRADE_ACCOUNT_INVALID"
    assert harness.price_lookup.calls == []
    assert harness.owner_reader.account_ids == []
    assert harness.position_reader.calls == []
    assert harness.identity_reader.calls == []
    assert harness.calendar_reader.calls == []
    assert harness.manual_executor.requests == []


def test_formal_calendar_date_mismatch_blocks_before_manual_executor() -> None:
    """Require the published session at the cutoff to equal the frozen run date."""

    execution_date = TRADE_DATE + timedelta(days=1)
    harness = _harness(execution_date=execution_date)
    price = harness.bridge.price_provider.require_price(ASSET_CODE, execution_date)

    with pytest.raises(AutomaticTradeExecutionPreflightBlocked) as captured:
        harness.bridge.buy_use_case.execute(
            account_id=ACCOUNT_ID,
            asset_code=ASSET_CODE,
            asset_name="Unit Security",
            asset_type="equity",
            quantity=100,
            price=price,
            reason="calendar mismatch fixture",
            execution_date=execution_date,
        )

    assert captured.value.code == "AUTO_TRADE_EXECUTION_DATE_MISMATCH"
    assert len(harness.identity_reader.calls) == 1
    assert harness.calendar_reader.calls == [("SSE", AS_OF, None)]
    assert harness.manual_executor.requests == []


@pytest.mark.parametrize("mismatch", ("date", "requested_code", "fallback"))
def test_captured_price_date_or_asset_evidence_mismatch_blocks(
    mismatch: str,
) -> None:
    """Do not trust Engine floats when the captured typed result differs in date or identity."""

    result = _price_result()
    if mismatch == "date":
        result = replace(result, as_of=TRADE_DATE - timedelta(days=1))
    elif mismatch == "requested_code":
        result = replace(result, requested_code="000001.SZ")
    else:
        result = replace(result, freshness="close_fallback", is_fallback=True)
    harness = _harness(price_result=result)
    price = harness.bridge.price_provider.require_price(ASSET_CODE, TRADE_DATE)

    with pytest.raises(AutomaticTradeExecutionPreflightBlocked) as captured:
        harness.bridge.buy_use_case.execute(
            account_id=ACCOUNT_ID,
            asset_code=ASSET_CODE,
            asset_name="Unit Security",
            asset_type="equity",
            quantity=100,
            price=price,
            reason="price evidence mismatch fixture",
            execution_date=TRADE_DATE,
        )

    assert captured.value.code == "AUTO_TRADE_PRICE_EVIDENCE_MISMATCH"
    assert harness.price_lookup.calls == [(ASSET_CODE, TRADE_DATE, "equity")]
    assert harness.owner_reader.account_ids == []
    assert harness.identity_reader.calls == []
    assert harness.calendar_reader.calls == []
    assert harness.manual_executor.requests == []


def test_typed_settlement_block_is_preflight_but_readback_unknown_is_indeterminate() -> None:
    """Keep a UoW rejection distinct from the manual use case's post-write readback state."""

    blocked = _harness(manual_error=SimulatedTradeExecutionBlocked("risk denied"))
    blocked.bridge.price_provider.require_price(ASSET_CODE, TRADE_DATE)

    with pytest.raises(AutomaticTradeExecutionPreflightBlocked) as preflight:
        blocked.bridge.buy_use_case.execute(
            account_id=ACCOUNT_ID,
            asset_code=ASSET_CODE,
            asset_name="Unit Security",
            asset_type="equity",
            quantity=100,
            price=10.0,
            reason="typed UoW rejection",
            execution_date=TRADE_DATE,
        )

    assert preflight.value.code == "AUTO_TRADE_SETTLEMENT_PREFLIGHT_BLOCKED"
    assert len(blocked.manual_executor.requests) == 1

    readback = _harness(
        manual_error=SimulatedTradeExecutionReadbackUnknown("trade readback unavailable")
    )
    readback.bridge.price_provider.require_price(ASSET_CODE, TRADE_DATE)

    with pytest.raises(SimulatedTradeExecutionReadbackUnknown) as indeterminate:
        readback.bridge.buy_use_case.execute(
            account_id=ACCOUNT_ID,
            asset_code=ASSET_CODE,
            asset_name="Unit Security",
            asset_type="equity",
            quantity=100,
            price=10.0,
            reason="dedicated readback uncertainty",
            execution_date=TRADE_DATE,
        )

    assert indeterminate.value.effects_indeterminate is True
    assert not isinstance(indeterminate.value, AutomaticTradeExecutionPreflightBlocked)
    assert len(readback.manual_executor.requests) == 1


def test_bridge_preserves_settlement_result_unknown_before_generic_blocked() -> None:
    """Keep a post-repository UoW uncertainty out of the known preflight path."""

    unknown_type = getattr(
        settlement_uow_application,
        "SimulatedTradeExecutionResultUnknown",
        None,
    )
    assert isinstance(unknown_type, type)
    assert issubclass(unknown_type, SimulatedTradeExecutionBlocked)
    assert getattr(unknown_type, "effects_indeterminate", False) is True
    assert issubclass(SimulatedTradeExecutionReadbackUnknown, unknown_type)

    error_type = cast(type[Exception], unknown_type)
    harness = _harness(manual_error=error_type("settlement result is unreadable"))
    price = harness.bridge.price_provider.require_price(ASSET_CODE, TRADE_DATE)

    with pytest.raises(error_type) as captured:
        harness.bridge.buy_use_case.execute(
            account_id=ACCOUNT_ID,
            asset_code=ASSET_CODE,
            asset_name="Unit Security",
            asset_type="equity",
            quantity=100,
            price=price,
            reason="post-repository result uncertainty",
            execution_date=TRADE_DATE,
        )

    assert captured.value.effects_indeterminate is True
    assert not isinstance(captured.value, AutomaticTradeExecutionPreflightBlocked)


def test_locked_account_scope_unavailable_keeps_a_known_block_and_stop_code() -> None:
    """Preserve the locked repository's no-scope result as a known stop, not an unknown write."""
    error_type = getattr(
        settlement_uow_application,
        "SimulatedTradeAccountScopeUnavailable",
        None,
    )
    assert isinstance(error_type, type)
    assert issubclass(error_type, SimulatedTradeExecutionBlocked)

    scope_error = cast(type[Exception], error_type)(
        "simulated account no longer matches the execution scope"
    )
    harness = _harness(manual_error=scope_error)
    price = harness.bridge.price_provider.require_price(ASSET_CODE, TRADE_DATE)

    with pytest.raises(AutomaticTradeExecutionPreflightBlocked) as captured:
        harness.bridge.buy_use_case.execute(
            account_id=ACCOUNT_ID,
            asset_code=ASSET_CODE,
            asset_name="Unit Security",
            asset_type="equity",
            quantity=100,
            price=price,
            reason="lock-time account scope changed",
            execution_date=TRADE_DATE,
        )

    assert captured.value.code == "AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE"
    assert captured.value.__cause__ is scope_error
    assert not isinstance(captured.value, SimulatedTradeExecutionReadbackUnknown)


@pytest.mark.parametrize(
    ("second_read", "expected_code"),
    (
        ("different_owner", "AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE"),
        ("missing_owner", "AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE"),
        ("invalid_owner", "AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE"),
        ("read_error", "AUTO_TRADE_ACCOUNT_SCOPE_UNAVAILABLE"),
        ("same_owner", "AUTO_TRADE_SETTLEMENT_PREFLIGHT_BLOCKED"),
    ),
)
def test_known_preflight_rereads_owner_and_stops_only_when_scope_is_unavailable(
    second_read: str,
    expected_code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop on lost ownership after a known block while preserving stable-owner preflights."""

    harness = _harness(manual_error=SimulatedTradeExecutionBlocked("fee scope unavailable"))
    harness.bridge.price_provider.require_price(ASSET_CODE, TRADE_DATE)

    def read_owner_for_this_attempt(*, account_id: int) -> int | None:
        harness.owner_reader.account_ids.append(account_id)
        if len(harness.owner_reader.account_ids) == 1:
            return USER_ID
        if second_read == "different_owner":
            return USER_ID + 1
        if second_read == "missing_owner":
            return None
        if second_read == "invalid_owner":
            return cast(int | None, True)
        if second_read == "read_error":
            raise RuntimeError("current account owner is unreadable")
        if second_read == "same_owner":
            return USER_ID
        raise AssertionError(f"unknown second owner read case: {second_read}")

    monkeypatch.setattr(harness.owner_reader, "get_owner_id", read_owner_for_this_attempt)

    with pytest.raises(AutomaticTradeExecutionPreflightBlocked) as captured:
        harness.bridge.buy_use_case.execute(
            account_id=ACCOUNT_ID,
            asset_code=ASSET_CODE,
            asset_name="Unit Security",
            asset_type="equity",
            quantity=100,
            price=10.0,
            reason="known settlement preflight block",
            execution_date=TRADE_DATE,
        )

    assert captured.value.code == expected_code
    assert harness.owner_reader.account_ids == [ACCOUNT_ID, ACCOUNT_ID]
    assert len(harness.manual_executor.requests) == 1
