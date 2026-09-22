"""Strict JSON projection for persisted financial decision evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from uuid import UUID

from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseBodyScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.domain.financial_source_time_evidence import (
    FinancialAvailabilityBasis,
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimeWitness,
)
from core.exceptions import DataValidationError

_SCHEMA_V1 = "financial-fact-decision-evidence.v1"
_SCHEMA_V2 = "financial-fact-decision-evidence.v2"
_ROOT_KEYS_V1 = frozenset(
    {"schema", "artifact_reference", "native_asset_code", "native_period_end", "native_row_id"}
)
_ROOT_KEYS_V2 = _ROOT_KEYS_V1 | {"source_time_witness"}
_REFERENCE_KEYS = frozenset(
    {
        "capture_id",
        "location",
        "format_version",
        "encryption_algorithm",
        "encryption_key_ref",
        "encryption_key_version",
        "evidence_basis",
        "body_sha256",
        "body_size_bytes",
        "response_completed_at",
        "request_scope",
        "response_scope",
        "response_scope_basis",
        "body_scope",
    }
)
_REQUEST_KEYS = frozenset({"provider_name", "dataset_key", "asset_code", "period_limit"})
_RESPONSE_KEYS = frozenset({"asset_codes", "period_ends", "row_count"})
_SOURCE_TIME_WITNESS_KEYS = frozenset(
    {
        "artifact_reference",
        "native_asset_code",
        "native_period_end",
        "financial_native_row_id",
        "financial_announced_date",
        "source_native_row_id",
        "source_timezone",
        "announced_at",
        "available_at",
        "row_projection_sha256",
        "governed_match_contract_id",
        "governed_match_contract_version",
        "governed_match_contract_sha256",
        "matched_row_count",
        "availability_basis",
    }
)
_SOURCE_TIME_REFERENCE_KEYS = frozenset(
    {
        "capture_id",
        "location",
        "provider_name",
        "dataset_key",
        "requested_asset_code",
        "requested_announcement_date",
        "body_sha256",
        "body_size_bytes",
        "response_completed_at",
        "response_row_count",
        "format_version",
        "encryption_algorithm",
        "encryption_key_ref",
        "encryption_key_version",
    }
)


class FinancialDecisionEvidenceCodecError(DataValidationError):
    """Raised when persisted decision evidence is incomplete or ambiguous."""

    default_message = "Financial decision evidence projection is invalid"
    default_code = "FINANCIAL_DECISION_EVIDENCE_INVALID"


def encode_financial_decision_evidence(
    evidence: FinancialFactDecisionEvidence | None,
) -> dict[str, object]:
    """Encode one typed witness as an exact versioned JSON projection."""

    if evidence is None:
        return {}
    payload: dict[str, object] = {
        "schema": _SCHEMA_V2 if evidence.source_time_witness is not None else _SCHEMA_V1,
        "artifact_reference": evidence.artifact_reference.to_dict(),
        "native_asset_code": evidence.native_asset_code,
        "native_period_end": evidence.native_period_end.isoformat(),
        "native_row_id": evidence.native_row_id,
    }
    if evidence.source_time_witness is not None:
        payload["source_time_witness"] = evidence.source_time_witness.to_dict()
    return payload


def decode_financial_decision_evidence(
    raw: object,
) -> FinancialFactDecisionEvidence | None:
    """Decode one exact persisted projection without accepting partial data."""

    if raw is None or raw == {}:
        return None
    root = _mapping(raw, "decision_evidence")
    schema = _text(root["schema"], "schema")
    if schema == _SCHEMA_V1:
        _exact_keys(root, _ROOT_KEYS_V1, "decision_evidence")
        source_time_witness = None
    elif schema == _SCHEMA_V2:
        _exact_keys(root, _ROOT_KEYS_V2, "decision_evidence")
        source_time_witness = _decode_source_time_witness(root["source_time_witness"])
    else:
        raise FinancialDecisionEvidenceCodecError("financial decision evidence schema is invalid")
    reference = _decode_reference(root["artifact_reference"])
    try:
        native_period_end = date.fromisoformat(
            _text(root["native_period_end"], "native_period_end")
        )
    except ValueError as exc:
        raise FinancialDecisionEvidenceCodecError(
            "financial decision evidence native_period_end is invalid"
        ) from exc
    return FinancialFactDecisionEvidence(
        artifact_reference=reference,
        native_asset_code=_text(root["native_asset_code"], "native_asset_code"),
        native_period_end=native_period_end,
        native_row_id=_text(root["native_row_id"], "native_row_id"),
        source_time_witness=source_time_witness,
    )


def _decode_source_time_witness(raw: object) -> FinancialSourceTimeWitness:
    """Decode one exact source-time artifact and row binding."""

    witness = _mapping(raw, "source_time_witness")
    _exact_keys(witness, _SOURCE_TIME_WITNESS_KEYS, "source_time_witness")
    reference_raw = _mapping(witness["artifact_reference"], "source_time_artifact_reference")
    _exact_keys(
        reference_raw,
        _SOURCE_TIME_REFERENCE_KEYS,
        "source_time_artifact_reference",
    )
    try:
        reference = FinancialSourceTimeArtifactRef(
            capture_id=UUID(_text(reference_raw["capture_id"], "source_time.capture_id")),
            location=_text(reference_raw["location"], "source_time.location"),
            provider_name=_text(reference_raw["provider_name"], "source_time.provider_name"),
            dataset_key=_text(reference_raw["dataset_key"], "source_time.dataset_key"),
            requested_asset_code=_text(
                reference_raw["requested_asset_code"], "source_time.requested_asset_code"
            ),
            requested_announcement_date=date.fromisoformat(
                _text(
                    reference_raw["requested_announcement_date"],
                    "source_time.requested_announcement_date",
                )
            ),
            body_sha256=_text(reference_raw["body_sha256"], "source_time.body_sha256"),
            body_size_bytes=_integer(
                reference_raw["body_size_bytes"], "source_time.body_size_bytes"
            ),
            response_completed_at=datetime.fromisoformat(
                _text(
                    reference_raw["response_completed_at"],
                    "source_time.response_completed_at",
                )
            ),
            response_row_count=_integer(
                reference_raw["response_row_count"], "source_time.response_row_count"
            ),
            format_version=_text(reference_raw["format_version"], "source_time.format_version"),
            encryption_algorithm=_text(
                reference_raw["encryption_algorithm"], "source_time.encryption_algorithm"
            ),
            encryption_key_ref=_text(
                reference_raw["encryption_key_ref"], "source_time.encryption_key_ref"
            ),
            encryption_key_version=_text(
                reference_raw["encryption_key_version"], "source_time.encryption_key_version"
            ),
        )
        return FinancialSourceTimeWitness(
            artifact_reference=reference,
            native_asset_code=_text(witness["native_asset_code"], "source_time.native_asset_code"),
            native_period_end=date.fromisoformat(
                _text(witness["native_period_end"], "source_time.native_period_end")
            ),
            financial_native_row_id=_text(
                witness["financial_native_row_id"], "source_time.financial_native_row_id"
            ),
            financial_announced_date=date.fromisoformat(
                _text(witness["financial_announced_date"], "source_time.financial_announced_date")
            ),
            source_native_row_id=_text(
                witness["source_native_row_id"], "source_time.source_native_row_id"
            ),
            source_timezone=_text(witness["source_timezone"], "source_time.source_timezone"),
            announced_at=datetime.fromisoformat(
                _text(witness["announced_at"], "source_time.announced_at")
            ),
            available_at=datetime.fromisoformat(
                _text(witness["available_at"], "source_time.available_at")
            ),
            row_projection_sha256=_text(
                witness["row_projection_sha256"], "source_time.row_projection_sha256"
            ),
            governed_match_contract_id=_text(
                witness["governed_match_contract_id"], "source_time.governed_match_contract_id"
            ),
            governed_match_contract_version=_text(
                witness["governed_match_contract_version"],
                "source_time.governed_match_contract_version",
            ),
            governed_match_contract_sha256=_text(
                witness["governed_match_contract_sha256"],
                "source_time.governed_match_contract_sha256",
            ),
            matched_row_count=_integer(
                witness["matched_row_count"], "source_time.matched_row_count"
            ),
            availability_basis=FinancialAvailabilityBasis(
                _text(witness["availability_basis"], "source_time.availability_basis")
            ),
        )
    except (TypeError, ValueError) as exc:
        raise FinancialDecisionEvidenceCodecError(
            "financial source-time witness contains invalid typed values"
        ) from exc


def _decode_reference(raw: object) -> FinancialResponseArtifactRef:
    reference = _mapping(raw, "artifact_reference")
    _exact_keys(reference, _REFERENCE_KEYS, "artifact_reference")
    if _text(reference["evidence_basis"], "evidence_basis") != "raw_response_bytes":
        raise FinancialDecisionEvidenceCodecError("financial response evidence basis is invalid")
    request = _mapping(reference["request_scope"], "request_scope")
    response = _mapping(reference["response_scope"], "response_scope")
    _exact_keys(request, _REQUEST_KEYS, "request_scope")
    _exact_keys(response, _RESPONSE_KEYS, "response_scope")
    try:
        completed_at = datetime.fromisoformat(
            _text(reference["response_completed_at"], "response_completed_at")
        )
        period_ends = tuple(
            date.fromisoformat(_text(item, "response_scope.period_ends"))
            for item in _list(response["period_ends"], "response_scope.period_ends")
        )
        capture_id = UUID(_text(reference["capture_id"], "capture_id"))
        body_scope = FinancialResponseBodyScope(_text(reference["body_scope"], "body_scope"))
        scope_basis = FinancialResponseScopeBasis(
            _text(reference["response_scope_basis"], "response_scope_basis")
        )
    except (ValueError, TypeError) as exc:
        raise FinancialDecisionEvidenceCodecError(
            "financial response reference contains invalid typed values"
        ) from exc
    evidence = FinancialResponseEvidence(
        body_sha256=_text(reference["body_sha256"], "body_sha256"),
        body_size_bytes=_integer(reference["body_size_bytes"], "body_size_bytes"),
        response_completed_at=completed_at,
        request_scope=FinancialRequestScope(
            provider_name=_text(request["provider_name"], "request_scope.provider_name"),
            dataset_key=_text(request["dataset_key"], "request_scope.dataset_key"),
            asset_code=_text(request["asset_code"], "request_scope.asset_code"),
            period_limit=_integer(request["period_limit"], "request_scope.period_limit"),
        ),
        response_scope=FinancialResponseScope(
            asset_codes=tuple(
                _text(item, "response_scope.asset_codes")
                for item in _list(response["asset_codes"], "response_scope.asset_codes")
            ),
            period_ends=period_ends,
            row_count=_integer(response["row_count"], "response_scope.row_count"),
        ),
        body_scope=body_scope,
        response_scope_basis=scope_basis,
    )
    return FinancialResponseArtifactRef(
        capture_id=capture_id,
        location=_text(reference["location"], "location"),
        evidence=evidence,
        format_version=_text(reference["format_version"], "format_version"),
        encryption_algorithm=_text(reference["encryption_algorithm"], "encryption_algorithm"),
        encryption_key_ref=_text(reference["encryption_key_ref"], "encryption_key_ref"),
        encryption_key_version=_text(reference["encryption_key_version"], "encryption_key_version"),
    )


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise FinancialDecisionEvidenceCodecError(f"{field_name} must be an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    if frozenset(value) != expected:
        raise FinancialDecisionEvidenceCodecError(f"{field_name} keys are invalid")


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise FinancialDecisionEvidenceCodecError(f"{field_name} must be canonical text")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FinancialDecisionEvidenceCodecError(f"{field_name} must be an integer")
    return value


def _list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise FinancialDecisionEvidenceCodecError(f"{field_name} must be a list")
    return value


__all__ = [
    "FinancialDecisionEvidenceCodecError",
    "decode_financial_decision_evidence",
    "encode_financial_decision_evidence",
]
