"""ID-only Application contracts for persisted R7 research results."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
    R7ResearchEvidenceGraph,
    R7ResearchInputReceipt,
)
from apps.research.domain.r7_sample_policy import PersistedR7SamplePolicy
from apps.research.domain.scenario_probability_calibration import (
    evaluate_scenario_probability_calibration,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ScenarioResearchScope,
)
from apps.research.domain.scenario_research_evidence import (
    HistoricalAnalogyStudyEvidence,
    ScenarioPathStudyEvidence,
    assess_historical_analogy,
    assess_scenario_path_evidence,
)
from apps.research.domain.scenario_research_hashing import require_sha256, require_token


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class R7ResearchResultConflict(ValueError):
    """One result identity was already sealed with different content."""


class R7ResearchResultCorruption(ValueError):
    """Persisted R7 result bytes no longer match their immutable headers."""


class R7ResearchResultUnavailable(ValueError):
    """The exact policy, evidence graph, or result was not knowable at a cutoff."""


@dataclass(frozen=True)
class RegisterR7ResearchResultCommand:
    """ID/version/cutoff-only command with no caller-supplied evidence or hash."""

    result_id: str
    result_version: str
    policy_id: str
    policy_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("result_id", self.result_id),
            ("result_version", self.result_version),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
        ):
            require_token(value, field_name, maximum=192)
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class GetExactR7ResearchResultCommand:
    """Exact PIT query that never falls back to latest/current."""

    result_id: str
    result_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        require_token(self.result_id, "result_id", maximum=192)
        require_token(self.result_version, "result_version", maximum=192)
        require_sha256(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


class ExactR7SamplePolicyRecordProvider(Protocol):
    """Read a strict persisted policy by its immutable identity."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the transaction boundary used for exact owner replay."""

    def get_exact_by_identity(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> PersistedR7SamplePolicy | None:
        """Return one fully restored policy known at ``as_of``."""


class ExactR7ResearchEvidenceGraphProvider(Protocol):
    """Resolve Signal, analogy, and path evidence without current-value fallback."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def get_exact_graph(
        self,
        *,
        policy_record: PersistedR7SamplePolicy,
        evaluated_at: datetime,
    ) -> R7ResearchEvidenceGraph:
        """Return only evidence visible at the exact evaluation cutoff."""


class ExactR7ForecastObservationProvider(Protocol):
    """Read immutable Signal observations through an exact owner port."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def list_exact(
        self,
        *,
        scope: ScenarioResearchScope,
        window_start: datetime,
        window_end: datetime,
        as_of: datetime,
    ) -> tuple[ForecastLedgerOutcomeObservation, ...]:
        """Return exact observations visible at ``as_of`` without latest fallback."""


class ExactR7HistoricalAnalogyProvider(Protocol):
    """Read one complete PIT historical analogy graph from its owner."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def get_exact(
        self,
        *,
        scope: ScenarioResearchScope,
        as_of: datetime,
    ) -> HistoricalAnalogyStudyEvidence | None:
        """Return a frozen PIT study or explicit absence at ``as_of``."""


class ExactR7PathStudyProvider(Protocol):
    """Read one typed path/conditional/transition graph from its owner."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction boundary key."""

    def get_exact(
        self,
        *,
        scope: ScenarioResearchScope,
        as_of: datetime,
    ) -> ScenarioPathStudyEvidence | None:
        """Return frozen path evidence or explicit absence at ``as_of``."""


class AuthoritativeR7ResearchEvidenceGraphProvider:
    """Compose three exact owner ports without creating fallback evidence."""

    def __init__(
        self,
        *,
        forecast_provider: ExactR7ForecastObservationProvider,
        historical_analogy_provider: ExactR7HistoricalAnalogyProvider,
        path_study_provider: ExactR7PathStudyProvider,
    ) -> None:
        keys = {
            forecast_provider.unit_of_work_key,
            historical_analogy_provider.unit_of_work_key,
            path_study_provider.unit_of_work_key,
        }
        if len(keys) != 1:
            raise ValueError("R7 evidence owners use different units of work")
        self._forecast_provider = forecast_provider
        self._historical_analogy_provider = historical_analogy_provider
        self._path_study_provider = path_study_provider
        self._unit_of_work_key = next(iter(keys))

    @property
    def unit_of_work_key(self) -> str:
        """Return the verified shared owner transaction boundary."""

        return self._unit_of_work_key

    def get_exact_graph(
        self,
        *,
        policy_record: PersistedR7SamplePolicy,
        evaluated_at: datetime,
    ) -> R7ResearchEvidenceGraph:
        """Dynamically reread and seal all authoritative evidence at one cutoff."""

        scope = policy_record.scope
        policy = policy_record.policy
        observations = self._forecast_provider.list_exact(
            scope=scope,
            window_start=policy.sample_window_start,
            window_end=policy.sample_window_end,
            as_of=evaluated_at,
        )
        analogy = self._historical_analogy_provider.get_exact(
            scope=scope,
            as_of=evaluated_at,
        )
        path_study = self._path_study_provider.get_exact(
            scope=scope,
            as_of=evaluated_at,
        )
        return R7ResearchEvidenceGraph.create(
            scope_content_hash=scope.content_hash,
            evaluated_at=evaluated_at,
            forecast_observations=observations,
            historical_analogy=analogy,
            path_study=path_study,
        )


class R7ResearchResultRepository(Protocol):
    """Public read-only exact/PIT result repository."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the repository transaction boundary key."""

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedR7ResearchResult | None:
        """Return one exact result only after its server knowledge time."""


class R7ResearchResultAtomicStore(Protocol):
    """Private append capability retained by a composition root."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the store transaction boundary key."""

    def atomic(self) -> AbstractContextManager[None]:
        """Enter the all-or-nothing policy/evidence/result boundary."""

    def append(self, result: PersistedR7ResearchResult) -> PersistedR7ResearchResult:
        """Append one exact input/result graph."""


class R7ResearchResultRegistrationWriter(Protocol):
    """Closure-bound writer accepting only the public ID-only command."""

    def register(
        self,
        command: RegisterR7ResearchResultCommand,
    ) -> PersistedR7ResearchResult:
        """Reread owners, recompute outputs, and append atomically."""


class RegisterR7ResearchResult:
    """Safe Application entry point for one R7 result registration."""

    def __init__(self, writer: R7ResearchResultRegistrationWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: RegisterR7ResearchResultCommand,
    ) -> PersistedR7ResearchResult:
        """Delegate the identifier-only request to the private writer."""

        return self._writer.register(command)


class GetExactR7ResearchResult:
    """Read an immutable R7 result by exact identity and expected seal."""

    def __init__(self, repository: R7ResearchResultRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR7ResearchResultCommand,
    ) -> PersistedR7ResearchResult | None:
        """Return the exact result without latest/current fallback."""

        return self._repository.get_exact(
            result_id=command.result_id,
            result_version=command.result_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )


def materialize_persisted_r7_research_result(
    *,
    result_id: str,
    result_version: str,
    policy_record: PersistedR7SamplePolicy,
    evidence_graph: R7ResearchEvidenceGraph,
    evaluated_at: datetime,
    recorded_at: datetime,
) -> PersistedR7ResearchResult:
    """Deterministically evaluate and seal an exact owner evidence graph."""

    if policy_record.recorded_at > evaluated_at:
        raise ValueError("R7 policy was not knowable at the evaluation cutoff")
    scope = policy_record.scope
    policy = policy_record.policy
    if not policy.is_active(evaluated_at):
        raise ValueError("R7 policy is inactive at the evaluation cutoff")
    if not (
        policy_record.authorization.issued_at
        <= evaluated_at
        < policy_record.authorization.valid_until
    ):
        raise ValueError("R7 policy owner authorization is inactive at the cutoff")
    if (
        evidence_graph.scope_content_hash != scope.content_hash
        or evidence_graph.evaluated_at != evaluated_at
    ):
        raise ValueError("R7 evidence graph scope or cutoff substitution")
    calibration = evaluate_scenario_probability_calibration(
        scope=scope,
        policy=policy,
        observations=evidence_graph.forecast_observations,
        evaluated_at=evaluated_at,
    )
    historical_analogy = assess_historical_analogy(
        scope=scope,
        policy=policy,
        evidence=evidence_graph.historical_analogy,
        evaluated_at=evaluated_at,
    )
    path_research = assess_scenario_path_evidence(
        scope=scope,
        policy=policy,
        evidence=evidence_graph.path_study,
        evaluated_at=evaluated_at,
    )
    receipt = R7ResearchInputReceipt.create(
        result_id=result_id,
        result_version=result_version,
        policy_id=policy_record.policy_id,
        policy_version=policy_record.policy_version,
        policy_record_hash=policy_record.content_hash,
        evidence_graph=evidence_graph,
    )
    return PersistedR7ResearchResult.create(
        result_id=result_id,
        result_version=result_version,
        evidence_graph=evidence_graph,
        input_receipt=receipt,
        calibration=calibration,
        historical_analogy=historical_analogy,
        path_research=path_research,
        recorded_at=recorded_at,
    )


__all__ = [
    "AuthoritativeR7ResearchEvidenceGraphProvider",
    "ExactR7ForecastObservationProvider",
    "ExactR7HistoricalAnalogyProvider",
    "ExactR7PathStudyProvider",
    "ExactR7ResearchEvidenceGraphProvider",
    "ExactR7SamplePolicyRecordProvider",
    "GetExactR7ResearchResult",
    "GetExactR7ResearchResultCommand",
    "PersistedR7ResearchResult",
    "R7ResearchEvidenceGraph",
    "R7ResearchResultAtomicStore",
    "R7ResearchResultConflict",
    "R7ResearchResultCorruption",
    "R7ResearchResultRegistrationWriter",
    "R7ResearchResultRepository",
    "R7ResearchResultUnavailable",
    "RegisterR7ResearchResult",
    "RegisterR7ResearchResultCommand",
    "materialize_persisted_r7_research_result",
]
