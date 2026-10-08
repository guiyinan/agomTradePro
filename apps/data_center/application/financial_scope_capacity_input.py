"""Validate a persisted reviewed scope report before it becomes capacity input."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol, cast

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityBinding,
    FinancialCapacityManifestSnapshot,
    FinancialCapacityWorkflowError,
)
from apps.data_center.application.financial_scope_manifest_bootstrap import (
    FinancialScopeManifestReviewSource,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryAsset,
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryCandidate,
    FinancialScopeDiscoveryError,
    FinancialScopeReviewedManifest,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_SHA = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_POINTER_ENVIRONMENTS = frozenset({"isolated", "production"})
_POINTER_ERROR_CODES = frozenset(
    {
        "FINANCIAL_CAPACITY_SCOPE_POINTER_MISSING",
        "FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID",
        "FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED",
        "FINANCIAL_CAPACITY_SCOPE_BINDING_MISMATCH",
        "FINANCIAL_CAPACITY_SCOPE_ENVIRONMENT_MISMATCH",
        "FINANCIAL_CAPACITY_SCOPE_TYPED_FACT_MISMATCH",
    }
)
_REPORT_KEYS = frozenset(
    {
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
)
_CANDIDATE_KEYS = frozenset(
    {
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
)
_REPORT_BINDING_KEYS = frozenset(
    {
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
)


class FinancialScopeCapacityInputError(FinancialCapacityWorkflowError):
    """Carry one stable business code for a reviewed-scope input rejection."""

    def __init__(self, code: str) -> None:
        """Expose only an allowlisted scope-input code to task and CLI boundaries."""

        self.code = (
            code if code in _POINTER_ERROR_CODES else "FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID"
        )
        super().__init__(self.code.lower())


@dataclass(frozen=True, slots=True)
class FinancialScopeManifestCurrentPointer:
    """Persisted current report pointer plus the two event identities it consumed."""

    environment: Literal["isolated", "production"]
    report_payload: object
    report_sha256: str
    owner_approval_id: str
    owner_event_id: str
    reviewer_approval_id: str
    reviewer_event_id: str
    revision: int
    updated_by: str


class FinancialScopeManifestCurrentPointerSource(Protocol):
    """Read and atomically replace the current reviewed full-scope report pointer."""

    def get_current(
        self, *, environment: Literal["isolated", "production"]
    ) -> FinancialScopeManifestCurrentPointer | None:
        """Return the current pointer for one environment, if a pointer exists."""

    def set_current(
        self,
        pointer: FinancialScopeManifestCurrentPointer,
        *,
        expected_revision: int,
    ) -> FinancialScopeManifestCurrentPointer:
        """Atomically install the reviewed report if the pointer revision still matches."""


@dataclass(frozen=True, slots=True)
class FinancialScopeCapacityInput:
    """A report whose current review events have been reloaded and verified."""

    reviewed_manifest: FinancialScopeReviewedManifest
    environment: Literal["isolated", "production"]
    report_sha256: str


def prepare_financial_scope_manifest_pointer(
    *,
    report_payload: object,
    environment: Literal["isolated", "production"],
    review_source: FinancialScopeManifestReviewSource,
    updated_by: str,
    now: datetime,
) -> FinancialScopeManifestCurrentPointer:
    """Build a pointer only after a complete report and persisted dual review are verified."""

    candidate, report_sha256 = _parse_reviewable_report(
        report_payload,
        environment=environment,
    )
    try:
        reviews = review_source.get(
            candidate=candidate,
            environment=environment,
            report_sha256=report_sha256,
            now=now,
        )
        if reviews is None or len(reviews) != 2:
            raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED")
        owner, reviewer = reviews
        reviewed = candidate.approve(
            owner=owner,
            reviewer=reviewer,
            environment=environment,
            report_sha256=report_sha256,
            now=now,
        )
    except FinancialScopeCapacityInputError:
        raise
    except (FinancialScopeDiscoveryError, OSError, RuntimeError, TypeError, ValueError):
        raise FinancialScopeCapacityInputError(
            "FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED"
        ) from None
    if not updated_by or updated_by != updated_by.strip():
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return FinancialScopeManifestCurrentPointer(
        environment=environment,
        report_payload=report_payload,
        report_sha256=report_sha256,
        owner_approval_id=reviewed.owner_approval_id,
        owner_event_id=reviewed.owner_event_id,
        reviewer_approval_id=reviewed.reviewer_approval_id,
        reviewer_event_id=reviewed.reviewer_event_id,
        revision=0,
        updated_by=updated_by,
    )


def install_financial_scope_manifest_pointer(
    *,
    pointer_source: FinancialScopeManifestCurrentPointerSource,
    review_source: FinancialScopeManifestReviewSource,
    report_payload: object,
    environment: Literal["isolated", "production"],
    updated_by: str,
    now: datetime,
) -> FinancialScopeManifestCurrentPointer:
    """Validate persisted review events, then compare-and-swap the current report pointer."""

    if environment != "isolated":
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_ENVIRONMENT_MISMATCH")
    current = pointer_source.get_current(environment=environment)
    prepared = prepare_financial_scope_manifest_pointer(
        report_payload=report_payload,
        environment=environment,
        review_source=review_source,
        updated_by=updated_by,
        now=now,
    )
    return pointer_source.set_current(
        prepared,
        expected_revision=current.revision if current is not None else 0,
    )


def resolve_current_financial_scope_capacity_input(
    *,
    pointer_source: FinancialScopeManifestCurrentPointerSource,
    review_source: FinancialScopeManifestReviewSource,
    binding: FinancialCapacityBinding,
    environment: Literal["isolated", "production"],
    now: datetime,
) -> FinancialScopeCapacityInput:
    """Reload current pointer and review events, then verify exact runtime identities."""

    try:
        pointer = pointer_source.get_current(environment=environment)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID") from None
    if pointer is None:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_MISSING")
    if pointer.environment != environment:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_ENVIRONMENT_MISMATCH")
    candidate, report_sha256 = _parse_reviewable_report(
        pointer.report_payload,
        environment=environment,
    )
    if (
        report_sha256 != pointer.report_sha256
        or candidate.binding.candidate_sha != binding.candidate_sha
        or candidate.binding.provider_id != binding.provider_id
        or candidate.binding.provider_name != binding.provider_name
        or candidate.binding.provider_identity_sha256 != binding.provider_identity_sha256
        or candidate.binding.contract_id != binding.contract_id
        or candidate.binding.contract_version != binding.contract_version
        or candidate.binding.contract_sha256 != binding.contract_sha256
        or candidate.binding.parser_id != binding.parser_id
        or candidate.binding.parser_sha256 != binding.parser_sha256
        or candidate.binding.deployment_region != binding.deployment_region
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_BINDING_MISMATCH")
    try:
        reviews = review_source.get(
            candidate=candidate,
            environment=environment,
            report_sha256=report_sha256,
            now=now,
        )
        if reviews is None or len(reviews) != 2:
            raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED")
        owner, reviewer = reviews
        reviewed = candidate.approve(
            owner=owner,
            reviewer=reviewer,
            environment=environment,
            report_sha256=report_sha256,
            now=now,
        )
    except FinancialScopeCapacityInputError:
        raise
    except (FinancialScopeDiscoveryError, OSError, RuntimeError, TypeError, ValueError):
        raise FinancialScopeCapacityInputError(
            "FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED"
        ) from None
    if (
        reviewed.owner_approval_id != pointer.owner_approval_id
        or reviewed.owner_event_id != pointer.owner_event_id
        or reviewed.reviewer_approval_id != pointer.reviewer_approval_id
        or reviewed.reviewer_event_id != pointer.reviewer_event_id
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_APPROVAL_REQUIRED")
    return FinancialScopeCapacityInput(
        reviewed_manifest=reviewed,
        environment=environment,
        report_sha256=report_sha256,
    )


def validate_capacity_scope_input(
    *,
    scope_input: FinancialScopeCapacityInput,
    active_asset_codes: tuple[str, ...],
    snapshot: FinancialCapacityManifestSnapshot,
    typed_source_record_ids: Mapping[str, str],
) -> None:
    """Select scope only after typed facts agree; discovery RawAudit never becomes fact.

    The reviewed native rows and audit IDs define universe scope and cross-check identity only.
    Existing policy-v3 facts with a persisted source-time witness are the sole slice source.
    """

    candidate = scope_input.reviewed_manifest.candidate
    if (
        candidate.asset_codes != active_asset_codes
        or candidate.coverage_count != len(active_asset_codes)
        or candidate.universe_sha256 != snapshot.active_universe_sha256
        or candidate.universe_sha256 != _universe_sha256(active_asset_codes)
        or len(snapshot.slices) != len(active_asset_codes)
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_BINDING_MISMATCH")
    typed_by_asset = {item.asset_code: item for item in snapshot.slices}
    if len(typed_by_asset) != len(snapshot.slices):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_TYPED_FACT_MISMATCH")
    for scoped_item in candidate.items:
        typed_item = typed_by_asset.get(scoped_item.asset_code)
        typed_record_id = typed_source_record_ids.get(scoped_item.asset_code)
        if (
            typed_item is None
            or typed_item.announcement_date != scoped_item.announcement_date
            or type(typed_record_id) is not str
            or typed_record_id not in scoped_item.native_row_ids
        ):
            raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_TYPED_FACT_MISMATCH")


def _parse_reviewable_report(
    value: object,
    *,
    environment: Literal["isolated", "production"],
) -> tuple[FinancialScopeDiscoveryCandidate, str]:
    """Parse an exact successful disposable PostgreSQL discovery report and digest it."""

    if environment != "isolated" or environment not in _POINTER_ENVIRONMENTS:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_ENVIRONMENT_MISMATCH")
    report = _mapping(value)
    if (
        set(report) != _REPORT_KEYS
        or report.get("schema") != "release.financial-scope-discovery.v1"
        or report.get("kind") != "financial_scope_discovery"
        or report.get("outcome") != "success"
        or report.get("review_status") != "pending_independent_review"
        or _IMAGE_ID.fullmatch(_text(report, "candidate_image_id")) is None
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    started_at = _datetime(report, "started_at")
    finished_at = _datetime(report, "finished_at")
    if finished_at < started_at:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    database = _mapping(report.get("database"))
    if (
        set(database)
        != {
            "vendor",
            "scope",
            "release_rehearsal_guard",
            "name",
            "host",
            "isolation_attestation_sha256",
        }
        or report.get("artifact_root") != "financial-scope-artifacts"
        or database.get("vendor") != "postgresql"
        or database.get("scope") != "disposable"
        or database.get("release_rehearsal_guard") is not True
        or not _text(database, "name").startswith("agom_release_rehearsal_")
        or not _text(database, "host").startswith("agom-s6-postgres-")
        or _SHA256.fullmatch(_text(database, "isolation_attestation_sha256")) is None
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_ENVIRONMENT_MISMATCH")
    candidate_sha = _text(report, "candidate_sha")
    if _CANDIDATE_SHA.fullmatch(candidate_sha) is None:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    result = _mapping(report.get("result"))
    if (
        set(result)
        != {"schema", "outcome", "error_codes", "counts", "candidate", "candidate_manifest"}
        or result.get("schema") != "data-center.financial-scope-discovery-result.v1"
        or result.get("outcome") != "success"
        or result.get("error_codes") != []
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    candidate_manifest = _mapping(result.get("candidate_manifest"))
    candidate = _parse_candidate(candidate_manifest)
    if candidate.binding.candidate_sha != candidate_sha:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_BINDING_MISMATCH")
    summary = _mapping(result.get("candidate"))
    if (
        set(summary) != {"manifest_sha256", "universe_sha256", "coverage_count", "review_status"}
        or summary.get("review_status") != "pending_independent_review"
        or summary.get("manifest_sha256") != candidate.manifest_sha256
        or summary.get("universe_sha256") != candidate.universe_sha256
        or summary.get("coverage_count") != candidate.coverage_count
        or candidate_manifest.get("manifest_sha256") != candidate.manifest_sha256
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_BINDING_MISMATCH")
    _validate_report_binding(report, candidate)
    authorization = _mapping(report.get("authorization"))
    if (
        set(authorization) != {"approval_id", "owner_event_id", "owner_receipt_sha256"}
        or authorization.get("approval_id") != candidate.discovery_approval_id
        or authorization.get("owner_event_id") != candidate.discovery_owner_event_id
        or authorization.get("owner_receipt_sha256") != candidate.discovery_owner_receipt_sha256
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_BINDING_MISMATCH")
    counts = _mapping(result.get("counts"))
    count = candidate.coverage_count
    if (
        set(counts)
        != {
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
        or not count * 2 <= _positive_int(counts, "physical_attempts") <= count * 4
        or counts.get("requested") != count
        or counts.get("captured") != count
        or counts.get("failed_capture") != 0
        or counts.get("missing") != 0
        or counts.get("duplicates") != 0
        or counts.get("conflicts") != 0
        or counts.get("logical_requests") != count * 2
        or counts.get("artifact_writes") != count * 2
        or counts.get("raw_audit_writes") != count * 2
        or counts.get("fact_writes") != 0
        or counts.get("publication_writes") != 0
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return candidate, _canonical_sha256(value)


def _parse_candidate(payload: Mapping[str, object]) -> FinancialScopeDiscoveryCandidate:
    """Narrow the persisted candidate JSON into validated domain values."""

    try:
        binding_value = _mapping(payload.get("binding"))
        if set(payload) != _CANDIDATE_KEYS or payload.get("status") != "pending_independent_review":
            raise ValueError("candidate keys")
        if set(binding_value) != {
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
        }:
            raise ValueError("binding keys")
        binding = FinancialScopeDiscoveryBinding(
            candidate_sha=_text(binding_value, "candidate_sha"),
            provider_id=_positive_int(binding_value, "provider_id"),
            provider_name=_text(binding_value, "provider_name"),
            provider_identity_sha256=_text(binding_value, "provider_identity_sha256"),
            contract_id=_text(binding_value, "contract_id"),
            contract_version=_text(binding_value, "contract_version"),
            contract_sha256=_text(binding_value, "contract_sha256"),
            parser_id=_text(binding_value, "parser_id"),
            parser_sha256=_text(binding_value, "parser_sha256"),
            deployment_region=_text(binding_value, "deployment_region"),
        )
        universe = _mapping(payload.get("universe"))
        if set(universe) != {"asset_count", "asset_codes", "sha256"}:
            raise ValueError("universe keys")
        asset_codes = _string_tuple(universe.get("asset_codes"))
        items = tuple(_parse_candidate_item(item) for item in _object_tuple(payload.get("items")))
        counts = _mapping(payload.get("counts"))
        if set(counts) != {
            "requested_assets",
            "captured_assets",
            "missing_assets",
            "duplicate_assets",
            "conflicting_assets",
            "logical_request_count",
        }:
            raise ValueError("count keys")
        item_count = len(asset_codes)
        if (
            payload.get("schema") != "data-center.financial-scope-discovery-manifest.v1"
            or payload.get("status") != "pending_independent_review"
            or _positive_int(universe, "asset_count") != item_count
            or universe.get("sha256") != _text(universe, "sha256")
            or counts.get("requested_assets") != item_count
            or counts.get("captured_assets") != item_count
            or counts.get("missing_assets") != 0
            or counts.get("duplicate_assets") != 0
            or counts.get("conflicting_assets") != 0
            or counts.get("logical_request_count") != item_count * 2
        ):
            raise ValueError("manifest shape")
        authorization = _mapping(payload.get("discovery_authorization"))
        if set(authorization) != {"approval_id", "owner_event_id", "owner_receipt_sha256"}:
            raise ValueError("authorization keys")
        candidate = FinancialScopeDiscoveryCandidate(
            binding=binding,
            discovery_approval_id=_text(authorization, "approval_id"),
            discovery_owner_event_id=_text(authorization, "owner_event_id"),
            discovery_owner_receipt_sha256=_text(authorization, "owner_receipt_sha256"),
            asset_codes=asset_codes,
            items=items,
            generated_at=_datetime(payload, "generated_at"),
            manifest_sha256=_text(payload, "manifest_sha256"),
        )
    except FinancialScopeCapacityInputError:
        raise
    except (FinancialScopeDiscoveryError, KeyError, TypeError, ValueError):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID") from None
    if tuple(item.asset_code for item in candidate.items) != candidate.asset_codes:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    if universe.get(
        "sha256"
    ) != candidate.universe_sha256 or candidate.universe_sha256 != _universe_sha256(
        candidate.asset_codes
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_BINDING_MISMATCH")
    return candidate


def _parse_candidate_item(value: object) -> FinancialScopeDiscoveryAsset:
    """Parse one discovery item while preserving raw-audit and native-row identities."""

    payload = _mapping(value)
    if set(payload) != {
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
    }:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    completed = _string_tuple(payload.get("response_completed_at"))
    if len(completed) != 2:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return FinancialScopeDiscoveryAsset(
        asset_code=_text(payload, "asset_code"),
        announcement_date=_date(payload, "announcement_date"),
        available_at=_datetime(payload, "available_at"),
        native_row_ids=_string_tuple(payload.get("native_row_ids")),
        financial_capture_id=_text(payload, "financial_capture_id"),
        financial_body_sha256=_text(payload, "financial_body_sha256"),
        financial_raw_audit_id=_positive_int(payload, "financial_raw_audit_id"),
        source_time_capture_id=_text(payload, "source_time_capture_id"),
        source_time_body_sha256=_text(payload, "source_time_body_sha256"),
        source_time_raw_audit_id=_positive_int(payload, "source_time_raw_audit_id"),
        response_completed_at=(_parse_datetime(completed[0]), _parse_datetime(completed[1])),
    )


def _validate_report_binding(
    report: Mapping[str, object],
    candidate: FinancialScopeDiscoveryCandidate,
) -> None:
    """Require the report projection to name the exact provider and parser binding."""

    binding = _mapping(report.get("binding"))
    expected = {
        "provider_id": candidate.binding.provider_id,
        "provider_name": candidate.binding.provider_name,
        "provider_identity_sha256": candidate.binding.provider_identity_sha256,
        "contract_id": candidate.binding.contract_id,
        "contract_version": candidate.binding.contract_version,
        "contract_sha256": candidate.binding.contract_sha256,
        "parser_id": candidate.binding.parser_id,
        "parser_sha256": candidate.binding.parser_sha256,
        "deployment_region": candidate.binding.deployment_region,
    }
    if set(binding) != _REPORT_BINDING_KEYS or any(
        binding.get(key) != value for key, value in expected.items()
    ):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_BINDING_MISMATCH")


def _mapping(value: object) -> Mapping[str, object]:
    """Require an object with string keys at an external JSON boundary."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return value


def _object_tuple(value: object) -> tuple[object, ...]:
    """Require a JSON array without accepting strings or arbitrary iterables."""

    if type(value) is not list:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return tuple(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    """Require a JSON array containing only non-empty strings."""

    items = _object_tuple(value)
    if any(type(item) is not str or not item for item in items):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return tuple(cast(str, item) for item in items)


def _text(payload: Mapping[str, object], name: str) -> str:
    """Read one exact non-empty trimmed string."""

    value = payload.get(name)
    if type(value) is not str or not value or value != value.strip():
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return value


def _positive_int(payload: Mapping[str, object], name: str) -> int:
    """Read one positive integer, rejecting bool and coerced values."""

    value = payload.get(name)
    if type(value) is not int or value <= 0:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return value


def _date(payload: Mapping[str, object], name: str) -> date:
    """Read one canonical ISO date."""

    value = _text(payload, name)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID") from None
    if parsed.isoformat() != value:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return parsed


def _datetime(payload: Mapping[str, object], name: str) -> datetime:
    """Read one aware ISO datetime."""

    return _parse_datetime(_text(payload, name))


def _parse_datetime(value: str) -> datetime:
    """Parse an aware ISO timestamp without interpreting naive local time."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return parsed


def _canonical_sha256(value: object) -> str:
    """Hash one JSON object using the governance canonical encoding."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID") from None
    digest = hashlib.sha256(encoded).hexdigest()
    if _SHA256.fullmatch(digest) is None:
        raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
    return digest


def _universe_sha256(asset_codes: tuple[str, ...]) -> str:
    """Hash the canonical sorted universe using the domain's JSON representation."""

    return _canonical_sha256(list(asset_codes))


__all__ = [
    "FinancialScopeCapacityInput",
    "FinancialScopeCapacityInputError",
    "FinancialScopeManifestCurrentPointer",
    "FinancialScopeManifestCurrentPointerSource",
    "install_financial_scope_manifest_pointer",
    "prepare_financial_scope_manifest_pointer",
    "resolve_current_financial_scope_capacity_input",
    "validate_capacity_scope_input",
]
