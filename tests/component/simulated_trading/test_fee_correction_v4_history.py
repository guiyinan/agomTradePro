"""Prove fee correction preserves a real FeeV2 V4 fill prefix and history read."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import cast
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    ApplySimulatedFeeCorrectionUseCase,
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionRequest,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    OPERATOR_FEE_CSV_SCHEMA,
    FeeCorrectionEvidenceUploadCommand,
    FeeCorrectionEvidenceUploadUseCase,
)
from apps.simulated_trading.application.order_reservation import (
    CancelSimulatedOrderReservationUseCase,
)
from apps.simulated_trading.application.order_reservation_fill import (
    ApplySimulatedOrderFillCommand,
    ApplySimulatedOrderFillUseCase,
    LocalSimulatedFillSourceBinding,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_repository import (
    DjangoFeeCorrectionEvidenceRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_runtime import (
    build_django_fee_correction_repository,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _READ_CUTOFF,
    _EventReader,
    _first_buy_rows,
    _FixedClock,
    _initial_position_mark,
    _InitialPositionMarkReader,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
)
from tests.support.native_postgres_database import (
    assert_native_postgres_test_database,
)
from tests.support.native_postgres_database import (  # noqa: F401
    native_postgres_test_database as _native_postgres_test_database_fixture,
)

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=[
            "apps.simulated_trading",
            "django.contrib.auth",
            "django.contrib.contenttypes",
        ],
    ),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Fee correction V4 history requires Native PostgreSQL",
    ),
]


@pytest.fixture(scope="session")
def django_db_setup(native_postgres_test_database: str) -> str:
    """Bind this module to the shared explicit TEST.NAME setup."""

    return native_postgres_test_database


_CSV_HEADERS = (
    "schema_version",
    "currency_code",
    "source_account_ref",
    "source_trade_ref",
    "asset_code",
    "side",
    "quantity",
    "price",
    "amount",
    "execution_at",
    "source_observed_at",
    "commission",
    "transfer_fee",
    "stamp_duty",
)


@dataclass(frozen=True, slots=True)
class _FixtureSettlementResolver:
    """Build a settlement proof from the fixture's published calendar evidence."""

    evidence: ExecutionCalendarEvidence
    read_cutoff: datetime

    def resolve(
        self,
        *,
        event_occurred_at: datetime,
        settlement_exchange: str,
        settlement_lag_sessions: int,
        sealed_calendar_evidence: ExecutionCalendarEvidence | None = None,
    ) -> OrderFillSettlementProof | None:
        """Resolve only the exact exchange and lag held by the sealed fixture."""

        if settlement_exchange != self.evidence.snapshot.exchange:
            return None
        return build_order_fill_settlement_proof(
            calendar_evidence=self.evidence,
            calendar_read_cutoff=self.read_cutoff,
            fill_occurred_at=event_occurred_at,
            settlement_exchange=settlement_exchange,
            settlement_lag_sessions=settlement_lag_sessions,
        )


def _json_object(value: object, label: str) -> dict[str, object]:
    """Narrow a persisted JSON object before asserting its sealed accrual fields."""

    if type(value) is not dict:
        raise AssertionError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _trade_rows_snapshot(account_id: int) -> tuple[dict[str, object], ...]:
    """Capture every persisted Trade column for an exact immutability comparison."""

    return tuple(
        cast(dict[str, object], row)
        for row in SimulatedTradeModel._base_manager.filter(account_id=account_id)
        .order_by("pk")
        .values()
    )


def _receipt_rows_snapshot(account_id: int) -> tuple[dict[str, object], ...]:
    """Capture every persisted receipt column, including JSON and all content seals."""

    return tuple(
        cast(dict[str, object], row)
        for row in SimulatedOrderFillReceiptModel._base_manager.filter(trade__account_id=account_id)
        .order_by("reservation_id", "fill_sequence", "pk")
        .values()
    )


def _operator_attested_csv(
    *,
    account_id: int,
    trade: SimulatedTradeModel,
    source_observed_at: datetime,
    revised_commission: Decimal,
) -> bytes:
    """Encode synthetic local operator-attested evidence for this exact Trade."""

    if trade.transfer_fee is None or trade.stamp_duty is None:
        raise AssertionError("V4 trade must preserve known transfer and stamp fees")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_CSV_HEADERS)
    writer.writerow(
        (
            OPERATOR_FEE_CSV_SCHEMA,
            "CNY",
            f"account-{account_id}",
            f"trade-{trade.pk}",
            trade.asset_code,
            trade.action,
            format(trade.quantity, "f"),
            format(trade.price, "f"),
            format(trade.amount, "f"),
            trade.execution_time.isoformat(timespec="microseconds"),
            source_observed_at.isoformat(timespec="microseconds"),
            format(revised_commission, ".2f"),
            format(trade.transfer_fee, ".2f"),
            format(trade.stamp_duty, ".2f"),
        )
    )
    return output.getvalue().encode("utf-8")


def test_fee_correction_preserves_nonempty_v4_fill_prefix_and_history_projection(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    django_db_setup: str,
) -> None:
    """Correct one fill's fee only through an append-only overlay after a real V4 chain."""

    del persisted_receipt_schema
    assert_native_postgres_test_database(expected_name=django_db_setup)
    harness = reservation_harness
    rows = _first_buy_rows(harness)
    # This typed fixture reader is synthetic; the real Application and ORM
    # writer create, seal, re-read, and later revalidate the persisted chain.
    reader = _EventReader(rows.event, [])
    mark_reader = _InitialPositionMarkReader(_initial_position_mark(rows), [])
    fill_repository = DjangoSimulatedOrderFillRepository(
        event_reader=reader,
        initial_position_mark_reader=mark_reader,
        using="default",
    )
    fill_clock = _FixedClock(_READ_CUTOFF)
    fill_use_case = ApplySimulatedOrderFillUseCase(
        repository=fill_repository,
        clock=fill_clock,
        source_binding=LocalSimulatedFillSourceBinding(
            reader=reader,
            source_namespace=rows.event.source_namespace,
            source_version=rows.event.source_version,
        ),
        settlement_resolver=_FixtureSettlementResolver(
            evidence=rows.proof.calendar_evidence,
            read_cutoff=_READ_CUTOFF,
        ),
    )

    first_event = rows.event
    first_result = fill_use_case.execute(
        ApplySimulatedOrderFillCommand(
            account_id=harness.account.pk,
            user_id=harness.user_id,
            order_idempotency_key=rows.reservation.idempotency_key,
            source_namespace=first_event.source_namespace,
            fill_event_id=first_event.source_event_id,
            expected_event_payload_hash=first_event.event_payload_hash,
        )
    )
    second_at = first_event.occurred_at + timedelta(seconds=30)
    second_event = replace(
        first_event,
        source_event_id="row-reader-event-0002",
        event_payload_hash="6" * 64,
        source_snapshot_id="row-reader-source-snapshot-002",
        source_snapshot_hash="7" * 64,
        quantity=Decimal("20.000000"),
        occurred_at=second_at,
        source_observed_at=second_at,
        source_available_at=second_at,
        recorded_at=second_at,
    )
    reader.event = second_event
    second_result = fill_use_case.execute(
        ApplySimulatedOrderFillCommand(
            account_id=harness.account.pk,
            user_id=harness.user_id,
            order_idempotency_key=rows.reservation.idempotency_key,
            source_namespace=second_event.source_namespace,
            fill_event_id=second_event.source_event_id,
            expected_event_payload_hash=second_event.event_payload_hash,
        )
    )
    assert first_result.replayed is False
    assert second_result.replayed is False
    assert first_result.reservation.status.value == "active"
    assert second_result.reservation.status.value == "active"

    receipts = tuple(
        SimulatedOrderFillReceiptModel._base_manager.filter(
            reservation_id=rows.reservation.pk
        ).order_by("fill_sequence", "pk")
    )
    assert len(receipts) == 2
    assert tuple(receipt.fill_sequence for receipt in receipts) == (1, 2)
    trades = tuple(
        SimulatedTradeModel._base_manager.filter(account_id=harness.account.pk).order_by("pk")
    )
    assert len(trades) == 2
    assert all(trade.settlement_plan_binding_version == 4 for trade in trades)
    assert all(trade.status == "executed" for trade in trades)
    prior = _json_object(receipts[1].economics_payload, "second receipt economics")
    prior_state = _json_object(prior["prior"], "second receipt prior accrual")
    cumulative_state = _json_object(prior["cumulative_state"], "second receipt cumulative accrual")
    assert prior_state["fill_count"] == 1
    assert Decimal(str(prior_state["cumulative_quantity"])) == Decimal("10.000000")
    assert cumulative_state["fill_count"] == 2
    assert Decimal(str(cumulative_state["cumulative_quantity"])) == Decimal("30.000000")

    cancel_use_case = CancelSimulatedOrderReservationUseCase(
        repository=harness.repository,
        clock=_FixedClock(_READ_CUTOFF + timedelta(seconds=1)),
    )
    cancelled = cancel_use_case.execute(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        idempotency_key=rows.reservation.idempotency_key,
    )
    assert cancelled.status.value == "cancelled"
    persisted_reservation = SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk)
    assert persisted_reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert persisted_reservation.filled_quantity == Decimal("30.000000")
    assert not SimulatedOrderReservationModel.objects.filter(
        account_id=harness.account.pk,
        status=SimulatedOrderReservationModel.STATUS_ACTIVE,
    ).exists()

    target_trade = SimulatedTradeModel.objects.get(pk=trades[0].pk)
    account_before = SimulatedAccountModel.objects.get(pk=harness.account.pk)
    position_before = PositionModel.objects.get(
        account_id=harness.account.pk,
        asset_code=target_trade.asset_code,
    )
    original_trade_rows = _trade_rows_snapshot(harness.account.pk)
    original_receipt_rows = _receipt_rows_snapshot(harness.account.pk)
    revised_commission = target_trade.commission + Decimal("0.01")
    now = timezone.now()
    source_observed_at = now - timedelta(hours=1)
    posted_at = now + timedelta(minutes=5)
    FeeCorrectionEvidencePolicyModel.objects.create(
        account_id=harness.account.pk,
        enabled=True,
        allow_operator_attested_upload=True,
        ledger_currency="CNY",
        version=1,
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=30),
        updated_by_id=harness.user_id,
    )
    raw_evidence = _operator_attested_csv(
        account_id=harness.account.pk,
        trade=target_trade,
        source_observed_at=source_observed_at,
        revised_commission=revised_commission,
    )
    idempotency_key = f"v4-fee-correction-{uuid4().hex}"
    evidence_repository = DjangoFeeCorrectionEvidenceRepository()
    owner = get_user_model()._base_manager.get(pk=harness.user_id)
    evidence_upload = FeeCorrectionEvidenceUploadUseCase(evidence_repository).execute(
        FeeCorrectionEvidenceUploadCommand(
            account_id=harness.account.pk,
            trade_id=target_trade.pk,
            expected_revision=0,
            expected_predecessor_id=None,
            idempotency_key=idempotency_key,
            original_filename="synthetic-v4-fee-correction.csv",
            content=raw_evidence,
            attestation_acknowledged=True,
        ),
        principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, owner),
    )
    request = FeeCorrectionRequest(
        account_id=harness.account.pk,
        trade_id=target_trade.pk,
        idempotency_key=idempotency_key,
        expected_revision=0,
        source_locator=evidence_upload.source_locator,
    )
    correction_repository = build_django_fee_correction_repository(
        evidence_repository=evidence_repository,
    )
    correction_use_case = ApplySimulatedFeeCorrectionUseCase(
        repository=correction_repository,
        evidence_verifier=evidence_repository,
        authority=evidence_repository,
        clock=_FixedClock(posted_at),
    )
    verified_evidence = evidence_repository.verify(request)
    authorization = evidence_repository.authorize(
        account_id=harness.account.pk,
        principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, owner),
    )
    assert verified_evidence is not None
    assert authorization is not None

    real_account = SimulatedAccountModel.objects.get(pk=harness.account.pk)
    real_account.account_type = "real"
    real_account.save(update_fields=("account_type",))
    with pytest.raises(FeeCorrectionBlockedError) as write_error:
        correction_repository.apply_fee_correction(
            request=request,
            principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, owner),
            evidence=verified_evidence,
            authorization=authorization,
            clock=_FixedClock(posted_at),
        )
    assert write_error.value.code == "SIMULATED_ACCOUNT_UNAVAILABLE"
    assert not SimulatedFeeCorrectionEventModel.objects.filter(
        account_id=harness.account.pk
    ).exists()
    real_account.account_type = "simulated"
    real_account.save(update_fields=("account_type",))

    correction_receipt = correction_use_case.execute(
        request,
        principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, owner),
    )

    assert correction_receipt.replayed is False
    event = SimulatedFeeCorrectionEventModel.objects.get(pk=correction_receipt.event_id)
    assert event.trade_id == target_trade.pk
    assert event.previous_commission == target_trade.commission
    assert event.revised_commission == revised_commission
    assert event.cash_delta == Decimal("-0.01")
    assert event.receipt_snapshot_hash is not None
    assert event.source_observed_at == source_observed_at
    assert event.posted_at == posted_at

    binding = FeeCorrectionEvidenceBindingModel.objects.select_related("artifact").get(
        public_id=evidence_upload.source_locator
    )
    assert binding.assurance_class == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert binding.artifact.assurance_class == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert bytes(binding.artifact.raw_bytes) == raw_evidence

    # Fee corrections append an overlay; every original Trade and V4 receipt column stays fixed.
    assert _trade_rows_snapshot(harness.account.pk) == original_trade_rows
    assert _receipt_rows_snapshot(harness.account.pk) == original_receipt_rows
    account_after = SimulatedAccountModel.objects.get(pk=harness.account.pk)
    assert account_after.current_cash == account_before.current_cash - Decimal("0.01")
    assert account_after.current_market_value == account_before.current_market_value
    assert account_after.total_value == account_before.total_value - Decimal("0.01")
    assert account_after.cash_known is True
    assert account_after.cash_reconciliation_status == "simulated_ledger"
    position_after = PositionModel.objects.get(pk=position_before.pk)
    expected_cost = position_before.total_cost + Decimal("0.01")
    with localcontext() as context:
        context.prec = 80
        expected_average_cost = (expected_cost / position_before.quantity).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_EVEN,
        )
    assert position_after.quantity == position_before.quantity
    assert position_after.available_quantity == position_before.available_quantity
    assert position_after.current_price == position_before.current_price
    assert position_after.market_value == position_before.market_value
    assert position_after.total_cost == expected_cost
    assert position_after.avg_cost == expected_average_cost
    assert position_after.unrealized_pnl == position_before.unrealized_pnl - Decimal("0.01")
    assert position_after.cost_basis_known is True

    history = correction_repository.get_account_history(
        account_id=harness.account.pk,
        as_of=posted_at + timedelta(seconds=1),
    )
    projected_trade = next(item for item in history.trades if item.trade_id == target_trade.pk)
    assert projected_trade.commission == float(target_trade.commission)
    assert projected_trade.effective_commission == float(revised_commission)
    assert projected_trade.current_commission == float(revised_commission)
    assert projected_trade.fee_correction_revision == 1
    assert projected_trade.fee_correction_overlay_applied is True
    assert len(projected_trade.fee_correction_cash_events) == 1
    assert projected_trade.fee_correction_cash_events[0].cash_delta == Decimal("-0.01")
    assert len(history.cash_events) == 1
    assert history.cash_events[0].account_revision == 1
    assert history.cash_events[0].cash_delta == Decimal("-0.01")

    real_account = SimulatedAccountModel.objects.get(pk=harness.account.pk)
    real_account.account_type = "real"
    real_account.save(update_fields=("account_type",))
    with pytest.raises(FeeCorrectionBlockedError) as history_error:
        correction_repository.get_account_history(
            account_id=harness.account.pk,
            as_of=posted_at + timedelta(seconds=1),
        )
    assert history_error.value.code == "FEE_CORRECTION_HISTORY_INVALID"
