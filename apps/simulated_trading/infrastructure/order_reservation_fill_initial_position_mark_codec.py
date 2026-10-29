"""Canonical wire encoding for a sealed initial-position mark proof."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, cast

from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _decimal_from_text,
    _require_aware,
    _utc_text,
    validate_ledger_price,
)
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof

_MARK_SCHEMA = "simulated-initial-position-mark.v1"
_DAILY_INTERVAL_MARK_SCHEMA = "simulated-initial-position-mark.daily-interval.v1"
_MARK_PURPOSE = "apply_time_initial_position_mark"
_DAILY_INTERVAL_BASIS = "daily_interval_end"
_MAX_MARK_JSON_LENGTH = 16_384
_MARK_FIELDS = (
    "schema",
    "purpose",
    "security_id",
    "asset_code",
    "asset_type",
    "market",
    "board",
    "price",
    "source_observed_at",
    "source_available_at",
    "read_at",
    "publication_as_of",
    "published_at",
    "valid_until",
    "freshness_window_seconds",
    "source_identity",
    "source_record_id",
    "source_content_hash",
    "publication_id",
    "publication_hash",
    "policy_identity",
    "policy_content_hash",
)
_DAILY_INTERVAL_MARK_FIELDS = _MARK_FIELDS + (
    "observation_basis",
    "interval_end_at",
    "local_known_at",
)


def _canonical_json(payload: Mapping[str, object]) -> str:
    """Serialize one JSON object with the snapshot codec's canonical settings."""

    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        encoded.encode("utf-8")
        return encoded
    except (TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(
            "initial-position mark cannot be represented as canonical JSON"
        ) from error


def _text(value: object, field_name: str) -> str:
    """Narrow one mark wire value to an exact string."""

    if type(value) is not str:
        raise SimulatedSettlementContractError(f"initial-position mark {field_name} must be text")
    return value


def _datetime(value: object, field_name: str) -> datetime:
    """Parse one canonical aware UTC wire clock."""

    text = _text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        _require_aware(parsed, field_name)
        if _utc_text(parsed) != text:
            raise SimulatedSettlementContractError(
                f"initial-position mark {field_name} is not canonical UTC text"
            )
        return parsed.astimezone(UTC)
    except SimulatedSettlementContractError:
        raise
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(
            f"initial-position mark {field_name} is not an aware UTC instant"
        ) from error


def _object(value: object) -> dict[str, object]:
    """Require an exact string-key object for one supported mark schema."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise SimulatedSettlementContractError("initial-position mark must be a JSON object")
    payload = cast(dict[str, object], value)
    schema = payload.get("schema")
    expected_fields = (
        _MARK_FIELDS
        if schema == _MARK_SCHEMA
        else _DAILY_INTERVAL_MARK_FIELDS if schema == _DAILY_INTERVAL_MARK_SCHEMA else ()
    )
    if not expected_fields or frozenset(payload) != frozenset(expected_fields):
        raise SimulatedSettlementContractError(
            "initial-position mark schema fields are missing, unknown, or unsupported"
        )
    return payload


def encode_initial_position_mark_evidence(proof: InitialPositionMarkProof) -> str:
    """Return the full canonical wire JSON for one exact Domain mark proof."""

    if type(proof) is not InitialPositionMarkProof:
        raise SimulatedSettlementContractError(
            "initial-position mark must be the exact typed Domain proof"
        )
    proof.validate()
    encoded = _canonical_json(proof.to_payload())
    if not encoded or len(encoded) > _MAX_MARK_JSON_LENGTH:
        raise SimulatedSettlementContractError("initial-position mark JSON is oversized")
    return encoded


def decode_initial_position_mark_evidence(value: object) -> InitialPositionMarkProof:
    """Decode exact fields, then delegate semantic and chronology checks to Domain."""

    if type(value) is not str or not value or len(value) > _MAX_MARK_JSON_LENGTH:
        raise SimulatedSettlementContractError("initial-position mark JSON is missing or oversized")
    try:
        raw_value: object = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("initial-position mark JSON is invalid") from error
    payload = _object(raw_value)
    if _canonical_json(payload) != value:
        raise SimulatedSettlementContractError("initial-position mark JSON is not canonical")
    schema = payload["schema"]
    if schema not in (_MARK_SCHEMA, _DAILY_INTERVAL_MARK_SCHEMA):
        raise SimulatedSettlementContractError("initial-position mark schema is unsupported")
    if payload["purpose"] != _MARK_PURPOSE:
        raise SimulatedSettlementContractError("initial-position mark schema is unsupported")
    price = validate_ledger_price(
        _decimal_from_text(payload["price"], "initial_position_mark.price"),
        "initial_position_mark.price",
        allow_zero=False,
    )
    source_available_at_value = payload["source_available_at"]
    source_available_at = (
        None
        if source_available_at_value is None
        else _datetime(source_available_at_value, "source_available_at")
    )
    source_observed_at_value = payload["source_observed_at"]
    source_observed_at = (
        None
        if source_observed_at_value is None
        else _datetime(source_observed_at_value, "source_observed_at")
    )
    if schema == _MARK_SCHEMA:
        observation_basis: Literal["legacy_source_observed", "daily_interval_end"] = (
            "legacy_source_observed"
        )
        interval_end_at = None
        local_known_at = None
    else:
        basis_value = payload["observation_basis"]
        if type(basis_value) is not str or basis_value != _DAILY_INTERVAL_BASIS:
            raise SimulatedSettlementContractError(
                "initial-position mark observation basis is unsupported"
            )
        observation_basis = "daily_interval_end"
        interval_end_at = _datetime(payload["interval_end_at"], "interval_end_at")
        local_known_at = _datetime(payload["local_known_at"], "local_known_at")
    freshness_window_seconds = payload["freshness_window_seconds"]
    if type(freshness_window_seconds) is not int:
        raise SimulatedSettlementContractError(
            "initial-position mark freshness_window_seconds must be an integer"
        )
    proof = InitialPositionMarkProof(
        security_id=_text(payload["security_id"], "security_id"),
        asset_code=_text(payload["asset_code"], "asset_code"),
        asset_type=_text(payload["asset_type"], "asset_type"),
        market=_text(payload["market"], "market"),
        board=_text(payload["board"], "board"),
        price=price,
        source_observed_at=source_observed_at,
        source_available_at=source_available_at,
        read_at=_datetime(payload["read_at"], "read_at"),
        publication_as_of=_datetime(payload["publication_as_of"], "publication_as_of"),
        published_at=_datetime(payload["published_at"], "published_at"),
        valid_until=_datetime(payload["valid_until"], "valid_until"),
        freshness_window_seconds=freshness_window_seconds,
        source_identity=_text(payload["source_identity"], "source_identity"),
        source_record_id=_text(payload["source_record_id"], "source_record_id"),
        source_content_hash=_text(payload["source_content_hash"], "source_content_hash"),
        publication_id=_text(payload["publication_id"], "publication_id"),
        publication_hash=_text(payload["publication_hash"], "publication_hash"),
        policy_identity=_text(payload["policy_identity"], "policy_identity"),
        policy_content_hash=_text(payload["policy_content_hash"], "policy_content_hash"),
        observation_basis=observation_basis,
        interval_end_at=interval_end_at,
        local_known_at=local_known_at,
    )
    proof.validate()
    if encode_initial_position_mark_evidence(proof) != value:
        raise SimulatedSettlementContractError(
            "initial-position mark differs from its canonical typed proof"
        )
    return proof


__all__ = (
    "decode_initial_position_mark_evidence",
    "encode_initial_position_mark_evidence",
)
