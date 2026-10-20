"""Strict V4 binding between a verified receipt snapshot and a calendar proof.

The receipt/economics snapshot and the per-fill settlement proof have separate
hash roles. This leaf has no ORM, source adapter, writer, or public facade.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _hash_payload,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_calendar_codec import (
    decode_order_fill_settlement_proof,
    encode_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_snapshot_codec import (
    DecodedOrderReservationFillSnapshot,
    EncodedOrderReservationFillSnapshot,
    decode_order_reservation_fill_snapshot,
)

_BINDING_SCHEMA = "simulated-order-fill-binding.v4"
_BINDING_KEYS = (
    "schema",
    "reservation_id",
    "intent_payload_hash",
    "reservation_request_hash",
    "plan_snapshot_hash",
    "fee_policy_hash",
    "source_namespace",
    "source_version",
    "source_event_id",
    "fill_sequence",
    "side",
    "source_event_payload_hash",
    "source_event_snapshot_hash",
    "economic_request_hash",
    "economics_snapshot_hash",
    "receipt_hash",
    "fill_settlement_proof",
    "fill_settlement_proof_hash",
)
_MAX_BINDING_BYTES = 786_432


def _canonical_json(payload: dict[str, object]) -> str:
    """Serialize bounded JSON using the established Domain UTF-8 hash recipe."""

    try:
        serialized = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        payload_size = len(serialized.encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("V4 binding is not canonical JSON") from error
    if payload_size > _MAX_BINDING_BYTES:
        raise SimulatedSettlementContractError("V4 binding exceeds the configured size limit")
    return serialized


def _expect_object(
    value: object,
    *,
    field_names: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    """Narrow one JSON object and reject every missing or unknown key."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise SimulatedSettlementContractError(f"{label} must be a JSON object")
    payload = cast(dict[str, object], value)
    if frozenset(payload) != frozenset(field_names):
        raise SimulatedSettlementContractError(f"{label} fields are missing or unknown")
    return payload


def _require_hash(value: object, field_name: str) -> str:
    """Require a lowercase SHA-256 digest at a persisted JSON boundary."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SimulatedSettlementContractError(f"{field_name} must be a lowercase SHA-256 hash")
    return value


def _same_json_value(actual: object, expected: object) -> bool:
    """Compare JSON values with exact scalar types rather than Python coercion."""

    if type(actual) is not type(expected):
        return False
    if type(actual) is dict:
        actual_map = cast(dict[str, object], actual)
        expected_map = cast(dict[str, object], expected)
        return actual_map.keys() == expected_map.keys() and all(
            _same_json_value(actual_map[key], expected_map[key]) for key in actual_map
        )
    if type(actual) is list:
        actual_list = cast(list[object], actual)
        expected_list = cast(list[object], expected)
        return len(actual_list) == len(expected_list) and all(
            _same_json_value(left, right)
            for left, right in zip(actual_list, expected_list, strict=False)
        )
    return actual == expected


def _validated_snapshot(
    snapshot: object,
) -> DecodedOrderReservationFillSnapshot:
    """Use the frozen G2 snapshot codec to recover event and economics facts."""

    if type(snapshot) is not EncodedOrderReservationFillSnapshot:
        raise SimulatedSettlementContractError(
            "binding requires the exact encoded receipt snapshot"
        )
    return decode_order_reservation_fill_snapshot(snapshot)


def _validate_proof_for_snapshot(
    *,
    snapshot: DecodedOrderReservationFillSnapshot,
    proof: object,
) -> OrderFillSettlementProof:
    """Require the calendar proof's fill instant to be the original event instant."""

    if type(proof) is not OrderFillSettlementProof:
        raise SimulatedSettlementContractError(
            "binding requires the exact Domain fill settlement proof"
        )
    proof.validate()
    if proof.fill_occurred_at != snapshot.event.occurred_at:
        raise SimulatedSettlementContractError(
            "calendar proof fill instant differs from the immutable source event"
        )
    if proof.fill_occurred_at != snapshot.economics.fill_occurred_at:
        raise SimulatedSettlementContractError(
            "calendar proof fill instant differs from the immutable fill economics"
        )
    return proof


def _binding_payload(
    *,
    snapshot: DecodedOrderReservationFillSnapshot,
    proof: OrderFillSettlementProof,
) -> dict[str, object]:
    """Build all 16 storage locator fields and the independent calendar proof."""

    event = snapshot.event
    economics = snapshot.economics
    encoded_proof = encode_order_fill_settlement_proof(proof)
    return {
        "schema": _BINDING_SCHEMA,
        "reservation_id": snapshot.reservation_id,
        "intent_payload_hash": event.intent_payload_hash,
        "reservation_request_hash": event.reservation_request_hash,
        "plan_snapshot_hash": snapshot.plan_snapshot_hash,
        "fee_policy_hash": economics.fee_policy_hash,
        "source_namespace": snapshot.source_namespace,
        "source_version": snapshot.source_version,
        "source_event_id": snapshot.source_event_id,
        "fill_sequence": snapshot.fill_sequence,
        "side": event.side.value,
        "source_event_payload_hash": snapshot.source_event_payload_hash,
        "source_event_snapshot_hash": snapshot.source_event_snapshot_hash,
        "economic_request_hash": snapshot.economic_request_hash,
        "economics_snapshot_hash": snapshot.economics_snapshot_hash,
        "receipt_hash": snapshot.receipt_hash,
        "fill_settlement_proof": encoded_proof.to_payload(),
        "fill_settlement_proof_hash": encoded_proof.proof_hash,
    }


@dataclass(frozen=True, slots=True)
class OrderReservationFillBindingV4:
    """Fully checked binding value ready for persistence by a future writer."""

    snapshot: EncodedOrderReservationFillSnapshot
    proof: OrderFillSettlementProof
    settlement_plan_binding_hash: str

    def __post_init__(self) -> None:
        """Revalidate every source snapshot, proof link, and outer seal."""

        decoded = _validated_snapshot(self.snapshot)
        proof = _validate_proof_for_snapshot(snapshot=decoded, proof=self.proof)
        expected_payload = _binding_payload(snapshot=decoded, proof=proof)
        _canonical_json(expected_payload)
        supplied_hash = _require_hash(
            self.settlement_plan_binding_hash,
            "settlement_plan_binding_hash",
        )
        if _hash_payload(expected_payload) != supplied_hash:
            raise SimulatedSettlementContractError(
                "settlement plan binding hash differs from its complete V4 payload"
            )

    def to_payload(self) -> dict[str, object]:
        """Return a fresh exact V4 JSON object with proof and receipt roles intact."""

        decoded = _validated_snapshot(self.snapshot)
        proof = _validate_proof_for_snapshot(snapshot=decoded, proof=self.proof)
        payload = _binding_payload(snapshot=decoded, proof=proof)
        _canonical_json(payload)
        return payload


def encode_order_reservation_fill_binding(
    *,
    snapshot: EncodedOrderReservationFillSnapshot,
    proof: OrderFillSettlementProof,
) -> OrderReservationFillBindingV4:
    """Create V4 by binding a verified 667 receipt to a separate calendar proof."""

    decoded = _validated_snapshot(snapshot)
    checked_proof = _validate_proof_for_snapshot(snapshot=decoded, proof=proof)
    payload = _binding_payload(snapshot=decoded, proof=checked_proof)
    _canonical_json(payload)
    return OrderReservationFillBindingV4(
        snapshot=snapshot,
        proof=checked_proof,
        settlement_plan_binding_hash=_hash_payload(payload),
    )


def decode_order_reservation_fill_binding(
    *,
    payload: object,
    settlement_plan_binding_hash: object,
    snapshot: EncodedOrderReservationFillSnapshot,
) -> OrderReservationFillBindingV4:
    """Strictly decode V4 against the independently persisted full receipt snapshot."""

    if type(payload) is not dict or any(type(key) is not str for key in payload):
        raise SimulatedSettlementContractError("V4 binding must be a JSON object")
    payload_object = _expect_object(
        payload,
        field_names=_BINDING_KEYS,
        label="V4 binding",
    )
    _canonical_json(payload_object)
    decoded = _validated_snapshot(snapshot)
    proof = decode_order_fill_settlement_proof(payload_object["fill_settlement_proof"])
    checked_proof = _validate_proof_for_snapshot(snapshot=decoded, proof=proof)
    expected_payload = _binding_payload(snapshot=decoded, proof=checked_proof)
    if not _same_json_value(payload_object, expected_payload):
        raise SimulatedSettlementContractError(
            "V4 binding fields differ from the complete source/economics receipt"
        )
    supplied_hash = _require_hash(
        settlement_plan_binding_hash,
        "settlement_plan_binding_hash",
    )
    if _hash_payload(expected_payload) != supplied_hash:
        raise SimulatedSettlementContractError(
            "V4 outer hash differs from its complete canonical JSON"
        )
    return OrderReservationFillBindingV4(
        snapshot=snapshot,
        proof=checked_proof,
        settlement_plan_binding_hash=supplied_hash,
    )


__all__: tuple[str, ...] = (
    "OrderReservationFillBindingV4",
    "decode_order_reservation_fill_binding",
    "encode_order_reservation_fill_binding",
)
