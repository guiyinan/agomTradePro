"""Contracts for the signed owner-scoped ordinary order submission use case."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.core import signing

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionMarketV2
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.manual_trade_execution import ManualSimulatedTradeRequest
from apps.simulated_trading.application.order_reservation import reservation_request_from_intent
from apps.simulated_trading.application.order_submission_market import (
    LocalOrderSubmissionMarket,
    LocalSimulatedOrderSubmissionGuard,
    OrderSubmissionAccountState,
    SimulatedOrderSubmissionGuard,
)
from apps.simulated_trading.application.owner_order_submission import (
    OwnerOrderSubmissionUseCase,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
    SettlementExecutionPlanV3,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionCalendarEvidence,
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservationBook,
    OrderReservationResult,
    reserve_order,
)
from apps.simulated_trading.infrastructure import owner_order_preview_codec as preview_codec
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    require_stored_submission_market_purpose,
    snapshot_digest,
    stored_submission_market_purpose,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.owner_order_preview_codec import (
    SignedOwnerOrderPreviewCodec,
)
from tests.api.test_manual_trade_current_reference import _current_identity
from tests.unit.risk_center.test_execution_submission_v2 import _market_v2
from tests.unit.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _bundle,
    _calendar,
    _fee_policy,
)


@dataclass
class _MutableClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class _CurrentIdentityReader:
    def __init__(self, identity: ExecutionInstrumentIdentityEvidenceV2) -> None:
        self.identity = identity
        self.available = True
        self.resolve_calls: list[tuple[str, datetime]] = []
        self.execution_calls: list[tuple[str, str, datetime]] = []

    def resolve_current_reference_identity(
        self, *, asset_code: str, as_of: datetime
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        self.resolve_calls.append((asset_code, as_of))
        if not self.available:
            return None
        if asset_code != self.identity.asset_code:
            raise AssertionError("test identity fixture was asked for another asset")
        return replace(self.identity, selection=replace(self.identity.selection, selected_at=as_of))

    def get_execution_instrument_identity(
        self, *, security_id: str, asset_code: str, as_of: datetime
    ) -> ExecutionInstrumentIdentityEvidenceV2 | None:
        self.execution_calls.append((security_id, asset_code, as_of))
        if not self.available:
            return None
        if (security_id, asset_code) != (self.identity.security_id, self.identity.asset_code):
            raise AssertionError("test identity fixture was asked for another security")
        return replace(self.identity, selection=replace(self.identity.selection, selected_at=as_of))


class _RuleReader:
    def __init__(self, bundle: ExecutionSettlementBundleV3) -> None:
        self.bundle = bundle
        self.calls: list[tuple[str, datetime]] = []

    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        self.calls.append((security_id, as_of))
        if security_id != "SH.UOW.SECURITY":
            raise AssertionError("unexpected settlement security")
        return self.bundle


class _CalendarReader:
    def __init__(self, evidence: ExecutionCalendarEvidence) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, datetime, object]] = []

    def get_effective_execution_calendar(
        self, *, exchange: str, as_of: datetime, coverage_start: object
    ) -> ExecutionCalendarEvidence:
        self.calls.append((exchange, as_of, coverage_start))
        if exchange != "SSE":
            raise AssertionError("unexpected identity exchange")
        return self.evidence


class _FeeReader:
    def __init__(self) -> None:
        self.policy = _fee_policy()
        self.calls: list[tuple[int, int, str, str, str, SimulatedTradeSide, datetime]] = []

    def get_execution_fee_policy(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_type: str,
        market: str,
        board: str,
        side: SimulatedTradeSide,
        as_of: datetime,
    ) -> object:
        self.calls.append((account_id, user_id, asset_type, market, board, side, as_of))
        return self.policy


class _PreparationRepository:
    def get_pending_settlement_scope(
        self, *, account_id: int, user_id: int, asset_code: str
    ) -> None:
        if (account_id, user_id, asset_code) != (7, 11, "600000.SH"):
            raise AssertionError("unexpected pending settlement scope")
        return None


@dataclass(frozen=True)
class _StoredOrder:
    intent: SimulatedTradeIntent
    fee_budget: Decimal | None
    result: OrderReservationResult
    order_id: int
    market_purpose: str


class _OwnerRepository:
    def __init__(self, *, owner_user_id: int = 11) -> None:
        self.owner_user_id = owner_user_id
        self.book = OrderReservationBook(
            account_id=7,
            security_id="SH.UOW.SECURITY",
            book_cash=Decimal("5000.00"),
            withdrawable_cash=Decimal("5000.00"),
            sellable_shares=Decimal("0.000000"),
            reservations=(),
        )
        self.owner_checks: list[tuple[int, int]] = []
        self.state_reads: list[tuple[object, datetime]] = []
        self.idempotency_reads: list[tuple[SimulatedTradeIntent, Decimal | None]] = []
        self.order_readbacks: list[SimulatedTradeIntent] = []
        self.write_calls = 0
        self.stored: _StoredOrder | None = None

    def require_owned_active_account(self, *, account_id: int, user_id: int) -> None:
        self.owner_checks.append((account_id, user_id))
        if (account_id, user_id) != (7, self.owner_user_id):
            raise SimulatedTradeAccountScopeUnavailable()

    def read_submission_state(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        clock: _MutableClock,
    ) -> OrderSubmissionAccountState:
        self.state_reads.append((plan, clock.now()))
        if (plan.intent.account_id, plan.intent.user_id) != (7, self.owner_user_id):
            raise SimulatedTradeAccountScopeUnavailable()
        return OrderSubmissionAccountState(book=self.book, total_quantity=None, read_at=clock.now())

    def find_idempotent_reservation(
        self,
        *,
        intent: SimulatedTradeIntent,
        fee_budget: Decimal | None,
        market_purpose: str | None = None,
    ) -> OrderReservationResult | None:
        self.idempotency_reads.append((intent, fee_budget))
        if (intent.account_id, intent.user_id) != (7, self.owner_user_id):
            raise SimulatedTradeAccountScopeUnavailable()
        if self.stored is None:
            return None
        if (self.stored.intent, self.stored.fee_budget) != (intent, fee_budget):
            raise SimulatedTradeExecutionInputError("idempotency key is bound to another request")
        if market_purpose is not None and self.stored.market_purpose != market_purpose:
            raise SimulatedTradeIdempotencyConflict(
                "idempotency key is bound to another market purpose"
            )
        return replace(self.stored.result, replayed=True)

    def get_owned_order_id(self, *, intent: SimulatedTradeIntent) -> int:
        self.order_readbacks.append(intent)
        if (intent.account_id, intent.user_id) != (7, self.owner_user_id):
            raise SimulatedTradeAccountScopeUnavailable()
        if self.stored is None or self.stored.intent != intent:
            raise SimulatedTradeAccountScopeUnavailable()
        return self.stored.order_id

    def commit(
        self,
        *,
        intent: SimulatedTradeIntent,
        fee_budget: Decimal | None,
        result: OrderReservationResult,
        market_purpose: str,
    ) -> None:
        self.write_calls += 1
        self.book = result.book
        self.stored = _StoredOrder(
            intent,
            fee_budget,
            result,
            order_id=801,
            market_purpose=market_purpose,
        )


@dataclass(frozen=True)
class _MarketRead:
    capture_id: str
    intent_hash: str
    market_hash: str
    bundle_hash: str
    as_of: datetime


class _RetainedMarket:
    def __init__(
        self,
        *,
        market: ExecutionSubmissionMarketV2,
        intent: SimulatedTradeIntent,
        capture_id: str,
    ) -> None:
        self.market = market
        self.intent = intent
        self.capture_id = capture_id
        self.closed = False
        self.reads: list[_MarketRead] = []
        self.preview_bundle_hash: str | None = None

    def export_retained_source(self) -> dict[str, object]:
        return {
            "capture_id": self.capture_id,
            "intent_hash": self.intent.request_payload_hash,
            "market_hash": self.market.content_hash,
            "market_source_hash": self.market.market_evidence_v1.market_source_hash,
        }

    def read_market(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        as_of: datetime,
    ) -> LocalOrderSubmissionMarket:
        if self.closed:
            raise SimulatedTradeExecutionBlocked("retained test source is closed")
        if plan.intent != self.intent:
            raise AssertionError("market capture no longer matches the exact signed intent")
        if plan.intent.request_payload_hash != self.intent.request_payload_hash:
            raise AssertionError("market source is not bound to the requested intent")
        if self.preview_bundle_hash is None:
            self.preview_bundle_hash = execution_bundle.content_hash
        elif execution_bundle.content_hash != self.preview_bundle_hash:
            raise AssertionError("locked check did not use the previewed settlement bundle")
        source = self.market.market_evidence_v1
        if source.security_id != plan.intent.security_id or source.market != plan.intent.market:
            raise AssertionError("market capture is not bound to the exact instrument")
        self.reads.append(
            _MarketRead(
                capture_id=self.capture_id,
                intent_hash=plan.intent.request_payload_hash,
                market_hash=self.market.content_hash,
                bundle_hash=execution_bundle.content_hash,
                as_of=as_of,
            )
        )
        return LocalOrderSubmissionMarket(
            market=self.market,
            provenance={
                "capture_id": self.capture_id,
                "intent_hash": self.intent.request_payload_hash,
                "market_hash": self.market.content_hash,
            },
        )


class _MarketFactory:
    def __init__(self, market: ExecutionSubmissionMarketV2) -> None:
        self.market = market
        self.available = True
        self.closed = False
        self.capture_calls: list[SimulatedTradeIntent] = []
        self.restore_calls: list[dict[str, object]] = []
        self.retained: _RetainedMarket | None = None

    def capture(self, *, intent: SimulatedTradeIntent) -> _RetainedMarket:
        self.capture_calls.append(intent)
        if not self.available:
            raise SimulatedTradeExecutionBlocked("qualified market source is unavailable")
        self.retained = _RetainedMarket(
            market=self.market,
            intent=intent,
            capture_id=f"synthetic-capture-{len(self.capture_calls)}",
        )
        return self.retained

    def restore(self, *, payload: dict[str, object]) -> _RetainedMarket:
        self.restore_calls.append(dict(payload))
        if (
            self.closed
            or self.retained is None
            or payload != self.retained.export_retained_source()
        ):
            raise SimulatedTradeExecutionBlocked("retained market source cannot be restored")
        return self.retained


class _GuardedWriter:
    def __init__(
        self,
        *,
        repository: _OwnerRepository,
        guard: SimulatedOrderSubmissionGuard,
        unknown_after_commit: bool,
    ) -> None:
        self.repository = repository
        self.guard = guard
        self.unknown_after_commit = unknown_after_commit
        self.reserve_calls = 0
        self.guard_receipts: list[dict[str, object]] = []
        self.intents: list[SimulatedTradeIntent] = []
        self.fee_budgets: list[Decimal | None] = []

    def reserve_order(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        fee_budget: Decimal | None,
        clock: _MutableClock,
    ) -> OrderReservationResult:
        self.reserve_calls += 1
        # This is the real source guard invoked by the simulated ordinary writer while
        # it owns the account lock; it is not replaced with a test-side mirror.
        receipt = self.guard.validate_locked_submission(
            plan=plan,
            execution_bundle=execution_bundle,
            book=self.repository.book,
            total_quantity=None,
            as_of=clock.now(),
        )
        self.guard_receipts.append(receipt)
        self.intents.append(plan.intent)
        self.fee_budgets.append(fee_budget)
        result = reserve_order(
            self.repository.book,
            reservation_request_from_intent(plan.intent, fee_budget=fee_budget),
            plan.fee_policy_v2,
            reserved_at=clock.now(),
        )
        self.repository.commit(
            intent=plan.intent,
            fee_budget=fee_budget,
            result=result,
            market_purpose=self.guard.market_purpose,
        )
        if self.unknown_after_commit:
            raise SimulatedTradeExecutionResultUnknown("simulated unknown commit result")
        return result


class _WriterFactory:
    def __init__(self, repository: _OwnerRepository) -> None:
        self.repository = repository
        self.unknown_after_commit = False
        self.build_calls: list[SimulatedOrderSubmissionGuard] = []
        self.writers: list[_GuardedWriter] = []

    def build(self, *, guard: SimulatedOrderSubmissionGuard) -> _GuardedWriter:
        self.build_calls.append(guard)
        writer = _GuardedWriter(
            repository=self.repository,
            guard=guard,
            unknown_after_commit=self.unknown_after_commit,
        )
        self.writers.append(writer)
        return writer


@dataclass
class _Harness:
    clock: _MutableClock
    identity_reader: _CurrentIdentityReader
    rule_reader: _RuleReader
    fee_reader: _FeeReader
    repository: _OwnerRepository
    market_factory: _MarketFactory
    writer_factory: _WriterFactory
    use_case: OwnerOrderSubmissionUseCase


def _submission_market(*, valid_until: datetime) -> ExecutionSubmissionMarketV2:
    available_at = min(AS_OF - timedelta(seconds=1), valid_until - timedelta(seconds=1))
    observed_at = min(AS_OF - timedelta(seconds=2), available_at - timedelta(seconds=1))
    base = _market_v2(
        market_observed_at=observed_at,
        market_available_at=available_at,
        market_valid_until=valid_until,
    )
    evidence = replace(
        base.market_evidence_v1,
        security_id="SH.UOW.SECURITY",
        market="SH",
        board="MAIN",
        content_hash="",
    )
    return replace(base, market_evidence_v1=evidence, content_hash="")


def _harness(
    *,
    market_valid_until: datetime | None = None,
    market_purpose: str = "local_simulation_only",
) -> _Harness:
    clock = _MutableClock(AS_OF)
    identity_reader = _CurrentIdentityReader(_current_identity())
    rule_reader = _RuleReader(_bundle())
    calendar_reader = _CalendarReader(_calendar(exchange="SSE"))
    fee_reader = _FeeReader()
    preparation_repository = _PreparationRepository()
    preparer = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=rule_reader,
        identity_reader=identity_reader,
        calendar_reader=calendar_reader,
        fee_policy_reader=fee_reader,
        repository=preparation_repository,
        clock=clock,
    )
    repository = _OwnerRepository()
    market_factory = _MarketFactory(
        _submission_market(valid_until=market_valid_until or AS_OF + timedelta(minutes=5))
    )
    writer_factory = _WriterFactory(repository)
    use_case = OwnerOrderSubmissionUseCase(
        identity_reader=identity_reader,
        preparer=preparer,
        repository=repository,
        repository_factory=writer_factory,
        market_factory=market_factory,
        codec=SignedOwnerOrderPreviewCodec(),
        clock=clock,
        market_purpose=market_purpose,
    )
    return _Harness(
        clock,
        identity_reader,
        rule_reader,
        fee_reader,
        repository,
        market_factory,
        writer_factory,
        use_case,
    )


def _request(*, user_id: int = 11, key: str = "owner-order-001") -> ManualSimulatedTradeRequest:
    return ManualSimulatedTradeRequest(
        account_id=7,
        user_id=user_id,
        idempotency_key=key,
        asset_code="600000.SH",
        asset_name="fixture equity",
        asset_type="equity",
        side=SimulatedTradeSide.BUY,
        quantity=Decimal("100"),
        price=Decimal("10.00"),
        reason="owner order submission contract",
        signal_id=None,
    )


def _fee_budget_for(
    harness: _Harness,
    request: ManualSimulatedTradeRequest,
) -> Decimal:
    """Use the exact fixture policy estimate for a valid reservation budget."""

    identity = harness.identity_reader.identity
    notional = (request.quantity * request.price).quantize(Decimal("0.01"))
    return harness.fee_reader.policy.calculate_for(
        asset_type=request.asset_type,
        market=identity.rule_market,
        board=identity.board,
        side=request.side,
        amount=notional,
        as_of=harness.clock.now(),
    ).total_fee


def test_preview_codec_preserves_legacy_shape_and_binds_close_source_purpose() -> None:
    harness = _harness()
    request = _request()
    preview = harness.use_case.preview(request, fee_budget=_fee_budget_for(harness, request))
    codec = SignedOwnerOrderPreviewCodec()
    legacy_payload = signing.loads(preview.token, salt=preview_codec._SALT)
    assert type(legacy_payload) is dict
    assert "market_purpose" not in legacy_payload
    assert codec.open(preview.token).market_purpose == "local_simulation_only"

    payload = dict(legacy_payload)
    payload["market_purpose"] = "close_snapshot_simulation"
    retained_source = dict(payload["retained_source"])
    retained_source["purpose"] = "close_snapshot_simulation"
    retained_source["account_id"] = 7
    payload["retained_source"] = retained_source
    close_token = signing.dumps(payload, salt=preview_codec._SALT, compress=True)
    binding = codec.open(close_token)
    assert binding.market_purpose == "close_snapshot_simulation"
    assert binding.retained_source["purpose"] == binding.market_purpose
    assert binding.retained_source["account_id"] == binding.intent.account_id
    assert codec.seal(binding) == close_token


@pytest.mark.parametrize(
    ("market_purpose", "source_purpose", "source_account_id"),
    [
        ("future_market", "future_market", 7),
        ("close_snapshot_simulation", "local_simulation_only", 7),
        ("close_snapshot_simulation", "close_snapshot_simulation", 8),
        ("local_simulation_only", None, 7),
    ],
)
def test_preview_codec_rejects_unknown_or_mismatched_close_purpose(
    market_purpose: str, source_purpose: str | None, source_account_id: int
) -> None:
    harness = _harness()
    request = _request()
    preview = harness.use_case.preview(request, fee_budget=_fee_budget_for(harness, request))
    payload_value = signing.loads(preview.token, salt=preview_codec._SALT)
    assert type(payload_value) is dict
    payload = dict(payload_value)
    payload["market_purpose"] = market_purpose
    retained_source_value = payload["retained_source"]
    assert type(retained_source_value) is dict
    retained_source = dict(retained_source_value)
    retained_source["purpose"] = source_purpose
    retained_source["account_id"] = source_account_id
    payload["retained_source"] = retained_source
    token = signing.dumps(payload, salt=preview_codec._SALT, compress=True)

    with pytest.raises(SimulatedTradeExecutionInputError):
        SignedOwnerOrderPreviewCodec().open(token)


def test_application_rejects_unknown_market_purpose_at_construction() -> None:
    with pytest.raises(SimulatedTradeExecutionInputError, match="行情用途"):
        _harness(market_purpose="fresh-but-unqualified")


def test_close_purpose_cannot_sign_a_local_market_receipt() -> None:
    harness = _harness(market_purpose="close_snapshot_simulation")
    request = _request()

    with pytest.raises(SimulatedTradeExecutionBlocked, match="行情用途"):
        harness.use_case.preview(request, fee_budget=_fee_budget_for(harness, request))

    assert len(harness.market_factory.capture_calls) == 1
    captured = harness.market_factory.capture_calls[0]
    identity = harness.identity_reader.identity
    assert captured == SimulatedTradeIntent(
        account_id=request.account_id,
        user_id=request.user_id,
        idempotency_key=request.idempotency_key,
        side=request.side,
        security_id=identity.security_id,
        asset_code=request.asset_code,
        asset_name=request.asset_name,
        asset_type=request.asset_type,
        market=identity.rule_market,
        board=identity.board,
        quantity=request.quantity,
        price=request.price,
        reason=request.reason,
        signal_id=request.signal_id,
    )
    assert harness.repository.stored is None
    assert harness.writer_factory.build_calls == []


@pytest.mark.parametrize(
    "snapshot",
    [
        {"submission_market": None},
        {"submission_market": {}},
        {"submission_market": {"purpose": None}},
        {"submission_market": {"purpose": "unqualified-live"}},
    ],
)
def test_persisted_unknown_market_purpose_is_not_downgraded_to_legacy_local(
    snapshot: dict[str, object],
) -> None:
    with pytest.raises(SimulatedTradeExecutionBlocked, match="用途凭据"):
        stored_submission_market_purpose(snapshot)


def test_persisted_market_purpose_uses_explicit_close_or_legacy_only() -> None:
    assert stored_submission_market_purpose({}) == "local_simulation_only"
    assert (
        stored_submission_market_purpose(
            {"submission_market": {"purpose": "local_simulation_only"}}
        )
        == "local_simulation_only"
    )
    assert (
        stored_submission_market_purpose(
            {"submission_market": {"purpose": "close_snapshot_simulation"}}
        )
        == "close_snapshot_simulation"
    )


def test_foreign_owner_is_rejected_before_any_identity_or_market_capture() -> None:
    harness = _harness()

    with pytest.raises(SimulatedTradeAccountScopeUnavailable):
        harness.use_case.preview(_request(user_id=12), fee_budget=Decimal("20.00"))

    assert harness.repository.owner_checks == [(7, 12)]
    assert harness.identity_reader.resolve_calls == []
    assert harness.market_factory.capture_calls == []
    assert harness.repository.write_calls == 0


def test_locked_market_guard_rejects_receipt_that_disagrees_with_signed_preview_purpose() -> None:
    """A close-risk purpose cannot turn the existing local market into a close receipt."""

    harness = _harness()
    request = _request()
    intent, identity = harness.use_case._resolve(request)
    prepared = harness.use_case._preparer.prepare(intent, as_of=identity.selection.selected_at)
    market = harness.market_factory.capture(intent=intent)
    state = harness.repository.read_submission_state(
        plan=prepared.plan,
        clock=harness.clock,
    )
    guard = LocalSimulatedOrderSubmissionGuard(
        market_reader=market,
        market_purpose="close_snapshot_simulation",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        guard.validate_locked_submission(
            plan=prepared.plan,
            execution_bundle=prepared.execution_bundle,
            book=state.book,
            total_quantity=state.total_quantity,
            as_of=state.read_at,
        )

    assert error.value.code == "SIMULATED_ORDER_MARKET_PURPOSE_MISMATCH"
    assert harness.repository.write_calls == 0
    assert harness.writer_factory.build_calls == []


def test_reserved_market_purpose_tampering_fails_the_existing_plan_snapshot_seal() -> None:
    """Fill-time purpose is read only after the plan snapshot's original hash verifies."""

    payload: dict[str, object] = {
        "schema": "simulated-order-reservation-plan.v1",
        "submission_market": {"purpose": "close_snapshot_simulation"},
    }
    row = SimulatedOrderReservationModel(
        plan_snapshot_version=1,
        plan_snapshot=payload,
        plan_snapshot_hash=snapshot_digest(payload),
    )
    assert (
        stored_submission_market_purpose(validated_plan_snapshot(row))
        == "close_snapshot_simulation"
    )

    row.plan_snapshot = {
        "schema": "simulated-order-reservation-plan.v1",
        "submission_market": {"purpose": "local_simulation_only"},
    }
    with pytest.raises(SimulatedTradeExecutionBlocked):
        validated_plan_snapshot(row)


def test_stored_market_purpose_helper_blocks_cross_purpose_idempotent_replay() -> None:
    """A row locked by another purpose cannot be replayed as this owner's request."""

    with pytest.raises(SimulatedTradeIdempotencyConflict):
        require_stored_submission_market_purpose(
            snapshot={"submission_market": {"purpose": "close_snapshot_simulation"}},
            expected="local_simulation_only",
        )


def test_signed_preview_rechecks_same_capture_under_writer_guard_and_recovers_first() -> None:
    harness = _harness()
    fee_budget = Decimal("20.00")
    preview = harness.use_case.preview(_request(), fee_budget=fee_budget)
    binding = SignedOwnerOrderPreviewCodec().open(preview.token)

    assert binding.intent.account_id == 7
    assert binding.intent.user_id == 11
    assert binding.intent.idempotency_key == "owner-order-001"
    assert binding.fee_budget == fee_budget
    assert binding.expires_at == preview.expires_at
    assert binding.market_source_hash == (
        harness.market_factory.retained.market.market_evidence_v1.market_source_hash
    )
    assert harness.repository.write_calls == 0
    assert harness.writer_factory.build_calls == []
    assert len(harness.market_factory.capture_calls) == 1
    assert len(harness.market_factory.retained.reads) == 1

    before_find = len(harness.repository.idempotency_reads)
    tampered_index = len(preview.token) // 2
    tampered_character = "A" if preview.token[tampered_index] != "A" else "B"
    tampered = (
        preview.token[:tampered_index] + tampered_character + preview.token[tampered_index + 1 :]
    )
    with pytest.raises(SimulatedTradeExecutionInputError):
        harness.use_case.confirm(account_id=7, user_id=11, token=tampered, confirmed=True)
    assert len(harness.repository.idempotency_reads) == before_find
    assert harness.market_factory.restore_calls == []
    assert harness.writer_factory.build_calls == []
    assert harness.repository.write_calls == 0

    harness.clock.value = AS_OF + timedelta(seconds=2)
    result = harness.use_case.confirm(
        account_id=7,
        user_id=11,
        token=preview.token,
        confirmed=True,
    )

    assert result.order_id == 801
    assert result.result.replayed is False
    assert result.result.reservation.fee_budget == fee_budget
    assert harness.repository.write_calls == 1
    assert len(harness.market_factory.restore_calls) == 1
    assert len(harness.writer_factory.writers) == 1
    writer = harness.writer_factory.writers[0]
    assert writer.intents == [binding.intent]
    assert writer.fee_budgets == [fee_budget]
    assert writer.reserve_calls == 1
    assert len(writer.guard_receipts) == 1
    assert writer.guard_receipts[0]["purpose"] == binding.market_purpose
    assert harness.writer_factory.build_calls[0].market_purpose == binding.market_purpose
    assert writer.guard_receipts[0]["intent_hash"] == binding.intent.request_payload_hash

    retained = harness.market_factory.retained
    assert retained is not None
    assert len(retained.reads) == 2
    assert retained.reads[0].capture_id == retained.reads[1].capture_id
    assert retained.reads[0].intent_hash == retained.reads[1].intent_hash
    assert retained.reads[0].market_hash == retained.reads[1].market_hash
    assert retained.reads[0].bundle_hash == retained.reads[1].bundle_hash
    assert retained.reads[0].as_of == AS_OF
    assert retained.reads[1].as_of == AS_OF + timedelta(seconds=2)
    assert (
        writer.guard_receipts[0]["market"]["content_hash"]
        == preview.market_receipt["market"]["content_hash"]
    )

    # Existing-order recovery is checked before preparing any source or restoring the token's
    # market capture, even after every new-order evidence window has gone stale.
    reads_before_replay = len(retained.reads)
    restores_before_replay = len(harness.market_factory.restore_calls)
    builds_before_replay = len(harness.writer_factory.build_calls)
    writes_before_replay = harness.repository.write_calls
    harness.clock.value = AS_OF + timedelta(days=40)
    harness.identity_reader.available = False
    harness.market_factory.closed = True
    retained.closed = True
    replay = harness.use_case.confirm(
        account_id=7,
        user_id=11,
        token=preview.token,
        confirmed=True,
    )
    assert replay.order_id == result.order_id
    assert replay.result.replayed is True
    assert len(retained.reads) == reads_before_replay
    assert len(harness.market_factory.restore_calls) == restores_before_replay
    assert len(harness.writer_factory.build_calls) == builds_before_replay
    assert harness.repository.write_calls == writes_before_replay
    assert len(harness.repository.order_readbacks) == 2


@pytest.mark.parametrize("missing", ("identity", "market", "expired_market"))
def test_preview_blocks_missing_or_expired_source_without_a_write(missing: str) -> None:
    harness = _harness(
        market_valid_until=(AS_OF - timedelta(seconds=1) if missing == "expired_market" else None)
    )
    if missing == "identity":
        harness.identity_reader.available = False
    elif missing == "market":
        harness.market_factory.available = False

    with pytest.raises(SimulatedTradeExecutionBlocked):
        harness.use_case.preview(_request(), fee_budget=Decimal("20.00"))

    assert harness.repository.write_calls == 0
    assert harness.writer_factory.build_calls == []
    assert len(harness.market_factory.capture_calls) == (0 if missing == "identity" else 1)


def test_expired_preview_blocks_before_source_restore_or_write() -> None:
    harness = _harness(market_valid_until=AS_OF + timedelta(seconds=1))
    preview = harness.use_case.preview(_request(), fee_budget=Decimal("20.00"))
    assert harness.repository.write_calls == 0

    harness.clock.value = AS_OF + timedelta(seconds=2)
    with pytest.raises(SimulatedTradeExecutionBlocked):
        harness.use_case.confirm(account_id=7, user_id=11, token=preview.token, confirmed=True)

    assert harness.market_factory.restore_calls == []
    assert harness.writer_factory.writers == []
    assert harness.repository.write_calls == 0
    assert harness.repository.stored is None


@pytest.mark.parametrize("changed", ("identity", "settlement_bundle", "fee_policy"))
def test_confirm_rejects_changed_configuration_before_source_restore_or_write(changed: str) -> None:
    harness = _harness()
    preview = harness.use_case.preview(_request(), fee_budget=Decimal("20.00"))
    if changed == "identity":
        harness.identity_reader.identity = replace(
            harness.identity_reader.identity,
            selection=replace(
                harness.identity_reader.identity.selection,
                profile_version=harness.identity_reader.identity.selection.profile_version + 1,
            ),
        )
    elif changed == "settlement_bundle":
        original = harness.rule_reader.bundle
        updated_policy = replace(
            original.settlement_policy_v1,
            source_version=original.settlement_policy_v1.source_version + "-changed",
            content_hash="",
        )
        harness.rule_reader.bundle = replace(
            original,
            settlement_policy_v1=updated_policy,
            content_hash="",
        )
    else:
        harness.fee_reader.policy = replace(
            harness.fee_reader.policy,
            policy_version=harness.fee_reader.policy.policy_version + 1,
            content_hash="",
        )

    harness.clock.value = AS_OF + timedelta(seconds=2)
    with pytest.raises(SimulatedTradeExecutionBlocked):
        harness.use_case.confirm(account_id=7, user_id=11, token=preview.token, confirmed=True)

    assert harness.market_factory.restore_calls == []
    assert harness.writer_factory.build_calls == []
    assert harness.repository.write_calls == 0


def test_unknown_commit_outcome_is_not_returned_as_a_success() -> None:
    harness = _harness()
    preview = harness.use_case.preview(_request(), fee_budget=Decimal("20.00"))
    harness.clock.value = AS_OF + timedelta(seconds=2)
    harness.writer_factory.unknown_after_commit = True

    with pytest.raises(SimulatedTradeExecutionResultUnknown) as raised:
        harness.use_case.confirm(account_id=7, user_id=11, token=preview.token, confirmed=True)

    assert raised.value.effects_indeterminate is True
    assert harness.repository.write_calls == 1
    assert harness.repository.stored is not None

    # Only the subsequent authoritative idempotency lookup may resolve that uncertain write.
    replay = harness.use_case.confirm(
        account_id=7,
        user_id=11,
        token=preview.token,
        confirmed=True,
    )
    assert replay.order_id == 801
    assert replay.result.replayed is True
    assert harness.repository.write_calls == 1
    assert harness.writer_factory.writers[0].reserve_calls == 1


def test_changed_derived_calendar_market_is_rejected_under_writer_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness()
    preview = harness.use_case.preview(_request(), fee_budget=Decimal("20.00"))
    retained = harness.market_factory.retained
    assert retained is not None
    original_read = retained.read_market
    before = harness.repository.book

    def changed_read(
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        as_of: datetime,
    ) -> LocalOrderSubmissionMarket:
        selected = original_read(plan=plan, execution_bundle=execution_bundle, as_of=as_of)
        evidence = replace(
            selected.market.market_evidence_v1,
            market_source_hash="e" * 64,
            calendar_source_hash="f" * 64,
            content_hash="",
        )
        return LocalOrderSubmissionMarket(
            replace(selected.market, market_evidence_v1=evidence, content_hash=""),
            selected.provenance,
        )

    monkeypatch.setattr(retained, "read_market", changed_read)
    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.use_case.confirm(account_id=7, user_id=11, token=preview.token, confirmed=True)
    assert error.value.code == "SIMULATED_ORDER_PREVIEW_CHANGED"
    assert harness.repository.book == before
    assert harness.repository.stored is None
    assert harness.repository.write_calls == 0


def test_original_preview_deadline_is_signed_and_cannot_be_extended_by_fresh_reads() -> None:
    harness = _harness()
    preview = harness.use_case.preview(_request(), fee_budget=Decimal("20.00"))
    harness.clock.value = preview.expires_at
    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.use_case.confirm(account_id=7, user_id=11, token=preview.token, confirmed=True)
    assert error.value.code == "SIMULATED_ORDER_PREVIEW_EXPIRED"
    assert harness.writer_factory.build_calls == []
    assert harness.repository.stored is None
    assert harness.repository.write_calls == 0


def test_preview_deadline_is_rechecked_after_writer_lock_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness()
    preview = harness.use_case.preview(_request(), fee_budget=Decimal("20.00"))
    original_reserve = _GuardedWriter.reserve_order

    def delayed_reserve(
        self: _GuardedWriter,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        fee_budget: Decimal | None,
        clock: _MutableClock,
    ) -> OrderReservationResult:
        clock.value = preview.expires_at
        return original_reserve(
            self, plan=plan, execution_bundle=execution_bundle, fee_budget=fee_budget, clock=clock
        )

    monkeypatch.setattr(_GuardedWriter, "reserve_order", delayed_reserve)
    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.use_case.confirm(account_id=7, user_id=11, token=preview.token, confirmed=True)
    assert error.value.code == "SIMULATED_ORDER_PREVIEW_EXPIRED"
    assert len(harness.writer_factory.build_calls) == 1
    assert harness.repository.stored is None
    assert harness.repository.write_calls == 0


def test_idempotent_confirm_and_recovery_reject_a_different_stored_market_purpose() -> None:
    """A signed preview cannot relabel an existing reservation during replay."""

    harness = _harness()
    preview = harness.use_case.preview(_request(), fee_budget=Decimal("20.00"))
    harness.use_case.confirm(account_id=7, user_id=11, token=preview.token, confirmed=True)
    assert harness.repository.stored is not None
    harness.repository.stored = replace(
        harness.repository.stored,
        market_purpose="close_snapshot_simulation",
    )

    with pytest.raises(SimulatedTradeIdempotencyConflict):
        harness.use_case.confirm(
            account_id=7,
            user_id=11,
            token=preview.token,
            confirmed=True,
        )
    with pytest.raises(SimulatedTradeIdempotencyConflict):
        harness.use_case.recover(account_id=7, user_id=11, token=preview.token)

    assert harness.repository.write_calls == 1
