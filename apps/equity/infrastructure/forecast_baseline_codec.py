"""Canonical JSON codecs for immutable forecast-baseline ledger records."""

from __future__ import annotations

import hashlib
import json
import types
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar, Union, cast, get_args, get_origin, get_type_hints

from apps.equity.application.forecast_baseline_materialize import (
    BaselineApprovalEvidence,
    EvidenceIdentity,
)
from apps.equity.domain.forecast_baseline import (
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
    ForecastBaselineTrialResult,
)

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

APPROVAL_PAYLOAD_SCHEMA = "r1-equity-baseline-approval-evidence.v1"
SPEC_PAYLOAD_SCHEMA = "r1-equity-forecast-baseline-spec-ledger.v1"
ARTIFACT_PAYLOAD_SCHEMA = "r1-equity-forecast-baseline-artifact-ledger.v1"
TRIAL_PAYLOAD_SCHEMA = "r1-equity-forecast-baseline-trial-ledger.v1"

_DataclassT = TypeVar("_DataclassT")


class ForecastBaselineCodecError(ValueError):
    """Raised when persisted JSON is non-canonical, malformed or tampered."""


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if Decimal(text) == 0 else text


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ForecastBaselineCodecError("datetime payload values must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _encode(value: object) -> JsonValue:
    if isinstance(value, Enum):
        return cast(str, value.value)
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        return _utc_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if value is None or type(value) in {bool, int, float, str}:
        return cast(None | bool | int | float | str, value)
    raise ForecastBaselineCodecError(f"unsupported canonical payload value: {type(value)!r}")


def _as_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ForecastBaselineCodecError(f"{field_name} must be a JSON object")
    return cast(Mapping[str, object], value)


def _decode_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ForecastBaselineCodecError(f"{field_name} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ForecastBaselineCodecError(f"{field_name} must be an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForecastBaselineCodecError(f"{field_name} must be timezone-aware")
    if _utc_text(parsed) != value:
        raise ForecastBaselineCodecError(f"{field_name} is not canonical UTC")
    return parsed


def _decode_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise ForecastBaselineCodecError(f"{field_name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ForecastBaselineCodecError(f"{field_name} must be an ISO date") from error
    if parsed.isoformat() != value:
        raise ForecastBaselineCodecError(f"{field_name} is not a canonical date")
    return parsed


def _decode(value: object, expected_type: object, field_name: str) -> object:
    origin = get_origin(expected_type)
    args = get_args(expected_type)
    if origin in {Union, types.UnionType}:
        if value is None and type(None) in args:
            return None
        candidates = tuple(item for item in args if item is not type(None))
        for candidate in candidates:
            try:
                return _decode(value, candidate, field_name)
            except (ForecastBaselineCodecError, TypeError, ValueError):
                continue
        raise ForecastBaselineCodecError(f"{field_name} does not match its union type")
    if origin is tuple:
        if not isinstance(value, list):
            raise ForecastBaselineCodecError(f"{field_name} must be a JSON array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(
                _decode(item, args[0], f"{field_name}[{index}]") for index, item in enumerate(value)
            )
        if len(value) != len(args):
            raise ForecastBaselineCodecError(f"{field_name} has an invalid tuple length")
        return tuple(
            _decode(item, item_type, f"{field_name}[{index}]")
            for index, (item, item_type) in enumerate(zip(value, args, strict=True))
        )
    if expected_type is datetime:
        return _decode_datetime(value, field_name)
    if expected_type is date:
        return _decode_date(value, field_name)
    if expected_type is Decimal:
        if not isinstance(value, str):
            raise ForecastBaselineCodecError(f"{field_name} must be a decimal string")
        try:
            parsed_decimal = Decimal(value)
        except Exception as error:
            raise ForecastBaselineCodecError(f"{field_name} must be a decimal string") from error
        if not parsed_decimal.is_finite() or _decimal_text(parsed_decimal) != value:
            raise ForecastBaselineCodecError(f"{field_name} is not a canonical decimal")
        return parsed_decimal
    if isinstance(expected_type, type) and issubclass(expected_type, Enum):
        if not isinstance(value, str):
            raise ForecastBaselineCodecError(f"{field_name} must be an enum token")
        try:
            return expected_type(value)
        except ValueError as error:
            raise ForecastBaselineCodecError(f"{field_name} has an unknown enum token") from error
    if isinstance(expected_type, type) and is_dataclass(expected_type):
        return _decode_dataclass(value, expected_type, field_name)
    if expected_type is bool:
        if type(value) is not bool:
            raise ForecastBaselineCodecError(f"{field_name} must be a boolean")
        return value
    if expected_type is int:
        if type(value) is not int:
            raise ForecastBaselineCodecError(f"{field_name} must be an integer")
        return value
    if expected_type is float:
        if type(value) is not float:
            raise ForecastBaselineCodecError(f"{field_name} must be a float")
        return value
    if expected_type is str:
        if not isinstance(value, str):
            raise ForecastBaselineCodecError(f"{field_name} must be a string")
        return value
    raise ForecastBaselineCodecError(f"{field_name} has an unsupported declared type")


def _decode_dataclass(
    value: object,
    expected_type: type[_DataclassT],
    field_name: str,
) -> _DataclassT:
    payload = _as_mapping(value, field_name)
    declared_fields = fields(cast(Any, expected_type))
    expected_names = {field.name for field in declared_fields}
    if set(payload) != expected_names:
        raise ForecastBaselineCodecError(f"{field_name} fields do not match the typed contract")
    type_hints = get_type_hints(expected_type)
    decoded = {
        field.name: _decode(
            payload[field.name],
            type_hints[field.name],
            f"{field_name}.{field.name}",
        )
        for field in declared_fields
    }
    try:
        return expected_type(**decoded)
    except (TypeError, ValueError) as error:
        raise ForecastBaselineCodecError(f"{field_name} violates its typed contract") from error


def _envelope(schema: str, value: object) -> dict[str, JsonValue]:
    return {"schema": schema, "payload": _encode(value)}


def _decode_envelope(
    raw: object,
    *,
    schema: str,
    expected_type: type[_DataclassT],
) -> _DataclassT:
    envelope = _as_mapping(raw, "ledger envelope")
    if set(envelope) != {"schema", "payload"} or envelope["schema"] != schema:
        raise ForecastBaselineCodecError("ledger payload schema is invalid")
    restored = _decode_dataclass(envelope["payload"], expected_type, "ledger payload")
    if _envelope(schema, restored) != envelope:
        raise ForecastBaselineCodecError("ledger payload is not canonical")
    return restored


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def approval_content_hash(evidence: BaselineApprovalEvidence) -> str:
    """Compute the non-self-referential canonical approval content hash."""

    envelope = _envelope(APPROVAL_PAYLOAD_SCHEMA, evidence)
    payload = _as_mapping(envelope["payload"], "approval payload")
    approval = _as_mapping(payload["approval"], "approval identity")
    neutral_approval = dict(approval)
    neutral_approval["content_hash"] = ""
    neutral_payload = dict(payload)
    neutral_payload["approval"] = neutral_approval
    return _canonical_hash({"schema": APPROVAL_PAYLOAD_SCHEMA, "payload": neutral_payload})


def seal_approval_evidence(evidence: BaselineApprovalEvidence) -> BaselineApprovalEvidence:
    """Return approval evidence carrying its exact canonical content hash."""

    digest = approval_content_hash(evidence)
    return replace(
        evidence,
        approval=EvidenceIdentity(
            stable_id=evidence.approval.stable_id,
            version=evidence.approval.version,
            content_hash=digest,
        ),
    )


def encode_approval_evidence(evidence: BaselineApprovalEvidence) -> dict[str, JsonValue]:
    """Encode and verify one canonical owner approval."""

    if evidence.approval.content_hash != approval_content_hash(evidence):
        raise ForecastBaselineCodecError("approval evidence content hash mismatch")
    return _envelope(APPROVAL_PAYLOAD_SCHEMA, evidence)


def decode_approval_evidence(raw: object) -> BaselineApprovalEvidence:
    """Restore typed owner approval and reject JSON/hash/time tampering."""

    evidence = _decode_envelope(
        raw,
        schema=APPROVAL_PAYLOAD_SCHEMA,
        expected_type=BaselineApprovalEvidence,
    )
    if evidence.approval.content_hash != approval_content_hash(evidence):
        raise ForecastBaselineCodecError("approval evidence content hash mismatch")
    return evidence


def encode_forecast_baseline_spec(spec: ForecastBaselineSpec) -> dict[str, JsonValue]:
    """Encode a Domain-validated immutable baseline spec."""

    return _envelope(SPEC_PAYLOAD_SCHEMA, spec)


def decode_forecast_baseline_spec(raw: object) -> ForecastBaselineSpec:
    """Restore a spec through all Domain hash and time validation."""

    return _decode_envelope(raw, schema=SPEC_PAYLOAD_SCHEMA, expected_type=ForecastBaselineSpec)


def encode_forecast_baseline_artifact(
    artifact: ForecastBaselineArtifact,
) -> dict[str, JsonValue]:
    """Encode a Domain-validated immutable baseline artifact."""

    return _envelope(ARTIFACT_PAYLOAD_SCHEMA, artifact)


def decode_forecast_baseline_artifact(raw: object) -> ForecastBaselineArtifact:
    """Restore an artifact through all Domain hash and time validation."""

    return _decode_envelope(
        raw,
        schema=ARTIFACT_PAYLOAD_SCHEMA,
        expected_type=ForecastBaselineArtifact,
    )


def encode_forecast_baseline_trial(
    trial: ForecastBaselineTrialResult,
) -> dict[str, JsonValue]:
    """Encode a Domain-validated immutable baseline trial result."""

    return _envelope(TRIAL_PAYLOAD_SCHEMA, trial)


def decode_forecast_baseline_trial(raw: object) -> ForecastBaselineTrialResult:
    """Restore a trial through all Domain hash and time validation."""

    return _decode_envelope(
        raw,
        schema=TRIAL_PAYLOAD_SCHEMA,
        expected_type=ForecastBaselineTrialResult,
    )


__all__ = [
    "APPROVAL_PAYLOAD_SCHEMA",
    "ARTIFACT_PAYLOAD_SCHEMA",
    "ForecastBaselineCodecError",
    "SPEC_PAYLOAD_SCHEMA",
    "TRIAL_PAYLOAD_SCHEMA",
    "approval_content_hash",
    "decode_approval_evidence",
    "decode_forecast_baseline_artifact",
    "decode_forecast_baseline_spec",
    "decode_forecast_baseline_trial",
    "encode_approval_evidence",
    "encode_forecast_baseline_artifact",
    "encode_forecast_baseline_spec",
    "encode_forecast_baseline_trial",
    "seal_approval_evidence",
]
