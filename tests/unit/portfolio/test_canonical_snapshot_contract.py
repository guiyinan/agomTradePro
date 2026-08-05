"""Unit coverage for Portfolio canonical snapshots and execution feedback."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.application.canonical_snapshots import (
    CanonicalPortfolioSnapshotQueryService,
    RecordPortfolioExecutionFeedbackUseCase,
)
from apps.portfolio.domain.canonical_snapshots import (
    BrokerExecutionEvidence,
    BrokerFillEvidence,
    BrokerOrderEventEvidence,
    CanonicalPortfolioSnapshot,
    CanonicalPosition,
    SnapshotEvidenceKind,
    SnapshotSourceEvidence,
    build_broker_execution_evidence,
    build_canonical_cash_projection,
    build_canonical_portfolio_snapshot,
    build_canonical_positions_projection,
    build_execution_feedback,
)

NOW = datetime(2026, 8, 5, 9, tzinfo=UTC)


def _position(asset_code: str = "000001.SZ") -> CanonicalPosition:
    return CanonicalPosition(
        asset_code=asset_code,
        quantity=Decimal("100"),
        available_quantity=Decimal("80"),
        market_value_base=Decimal("1023.00"),
        position_source_ref=f"position:{asset_code}:v11",
        position_observed_at=NOW,
        valuation_source_ref=f"valuation:{asset_code}:20260805T0900Z",
        valuation_observed_at=NOW + timedelta(seconds=30),
    )


def _snapshot() -> CanonicalPortfolioSnapshot:
    return build_canonical_portfolio_snapshot(
        cash_projection=build_canonical_cash_projection(
            account_ref="account:42",
            base_currency="CNY",
            cash_balance=Decimal("5000"),
            evidence_ref="account-ledger:cash:42:v7",
            version="cash.v7",
            observed_at=NOW,
        ),
        positions_projection=build_canonical_positions_projection(
            account_ref="account:42",
            evidence_ref="portfolio-ledger:positions:42:v11",
            version="positions.v11",
            observed_at=NOW + timedelta(minutes=1),
            positions=(_position(),),
        ),
    )


def _broker_evidence() -> BrokerExecutionEvidence:
    return build_broker_execution_evidence(
        client_order_ref="client-order:1001",
        broker_order_ref="broker-order:9001",
        order_events=(
            BrokerOrderEventEvidence(
                event_ref="broker-event:accepted:1",
                event_type="accepted",
                status="submitted",
                occurred_at=NOW + timedelta(minutes=2),
            ),
        ),
        fills=(
            BrokerFillEvidence(
                fill_ref="broker-fill:trade-1",
                quantity=Decimal("40"),
                price=Decimal("10.20"),
                fee=Decimal("1.20"),
                occurred_at=NOW + timedelta(minutes=3),
            ),
            BrokerFillEvidence(
                fill_ref="broker-fill:trade-2",
                quantity=Decimal("40"),
                price=Decimal("10.30"),
                fee=Decimal("1.30"),
                occurred_at=NOW + timedelta(minutes=4),
            ),
        ),
        reconciliation_ref="broker-reconciliation:77",
        reconciliation_observed_at=NOW + timedelta(minutes=5),
    )


def test_snapshot_derives_as_of_and_stable_identity_from_source_observations() -> None:
    first = build_canonical_portfolio_snapshot(
        cash_projection=build_canonical_cash_projection(
            account_ref="account:42",
            base_currency="CNY",
            cash_balance=Decimal("5000.00"),
            evidence_ref="account-ledger:cash:42:v7",
            version="cash.v7",
            observed_at=NOW,
        ),
        positions_projection=build_canonical_positions_projection(
            account_ref="account:42",
            evidence_ref="portfolio-ledger:positions:42:v11",
            version="positions.v11",
            observed_at=NOW + timedelta(minutes=1),
            positions=(_position("600000.SH"), _position("000001.SZ")),
        ),
    )
    second = build_canonical_portfolio_snapshot(
        cash_projection=build_canonical_cash_projection(
            account_ref="account:42",
            base_currency="CNY",
            cash_balance=Decimal("5000"),
            evidence_ref="account-ledger:cash:42:v7",
            version="cash.v7",
            observed_at=NOW,
        ),
        positions_projection=build_canonical_positions_projection(
            account_ref="account:42",
            evidence_ref="portfolio-ledger:positions:42:v11",
            version="positions.v11",
            observed_at=NOW + timedelta(minutes=1),
            positions=(_position("000001.SZ"), _position("600000.SH")),
        ),
    )

    assert first.as_of == NOW + timedelta(minutes=1)
    assert first.snapshot_id == second.snapshot_id
    assert first.content_hash == second.content_hash
    assert [item.asset_code for item in first.positions] == ["000001.SZ", "600000.SH"]


def test_snapshot_rejects_missing_dimension_and_timestamp_washing() -> None:
    with pytest.raises(ValueError, match="positions evidence owner is not governed"):
        SnapshotSourceEvidence(
            SnapshotEvidenceKind.POSITIONS,
            "account",
            "positions:1",
            "positions.v1",
            NOW,
            "b" * 64,
        )

    valid = _snapshot()
    with pytest.raises(ValueError, match="latest source observation"):
        CanonicalPortfolioSnapshot(
            snapshot_id=valid.snapshot_id,
            account_ref=valid.account_ref,
            as_of=valid.as_of + timedelta(hours=1),
            base_currency=valid.base_currency,
            cash_balance=valid.cash_balance,
            cash_version=valid.cash_version,
            positions_version=valid.positions_version,
            positions=valid.positions,
            source_evidence=valid.source_evidence,
            content_hash=valid.content_hash,
        )


def test_snapshot_rejects_payload_tampering_with_reused_digest() -> None:
    cash = build_canonical_cash_projection(
        account_ref="account:42",
        base_currency="CNY",
        cash_balance=Decimal("5000"),
        evidence_ref="account-ledger:cash:42:v7",
        version="cash.v7",
        observed_at=NOW,
    )
    with pytest.raises(ValueError, match="cash projection content hash mismatch"):
        replace(cash, cash_balance=Decimal("9000"))


def test_execution_feedback_calculates_plan_vs_fill_metrics() -> None:
    feedback = build_execution_feedback(
        portfolio_snapshot_ref=_snapshot().snapshot_id,
        transition_plan_ref="transition-plan:1",
        order_intent_ref="order-intent:1",
        planning_policy_version="a-share-policy.v4",
        asset_code="000001.SZ",
        side="buy",
        planned_quantity=Decimal("100"),
        planned_reference_price=Decimal("10"),
        planned_estimated_fee=Decimal("3"),
        broker_evidence=_broker_evidence(),
    )

    assert feedback.filled_quantity == Decimal("80")
    assert feedback.average_fill_price == Decimal("10.25")
    assert feedback.fill_rate == Decimal("0.8")
    assert feedback.actual_fee == Decimal("2.50")
    assert feedback.fee_variance == Decimal("-0.50")
    assert feedback.realized_slippage == Decimal("20.00")
    assert feedback.reconciliation_observed_at == NOW + timedelta(minutes=5)


def test_execution_feedback_rejects_missing_or_inconsistent_broker_evidence() -> None:
    with pytest.raises(ValueError, match="order-event evidence is required"):
        build_broker_execution_evidence(
            client_order_ref="client-order:1001",
            broker_order_ref="broker-order:9001",
            order_events=(),
            fills=(),
            reconciliation_ref="broker-reconciliation:77",
            reconciliation_observed_at=NOW,
        )
    with pytest.raises(ValueError, match="cannot predate"):
        build_broker_execution_evidence(
            client_order_ref="client-order:1001",
            broker_order_ref="broker-order:9001",
            order_events=(
                BrokerOrderEventEvidence(
                    event_ref="event:1",
                    event_type="accepted",
                    status="submitted",
                    occurred_at=NOW + timedelta(minutes=2),
                ),
            ),
            fills=(),
            reconciliation_ref="broker-reconciliation:77",
            reconciliation_observed_at=NOW,
        )


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_non_finite_snapshot_and_execution_values_are_rejected(value: Decimal) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        CanonicalPosition(
            asset_code="000001.SZ",
            quantity=value,
            available_quantity=Decimal("0"),
            market_value_base=Decimal("0"),
            position_source_ref="position:1",
            position_observed_at=NOW,
            valuation_source_ref="valuation:1",
            valuation_observed_at=NOW,
        )
    with pytest.raises(ValueError, match="must be finite"):
        build_execution_feedback(
            portfolio_snapshot_ref=_snapshot().snapshot_id,
            transition_plan_ref="transition-plan:1",
            order_intent_ref="order-intent:1",
            planning_policy_version="a-share-policy.v4",
            asset_code="000001.SZ",
            side="buy",
            planned_quantity=value,
            planned_reference_price=Decimal("10"),
            planned_estimated_fee=Decimal("3"),
            broker_evidence=_broker_evidence(),
        )


def test_evidence_status_and_hashes_are_verified() -> None:
    with pytest.raises(ValueError, match="required values are missing: status"):
        BrokerOrderEventEvidence(
            event_ref="event:1",
            event_type="accepted",
            status="",
            occurred_at=NOW,
        )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        SnapshotSourceEvidence(
            kind=SnapshotEvidenceKind.CASH,
            owner="account",
            evidence_ref="cash:1",
            version="cash.v1",
            observed_at=NOW,
            content_hash="not-a-digest",
        )
    valid = _broker_evidence()
    with pytest.raises(ValueError, match="source evidence hash mismatch"):
        BrokerExecutionEvidence(
            client_order_ref=valid.client_order_ref,
            broker_order_ref=valid.broker_order_ref,
            order_events=valid.order_events,
            fills=valid.fills,
            reconciliation_ref=valid.reconciliation_ref,
            reconciliation_observed_at=valid.reconciliation_observed_at,
            source_evidence_hash="0" * 64,
        )


class _FeedbackRepository:
    def __init__(self) -> None:
        self.saved = None

    def append(self, feedback):  # type: ignore[no-untyped-def]
        self.saved = feedback
        return feedback

    def get(self, feedback_id: str):  # type: ignore[no-untyped-def]
        return None


class _MissingBrokerEvidenceProvider:
    def get_reconciled_evidence(self, *, client_order_ref: str, reconciliation_ref: str) -> None:
        return None


def test_application_fails_closed_when_broker_evidence_is_missing() -> None:
    repository = _FeedbackRepository()
    use_case = RecordPortfolioExecutionFeedbackUseCase(
        repository=repository,
        broker_evidence_provider=_MissingBrokerEvidenceProvider(),
    )

    with pytest.raises(ValueError, match="broker execution evidence is missing"):
        use_case.execute(
            portfolio_snapshot_ref=_snapshot().snapshot_id,
            transition_plan_ref="transition-plan:1",
            order_intent_ref="order-intent:1",
            planning_policy_version="a-share-policy.v4",
            asset_code="000001.SZ",
            side="buy",
            planned_quantity=Decimal("100"),
            planned_reference_price=Decimal("10"),
            planned_estimated_fee=Decimal("3"),
            client_order_ref="client-order:1001",
            reconciliation_ref="broker-reconciliation:77",
        )
    assert repository.saved is None


class _SnapshotRepository:
    def append(self, snapshot):  # type: ignore[no-untyped-def]
        return snapshot

    def get(self, snapshot_id: str):  # type: ignore[no-untyped-def]
        return None

    def find_at_or_before(
        self, *, account_ref: str, cutoff: datetime
    ) -> CanonicalPortfolioSnapshot | None:
        return None


def test_snapshot_query_rejects_naive_cutoff() -> None:
    query = CanonicalPortfolioSnapshotQueryService(_SnapshotRepository())

    with pytest.raises(ValueError, match="cutoff must be timezone-aware"):
        query.get_snapshot_at_or_before(
            account_ref="account:42",
            cutoff=datetime(2026, 8, 5, 9),
        )
