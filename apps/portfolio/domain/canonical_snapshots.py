"""Immutable Portfolio-owned snapshots and reconciled execution feedback."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum


class SnapshotEvidenceKind(str, Enum):
    """Required source-evidence dimensions for a canonical snapshot."""

    CASH = "cash"
    POSITIONS = "positions"


GOVERNED_SNAPSHOT_EVIDENCE_OWNERS = {
    SnapshotEvidenceKind.CASH: "account",
    SnapshotEvidenceKind.POSITIONS: "portfolio",
}


@dataclass(frozen=True)
class SnapshotSourceEvidence:
    """Versioned source observation used to construct a snapshot dimension."""

    kind: SnapshotEvidenceKind
    owner: str
    evidence_ref: str
    version: str
    observed_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        """Reject evidence that cannot be independently audited."""

        _require_values(
            owner=self.owner,
            evidence_ref=self.evidence_ref,
            version=self.version,
            content_hash=self.content_hash,
        )
        _require_aware(self.observed_at, "observed_at")
        _require_sha256(self.content_hash, "content_hash")
        if self.owner != GOVERNED_SNAPSHOT_EVIDENCE_OWNERS[self.kind]:
            raise ValueError(f"{self.kind.value} evidence owner is not governed")


@dataclass(frozen=True)
class CanonicalPosition:
    """One position and its unmodified ledger and valuation observation times."""

    asset_code: str
    quantity: Decimal
    available_quantity: Decimal
    market_value_base: Decimal
    position_source_ref: str
    position_observed_at: datetime
    valuation_source_ref: str
    valuation_observed_at: datetime

    def __post_init__(self) -> None:
        """Validate a canonical position without inventing missing prices or units."""

        _require_values(
            asset_code=self.asset_code,
            position_source_ref=self.position_source_ref,
            valuation_source_ref=self.valuation_source_ref,
        )
        _require_aware(self.position_observed_at, "position_observed_at")
        _require_aware(self.valuation_observed_at, "valuation_observed_at")
        _require_finite_decimals(
            quantity=self.quantity,
            available_quantity=self.available_quantity,
            market_value_base=self.market_value_base,
        )
        if self.quantity < 0 or self.available_quantity < 0:
            raise ValueError("canonical position quantities cannot be negative")
        if self.available_quantity > self.quantity:
            raise ValueError("available quantity cannot exceed total quantity")
        if self.market_value_base < 0:
            raise ValueError("canonical position market value cannot be negative")


@dataclass(frozen=True)
class CanonicalCashProjection:
    """Immutable Account-owned cash payload with a canonical digest."""

    account_ref: str
    base_currency: str
    cash_balance: Decimal
    evidence_ref: str
    version: str
    observed_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        """Recompute the exact cash payload digest and reject arbitrary hashes."""

        _require_values(
            account_ref=self.account_ref,
            base_currency=self.base_currency,
            evidence_ref=self.evidence_ref,
            version=self.version,
        )
        _require_aware(self.observed_at, "cash observed_at")
        _require_finite_decimals(cash_balance=self.cash_balance)
        if self.cash_balance < 0:
            raise ValueError("canonical cash cannot be negative")
        _require_sha256(self.content_hash, "cash content_hash")
        if self.content_hash != canonical_cash_projection_hash(
            account_ref=self.account_ref,
            base_currency=self.base_currency,
            cash_balance=self.cash_balance,
            evidence_ref=self.evidence_ref,
            version=self.version,
            observed_at=self.observed_at,
        ):
            raise ValueError("canonical cash projection content hash mismatch")


@dataclass(frozen=True)
class CanonicalPositionsProjection:
    """Immutable Portfolio-owned positions payload with a canonical digest."""

    account_ref: str
    evidence_ref: str
    version: str
    observed_at: datetime
    positions: tuple[CanonicalPosition, ...]
    content_hash: str

    def __post_init__(self) -> None:
        """Recompute exact position rows, version, and source observation time."""

        _require_values(
            account_ref=self.account_ref,
            evidence_ref=self.evidence_ref,
            version=self.version,
        )
        _require_aware(self.observed_at, "positions observed_at")
        codes = tuple(item.asset_code for item in self.positions)
        if len(codes) != len(set(codes)) or codes != tuple(sorted(codes)):
            raise ValueError("canonical positions projection must be unique and ordered")
        if any(item.position_observed_at > self.observed_at for item in self.positions):
            raise ValueError("position observation is newer than positions projection")
        _require_sha256(self.content_hash, "positions content_hash")
        if self.content_hash != canonical_positions_projection_hash(
            account_ref=self.account_ref,
            evidence_ref=self.evidence_ref,
            version=self.version,
            observed_at=self.observed_at,
            positions=self.positions,
        ):
            raise ValueError("canonical positions projection content hash mismatch")


@dataclass(frozen=True)
class CanonicalPortfolioSnapshot:
    """Append-only Portfolio truth bound to exact cash and position versions."""

    snapshot_id: str
    account_ref: str
    as_of: datetime
    base_currency: str
    cash_balance: Decimal
    cash_version: str
    positions_version: str
    positions: tuple[CanonicalPosition, ...]
    source_evidence: tuple[SnapshotSourceEvidence, ...]
    content_hash: str

    def __post_init__(self) -> None:
        """Verify identity, source completeness, timestamps, and content integrity."""

        _require_values(
            snapshot_id=self.snapshot_id,
            account_ref=self.account_ref,
            base_currency=self.base_currency,
            cash_version=self.cash_version,
            positions_version=self.positions_version,
            content_hash=self.content_hash,
        )
        _require_aware(self.as_of, "as_of")
        _require_sha256(self.content_hash, "content_hash")
        _require_finite_decimals(cash_balance=self.cash_balance)
        if self.cash_balance < 0:
            raise ValueError("canonical portfolio cash cannot be negative")
        codes = [position.asset_code for position in self.positions]
        if len(codes) != len(set(codes)):
            raise ValueError("canonical snapshot contains duplicate asset codes")
        by_kind = {item.kind: item for item in self.source_evidence}
        if len(by_kind) != len(self.source_evidence):
            raise ValueError("canonical snapshot contains duplicate evidence kinds")
        if set(by_kind) != {SnapshotEvidenceKind.CASH, SnapshotEvidenceKind.POSITIONS}:
            raise ValueError("canonical snapshot requires cash and positions evidence")
        if by_kind[SnapshotEvidenceKind.CASH].version != self.cash_version:
            raise ValueError("cash version does not match its source evidence")
        if by_kind[SnapshotEvidenceKind.POSITIONS].version != self.positions_version:
            raise ValueError("positions version does not match its source evidence")
        cash_evidence = by_kind[SnapshotEvidenceKind.CASH]
        positions_evidence = by_kind[SnapshotEvidenceKind.POSITIONS]
        expected_cash_hash = canonical_cash_projection_hash(
            account_ref=self.account_ref,
            base_currency=self.base_currency,
            cash_balance=self.cash_balance,
            evidence_ref=cash_evidence.evidence_ref,
            version=cash_evidence.version,
            observed_at=cash_evidence.observed_at,
        )
        expected_positions_hash = canonical_positions_projection_hash(
            account_ref=self.account_ref,
            evidence_ref=positions_evidence.evidence_ref,
            version=positions_evidence.version,
            observed_at=positions_evidence.observed_at,
            positions=self.positions,
        )
        if cash_evidence.content_hash != expected_cash_hash:
            raise ValueError("cash evidence does not bind the canonical cash payload")
        if positions_evidence.content_hash != expected_positions_hash:
            raise ValueError("positions evidence does not bind the canonical positions payload")
        latest_source_time = max(item.observed_at for item in self.source_evidence)
        if self.as_of != latest_source_time:
            raise ValueError("snapshot as_of must preserve the latest source observation time")
        positions_observed_at = by_kind[SnapshotEvidenceKind.POSITIONS].observed_at
        for position in self.positions:
            if position.position_observed_at > positions_observed_at:
                raise ValueError("position observation is newer than positions evidence")
            if position.valuation_observed_at > self.as_of:
                raise ValueError("valuation observation is newer than snapshot as_of")
        expected_hash = canonical_snapshot_content_hash(
            account_ref=self.account_ref,
            as_of=self.as_of,
            base_currency=self.base_currency,
            cash_balance=self.cash_balance,
            cash_version=self.cash_version,
            positions_version=self.positions_version,
            positions=self.positions,
            source_evidence=self.source_evidence,
        )
        if self.content_hash != expected_hash:
            raise ValueError("canonical snapshot content hash mismatch")
        if self.snapshot_id != f"portfolio_snapshot:{expected_hash[:24]}":
            raise ValueError("canonical snapshot id does not match its content hash")


@dataclass(frozen=True)
class BrokerOrderEventEvidence:
    """Stable broker order-event reference with its original event time."""

    event_ref: str
    event_type: str
    status: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        """Reject events without a stable identity or source time."""

        _require_values(
            event_ref=self.event_ref,
            event_type=self.event_type,
            status=self.status,
        )
        _require_aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True)
class BrokerFillEvidence:
    """Stable immutable fill evidence supplied by Broker Execution."""

    fill_ref: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    occurred_at: datetime

    def __post_init__(self) -> None:
        """Validate one broker fill without changing its source timestamp."""

        _require_values(fill_ref=self.fill_ref)
        _require_aware(self.occurred_at, "occurred_at")
        _require_finite_decimals(quantity=self.quantity, price=self.price, fee=self.fee)
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("broker fill quantity and price must be positive")
        if self.fee < 0:
            raise ValueError("broker fill fee cannot be negative")


@dataclass(frozen=True)
class BrokerExecutionEvidence:
    """Broker-owned evidence projection consumed across an Application boundary."""

    client_order_ref: str
    broker_order_ref: str
    order_events: tuple[BrokerOrderEventEvidence, ...]
    fills: tuple[BrokerFillEvidence, ...]
    reconciliation_ref: str
    reconciliation_observed_at: datetime
    source_evidence_hash: str
    rejected: bool = False
    rejection_code: str = ""
    rejection_reason: str = ""

    def __post_init__(self) -> None:
        """Require broker and reconciliation evidence before feedback can be recorded."""

        _require_values(
            client_order_ref=self.client_order_ref,
            reconciliation_ref=self.reconciliation_ref,
            source_evidence_hash=self.source_evidence_hash,
        )
        _require_aware(self.reconciliation_observed_at, "reconciliation_observed_at")
        _require_sha256(self.source_evidence_hash, "source_evidence_hash")
        if not self.order_events:
            raise ValueError("broker order-event evidence is required")
        event_refs = [item.event_ref for item in self.order_events]
        fill_refs = [item.fill_ref for item in self.fills]
        if len(event_refs) != len(set(event_refs)):
            raise ValueError("duplicate broker order-event evidence")
        if len(fill_refs) != len(set(fill_refs)):
            raise ValueError("duplicate broker fill evidence")
        source_times = [item.occurred_at for item in self.order_events]
        source_times.extend(item.occurred_at for item in self.fills)
        if self.reconciliation_observed_at < max(source_times):
            raise ValueError("reconciliation cannot predate broker execution evidence")
        if self.rejected:
            if self.fills:
                raise ValueError("a rejected broker order cannot contain fills")
            if not self.rejection_code.strip() or not self.rejection_reason.strip():
                raise ValueError("rejected broker evidence requires code and reason")
        else:
            if not self.broker_order_ref.strip():
                raise ValueError("accepted broker evidence requires broker_order_ref")
            if self.rejection_code or self.rejection_reason:
                raise ValueError("accepted broker evidence cannot contain rejection details")
        expected_hash = broker_execution_evidence_hash(
            client_order_ref=self.client_order_ref,
            broker_order_ref=self.broker_order_ref,
            order_events=self.order_events,
            fills=self.fills,
            reconciliation_ref=self.reconciliation_ref,
            reconciliation_observed_at=self.reconciliation_observed_at,
            rejected=self.rejected,
            rejection_code=self.rejection_code,
            rejection_reason=self.rejection_reason,
        )
        if self.source_evidence_hash != expected_hash:
            raise ValueError("broker source evidence hash mismatch")


@dataclass(frozen=True)
class ConstraintExecutionDeviation:
    """Observed difference from one versioned planning constraint."""

    rule_code: str
    expected_value: str
    actual_value: str
    reason: str

    def __post_init__(self) -> None:
        """Require auditable expected and actual constraint values."""

        _require_values(
            rule_code=self.rule_code,
            expected_value=self.expected_value,
            actual_value=self.actual_value,
            reason=self.reason,
        )


@dataclass(frozen=True)
class _ExecutionFeedbackMetrics:
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    actual_fee: Decimal
    fee_variance: Decimal
    realized_slippage: Decimal
    fill_rate: Decimal
    constraint_deviations: tuple[ConstraintExecutionDeviation, ...]


@dataclass(frozen=True)
class PortfolioExecutionFeedback:
    """Append-only plan-versus-broker execution feedback owned by Portfolio."""

    feedback_id: str
    portfolio_snapshot_ref: str
    transition_plan_ref: str
    order_intent_ref: str
    planning_policy_version: str
    asset_code: str
    side: str
    planned_quantity: Decimal
    planned_reference_price: Decimal
    planned_estimated_fee: Decimal
    client_order_ref: str
    broker_order_ref: str
    order_events: tuple[BrokerOrderEventEvidence, ...]
    fills: tuple[BrokerFillEvidence, ...]
    reconciliation_ref: str
    reconciliation_observed_at: datetime
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    actual_fee: Decimal
    fee_variance: Decimal
    realized_slippage: Decimal
    fill_rate: Decimal
    rejected: bool
    rejection_code: str
    rejection_reason: str
    constraint_deviations: tuple[ConstraintExecutionDeviation, ...]
    source_evidence_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        """Verify the persisted metrics against immutable broker evidence."""

        _require_values(
            feedback_id=self.feedback_id,
            portfolio_snapshot_ref=self.portfolio_snapshot_ref,
            transition_plan_ref=self.transition_plan_ref,
            order_intent_ref=self.order_intent_ref,
            planning_policy_version=self.planning_policy_version,
            asset_code=self.asset_code,
            side=self.side,
            client_order_ref=self.client_order_ref,
            reconciliation_ref=self.reconciliation_ref,
            source_evidence_hash=self.source_evidence_hash,
            content_hash=self.content_hash,
        )
        _require_sha256(self.source_evidence_hash, "source_evidence_hash")
        _require_sha256(self.content_hash, "content_hash")
        metrics: dict[str, Decimal] = {
            "planned_quantity": self.planned_quantity,
            "planned_reference_price": self.planned_reference_price,
            "planned_estimated_fee": self.planned_estimated_fee,
            "filled_quantity": self.filled_quantity,
            "actual_fee": self.actual_fee,
            "fee_variance": self.fee_variance,
            "realized_slippage": self.realized_slippage,
            "fill_rate": self.fill_rate,
        }
        if self.average_fill_price is not None:
            metrics["average_fill_price"] = self.average_fill_price
        _require_finite_decimals(**metrics)
        if self.side not in {"buy", "sell"}:
            raise ValueError("execution feedback side must be buy or sell")
        if self.planned_quantity <= 0 or self.planned_reference_price <= 0:
            raise ValueError("planned quantity and reference price must be positive")
        if self.planned_estimated_fee < 0:
            raise ValueError("planned estimated fee cannot be negative")
        evidence = BrokerExecutionEvidence(
            client_order_ref=self.client_order_ref,
            broker_order_ref=self.broker_order_ref,
            order_events=self.order_events,
            fills=self.fills,
            reconciliation_ref=self.reconciliation_ref,
            reconciliation_observed_at=self.reconciliation_observed_at,
            source_evidence_hash=self.source_evidence_hash,
            rejected=self.rejected,
            rejection_code=self.rejection_code,
            rejection_reason=self.rejection_reason,
        )
        expected = _calculate_execution_feedback_metrics(
            side=self.side,
            planned_quantity=self.planned_quantity,
            planned_reference_price=self.planned_reference_price,
            planned_estimated_fee=self.planned_estimated_fee,
            broker_evidence=evidence,
            constraint_deviations=self.constraint_deviations,
        )
        for field_name in (
            "filled_quantity",
            "average_fill_price",
            "actual_fee",
            "fee_variance",
            "realized_slippage",
            "fill_rate",
            "constraint_deviations",
        ):
            if getattr(self, field_name) != getattr(expected, field_name):
                raise ValueError(f"execution feedback {field_name} mismatch")
        payload = _execution_feedback_payload(
            portfolio_snapshot_ref=self.portfolio_snapshot_ref,
            transition_plan_ref=self.transition_plan_ref,
            order_intent_ref=self.order_intent_ref,
            planning_policy_version=self.planning_policy_version,
            asset_code=self.asset_code,
            side=self.side,
            planned_quantity=self.planned_quantity,
            planned_reference_price=self.planned_reference_price,
            planned_estimated_fee=self.planned_estimated_fee,
            broker_evidence=evidence,
            filled_quantity=expected.filled_quantity,
            average_fill_price=expected.average_fill_price,
            actual_fee=expected.actual_fee,
            fee_variance=expected.fee_variance,
            realized_slippage=expected.realized_slippage,
            fill_rate=expected.fill_rate,
            constraint_deviations=expected.constraint_deviations,
        )
        expected_hash = _sha256(payload)
        if self.content_hash != expected_hash:
            raise ValueError("execution feedback content_hash mismatch")
        if self.feedback_id != f"portfolio_execution_feedback:{expected_hash[:24]}":
            raise ValueError("execution feedback feedback_id mismatch")


def build_canonical_cash_projection(
    *,
    account_ref: str,
    base_currency: str,
    cash_balance: Decimal,
    evidence_ref: str,
    version: str,
    observed_at: datetime,
) -> CanonicalCashProjection:
    """Build a verified Account-owned cash projection."""

    return CanonicalCashProjection(
        account_ref=account_ref,
        base_currency=base_currency,
        cash_balance=cash_balance,
        evidence_ref=evidence_ref,
        version=version,
        observed_at=observed_at,
        content_hash=canonical_cash_projection_hash(
            account_ref=account_ref,
            base_currency=base_currency,
            cash_balance=cash_balance,
            evidence_ref=evidence_ref,
            version=version,
            observed_at=observed_at,
        ),
    )


def build_canonical_positions_projection(
    *,
    account_ref: str,
    evidence_ref: str,
    version: str,
    observed_at: datetime,
    positions: tuple[CanonicalPosition, ...],
) -> CanonicalPositionsProjection:
    """Build a verified Portfolio-owned positions projection."""

    ordered_positions = tuple(sorted(positions, key=lambda item: item.asset_code))
    return CanonicalPositionsProjection(
        account_ref=account_ref,
        evidence_ref=evidence_ref,
        version=version,
        observed_at=observed_at,
        positions=ordered_positions,
        content_hash=canonical_positions_projection_hash(
            account_ref=account_ref,
            evidence_ref=evidence_ref,
            version=version,
            observed_at=observed_at,
            positions=ordered_positions,
        ),
    )


def build_canonical_portfolio_snapshot(
    *,
    cash_projection: CanonicalCashProjection,
    positions_projection: CanonicalPositionsProjection,
) -> CanonicalPortfolioSnapshot:
    """Build only from verified immutable owner projections, never arbitrary hashes."""

    if cash_projection.account_ref != positions_projection.account_ref:
        raise ValueError("cash and positions projections must bind the same account")
    source_evidence = (
        SnapshotSourceEvidence(
            kind=SnapshotEvidenceKind.CASH,
            owner=GOVERNED_SNAPSHOT_EVIDENCE_OWNERS[SnapshotEvidenceKind.CASH],
            evidence_ref=cash_projection.evidence_ref,
            version=cash_projection.version,
            observed_at=cash_projection.observed_at,
            content_hash=cash_projection.content_hash,
        ),
        SnapshotSourceEvidence(
            kind=SnapshotEvidenceKind.POSITIONS,
            owner=GOVERNED_SNAPSHOT_EVIDENCE_OWNERS[SnapshotEvidenceKind.POSITIONS],
            evidence_ref=positions_projection.evidence_ref,
            version=positions_projection.version,
            observed_at=positions_projection.observed_at,
            content_hash=positions_projection.content_hash,
        ),
    )
    as_of = max(item.observed_at for item in source_evidence)
    ordered_positions = positions_projection.positions
    ordered_evidence = tuple(sorted(source_evidence, key=lambda item: item.kind.value))
    content_hash = canonical_snapshot_content_hash(
        account_ref=cash_projection.account_ref,
        as_of=as_of,
        base_currency=cash_projection.base_currency,
        cash_balance=cash_projection.cash_balance,
        cash_version=cash_projection.version,
        positions_version=positions_projection.version,
        positions=ordered_positions,
        source_evidence=ordered_evidence,
    )
    return CanonicalPortfolioSnapshot(
        snapshot_id=f"portfolio_snapshot:{content_hash[:24]}",
        account_ref=cash_projection.account_ref,
        as_of=as_of,
        base_currency=cash_projection.base_currency,
        cash_balance=cash_projection.cash_balance,
        cash_version=cash_projection.version,
        positions_version=positions_projection.version,
        positions=ordered_positions,
        source_evidence=ordered_evidence,
        content_hash=content_hash,
    )


def build_execution_feedback(
    *,
    portfolio_snapshot_ref: str,
    transition_plan_ref: str,
    order_intent_ref: str,
    planning_policy_version: str,
    asset_code: str,
    side: str,
    planned_quantity: Decimal,
    planned_reference_price: Decimal,
    planned_estimated_fee: Decimal,
    broker_evidence: BrokerExecutionEvidence,
    constraint_deviations: tuple[ConstraintExecutionDeviation, ...] = (),
) -> PortfolioExecutionFeedback:
    """Reconcile plan values with exact broker fills without creating an order."""

    _require_values(
        portfolio_snapshot_ref=portfolio_snapshot_ref,
        transition_plan_ref=transition_plan_ref,
        order_intent_ref=order_intent_ref,
        planning_policy_version=planning_policy_version,
        asset_code=asset_code,
    )
    _require_finite_decimals(
        planned_quantity=planned_quantity,
        planned_reference_price=planned_reference_price,
        planned_estimated_fee=planned_estimated_fee,
    )
    if side not in {"buy", "sell"}:
        raise ValueError("execution feedback side must be buy or sell")
    if planned_quantity <= 0 or planned_reference_price <= 0:
        raise ValueError("planned quantity and reference price must be positive")
    if planned_estimated_fee < 0:
        raise ValueError("planned estimated fee cannot be negative")
    metrics = _calculate_execution_feedback_metrics(
        side=side,
        planned_quantity=planned_quantity,
        planned_reference_price=planned_reference_price,
        planned_estimated_fee=planned_estimated_fee,
        broker_evidence=broker_evidence,
        constraint_deviations=constraint_deviations,
    )
    payload = _execution_feedback_payload(
        portfolio_snapshot_ref=portfolio_snapshot_ref,
        transition_plan_ref=transition_plan_ref,
        order_intent_ref=order_intent_ref,
        planning_policy_version=planning_policy_version,
        asset_code=asset_code,
        side=side,
        planned_quantity=planned_quantity,
        planned_reference_price=planned_reference_price,
        planned_estimated_fee=planned_estimated_fee,
        broker_evidence=broker_evidence,
        filled_quantity=metrics.filled_quantity,
        average_fill_price=metrics.average_fill_price,
        actual_fee=metrics.actual_fee,
        fee_variance=metrics.fee_variance,
        realized_slippage=metrics.realized_slippage,
        fill_rate=metrics.fill_rate,
        constraint_deviations=metrics.constraint_deviations,
    )
    content_hash = _sha256(payload)
    return PortfolioExecutionFeedback(
        feedback_id=f"portfolio_execution_feedback:{content_hash[:24]}",
        portfolio_snapshot_ref=portfolio_snapshot_ref,
        transition_plan_ref=transition_plan_ref,
        order_intent_ref=order_intent_ref,
        planning_policy_version=planning_policy_version,
        asset_code=asset_code,
        side=side,
        planned_quantity=planned_quantity,
        planned_reference_price=planned_reference_price,
        planned_estimated_fee=planned_estimated_fee,
        client_order_ref=broker_evidence.client_order_ref,
        broker_order_ref=broker_evidence.broker_order_ref,
        order_events=broker_evidence.order_events,
        fills=broker_evidence.fills,
        reconciliation_ref=broker_evidence.reconciliation_ref,
        reconciliation_observed_at=broker_evidence.reconciliation_observed_at,
        filled_quantity=metrics.filled_quantity,
        average_fill_price=metrics.average_fill_price,
        actual_fee=metrics.actual_fee,
        fee_variance=metrics.fee_variance,
        realized_slippage=metrics.realized_slippage,
        fill_rate=metrics.fill_rate,
        rejected=broker_evidence.rejected,
        rejection_code=broker_evidence.rejection_code,
        rejection_reason=broker_evidence.rejection_reason,
        constraint_deviations=metrics.constraint_deviations,
        source_evidence_hash=broker_evidence.source_evidence_hash,
        content_hash=content_hash,
    )


def build_broker_execution_evidence(
    *,
    client_order_ref: str,
    broker_order_ref: str,
    order_events: tuple[BrokerOrderEventEvidence, ...],
    fills: tuple[BrokerFillEvidence, ...],
    reconciliation_ref: str,
    reconciliation_observed_at: datetime,
    rejected: bool = False,
    rejection_code: str = "",
    rejection_reason: str = "",
) -> BrokerExecutionEvidence:
    """Build broker evidence with a digest over the exact source projection."""

    source_evidence_hash = broker_execution_evidence_hash(
        client_order_ref=client_order_ref,
        broker_order_ref=broker_order_ref,
        order_events=order_events,
        fills=fills,
        reconciliation_ref=reconciliation_ref,
        reconciliation_observed_at=reconciliation_observed_at,
        rejected=rejected,
        rejection_code=rejection_code,
        rejection_reason=rejection_reason,
    )
    return BrokerExecutionEvidence(
        client_order_ref=client_order_ref,
        broker_order_ref=broker_order_ref,
        order_events=order_events,
        fills=fills,
        reconciliation_ref=reconciliation_ref,
        reconciliation_observed_at=reconciliation_observed_at,
        source_evidence_hash=source_evidence_hash,
        rejected=rejected,
        rejection_code=rejection_code,
        rejection_reason=rejection_reason,
    )


def broker_execution_evidence_hash(
    *,
    client_order_ref: str,
    broker_order_ref: str,
    order_events: tuple[BrokerOrderEventEvidence, ...],
    fills: tuple[BrokerFillEvidence, ...],
    reconciliation_ref: str,
    reconciliation_observed_at: datetime,
    rejected: bool,
    rejection_code: str,
    rejection_reason: str,
) -> str:
    """Hash stable broker references, values, and original source timestamps."""

    payload: dict[str, object] = {
        "client_order_ref": client_order_ref,
        "broker_order_ref": broker_order_ref,
        "order_events": [
            {
                "event_ref": item.event_ref,
                "event_type": item.event_type,
                "status": item.status,
                "occurred_at": _datetime_string(item.occurred_at),
            }
            for item in order_events
        ],
        "fills": [
            {
                "fill_ref": item.fill_ref,
                "quantity": _decimal_string(item.quantity),
                "price": _decimal_string(item.price),
                "fee": _decimal_string(item.fee),
                "occurred_at": _datetime_string(item.occurred_at),
            }
            for item in fills
        ],
        "reconciliation_ref": reconciliation_ref,
        "reconciliation_observed_at": _datetime_string(reconciliation_observed_at),
        "rejected": rejected,
        "rejection_code": rejection_code,
        "rejection_reason": rejection_reason,
    }
    return _sha256(payload)


def canonical_snapshot_content_hash(
    *,
    account_ref: str,
    as_of: datetime,
    base_currency: str,
    cash_balance: Decimal,
    cash_version: str,
    positions_version: str,
    positions: tuple[CanonicalPosition, ...],
    source_evidence: tuple[SnapshotSourceEvidence, ...],
) -> str:
    """Return a deterministic SHA-256 over the canonical snapshot content."""

    _require_finite_decimals(cash_balance=cash_balance)
    payload: dict[str, object] = {
        "account_ref": account_ref,
        "as_of": _datetime_string(as_of),
        "base_currency": base_currency,
        "cash_balance": _decimal_string(cash_balance),
        "cash_version": cash_version,
        "positions_version": positions_version,
        "positions": [
            {
                "asset_code": item.asset_code,
                "quantity": _decimal_string(item.quantity),
                "available_quantity": _decimal_string(item.available_quantity),
                "market_value_base": _decimal_string(item.market_value_base),
                "position_source_ref": item.position_source_ref,
                "position_observed_at": _datetime_string(item.position_observed_at),
                "valuation_source_ref": item.valuation_source_ref,
                "valuation_observed_at": _datetime_string(item.valuation_observed_at),
            }
            for item in sorted(positions, key=lambda value: value.asset_code)
        ],
        "source_evidence": [
            {
                "kind": item.kind.value,
                "owner": item.owner,
                "evidence_ref": item.evidence_ref,
                "version": item.version,
                "observed_at": _datetime_string(item.observed_at),
                "content_hash": item.content_hash,
            }
            for item in sorted(source_evidence, key=lambda value: value.kind.value)
        ],
    }
    return _sha256(payload)


def canonical_cash_projection_hash(
    *,
    account_ref: str,
    base_currency: str,
    cash_balance: Decimal,
    evidence_ref: str,
    version: str,
    observed_at: datetime,
) -> str:
    """Hash the exact Account-owned cash payload and source clock."""

    _require_finite_decimals(cash_balance=cash_balance)
    return _sha256(
        {
            "kind": SnapshotEvidenceKind.CASH.value,
            "owner": GOVERNED_SNAPSHOT_EVIDENCE_OWNERS[SnapshotEvidenceKind.CASH],
            "account_ref": account_ref,
            "base_currency": base_currency,
            "cash_balance": _decimal_string(cash_balance),
            "evidence_ref": evidence_ref,
            "version": version,
            "observed_at": _datetime_string(observed_at),
        }
    )


def canonical_positions_projection_hash(
    *,
    account_ref: str,
    evidence_ref: str,
    version: str,
    observed_at: datetime,
    positions: tuple[CanonicalPosition, ...],
) -> str:
    """Hash exact Portfolio-owned position rows and their original clocks."""

    return _sha256(
        {
            "kind": SnapshotEvidenceKind.POSITIONS.value,
            "owner": GOVERNED_SNAPSHOT_EVIDENCE_OWNERS[SnapshotEvidenceKind.POSITIONS],
            "account_ref": account_ref,
            "evidence_ref": evidence_ref,
            "version": version,
            "observed_at": _datetime_string(observed_at),
            "positions": [
                {
                    "asset_code": item.asset_code,
                    "quantity": _decimal_string(item.quantity),
                    "available_quantity": _decimal_string(item.available_quantity),
                    "market_value_base": _decimal_string(item.market_value_base),
                    "position_source_ref": item.position_source_ref,
                    "position_observed_at": _datetime_string(item.position_observed_at),
                    "valuation_source_ref": item.valuation_source_ref,
                    "valuation_observed_at": _datetime_string(item.valuation_observed_at),
                }
                for item in sorted(positions, key=lambda value: value.asset_code)
            ],
        }
    )


def _calculate_execution_feedback_metrics(
    *,
    side: str,
    planned_quantity: Decimal,
    planned_reference_price: Decimal,
    planned_estimated_fee: Decimal,
    broker_evidence: BrokerExecutionEvidence,
    constraint_deviations: tuple[ConstraintExecutionDeviation, ...],
) -> _ExecutionFeedbackMetrics:
    filled_quantity = sum((item.quantity for item in broker_evidence.fills), Decimal("0"))
    actual_fee = sum((item.fee for item in broker_evidence.fills), Decimal("0"))
    filled_notional = sum(
        (item.quantity * item.price for item in broker_evidence.fills), Decimal("0")
    )
    average_fill_price = filled_notional / filled_quantity if filled_quantity > 0 else None
    slippage_per_unit = Decimal("0")
    if average_fill_price is not None:
        slippage_per_unit = (
            average_fill_price - planned_reference_price
            if side == "buy"
            else planned_reference_price - average_fill_price
        )
    realized_slippage = slippage_per_unit * filled_quantity
    fill_rate = filled_quantity / planned_quantity
    deviations = list(constraint_deviations)
    if filled_quantity > planned_quantity and not any(
        item.rule_code == "planned_quantity_cap" for item in deviations
    ):
        deviations.append(
            ConstraintExecutionDeviation(
                rule_code="planned_quantity_cap",
                expected_value=_decimal_string(planned_quantity),
                actual_value=_decimal_string(filled_quantity),
                reason="broker fills exceeded the planned quantity",
            )
        )
    return _ExecutionFeedbackMetrics(
        filled_quantity=filled_quantity,
        average_fill_price=average_fill_price,
        actual_fee=actual_fee,
        fee_variance=actual_fee - planned_estimated_fee,
        realized_slippage=realized_slippage,
        fill_rate=fill_rate,
        constraint_deviations=tuple(sorted(deviations, key=lambda item: item.rule_code)),
    )


def _execution_feedback_payload(
    *,
    portfolio_snapshot_ref: str,
    transition_plan_ref: str,
    order_intent_ref: str,
    planning_policy_version: str,
    asset_code: str,
    side: str,
    planned_quantity: Decimal,
    planned_reference_price: Decimal,
    planned_estimated_fee: Decimal,
    broker_evidence: BrokerExecutionEvidence,
    filled_quantity: Decimal,
    average_fill_price: Decimal | None,
    actual_fee: Decimal,
    fee_variance: Decimal,
    realized_slippage: Decimal,
    fill_rate: Decimal,
    constraint_deviations: tuple[ConstraintExecutionDeviation, ...],
) -> dict[str, object]:
    return {
        "portfolio_snapshot_ref": portfolio_snapshot_ref,
        "transition_plan_ref": transition_plan_ref,
        "order_intent_ref": order_intent_ref,
        "planning_policy_version": planning_policy_version,
        "asset_code": asset_code,
        "side": side,
        "planned_quantity": _decimal_string(planned_quantity),
        "planned_reference_price": _decimal_string(planned_reference_price),
        "planned_estimated_fee": _decimal_string(planned_estimated_fee),
        "client_order_ref": broker_evidence.client_order_ref,
        "broker_order_ref": broker_evidence.broker_order_ref,
        "order_events": [
            {
                "event_ref": item.event_ref,
                "event_type": item.event_type,
                "status": item.status,
                "occurred_at": _datetime_string(item.occurred_at),
            }
            for item in broker_evidence.order_events
        ],
        "fills": [
            {
                "fill_ref": item.fill_ref,
                "quantity": _decimal_string(item.quantity),
                "price": _decimal_string(item.price),
                "fee": _decimal_string(item.fee),
                "occurred_at": _datetime_string(item.occurred_at),
            }
            for item in broker_evidence.fills
        ],
        "reconciliation_ref": broker_evidence.reconciliation_ref,
        "reconciliation_observed_at": _datetime_string(broker_evidence.reconciliation_observed_at),
        "filled_quantity": _decimal_string(filled_quantity),
        "average_fill_price": (
            _decimal_string(average_fill_price) if average_fill_price is not None else None
        ),
        "actual_fee": _decimal_string(actual_fee),
        "fee_variance": _decimal_string(fee_variance),
        "realized_slippage": _decimal_string(realized_slippage),
        "fill_rate": _decimal_string(fill_rate),
        "rejected": broker_evidence.rejected,
        "rejection_code": broker_evidence.rejection_code,
        "rejection_reason": broker_evidence.rejection_reason,
        "constraint_deviations": [
            {
                "rule_code": item.rule_code,
                "expected_value": item.expected_value,
                "actual_value": item.actual_value,
                "reason": item.reason,
            }
            for item in constraint_deviations
        ],
        "source_evidence_hash": broker_evidence.source_evidence_hash,
    }


def _sha256(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _decimal_string(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _datetime_string(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(UTC).isoformat()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_values(**values: str) -> None:
    missing = sorted(name for name, value in values.items() if not value.strip())
    if missing:
        raise ValueError(f"required values are missing: {', '.join(missing)}")


def _require_finite_decimals(**values: Decimal) -> None:
    non_finite = sorted(name for name, value in values.items() if not value.is_finite())
    if non_finite:
        raise ValueError(f"decimal values must be finite: {', '.join(non_finite)}")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")


__all__ = [
    "BrokerExecutionEvidence",
    "BrokerFillEvidence",
    "BrokerOrderEventEvidence",
    "CanonicalPortfolioSnapshot",
    "CanonicalCashProjection",
    "CanonicalPosition",
    "CanonicalPositionsProjection",
    "ConstraintExecutionDeviation",
    "PortfolioExecutionFeedback",
    "SnapshotEvidenceKind",
    "SnapshotSourceEvidence",
    "build_canonical_cash_projection",
    "build_canonical_portfolio_snapshot",
    "build_canonical_positions_projection",
    "build_broker_execution_evidence",
    "build_execution_feedback",
    "broker_execution_evidence_hash",
    "canonical_snapshot_content_hash",
    "canonical_cash_projection_hash",
    "canonical_positions_projection_hash",
]
