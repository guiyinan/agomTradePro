"""Fail-closed orchestration for the no-data R3 reproducible runner."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from apps.macro_factor.domain.entities import (
    ExternalMacroFactorResearchResult,
    PITManifestEvidence,
    RetirementEvidence,
)
from apps.macro_factor.domain.lifecycle import RetirementOwnerAttestation
from apps.macro_factor.domain.reproducible_runner import (
    ExternalNestedCVArtifact,
    MacroFactorLifecycleEvent,
    MacroFactorRunnerSpec,
    NestedCVExecutionRequest,
    PITResearchDataset,
    ReproducibleMacroFactorRunArtifact,
    ReproducibleMacroFactorRunBundle,
    append_retirement_event,
    build_execution_request,
    build_reproducible_run,
)

logger = logging.getLogger(__name__)


class MacroFactorRunnerStatus(str, Enum):
    """Research-only orchestration outcome."""

    RECORDED = "recorded"
    RETIRED = "retired"
    BLOCKED = "blocked"


class MacroFactorRunnerBlockerCode(str, Enum):
    """Stable fail-closed reasons for runner and lifecycle orchestration."""

    PIT_MANIFEST_MISSING = "pit_manifest_missing"
    PIT_MANIFEST_MISMATCH = "pit_manifest_mismatch"
    PIT_MANIFEST_UNVERIFIED = "pit_manifest_unverified"
    PIT_DATASET_MISSING = "pit_dataset_missing"
    RUN_INPUT_INVALID = "run_input_invalid"
    EXTERNAL_RUNNER_UNAVAILABLE = "external_runner_unavailable"
    EXTERNAL_ARTIFACT_INVALID = "external_artifact_invalid"
    RUN_ARTIFACT_MISSING = "run_artifact_missing"
    RETIREMENT_INVALID = "retirement_invalid"


class MacroFactorRunnerManifestProvider(Protocol):
    """Read a canonical Data Center PIT manifest projection."""

    def get_manifest(self, manifest_id: str) -> PITManifestEvidence | None:
        """Return exact immutable PIT evidence or ``None``."""


class MacroFactorRunnerDatasetProvider(Protocol):
    """Build in-memory design rows from a manifest-bound Data Center view."""

    def get_dataset(
        self,
        *,
        manifest_id: str,
        manifest_hash: str,
        target_code: str,
        candidate_asset_codes: tuple[str, ...],
    ) -> PITResearchDataset | None:
        """Return rows without persisting a second fact source."""


class TypedExternalMacroFactorRunner(Protocol):
    """Numerical model boundary implemented only outside Domain/Application."""

    def execute(
        self,
        *,
        request: NestedCVExecutionRequest,
        dataset: PITResearchDataset,
        spec: MacroFactorRunnerSpec,
    ) -> ExternalNestedCVArtifact | None:
        """Fit against the already validated PIT design or fail closed."""


class MacroFactorRunLedgerRepository(Protocol):
    """Append-only persistence boundary for one run bundle and lifecycle."""

    def append_bundle(
        self,
        bundle: ReproducibleMacroFactorRunBundle,
    ) -> ReproducibleMacroFactorRunBundle:
        """Atomically append source result, run, outputs, and root event."""

    def get_artifact(
        self,
        artifact_id: str,
    ) -> ReproducibleMacroFactorRunArtifact | None:
        """Return one immutable run artifact."""

    def list_lifecycle_events(
        self,
        artifact_id: str,
    ) -> tuple[MacroFactorLifecycleEvent, ...]:
        """Return the ordered immutable event chain."""

    def append_lifecycle_event(
        self,
        event: MacroFactorLifecycleEvent,
    ) -> MacroFactorLifecycleEvent:
        """Append exactly one chain link."""


@dataclass(frozen=True)
class RunReproducibleMacroFactorCommand:
    """Exact runner spec and expected canonical manifest identity."""

    spec: MacroFactorRunnerSpec
    expected_manifest_id: str
    expected_manifest_hash: str

    def __post_init__(self) -> None:
        if not self.expected_manifest_id.strip():
            raise ValueError("expected_manifest_id cannot be blank")
        if len(self.expected_manifest_hash) != 64:
            raise ValueError("expected_manifest_hash must be a sha256 digest")


@dataclass(frozen=True)
class MacroFactorRunnerAssessment:
    """Fail-closed result that never grants decision or execution authority."""

    status: MacroFactorRunnerStatus
    blocked_reasons: tuple[MacroFactorRunnerBlockerCode, ...]
    bundle: ReproducibleMacroFactorRunBundle | None
    lifecycle_event: MacroFactorLifecycleEvent | None
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        if not all((self.research_only, self.must_not_use_for_decision, self.must_not_execute)):
            raise ValueError("runner assessments cannot authorize decisions or execution")
        if self.status is MacroFactorRunnerStatus.BLOCKED:
            if (
                not self.blocked_reasons
                or self.bundle is not None
                or self.lifecycle_event is not None
            ):
                raise ValueError("blocked runner assessment requires only blockers")
        elif self.blocked_reasons:
            raise ValueError("successful runner assessment cannot contain blockers")


def _blocked(reason: MacroFactorRunnerBlockerCode) -> MacroFactorRunnerAssessment:
    return MacroFactorRunnerAssessment(
        status=MacroFactorRunnerStatus.BLOCKED,
        blocked_reasons=(reason,),
        bundle=None,
        lifecycle_event=None,
    )


class RunReproducibleMacroFactor:
    """Build deterministic baselines and validate one typed external run."""

    def __init__(
        self,
        *,
        manifest_provider: MacroFactorRunnerManifestProvider,
        dataset_provider: MacroFactorRunnerDatasetProvider,
        external_runner: TypedExternalMacroFactorRunner,
        repository: MacroFactorRunLedgerRepository,
    ) -> None:
        self._manifest_provider = manifest_provider
        self._dataset_provider = dataset_provider
        self._external_runner = external_runner
        self._repository = repository

    def execute(
        self,
        command: RunReproducibleMacroFactorCommand,
    ) -> MacroFactorRunnerAssessment:
        """Fail closed before persistence on every absent or inconsistent input."""

        manifest = self._manifest_provider.get_manifest(command.expected_manifest_id)
        if manifest is None:
            return _blocked(MacroFactorRunnerBlockerCode.PIT_MANIFEST_MISSING)
        if (
            manifest.manifest_id != command.expected_manifest_id
            or manifest.manifest_hash.lower() != command.expected_manifest_hash.lower()
        ):
            return _blocked(MacroFactorRunnerBlockerCode.PIT_MANIFEST_MISMATCH)
        if not manifest.is_complete:
            return _blocked(MacroFactorRunnerBlockerCode.PIT_MANIFEST_UNVERIFIED)
        candidate_codes = tuple(item.asset_code for item in command.spec.candidates)
        dataset = self._dataset_provider.get_dataset(
            manifest_id=manifest.manifest_id,
            manifest_hash=manifest.manifest_hash,
            target_code=command.spec.target.target_code,
            candidate_asset_codes=candidate_codes,
        )
        if dataset is None:
            return _blocked(MacroFactorRunnerBlockerCode.PIT_DATASET_MISSING)
        try:
            request = build_execution_request(command.spec, dataset, manifest)
        except ValueError:
            return _blocked(MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID)
        try:
            external = self._external_runner.execute(
                request=request,
                dataset=dataset,
                spec=command.spec,
            )
        except Exception:
            logger.exception("macro-factor external runner boundary failed")
            return _blocked(MacroFactorRunnerBlockerCode.EXTERNAL_RUNNER_UNAVAILABLE)
        if external is None:
            return _blocked(MacroFactorRunnerBlockerCode.EXTERNAL_RUNNER_UNAVAILABLE)
        try:
            bundle = build_reproducible_run(command.spec, dataset, manifest, external)
        except ValueError:
            return _blocked(MacroFactorRunnerBlockerCode.EXTERNAL_ARTIFACT_INVALID)
        stored = self._repository.append_bundle(bundle)
        return MacroFactorRunnerAssessment(
            status=MacroFactorRunnerStatus.RECORDED,
            blocked_reasons=(),
            bundle=stored,
            lifecycle_event=stored.lifecycle_events[0],
        )


@dataclass(frozen=True)
class RetireReproducibleMacroFactorRunCommand:
    """Exact source/run/evidence binding for append-only retirement."""

    artifact_id: str
    expected_artifact_hash: str
    source_result: ExternalMacroFactorResearchResult
    retirement: RetirementEvidence
    owner_attestation: RetirementOwnerAttestation
    recorded_at: datetime

    def __post_init__(self) -> None:
        if len(self.artifact_id) != 64 or len(self.expected_artifact_hash) != 64:
            raise ValueError("retirement artifact identity must use sha256 digests")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")


class RetireReproducibleMacroFactorRun:
    """Append one retirement event while leaving all source/run rows unchanged."""

    def __init__(self, *, repository: MacroFactorRunLedgerRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: RetireReproducibleMacroFactorRunCommand,
    ) -> MacroFactorRunnerAssessment:
        """Validate the existing retirement policy and append its chain event."""

        artifact = self._repository.get_artifact(command.artifact_id)
        if artifact is None:
            return _blocked(MacroFactorRunnerBlockerCode.RUN_ARTIFACT_MISSING)
        if artifact.content_hash != command.expected_artifact_hash:
            return _blocked(MacroFactorRunnerBlockerCode.RETIREMENT_INVALID)
        events = self._repository.list_lifecycle_events(command.artifact_id)
        if not events:
            return _blocked(MacroFactorRunnerBlockerCode.RETIREMENT_INVALID)
        try:
            event = append_retirement_event(
                artifact=artifact,
                source_result=command.source_result,
                retirement=command.retirement,
                owner_attestation=command.owner_attestation,
                previous_event=events[-1],
                recorded_at=command.recorded_at,
            )
        except ValueError:
            return _blocked(MacroFactorRunnerBlockerCode.RETIREMENT_INVALID)
        stored = self._repository.append_lifecycle_event(event)
        return MacroFactorRunnerAssessment(
            status=MacroFactorRunnerStatus.RETIRED,
            blocked_reasons=(),
            bundle=None,
            lifecycle_event=stored,
        )


__all__ = [
    "MacroFactorRunLedgerRepository",
    "MacroFactorRunnerAssessment",
    "MacroFactorRunnerBlockerCode",
    "MacroFactorRunnerDatasetProvider",
    "MacroFactorRunnerManifestProvider",
    "MacroFactorRunnerStatus",
    "RetireReproducibleMacroFactorRun",
    "RetireReproducibleMacroFactorRunCommand",
    "RunReproducibleMacroFactor",
    "RunReproducibleMacroFactorCommand",
    "TypedExternalMacroFactorRunner",
]
