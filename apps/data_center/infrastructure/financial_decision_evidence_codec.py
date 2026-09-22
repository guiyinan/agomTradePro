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
from core.exceptions import DataValidationError

_SCHEMA = "financial-fact-decision-evidence.v1"
_ROOT_KEYS = frozenset(
    {"schema", "artifact_reference", "native_asset_code", "native_period_end", "native_row_id"}
)
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
    return {
        "schema": _SCHEMA,
        "artifact_reference": evidence.artifact_reference.to_dict(),
        "native_asset_code": evidence.native_asset_code,
        "native_period_end": evidence.native_period_end.isoformat(),
        "native_row_id": evidence.native_row_id,
    }


def decode_financial_decision_evidence(
    raw: object,
) -> FinancialFactDecisionEvidence | None:
    """Decode one exact persisted projection without accepting partial data."""

    if raw is None or raw == {}:
        return None
    root = _mapping(raw, "decision_evidence")
    _exact_keys(root, _ROOT_KEYS, "decision_evidence")
    if _text(root["schema"], "schema") != _SCHEMA:
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
    )


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
