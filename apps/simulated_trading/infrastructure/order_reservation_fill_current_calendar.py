"""Separate retained event-calendar proof from lock-time settlement evidence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from apps.simulated_trading.application.execution_settlement_uow import (
    PublishedExecutionCalendarReader,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from apps.simulated_trading.domain.order_reservation_fill_release import (
    OrderFillSettlementReleaseProof,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import OrderFillSettlementProof
from apps.simulated_trading.infrastructure.order_reservation_codec import validated_plan_snapshot
from apps.simulated_trading.infrastructure.order_reservation_fill_calendar_codec import (
    decode_sealed_order_calendar_evidence,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_release_codec import (
    encode_order_fill_settlement_release_proof,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_release_storage import (
    set_release_proof_fields,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import SimulatedTradeModel


def read_fill_release_calendar(
    *,
    reader: PublishedExecutionCalendarReader | None,
    reservation: SimulatedOrderReservationModel,
    proof: OrderFillSettlementProof,
    pending_rows: Sequence[SimulatedTradeModel],
    now: datetime,
) -> ExecutionCalendarEvidence:
    """Read current evidence under the caller's account lock without revising history.

    An explicitly supplied reader enables the retained-plan path. Existing
    injected single-calendar writers continue to require their original proof
    to be valid at the current clock as well as the event clock.
    """

    try:
        if reader is None:
            proof.calendar_evidence.validate_for(now)
            return proof.calendar_evidence
        sealed = decode_sealed_order_calendar_evidence(
            validated_plan_snapshot(reservation).get("calendar_evidence")
        )
        if (
            sealed.evidence_hash != proof.calendar_evidence.evidence_hash
            or sealed != proof.calendar_evidence
            or proof.calendar_read_cutoff != proof.fill_occurred_at
        ):
            raise ValueError("event proof differs from the retained reservation calendar")
        coverage_start = proof.fill_market_session
        for row in pending_rows:
            if type(row.settlement_market_session) is not date:
                raise ValueError("pending settlement session is invalid")
            coverage_start = min(coverage_start, row.settlement_market_session)
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "成交日历证明与订单封存证据不一致或无法验证",
            code="SIMULATED_FILL_CALENDAR_INVALID",
        ) from error

    evidence = reader.get_effective_execution_calendar(
        exchange=proof.settlement_exchange,
        as_of=now,
        coverage_start=coverage_start,
    )
    if evidence is None:
        raise SimulatedTradeExecutionBlocked(
            "当前结算日历不可用，未记账或释放股份",
            code="SIMULATED_FILL_RELEASE_CALENDAR_UNAVAILABLE",
        )
    try:
        if type(evidence) is not ExecutionCalendarEvidence:
            raise ValueError("current calendar reader returned an unsupported evidence type")
        evidence.__post_init__()
        if evidence.snapshot.exchange != proof.settlement_exchange:
            raise ValueError("current calendar exchange differs from the sealed order")
        current_session = evidence.current_open_session(now)
        evidence.elapsed_open_sessions(proof.fill_market_session, current_session)
        if evidence.snapshot.coverage_start > coverage_start:
            raise ValueError("current calendar omits a pending settlement session")
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "当前日历不能证明完整结算区间，未记账或释放股份",
            code="SIMULATED_FILL_RELEASE_CALENDAR_INVALID",
        ) from error
    return evidence


def persist_immediate_fill_release_proof(
    *,
    trade: SimulatedTradeModel,
    reservation: SimulatedOrderReservationModel,
    receipt_hash: str,
    fill_proof: OrderFillSettlementProof,
    current_evidence: ExecutionCalendarEvidence,
    released_at: datetime,
    using: str,
) -> None:
    """Seal an independently evidenced lag-zero release in the original fill transaction."""

    proof = OrderFillSettlementReleaseProof(
        trade_id=trade.pk,
        reservation_id=reservation.pk,
        account_id=reservation.account_id,
        user_id=reservation.owner_user_id,
        receipt_hash=receipt_hash,
        security_id=reservation.security_id,
        settlement_exchange=fill_proof.settlement_exchange,
        fill_market_session=fill_proof.fill_market_session,
        settlement_lag_sessions=fill_proof.settlement_lag_sessions,
        released_at=released_at,
        release_session=current_evidence.current_open_session(released_at),
        calendar_evidence=current_evidence,
    )
    if proof.settlement_lag_sessions != 0 or trade.settlement_status != "released":
        raise SimulatedTradeExecutionBlocked(
            "即时释放证明只适用于已释放的零滞后买入",
            code="SIMULATED_FILL_RELEASE_CALENDAR_INVALID",
        )
    encoded = encode_order_fill_settlement_release_proof(proof)
    set_release_proof_fields(trade=trade, encoded=encoded)
    trade.save(
        using=using,
        update_fields=["settlement_release_proof_payload", "settlement_release_proof_hash"],
    )
