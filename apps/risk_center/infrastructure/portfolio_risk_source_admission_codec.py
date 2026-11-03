"""Build the exact immutable RawPayload manifest consumed by the risk reader."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.domain.raw_landing import RawPayload
from apps.risk_center.application.portfolio_risk_source_admission import (
    PortfolioRiskSinaQuoteCaptureMetadata,
    PortfolioRiskSourceAdmissionRequest,
)
from apps.risk_center.application.portfolio_risk_source_codec import (
    PortfolioRiskSourcePayload,
    decode_portfolio_risk_source_payload,
)
from apps.risk_center.infrastructure.portfolio_risk_assets_manifest import (
    _CAPTURE_RECEIPT_MANIFEST_KEYS,
    _CAPTURE_RECEIPT_MANIFEST_SCHEMA,
    _CAPTURE_RECEIPT_PARSER_VERSION,
    _DATASET_KEY,
    _MANIFEST_KEYS,
    _MANIFEST_SCHEMA,
    _PARSER_VERSION,
    _manifest_payload_hash,
    _parse_facts,
)


class RetainedPortfolioRiskAdmissionManifestCodec:
    """Validate typed admission values and serialize the reader's exact schema."""

    def build_payload(self, request: PortfolioRiskSourceAdmissionRequest) -> RawPayload:
        """Build a hash-addressed RawPayload without parsing its original body."""

        if type(request) is not PortfolioRiskSourceAdmissionRequest:
            raise TypeError("request_must_be_portfolio_risk_source_admission_request")
        original_hash = hashlib.sha256(request.original_body).hexdigest()
        supplied_hash = request.source_evidence.original_payload_sha256
        if supplied_hash is not None and supplied_hash != original_hash:
            raise ValueError("risk_input_original_body_hash_mismatch")
        if len(request.source_evidence.source_id) > 100:
            raise ValueError("risk_input_provider_name_too_long")

        facts = cast(dict[str, object], dict(request.facts))
        _parse_facts(request.kind, facts)
        evidence = replace(
            request.source_evidence,
            original_payload_sha256=original_hash,
        )
        try:
            source_evidence_json = _source_evidence_json(evidence)
            if decode_portfolio_risk_source_payload(source_evidence_json) != evidence:
                raise ValueError("risk_input_source_evidence_round_trip_mismatch")
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("risk_input_source_evidence_invalid") from exc
        payload: dict[str, object] = {
            "schema_version": (
                _CAPTURE_RECEIPT_MANIFEST_SCHEMA
                if request.capture_receipt is not None
                else _MANIFEST_SCHEMA
            ),
            "kind": request.kind,
            "asset_code": request.asset_code,
            "security_id": request.security_id,
            "source_record_id": request.source_record_id,
            "original_body_base64": base64.b64encode(request.original_body).decode("ascii"),
            "original_url": request.original_url,
            "source_evidence": source_evidence_json,
            "facts": facts,
        }
        manifest_keys = (
            _CAPTURE_RECEIPT_MANIFEST_KEYS
            if request.capture_receipt is not None
            else _MANIFEST_KEYS
        )
        if request.capture_receipt is not None:
            receipt = request.capture_receipt
            payload["capture_receipt"] = {
                "capture_id": receipt.capture_id,
                "source_id": receipt.source_id,
                "source_record_id": receipt.source_record_id,
                "original_body_sha256": receipt.original_body_sha256,
                "response_completed_at": receipt.response_completed_at.isoformat(),
                "http_status": receipt.http_status,
                "body_size_bytes": receipt.body_size_bytes,
                "body_complete": receipt.body_complete,
            }
            capture_metadata: PortfolioRiskSinaQuoteCaptureMetadata | None = None
            if request.sina_capture is not None:
                capture = request.sina_capture.to_payload()
                capture_metadata = {
                    "asset_code": capture["asset_code"],
                    "requested_url": capture["requested_url"],
                    "final_url": capture["final_url"],
                    "request_started_at": capture["request_started_at"],
                    "response_completed_at": capture["response_completed_at"],
                    "http_status": capture["http_status"],
                    "http_date": capture["http_date"],
                    "content_type": capture["content_type"],
                    "charset": capture["charset"],
                    "content_encoding": capture["content_encoding"],
                }
            payload["sina_capture_metadata"] = capture_metadata
        if frozenset(payload) != manifest_keys:
            raise ValueError("risk_input_manifest_schema_mismatch")
        manifest_hash = _manifest_payload_hash(payload)
        schema_version = cast(str, payload["schema_version"])
        schema_fingerprint = _schema_fingerprint(schema_version, manifest_keys)
        return RawPayload(
            payload_id=str(uuid5(NAMESPACE_URL, manifest_hash)),
            dataset_key=_DATASET_KEY,
            provider_name=evidence.source_id,
            payload_hash=manifest_hash,
            schema_fingerprint=schema_fingerprint,
            payload=cast(dict[str, Any], payload),
            fetched_at=request.captured_at,
            request_params={},
            content_type="application/json",
            parser_version=(
                _CAPTURE_RECEIPT_PARSER_VERSION
                if request.capture_receipt is not None
                else _PARSER_VERSION
            ),
            redacted=True,
            payload_size_bytes=len(request.original_body),
        )


def _source_evidence_json(evidence: PortfolioRiskSourcePayload) -> dict[str, object]:
    """Serialize only captured source fields, preserving unknowns and offsets."""

    coverage = evidence.coverage
    return {
        "source_id": evidence.source_id,
        "source_record_id": evidence.source_record_id,
        "original_payload_sha256": evidence.original_payload_sha256,
        "observation_precision": evidence.observation_precision.value,
        "observed_at": evidence.observed_at.isoformat() if evidence.observed_at else None,
        "observed_on": evidence.observed_on.isoformat() if evidence.observed_on else None,
        "available_at": evidence.available_at.isoformat() if evidence.available_at else None,
        "known_at": evidence.known_at.isoformat() if evidence.known_at else None,
        "valid_until": evidence.valid_until.isoformat() if evidence.valid_until else None,
        "source_purpose": evidence.source_purpose,
        "allowed_purposes": list(evidence.allowed_purposes),
        "restrictions": list(evidence.restrictions),
        "must_not_use_for_decision": evidence.must_not_use_for_decision,
        "coverage": {
            "status": coverage.status.value,
            "precision_basis": coverage.precision_basis,
            "reported_weight_fraction": (
                str(coverage.reported_weight_fraction)
                if coverage.reported_weight_fraction is not None
                else None
            ),
            "expected_item_count": coverage.expected_item_count,
            "observed_item_count": coverage.observed_item_count,
        },
        "effective_on": evidence.effective_on.isoformat() if evidence.effective_on else None,
        "effective_until": (
            evidence.effective_until.isoformat() if evidence.effective_until else None
        ),
    }


def _schema_fingerprint(schema_version: str, manifest_keys: frozenset[str]) -> str:
    """Fingerprint the stable manifest shape rather than one source's content."""

    shape = {"schema_version": schema_version, "fields": sorted(manifest_keys)}
    encoded = json.dumps(
        shape,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = ("RetainedPortfolioRiskAdmissionManifestCodec",)
