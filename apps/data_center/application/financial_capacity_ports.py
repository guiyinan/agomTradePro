"""Application ports and checkpoint helpers for financial capacity workflows."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from threading import Lock
from typing import Literal, Protocol
from uuid import UUID

from apps.data_center.application.financial_capacity_models import (
    _SLICE_REQUESTS,
    FinancialCapacityActivationIntent,
    FinancialCapacityBinding,
    FinancialCapacityCheckpoint,
    FinancialCapacityManifestSnapshot,
    FinancialCapacityPublicationPlan,
    FinancialCapacityReceipt,
    FinancialCapacitySliceAttempt,
    FinancialCapacitySliceEvidence,
    FinancialCapacityWorkflowError,
    FinancialPublicationSlice,
    FinancialWorkflowStage,
    GovernedFinancialCapacityRehearsalCeiling,
    GovernedFinancialProductionCeiling,
    GovernedFinancialQualificationCeiling,
    _append_evidence_sha256,
)


class FinancialCapacityBindingSource(Protocol):
    """Read the exact active provider, parser, policy, and environment identity."""

    def snapshot(self, *, environment: str, candidate_sha: str) -> FinancialCapacityBinding:
        """Return a complete exact runtime binding or fail closed."""


class FinancialCapacityBuildIdentitySource(Protocol):
    """Read the immutable source commit recorded by the currently running image."""

    def source_commit(self) -> str:
        """Return the validated image source commit or raise on missing identity."""


class FinancialCapacityManifestSource(Protocol):
    """Freeze one typed isolated seed or the complete production asset workload."""

    def freeze(
        self,
        *,
        stage: FinancialWorkflowStage,
        environment: Literal["isolated", "production"],
        binding: FinancialCapacityBinding,
    ) -> FinancialCapacityManifestSnapshot:
        """Return the manifest and stable database-backed source revision."""


class FinancialCapacitySliceRunner(Protocol):
    """Run exactly one slice through the controlled AKShare use case."""

    def execute(
        self,
        *,
        binding: FinancialCapacityBinding,
        item: FinancialPublicationSlice,
        run_id: UUID,
    ) -> FinancialCapacitySliceAttempt:
        """Return counts and separately verified body, RawAudit, and fact evidence."""


class FinancialCapacityPublisher(Protocol):
    """Stage and activate one exact policy-v3 candidate after full success."""

    def begin_activation(
        self,
        *,
        binding: FinancialCapacityBinding,
        run_id: UUID,
        evidence: tuple[FinancialCapacitySliceEvidence, ...],
    ) -> FinancialCapacityActivationIntent:
        """Freeze the current-pointer CAS and one exact workflow RawAudit identity."""

    def stage(
        self,
        *,
        binding: FinancialCapacityBinding,
        intent: FinancialCapacityActivationIntent,
        asset_codes: tuple[str, ...],
        manifest_sha256: str,
    ) -> FinancialCapacityPublicationPlan:
        """Persist or recover the exact candidate/member snapshot without activation."""

    def activate(
        self,
        *,
        binding: FinancialCapacityBinding,
        plan: FinancialCapacityPublicationPlan,
    ) -> str:
        """CAS activate the exact staged candidate, or verify its same-identity replay."""


class FinancialCapacityAuthorityValidator(Protocol):
    """Revalidate the same DATA-02 authority at each formal write boundary."""

    def is_current(self) -> bool:
        """Return whether the latched authority still permits the next write."""


class FinancialQualificationCeilingSource(Protocol):
    """Read the reviewed isolated request ceiling bound to one exact workload."""

    def get_qualification(
        self,
        *,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
    ) -> GovernedFinancialQualificationCeiling | None:
        """Return the exact reviewed qualification ceiling or None when absent."""


class FinancialCapacityRehearsalCeilingSource(Protocol):
    """Read the reviewed isolated ceiling bound to a complete rehearsal manifest."""

    def get_capacity_rehearsal(
        self,
        *,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
    ) -> GovernedFinancialCapacityRehearsalCeiling | None:
        """Return the exact approved full-scope rehearsal ceiling or None."""


class FinancialProductionCeilingSource(Protocol):
    """Read the current human-governed production ceiling for one receipt."""

    def get(
        self,
        *,
        receipt_sha256: str,
        candidate_sha: str,
        manifest_sha256: str,
    ) -> GovernedFinancialProductionCeiling | None:
        """Return an exact approved ceiling, or None when governance has not approved it."""


class FinancialScopeCapacityImportAuthoritySource(Protocol):
    """Revalidate one persisted S6 import and its production authority chain."""

    def load_record_sha256(self, import_id: str) -> str | None:
        """Return the sealed digest read from one persisted import record."""

    def validate_current(
        self,
        *,
        import_id: str,
        record_sha256: str,
        workflow_id: str,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
        active_universe_sha256: str,
        source_revision_sha256: str,
        now: datetime,
        expected_consumed: bool,
    ) -> str | None:
        """Return a stable block reason unless the import still authorizes this exact scope."""

    def consume_formal_start(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        now: datetime,
    ) -> None:
        """Append the one-time consumption event inside the checkpoint transaction."""


class FinancialCapacityCheckpointRepository(Protocol):
    """Persist one workflow using revision-checked updates."""

    def create(self, checkpoint: FinancialCapacityCheckpoint) -> FinancialCapacityCheckpoint:
        """Insert the initial frozen state or reject a duplicate workflow ID."""

    def get(self, workflow_id: str) -> FinancialCapacityCheckpoint | None:
        """Load one workflow checkpoint by exact identifier."""

    def save(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        expected_revision: int,
    ) -> FinancialCapacityCheckpoint:
        """Atomically replace the checkpoint if its revision still matches."""

    def manifest_item(self, workflow_id: str, index: int) -> FinancialPublicationSlice:
        """Read one immutable manifest item by ordinal."""

    def stream_manifest(self, workflow_id: str) -> tuple[FinancialPublicationSlice, ...]:
        """Read the complete manifest once at a terminal validation boundary."""

    def stream_evidence(self, workflow_id: str) -> tuple[FinancialCapacitySliceEvidence, ...]:
        """Read append-only slice evidence once at a receipt or activation boundary."""


class InMemoryFinancialCapacityCheckpointRepository:
    """Small revision-aware checkpoint store for deterministic application tests."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, FinancialCapacityCheckpoint] = {}
        self._manifest_rows: dict[str, tuple[FinancialPublicationSlice, ...]] = {}
        self._evidence_rows: dict[str, list[FinancialCapacitySliceEvidence]] = {}
        self._consumed_approval_ids: set[str] = set()
        self._consumed_receipt_sha256s: set[str] = set()
        self._lock = Lock()

    def create(self, checkpoint: FinancialCapacityCheckpoint) -> FinancialCapacityCheckpoint:
        """Insert the initial frozen state or reject a duplicate workflow ID."""

        with self._lock:
            if checkpoint.workflow_id in self._checkpoints:
                raise FinancialCapacityWorkflowError("financial capacity workflow already exists")
            approval_id = _checkpoint_approval_id(checkpoint)
            if approval_id is not None and approval_id in self._consumed_approval_ids:
                raise FinancialCapacityWorkflowError(
                    "financial capacity approval or receipt has already been consumed"
                )
            receipt_sha256 = _checkpoint_consumed_receipt_sha256(checkpoint)
            if receipt_sha256 is not None and receipt_sha256 in self._consumed_receipt_sha256s:
                raise FinancialCapacityWorkflowError(
                    "financial capacity approval or receipt has already been consumed"
                )
            created = replace(checkpoint, revision=1)
            self._checkpoints[created.workflow_id] = created
            self._manifest_rows[created.workflow_id] = created.manifest
            self._evidence_rows[created.workflow_id] = list(created.evidence)
            if approval_id is not None:
                self._consumed_approval_ids.add(approval_id)
            if receipt_sha256 is not None:
                self._consumed_receipt_sha256s.add(receipt_sha256)
            return created

    def get(self, workflow_id: str) -> FinancialCapacityCheckpoint | None:
        """Load one workflow checkpoint by exact identifier."""

        return self._checkpoints.get(workflow_id)

    def manifest_item(self, workflow_id: str, index: int) -> FinancialPublicationSlice:
        """Read one item without rebuilding the complete scope."""

        return self._manifest_rows[workflow_id][index]

    def stream_manifest(self, workflow_id: str) -> tuple[FinancialPublicationSlice, ...]:
        """Return the complete in-memory manifest at a terminal boundary."""

        return self._manifest_rows[workflow_id]

    def stream_evidence(self, workflow_id: str) -> tuple[FinancialCapacitySliceEvidence, ...]:
        """Return the evidence ledger at a receipt or activation boundary."""

        return tuple(self._evidence_rows[workflow_id])

    def save(
        self,
        checkpoint: FinancialCapacityCheckpoint,
        *,
        expected_revision: int,
    ) -> FinancialCapacityCheckpoint:
        """Atomically replace the checkpoint if its revision still matches."""

        with self._lock:
            current = self._checkpoints.get(checkpoint.workflow_id)
            if current is None or current.revision != expected_revision:
                raise FinancialCapacityWorkflowError(
                    "financial capacity checkpoint revision changed"
                )
            saved = replace(checkpoint, revision=expected_revision + 1)
            if saved.evidence_append is not None:
                expected_count = saved.evidence_count - 1
                current = self._checkpoints[saved.workflow_id]
                if (
                    len(self._evidence_rows[saved.workflow_id]) != expected_count
                    or saved.evidence_previous_sha256 != current.evidence_sha256
                    or saved.evidence_sha256
                    != _append_evidence_sha256(
                        current.evidence_sha256,
                        index=expected_count,
                        evidence=saved.evidence_append,
                    )
                ):
                    raise FinancialCapacityWorkflowError(
                        "financial capacity evidence append seal changed"
                    )
                manifest_item = self.manifest_item(saved.workflow_id, expected_count)
                if (
                    saved.evidence_append.asset_code != manifest_item.asset_code
                    or saved.evidence_append.announcement_date != manifest_item.announcement_date
                ):
                    raise FinancialCapacityWorkflowError(
                        "financial capacity evidence does not match its manifest item"
                    )
                self._evidence_rows[saved.workflow_id].append(saved.evidence_append)
                saved = replace(
                    saved,
                    evidence_append=None,
                    evidence_previous_sha256=None,
                )
            self._checkpoints[saved.workflow_id] = saved
            return saved


class ProtocolClock(Protocol):
    """Return the current timezone-aware workflow timestamp."""

    def __call__(self) -> datetime:
        """Return current UTC time."""


def _valid_attempt(
    checkpoint: FinancialCapacityCheckpoint,
    item_index: int,
    attempt: FinancialCapacitySliceAttempt,
    item: FinancialPublicationSlice,
) -> bool:

    result = attempt.result

    return (
        (
            (
                type(attempt.observed_provider_requests) is int
                and attempt.observed_provider_requests >= 0
                and (
                    attempt.observed_provider_requests <= _SLICE_REQUESTS
                    or result.outcome != "success"
                )
            )
            or (attempt.observed_provider_requests is None and result.outcome != "success")
        )
        and type(attempt.duration_ms) is int
        and attempt.duration_ms >= 0
        and result.source == "akshare"
        and result.provider_id == checkpoint.binding.provider_id
        and result.requested == 1
        and result.planned_provider_requests == _SLICE_REQUESTS
        and result.requested == result.succeeded + result.failed
        and (
            attempt.evidence is None
            or (
                attempt.evidence.asset_code == item.asset_code
                and attempt.evidence.announcement_date == item.announcement_date
            )
        )
        and (
            result.outcome != "success"
            or (
                result.succeeded == 1
                and result.failed == 0
                and result.stored > 0
                and result.atomic_fact_write_count == 1
                and attempt.evidence is not None
                and attempt.evidence.stored == result.stored
                and attempt.observed_provider_requests == _SLICE_REQUESTS
            )
        )
    )


def _ceiling_matches(
    *,
    ceiling: GovernedFinancialProductionCeiling,
    receipt: FinancialCapacityReceipt,
    binding: FinancialCapacityBinding,
    manifest_sha256: str,
    now: datetime,
) -> bool:

    return (
        ceiling.approved
        and ceiling.approved_at <= now
        and ceiling.expires_at > now
        and ceiling.receipt_sha256 == receipt.sha256
        and ceiling.binding == binding
        and ceiling.manifest_sha256 == manifest_sha256
        and ceiling.maximum_slices == receipt.manifest_count
        and ceiling.maximum_provider_requests == receipt.manifest_count * _SLICE_REQUESTS
    )


def _qualification_ceiling_matches(
    *,
    ceiling: GovernedFinancialQualificationCeiling,
    binding: FinancialCapacityBinding,
    manifest_sha256: str,
    maximum_slices: int,
    now: datetime,
) -> bool:
    """Check an active isolated approval against the exact frozen qualification."""

    return (
        ceiling.approved
        and ceiling.approved_at <= now
        and ceiling.expires_at > now
        and ceiling.binding == binding
        and ceiling.manifest_sha256 == manifest_sha256
        and ceiling.maximum_slices == maximum_slices
        and ceiling.maximum_provider_requests == maximum_slices * _SLICE_REQUESTS
    )


def _capacity_rehearsal_ceiling_matches(
    *,
    ceiling: GovernedFinancialCapacityRehearsalCeiling,
    binding: FinancialCapacityBinding,
    manifest_sha256: str,
    maximum_slices: int,
    now: datetime,
) -> bool:
    """Check an active approval against the exact full isolated workload."""

    return (
        ceiling.approved
        and ceiling.approved_at <= now
        and ceiling.expires_at > now
        and ceiling.binding == binding
        and ceiling.manifest_sha256 == manifest_sha256
        and ceiling.maximum_slices == maximum_slices
        and ceiling.maximum_provider_requests == maximum_slices * _SLICE_REQUESTS
    )


def _checkpoint_approval_id(checkpoint: FinancialCapacityCheckpoint) -> str | None:
    """Return the one-time approval reserved by a qualification or formal start."""

    if checkpoint.stage == "qualification" and checkpoint.qualification_ceiling is not None:
        return checkpoint.qualification_ceiling.approval_id
    if (
        checkpoint.stage == "capacity_rehearsal"
        and checkpoint.capacity_rehearsal_ceiling is not None
    ):
        return checkpoint.capacity_rehearsal_ceiling.approval_id
    if checkpoint.stage == "formal_publication" and checkpoint.governed_ceiling is not None:
        return checkpoint.governed_ceiling.approval_id
    return None


def _checkpoint_consumed_receipt_sha256(
    checkpoint: FinancialCapacityCheckpoint,
) -> str | None:
    """Return a receipt digest only when a formal workflow consumes it."""

    if checkpoint.stage != "formal_publication" or checkpoint.governed_ceiling is None:
        return None
    if checkpoint.capacity_receipt is None:
        raise FinancialCapacityWorkflowError("formal financial capacity receipt is missing")
    return checkpoint.capacity_receipt.sha256


def _freeze_manifest(
    slices: tuple[FinancialPublicationSlice, ...],
) -> tuple[FinancialPublicationSlice, ...]:

    if not isinstance(slices, tuple) or any(
        type(item) is not FinancialPublicationSlice for item in slices
    ):

        raise FinancialCapacityWorkflowError("financial capacity manifest shape is invalid")

    ordered = tuple(sorted(slices))

    if len(set(ordered)) != len(ordered):

        raise FinancialCapacityWorkflowError("financial capacity manifest has duplicate slices")

    return ordered


def _stable_error_code(exc: BaseException) -> str:

    code = getattr(exc, "code", "")

    if isinstance(code, str) and code.startswith("FINANCIAL_"):

        return code.lower()

    return "financial_capacity_slice_execution_failed"
