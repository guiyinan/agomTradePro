"""Build and validate the S6 full-scope financial capacity receipt."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import cast

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE = re.compile(r"^[0-9a-f]{40}$")
_IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ARTIFACT_ROOT = re.compile(r"^agom-s6-financial-scope-[0-9a-f]{32}$")
_ARTIFACT_PATH = re.compile(r"^agom-s6-financial-scope-[0-9a-f]{32}/v1/[0-9a-f-]{36}\.frb$")
_ASSET_CODE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_NATIVE_ROW_ID = re.compile(
    r"^akshare:[0-9]{6}\.(?:SH|SZ|BJ):[0-9]{4}-[0-9]{2}-[0-9]{2}:" r"[0-9]{4}-[0-9]{2}-[0-9]{2}$"
)


class FinancialScopeCapacityReceiptError(ValueError):
    """One stable, safe S6 financial-scope receipt validation failure."""

    def __init__(self, code: str) -> None:
        """Expose only the stable S6 receipt diagnostic code."""

        self.code = code
        super().__init__(code)


def build_financial_scope_capacity_receipt(
    *,
    scope_report: object,
    scope_report_sha256: str,
    target_trade_date: str,
    release_universe_sha256: str,
    provider_identities_sha256: str,
) -> dict[str, object]:
    """Seal full-universe dual-capture evidence without treating it as publication."""

    _require_sha256(scope_report_sha256, "S6_FINANCIAL_SCOPE_SOURCE_DIGEST_INVALID")
    _require_sha256(release_universe_sha256, "S6_FINANCIAL_SCOPE_UNIVERSE_INVALID")
    _require_sha256(provider_identities_sha256, "S6_FINANCIAL_SCOPE_PROVIDER_INVALID")
    try:
        date.fromisoformat(target_trade_date)
    except (TypeError, ValueError):
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_DATE_INVALID") from None

    source = _mapping(scope_report, "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    _validate_scope_source(source)
    result = _mapping(source.get("result"), "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    candidate = _mapping(result.get("candidate_manifest"), "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    binding = _mapping(candidate.get("binding"), "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    universe = _mapping(candidate.get("universe"), "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    counts = _mapping(result.get("counts"), "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    items = _list(candidate.get("items"), "S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
    artifacts = _list(source.get("encrypted_artifacts"), "S6_FINANCIAL_SCOPE_ARTIFACT_INVALID")
    asset_count = len(items)
    if asset_count <= 0:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_COVERAGE_INCOMPLETE")
    candidate_sha = _text(source, "candidate_sha", "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    manifest_sha256 = _text(candidate, "manifest_sha256", "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    financial_universe_sha256 = _text(universe, "sha256", "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    financial_provider_sha256 = _text(
        binding, "provider_identity_sha256", "S6_FINANCIAL_SCOPE_SOURCE_INVALID"
    )
    contract_sha256 = _text(binding, "contract_sha256", "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    parser_sha256 = _text(binding, "parser_sha256", "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    scope_provider_id = _positive_int(binding, "provider_id")
    root_name = _text(source, "artifact_root", "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    if _ARTIFACT_ROOT.fullmatch(root_name) is None:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_ARTIFACT_INVALID")

    _validate_candidate(candidate, source, result, binding, universe, items, counts, artifacts)
    evidence_ledger_sha256 = canonical_sha256(items)
    artifact_ledger_sha256 = canonical_sha256(artifacts)
    source_revision_sha256 = canonical_sha256(
        {
            "candidate_sha": candidate_sha,
            "scope_manifest_sha256": manifest_sha256,
            "financial_universe_sha256": financial_universe_sha256,
            "provider_identity_sha256": financial_provider_sha256,
            "contract_sha256": contract_sha256,
            "parser_sha256": parser_sha256,
            "evidence_ledger_sha256": evidence_ledger_sha256,
        }
    )
    scope_pointer_sha256 = canonical_sha256(
        {
            "environment": "s6_isolated_disposable",
            "candidate_sha": candidate_sha,
            "scope_report_sha256": scope_report_sha256,
            "scope_manifest_sha256": manifest_sha256,
        }
    )
    logical_requests = _positive_int(counts, "logical_requests")
    physical_attempts = _positive_int(counts, "physical_attempts")
    receipt: dict[str, object] = {
        "schema": "release.financial-scope-capacity.v1",
        "kind": "financial_scope_capacity",
        "candidate_sha": candidate_sha,
        "candidate_image_id": _text(
            source, "candidate_image_id", "S6_FINANCIAL_SCOPE_SOURCE_INVALID"
        ),
        "candidate_source_attestation": "image_release_manifest",
        "target_trade_date": target_trade_date,
        "universe_sha256": release_universe_sha256,
        "provider_identities_sha256": provider_identities_sha256,
        "outcome": "success",
        "evidence_mode": "isolated_full_scope_financial_capture",
        "environment": "s6_isolated_disposable",
        "started_at": _text(source, "started_at", "S6_FINANCIAL_SCOPE_SOURCE_INVALID"),
        "finished_at": _text(source, "finished_at", "S6_FINANCIAL_SCOPE_SOURCE_INVALID"),
        "scope_report": {
            "path": "financial-scope-discovery.json",
            "sha256": scope_report_sha256,
        },
        "scope_manifest_sha256": manifest_sha256,
        "scope_pointer_sha256": scope_pointer_sha256,
        "financial_universe_sha256": financial_universe_sha256,
        "financial_provider_id": scope_provider_id,
        "financial_provider_identity_sha256": financial_provider_sha256,
        "contract_sha256": contract_sha256,
        "parser_sha256": parser_sha256,
        "source_revision_sha256": source_revision_sha256,
        "evidence_ledger_sha256": evidence_ledger_sha256,
        "artifact_ledger_sha256": artifact_ledger_sha256,
        "capacity": {
            "asset_count": asset_count,
            "logical_request_count": logical_requests,
            "logical_request_ceiling": asset_count * 2,
            "physical_attempt_count": physical_attempts,
            "physical_attempt_ceiling": asset_count * 4,
            "artifact_count": len(artifacts),
            "raw_audit_count": _positive_int(counts, "raw_audit_writes"),
            "fact_writes": 0,
            "publication_writes": 0,
        },
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def validate_financial_scope_capacity_receipt(
    *,
    receipt: object,
    scope_report: object,
    scope_report_sha256: str,
    expected_candidate: str,
    expected_image_id: str,
    expected_trade_date: str,
    expected_release_universe_sha256: str,
    expected_provider_identities_sha256: str,
) -> None:
    """Recompute all receipt hashes and bind the report to the exact S6 candidate."""

    expected = build_financial_scope_capacity_receipt(
        scope_report=scope_report,
        scope_report_sha256=scope_report_sha256,
        target_trade_date=expected_trade_date,
        release_universe_sha256=expected_release_universe_sha256,
        provider_identities_sha256=expected_provider_identities_sha256,
    )
    value = _mapping(receipt, "S6_FINANCIAL_SCOPE_RECEIPT_INVALID")
    if value != expected:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_RECEIPT_BINDING_INVALID")
    if (
        expected["candidate_sha"] != expected_candidate
        or expected["candidate_image_id"] != expected_image_id
    ):
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_IDENTITY_MISMATCH")


def canonical_sha256(value: object) -> str:
    """Return the SHA-256 digest of a canonical JSON value."""

    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()


def _validate_scope_source(source: Mapping[str, object]) -> None:
    expected_keys = {
        "schema",
        "kind",
        "candidate_sha",
        "started_at",
        "finished_at",
        "outcome",
        "review_status",
        "binding",
        "database",
        "authorization",
        "candidate_image_id",
        "artifact_root",
        "encrypted_artifacts",
        "result",
    }
    database = _mapping(source.get("database"), "S6_FINANCIAL_SCOPE_ENVIRONMENT_INVALID")
    result = _mapping(source.get("result"), "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    if (
        set(source) != expected_keys
        or source.get("schema") != "release.financial-scope-discovery.v1"
        or source.get("kind") != "financial_scope_discovery"
        or source.get("outcome") != "success"
        or source.get("review_status") != "pending_independent_review"
        or set(result)
        != {"schema", "outcome", "error_codes", "counts", "candidate", "candidate_manifest"}
        or result.get("schema") != "data-center.financial-scope-discovery-result.v1"
        or result.get("outcome") != "success"
        or result.get("error_codes") != []
        or _IMAGE.fullmatch(
            _text(source, "candidate_image_id", "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
        )
        is None
        or database.get("vendor") != "postgresql"
        or database.get("scope") != "disposable"
        or database.get("release_rehearsal_guard") is not True
        or not _text(database, "name", "S6_FINANCIAL_SCOPE_ENVIRONMENT_INVALID").startswith(
            "agom_release_rehearsal_"
        )
        or not _text(database, "host", "S6_FINANCIAL_SCOPE_ENVIRONMENT_INVALID").startswith(
            "agom-s6-postgres-"
        )
        or _SHA256.fullmatch(
            _text(
                database, "isolation_attestation_sha256", "S6_FINANCIAL_SCOPE_ENVIRONMENT_INVALID"
            )
        )
        is None
    ):
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_ENVIRONMENT_INVALID")
    candidate_sha = _text(source, "candidate_sha", "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    if _CANDIDATE.fullmatch(candidate_sha) is None:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    started = _parse_datetime(source.get("started_at"))
    finished = _parse_datetime(source.get("finished_at"))
    if finished < started:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_TIME_INVALID")
    _mapping(source.get("binding"), "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    authorization = _mapping(
        source.get("authorization"), "S6_FINANCIAL_SCOPE_AUTHORIZATION_INVALID"
    )
    if set(authorization) != {"approval_id", "owner_event_id", "owner_receipt_sha256"}:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_AUTHORIZATION_INVALID")
    for key in ("approval_id", "owner_event_id"):
        _text(authorization, key, "S6_FINANCIAL_SCOPE_AUTHORIZATION_INVALID")
    _require_sha256(
        _text(authorization, "owner_receipt_sha256", "S6_FINANCIAL_SCOPE_AUTHORIZATION_INVALID"),
        "S6_FINANCIAL_SCOPE_AUTHORIZATION_INVALID",
    )


def _validate_candidate(
    candidate: Mapping[str, object],
    source: Mapping[str, object],
    result: Mapping[str, object],
    binding: Mapping[str, object],
    universe: Mapping[str, object],
    items: list[object],
    counts: Mapping[str, object],
    artifacts: list[object],
) -> None:
    candidate_binding = _mapping(candidate.get("binding"), "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    codes = _list(universe.get("asset_codes"), "S6_FINANCIAL_SCOPE_UNIVERSE_INVALID")
    summary = _mapping(result.get("candidate"), "S6_FINANCIAL_SCOPE_COVERAGE_INCOMPLETE")
    asset_count = len(items)
    expected_manifest_keys = {
        "schema",
        "status",
        "binding",
        "universe",
        "generated_at",
        "discovery_authorization",
        "items",
        "counts",
        "manifest_sha256",
    }
    expected_binding_keys = {
        "candidate_sha",
        "provider_id",
        "provider_name",
        "provider_identity_sha256",
        "contract_id",
        "contract_version",
        "contract_sha256",
        "parser_id",
        "parser_sha256",
        "deployment_region",
    }
    expected_manifest_count_keys = {
        "requested_assets",
        "captured_assets",
        "missing_assets",
        "duplicate_assets",
        "conflicting_assets",
        "logical_request_count",
    }
    manifest_counts = _mapping(candidate.get("counts"), "S6_FINANCIAL_SCOPE_COVERAGE_INCOMPLETE")
    candidate_sha = _text(source, "candidate_sha", "S6_FINANCIAL_SCOPE_SOURCE_INVALID")
    if (
        set(candidate) != expected_manifest_keys
        or set(candidate_binding) != expected_binding_keys
        or candidate.get("schema") != "data-center.financial-scope-discovery-manifest.v1"
        or candidate.get("status") != "pending_independent_review"
        or candidate.get("manifest_sha256")
        != canonical_sha256(
            {key: value for key, value in candidate.items() if key != "manifest_sha256"}
        )
        or candidate_binding.get("candidate_sha") != candidate_sha
        or candidate_binding.get("provider_name") != "akshare"
        or manifest_counts.keys() != expected_manifest_count_keys
        or manifest_counts.get("requested_assets") != asset_count
        or manifest_counts.get("captured_assets") != asset_count
        or manifest_counts.get("missing_assets") != 0
        or manifest_counts.get("duplicate_assets") != 0
        or manifest_counts.get("conflicting_assets") != 0
        or manifest_counts.get("logical_request_count") != asset_count * 2
        or universe.get("asset_count") != asset_count
        or universe.get("sha256") != canonical_sha256(codes)
        or len(codes) != asset_count
        or any(type(code) is not str or _ASSET_CODE.fullmatch(code) is None for code in codes)
        or cast(list[str], codes) != sorted(cast(list[str], codes))
        or len(set(cast(list[str], codes))) != asset_count
        or candidate_binding != dict(binding)
        or summary.get("manifest_sha256") != candidate.get("manifest_sha256")
        or summary.get("universe_sha256") != universe.get("sha256")
        or summary.get("coverage_count") != asset_count
        or summary.get("review_status") != "pending_independent_review"
        or source.get("authorization") != candidate.get("discovery_authorization")
    ):
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_COVERAGE_INCOMPLETE")
    _parse_datetime(candidate.get("generated_at"))
    expected_count_keys = {
        "requested",
        "captured",
        "failed_capture",
        "missing",
        "duplicates",
        "conflicts",
        "logical_requests",
        "physical_attempts",
        "artifact_writes",
        "raw_audit_writes",
        "fact_writes",
        "publication_writes",
    }
    if (
        set(counts) != expected_count_keys
        or counts.get("requested") != asset_count
        or counts.get("captured") != asset_count
        or counts.get("failed_capture") != 0
        or counts.get("missing") != 0
        or counts.get("duplicates") != 0
        or counts.get("conflicts") != 0
        or counts.get("logical_requests") != asset_count * 2
        or not asset_count * 2 <= _positive_int(counts, "physical_attempts") <= asset_count * 4
        or counts.get("artifact_writes") != asset_count * 2
        or counts.get("raw_audit_writes") != asset_count * 2
        or counts.get("fact_writes") != 0
        or counts.get("publication_writes") != 0
        or len(artifacts) != asset_count * 2
    ):
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_CAPACITY_INVALID")
    authorization = _mapping(
        candidate.get("discovery_authorization"), "S6_FINANCIAL_SCOPE_AUTHORIZATION_INVALID"
    )
    if set(authorization) != {"approval_id", "owner_event_id", "owner_receipt_sha256"}:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_AUTHORIZATION_INVALID")
    _require_sha256(
        _text(authorization, "owner_receipt_sha256", "S6_FINANCIAL_SCOPE_AUTHORIZATION_INVALID"),
        "S6_FINANCIAL_SCOPE_AUTHORIZATION_INVALID",
    )
    audit_ids: set[int] = set()
    capture_ids: set[str] = set()
    observed_codes: list[str] = []
    for raw_item in items:
        item = _mapping(raw_item, "S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
        expected_item_keys = {
            "asset_code",
            "announcement_date",
            "available_at",
            "native_row_ids",
            "financial_capture_id",
            "financial_body_sha256",
            "financial_raw_audit_id",
            "source_time_capture_id",
            "source_time_body_sha256",
            "source_time_raw_audit_id",
            "response_completed_at",
        }
        if set(item) != expected_item_keys:
            raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
        asset_code = _text(item, "asset_code", "S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
        native_row_ids = _list(item.get("native_row_ids"), "S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
        completed = _list(item.get("response_completed_at"), "S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
        try:
            announcement_date = date.fromisoformat(
                _text(item, "announcement_date", "S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
            )
        except ValueError:
            raise FinancialScopeCapacityReceiptError(
                "S6_FINANCIAL_SCOPE_EVIDENCE_INVALID"
            ) from None
        available_at = _parse_datetime(item.get("available_at"))
        completed_at = [_parse_datetime(value) for value in completed]
        row_ids = cast(list[str], native_row_ids)
        if (
            _ASSET_CODE.fullmatch(asset_code) is None
            or not row_ids
            or any(
                type(row_id) is not str or _NATIVE_ROW_ID.fullmatch(row_id) is None
                for row_id in native_row_ids
            )
            or any(not row_id.startswith(f"akshare:{asset_code}:") for row_id in row_ids)
            or any(not row_id.endswith(f":{announcement_date.isoformat()}") for row_id in row_ids)
            or len(set(row_ids)) != len(row_ids)
            or len(completed_at) != 2
            or any(not _is_utc(value) for value in completed_at)
            or available_at > min(completed_at)
        ):
            raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
        for text_key in ("financial_capture_id", "source_time_capture_id"):
            capture_id = _text(item, text_key, "S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
            if capture_id in capture_ids:
                raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
            capture_ids.add(capture_id)
        for audit_key in ("financial_raw_audit_id", "source_time_raw_audit_id"):
            audit_id = _positive_int(item, audit_key)
            if audit_id in audit_ids:
                raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
            audit_ids.add(audit_id)
        if item.get("financial_capture_id") == item.get("source_time_capture_id"):
            raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_EVIDENCE_INVALID")
        for digest_key in ("financial_body_sha256", "source_time_body_sha256"):
            _require_sha256(
                _text(item, digest_key, "S6_FINANCIAL_SCOPE_EVIDENCE_INVALID"),
                "S6_FINANCIAL_SCOPE_EVIDENCE_INVALID",
            )
        observed_codes.append(asset_code)
    if observed_codes != cast(list[str], codes):
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_COVERAGE_INCOMPLETE")
    root_name = _text(source, "artifact_root", "S6_FINANCIAL_SCOPE_ARTIFACT_INVALID")
    paths: set[str] = set()
    for value in artifacts:
        artifact = _mapping(value, "S6_FINANCIAL_SCOPE_ARTIFACT_INVALID")
        path = _text(artifact, "path", "S6_FINANCIAL_SCOPE_ARTIFACT_INVALID")
        digest = _text(artifact, "ciphertext_sha256", "S6_FINANCIAL_SCOPE_ARTIFACT_INVALID")
        size = artifact.get("size_bytes")
        if (
            set(artifact) != {"path", "size_bytes", "ciphertext_sha256"}
            or _ARTIFACT_PATH.fullmatch(path) is None
            or not path.startswith(f"{root_name}/")
            or _SHA256.fullmatch(digest) is None
            or type(size) is not int
            or size <= 0
            or path in paths
        ):
            raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_ARTIFACT_INVALID")
        paths.add(path)
    _require_sha256(
        _text(universe, "sha256", "S6_FINANCIAL_SCOPE_UNIVERSE_INVALID"),
        "S6_FINANCIAL_SCOPE_UNIVERSE_INVALID",
    )
    _require_sha256(
        _text(binding, "provider_identity_sha256", "S6_FINANCIAL_SCOPE_PROVIDER_INVALID"),
        "S6_FINANCIAL_SCOPE_PROVIDER_INVALID",
    )
    _require_sha256(
        _text(binding, "contract_sha256", "S6_FINANCIAL_SCOPE_SOURCE_INVALID"),
        "S6_FINANCIAL_SCOPE_SOURCE_INVALID",
    )
    _require_sha256(
        _text(binding, "parser_sha256", "S6_FINANCIAL_SCOPE_SOURCE_INVALID"),
        "S6_FINANCIAL_SCOPE_SOURCE_INVALID",
    )


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise FinancialScopeCapacityReceiptError(code)
    return cast(Mapping[str, object], value)


def _list(value: object, code: str) -> list[object]:
    if not isinstance(value, list):
        raise FinancialScopeCapacityReceiptError(code)
    return cast(list[object], value)


def _text(payload: Mapping[str, object], key: str, code: str) -> str:
    value = payload.get(key)
    if type(value) is not str or not value:
        raise FinancialScopeCapacityReceiptError(code)
    return value


def _positive_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if type(value) is not int or value <= 0:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_CAPACITY_INVALID")
    return value


def _require_sha256(value: str, code: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise FinancialScopeCapacityReceiptError(code)


def _parse_datetime(value: object) -> datetime:
    if type(value) is not str:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_TIME_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FinancialScopeCapacityReceiptError("S6_FINANCIAL_SCOPE_TIME_INVALID")
    return parsed


def _is_utc(value: datetime) -> bool:
    """Require the source report's capture completion timestamps to use UTC."""

    offset = value.utcoffset()
    return offset is not None and offset.total_seconds() == 0


__all__ = [
    "FinancialScopeCapacityReceiptError",
    "build_financial_scope_capacity_receipt",
    "canonical_sha256",
    "validate_financial_scope_capacity_receipt",
]
