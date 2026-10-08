"""Immutable state and evidence values for financial capacity workflows."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID

from apps.data_center.application.financial_slice_sync import FinancialSliceSyncResult

_ASSET_CODE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")

_SLICE_REQUESTS = 2

FinancialWorkflowStage = Literal[
    "qualification",
    "capacity_rehearsal",
    "formal_publication",
]


@dataclass(frozen=True, slots=True)
class FinancialCapacityManifestSnapshot:
    """One frozen manifest plus stable database-backed source revision identities."""

    slices: tuple[FinancialPublicationSlice, ...]
    active_universe_sha256: str
    typed_source_snapshot_sha256: str
    source_revision_sha256: str

    def __post_init__(self) -> None:
        """Require a stable revision derived from the universe and typed source snapshot."""

        if not self.slices:
            raise FinancialCapacityWorkflowError("financial capacity manifest is empty")
        for name in (
            "active_universe_sha256",
            "typed_source_snapshot_sha256",
            "source_revision_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        expected = _canonical_sha256(
            {
                "active_universe_sha256": self.active_universe_sha256,
                "typed_source_snapshot_sha256": self.typed_source_snapshot_sha256,
            }
        )
        if self.source_revision_sha256 != expected:
            raise FinancialCapacityWorkflowError("financial capacity source revision is invalid")

    @classmethod
    def build(
        cls,
        *,
        slices: tuple[FinancialPublicationSlice, ...],
        active_universe_sha256: str,
        typed_source_snapshot_sha256: str,
    ) -> FinancialCapacityManifestSnapshot:
        """Build a source revision from its universe and typed-fact database identities."""

        source_revision_sha256 = _canonical_sha256(
            {
                "active_universe_sha256": active_universe_sha256,
                "typed_source_snapshot_sha256": typed_source_snapshot_sha256,
            }
        )
        return cls(
            slices=slices,
            active_universe_sha256=active_universe_sha256,
            typed_source_snapshot_sha256=typed_source_snapshot_sha256,
            source_revision_sha256=source_revision_sha256,
        )


FinancialWorkflowStatus = Literal["running", "success", "partial", "failed", "blocked"]


class FinancialCapacityWorkflowError(ValueError):
    """Raised when checkpoint state cannot safely be created or resumed."""


class FinancialCapacityPublicationIndeterminateError(FinancialCapacityWorkflowError):
    """Identify a publication write whose durable commit outcome is not yet known."""

    def __init__(self, phase: Literal["staging", "activation"]) -> None:
        """Attach a stable retry reason while preserving the stored workflow plan."""

        if phase not in {"staging", "activation"}:
            raise ValueError("financial capacity indeterminate phase is invalid")
        self.phase = phase
        self.code = f"FINANCIAL_CAPACITY_PUBLICATION_{phase.upper()}_OUTCOME_INDETERMINATE"
        super().__init__("financial capacity publication commit outcome is indeterminate")


@dataclass(frozen=True, slots=True, order=True)
class FinancialPublicationSlice:
    """One normalized asset and announcement-date pair in a frozen manifest."""

    asset_code: str
    announcement_date: date

    def __post_init__(self) -> None:
        """Reject non-canonical slice dimensions before they enter a digest."""

        if type(self.asset_code) is not str or _ASSET_CODE.fullmatch(self.asset_code) is None:
            raise FinancialCapacityWorkflowError("financial capacity asset code is invalid")
        if type(self.announcement_date) is not date:
            raise FinancialCapacityWorkflowError("financial capacity announcement date is invalid")


@dataclass(frozen=True, slots=True)
class FinancialCapacityBinding:
    """Exact provider, parser, policy, candidate, and environment identity."""

    environment: str
    candidate_sha: str
    provider_id: int
    provider_name: str
    provider_source: str
    provider_identity_sha256: str
    contract_id: str
    contract_version: str
    contract_sha256: str
    parser_id: str
    parser_sha256: str
    deployment_region: str
    publication_policy_version: str
    publication_policy_sha256: str
    isolation_attestation_sha256: str = ""

    def __post_init__(self) -> None:
        """Require the one AKShare/policy-v3 identity and valid binding hashes."""

        if self.environment not in {"isolated", "production"}:
            raise FinancialCapacityWorkflowError("financial capacity environment is invalid")
        if _COMMIT_SHA.fullmatch(self.candidate_sha) is None:
            raise FinancialCapacityWorkflowError("financial capacity candidate SHA is invalid")
        if type(self.provider_id) is not int or self.provider_id <= 0:
            raise FinancialCapacityWorkflowError("financial capacity provider ID is invalid")
        if self.provider_source != "akshare" or self.publication_policy_version != "3":
            raise FinancialCapacityWorkflowError("AKShare policy-v3 binding is required")
        for name in (
            "provider_name",
            "contract_id",
            "contract_version",
            "parser_id",
            "deployment_region",
        ):
            _require_token(getattr(self, name), name)
        for name in (
            "provider_identity_sha256",
            "contract_sha256",
            "parser_sha256",
            "publication_policy_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        if self.environment == "isolated":
            _require_sha256(self.isolation_attestation_sha256, "isolation_attestation_sha256")
        elif self.isolation_attestation_sha256:
            raise FinancialCapacityWorkflowError(
                "production binding cannot carry an isolated-environment attestation"
            )

    def for_environment(self, environment: str) -> FinancialCapacityBinding:
        """Return the same provider/contract/policy identity for another stage."""

        return replace(
            self,
            environment=environment,
            isolation_attestation_sha256=(
                self.isolation_attestation_sha256 if environment == "isolated" else ""
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Return the canonical review representation of this binding."""

        return {
            "environment": self.environment,
            "candidate_sha": self.candidate_sha,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "provider_source": self.provider_source,
            "provider_identity_sha256": self.provider_identity_sha256,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_sha256": self.contract_sha256,
            "parser_id": self.parser_id,
            "parser_sha256": self.parser_sha256,
            "deployment_region": self.deployment_region,
            "publication_policy_version": self.publication_policy_version,
            "publication_policy_sha256": self.publication_policy_sha256,
            "isolation_attestation_sha256": self.isolation_attestation_sha256,
        }


@dataclass(frozen=True, slots=True)
class FinancialCapacitySliceEvidence:
    """Report-safe evidence for one successful dual-capture atomic fact write."""

    asset_code: str
    announcement_date: date
    financial_body_sha256: str
    source_time_body_sha256: str
    financial_body_size_bytes: int
    source_time_body_size_bytes: int
    financial_capture_id: str
    source_time_capture_id: str
    financial_raw_audit_id: str
    source_time_raw_audit_id: str
    financial_raw_audit_count: int
    source_time_raw_audit_count: int
    typed_financial_evidence_count: int
    source_time_witness_count: int
    atomic_fact_write_count: int
    stored: int
    duration_ms: int

    def __post_init__(self) -> None:
        """Require both retained bodies, both RawAudit links, and one atomic write."""

        FinancialPublicationSlice(self.asset_code, self.announcement_date)
        _require_sha256(self.financial_body_sha256, "financial_body_sha256")
        _require_sha256(self.source_time_body_sha256, "source_time_body_sha256")
        if self.financial_body_size_bytes <= 0 or self.source_time_body_size_bytes <= 0:
            raise FinancialCapacityWorkflowError("financial response body size is invalid")
        for name in (
            "financial_capture_id",
            "source_time_capture_id",
            "financial_raw_audit_id",
            "source_time_raw_audit_id",
        ):
            _require_token(getattr(self, name), name)
        if self.financial_capture_id == self.source_time_capture_id:
            raise FinancialCapacityWorkflowError("financial body captures must be distinct")
        if self.financial_raw_audit_id == self.source_time_raw_audit_id:
            raise FinancialCapacityWorkflowError("financial RawAudit rows must be distinct")
        if self.financial_raw_audit_count != 1 or self.source_time_raw_audit_count != 1:
            raise FinancialCapacityWorkflowError("each financial body requires one RawAudit row")
        if self.typed_financial_evidence_count <= 0 or self.source_time_witness_count <= 0:
            raise FinancialCapacityWorkflowError("typed financial evidence is incomplete")
        if self.typed_financial_evidence_count != self.source_time_witness_count:
            raise FinancialCapacityWorkflowError(
                "financial evidence witness coverage is incomplete"
            )
        if self.atomic_fact_write_count != 1 or self.stored <= 0 or self.duration_ms < 0:
            raise FinancialCapacityWorkflowError("financial slice write evidence is incomplete")

    def to_dict(self) -> dict[str, object]:
        """Return the exact evidence fields used by a capacity receipt."""

        return {
            "asset_code": self.asset_code,
            "announcement_date": self.announcement_date.isoformat(),
            "financial_body_sha256": self.financial_body_sha256,
            "source_time_body_sha256": self.source_time_body_sha256,
            "financial_body_size_bytes": self.financial_body_size_bytes,
            "source_time_body_size_bytes": self.source_time_body_size_bytes,
            "financial_capture_id": self.financial_capture_id,
            "source_time_capture_id": self.source_time_capture_id,
            "financial_raw_audit_id": self.financial_raw_audit_id,
            "source_time_raw_audit_id": self.source_time_raw_audit_id,
            "financial_raw_audit_count": self.financial_raw_audit_count,
            "source_time_raw_audit_count": self.source_time_raw_audit_count,
            "typed_financial_evidence_count": self.typed_financial_evidence_count,
            "source_time_witness_count": self.source_time_witness_count,
            "atomic_fact_write_count": self.atomic_fact_write_count,
            "stored": self.stored,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True, slots=True)
class FinancialCapacitySliceAttempt:
    """One exact one-slice UseCase result plus independently inspected evidence."""

    result: FinancialSliceSyncResult
    evidence: FinancialCapacitySliceEvidence | None
    observed_provider_requests: int | None
    duration_ms: int
    error_code: str = ""


@dataclass(frozen=True, slots=True)
class FinancialCapacityActivationIntent:
    """Durable pre-stage pointer CAS and real capture lineage for one workflow."""

    run_id: UUID
    activation_id: UUID
    expected_current_publication_id: str | None
    expected_current_publication_hash: str | None
    financial_raw_audit_id: str
    financial_raw_audit_content_hash: str
    ingested_run_id: UUID
    provider_key: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        """Require one fixed run, activation, pointer pair, and persisted audit reference."""

        if type(self.run_id) is not UUID or type(self.activation_id) is not UUID:
            raise FinancialCapacityWorkflowError("financial capacity activation UUID is invalid")
        if type(self.ingested_run_id) is not UUID or self.ingested_run_id != self.run_id:
            raise FinancialCapacityWorkflowError(
                "financial capacity ingestion identity must match its workflow run"
            )
        expected_id = self.expected_current_publication_id
        expected_hash = self.expected_current_publication_hash
        if (expected_id is None) != (expected_hash is None):
            raise FinancialCapacityWorkflowError(
                "financial capacity current pointer compare-and-swap pair is incomplete"
            )
        if expected_id is not None:
            try:
                if str(UUID(expected_id)) != expected_id:
                    raise ValueError("non-canonical pointer UUID")
            except (TypeError, ValueError) as exc:
                raise FinancialCapacityWorkflowError(
                    "financial capacity expected publication ID is invalid"
                ) from exc
            if _SHA256.fullmatch(expected_hash or "") is None:
                raise FinancialCapacityWorkflowError(
                    "financial capacity expected publication hash is invalid"
                )
        if (
            type(self.financial_raw_audit_id) is not str
            or not self.financial_raw_audit_id.isascii()
            or not self.financial_raw_audit_id.isdecimal()
            or int(self.financial_raw_audit_id) <= 0
            or str(int(self.financial_raw_audit_id)) != self.financial_raw_audit_id
        ):
            raise FinancialCapacityWorkflowError(
                "financial capacity activation RawAudit ID is invalid"
            )
        _require_sha256(self.financial_raw_audit_content_hash, "financial_raw_audit_content_hash")
        _require_token(self.provider_key, "provider_key")
        if (
            type(self.occurred_at) is not datetime
            or self.occurred_at.tzinfo is None
            or self.occurred_at.utcoffset() is None
        ):
            raise FinancialCapacityWorkflowError(
                "financial capacity activation audit time must be timezone-aware"
            )


@dataclass(frozen=True, slots=True)
class FinancialCapacityPublicationPlan:
    """Exact staged candidate and member seal saved before current-pointer activation."""

    intent: FinancialCapacityActivationIntent
    manifest_sha256: str
    candidate_publication_id: str
    candidate_publication_hash: str
    member_manifest_sha256: str

    def __post_init__(self) -> None:
        """Reject incomplete, malformed, or detached staged candidate identities."""

        if type(self.intent) is not FinancialCapacityActivationIntent:
            raise FinancialCapacityWorkflowError(
                "financial capacity publication plan has no exact activation intent"
            )
        _require_sha256(self.manifest_sha256, "manifest_sha256")
        try:
            if str(UUID(self.candidate_publication_id)) != self.candidate_publication_id:
                raise ValueError("non-canonical candidate UUID")
        except (TypeError, ValueError) as exc:
            raise FinancialCapacityWorkflowError(
                "financial capacity candidate publication ID is invalid"
            ) from exc
        _require_sha256(self.candidate_publication_hash, "candidate_publication_hash")
        _require_sha256(self.member_manifest_sha256, "member_manifest_sha256")


@dataclass(frozen=True, slots=True)
class GovernedFinancialQualificationCeiling:
    """Reviewed isolated request ceiling for one exact provider and frozen scope."""

    approval_id: str
    approved_by: str
    approved_at: datetime
    approval_receipt_sha256: str
    binding: FinancialCapacityBinding
    manifest_sha256: str
    maximum_slices: int
    maximum_provider_requests: int
    expires_at: datetime
    approved: bool

    def __post_init__(self) -> None:
        """Reject unbounded or mismatched isolated qualification approvals."""

        _require_token(self.approval_id, "approval_id")
        _require_token(self.approved_by, "approved_by")
        _require_sha256(self.approval_receipt_sha256, "approval_receipt_sha256")
        _require_utc_datetime(self.approved_at, "approved_at")
        _require_utc_datetime(self.expires_at, "expires_at")
        if self.approved_at > self.expires_at:
            raise FinancialCapacityWorkflowError(
                "qualification approval time must not be later than expiry"
            )
        _require_sha256(self.manifest_sha256, "manifest_sha256")
        if self.binding.environment != "isolated":
            raise FinancialCapacityWorkflowError("qualification ceiling binding is not isolated")
        if (
            type(self.maximum_slices) is not int
            or self.maximum_slices <= 0
            or type(self.maximum_provider_requests) is not int
            or self.maximum_provider_requests != self.maximum_slices * _SLICE_REQUESTS
        ):
            raise FinancialCapacityWorkflowError("governed qualification ceiling is inconsistent")
        if type(self.approved) is not bool:
            raise FinancialCapacityWorkflowError("governed qualification approval is invalid")


@dataclass(frozen=True, slots=True)
class GovernedFinancialCapacityRehearsalCeiling:
    """Reviewed full-universe isolated ceiling for one exact rehearsal manifest."""

    approval_id: str
    approved_by: str
    approved_at: datetime
    approval_receipt_sha256: str
    binding: FinancialCapacityBinding
    manifest_sha256: str
    maximum_slices: int
    maximum_provider_requests: int
    expires_at: datetime
    approved: bool

    def __post_init__(self) -> None:
        """Reject ceilings that do not cover one exact, full-scope rehearsal."""

        _require_token(self.approval_id, "approval_id")
        _require_token(self.approved_by, "approved_by")
        _require_sha256(self.approval_receipt_sha256, "approval_receipt_sha256")
        _require_utc_datetime(self.approved_at, "approved_at")
        _require_utc_datetime(self.expires_at, "expires_at")
        if self.approved_at > self.expires_at:
            raise FinancialCapacityWorkflowError(
                "capacity rehearsal approval time must not be later than expiry"
            )
        _require_sha256(self.manifest_sha256, "manifest_sha256")
        if self.binding.environment != "isolated":
            raise FinancialCapacityWorkflowError(
                "capacity rehearsal ceiling binding is not isolated"
            )
        if (
            type(self.maximum_slices) is not int
            or self.maximum_slices <= 0
            or type(self.maximum_provider_requests) is not int
            or self.maximum_provider_requests != self.maximum_slices * _SLICE_REQUESTS
        ):
            raise FinancialCapacityWorkflowError(
                "governed capacity rehearsal ceiling is inconsistent"
            )
        if type(self.approved) is not bool:
            raise FinancialCapacityWorkflowError("governed capacity rehearsal approval is invalid")


@dataclass(frozen=True, slots=True)
class GovernedFinancialProductionCeiling:
    """Reviewed ceiling bound to one exact successful qualification receipt."""

    approval_id: str
    approved_by: str
    approved_at: datetime
    approval_receipt_sha256: str
    receipt_sha256: str
    binding: FinancialCapacityBinding
    manifest_sha256: str
    maximum_slices: int
    maximum_provider_requests: int
    expires_at: datetime
    approved: bool

    def __post_init__(self) -> None:
        """Reject incomplete or unbounded governance approvals."""

        _require_token(self.approval_id, "approval_id")
        _require_token(self.approved_by, "approved_by")
        _require_sha256(self.approval_receipt_sha256, "approval_receipt_sha256")
        _require_utc_datetime(self.approved_at, "approved_at")
        _require_utc_datetime(self.expires_at, "expires_at")
        if self.approved_at > self.expires_at:
            raise FinancialCapacityWorkflowError(
                "production approval time must not be later than expiry"
            )
        _require_sha256(self.receipt_sha256, "receipt_sha256")
        _require_sha256(self.manifest_sha256, "manifest_sha256")
        if self.binding.environment != "production":
            raise FinancialCapacityWorkflowError("production ceiling binding is not production")
        if (
            type(self.maximum_slices) is not int
            or self.maximum_slices <= 0
            or type(self.maximum_provider_requests) is not int
            or self.maximum_provider_requests <= 0
            or self.maximum_provider_requests != self.maximum_slices * _SLICE_REQUESTS
        ):
            raise FinancialCapacityWorkflowError("governed financial ceiling is inconsistent")
        if type(self.approved) is not bool:
            raise FinancialCapacityWorkflowError("governed financial ceiling approval is invalid")


@dataclass(frozen=True, slots=True)
class FinancialCapacityReceipt:
    """Compact reviewable workload seal; details are read from paged evidence storage."""

    workflow_id: str
    stage: FinancialWorkflowStage
    approval_id: str
    binding: FinancialCapacityBinding
    manifest_count: int
    manifest_sha256: str
    source_revision_sha256: str
    evidence_count: int
    evidence_sha256: str
    outcome: FinancialWorkflowStatus
    review_status: Literal["pending_review", "not_eligible"]
    total_provider_request_budget: int
    provider_requests: int
    reserved_provider_requests: int
    requested: int
    succeeded: int
    failed: int
    stored: int
    raw_body_count: int
    raw_audit_count: int
    typed_evidence_count: int
    atomic_fact_write_count: int
    duration_ms: int
    error_codes: tuple[str, ...]
    started_at: datetime
    finished_at: datetime
    schema_version: Literal["v3"] = "v3"

    def __post_init__(self) -> None:
        """Keep receipt counters and hashes consistent with its frozen manifest."""

        _require_token(self.workflow_id, "workflow_id")
        if self.stage not in {"qualification", "capacity_rehearsal"}:
            raise FinancialCapacityWorkflowError("capacity receipt stage is invalid")
        _require_token(self.approval_id, "approval_id")
        if self.schema_version != "v3":
            raise FinancialCapacityWorkflowError("capacity receipt schema version is invalid")
        _require_sha256(self.manifest_sha256, "manifest_sha256")
        _require_sha256(self.source_revision_sha256, "source_revision_sha256")
        _require_sha256(self.evidence_sha256, "evidence_sha256")
        if type(self.manifest_count) is not int or self.manifest_count <= 0:
            raise FinancialCapacityWorkflowError("capacity receipt manifest count is invalid")
        if type(self.evidence_count) is not int or self.evidence_count < 0:
            raise FinancialCapacityWorkflowError("capacity receipt evidence count is invalid")
        if self.requested != self.succeeded + self.failed:
            raise FinancialCapacityWorkflowError("capacity receipt counters are inconsistent")
        counters = (
            self.total_provider_request_budget,
            self.provider_requests,
            self.reserved_provider_requests,
            self.requested,
            self.succeeded,
            self.failed,
            self.stored,
            self.raw_body_count,
            self.raw_audit_count,
            self.typed_evidence_count,
            self.atomic_fact_write_count,
            self.duration_ms,
        )
        if any(type(value) is not int for value in counters):
            raise FinancialCapacityWorkflowError("capacity receipt counters must be integers")
        if (
            min(
                self.total_provider_request_budget,
                self.provider_requests,
                self.reserved_provider_requests,
                self.requested,
                self.succeeded,
                self.failed,
                self.stored,
                self.raw_body_count,
                self.raw_audit_count,
                self.typed_evidence_count,
                self.atomic_fact_write_count,
                self.duration_ms,
            )
            < 0
        ):
            raise FinancialCapacityWorkflowError("capacity receipt counters cannot be negative")
        if self.provider_requests > self.total_provider_request_budget:
            raise FinancialCapacityWorkflowError("capacity receipt exceeds total request budget")
        if self.reserved_provider_requests > self.total_provider_request_budget:
            raise FinancialCapacityWorkflowError(
                "capacity receipt reservation exceeds total budget"
            )
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise FinancialCapacityWorkflowError("capacity receipt timestamps must be aware")
        if self.finished_at < self.started_at:
            raise FinancialCapacityWorkflowError("capacity receipt time range is invalid")
        if self.outcome == "success" and (
            self.requested != self.manifest_count
            or self.succeeded != self.manifest_count
            or self.failed != 0
            or self.provider_requests != self.manifest_count * _SLICE_REQUESTS
            or self.reserved_provider_requests != self.provider_requests
            or self.evidence_count != self.manifest_count
            or self.atomic_fact_write_count != self.manifest_count
        ):
            raise FinancialCapacityWorkflowError("successful capacity receipt is incomplete")
        if self.raw_body_count != self.raw_audit_count:
            raise FinancialCapacityWorkflowError("capacity receipt body and audit counts differ")

    @property
    def sha256(self) -> str:
        """Return the canonical immutable receipt digest."""

        return _canonical_sha256(self.to_dict())

    @property
    def qualification_approval_id(self) -> str:
        """Expose the legacy field name while old checkpoint readers are retired."""

        return self.approval_id

    def to_dict(self) -> dict[str, object]:
        """Return reviewable evidence without raw body bytes or credentials."""

        payload: dict[str, object] = {
            "schema": "financial-publication-capacity-receipt.v3",
            "workflow_id": self.workflow_id,
            "binding": self.binding.to_dict(),
            "manifest_count": self.manifest_count,
            "manifest_sha256": self.manifest_sha256,
            "source_revision_sha256": self.source_revision_sha256,
            "evidence_count": self.evidence_count,
            "evidence_sha256": self.evidence_sha256,
            "outcome": self.outcome,
            "review_status": self.review_status,
            "total_provider_request_budget": self.total_provider_request_budget,
            "provider_requests": self.provider_requests,
            "reserved_provider_requests": self.reserved_provider_requests,
            "requested": self.requested,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "stored": self.stored,
            "raw_body_count": self.raw_body_count,
            "raw_audit_count": self.raw_audit_count,
            "typed_evidence_count": self.typed_evidence_count,
            "atomic_fact_write_count": self.atomic_fact_write_count,
            "duration_ms": self.duration_ms,
            "error_codes": list(self.error_codes),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }
        payload["stage"] = self.stage
        payload["approval_id"] = self.approval_id
        return payload

    @classmethod
    def build(
        cls,
        *,
        workflow_id: str,
        stage: FinancialWorkflowStage,
        approval_id: str,
        binding: FinancialCapacityBinding,
        manifest_count: int,
        manifest_sha256: str,
        source_revision_sha256: str,
        outcome: FinancialWorkflowStatus,
        total_provider_request_budget: int,
        provider_requests: int,
        reserved_provider_requests: int,
        requested: int,
        succeeded: int,
        failed: int,
        stored: int,
        evidence_count: int,
        evidence_sha256: str,
        raw_body_count: int,
        raw_audit_count: int,
        typed_evidence_count: int,
        atomic_fact_write_count: int,
        error_codes: tuple[str, ...],
        started_at: datetime,
        finished_at: datetime,
    ) -> FinancialCapacityReceipt:
        """Aggregate per-slice retained body, audit, typed evidence, and timing data."""

        return cls(
            workflow_id=workflow_id,
            stage=stage,
            approval_id=approval_id,
            binding=binding,
            manifest_count=manifest_count,
            manifest_sha256=manifest_sha256,
            source_revision_sha256=source_revision_sha256,
            evidence_count=evidence_count,
            evidence_sha256=evidence_sha256,
            outcome=outcome,
            review_status="pending_review" if outcome == "success" else "not_eligible",
            total_provider_request_budget=total_provider_request_budget,
            provider_requests=provider_requests,
            reserved_provider_requests=reserved_provider_requests,
            requested=requested,
            succeeded=succeeded,
            failed=failed,
            stored=stored,
            raw_body_count=raw_body_count,
            raw_audit_count=raw_audit_count,
            typed_evidence_count=typed_evidence_count,
            atomic_fact_write_count=atomic_fact_write_count,
            duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
            error_codes=error_codes,
            started_at=started_at,
            finished_at=finished_at,
        )


@dataclass(frozen=True, slots=True)
class FinancialCapacityCheckpoint:
    """Compact workflow header referring to immutable manifest and evidence rows."""

    workflow_id: str
    stage: FinancialWorkflowStage
    binding: FinancialCapacityBinding
    manifest: tuple[FinancialPublicationSlice, ...]
    manifest_count: int
    manifest_sha256: str
    source_revision_sha256: str
    total_provider_request_budget: int
    status: FinancialWorkflowStatus
    next_slice_index: int
    reserved_provider_requests: int
    observed_provider_requests: int
    requested: int
    succeeded: int
    failed: int
    stored: int
    evidence: tuple[FinancialCapacitySliceEvidence, ...]
    evidence_count: int
    evidence_sha256: str
    raw_body_count: int
    raw_audit_count: int
    typed_evidence_count: int
    atomic_fact_write_count: int
    error_codes: tuple[str, ...]
    started_at: datetime
    run_id: str | None = None
    finished_at: datetime | None = None
    in_flight_slice_index: int | None = None
    in_flight_claim_token: str | None = None
    in_flight_claim_expires_at: datetime | None = None
    evidence_append: FinancialCapacitySliceEvidence | None = None
    evidence_previous_sha256: str | None = None
    capacity_receipt: FinancialCapacityReceipt | None = None
    qualification_ceiling: GovernedFinancialQualificationCeiling | None = None
    capacity_rehearsal_ceiling: GovernedFinancialCapacityRehearsalCeiling | None = None
    governed_ceiling: GovernedFinancialProductionCeiling | None = None
    activation_intent: FinancialCapacityActivationIntent | None = None
    publication_plan: FinancialCapacityPublicationPlan | None = None
    publication_hash: str | None = None
    blocked_reason: str | None = None
    revision: int = 0

    def __post_init__(self) -> None:
        """Keep exact activation state attached to one immutable workflow run."""

        if self.run_id is not None:
            try:
                if str(UUID(self.run_id)) != self.run_id:
                    raise ValueError("non-canonical run UUID")
            except (TypeError, ValueError) as exc:
                raise FinancialCapacityWorkflowError(
                    "financial capacity workflow run ID is invalid"
                ) from exc
        if self.activation_intent is not None and (
            self.run_id is None or str(self.activation_intent.run_id) != self.run_id
        ):
            raise FinancialCapacityWorkflowError(
                "financial capacity activation intent differs from workflow run"
            )
        if self.publication_plan is not None and (
            self.activation_intent is None
            or self.publication_plan.intent != self.activation_intent
            or self.publication_plan.manifest_sha256 != self.manifest_sha256
        ):
            raise FinancialCapacityWorkflowError(
                "financial capacity publication plan differs from its frozen checkpoint"
            )


@dataclass(frozen=True, slots=True)
class FinancialCapacityWorkflowResult:
    """One task invocation result plus its current durable checkpoint."""

    outcome: FinancialWorkflowStatus
    checkpoint: FinancialCapacityCheckpoint
    blocked_reason: str | None = None
    receipt: FinancialCapacityReceipt | None = None
    publication_hash: str | None = None


def _manifest_sha256(slices: tuple[FinancialPublicationSlice, ...]) -> str:

    material = [
        {
            "asset_code": item.asset_code,
            "announcement_date": item.announcement_date.isoformat(),
        }
        for item in slices
    ]

    return _canonical_sha256(material)


def _empty_evidence_sha256() -> str:
    """Return the domain-separated digest for a workflow with no completed slices."""

    return _canonical_sha256({"schema": "financial-capacity-evidence.v1", "items": []})


def _append_evidence_sha256(
    previous_sha256: str,
    *,
    index: int,
    evidence: FinancialCapacitySliceEvidence,
) -> str:
    """Extend the ordered evidence seal without retaining prior evidence in memory."""

    _require_sha256(previous_sha256, "previous evidence digest")
    if type(index) is not int or index < 0:
        raise FinancialCapacityWorkflowError("financial capacity evidence index is invalid")
    return _canonical_sha256(
        {
            "schema": "financial-capacity-evidence.v1",
            "previous_sha256": previous_sha256,
            "index": index,
            "evidence": evidence.to_dict(),
        }
    )


def _evidence_manifest_sha256(
    evidence: tuple[FinancialCapacitySliceEvidence, ...],
) -> str:
    """Calculate the ordered evidence seal for a bounded in-memory test or seed set."""

    digest = _empty_evidence_sha256()
    for index, item in enumerate(evidence):
        digest = _append_evidence_sha256(digest, index=index, evidence=item)
    return digest


def _canonical_sha256(payload: object) -> str:

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: object, field_name: str) -> str:

    if type(value) is not str or _SHA256.fullmatch(value) is None:

        raise FinancialCapacityWorkflowError(f"{field_name} must be a lowercase SHA-256 digest")

    return value


def _require_token(value: object, field_name: str) -> str:

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 300
        or any(character in value for character in ("\r", "\n"))
    ):

        raise FinancialCapacityWorkflowError(f"{field_name} must be a bounded token")

    return value


def _require_utc_datetime(value: object, field_name: str) -> None:
    """Require an explicit timezone-aware timestamp with a zero UTC offset."""

    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.utcoffset() != timedelta(0)
    ):
        raise FinancialCapacityWorkflowError(f"{field_name} must be a UTC-aware timestamp")
