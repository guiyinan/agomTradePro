"""Strictly reconcile one loaded G2 receipt with its sealed parent and Trade."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import NoReturn, cast

from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
)
from apps.simulated_trading.domain.execution_settlement_uow import TradeFeeBreakdown
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillEconomics,
)
from apps.simulated_trading.domain.order_reservation_fill_release import (
    OrderFillSettlementReleaseProof,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
    simulated_order_fill_trade_key,
)

from .order_fill_receipt_models import SimulatedOrderFillReceiptModel
from .order_reservation_codec import (
    decode_order_reservation,
    fee_policy_from_snapshot,
    validated_plan_snapshot,
)
from .order_reservation_fill_binding_codec import (
    decode_order_reservation_fill_binding,
)
from .order_reservation_fill_release_codec import (
    decode_order_fill_settlement_release_proof,
)
from .order_reservation_fill_snapshot_codec import (
    DecodedOrderReservationFillSnapshot,
    EncodedOrderReservationFillSnapshot,
    decode_order_reservation_fill_snapshot,
)
from .order_reservation_models import SimulatedOrderReservationModel
from .simulated_account_trade_models import SimulatedTradeModel


@dataclass(frozen=True, slots=True)
class DecodedOrderReservationFillRow:
    """Return only the typed event, economics, and proof checked for one row."""

    reservation_id: int
    receipt_id: int
    trade_id: int
    fill_sequence: int
    trade_key: str
    receipt_hash: str
    event: LocalSimulatedFillEventV1
    economics: OrderReservationFillEconomics
    proof: OrderFillSettlementProof
    release_proof: OrderFillSettlementReleaseProof | None = None


@dataclass(frozen=True, slots=True)
class _ParentContext:
    """Carry exact parent columns and sealed policy values into row checks."""

    reservation_id: int
    account_id: int
    owner_user_id: int
    idempotency_key: str
    intent_payload_hash: str
    reservation_request_hash: str
    plan_snapshot_hash: str
    security_id: str
    asset_code: str
    asset_name: str
    asset_type: str
    market: str
    board: str
    side: str
    quantity: Decimal
    filled_quantity: Decimal
    limit_price: Decimal
    reserved_at: datetime
    market_session: date
    settlement_exchange: str
    settlement_lag_sessions: int
    settlement_bundle_id: str
    settlement_bundle_version: str
    settlement_bundle_hash: str
    settlement_policy_id: str
    settlement_policy_version: str
    settlement_policy_hash: str
    execution_rule_v2_hash: str
    reason: str
    signal_id: int | None
    fee_policy: SimulatedFeePolicyV2


def _invalid(label: str) -> NoReturn:
    """Raise the existing typed contract error for an inconsistent stored row."""

    raise SimulatedSettlementContractError(f"stored fill receipt row is inconsistent: {label}")


def _same(actual: object, expected: object, label: str) -> None:
    """Require exact runtime types and values for duplicated persisted fields."""

    if type(actual) is not type(expected) or actual != expected:
        _invalid(label)


def _object(value: object, label: str) -> dict[str, object]:
    """Accept only a JSON object with literal string keys."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        _invalid(f"{label} is not a JSON object")
    return cast(dict[str, object], value)


def _text(value: object, label: str, *, allow_empty: bool = False) -> str:
    """Narrow one stored plan field to exact text."""

    if type(value) is not str or (not allow_empty and not value):
        _invalid(f"{label} is not valid text")
    return value


def _positive_int(value: object, label: str) -> int:
    """Narrow one stored row key while excluding booleans."""

    if type(value) is not int or value <= 0:
        _invalid(f"{label} is not a positive integer")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    """Narrow one stored session count while excluding booleans."""

    if type(value) is not int or value < 0:
        _invalid(f"{label} is not a nonnegative integer")
    return value


def _date(value: object, label: str) -> date:
    """Parse one exact ISO date from the validated parent JSON snapshot."""

    if type(value) is not str:
        _invalid(f"{label} is not an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise SimulatedSettlementContractError(f"{label} is not an ISO date") from error
    if parsed.isoformat() != value:
        _invalid(f"{label} is not canonical")
    return parsed


def _canonical_json_field(value: object, label: str) -> str:
    """Serialize a JSONField using the receipt codec's canonical JSON recipe."""

    payload = _object(value, label)
    try:
        serialized = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        serialized.encode("utf-8")
        return serialized
    except (TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(f"{label} is not canonical JSON") from error


def _parent_context(row: SimulatedOrderReservationModel) -> _ParentContext:
    """Decode the parent before trusting any receipt's duplicated identifiers."""

    if type(row) is not SimulatedOrderReservationModel:
        _invalid("reservation row has an unexpected model type")
    reservation_id = _positive_int(row.pk, "reservation id")
    account_id = _positive_int(row.account_id, "reservation account id")
    owner_user_id = _positive_int(row.owner_user_id, "reservation owner")
    reservation = decode_order_reservation(row)
    snapshot = validated_plan_snapshot(row)
    intent = _object(snapshot.get("intent"), "sealed intent")
    calendar = _object(snapshot.get("calendar_evidence"), "sealed calendar evidence")
    calendar_snapshot = _object(calendar.get("snapshot"), "sealed calendar snapshot")
    fee_policy = fee_policy_from_snapshot(snapshot)

    if reservation.identity.account_id != account_id:
        _invalid("Domain reservation account differs from its ORM row")
    if reservation.identity.idempotency_key != row.idempotency_key:
        _invalid("Domain reservation key differs from its ORM row")
    if reservation.identity.request_payload_hash != row.reservation_request_hash:
        _invalid("Domain reservation digest differs from its ORM row")

    signal_id_value = intent.get("signal_id")
    if signal_id_value is not None and type(signal_id_value) is not int:
        _invalid("sealed intent signal id is invalid")
    settlement_lag = _nonnegative_int(
        snapshot.get("settlement_lag_sessions"),
        "sealed settlement lag",
    )
    return _ParentContext(
        reservation_id=reservation_id,
        account_id=account_id,
        owner_user_id=owner_user_id,
        idempotency_key=_text(row.idempotency_key, "reservation key"),
        intent_payload_hash=_text(row.intent_payload_hash, "intent hash"),
        reservation_request_hash=_text(row.reservation_request_hash, "reservation hash"),
        plan_snapshot_hash=_text(row.plan_snapshot_hash, "plan hash"),
        security_id=_text(row.security_id, "security id"),
        asset_code=_text(row.asset_code, "asset code"),
        asset_name=_text(row.asset_name, "asset name"),
        asset_type=_text(row.asset_type, "asset type"),
        market=_text(row.market, "market"),
        board=_text(row.board, "board"),
        side=_text(row.side, "side"),
        quantity=reservation.quantity,
        filled_quantity=reservation.filled_quantity,
        limit_price=reservation.limit_price,
        reserved_at=reservation.reserved_at,
        market_session=_date(snapshot.get("market_session"), "sealed market session"),
        settlement_exchange=_text(calendar_snapshot.get("exchange"), "sealed exchange"),
        settlement_lag_sessions=settlement_lag,
        settlement_bundle_id=_text(snapshot.get("settlement_bundle_id"), "bundle id"),
        settlement_bundle_version=_text(
            snapshot.get("settlement_bundle_version"),
            "bundle version",
        ),
        settlement_bundle_hash=_text(snapshot.get("settlement_bundle_hash"), "bundle hash"),
        settlement_policy_id=_text(snapshot.get("settlement_policy_id"), "policy id"),
        settlement_policy_version=_text(
            snapshot.get("settlement_policy_version"),
            "policy version",
        ),
        settlement_policy_hash=_text(snapshot.get("settlement_policy_hash"), "policy hash"),
        execution_rule_v2_hash=_text(
            snapshot.get("execution_rule_v2_hash"),
            "execution rule hash",
        ),
        reason=_text(intent.get("reason"), "sealed intent reason", allow_empty=True),
        signal_id=signal_id_value,
        fee_policy=fee_policy,
    )


def _decode_receipt_snapshot(
    *,
    parent: _ParentContext,
    receipt: SimulatedOrderFillReceiptModel,
) -> tuple[EncodedOrderReservationFillSnapshot, DecodedOrderReservationFillSnapshot]:
    """Rebuild the canonical snapshot DTO from one already-loaded receipt row."""

    if type(receipt) is not SimulatedOrderFillReceiptModel:
        _invalid("receipt row has an unexpected model type")
    _same(receipt.reservation_id, parent.reservation_id, "receipt parent id")
    _positive_int(receipt.pk, "receipt id")
    if type(receipt.receipt_version) is not int or receipt.receipt_version not in (1, 2):
        _invalid("receipt version is unsupported")
    if receipt.receipt_version == 1:
        if receipt.initial_position_mark_evidence is not None:
            _invalid("version one receipt contains initial-position mark evidence")
        mark_json: str | None = None
    else:
        mark_json = _canonical_json_field(
            receipt.initial_position_mark_evidence,
            "initial-position mark evidence",
        )
    encoded = EncodedOrderReservationFillSnapshot(
        reservation_id=parent.reservation_id,
        fill_sequence=_positive_int(receipt.fill_sequence, "fill sequence"),
        source_namespace=_text(receipt.source_namespace, "source namespace"),
        source_version=_text(receipt.source_version, "source version"),
        source_event_id=_text(receipt.source_event_id, "source event id"),
        plan_snapshot_hash=_text(receipt.plan_snapshot_hash, "receipt plan hash"),
        source_event_payload_hash=_text(
            receipt.source_event_payload_hash,
            "external event hash",
        ),
        source_event_snapshot_hash=_text(
            receipt.source_event_snapshot_hash,
            "local event snapshot hash",
        ),
        economic_request_hash=_text(receipt.economic_request_hash, "economic request hash"),
        economics_snapshot_hash=_text(
            receipt.economics_snapshot_hash,
            "economics snapshot hash",
        ),
        receipt_hash=_text(receipt.receipt_hash, "receipt hash"),
        source_event_snapshot_json=_canonical_json_field(
            receipt.source_event_payload,
            "source event payload",
        ),
        economics_snapshot_json=_canonical_json_field(
            receipt.economics_payload,
            "economics payload",
        ),
        receipt_version=receipt.receipt_version,
        initial_position_mark_evidence_json=mark_json,
    )
    decoded = decode_order_reservation_fill_snapshot(encoded)
    _same(receipt.receipt_version, decoded.receipt_version, "receipt version")
    decoded_mark = decoded.initial_position_mark_evidence
    expected_mark = None if decoded_mark is None else decoded_mark.to_payload()
    _same(
        receipt.initial_position_mark_evidence,
        expected_mark,
        "initial-position mark evidence",
    )
    _same(receipt.event_kind, decoded.event.event_kind.value, "receipt event kind")
    _same(receipt.source_namespace, decoded.source_namespace, "receipt source namespace")
    _same(receipt.source_version, decoded.source_version, "receipt source version")
    _same(receipt.source_event_id, decoded.source_event_id, "receipt source event id")
    _same(receipt.plan_snapshot_hash, decoded.plan_snapshot_hash, "receipt plan hash")
    _same(
        receipt.source_event_payload_hash,
        decoded.source_event_payload_hash,
        "receipt external event hash",
    )
    _same(
        receipt.source_event_snapshot_hash,
        decoded.source_event_snapshot_hash,
        "receipt local event snapshot hash",
    )
    _same(receipt.economic_request_hash, decoded.economic_request_hash, "receipt request hash")
    _same(
        receipt.economics_snapshot_hash,
        decoded.economics_snapshot_hash,
        "receipt economics snapshot hash",
    )
    _same(receipt.receipt_hash, decoded.receipt_hash, "receipt hash")
    return encoded, decoded


def _validate_parent_binding(
    *,
    parent: _ParentContext,
    decoded: DecodedOrderReservationFillSnapshot,
    proof: OrderFillSettlementProof,
    fill_sequence: int,
) -> None:
    """Tie each individually valid receipt and proof back to the sealed order."""

    event = decoded.event
    economics = decoded.economics
    _same(decoded.reservation_id, parent.reservation_id, "snapshot reservation id")
    _same(decoded.plan_snapshot_hash, parent.plan_snapshot_hash, "snapshot parent plan hash")
    _same(event.account_id, parent.account_id, "event account id")
    _same(event.user_id, parent.owner_user_id, "event owner id")
    _same(event.order_idempotency_key, parent.idempotency_key, "event order key")
    _same(event.intent_payload_hash, parent.intent_payload_hash, "event intent hash")
    _same(event.reservation_request_hash, parent.reservation_request_hash, "event reservation hash")
    _same(event.security_id, parent.security_id, "event security id")
    _same(event.asset_code, parent.asset_code, "event asset code")
    _same(event.side.value, parent.side, "event side")
    _same(economics.reservation_identity.account_id, parent.account_id, "economics account id")
    _same(
        economics.reservation_identity.security_id,
        parent.security_id,
        "economics security id",
    )
    _same(
        economics.reservation_identity.idempotency_key,
        parent.idempotency_key,
        "economics order key",
    )
    _same(
        economics.reservation_identity.request_payload_hash,
        parent.reservation_request_hash,
        "economics reservation hash",
    )
    _same(economics.user_id, parent.owner_user_id, "economics owner id")
    _same(economics.intent_payload_hash, parent.intent_payload_hash, "economics intent hash")
    _same(economics.side.value, parent.side, "economics side")
    _same(economics.asset_code, parent.asset_code, "economics asset code")
    _same(economics.asset_type, parent.asset_type, "economics asset type")
    _same(economics.market, parent.market, "economics market")
    _same(economics.board, parent.board, "economics board")
    _same(economics.limit_price, parent.limit_price, "economics limit price")
    _same(economics.prior.fill_count + 1, fill_sequence, "fill sequence and prior count")
    _same(economics.cumulative_state.fill_count, fill_sequence, "cumulative fill count")
    if economics.cumulative_state.cumulative_quantity > parent.quantity:
        _invalid("fill economics exceed the sealed order quantity")
    if economics.cumulative_state.cumulative_quantity > parent.filled_quantity:
        _invalid("fill cumulative quantity exceeds the current reservation row")

    policy = parent.fee_policy
    _same(economics.fee_policy_hash, policy.content_hash, "economics FeeV2 hash")
    prior = economics.prior
    if prior.fill_count == 0:
        _same(prior.cumulative_quantity, Decimal("0.000000"), "initial prior quantity")
        _same(prior.cumulative_gross, Decimal("0.00"), "initial prior gross")
        _same(
            prior.cumulative_fees,
            TradeFeeBreakdown(
                commission=Decimal("0.00"),
                transfer_fee=Decimal("0.00"),
                stamp_duty=Decimal("0.00"),
                slippage=Decimal("0.00"),
                total_fee=Decimal("0.00"),
            ),
            "initial prior fees",
        )
        prior_fees = prior.cumulative_fees
    else:
        prior_fees = policy.calculate_for(
            asset_type=parent.asset_type,
            market=parent.market,
            board=parent.board,
            side=economics.side,
            amount=prior.cumulative_gross,
            as_of=parent.reserved_at,
        )
        _same(prior.cumulative_fees, prior_fees, "prior FeeV2 cumulative fees")
    expected_cumulative_fees = policy.calculate_for(
        asset_type=parent.asset_type,
        market=parent.market,
        board=parent.board,
        side=economics.side,
        amount=economics.cumulative_state.cumulative_gross,
        as_of=parent.reserved_at,
    )
    _same(
        economics.cumulative_state.cumulative_fees,
        expected_cumulative_fees,
        "cumulative FeeV2 fees",
    )
    with localcontext() as context:
        context.prec = 80
        expected_incremental_fees = TradeFeeBreakdown(
            commission=(expected_cumulative_fees.commission - prior_fees.commission),
            transfer_fee=(expected_cumulative_fees.transfer_fee - prior_fees.transfer_fee),
            stamp_duty=(expected_cumulative_fees.stamp_duty - prior_fees.stamp_duty),
            slippage=(expected_cumulative_fees.slippage - prior_fees.slippage),
            total_fee=(expected_cumulative_fees.total_fee - prior_fees.total_fee),
        )
    _same(
        economics.incremental_fees,
        expected_incremental_fees,
        "incremental FeeV2 fees",
    )
    _same(proof.fill_occurred_at, event.occurred_at, "proof event clock")
    _same(proof.fill_occurred_at, economics.fill_occurred_at, "proof economics clock")
    if proof.fill_occurred_at < parent.reserved_at:
        _invalid("fill event predates its sealed reservation")
    _same(proof.settlement_exchange, parent.settlement_exchange, "proof sealed exchange")
    _same(
        proof.calendar_evidence.snapshot.exchange,
        parent.settlement_exchange,
        "proof calendar exchange",
    )
    _same(proof.settlement_lag_sessions, parent.settlement_lag_sessions, "proof sealed lag")


def _validate_trade_row(
    *,
    parent: _ParentContext,
    receipt: SimulatedOrderFillReceiptModel,
    trade: SimulatedTradeModel,
    decoded: DecodedOrderReservationFillSnapshot,
    proof: OrderFillSettlementProof,
    binding_hash: str,
) -> str:
    """Check every Trade field duplicated by the fill, parent, or proof."""

    trade_id = _positive_int(trade.pk, "trade id")
    _same(receipt.trade_id, trade_id, "receipt Trade id")
    expected_key = simulated_order_fill_trade_key(
        reservation_id=parent.reservation_id,
        source_namespace=decoded.source_namespace,
        fill_event_id=decoded.source_event_id,
    )
    _same(trade.account_id, parent.account_id, "Trade account id")
    _same(trade.idempotency_key, expected_key, "stable per-fill Trade key")
    _same(trade.request_payload_hash, decoded.receipt_hash, "Trade receipt hash")
    _same(trade.settlement_plan_binding_version, 4, "Trade binding version")
    _same(trade.settlement_plan_binding_hash, binding_hash, "Trade V4 binding hash")
    _same(trade.status, "executed", "Trade execution status")
    _same(trade.asset_code, parent.asset_code, "Trade asset code")
    _same(trade.asset_name, parent.asset_name, "Trade asset name")
    _same(trade.asset_type, parent.asset_type, "Trade asset type")
    _same(trade.action, parent.side, "Trade side")
    _same(trade.reason, parent.reason, "Trade reason")
    _same(trade.signal_id, parent.signal_id, "Trade signal id")
    _same(trade.order_date, parent.market_session, "Trade original order session")
    _same(trade.execution_date, proof.fill_market_session, "Trade fill session")
    _same(trade.execution_time, decoded.event.occurred_at, "Trade fill event clock")
    economics = decoded.economics
    fees = economics.incremental_fees
    _same(trade.quantity, economics.quantity, "Trade fill quantity")
    _same(trade.price, economics.price, "Trade fill price")
    _same(trade.amount, economics.gross_amount, "Trade fill gross")
    _same(trade.commission, fees.commission, "Trade commission")
    _same(trade.transfer_fee, fees.transfer_fee, "Trade transfer fee")
    _same(trade.stamp_duty, fees.stamp_duty, "Trade stamp duty")
    _same(trade.slippage, fees.slippage, "Trade slippage")
    if economics.side.value == "buy":
        with localcontext() as context:
            context.prec = 80
            expected_total_cost = economics.gross_amount + fees.total_fee
    else:
        expected_total_cost = fees.total_fee
    _same(trade.total_cost, expected_total_cost, "Trade total cost")
    _same(trade.fee_amounts_known, True, "Trade complete-fee knowledge")
    _same(trade.settlement_security_id, parent.security_id, "Trade settlement security")
    _same(trade.settlement_market, parent.market, "Trade settlement market")
    _same(trade.settlement_exchange, proof.settlement_exchange, "Trade settlement exchange")
    _same(trade.settlement_board, parent.board, "Trade settlement board")
    _same(trade.settlement_market_session, proof.fill_market_session, "Trade settlement session")
    _same(
        trade.settlement_lag_sessions,
        proof.settlement_lag_sessions,
        "Trade settlement lag",
    )
    if economics.side.value == "buy":
        if type(trade.settlement_status) is not str or trade.settlement_status not in (
            "pending",
            "released",
        ):
            _invalid("BUY Trade settlement status is missing or unknown")
        if (
            proof.expected_release_session == proof.fill_market_session
            and trade.settlement_status != "released"
        ):
            _invalid("same-session BUY settlement must already be released")
        _same(
            trade.settlement_release_date,
            proof.expected_release_session,
            "BUY Trade expected release session",
        )
    else:
        _same(trade.settlement_status, None, "SELL Trade has no pending share settlement")
        _same(trade.settlement_release_date, None, "SELL Trade release-date semantics")

    schedule = parent.fee_policy.fee_schedule_v1
    _same(trade.fee_config_id, schedule.config_id, "Trade fee config id")
    _same(trade.fee_schedule_hash, parent.fee_policy.content_hash, "Trade fee policy hash")
    actual_fee_snapshot = _canonical_json_field(
        trade.fee_schedule_snapshot,
        "Trade FeeV2 snapshot",
    )
    expected_fee_snapshot = _canonical_json_field(
        parent.fee_policy.to_payload(),
        "sealed FeeV2 snapshot",
    )
    _same(actual_fee_snapshot, expected_fee_snapshot, "Trade FeeV2 snapshot")
    _same(
        trade.fee_precision_basis,
        schedule.precision_basis.value,
        "Trade fee precision basis",
    )
    _same(
        trade.fee_calculation_purpose,
        schedule.calculation_purpose.value,
        "Trade fee calculation purpose",
    )
    _same(
        trade.fee_rounding_policy,
        schedule.rounding_policy.value,
        "Trade fee rounding policy",
    )
    _same(trade.settlement_bundle_id, parent.settlement_bundle_id, "Trade bundle id")
    _same(trade.settlement_bundle_version, parent.settlement_bundle_version, "Trade bundle version")
    _same(trade.settlement_bundle_hash, parent.settlement_bundle_hash, "Trade bundle hash")
    _same(trade.settlement_policy_id, parent.settlement_policy_id, "Trade settlement policy id")
    _same(
        trade.settlement_policy_version,
        parent.settlement_policy_version,
        "Trade settlement policy version",
    )
    _same(
        trade.settlement_policy_hash, parent.settlement_policy_hash, "Trade settlement policy hash"
    )
    _same(trade.execution_rule_v2_hash, parent.execution_rule_v2_hash, "Trade execution rule hash")

    evidence = proof.calendar_evidence
    publication = evidence.publication
    if publication is None:
        _invalid("fill proof has no formal publication")
    _same(
        trade.settlement_calendar_snapshot_id,
        evidence.snapshot.snapshot_id,
        "Trade calendar snapshot",
    )
    _same(
        trade.settlement_calendar_content_hash,
        evidence.snapshot.content_hash,
        "Trade calendar content hash",
    )
    _same(
        trade.settlement_calendar_record_digest,
        evidence.snapshot.record_digest,
        "Trade calendar record digest",
    )
    _same(
        trade.settlement_calendar_publication_id,
        publication.publication_id,
        "Trade calendar publication",
    )
    _same(
        trade.settlement_calendar_publication_hash,
        publication.publication_hash,
        "Trade calendar publication hash",
    )
    _same(
        trade.settlement_calendar_policy_hash, publication.policy_hash, "Trade calendar policy hash"
    )
    _same(
        trade.settlement_calendar_evidence_hash,
        evidence.evidence_hash,
        "Trade calendar evidence hash",
    )
    _same(trade.settlement_calendar_timezone, publication.timezone_name, "Trade calendar timezone")
    return expected_key


def _validate_release_calendar_mirrors(
    *,
    trade: SimulatedTradeModel,
    evidence: ExecutionCalendarEvidence,
) -> None:
    """Bind every duplicated release-calendar column to full typed evidence."""

    if type(evidence) is not ExecutionCalendarEvidence:
        _invalid("release calendar evidence has an unexpected type")
    snapshot = evidence.snapshot
    publication = evidence.publication
    if publication is None:
        _invalid("release calendar has no formal publication")
    _same(
        trade.settlement_release_calendar_snapshot_id,
        snapshot.snapshot_id,
        "Trade release calendar snapshot",
    )
    _same(
        trade.settlement_release_calendar_content_hash,
        snapshot.content_hash,
        "Trade release calendar content hash",
    )
    _same(
        trade.settlement_release_calendar_record_digest,
        snapshot.record_digest,
        "Trade release calendar record digest",
    )
    _same(
        trade.settlement_release_calendar_publication_id,
        publication.publication_id,
        "Trade release calendar publication",
    )
    _same(
        trade.settlement_release_calendar_publication_hash,
        publication.publication_hash,
        "Trade release calendar publication hash",
    )
    _same(
        trade.settlement_release_calendar_policy_hash,
        publication.policy_hash,
        "Trade release calendar policy hash",
    )
    _same(
        trade.settlement_release_calendar_evidence_hash,
        evidence.evidence_hash,
        "Trade release calendar evidence hash",
    )
    _same(
        trade.settlement_release_calendar_timezone,
        publication.timezone_name,
        "Trade release calendar timezone",
    )


def _require_release_mirrors_absent(trade: SimulatedTradeModel) -> None:
    """Require a pending BUY or SELL to carry no release claim or mirror."""

    _same(trade.settlement_released_at, None, "Trade release clock is absent")
    _same(trade.settlement_release_session, None, "Trade release session is absent")
    _same(
        trade.settlement_release_calendar_snapshot_id,
        None,
        "Trade release calendar snapshot is absent",
    )
    _same(
        trade.settlement_release_calendar_content_hash,
        None,
        "Trade release calendar content hash is absent",
    )
    _same(
        trade.settlement_release_calendar_record_digest,
        None,
        "Trade release calendar record digest is absent",
    )
    _same(
        trade.settlement_release_calendar_publication_id,
        None,
        "Trade release calendar publication is absent",
    )
    _same(
        trade.settlement_release_calendar_publication_hash,
        None,
        "Trade release calendar publication hash is absent",
    )
    _same(
        trade.settlement_release_calendar_policy_hash,
        None,
        "Trade release calendar policy hash is absent",
    )
    _same(
        trade.settlement_release_calendar_evidence_hash,
        None,
        "Trade release calendar evidence hash is absent",
    )
    _same(
        trade.settlement_release_calendar_timezone,
        None,
        "Trade release calendar timezone is absent",
    )


def _validate_release_time(
    *,
    released_at: object,
    trade: SimulatedTradeModel,
    decoded: DecodedOrderReservationFillSnapshot,
    fill_proof: OrderFillSettlementProof,
) -> datetime:
    """Require an aware release after the event, durable record, Trade, and read cutoff."""

    if type(released_at) is not datetime:
        _invalid("Trade release clock is missing or is not an exact datetime")
    if released_at.tzinfo is None or released_at.utcoffset() is None:
        _invalid("Trade release clock is not timezone-aware")
    if released_at < decoded.event.occurred_at:
        _invalid("Trade release predates the fill event")
    if released_at < decoded.event.recorded_at:
        _invalid("Trade release predates the durable fill event")
    if released_at < trade.execution_time:
        _invalid("Trade release predates the Trade execution clock")
    if released_at < fill_proof.calendar_read_cutoff:
        _invalid("Trade release predates the original fill calendar read cutoff")
    return released_at


def _validate_release_settlement(
    *,
    parent: _ParentContext,
    trade: SimulatedTradeModel,
    decoded: DecodedOrderReservationFillSnapshot,
    fill_proof: OrderFillSettlementProof,
) -> OrderFillSettlementReleaseProof | None:
    """Validate release proof state after the original V4 fill and Trade agree."""

    payload = trade.settlement_release_proof_payload
    stored_hash = trade.settlement_release_proof_hash
    has_payload = payload is not None
    has_hash = stored_hash is not None

    if decoded.economics.side.value == "sell":
        _same(has_payload, False, "SELL has no release proof payload")
        _same(has_hash, False, "SELL has no release proof hash")
        _require_release_mirrors_absent(trade)
        return None

    status = trade.settlement_status
    if status == "pending":
        _same(has_payload, False, "pending BUY has no release proof payload")
        _same(has_hash, False, "pending BUY has no release proof hash")
        _require_release_mirrors_absent(trade)
        return None
    if status != "released":
        _invalid("BUY release status is unknown")
    if has_payload != has_hash:
        _invalid("BUY release proof payload and hash must be stored together")

    released_at = _validate_release_time(
        released_at=trade.settlement_released_at,
        trade=trade,
        decoded=decoded,
        fill_proof=fill_proof,
    )
    if type(trade.settlement_release_session) is not date:
        _invalid("Trade release session is missing or is not an exact date")

    if not has_payload:
        if parent.settlement_lag_sessions != 0:
            _invalid("lagged V4 BUY is missing its release proof pair")
        _same(
            trade.settlement_release_session,
            fill_proof.fill_market_session,
            "legacy lag-zero release session",
        )
        _same(
            fill_proof.calendar_evidence.current_open_session(released_at),
            trade.settlement_release_session,
            "legacy lag-zero release-time calendar session",
        )
        _validate_release_calendar_mirrors(
            trade=trade,
            evidence=fill_proof.calendar_evidence,
        )
        return None

    release_proof = decode_order_fill_settlement_release_proof(
        payload,
        proof_hash=stored_hash,
    )
    _same(release_proof.trade_id, _positive_int(trade.pk, "Trade id"), "release proof Trade id")
    _same(
        release_proof.reservation_id,
        parent.reservation_id,
        "release proof reservation id",
    )
    _same(release_proof.account_id, parent.account_id, "release proof account id")
    _same(release_proof.user_id, parent.owner_user_id, "release proof owner id")
    _same(release_proof.receipt_hash, decoded.receipt_hash, "release proof receipt hash")
    _same(release_proof.security_id, parent.security_id, "release proof security id")
    _same(
        release_proof.settlement_exchange,
        fill_proof.settlement_exchange,
        "release proof exchange",
    )
    _same(
        release_proof.fill_market_session,
        fill_proof.fill_market_session,
        "release proof original fill session",
    )
    _same(
        release_proof.settlement_lag_sessions,
        parent.settlement_lag_sessions,
        "release proof stored lag",
    )
    _same(release_proof.released_at, released_at, "release proof clock")
    _same(
        release_proof.release_session,
        trade.settlement_release_session,
        "release proof session",
    )
    _validate_release_calendar_mirrors(
        trade=trade,
        evidence=release_proof.calendar_evidence,
    )
    return release_proof


def read_order_reservation_fill_row(
    *,
    reservation_row: SimulatedOrderReservationModel,
    receipt_row: SimulatedOrderFillReceiptModel,
    trade_row: SimulatedTradeModel,
) -> DecodedOrderReservationFillRow:
    """Reconcile three loaded rows without querying, writing, or deriving PnL.

    The caller supplies the exact Reservation, receipt, and Trade rows it has
    already loaded. This leaf validates their seals and duplicated fields, but
    it neither qualifies the source nor validates the full ordered FeeV2 chain.
    """

    if type(reservation_row) is not SimulatedOrderReservationModel:
        _invalid("reservation row has an unexpected model type")
    if type(receipt_row) is not SimulatedOrderFillReceiptModel:
        _invalid("receipt row has an unexpected model type")
    if type(trade_row) is not SimulatedTradeModel:
        _invalid("Trade row has an unexpected model type")
    if reservation_row.get_deferred_fields():
        _invalid("reservation row has deferred fields")
    if receipt_row.get_deferred_fields():
        _invalid("receipt row has deferred fields")
    if trade_row.get_deferred_fields():
        _invalid("Trade row has deferred fields")
    parent = _parent_context(reservation_row)
    encoded, decoded = _decode_receipt_snapshot(parent=parent, receipt=receipt_row)
    _same(receipt_row.trade_id, _positive_int(trade_row.pk, "Trade id"), "receipt Trade id")
    _same(receipt_row.reservation_id, parent.reservation_id, "receipt parent id")
    if receipt_row.source_namespace != encoded.source_namespace:
        _invalid("receipt namespace differs from its canonical snapshot")

    binding_payload = cast(object, trade_row.settlement_plan_binding_payload)
    binding = decode_order_reservation_fill_binding(
        payload=binding_payload,
        settlement_plan_binding_hash=cast(object, trade_row.settlement_plan_binding_hash),
        snapshot=encoded,
    )
    _validate_parent_binding(
        parent=parent,
        decoded=decoded,
        proof=binding.proof,
        fill_sequence=encoded.fill_sequence,
    )
    trade_key = _validate_trade_row(
        parent=parent,
        receipt=receipt_row,
        trade=trade_row,
        decoded=decoded,
        proof=binding.proof,
        binding_hash=binding.settlement_plan_binding_hash,
    )
    release_proof = _validate_release_settlement(
        parent=parent,
        trade=trade_row,
        decoded=decoded,
        fill_proof=binding.proof,
    )
    return DecodedOrderReservationFillRow(
        reservation_id=parent.reservation_id,
        receipt_id=_positive_int(receipt_row.pk, "receipt id"),
        trade_id=_positive_int(trade_row.pk, "Trade id"),
        fill_sequence=encoded.fill_sequence,
        trade_key=trade_key,
        receipt_hash=decoded.receipt_hash,
        event=decoded.event,
        economics=decoded.economics,
        proof=binding.proof,
        release_proof=release_proof,
    )


__all__: tuple[str, ...] = (
    "DecodedOrderReservationFillRow",
    "read_order_reservation_fill_row",
)
