"""Canonical typed snapshots and receipt seals for G2 fill persistence.

This codec serializes an Application source event and Domain fill economics. It
does not qualify or authenticate a source, validate a stored FeeV2 policy,
verify a complete persisted fill chain, or write a ledger. Its local snapshot
hashes are tamper-detection checksums, not signatures.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypedDict, cast

from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _decimal_from_text,
    _decimal_numeric_text,
    _require_aware,
    _require_hash,
    _require_token,
    _utc_text,
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeSide,
    TradeFeeBreakdown,
)
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof
from apps.simulated_trading.domain.order_reservation import (
    OrderReservationIdentity,
)
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillAccrual,
    OrderReservationFillEconomics,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_initial_position_mark_codec import (
    decode_initial_position_mark_evidence,
    encode_initial_position_mark_evidence,
)

_logger = logging.getLogger(__name__)
_EVENT_SCHEMA = "local-simulated-fill-event.v1"
_ECONOMICS_SCHEMA = "order-reservation-fill-economics.v1"
_RECEIPT_SCHEMA = "simulated-order-reservation-fill-receipt.v1"
_RECEIPT_V2_SCHEMA = "simulated-order-reservation-fill-receipt.v2"
_MAX_EVENT_ID_LENGTH = 128
_MAX_ORDER_KEY_LENGTH = 128
_MAX_NAMESPACE_LENGTH = 128
_MAX_SNAPSHOT_JSON_LENGTH = 262_144


class _ReservationIdentityPayload(TypedDict):
    account_id: int
    security_id: str
    idempotency_key: str
    request_payload_hash: str


class _FeeBreakdownPayload(TypedDict):
    commission: str
    transfer_fee: str
    stamp_duty: str
    slippage: str
    total_fee: str


class _AccrualPayload(TypedDict):
    fill_count: int
    cumulative_quantity: str
    cumulative_gross: str
    cumulative_fees: _FeeBreakdownPayload


class _EventPayload(TypedDict):
    schema: str
    source_namespace: str
    source_version: str
    source_event_id: str
    event_payload_hash: str
    source_snapshot_id: str
    source_snapshot_hash: str
    reservation_id: int
    account_id: int
    user_id: int
    order_idempotency_key: str
    intent_payload_hash: str
    reservation_request_hash: str
    plan_snapshot_hash: str
    security_id: str
    asset_code: str
    side: str
    event_kind: str
    quantity: str
    price: str
    occurred_at: str
    source_observed_at: str
    source_available_at: str
    recorded_at: str


class _EconomicsPayload(TypedDict):
    schema: str
    fill_event_id: str
    reservation_identity: _ReservationIdentityPayload
    user_id: int
    intent_payload_hash: str
    fee_policy_hash: str
    side: str
    asset_code: str
    asset_type: str
    market: str
    board: str
    limit_price: str
    fill_occurred_at: str
    close_order: bool
    quantity: str
    price: str
    gross_amount: str
    prior: _AccrualPayload
    cumulative_state: _AccrualPayload
    incremental_fees: _FeeBreakdownPayload
    payload_hash: str


class _ReceiptPayload(TypedDict):
    schema: str
    reservation_id: int
    fill_sequence: int
    source_namespace: str
    source_version: str
    source_event_id: str
    source_event_payload_hash: str
    source_event_snapshot_hash: str
    economic_request_hash: str
    economics_snapshot_hash: str
    intent_payload_hash: str
    fee_policy_hash: str
    plan_snapshot_hash: str
    account_id: int
    user_id: int
    order_idempotency_key: str
    security_id: str
    asset_code: str
    side: str


class _ReceiptV2Payload(TypedDict):
    schema: str
    receipt_version: int
    receipt: _ReceiptPayload
    initial_position_mark: dict[str, object]
    initial_position_mark_hash: str


@dataclass(frozen=True, slots=True)
class EncodedOrderReservationFillSnapshot:
    """Canonical JSON snapshots plus independently persisted locator/hash fields."""

    reservation_id: int
    fill_sequence: int
    source_namespace: str
    source_version: str
    source_event_id: str
    plan_snapshot_hash: str
    source_event_payload_hash: str
    source_event_snapshot_hash: str
    economic_request_hash: str
    economics_snapshot_hash: str
    receipt_hash: str
    source_event_snapshot_json: str
    economics_snapshot_json: str
    receipt_version: int = 1
    initial_position_mark_evidence_json: str | None = None

    def __post_init__(self) -> None:
        """Validate outer row fields without trusting their JSON contents."""

        _require_positive_int(self.reservation_id, "reservation_id")
        _require_positive_int(self.fill_sequence, "fill_sequence")
        _require_token(
            self.source_namespace,
            "source_namespace",
            max_length=_MAX_NAMESPACE_LENGTH,
        )
        _require_token(self.source_version, "source_version")
        _require_token(self.source_event_id, "source_event_id", max_length=_MAX_EVENT_ID_LENGTH)
        _require_hash(self.plan_snapshot_hash, "plan_snapshot_hash")
        _require_hash(self.source_event_payload_hash, "source_event_payload_hash")
        _require_hash(self.source_event_snapshot_hash, "source_event_snapshot_hash")
        _require_hash(self.economic_request_hash, "economic_request_hash")
        _require_hash(self.economics_snapshot_hash, "economics_snapshot_hash")
        _require_hash(self.receipt_hash, "receipt_hash")
        if type(self.receipt_version) is not int or self.receipt_version not in (1, 2):
            raise SimulatedSettlementContractError("receipt_version must be 1 or 2")
        if self.receipt_version == 1:
            if self.initial_position_mark_evidence_json is not None:
                raise SimulatedSettlementContractError(
                    "version one receipts cannot contain initial-position mark evidence"
                )
        elif (
            type(self.initial_position_mark_evidence_json) is not str
            or not self.initial_position_mark_evidence_json
            or len(self.initial_position_mark_evidence_json) > _MAX_SNAPSHOT_JSON_LENGTH
        ):
            raise SimulatedSettlementContractError(
                "version two receipts require bounded initial-position mark JSON"
            )
        for field_name, value in (
            ("source_event_snapshot_json", self.source_event_snapshot_json),
            ("economics_snapshot_json", self.economics_snapshot_json),
        ):
            if type(value) is not str or not value or len(value) > _MAX_SNAPSHOT_JSON_LENGTH:
                raise SimulatedSettlementContractError(
                    f"{field_name} must be a bounded nonempty JSON string"
                )


@dataclass(frozen=True, slots=True)
class DecodedOrderReservationFillSnapshot:
    """Validated typed event/economics with their immutable receipt metadata."""

    reservation_id: int
    fill_sequence: int
    source_namespace: str
    source_version: str
    source_event_id: str
    plan_snapshot_hash: str
    source_event_payload_hash: str
    source_event_snapshot_hash: str
    economic_request_hash: str
    economics_snapshot_hash: str
    receipt_hash: str
    event: LocalSimulatedFillEventV1
    economics: OrderReservationFillEconomics
    receipt_version: int = 1
    initial_position_mark_evidence: InitialPositionMarkProof | None = None


def _require_positive_int(value: object, field_name: str) -> int:
    """Require a positive literal integer, excluding bool and integer subclasses."""

    if type(value) is not int or value <= 0:
        raise SimulatedSettlementContractError(f"{field_name} must be a positive integer")
    return value


def _require_text(value: object, field_name: str) -> str:
    """Require one literal string at the JSON boundary."""

    if type(value) is not str:
        raise SimulatedSettlementContractError(f"{field_name} must be text")
    return value


def _require_int(value: object, field_name: str) -> int:
    """Require one literal integer at the JSON boundary."""

    if type(value) is not int:
        raise SimulatedSettlementContractError(f"{field_name} must be an integer")
    return value


def _require_bool(value: object, field_name: str) -> bool:
    """Require one literal boolean at the JSON boundary."""

    if type(value) is not bool:
        raise SimulatedSettlementContractError(f"{field_name} must be a boolean")
    return value


def _canonical_json(payload: Mapping[str, object]) -> str:
    """Serialize a typed mapping with one stable UTF-8 JSON representation."""

    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("snapshot is not canonical JSON") from error


def _sha256_text(value: str) -> str:
    """Hash canonical UTF-8 text using lowercase SHA-256 hex."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _wire_decimal_text(value: Decimal) -> str:
    """Use one canonical zero spelling while retaining the frozen helper's checks."""

    normalized = _decimal_numeric_text(value)
    return "0" if value.is_zero() else normalized


def _log_unknown_kind() -> None:
    """Log a fixed safe event-kind diagnostic without source identifiers."""

    _logger.warning(
        "Unknown local simulated fill event kind rejected by snapshot codec",
        extra={"code": "SIMULATED_FILL_EVENT_KIND_UNKNOWN"},
    )


def _validate_event(event: object) -> LocalSimulatedFillEventV1:
    """Validate every typed source-event field before serialization or receipt checks."""

    if type(event) is not LocalSimulatedFillEventV1:
        raise SimulatedSettlementContractError("fill event must be the exact typed Application DTO")
    try:
        _require_token(
            event.source_namespace,
            "source_namespace",
            max_length=_MAX_NAMESPACE_LENGTH,
        )
        _require_token(event.source_version, "source_version")
        _require_token(
            event.source_event_id,
            "source_event_id",
            max_length=_MAX_EVENT_ID_LENGTH,
        )
        _require_token(event.source_snapshot_id, "source_snapshot_id")
        _require_token(
            event.order_idempotency_key,
            "order_idempotency_key",
            max_length=_MAX_ORDER_KEY_LENGTH,
        )
        for field_name, token_value in (
            ("security_id", event.security_id),
            ("asset_code", event.asset_code),
        ):
            _require_token(token_value, field_name)
        for field_name, digest in (
            ("event_payload_hash", event.event_payload_hash),
            ("source_snapshot_hash", event.source_snapshot_hash),
            ("intent_payload_hash", event.intent_payload_hash),
            ("reservation_request_hash", event.reservation_request_hash),
            ("plan_snapshot_hash", event.plan_snapshot_hash),
        ):
            _require_hash(digest, field_name)
        for field_name, integer_value in (
            ("reservation_id", event.reservation_id),
            ("account_id", event.account_id),
            ("user_id", event.user_id),
        ):
            _require_positive_int(integer_value, field_name)
        if type(event.side) is not SimulatedTradeSide:
            raise SimulatedSettlementContractError("event side is invalid")
        if type(event.event_kind) is not LocalSimulatedFillEventKind:
            _log_unknown_kind()
            raise SimulatedSettlementContractError("event kind is unknown")
        if event.event_kind is LocalSimulatedFillEventKind.UNKNOWN:
            _log_unknown_kind()
            raise SimulatedSettlementContractError("event kind is unknown")
        if event.event_kind not in (
            LocalSimulatedFillEventKind.FILL,
            LocalSimulatedFillEventKind.FINAL_FILL,
        ):
            _log_unknown_kind()
            raise SimulatedSettlementContractError("event kind is unsupported")
        validate_ledger_quantity(event.quantity, "event.quantity", allow_zero=False)
        validate_ledger_price(event.price, "event.price", allow_zero=False)
        for field_name, clock_value in (
            ("occurred_at", event.occurred_at),
            ("source_observed_at", event.source_observed_at),
            ("source_available_at", event.source_available_at),
            ("recorded_at", event.recorded_at),
        ):
            if type(clock_value) is not datetime:
                raise SimulatedSettlementContractError(f"{field_name} is required")
            _require_aware(clock_value, field_name)
    except SimulatedSettlementContractError:
        raise
    except (ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("fill event fields are invalid") from error
    return event


def _validate_economics(economics: object) -> OrderReservationFillEconomics:
    """Revalidate exact Domain economics without claiming FeeV2 provenance."""

    if type(economics) is not OrderReservationFillEconomics:
        raise SimulatedSettlementContractError(
            "fill economics must be the exact typed Domain value"
        )
    try:
        economics.__post_init__()
    except SimulatedSettlementContractError:
        raise
    except (ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("fill economics are invalid") from error
    return economics


def _validate_pair(
    *,
    event: object,
    economics: object,
    reservation_id: object,
    fill_sequence: object,
    plan_snapshot_hash: object,
) -> tuple[LocalSimulatedFillEventV1, OrderReservationFillEconomics]:
    """Cross-check source event, economics, existing parent key and fill sequence."""

    checked_event = _validate_event(event)
    checked_economics = _validate_economics(economics)
    parent_id = _require_positive_int(reservation_id, "reservation_id")
    sequence = _require_positive_int(fill_sequence, "fill_sequence")
    _require_hash(plan_snapshot_hash, "plan_snapshot_hash")
    identity = checked_economics.reservation_identity
    if sequence != checked_economics.cumulative_state.fill_count:
        raise SimulatedSettlementContractError("fill sequence differs from cumulative economics")
    if (
        checked_event.reservation_id != parent_id
        or checked_event.plan_snapshot_hash != plan_snapshot_hash
        or checked_event.source_event_id != checked_economics.fill_event_id
        or checked_event.account_id != identity.account_id
        or checked_event.user_id != checked_economics.user_id
        or checked_event.order_idempotency_key != identity.idempotency_key
        or checked_event.intent_payload_hash != checked_economics.intent_payload_hash
        or checked_event.reservation_request_hash != identity.request_payload_hash
        or checked_event.security_id != identity.security_id
        or checked_event.asset_code != checked_economics.asset_code
        or checked_event.side is not checked_economics.side
        or checked_event.quantity != checked_economics.quantity
        or checked_event.price != checked_economics.price
        or checked_event.occurred_at != checked_economics.fill_occurred_at
        or checked_economics.close_order
        is not (checked_event.event_kind is LocalSimulatedFillEventKind.FINAL_FILL)
    ):
        raise SimulatedSettlementContractError(
            "source event differs from its immutable fill economics"
        )
    return checked_event, checked_economics


def _fee_payload(fees: TradeFeeBreakdown) -> _FeeBreakdownPayload:
    """Serialize all four fee components and their stored total."""

    return {
        "commission": _wire_decimal_text(fees.commission),
        "transfer_fee": _wire_decimal_text(fees.transfer_fee),
        "stamp_duty": _wire_decimal_text(fees.stamp_duty),
        "slippage": _wire_decimal_text(fees.slippage),
        "total_fee": _wire_decimal_text(fees.total_fee),
    }


def _accrual_payload(accrual: OrderReservationFillAccrual) -> _AccrualPayload:
    """Serialize explicit cumulative quantity, gross, and complete known fees."""

    return {
        "fill_count": accrual.fill_count,
        "cumulative_quantity": _wire_decimal_text(accrual.cumulative_quantity),
        "cumulative_gross": _wire_decimal_text(accrual.cumulative_gross),
        "cumulative_fees": _fee_payload(accrual.cumulative_fees),
    }


def _event_payload(event: LocalSimulatedFillEventV1) -> _EventPayload:
    """Build every typed source-event field, retaining its external raw digest."""

    return {
        "schema": _EVENT_SCHEMA,
        "source_namespace": event.source_namespace,
        "source_version": event.source_version,
        "source_event_id": event.source_event_id,
        "event_payload_hash": event.event_payload_hash,
        "source_snapshot_id": event.source_snapshot_id,
        "source_snapshot_hash": event.source_snapshot_hash,
        "reservation_id": event.reservation_id,
        "account_id": event.account_id,
        "user_id": event.user_id,
        "order_idempotency_key": event.order_idempotency_key,
        "intent_payload_hash": event.intent_payload_hash,
        "reservation_request_hash": event.reservation_request_hash,
        "plan_snapshot_hash": event.plan_snapshot_hash,
        "security_id": event.security_id,
        "asset_code": event.asset_code,
        "side": event.side.value,
        "event_kind": event.event_kind.value,
        "quantity": _wire_decimal_text(event.quantity),
        "price": _wire_decimal_text(event.price),
        "occurred_at": _utc_text(event.occurred_at),
        "source_observed_at": _utc_text(event.source_observed_at),
        "source_available_at": _utc_text(event.source_available_at),
        "recorded_at": _utc_text(event.recorded_at),
    }


def _economics_payload(economics: OrderReservationFillEconomics) -> _EconomicsPayload:
    """Serialize every immutable request and mutable accrued-economics field."""

    identity = economics.reservation_identity
    identity_payload: _ReservationIdentityPayload = {
        "account_id": identity.account_id,
        "security_id": identity.security_id,
        "idempotency_key": identity.idempotency_key,
        "request_payload_hash": identity.request_payload_hash,
    }
    return {
        "schema": _ECONOMICS_SCHEMA,
        "fill_event_id": economics.fill_event_id,
        "reservation_identity": identity_payload,
        "user_id": economics.user_id,
        "intent_payload_hash": economics.intent_payload_hash,
        "fee_policy_hash": economics.fee_policy_hash,
        "side": economics.side.value,
        "asset_code": economics.asset_code,
        "asset_type": economics.asset_type,
        "market": economics.market,
        "board": economics.board,
        "limit_price": _wire_decimal_text(economics.limit_price),
        "fill_occurred_at": _utc_text(economics.fill_occurred_at),
        "close_order": economics.close_order,
        "quantity": _wire_decimal_text(economics.quantity),
        "price": _wire_decimal_text(economics.price),
        "gross_amount": _wire_decimal_text(economics.gross_amount),
        "prior": _accrual_payload(economics.prior),
        "cumulative_state": _accrual_payload(economics.cumulative_state),
        "incremental_fees": _fee_payload(economics.incremental_fees),
        "payload_hash": economics.payload_hash,
    }


def _receipt_payload(
    *,
    reservation_id: int,
    fill_sequence: int,
    event: LocalSimulatedFillEventV1,
    economics: OrderReservationFillEconomics,
    source_event_payload_hash: str,
    source_event_snapshot_hash: str,
    economic_request_hash: str,
    economics_snapshot_hash: str,
    plan_snapshot_hash: str,
) -> _ReceiptPayload:
    """Bind stable parent, sequence, event, request, snapshots and plan identities."""

    return {
        "schema": _RECEIPT_SCHEMA,
        "reservation_id": reservation_id,
        "fill_sequence": fill_sequence,
        "source_namespace": event.source_namespace,
        "source_version": event.source_version,
        "source_event_id": event.source_event_id,
        "source_event_payload_hash": source_event_payload_hash,
        "source_event_snapshot_hash": source_event_snapshot_hash,
        "economic_request_hash": economic_request_hash,
        "economics_snapshot_hash": economics_snapshot_hash,
        "intent_payload_hash": economics.intent_payload_hash,
        "fee_policy_hash": economics.fee_policy_hash,
        "plan_snapshot_hash": plan_snapshot_hash,
        "account_id": event.account_id,
        "user_id": event.user_id,
        "order_idempotency_key": event.order_idempotency_key,
        "security_id": event.security_id,
        "asset_code": event.asset_code,
        "side": event.side.value,
    }


def _receipt_v2_payload(
    *,
    receipt: _ReceiptPayload,
    initial_position_mark: InitialPositionMarkProof,
) -> _ReceiptV2Payload:
    """Bind the original V1 receipt with a complete canonical mark proof."""

    return {
        "schema": _RECEIPT_V2_SCHEMA,
        "receipt_version": 2,
        "receipt": receipt,
        "initial_position_mark": initial_position_mark.to_payload(),
        "initial_position_mark_hash": initial_position_mark.proof_hash,
    }


def _validate_initial_position_mark(
    *,
    mark: object,
    event: LocalSimulatedFillEventV1,
    economics: OrderReservationFillEconomics,
) -> InitialPositionMarkProof:
    """Require a BUY mark read after event recording and matching its economics."""

    if type(mark) is not InitialPositionMarkProof:
        raise SimulatedSettlementContractError(
            "initial-position mark must be the exact typed Domain proof"
        )
    if economics.side is not SimulatedTradeSide.BUY:
        raise SimulatedSettlementContractError(
            "initial-position mark evidence is supported only for BUY fills"
        )
    if mark.read_at < event.recorded_at:
        raise SimulatedSettlementContractError(
            "initial-position mark was read before the source event was durably recorded"
        )
    identity = economics.reservation_identity
    mark.validate_for_instrument(
        security_id=identity.security_id,
        asset_code=economics.asset_code,
        asset_type=economics.asset_type,
        market=economics.market,
        board=economics.board,
        read_at=mark.read_at,
    )
    return mark


def encode_order_reservation_fill_snapshot(
    *,
    event: LocalSimulatedFillEventV1,
    economics: OrderReservationFillEconomics,
    reservation_id: int,
    fill_sequence: int,
    plan_snapshot_hash: str,
    initial_position_mark: InitialPositionMarkProof | None = None,
) -> EncodedOrderReservationFillSnapshot:
    """Create canonical full snapshots and a receipt seal before Trade insertion.

    reservation_id and fill_sequence are existing parent/ordering facts. The
    receipt hash intentionally excludes future Trade and receipt primary keys,
    preventing a Trade-to-receipt insertion cycle.
    """

    checked_event, checked_economics = _validate_pair(
        event=event,
        economics=economics,
        reservation_id=reservation_id,
        fill_sequence=fill_sequence,
        plan_snapshot_hash=plan_snapshot_hash,
    )
    event_json = _canonical_json(_event_payload(checked_event))
    economics_json = _canonical_json(_economics_payload(checked_economics))
    source_event_payload_hash = checked_event.event_payload_hash
    source_event_snapshot_hash = _sha256_text(event_json)
    economic_request_hash = checked_economics.payload_hash
    economics_snapshot_hash = _sha256_text(economics_json)
    receipt_payload = _receipt_payload(
        reservation_id=reservation_id,
        fill_sequence=fill_sequence,
        event=checked_event,
        economics=checked_economics,
        source_event_payload_hash=source_event_payload_hash,
        source_event_snapshot_hash=source_event_snapshot_hash,
        economic_request_hash=economic_request_hash,
        economics_snapshot_hash=economics_snapshot_hash,
        plan_snapshot_hash=plan_snapshot_hash,
    )
    receipt_version = 1
    mark_json: str | None = None
    if initial_position_mark is None:
        receipt_json = _canonical_json(receipt_payload)
    else:
        checked_mark = _validate_initial_position_mark(
            mark=initial_position_mark,
            event=checked_event,
            economics=checked_economics,
        )
        mark_json = encode_initial_position_mark_evidence(checked_mark)
        receipt_version = 2
        receipt_json = _canonical_json(
            _receipt_v2_payload(
                receipt=receipt_payload,
                initial_position_mark=checked_mark,
            )
        )
    return EncodedOrderReservationFillSnapshot(
        reservation_id=reservation_id,
        fill_sequence=fill_sequence,
        source_namespace=checked_event.source_namespace,
        source_version=checked_event.source_version,
        source_event_id=checked_event.source_event_id,
        plan_snapshot_hash=plan_snapshot_hash,
        source_event_payload_hash=source_event_payload_hash,
        source_event_snapshot_hash=source_event_snapshot_hash,
        economic_request_hash=economic_request_hash,
        economics_snapshot_hash=economics_snapshot_hash,
        receipt_hash=_sha256_text(receipt_json),
        source_event_snapshot_json=event_json,
        economics_snapshot_json=economics_json,
        receipt_version=receipt_version,
        initial_position_mark_evidence_json=mark_json,
    )


def _expect_object(
    value: object,
    *,
    field_names: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    """Narrow JSON Any to a string-key object with an exact schema field set."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise SimulatedSettlementContractError(f"{label} must be a JSON object")
    object_value = cast(dict[str, object], value)
    if frozenset(object_value) != frozenset(field_names):
        raise SimulatedSettlementContractError(f"{label} fields are missing or unknown")
    return object_value


def _load_canonical_object(
    text: object,
    *,
    field_names: tuple[str, ...],
    schema: str,
    label: str,
) -> dict[str, object]:
    """Parse bounded canonical JSON and reject duplicate, extra or absent keys."""

    if type(text) is not str or not text or len(text) > _MAX_SNAPSHOT_JSON_LENGTH:
        raise SimulatedSettlementContractError(f"{label} JSON is missing or oversized")
    try:
        raw_value: object = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(f"{label} JSON is invalid") from error
    payload = _expect_object(raw_value, field_names=field_names, label=label)
    if _canonical_json(payload) != text:
        raise SimulatedSettlementContractError(f"{label} JSON is not canonical")
    if payload.get("schema") != schema:
        raise SimulatedSettlementContractError(f"{label} schema is unsupported")
    return payload


def _parse_decimal(value: object, field_name: str) -> Decimal:
    """Parse exactly one canonical decimal string without float or scale fallback."""

    return _decimal_from_text(value, field_name)


def _parse_datetime(value: object, field_name: str) -> datetime:
    """Parse canonical aware UTC text and preserve its exact instant."""

    text = _require_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        _require_aware(parsed, field_name)
        if _utc_text(parsed) != text:
            raise SimulatedSettlementContractError(f"{field_name} is not canonical UTC text")
        return parsed.astimezone(UTC)
    except SimulatedSettlementContractError:
        raise
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(
            f"{field_name} is not an aware UTC instant"
        ) from error


def _parse_fees(value: object, field_name: str) -> TradeFeeBreakdown:
    """Decode every fee field explicitly; None is never treated as zero."""

    payload = _expect_object(
        value,
        field_names=("commission", "transfer_fee", "stamp_duty", "slippage", "total_fee"),
        label=field_name,
    )
    fees = TradeFeeBreakdown(
        commission=validate_ledger_money(
            _parse_decimal(payload["commission"], f"{field_name}.commission"),
            f"{field_name}.commission",
        ),
        transfer_fee=validate_ledger_money(
            _parse_decimal(payload["transfer_fee"], f"{field_name}.transfer_fee"),
            f"{field_name}.transfer_fee",
        ),
        stamp_duty=validate_ledger_money(
            _parse_decimal(payload["stamp_duty"], f"{field_name}.stamp_duty"),
            f"{field_name}.stamp_duty",
        ),
        slippage=validate_ledger_money(
            _parse_decimal(payload["slippage"], f"{field_name}.slippage"),
            f"{field_name}.slippage",
        ),
        total_fee=validate_ledger_money(
            _parse_decimal(payload["total_fee"], f"{field_name}.total_fee"),
            f"{field_name}.total_fee",
        ),
    )
    return fees


def _parse_accrual(value: object, field_name: str) -> OrderReservationFillAccrual:
    """Decode explicit fill count, quantity, gross and complete fee components."""

    payload = _expect_object(
        value,
        field_names=("fill_count", "cumulative_quantity", "cumulative_gross", "cumulative_fees"),
        label=field_name,
    )
    accrual = OrderReservationFillAccrual(
        fill_count=_require_int(payload["fill_count"], f"{field_name}.fill_count"),
        cumulative_quantity=validate_ledger_quantity(
            _parse_decimal(payload["cumulative_quantity"], f"{field_name}.cumulative_quantity"),
            f"{field_name}.cumulative_quantity",
        ),
        cumulative_gross=validate_ledger_money(
            _parse_decimal(payload["cumulative_gross"], f"{field_name}.cumulative_gross"),
            f"{field_name}.cumulative_gross",
        ),
        cumulative_fees=_parse_fees(payload["cumulative_fees"], f"{field_name}.cumulative_fees"),
    )
    accrual.__post_init__()
    return accrual


def _decode_event(text: object) -> LocalSimulatedFillEventV1:
    """Decode the complete event JSON into its exact Application DTO."""

    field_names = (
        "schema",
        "source_namespace",
        "source_version",
        "source_event_id",
        "event_payload_hash",
        "source_snapshot_id",
        "source_snapshot_hash",
        "reservation_id",
        "account_id",
        "user_id",
        "order_idempotency_key",
        "intent_payload_hash",
        "reservation_request_hash",
        "plan_snapshot_hash",
        "security_id",
        "asset_code",
        "side",
        "event_kind",
        "quantity",
        "price",
        "occurred_at",
        "source_observed_at",
        "source_available_at",
        "recorded_at",
    )
    payload = _load_canonical_object(
        text,
        field_names=field_names,
        schema=_EVENT_SCHEMA,
        label="source event",
    )
    try:
        side = SimulatedTradeSide(_require_text(payload["side"], "side"))
    except ValueError as error:
        raise SimulatedSettlementContractError("event side is unsupported") from error
    kind_text = payload["event_kind"]
    if type(kind_text) is not str:
        _log_unknown_kind()
        raise SimulatedSettlementContractError("event kind is unknown")
    try:
        event_kind = LocalSimulatedFillEventKind(kind_text)
    except ValueError as error:
        _log_unknown_kind()
        raise SimulatedSettlementContractError("event kind is unknown") from error
    event = LocalSimulatedFillEventV1(
        source_namespace=_require_text(payload["source_namespace"], "source_namespace"),
        source_version=_require_text(payload["source_version"], "source_version"),
        source_event_id=_require_text(payload["source_event_id"], "source_event_id"),
        event_payload_hash=_require_text(payload["event_payload_hash"], "event_payload_hash"),
        source_snapshot_id=_require_text(payload["source_snapshot_id"], "source_snapshot_id"),
        source_snapshot_hash=_require_text(payload["source_snapshot_hash"], "source_snapshot_hash"),
        reservation_id=_require_int(payload["reservation_id"], "reservation_id"),
        account_id=_require_int(payload["account_id"], "account_id"),
        user_id=_require_int(payload["user_id"], "user_id"),
        order_idempotency_key=_require_text(
            payload["order_idempotency_key"], "order_idempotency_key"
        ),
        intent_payload_hash=_require_text(payload["intent_payload_hash"], "intent_payload_hash"),
        reservation_request_hash=_require_text(
            payload["reservation_request_hash"], "reservation_request_hash"
        ),
        plan_snapshot_hash=_require_text(payload["plan_snapshot_hash"], "plan_snapshot_hash"),
        security_id=_require_text(payload["security_id"], "security_id"),
        asset_code=_require_text(payload["asset_code"], "asset_code"),
        side=side,
        event_kind=event_kind,
        quantity=validate_ledger_quantity(
            _parse_decimal(payload["quantity"], "quantity"),
            "quantity",
            allow_zero=False,
        ),
        price=validate_ledger_price(
            _parse_decimal(payload["price"], "price"),
            "price",
            allow_zero=False,
        ),
        occurred_at=_parse_datetime(payload["occurred_at"], "occurred_at"),
        source_observed_at=_parse_datetime(payload["source_observed_at"], "source_observed_at"),
        source_available_at=_parse_datetime(payload["source_available_at"], "source_available_at"),
        recorded_at=_parse_datetime(payload["recorded_at"], "recorded_at"),
    )
    return _validate_event(event)


def _decode_identity(value: object) -> OrderReservationIdentity:
    """Decode one sealed Reservation identity from a strict nested JSON object."""

    payload = _expect_object(
        value,
        field_names=("account_id", "security_id", "idempotency_key", "request_payload_hash"),
        label="reservation identity",
    )
    identity = OrderReservationIdentity(
        account_id=_require_int(payload["account_id"], "reservation_identity.account_id"),
        security_id=_require_text(payload["security_id"], "reservation_identity.security_id"),
        idempotency_key=_require_text(
            payload["idempotency_key"], "reservation_identity.idempotency_key"
        ),
        request_payload_hash=_require_text(
            payload["request_payload_hash"], "reservation_identity.request_payload_hash"
        ),
    )
    identity.__post_init__()
    return identity


def _decode_economics(text: object) -> OrderReservationFillEconomics:
    """Decode all immutable request fields, prior state, cumulative state and fees."""

    field_names = (
        "schema",
        "fill_event_id",
        "reservation_identity",
        "user_id",
        "intent_payload_hash",
        "fee_policy_hash",
        "side",
        "asset_code",
        "asset_type",
        "market",
        "board",
        "limit_price",
        "fill_occurred_at",
        "close_order",
        "quantity",
        "price",
        "gross_amount",
        "prior",
        "cumulative_state",
        "incremental_fees",
        "payload_hash",
    )
    payload = _load_canonical_object(
        text,
        field_names=field_names,
        schema=_ECONOMICS_SCHEMA,
        label="fill economics",
    )
    try:
        side = SimulatedTradeSide(_require_text(payload["side"], "economics.side"))
    except ValueError as error:
        raise SimulatedSettlementContractError("economics side is unsupported") from error
    economics = OrderReservationFillEconomics(
        fill_event_id=_require_text(payload["fill_event_id"], "fill_event_id"),
        reservation_identity=_decode_identity(payload["reservation_identity"]),
        user_id=_require_int(payload["user_id"], "user_id"),
        intent_payload_hash=_require_text(payload["intent_payload_hash"], "intent_payload_hash"),
        fee_policy_hash=_require_text(payload["fee_policy_hash"], "fee_policy_hash"),
        side=side,
        asset_code=_require_text(payload["asset_code"], "asset_code"),
        asset_type=_require_text(payload["asset_type"], "asset_type"),
        market=_require_text(payload["market"], "market"),
        board=_require_text(payload["board"], "board"),
        limit_price=validate_ledger_price(
            _parse_decimal(payload["limit_price"], "limit_price"), "limit_price", allow_zero=False
        ),
        fill_occurred_at=_parse_datetime(payload["fill_occurred_at"], "fill_occurred_at"),
        close_order=_require_bool(payload["close_order"], "close_order"),
        quantity=validate_ledger_quantity(
            _parse_decimal(payload["quantity"], "quantity"), "quantity", allow_zero=False
        ),
        price=validate_ledger_price(
            _parse_decimal(payload["price"], "price"), "price", allow_zero=False
        ),
        gross_amount=validate_ledger_money(
            _parse_decimal(payload["gross_amount"], "gross_amount"),
            "gross_amount",
            allow_zero=False,
        ),
        prior=_parse_accrual(payload["prior"], "prior"),
        cumulative_state=_parse_accrual(payload["cumulative_state"], "cumulative_state"),
        incremental_fees=_parse_fees(payload["incremental_fees"], "incremental_fees"),
        payload_hash=_require_text(payload["payload_hash"], "payload_hash"),
    )
    return _validate_economics(economics)


def decode_order_reservation_fill_snapshot(
    snapshot: object,
) -> DecodedOrderReservationFillSnapshot:
    """Recompute and cross-check every snapshot, request, locator and receipt hash."""

    if type(snapshot) is not EncodedOrderReservationFillSnapshot:
        raise SimulatedSettlementContractError("fill snapshot must be the exact encoded DTO")
    snapshot.__post_init__()
    event = _decode_event(snapshot.source_event_snapshot_json)
    economics = _decode_economics(snapshot.economics_snapshot_json)
    _validate_pair(
        event=event,
        economics=economics,
        reservation_id=snapshot.reservation_id,
        fill_sequence=snapshot.fill_sequence,
        plan_snapshot_hash=snapshot.plan_snapshot_hash,
    )
    if (
        snapshot.source_namespace != event.source_namespace
        or snapshot.source_version != event.source_version
        or snapshot.source_event_id != event.source_event_id
        or snapshot.source_event_payload_hash != event.event_payload_hash
        or snapshot.economic_request_hash != economics.payload_hash
    ):
        raise SimulatedSettlementContractError("snapshot locator or request hash differs from JSON")
    event_json = _canonical_json(_event_payload(event))
    economics_json = _canonical_json(_economics_payload(economics))
    source_event_snapshot_hash = _sha256_text(event_json)
    economics_snapshot_hash = _sha256_text(economics_json)
    if (
        event_json != snapshot.source_event_snapshot_json
        or economics_json != snapshot.economics_snapshot_json
        or source_event_snapshot_hash != snapshot.source_event_snapshot_hash
        or economics_snapshot_hash != snapshot.economics_snapshot_hash
    ):
        raise SimulatedSettlementContractError(
            "full typed snapshot hash does not match stored JSON"
        )
    receipt_payload = _receipt_payload(
        reservation_id=snapshot.reservation_id,
        fill_sequence=snapshot.fill_sequence,
        event=event,
        economics=economics,
        source_event_payload_hash=snapshot.source_event_payload_hash,
        source_event_snapshot_hash=snapshot.source_event_snapshot_hash,
        economic_request_hash=snapshot.economic_request_hash,
        economics_snapshot_hash=snapshot.economics_snapshot_hash,
        plan_snapshot_hash=snapshot.plan_snapshot_hash,
    )
    mark: InitialPositionMarkProof | None = None
    if snapshot.receipt_version == 1:
        receipt_json = _canonical_json(receipt_payload)
    else:
        mark = decode_initial_position_mark_evidence(snapshot.initial_position_mark_evidence_json)
        mark = _validate_initial_position_mark(mark=mark, event=event, economics=economics)
        receipt_json = _canonical_json(
            _receipt_v2_payload(
                receipt=receipt_payload,
                initial_position_mark=mark,
            )
        )
    if _sha256_text(receipt_json) != snapshot.receipt_hash:
        raise SimulatedSettlementContractError("receipt hash differs from its canonical envelope")
    return DecodedOrderReservationFillSnapshot(
        reservation_id=snapshot.reservation_id,
        fill_sequence=snapshot.fill_sequence,
        source_namespace=snapshot.source_namespace,
        source_version=snapshot.source_version,
        source_event_id=snapshot.source_event_id,
        plan_snapshot_hash=snapshot.plan_snapshot_hash,
        source_event_payload_hash=snapshot.source_event_payload_hash,
        source_event_snapshot_hash=snapshot.source_event_snapshot_hash,
        economic_request_hash=snapshot.economic_request_hash,
        economics_snapshot_hash=snapshot.economics_snapshot_hash,
        receipt_hash=snapshot.receipt_hash,
        event=event,
        economics=economics,
        receipt_version=snapshot.receipt_version,
        initial_position_mark_evidence=mark,
    )


__all__: tuple[str, ...] = (
    "DecodedOrderReservationFillSnapshot",
    "EncodedOrderReservationFillSnapshot",
    "decode_order_reservation_fill_snapshot",
    "encode_order_reservation_fill_snapshot",
)
