"""Validate one production-bound S6 financial scope capacity import."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityBinding,
    GovernedFinancialProductionCeiling,
)
from apps.data_center.application.financial_scope_capacity_input import (
    FinancialScopeCapacityInputError,
    _parse_reviewable_report,
)
from apps.data_center.application.financial_scope_capacity_receipt import (
    FinancialScopeCapacityReceiptError,
    canonical_sha256,
    validate_financial_scope_capacity_receipt,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryError,
    FinancialScopeManifestReview,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_SHA = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_RELEASE_SCHEMA = "release.rehearsal-manifest.v1"
_CAPACITY_KIND = "financial_scope_capacity"
_REQUIRED_REPORT_KINDS = frozenset(
    {
        "real_response_unit_replay",
        "full_universe_capacity",
        "production_policy_parity",
        "isolated_write_rehearsal",
        "akshare_financial_slice",
        "financial_scope_capacity",
        "stage_environment_preflight",
        "isolated_database_migrations",
        "candidate_regression_evidence",
    }
)


class FinancialScopeCapacityImportError(ValueError):
    """One stable, safe rejection code for production capacity imports."""

    def __init__(self, code: str) -> None:
        """Expose only an allowlisted import diagnostic."""

        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FinancialScopeCapacityArtifactDigest:
    """One encrypted artifact that was opened and hashed from the copied bundle."""

    path: str
    size_bytes: int
    ciphertext_sha256: str


def prepare_financial_scope_capacity_import_record(
    *,
    release_manifest: object,
    release_manifest_sha256: str,
    capacity_receipt: object,
    capacity_receipt_raw_sha256: str,
    scope_report: object,
    scope_report_raw_sha256: str,
    artifacts: tuple[FinancialScopeCapacityArtifactDigest, ...],
    runtime_binding: FinancialCapacityBinding,
    active_asset_codes: tuple[str, ...],
    reviews: tuple[FinancialScopeManifestReview, ...],
    production_ceiling: GovernedFinancialProductionCeiling,
    production_ceiling_event_id: str,
    production_ceiling_record_sha256: str,
    imported_by: str,
    now: datetime,
) -> dict[str, object]:
    """Build an immutable ledger payload after exact runtime and authority checks."""

    _require_sha256(release_manifest_sha256, "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    _require_sha256(capacity_receipt_raw_sha256, "FINANCIAL_SCOPE_IMPORT_RECEIPT_INVALID")
    _require_sha256(scope_report_raw_sha256, "FINANCIAL_SCOPE_IMPORT_SOURCE_INVALID")
    _require_sha256(production_ceiling_record_sha256, "FINANCIAL_SCOPE_IMPORT_CEILING_INVALID")
    if runtime_binding.environment != "production" or not _aware(now):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_ENVIRONMENT_INVALID")
    if not imported_by or imported_by != imported_by.strip():
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_ACTOR_INVALID")
    if (
        not production_ceiling_event_id
        or production_ceiling_event_id != production_ceiling_event_id.strip()
    ):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_CEILING_INVALID")

    manifest = _mapping(release_manifest, "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    manifest_identity = _parse_release_manifest(manifest)
    expected_release_asset_codes = _manifest_release_asset_codes(manifest)
    frozen_provider_identities = _manifest_provider_identities(manifest)
    if expected_release_asset_codes != active_asset_codes:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_UNIVERSE_MISMATCH")
    if (
        canonical_sha256([dict(item) for item in frozen_provider_identities])
        != manifest_identity["provider_identities_sha256"]
    ):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_BINDING_INVALID")
    if manifest_identity["capacity_report_sha256"] != capacity_receipt_raw_sha256:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_BINDING_INVALID")
    try:
        candidate, review_report_sha256 = _parse_reviewable_report(
            scope_report,
            environment="isolated",
        )
    except (FinancialScopeCapacityInputError, FinancialScopeDiscoveryError, TypeError, ValueError):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_SOURCE_INVALID") from None

    if (
        manifest_identity["candidate_sha"] != runtime_binding.candidate_sha
        or _CANDIDATE_SHA.fullmatch(runtime_binding.candidate_sha) is None
        or candidate.binding.candidate_sha != runtime_binding.candidate_sha
    ):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_CANDIDATE_MISMATCH")
    _validate_runtime_provider(candidate.binding, runtime_binding)
    if (
        not active_asset_codes
        or active_asset_codes != tuple(sorted(set(active_asset_codes)))
        or candidate.asset_codes != active_asset_codes
    ):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_UNIVERSE_MISMATCH")

    receipt_map = _mapping(capacity_receipt, "FINANCIAL_SCOPE_IMPORT_RECEIPT_INVALID")
    receipt_sha256 = _text(receipt_map, "receipt_sha256", "FINANCIAL_SCOPE_IMPORT_RECEIPT_INVALID")
    _require_sha256(receipt_sha256, "FINANCIAL_SCOPE_IMPORT_RECEIPT_INVALID")
    _validate_artifact_projection(scope_report, artifacts)
    try:
        validate_financial_scope_capacity_receipt(
            receipt=capacity_receipt,
            scope_report=scope_report,
            scope_report_sha256=scope_report_raw_sha256,
            expected_candidate=runtime_binding.candidate_sha,
            expected_image_id=manifest_identity["candidate_image_id"],
            expected_trade_date=manifest_identity["target_trade_date"],
            expected_release_universe_sha256=manifest_identity["universe_sha256"],
            expected_provider_identities_sha256=manifest_identity["provider_identities_sha256"],
            expected_release_asset_codes=expected_release_asset_codes,
            frozen_provider_identities=frozen_provider_identities,
        )
    except FinancialScopeCapacityReceiptError:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_RECEIPT_INVALID") from None

    if (
        receipt_map.get("candidate_image_id") != manifest_identity["candidate_image_id"]
        or receipt_map.get("target_trade_date") != manifest_identity["target_trade_date"]
        or receipt_map.get("universe_sha256") != manifest_identity["universe_sha256"]
        or receipt_map.get("provider_identities_sha256")
        != manifest_identity["provider_identities_sha256"]
    ):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_BINDING_INVALID")

    if len(reviews) != 2:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_REVIEW_REQUIRED")
    by_role = {review.role: review for review in reviews}
    if set(by_role) != {"data_owner", "independent_reviewer"}:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_REVIEW_REQUIRED")
    owner = by_role["data_owner"]
    reviewer = by_role["independent_reviewer"]
    if owner.event_id == reviewer.event_id:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_REVIEW_REQUIRED")
    try:
        reviewed = candidate.approve(
            owner=owner,
            reviewer=reviewer,
            environment="production",
            report_sha256=review_report_sha256,
            now=now,
        )
    except FinancialScopeDiscoveryError:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_REVIEW_REQUIRED") from None

    capacity = _mapping(receipt_map.get("capacity"), "FINANCIAL_SCOPE_IMPORT_CAPACITY_INVALID")
    asset_count = len(active_asset_codes)
    logical_request_ceiling = _positive_int(
        capacity, "logical_request_ceiling", "FINANCIAL_SCOPE_IMPORT_CAPACITY_INVALID"
    )
    physical_attempt_ceiling = _positive_int(
        capacity, "physical_attempt_ceiling", "FINANCIAL_SCOPE_IMPORT_CAPACITY_INVALID"
    )
    if (
        capacity.get("asset_count") != asset_count
        or logical_request_ceiling != asset_count * 2
        or physical_attempt_ceiling != asset_count * 4
        or capacity.get("logical_request_count") != logical_request_ceiling
        or capacity.get("fact_writes") != 0
        or capacity.get("publication_writes") != 0
    ):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_CAPACITY_INVALID")

    _validate_production_ceiling(
        production_ceiling=production_ceiling,
        runtime_binding=runtime_binding,
        receipt_sha256=receipt_sha256,
        scope_manifest_sha256=candidate.manifest_sha256,
        asset_count=asset_count,
        logical_request_ceiling=logical_request_ceiling,
        now=now,
    )

    record: dict[str, object] = {
        "schema": "data-center.financial-scope-capacity-import.v1",
        "environment": "production",
        "release_manifest_sha256": release_manifest_sha256,
        "capacity_receipt_raw_sha256": capacity_receipt_raw_sha256,
        "scope_report_raw_sha256": scope_report_raw_sha256,
        "scope_report_review_sha256": review_report_sha256,
        "receipt_sha256": receipt_sha256,
        "scope_pointer_sha256": receipt_map["scope_pointer_sha256"],
        "candidate_sha": runtime_binding.candidate_sha,
        "candidate_image_id": manifest_identity["candidate_image_id"],
        "target_trade_date": manifest_identity["target_trade_date"],
        "release_universe_sha256": manifest_identity["universe_sha256"],
        "provider_identities_sha256": manifest_identity["provider_identities_sha256"],
        "scope_manifest_sha256": candidate.manifest_sha256,
        "financial_universe_sha256": candidate.universe_sha256,
        "financial_provider_id": candidate.binding.provider_id,
        "financial_provider_identity_sha256": candidate.binding.provider_identity_sha256,
        "source_revision_sha256": receipt_map["source_revision_sha256"],
        "evidence_ledger_sha256": receipt_map["evidence_ledger_sha256"],
        "artifact_ledger_sha256": receipt_map["artifact_ledger_sha256"],
        "capacity": dict(capacity),
        "runtime_binding": runtime_binding.to_dict(),
        "review": {
            "owner_approval_id": reviewed.owner_approval_id,
            "owner_event_id": reviewed.owner_event_id,
            "reviewer_approval_id": reviewed.reviewer_approval_id,
            "reviewer_event_id": reviewed.reviewer_event_id,
        },
        "production_ceiling": {
            "approval_id": production_ceiling.approval_id,
            "event_id": production_ceiling_event_id,
            "record_sha256": production_ceiling_record_sha256,
            "maximum_slices": production_ceiling.maximum_slices,
            "maximum_provider_requests": production_ceiling.maximum_provider_requests,
        },
        "imported_by": imported_by,
        "imported_at": now.isoformat(),
        "capacity_receipt": dict(receipt_map),
        "scope_report": cast(
            dict[str, object], _mapping(scope_report, "FINANCIAL_SCOPE_IMPORT_SOURCE_INVALID")
        ),
    }
    record["record_sha256"] = canonical_sha256(record)
    return record


def _parse_release_manifest(manifest: Mapping[str, object]) -> dict[str, str]:
    expected_keys = {
        "schema",
        "candidate_sha",
        "target_trade_date",
        "universe_sha256",
        "provider_identities_sha256",
        "provider_settings_raw_file_sha256",
        "provider_settings_canonical_payload_sha256",
        "candidate_image_id",
        "release_tag",
        "image_tag",
        "release_universe",
        "provider_identities",
        "reports",
    }
    if set(manifest) != expected_keys or manifest.get("schema") != _RELEASE_SCHEMA:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    reports = manifest.get("reports")
    if not isinstance(reports, list):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    by_kind: dict[str, Mapping[str, object]] = {}
    for value in reports:
        report = _mapping(value, "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
        if set(report) != {"kind", "path", "sha256"}:
            raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
        kind = _text(report, "kind", "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
        if kind in by_kind:
            raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
        by_kind[kind] = report
    if set(by_kind) != _REQUIRED_REPORT_KINDS:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    capacity_report = by_kind[_CAPACITY_KIND]
    if capacity_report.get("path") != "financial_scope_capacity/financial-full-scope-capacity.json":
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    values = {
        "candidate_sha": _text(
            manifest, "candidate_sha", "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID"
        ),
        "target_trade_date": _text(
            manifest, "target_trade_date", "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID"
        ),
        "universe_sha256": _sha_text(manifest, "universe_sha256"),
        "provider_identities_sha256": _sha_text(manifest, "provider_identities_sha256"),
        "candidate_image_id": _text(
            manifest, "candidate_image_id", "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID"
        ),
        "capacity_report_sha256": _sha_text(capacity_report, "sha256"),
    }
    _require_sha256(
        _text(
            manifest, "provider_settings_raw_file_sha256", "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID"
        ),
        "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID",
    )
    _require_sha256(
        _text(
            manifest,
            "provider_settings_canonical_payload_sha256",
            "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID",
        ),
        "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID",
    )
    if (
        _CANDIDATE_SHA.fullmatch(values["candidate_sha"]) is None
        or _IMAGE_ID.fullmatch(values["candidate_image_id"]) is None
        or re.fullmatch(
            r"[0-9]{14}", _text(manifest, "release_tag", "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
        )
        is None
        or _text(manifest, "image_tag", "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
        != f"agomtradepro-web:{_text(manifest, 'release_tag', 'FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID')}"
    ):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    try:
        parsed_date = date.fromisoformat(values["target_trade_date"])
    except ValueError:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID") from None
    if parsed_date.isoformat() != values["target_trade_date"]:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    return values


def _manifest_release_asset_codes(manifest: Mapping[str, object]) -> tuple[str, ...]:
    release_universe = _mapping(
        manifest.get("release_universe"), "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID"
    )
    codes = release_universe.get("asset_codes")
    if (
        set(release_universe) != {"asset_count", "asset_codes", "sha256"}
        or not isinstance(codes, list)
        or not codes
        or any(
            type(code) is not str or re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", code) is None
            for code in codes
        )
        or codes != sorted(set(codes))
        or release_universe.get("asset_count") != len(codes)
        or release_universe.get("sha256") != canonical_sha256(codes)
    ):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    return tuple(cast(list[str], codes))


def _manifest_provider_identities(
    manifest: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    raw_identities = manifest.get("provider_identities")
    if not isinstance(raw_identities, list) or not raw_identities:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
    identities: list[Mapping[str, object]] = []
    for raw in cast(list[object], raw_identities):
        identity = _mapping(raw, "FINANCIAL_SCOPE_IMPORT_MANIFEST_INVALID")
        normalized = dict(identity)
        if normalized.get("deployment_region") is None:
            normalized.pop("deployment_region", None)
        identities.append(normalized)
    return tuple(identities)


def _validate_runtime_provider(
    binding: FinancialScopeDiscoveryBinding,
    runtime: FinancialCapacityBinding,
) -> None:
    if (
        binding.provider_id != runtime.provider_id
        or binding.provider_name != runtime.provider_name
        or binding.provider_identity_sha256 != runtime.provider_identity_sha256
        or binding.contract_id != runtime.contract_id
        or binding.contract_version != runtime.contract_version
        or binding.contract_sha256 != runtime.contract_sha256
        or binding.parser_id != runtime.parser_id
        or binding.parser_sha256 != runtime.parser_sha256
        or binding.deployment_region != runtime.deployment_region
    ):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_PROVIDER_MISMATCH")


def _validate_artifact_projection(
    scope_report: object,
    artifacts: tuple[FinancialScopeCapacityArtifactDigest, ...],
) -> None:
    source = _mapping(scope_report, "FINANCIAL_SCOPE_IMPORT_SOURCE_INVALID")
    raw_values = source.get("encrypted_artifacts")
    if not isinstance(raw_values, list) or len(raw_values) != len(artifacts):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_ARTIFACT_MISMATCH")
    expected: dict[str, tuple[int, str]] = {}
    for value in raw_values:
        raw_artifact = _mapping(value, "FINANCIAL_SCOPE_IMPORT_ARTIFACT_MISMATCH")
        path = _text(raw_artifact, "path", "FINANCIAL_SCOPE_IMPORT_ARTIFACT_MISMATCH")
        size = _positive_int(
            raw_artifact,
            "size_bytes",
            "FINANCIAL_SCOPE_IMPORT_ARTIFACT_MISMATCH",
        )
        digest = _sha_text(raw_artifact, "ciphertext_sha256")
        if path in expected:
            raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_ARTIFACT_MISMATCH")
        expected[path] = (size, digest)
    observed: dict[str, tuple[int, str]] = {}
    for artifact_digest in artifacts:
        if (
            not artifact_digest.path
            or artifact_digest.path in observed
            or type(artifact_digest.size_bytes) is not int
            or artifact_digest.size_bytes <= 0
            or _SHA256.fullmatch(artifact_digest.ciphertext_sha256) is None
        ):
            raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_ARTIFACT_MISMATCH")
        observed[artifact_digest.path] = (
            artifact_digest.size_bytes,
            artifact_digest.ciphertext_sha256,
        )
    if expected != observed:
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_ARTIFACT_MISMATCH")


def _validate_production_ceiling(
    *,
    production_ceiling: GovernedFinancialProductionCeiling,
    runtime_binding: FinancialCapacityBinding,
    receipt_sha256: str,
    scope_manifest_sha256: str,
    asset_count: int,
    logical_request_ceiling: int,
    now: datetime,
) -> None:
    if (
        production_ceiling.binding != runtime_binding
        or production_ceiling.receipt_sha256 != receipt_sha256
        or production_ceiling.manifest_sha256 != scope_manifest_sha256
        or production_ceiling.maximum_slices != asset_count
        or production_ceiling.maximum_provider_requests != logical_request_ceiling
        or production_ceiling.approved is not True
        or production_ceiling.approved_at > now
        or production_ceiling.expires_at <= now
    ):
        raise FinancialScopeCapacityImportError("FINANCIAL_SCOPE_IMPORT_CEILING_INVALID")


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise FinancialScopeCapacityImportError(code)
    return cast(Mapping[str, object], value)


def _text(payload: Mapping[str, object], key: str, code: str) -> str:
    value = payload.get(key)
    if type(value) is not str or not value or value != value.strip():
        raise FinancialScopeCapacityImportError(code)
    return value


def _sha_text(payload: Mapping[str, object], key: str) -> str:
    value = _text(payload, key, "FINANCIAL_SCOPE_IMPORT_IDENTITY_INVALID")
    _require_sha256(value, "FINANCIAL_SCOPE_IMPORT_IDENTITY_INVALID")
    return value


def _positive_int(payload: Mapping[str, object], key: str, code: str) -> int:
    value = payload.get(key)
    if type(value) is not int or value <= 0:
        raise FinancialScopeCapacityImportError(code)
    return value


def _require_sha256(value: str, code: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise FinancialScopeCapacityImportError(code)


def _aware(value: datetime) -> bool:
    offset = value.utcoffset()
    return value.tzinfo is not None and offset is not None


__all__ = [
    "FinancialScopeCapacityArtifactDigest",
    "FinancialScopeCapacityImportError",
    "prepare_financial_scope_capacity_import_record",
]
