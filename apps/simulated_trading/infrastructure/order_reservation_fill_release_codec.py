"""Strictly encode and decode immutable V4 pending-settlement release proof."""

from __future__ import annotations

import json
from dataclasses import dataclass

from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
    SimulatedSettlementContractError,
    _require_hash,
)
from apps.simulated_trading.domain.order_reservation_fill_release import (
    OrderFillSettlementReleaseProof,
)
from apps.simulated_trading.infrastructure import (
    order_reservation_fill_calendar_codec as calendar_codec,
)

_RELEASE_PROOF_SCHEMA = "simulated-order-fill-settlement-release-proof.v1"
_RELEASE_PROOF_KEYS = (
    "schema",
    "trade_id",
    "reservation_id",
    "account_id",
    "user_id",
    "receipt_hash",
    "security_id",
    "settlement_exchange",
    "fill_market_session",
    "settlement_lag_sessions",
    "released_at",
    "release_session",
    "calendar_evidence",
)


@dataclass(frozen=True, slots=True)
class EncodedOrderFillSettlementReleaseProof:
    """Validated release proof and its exact JSON/hash storage pair."""

    proof: OrderFillSettlementReleaseProof
    proof_json: str
    proof_hash: str

    def __post_init__(self) -> None:
        """Reject noncanonical JSON or a hash unrelated to the typed proof."""

        if type(self.proof) is not OrderFillSettlementReleaseProof:
            raise SimulatedSettlementContractError("proof must be the exact Domain value")
        self.proof.validate()
        expected_json = calendar_codec._canonical_json(
            self.proof.to_payload(),
            "release proof",
        )
        if type(self.proof_json) is not str or self.proof_json != expected_json:
            raise SimulatedSettlementContractError(
                "release proof JSON is not its canonical typed payload"
            )
        _require_hash(self.proof_hash, "release proof hash")
        if self.proof_hash != self.proof.proof_hash:
            raise SimulatedSettlementContractError(
                "release proof hash differs from its exact payload"
            )

    def to_payload(self) -> dict[str, object]:
        """Return a fresh payload mapping decoded from the sealed canonical JSON."""

        try:
            value: object = json.loads(self.proof_json)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise SimulatedSettlementContractError(
                "encoded release proof JSON is invalid"
            ) from error
        payload = calendar_codec._expect_object(
            value,
            field_names=_RELEASE_PROOF_KEYS,
            label="encoded release proof",
        )
        return dict(payload)


def decode_order_fill_settlement_release_proof(
    payload: object,
    *,
    proof_hash: object,
) -> OrderFillSettlementReleaseProof:
    """Decode exact JSON and verify its separately stored digest."""

    release_payload = calendar_codec._expect_object(
        payload,
        field_names=_RELEASE_PROOF_KEYS,
        label="fill settlement release proof",
    )
    calendar_codec._canonical_json(release_payload, "fill settlement release proof")
    schema = calendar_codec._require_text(
        release_payload["schema"],
        "release_proof.schema",
    )
    if schema != _RELEASE_PROOF_SCHEMA:
        raise CalendarEvidenceValidationError("fill settlement release proof schema is unsupported")

    if type(proof_hash) is not str:
        raise SimulatedSettlementContractError("release proof hash must be text")
    _require_hash(proof_hash, "release proof hash")
    proof = OrderFillSettlementReleaseProof(
        trade_id=calendar_codec._require_int(release_payload["trade_id"], "trade_id"),
        reservation_id=calendar_codec._require_int(
            release_payload["reservation_id"],
            "reservation_id",
        ),
        account_id=calendar_codec._require_int(
            release_payload["account_id"],
            "account_id",
        ),
        user_id=calendar_codec._require_int(release_payload["user_id"], "user_id"),
        receipt_hash=calendar_codec._require_text(
            release_payload["receipt_hash"],
            "receipt_hash",
        ),
        security_id=calendar_codec._require_text(
            release_payload["security_id"],
            "security_id",
        ),
        settlement_exchange=calendar_codec._require_text(
            release_payload["settlement_exchange"],
            "settlement_exchange",
        ),
        fill_market_session=calendar_codec._parse_date(
            release_payload["fill_market_session"],
            "fill_market_session",
        ),
        settlement_lag_sessions=calendar_codec._require_int(
            release_payload["settlement_lag_sessions"],
            "settlement_lag_sessions",
        ),
        released_at=calendar_codec._parse_utc_datetime(
            release_payload["released_at"],
            "released_at",
        ),
        release_session=calendar_codec._parse_date(
            release_payload["release_session"],
            "release_session",
        ),
        calendar_evidence=calendar_codec._parse_evidence(release_payload["calendar_evidence"]),
    )
    if not calendar_codec._same_json_value(release_payload, proof.to_payload()):
        raise SimulatedSettlementContractError(
            "release proof is not its exact canonical typed representation"
        )
    calendar_codec._canonical_json(proof.to_payload(), "fill settlement release proof")
    if proof.proof_hash != proof_hash:
        raise SimulatedSettlementContractError(
            "stored release proof hash differs from the exact typed payload"
        )
    return proof


def encode_order_fill_settlement_release_proof(
    proof: OrderFillSettlementReleaseProof,
) -> EncodedOrderFillSettlementReleaseProof:
    """Validate and serialize the exact release proof without changing source clocks."""

    if type(proof) is not OrderFillSettlementReleaseProof:
        raise SimulatedSettlementContractError("proof must be the exact Domain value")
    proof.validate()
    proof_json = calendar_codec._canonical_json(
        proof.to_payload(),
        "fill settlement release proof",
    )
    return EncodedOrderFillSettlementReleaseProof(
        proof=proof,
        proof_json=proof_json,
        proof_hash=proof.proof_hash,
    )


__all__: tuple[str, ...] = (
    "EncodedOrderFillSettlementReleaseProof",
    "decode_order_fill_settlement_release_proof",
    "encode_order_fill_settlement_release_proof",
)
