"""Typed provider-native scope evidence for financial manifest bootstrap."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

_ASSET_CODE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_CANDIDATE_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_ROW_ID = re.compile(
    r"^akshare:[0-9]{6}\.(?:SH|SZ|BJ):[0-9]{4}-[0-9]{2}-[0-9]{2}:[0-9]{4}-[0-9]{2}-[0-9]{2}$"
)
_FINANCIAL_DATASET = "equity.financial.fact"
_SOURCE_TIME_DATASET = "equity.financial.source-time"
_REQUESTS_PER_ASSET = 2
_MAX_PHYSICAL_ATTEMPTS_PER_REQUEST = 2
_SOURCE_TIMEZONE = "Asia/Shanghai"


class FinancialScopeDiscoveryError(ValueError):
    """A sanitized, stable failure in authorized financial scope discovery."""

    def __init__(
        self,
        code: str,
        *,
        counts: FinancialScopeDiscoveryCounts | None = None,
        artifact_writes: int = 0,
        audit_writes: int = 0,
    ) -> None:
        """Store only an allowlisted code and aggregate counts, never provider payloads."""

        if code not in FINANCIAL_SCOPE_DISCOVERY_ERROR_CODES:
            code = "FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID"
        self.code = code
        self.counts = counts
        self.artifact_writes = artifact_writes
        self.audit_writes = audit_writes
        super().__init__(code)


FINANCIAL_SCOPE_DISCOVERY_ERROR_CODES = frozenset(
    {
        "FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_REQUIRED",
        "FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID",
        "FINANCIAL_SCOPE_DISCOVERY_BUDGET_EXCEEDED",
        "FINANCIAL_SCOPE_DISCOVERY_ENVIRONMENT_FORBIDDEN",
        "FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_INVALID",
        "FINANCIAL_SCOPE_DISCOVERY_COVERAGE_INCOMPLETE",
        "FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID",
        "FINANCIAL_SCOPE_DISCOVERY_CAPTURE_CONFLICT",
        "FINANCIAL_SCOPE_DISCOVERY_DUPLICATE_NATIVE_ROW",
        "FINANCIAL_SCOPE_DISCOVERY_REVIEW_REQUIRED",
        "FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID",
        "FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID",
        "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_CAPTURE_FAILED",
        "FINANCIAL_SCOPE_DISCOVERY_EGRESS_ROUTE_REQUIRED",
        "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_IDENTITY_INVALID",
        "FINANCIAL_SCOPE_DISCOVERY_RAW_ARTIFACT_INVALID",
        "FINANCIAL_SCOPE_DISCOVERY_RESPONSE_TRUNCATED",
        "FINANCIAL_SCOPE_DISCOVERY_AUTHORITY_INVALID",
        "FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_DRIFT",
    }
)


@dataclass(frozen=True, slots=True)
class FinancialScopeDiscoveryBinding:
    """Freeze provider, query contract, parser, and deployment-region identity."""

    candidate_sha: str
    provider_id: int
    provider_name: str
    provider_identity_sha256: str
    contract_id: str
    contract_version: str
    contract_sha256: str
    parser_id: str
    parser_sha256: str
    deployment_region: str

    def __post_init__(self) -> None:
        """Reject incomplete identities before provider access is considered."""

        if _CANDIDATE_SHA.fullmatch(self.candidate_sha) is None:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
        if type(self.provider_id) is not int or self.provider_id <= 0:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
        if not _valid_token(self.provider_name) or self.provider_name != "akshare":
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
        for value in (self.provider_identity_sha256, self.contract_sha256, self.parser_sha256):
            if _SHA256.fullmatch(value) is None:
                raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")
        for value in (
            self.contract_id,
            self.contract_version,
            self.parser_id,
            self.deployment_region,
        ):
            if not _valid_token(value):
                raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CONTRACT_INVALID")


@dataclass(frozen=True, slots=True)
class FinancialScopeDiscoveryRow:
    """One provider-native security, fiscal period, and announcement-date row."""

    asset_code: str
    period_end: date
    announcement_date: date

    def __post_init__(self) -> None:
        """Require canonical provider-native calendar dates and asset code."""

        if _ASSET_CODE.fullmatch(self.asset_code) is None:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if type(self.period_end) is not date or type(self.announcement_date) is not date:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")

    @property
    def native_row_id(self) -> str:
        """Return the owner-declared composite identity from native row fields."""

        return (
            f"akshare:{self.asset_code}:{self.period_end.isoformat()}:"
            f"{self.announcement_date.isoformat()}"
        )


@dataclass(frozen=True, slots=True)
class FinancialScopeDiscoveryCapture:
    """One retained provider-native response with a verified RawAudit identity."""

    asset_code: str
    provider_id: int
    provider_identity_sha256: str
    candidate_sha: str
    contract_id: str
    contract_version: str
    contract_sha256: str
    parser_id: str
    parser_sha256: str
    deployment_region: str
    capture_id: str
    body_sha256: str
    raw_audit_id: int
    dataset_key: str
    response_completed_at: datetime
    rows: tuple[FinancialScopeDiscoveryRow, ...]
    physical_request_attempts: int

    def __post_init__(self) -> None:
        """Require one exact asset-bound raw capture and its audit evidence."""

        if _ASSET_CODE.fullmatch(self.asset_code) is None:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if type(self.provider_id) is not int or self.provider_id <= 0:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if (
            _SHA256.fullmatch(self.provider_identity_sha256) is None
            or _SHA256.fullmatch(self.contract_sha256) is None
            or _SHA256.fullmatch(self.parser_sha256) is None
            or _CANDIDATE_SHA.fullmatch(self.candidate_sha) is None
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if not all(
            _valid_token(value)
            for value in (
                self.contract_id,
                self.contract_version,
                self.parser_id,
                self.deployment_region,
                self.capture_id,
            )
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if _SHA256.fullmatch(self.body_sha256) is None:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if type(self.raw_audit_id) is not int or self.raw_audit_id <= 0:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if self.dataset_key not in {_FINANCIAL_DATASET, _SOURCE_TIME_DATASET}:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if not isinstance(self.response_completed_at, datetime):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if (
            self.response_completed_at.tzinfo is None
            or self.response_completed_at.utcoffset() != timedelta(0)
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if not isinstance(self.rows, tuple) or not self.rows:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if any(type(row) is not FinancialScopeDiscoveryRow for row in self.rows):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if any(row.asset_code != self.asset_code for row in self.rows):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if (
            type(self.physical_request_attempts) is not int
            or not 1 <= self.physical_request_attempts <= _MAX_PHYSICAL_ATTEMPTS_PER_REQUEST
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")


@dataclass(frozen=True, slots=True)
class FinancialScopeDiscoveryAuthorization:
    """Authenticated owner authorization for one exact isolated discovery request."""

    approval_id: str
    candidate_sha: str
    approved_by: str
    recorded_by: str
    event_id: str
    receipt_sha256: str
    provider_id: int
    provider_identity_sha256: str
    contract_id: str
    contract_sha256: str
    deployment_region: str
    universe_count: int
    universe_sha256: str
    maximum_logical_requests: int
    maximum_physical_attempts: int
    maximum_rows_per_asset: int
    approved_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """Reject unbound, self-approved, expired-shape, or underspecified ceilings."""

        for text_value in (self.approval_id, self.approved_by, self.recorded_by, self.event_id):
            if not _valid_token(text_value):
                raise FinancialScopeDiscoveryError(
                    "FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID"
                )
        if _CANDIDATE_SHA.fullmatch(self.candidate_sha) is None:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
        if self.approved_by.casefold() == self.recorded_by.casefold():
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
        for value in (
            self.receipt_sha256,
            self.provider_identity_sha256,
            self.contract_sha256,
            self.universe_sha256,
        ):
            if _SHA256.fullmatch(value) is None:
                raise FinancialScopeDiscoveryError(
                    "FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID"
                )
        if not _valid_token(self.contract_id) or not _valid_token(self.deployment_region):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
        integer_values = (
            self.provider_id,
            self.universe_count,
            self.maximum_logical_requests,
            self.maximum_physical_attempts,
            self.maximum_rows_per_asset,
        )
        if any(type(value) is not int for value in integer_values) or min(integer_values) <= 0:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
        if self.maximum_logical_requests != self.universe_count * _REQUESTS_PER_ASSET:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
        if self.maximum_physical_attempts != (
            self.maximum_logical_requests * _MAX_PHYSICAL_ATTEMPTS_PER_REQUEST
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
        if self.maximum_rows_per_asset != 200:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
        _validate_aware(self.approved_at)
        _validate_aware(self.expires_at)
        if self.expires_at <= self.approved_at:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")

    @classmethod
    def for_universe(
        cls,
        *,
        binding: FinancialScopeDiscoveryBinding,
        asset_codes: tuple[str, ...],
        approval_id: str,
        approved_by: str,
        recorded_by: str,
        event_id: str,
        receipt_sha256: str,
        approved_at: datetime,
        expires_at: datetime,
        maximum_logical_requests: int,
        maximum_rows_per_asset: int,
    ) -> FinancialScopeDiscoveryAuthorization:
        """Build exact universe binding material without sorting away bad input."""

        if _canonical_universe(asset_codes) is None:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_INVALID")
        return cls(
            approval_id=approval_id,
            candidate_sha=binding.candidate_sha,
            approved_by=approved_by,
            recorded_by=recorded_by,
            event_id=event_id,
            receipt_sha256=receipt_sha256,
            provider_id=binding.provider_id,
            provider_identity_sha256=binding.provider_identity_sha256,
            contract_id=binding.contract_id,
            contract_sha256=binding.contract_sha256,
            deployment_region=binding.deployment_region,
            universe_count=len(asset_codes),
            universe_sha256=universe_sha256(asset_codes),
            maximum_logical_requests=maximum_logical_requests,
            maximum_physical_attempts=maximum_logical_requests * _MAX_PHYSICAL_ATTEMPTS_PER_REQUEST,
            maximum_rows_per_asset=maximum_rows_per_asset,
            approved_at=approved_at,
            expires_at=expires_at,
        )

    def validate(
        self,
        *,
        binding: FinancialScopeDiscoveryBinding,
        asset_codes: tuple[str, ...],
        now: datetime,
    ) -> None:
        """Bind the owner event to the full dynamic scope and exact request ceiling."""

        _validate_aware(now)
        if (
            self.approved_at > now
            or self.expires_at <= now
            or self.candidate_sha != binding.candidate_sha
            or self.provider_id != binding.provider_id
            or self.provider_identity_sha256 != binding.provider_identity_sha256
            or self.contract_id != binding.contract_id
            or self.contract_sha256 != binding.contract_sha256
            or self.deployment_region != binding.deployment_region
            or self.universe_count != len(asset_codes)
            or self.universe_sha256 != universe_sha256(asset_codes)
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
        expected_requests = len(asset_codes) * _REQUESTS_PER_ASSET
        if self.maximum_logical_requests != expected_requests:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_BUDGET_EXCEEDED")


@dataclass(frozen=True, slots=True)
class FinancialScopeDiscoveryCounts:
    """Aggregate run counts safe for reporting without exposing provider content."""

    requested_assets: int
    captured_assets: int
    failed_capture_assets: int
    missing_assets: int
    duplicate_assets: int
    conflicting_assets: int
    logical_request_count: int
    physical_request_attempts: int
    artifact_writes: int = 0
    raw_audit_writes: int = 0
    fact_write_count: int = 0
    publication_write_count: int = 0


@dataclass(frozen=True, slots=True)
class FinancialScopeDiscoveryAsset:
    """Latest source-native announcement date and its two capture proofs."""

    asset_code: str
    announcement_date: date
    available_at: datetime
    native_row_ids: tuple[str, ...]
    financial_capture_id: str
    financial_body_sha256: str
    financial_raw_audit_id: int
    source_time_capture_id: str
    source_time_body_sha256: str
    source_time_raw_audit_id: int
    response_completed_at: tuple[datetime, datetime]

    def __post_init__(self) -> None:
        """Require exact pair identities, typed source-time, and canonical row coverage."""

        if (
            _ASSET_CODE.fullmatch(self.asset_code) is None
            or type(self.announcement_date) is not date
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        _validate_aware(self.available_at)
        if not isinstance(self.native_row_ids, tuple) or not self.native_row_ids:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if tuple(sorted(set(self.native_row_ids))) != self.native_row_ids or any(
            _PROVIDER_ROW_ID.fullmatch(row_id) is None
            or not row_id.startswith(f"akshare:{self.asset_code}:")
            or not row_id.endswith(f":{self.announcement_date.isoformat()}")
            for row_id in self.native_row_ids
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if self.financial_capture_id == self.source_time_capture_id:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if self.financial_raw_audit_id == self.source_time_raw_audit_id:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        for value in (self.financial_capture_id, self.source_time_capture_id):
            if not _valid_token(value):
                raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        for value in (self.financial_body_sha256, self.source_time_body_sha256):
            if _SHA256.fullmatch(value) is None:
                raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if self.financial_raw_audit_id <= 0 or self.source_time_raw_audit_id <= 0:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if (
            not isinstance(self.response_completed_at, tuple)
            or len(self.response_completed_at) != 2
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        for completed_at in self.response_completed_at:
            _validate_aware(completed_at)
            if self.available_at > completed_at:
                raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")

    def to_dict(self) -> dict[str, object]:
        """Return review-safe evidence metadata with no response bodies or secrets."""

        return {
            "asset_code": self.asset_code,
            "announcement_date": self.announcement_date.isoformat(),
            "available_at": self.available_at.isoformat(),
            "native_row_ids": list(self.native_row_ids),
            "financial_capture_id": self.financial_capture_id,
            "financial_body_sha256": self.financial_body_sha256,
            "financial_raw_audit_id": self.financial_raw_audit_id,
            "source_time_capture_id": self.source_time_capture_id,
            "source_time_body_sha256": self.source_time_body_sha256,
            "source_time_raw_audit_id": self.source_time_raw_audit_id,
            "response_completed_at": [value.isoformat() for value in self.response_completed_at],
        }


@dataclass(frozen=True, slots=True)
class FinancialScopeDiscoveryCandidate:
    """Complete but unapproved source-native candidate manifest."""

    binding: FinancialScopeDiscoveryBinding
    discovery_approval_id: str
    discovery_owner_event_id: str
    discovery_owner_receipt_sha256: str
    asset_codes: tuple[str, ...]
    items: tuple[FinancialScopeDiscoveryAsset, ...]
    generated_at: datetime
    manifest_sha256: str

    def __post_init__(self) -> None:
        """Seal exact universe order, complete item coverage, and manifest digest."""

        _validate_aware(self.generated_at)
        canonical = _canonical_universe(self.asset_codes)
        if canonical is None or canonical != self.asset_codes or not self.items:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_INVALID")
        if (
            not all(
                _valid_token(value)
                for value in (self.discovery_approval_id, self.discovery_owner_event_id)
            )
            or _SHA256.fullmatch(self.discovery_owner_receipt_sha256) is None
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
        if tuple(item.asset_code for item in self.items) != self.asset_codes:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_COVERAGE_INCOMPLETE")
        if _SHA256.fullmatch(self.manifest_sha256) is None:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
        if self.manifest_sha256 != self.calculate_sha256():
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")

    @property
    def universe_sha256(self) -> str:
        """Return the digest of the complete dynamically discovered asset universe."""

        return universe_sha256(self.asset_codes)

    @property
    def coverage_count(self) -> int:
        """Return the number of dynamic universe members represented in the manifest."""

        return len(self.items)

    @property
    def logical_request_count(self) -> int:
        """Return two independent provider reads per active security."""

        return len(self.items) * _REQUESTS_PER_ASSET

    def payload(self) -> dict[str, object]:
        """Return the canonical schema payload that is covered by the manifest hash."""

        return {
            "schema": "data-center.financial-scope-discovery-manifest.v1",
            "status": "pending_independent_review",
            "binding": {
                "candidate_sha": self.binding.candidate_sha,
                "provider_id": self.binding.provider_id,
                "provider_name": self.binding.provider_name,
                "provider_identity_sha256": self.binding.provider_identity_sha256,
                "contract_id": self.binding.contract_id,
                "contract_version": self.binding.contract_version,
                "contract_sha256": self.binding.contract_sha256,
                "parser_id": self.binding.parser_id,
                "parser_sha256": self.binding.parser_sha256,
                "deployment_region": self.binding.deployment_region,
            },
            "universe": {
                "asset_count": len(self.asset_codes),
                "asset_codes": list(self.asset_codes),
                "sha256": self.universe_sha256,
            },
            "generated_at": self.generated_at.isoformat(),
            "discovery_authorization": {
                "approval_id": self.discovery_approval_id,
                "owner_event_id": self.discovery_owner_event_id,
                "owner_receipt_sha256": self.discovery_owner_receipt_sha256,
            },
            "items": [item.to_dict() for item in self.items],
            "counts": {
                "requested_assets": len(self.asset_codes),
                "captured_assets": len(self.items),
                "missing_assets": 0,
                "duplicate_assets": 0,
                "conflicting_assets": 0,
                "logical_request_count": self.logical_request_count,
            },
        }

    def calculate_sha256(self) -> str:
        """Hash the canonical provider binding, dynamic universe, and item evidence."""

        return _sha256(self.payload())

    def approve(
        self,
        *,
        owner: FinancialScopeManifestReview,
        reviewer: FinancialScopeManifestReview,
        environment: Literal["isolated", "production"],
        report_sha256: str,
        now: datetime,
    ) -> FinancialScopeReviewedManifest:
        """Require separate authenticated owner and reviewer events for this exact digest."""

        _validate_aware(now)
        for approval in (owner, reviewer):
            approval.validate(
                candidate=self,
                environment=environment,
                report_sha256=report_sha256,
                now=now,
            )
        if (
            owner.role != "data_owner"
            or reviewer.role != "independent_reviewer"
            or owner.approved_by.casefold() == reviewer.approved_by.casefold()
            or owner.event_id == reviewer.event_id
            or owner.approval_id == reviewer.approval_id
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID")
        return FinancialScopeReviewedManifest(
            candidate=self,
            owner_approval_id=owner.approval_id,
            owner_event_id=owner.event_id,
            reviewer_approval_id=reviewer.approval_id,
            reviewer_event_id=reviewer.event_id,
            environment=environment,
            report_sha256=report_sha256,
            reviewed_at=now,
        )


@dataclass(frozen=True, slots=True)
class FinancialScopeManifestReview:
    """Authenticated post-discovery approval bound to the complete manifest digest."""

    candidate_sha: str
    manifest_sha256: str
    universe_sha256: str
    provider_identity_sha256: str
    contract_sha256: str
    deployment_region: str
    approval_id: str
    approved_by: str
    recorded_by: str
    event_id: str
    receipt_sha256: str
    role: Literal["data_owner", "independent_reviewer"]
    environment: Literal["isolated", "production"]
    report_sha256: str
    approved_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """Require distinct authenticated recorder and approver identities."""

        for value in (
            self.manifest_sha256,
            self.universe_sha256,
            self.provider_identity_sha256,
            self.contract_sha256,
            self.receipt_sha256,
            self.report_sha256,
        ):
            if _SHA256.fullmatch(value) is None:
                raise FinancialScopeDiscoveryError(
                    "FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID"
                )
        if _CANDIDATE_SHA.fullmatch(self.candidate_sha) is None:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID")
        for value in (
            self.deployment_region,
            self.approval_id,
            self.approved_by,
            self.recorded_by,
            self.event_id,
        ):
            if not _valid_token(value):
                raise FinancialScopeDiscoveryError(
                    "FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID"
                )
        if self.role not in {"data_owner", "independent_reviewer"} or self.environment not in {
            "isolated",
            "production",
        }:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID")
        if self.approved_by.casefold() == self.recorded_by.casefold():
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID")
        _validate_aware(self.approved_at)
        _validate_aware(self.expires_at)
        if self.expires_at <= self.approved_at:
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID")

    def validate(
        self,
        *,
        candidate: FinancialScopeDiscoveryCandidate,
        environment: Literal["isolated", "production"],
        report_sha256: str,
        now: datetime,
    ) -> None:
        """Reject stale approvals or any candidate/provider/universe drift."""

        if (
            self.approved_at > now
            or self.approved_at < candidate.generated_at
            or self.expires_at <= now
            or self.candidate_sha != candidate.binding.candidate_sha
            or self.manifest_sha256 != candidate.manifest_sha256
            or self.universe_sha256 != candidate.universe_sha256
            or self.provider_identity_sha256 != candidate.binding.provider_identity_sha256
            or self.contract_sha256 != candidate.binding.contract_sha256
            or self.deployment_region != candidate.binding.deployment_region
            or self.environment != environment
            or self.report_sha256 != report_sha256
        ):
            raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID")


@dataclass(frozen=True, slots=True)
class FinancialScopeReviewedManifest:
    """Candidate manifest plus independent owner and reviewer event identities."""

    candidate: FinancialScopeDiscoveryCandidate
    owner_approval_id: str
    owner_event_id: str
    reviewer_approval_id: str
    reviewer_event_id: str
    environment: Literal["isolated", "production"]
    report_sha256: str
    reviewed_at: datetime

    @property
    def review_status(self) -> Literal["approved"]:
        """Expose the approval state only after both exact-digest checks have passed."""

        return "approved"


def universe_sha256(asset_codes: tuple[str, ...]) -> str:
    """Return canonical JSON digest for an already sorted complete active universe."""

    canonical = _canonical_universe(asset_codes)
    if canonical is None:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_INVALID")
    return _sha256(list(canonical))


def latest_source_time(announcement_date: date) -> datetime:
    """Derive conservative availability from provider-native date-only contract semantics."""

    if type(announcement_date) is not date:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
    source_zone = ZoneInfo(_SOURCE_TIMEZONE)
    return datetime.combine(
        announcement_date + timedelta(days=1),
        time.min,
        tzinfo=source_zone,
    ).astimezone(UTC)


def make_candidate(
    *,
    binding: FinancialScopeDiscoveryBinding,
    authorization: FinancialScopeDiscoveryAuthorization,
    asset_codes: tuple[str, ...],
    items: tuple[FinancialScopeDiscoveryAsset, ...],
    generated_at: datetime,
) -> FinancialScopeDiscoveryCandidate:
    """Build a complete candidate with its canonical immutable manifest digest."""

    provisional = object.__new__(FinancialScopeDiscoveryCandidate)
    object.__setattr__(provisional, "binding", binding)
    object.__setattr__(provisional, "discovery_approval_id", authorization.approval_id)
    object.__setattr__(provisional, "discovery_owner_event_id", authorization.event_id)
    object.__setattr__(
        provisional,
        "discovery_owner_receipt_sha256",
        authorization.receipt_sha256,
    )
    object.__setattr__(provisional, "asset_codes", asset_codes)
    object.__setattr__(provisional, "items", items)
    object.__setattr__(provisional, "generated_at", generated_at)
    object.__setattr__(provisional, "manifest_sha256", "0" * 64)
    digest = _sha256(provisional.payload())
    return FinancialScopeDiscoveryCandidate(
        binding=binding,
        discovery_approval_id=authorization.approval_id,
        discovery_owner_event_id=authorization.event_id,
        discovery_owner_receipt_sha256=authorization.receipt_sha256,
        asset_codes=asset_codes,
        items=items,
        generated_at=generated_at,
        manifest_sha256=digest,
    )


def build_asset_item(
    *,
    binding: FinancialScopeDiscoveryBinding,
    asset_code: str,
    financial: FinancialScopeDiscoveryCapture,
    source_time: FinancialScopeDiscoveryCapture,
) -> FinancialScopeDiscoveryAsset:
    """Compare duplicate provider reads and freeze the newest native announcement date."""

    _validate_capture_pair(
        binding=binding,
        asset_code=asset_code,
        financial=financial,
        source_time=source_time,
    )
    financial_rows = tuple(sorted(financial.rows, key=lambda row: row.native_row_id))
    source_rows = tuple(sorted(source_time.rows, key=lambda row: row.native_row_id))
    if len({row.native_row_id for row in financial_rows}) != len(financial_rows) or len(
        {row.native_row_id for row in source_rows}
    ) != len(source_rows):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_DUPLICATE_NATIVE_ROW")
    if financial_rows != source_rows:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_CONFLICT")
    newest_date = max(row.announcement_date for row in financial_rows)
    local_completion = min(
        financial.response_completed_at, source_time.response_completed_at
    ).astimezone(ZoneInfo(_SOURCE_TIMEZONE))
    if newest_date > local_completion.date():
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")
    row_ids = tuple(
        sorted(row.native_row_id for row in financial_rows if row.announcement_date == newest_date)
    )
    return FinancialScopeDiscoveryAsset(
        asset_code=asset_code,
        announcement_date=newest_date,
        available_at=latest_source_time(newest_date),
        native_row_ids=row_ids,
        financial_capture_id=financial.capture_id,
        financial_body_sha256=financial.body_sha256,
        financial_raw_audit_id=financial.raw_audit_id,
        source_time_capture_id=source_time.capture_id,
        source_time_body_sha256=source_time.body_sha256,
        source_time_raw_audit_id=source_time.raw_audit_id,
        response_completed_at=(financial.response_completed_at, source_time.response_completed_at),
    )


def _validate_capture_pair(
    *,
    binding: FinancialScopeDiscoveryBinding,
    asset_code: str,
    financial: FinancialScopeDiscoveryCapture,
    source_time: FinancialScopeDiscoveryCapture,
) -> None:
    """Require exact dataset roles, provider identity, dimensions, and distinct evidence IDs."""

    if (
        financial.asset_code != asset_code
        or source_time.asset_code != asset_code
        or financial.dataset_key != _FINANCIAL_DATASET
        or source_time.dataset_key != _SOURCE_TIME_DATASET
        or financial.provider_id != source_time.provider_id
        or financial.provider_identity_sha256 != source_time.provider_identity_sha256
        or financial.candidate_sha != source_time.candidate_sha
        or financial.contract_id != source_time.contract_id
        or financial.contract_version != source_time.contract_version
        or financial.contract_sha256 != source_time.contract_sha256
        or financial.parser_id != source_time.parser_id
        or financial.parser_sha256 != source_time.parser_sha256
        or financial.deployment_region != source_time.deployment_region
        or financial.provider_id != binding.provider_id
        or financial.provider_identity_sha256 != binding.provider_identity_sha256
        or financial.candidate_sha != binding.candidate_sha
        or financial.contract_id != binding.contract_id
        or financial.contract_version != binding.contract_version
        or financial.contract_sha256 != binding.contract_sha256
        or financial.parser_id != binding.parser_id
        or financial.parser_sha256 != binding.parser_sha256
        or financial.deployment_region != binding.deployment_region
        or financial.capture_id == source_time.capture_id
        or financial.raw_audit_id == source_time.raw_audit_id
    ):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_CAPTURE_INVALID")


def _canonical_universe(asset_codes: tuple[str, ...]) -> tuple[str, ...] | None:
    """Validate exact universe shape without silently sorting or deduplicating."""

    if not isinstance(asset_codes, tuple) or not asset_codes:
        return None
    if any(type(code) is not str or _ASSET_CODE.fullmatch(code) is None for code in asset_codes):
        return None
    if len(set(asset_codes)) != len(asset_codes):
        return None
    ordered = tuple(sorted(asset_codes))
    return ordered if ordered == asset_codes else None


def _validate_aware(value: datetime) -> None:
    """Require an aware UTC timestamp for an authorization or evidence clock."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID")


def _valid_token(value: object) -> bool:
    """Check a bounded opaque identifier without accepting control characters."""

    return (
        isinstance(value, str)
        and 1 <= len(value) <= 256
        and value == value.strip()
        and all(ord(character) >= 32 for character in value)
    )


def _sha256(value: object) -> str:
    """Hash canonical UTF-8 JSON without accepting non-finite numbers."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "FINANCIAL_SCOPE_DISCOVERY_ERROR_CODES",
    "FinancialScopeDiscoveryAuthorization",
    "FinancialScopeDiscoveryBinding",
    "FinancialScopeDiscoveryCapture",
    "FinancialScopeDiscoveryCounts",
    "FinancialScopeDiscoveryError",
    "FinancialScopeDiscoveryRow",
    "FinancialScopeDiscoveryAsset",
    "FinancialScopeDiscoveryCandidate",
    "FinancialScopeManifestReview",
    "FinancialScopeReviewedManifest",
    "build_asset_item",
    "latest_source_time",
    "make_candidate",
    "universe_sha256",
]
