"""Require explicit market checks for public simulated-order commitments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Protocol

from apps.risk_center.application.close_snapshot_simulation import CloseSnapshotSimulationUseCase
from apps.risk_center.application.execution_submission_v2 import (
    EvaluateExecutionSubmissionV2UseCase,
)
from apps.risk_center.domain.close_snapshot_simulation import (
    CloseSnapshotSimulationBundle,
    CloseSnapshotSimulationMarket,
    CloseSnapshotSimulationStatus,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionMarketV2,
    ExecutionSubmissionRuleV2,
)
from apps.risk_center.domain.execution_trading_constraints import (
    ExecutionDecisionStatus,
    ExecutionOrder,
    ExecutionSide,
    SellPositionCompleteness,
    SellPositionEvidence,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    _require_aware_clock,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
    SettlementExecutionPlanV3,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_identity import SettlementExecutionPlanV2
from apps.simulated_trading.domain.execution_settlement_primitives import _hash_payload
from apps.simulated_trading.domain.order_reservation import OrderReservation, OrderReservationBook

LOCAL_ORDER_MARKET_PURPOSE = "local_simulation_only"
CLOSE_ORDER_MARKET_PURPOSE = "close_snapshot_simulation"
SUPPORTED_ORDER_MARKET_PURPOSES = frozenset(
    {LOCAL_ORDER_MARKET_PURPOSE, CLOSE_ORDER_MARKET_PURPOSE}
)


@dataclass(frozen=True, slots=True)
class LocalOrderSubmissionMarket:
    """A retained paper-market snapshot with its explicitly limited provenance."""

    market: ExecutionSubmissionMarketV2 | CloseSnapshotSimulationMarket
    provenance: dict[str, object]
    close_bundle: CloseSnapshotSimulationBundle | None = None


def _close_submission_receipt(
    *,
    selected: LocalOrderSubmissionMarket,
    plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
    execution_bundle: ExecutionSettlementBundleV3,
    position: SellPositionEvidence | None,
    as_of: datetime,
) -> dict[str, object]:
    """Apply explicit close-only source and ordinary execution terms without OPEN claims."""
    bundle = selected.close_bundle
    market = selected.market
    if (
        type(bundle) is not CloseSnapshotSimulationBundle
        or type(market) is not CloseSnapshotSimulationMarket
        or bundle.market != market
        or selected.provenance.get("purpose") != CLOSE_ORDER_MARKET_PURPOSE
    ):
        raise SimulatedTradeExecutionBlocked("收盘快照的原件绑定不完整")
    intent = plan.intent
    decision = CloseSnapshotSimulationUseCase().evaluate_order(
        rule=execution_bundle.execution_submission_v2,
        bundle=bundle,
        order=ExecutionOrder(
            order_id=intent.idempotency_key,
            account_id=intent.account_id,
            security_id=intent.security_id,
            side=ExecutionSide.BUY if intent.side.value == "buy" else ExecutionSide.SELL,
            quantity=intent.quantity,
            limit_price=intent.price,
            sell_position_evidence=position,
        ),
        as_of=as_of,
    )
    if decision.status is not CloseSnapshotSimulationStatus.QUALIFIED:
        raise SimulatedTradeExecutionBlocked(
            "收盘快照、价格或可卖量不允许此次模拟预留",
            code="SIMULATED_ORDER_MARKET_BLOCKED",
        )
    identity = plan.identity_evidence
    identity_source = (
        identity.source_evidence
        if isinstance(identity, ExecutionInstrumentIdentityEvidenceV2)
        else identity
    )
    fee_policy = plan.fee_policy_v2
    if type(fee_policy) is not SimulatedFeePolicyV2:
        raise SimulatedTradeExecutionBlocked("缺少完整模拟费用政策")
    source = market.market_evidence_v1
    return {
        "purpose": CLOSE_ORDER_MARKET_PURPOSE,
        "account_id": intent.account_id,
        "user_id": intent.user_id,
        "intent_hash": intent.request_payload_hash,
        "evaluated_at": as_of.isoformat(),
        "market": market.to_payload(),
        "market_source_hash": source.market_source_hash,
        "decision": decision.to_payload(),
        "position": position.to_payload() if position is not None else None,
        "position_time_semantics": "historical_locked_local_ledger_observation_only",
        "execution_authority": False,
        "qualification": {
            "decision_scope": CLOSE_ORDER_MARKET_PURPOSE,
            "qualified_at": as_of.isoformat(),
            "freshness": "close_snapshot",
            "reliability": "vendor_reported_close_snapshot",
            "must_not_use_for_decision": True,
            "must_not_execute": True,
            "local_simulation_qualified": True,
            "blocking_reasons": [],
            "market_available_at_basis": "local_response_completed_at_not_vendor_published_at",
        },
        "valid_until": min(
            source.market_valid_until,
            source.calendar_valid_until,
            execution_bundle.valid_until,
            fee_policy.valid_until,
            identity_source.identity_valid_until,
        ).isoformat(),
        "provenance": selected.provenance,
    }


@dataclass(frozen=True, slots=True)
class OrderSubmissionAccountState:
    """A read-only account projection including provable due settlement releases."""

    book: OrderReservationBook
    total_quantity: Decimal | None
    read_at: datetime


@dataclass(frozen=True, slots=True)
class OwnerOrderStoredReadback:
    """An original durable order read without re-evaluating its market or balances."""

    order_id: int
    reservation: OrderReservation
    market_purpose: str = "local_simulation_only"


class LocalOrderSubmissionMarketReader(Protocol):
    """Build market evidence for one exact prepared order, without network I/O."""

    def read_market(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        as_of: datetime,
    ) -> LocalOrderSubmissionMarket:
        """Recheck retained source clocks, current policy and exact calendar/rule bindings."""


class SimulatedOrderSubmissionGuard(Protocol):
    """Validate retained market evidence against the actual locked account state."""

    @property
    def market_purpose(self) -> str:
        """Expose the server-signed purpose required by the locked market guard."""
        ...

    def validate_locked_submission(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        book: OrderReservationBook,
        total_quantity: Decimal | None,
        as_of: datetime,
    ) -> dict[str, object]:
        """Return sealed local-purpose evidence or raise before any committed effect."""


class _ExactSubmissionReaders:
    """Supply the Risk application with the already bound rule and locked balances."""

    def __init__(
        self,
        *,
        rule: ExecutionSubmissionRuleV2,
        market: ExecutionSubmissionMarketV2,
        position: SellPositionEvidence | None,
    ) -> None:
        """Bind the already-qualified market and actual locked position to one check."""
        self._rule = rule
        self._market = market
        self._position = position

    def get_submission_rule(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionRuleV2:
        """Return the exact settlement bundle's submission rule."""
        return self._rule

    def get_submission_market(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionMarketV2:
        """Return the retained and requalified market snapshot."""
        return self._market

    def get_sell_position(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> SellPositionEvidence | None:
        """Return only the account state observed under the shared ledger lock."""
        return self._position


class LocalSimulatedOrderSubmissionGuard:
    """Apply the ordinary Risk checks to an explicitly local simulated order."""

    def __init__(
        self,
        *,
        market_reader: LocalOrderSubmissionMarketReader,
        market_purpose: str,
        expected_market_source_hash: str | None = None,
        confirmation_expires_at: datetime | None = None,
    ) -> None:
        """Inject a retained-source reader; the guard never fetches network data."""
        self._markets = market_reader
        if type(market_purpose) is not str or market_purpose not in SUPPORTED_ORDER_MARKET_PURPOSES:
            raise SimulatedTradeExecutionBlocked(
                "订单行情用途无效", code="SIMULATED_ORDER_MARKET_PURPOSE_INVALID"
            )
        self._market_purpose = market_purpose
        if (expected_market_source_hash is None) != (confirmation_expires_at is None):
            raise SimulatedTradeExecutionBlocked("原预览的行情绑定和截止时间必须完整")
        self._expected_market_source_hash = expected_market_source_hash
        self._confirmation_expires_at = (
            _require_aware_clock(confirmation_expires_at)
            if confirmation_expires_at is not None
            else None
        )

    @property
    def market_purpose(self) -> str:
        """Return the purpose copied from the signed preview, never from client input."""
        return self._market_purpose

    def validate_locked_submission(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        book: OrderReservationBook,
        total_quantity: Decimal | None,
        as_of: datetime,
    ) -> dict[str, object]:
        """Evaluate exact market terms against fresh, locked local account balances.

        The balance observation is a current physical read of the local ledger,
        not a broker snapshot or a rewritten historical trade/source clock.
        Its validity cannot exceed the retained market's own validity window.
        """
        intent = plan.intent
        if self._confirmation_expires_at is not None and as_of >= self._confirmation_expires_at:
            raise SimulatedTradeExecutionBlocked(
                "原预览已过确认截止，请重新预览", code="SIMULATED_ORDER_PREVIEW_EXPIRED"
            )
        fee_policy = plan.fee_policy_v2
        if type(fee_policy) is not SimulatedFeePolicyV2:
            raise SimulatedTradeExecutionBlocked("模拟订单必须使用完整的 V2 费用政策")
        fee_policy.validate_at(as_of)
        identity = plan.identity_evidence
        identity_source = (
            identity.source_evidence
            if isinstance(identity, ExecutionInstrumentIdentityEvidenceV2)
            else identity
        )
        book.__post_init__()
        if (book.account_id, book.security_id) != (intent.account_id, intent.security_id):
            raise SimulatedTradeExecutionBlocked("订单余额快照与账户或证券不一致")
        selected = self._markets.read_market(
            plan=plan, execution_bundle=execution_bundle, as_of=as_of
        )
        if type(selected) is not LocalOrderSubmissionMarket:
            raise SimulatedTradeExecutionBlocked("模拟行情返回了不可验证的合同")
        market = selected.market
        market.__post_init__()
        source = market.market_evidence_v1
        if (
            self._expected_market_source_hash is not None
            and source.market_source_hash != self._expected_market_source_hash
        ):
            raise SimulatedTradeExecutionBlocked(
                "原预览的日历或行情条件已变化，请重新预览",
                code="SIMULATED_ORDER_PREVIEW_CHANGED",
            )
        if not source.market_available_at <= as_of < source.market_valid_until:
            raise SimulatedTradeExecutionBlocked("模拟报价已过期或尚不可用")
        available = book.available_shares
        position: SellPositionEvidence | None = None
        if intent.side.value == "sell":
            if (
                total_quantity is None
                or available is None
                or not Decimal(0) <= available <= total_quantity
            ):
                raise SimulatedTradeExecutionBlocked("可卖量未知或预留余额不一致")
            balance_payload: dict[str, object] = {
                "account_id": intent.account_id,
                "security_id": intent.security_id,
                "total_quantity": str(total_quantity),
                "settled_quantity": str(book.sellable_shares),
                "held_quantity": str(book.active_held_shares),
                "free_quantity": str(available),
                "observed_at": as_of.isoformat(),
            }
            with localcontext() as context:
                context.prec = 80
                restricted = total_quantity - available
            position = SellPositionEvidence(
                security_id=intent.security_id,
                account_id=intent.account_id,
                available_to_sell_quantity=available,
                restricted_quantity=restricted,
                completeness=SellPositionCompleteness.COMPLETE,
                source_id="local.locked_simulated_ledger",
                source_version="current_physical_read",
                source_hash=_hash_payload(balance_payload),
                observed_at=as_of,
                available_at=as_of,
                valid_until=market.market_evidence_v1.market_valid_until,
            )
        if isinstance(market, CloseSnapshotSimulationMarket):
            close_receipt = _close_submission_receipt(
                selected=selected,
                plan=plan,
                execution_bundle=execution_bundle,
                position=position,
                as_of=as_of,
            )
            if close_receipt["purpose"] != self._market_purpose:
                raise SimulatedTradeExecutionBlocked(
                    "锁内行情用途与已签预览不一致",
                    code="SIMULATED_ORDER_MARKET_PURPOSE_MISMATCH",
                )
            return close_receipt
        readers = _ExactSubmissionReaders(
            rule=execution_bundle.execution_submission_v2, market=market, position=position
        )
        evaluation = EvaluateExecutionSubmissionV2UseCase(
            rule_provider=readers, market_provider=readers, position_provider=readers
        ).execute(
            order=ExecutionOrder(
                order_id=intent.idempotency_key,
                account_id=intent.account_id,
                security_id=intent.security_id,
                side=(ExecutionSide.BUY if intent.side.value == "buy" else ExecutionSide.SELL),
                quantity=intent.quantity,
                limit_price=intent.price,
                sell_position_evidence=None,
            ),
            as_of=as_of,
        )
        if evaluation.decision.status is not ExecutionDecisionStatus.ALLOWED:
            raise SimulatedTradeExecutionBlocked(
                "当前行情、时段、价格或可卖量不允许预留",
                code="SIMULATED_ORDER_MARKET_BLOCKED",
            )
        local_receipt: dict[str, object] = {
            "purpose": LOCAL_ORDER_MARKET_PURPOSE,
            "account_id": intent.account_id,
            "user_id": intent.user_id,
            "intent_hash": intent.request_payload_hash,
            "evaluated_at": as_of.isoformat(),
            "market": evaluation.market_evidence.to_payload(),
            "market_source_hash": source.market_source_hash,
            "decision": evaluation.decision.to_payload(),
            "position": position.to_payload() if position is not None else None,
            "position_time_semantics": "historical_locked_local_ledger_observation_only",
            "execution_authority": False,
            "qualification": {
                "decision_scope": LOCAL_ORDER_MARKET_PURPOSE,
                "qualified_at": as_of.isoformat(),
                "freshness": "fresh",
                "reliability": "vendor_reported_with_explicit_simulation_policy",
                "must_not_use_for_decision": False,
                "blocking_reasons": [],
                "market_available_at_basis": "local_response_completed_at_not_vendor_published_at",
            },
            "valid_until": min(
                source.market_valid_until,
                source.calendar_valid_until,
                source.session_close_at,
                execution_bundle.valid_until,
                fee_policy.valid_until,
                identity_source.identity_valid_until,
            ).isoformat(),
            "provenance": selected.provenance,
        }
        if local_receipt["purpose"] != self._market_purpose:
            raise SimulatedTradeExecutionBlocked(
                "锁内行情用途与已签预览不一致",
                code="SIMULATED_ORDER_MARKET_PURPOSE_MISMATCH",
            )
        return local_receipt
