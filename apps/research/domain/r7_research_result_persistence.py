"""Immutable input and result seals for persisted R7 research evaluations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ScenarioCalibrationReport,
)
from apps.research.domain.scenario_research_evidence import (
    HistoricalAnalogyAssessment,
    HistoricalAnalogyStudyEvidence,
    ScenarioPathAssessment,
    ScenarioPathStudyEvidence,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_token,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class R7ForecastObservationReference:
    """Content-addressed reference to one immutable Signal observation."""

    entry_id: str
    observation_version: str
    content_hash: str

    @classmethod
    def from_observation(
        cls,
        observation: ForecastLedgerOutcomeObservation,
    ) -> R7ForecastObservationReference:
        """Project the exact Signal identity needed for owner replay."""

        return cls(
            entry_id=observation.entry_id,
            observation_version=observation.observation_version,
            content_hash=observation.content_hash,
        )

    def __post_init__(self) -> None:
        """Reject ambiguous Signal identities and noncanonical digests."""

        require_token(self.entry_id, "forecast observation entry_id", maximum=192)
        require_token(
            self.observation_version,
            "forecast observation version",
            maximum=192,
        )
        require_sha256(self.content_hash, "forecast observation content_hash")


@dataclass(frozen=True)
class R7ResearchEvidenceGraph:
    """Complete typed owner evidence graph consumed by one R7 evaluation."""

    graph_version: str
    scope_content_hash: str
    evaluated_at: datetime
    forecast_observations: tuple[ForecastLedgerOutcomeObservation, ...]
    historical_analogy: HistoricalAnalogyStudyEvidence | None
    path_study: ScenarioPathStudyEvidence | None
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        scope_content_hash: str,
        evaluated_at: datetime,
        forecast_observations: tuple[ForecastLedgerOutcomeObservation, ...],
        historical_analogy: HistoricalAnalogyStudyEvidence | None,
        path_study: ScenarioPathStudyEvidence | None,
    ) -> R7ResearchEvidenceGraph:
        """Canonicalize and seal exact Signal, analogy, and path evidence."""

        observations = tuple(
            sorted(
                forecast_observations,
                key=lambda item: (item.entry_id, item.observation_version),
            )
        )
        graph_version = "r7-research-evidence-graph.v1"
        digest = _r7_research_evidence_graph_hash(
            graph_version=graph_version,
            scope_content_hash=scope_content_hash,
            evaluated_at=evaluated_at,
            forecast_observations=observations,
            historical_analogy=historical_analogy,
            path_study=path_study,
        )
        return cls(
            graph_version=graph_version,
            scope_content_hash=scope_content_hash,
            evaluated_at=evaluated_at,
            forecast_observations=observations,
            historical_analogy=historical_analogy,
            path_study=path_study,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Reject look-ahead, substitution, duplicates, and forged graph seals."""

        require_token(self.graph_version, "evidence graph_version", maximum=192)
        require_sha256(self.scope_content_hash, "evidence scope_content_hash")
        require_sha256(self.content_hash, "evidence graph content_hash")
        _require_aware(self.evaluated_at, "evidence evaluated_at")
        identities = tuple(
            (item.entry_id, item.observation_version) for item in self.forecast_observations
        )
        if identities != tuple(sorted(identities)):
            raise ValueError("R7 forecast observations must be canonically ordered")
        if len(identities) != len(set(identities)):
            raise ValueError("R7 forecast observations contain duplicate identities")
        for observation in self.forecast_observations:
            if observation.published_at > self.evaluated_at:
                raise ValueError("R7 forecast observation is future-dated")
            if (
                observation.outcome_recorded_at is not None
                and observation.outcome_recorded_at > self.evaluated_at
            ):
                raise ValueError("R7 forecast outcome is future-dated")
            if (
                observation.invalidation is not None
                and observation.invalidation.invalidated_at > self.evaluated_at
            ):
                raise ValueError("R7 forecast invalidation is future-dated")
        for label, evidence in (
            ("historical analogy", self.historical_analogy),
            ("path study", self.path_study),
        ):
            if evidence is not None:
                if evidence.scope_hash != self.scope_content_hash:
                    raise ValueError(f"R7 {label} scope substitution")
                if evidence.generated_at > self.evaluated_at:
                    raise ValueError(f"R7 {label} is future-dated")
        expected = _r7_research_evidence_graph_hash(
            graph_version=self.graph_version,
            scope_content_hash=self.scope_content_hash,
            evaluated_at=self.evaluated_at,
            forecast_observations=self.forecast_observations,
            historical_analogy=self.historical_analogy,
            path_study=self.path_study,
        )
        if self.content_hash != expected:
            raise ValueError("R7 research evidence graph content_hash mismatch")


@dataclass(frozen=True)
class R7ResearchInputReceipt:
    """Exact policy and owner-reference graph consumed by one R7 evaluation."""

    receipt_version: str
    result_id: str
    result_version: str
    policy_id: str
    policy_version: str
    policy_record_hash: str
    scope_content_hash: str
    evaluated_at: datetime
    evidence_graph_hash: str
    forecast_observations: tuple[R7ForecastObservationReference, ...]
    analogy_evidence_hash: str | None
    path_evidence_hash: str | None
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        result_id: str,
        result_version: str,
        policy_id: str,
        policy_version: str,
        policy_record_hash: str,
        evidence_graph: R7ResearchEvidenceGraph,
    ) -> R7ResearchInputReceipt:
        """Seal policy and exact evidence identities without inventing owner data."""

        references = tuple(
            R7ForecastObservationReference.from_observation(observation)
            for observation in evidence_graph.forecast_observations
        )
        receipt_version = "r7-research-input-receipt.v1"
        analogy_hash = (
            evidence_graph.historical_analogy.content_hash
            if evidence_graph.historical_analogy is not None
            else None
        )
        path_hash = (
            evidence_graph.path_study.content_hash
            if evidence_graph.path_study is not None
            else None
        )
        digest = _r7_research_input_receipt_hash(
            receipt_version=receipt_version,
            result_id=result_id,
            result_version=result_version,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_record_hash=policy_record_hash,
            scope_content_hash=evidence_graph.scope_content_hash,
            evaluated_at=evidence_graph.evaluated_at,
            evidence_graph_hash=evidence_graph.content_hash,
            forecast_observations=references,
            analogy_evidence_hash=analogy_hash,
            path_evidence_hash=path_hash,
        )
        return cls(
            receipt_version=receipt_version,
            result_id=result_id,
            result_version=result_version,
            policy_id=policy_id,
            policy_version=policy_version,
            policy_record_hash=policy_record_hash,
            scope_content_hash=evidence_graph.scope_content_hash,
            evaluated_at=evidence_graph.evaluated_at,
            evidence_graph_hash=evidence_graph.content_hash,
            forecast_observations=references,
            analogy_evidence_hash=analogy_hash,
            path_evidence_hash=path_hash,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Validate canonical ordering, uniqueness, clocks, and the receipt seal."""

        for field_name, value in (
            ("receipt_version", self.receipt_version),
            ("result_id", self.result_id),
            ("result_version", self.result_version),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
        ):
            require_token(value, field_name, maximum=192)
        for field_name, value in (
            ("policy_record_hash", self.policy_record_hash),
            ("scope_content_hash", self.scope_content_hash),
            ("evidence_graph_hash", self.evidence_graph_hash),
            ("content_hash", self.content_hash),
        ):
            require_sha256(value, field_name)
        for field_name, optional_hash in (
            ("analogy_evidence_hash", self.analogy_evidence_hash),
            ("path_evidence_hash", self.path_evidence_hash),
        ):
            if optional_hash is not None:
                require_sha256(optional_hash, field_name)
        _require_aware(self.evaluated_at, "evaluated_at")
        identities = tuple(
            (item.entry_id, item.observation_version) for item in self.forecast_observations
        )
        if identities != tuple(sorted(identities)):
            raise ValueError("R7 forecast observation references must be canonically ordered")
        if len(identities) != len(set(identities)):
            raise ValueError("R7 forecast observation references contain duplicate identities")
        expected = _r7_research_input_receipt_hash(
            receipt_version=self.receipt_version,
            result_id=self.result_id,
            result_version=self.result_version,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            policy_record_hash=self.policy_record_hash,
            scope_content_hash=self.scope_content_hash,
            evaluated_at=self.evaluated_at,
            evidence_graph_hash=self.evidence_graph_hash,
            forecast_observations=self.forecast_observations,
            analogy_evidence_hash=self.analogy_evidence_hash,
            path_evidence_hash=self.path_evidence_hash,
        )
        if self.content_hash != expected:
            raise ValueError("R7 research input receipt content_hash mismatch")


@dataclass(frozen=True)
class PersistedR7ResearchResult:
    """One server-clocked calibration/analogy/path evidence and result bundle."""

    result_id: str
    result_version: str
    evidence_graph: R7ResearchEvidenceGraph
    input_receipt: R7ResearchInputReceipt
    calibration: ScenarioCalibrationReport
    historical_analogy: HistoricalAnalogyAssessment
    path_research: ScenarioPathAssessment
    recorded_at: datetime
    trains_probability_model: bool
    publishes_model_probability: bool
    produces_decision: bool
    executes_orders: bool
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        result_id: str,
        result_version: str,
        evidence_graph: R7ResearchEvidenceGraph,
        input_receipt: R7ResearchInputReceipt,
        calibration: ScenarioCalibrationReport,
        historical_analogy: HistoricalAnalogyAssessment,
        path_research: ScenarioPathAssessment,
        recorded_at: datetime,
    ) -> PersistedR7ResearchResult:
        """Bind deterministic research outputs to one complete exact input graph."""

        digest = _persisted_r7_research_result_hash(
            result_id=result_id,
            result_version=result_version,
            evidence_graph=evidence_graph,
            input_receipt=input_receipt,
            calibration=calibration,
            historical_analogy=historical_analogy,
            path_research=path_research,
            recorded_at=recorded_at,
        )
        return cls(
            result_id=result_id,
            result_version=result_version,
            evidence_graph=evidence_graph,
            input_receipt=input_receipt,
            calibration=calibration,
            historical_analogy=historical_analogy,
            path_research=path_research,
            recorded_at=recorded_at,
            trains_probability_model=False,
            publishes_model_probability=False,
            produces_decision=False,
            executes_orders=False,
            research_only=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Reject output substitution, backdating, or safety relaxation."""

        require_token(self.result_id, "result_id", maximum=192)
        require_token(self.result_version, "result_version", maximum=192)
        require_sha256(self.content_hash, "R7 research result content_hash")
        _require_aware(self.recorded_at, "recorded_at")
        receipt = self.input_receipt
        if (receipt.result_id, receipt.result_version) != (
            self.result_id,
            self.result_version,
        ):
            raise ValueError("R7 result identity does not match its input receipt")
        if self.recorded_at < receipt.evaluated_at:
            raise ValueError("R7 result cannot be recorded before its evaluation cutoff")
        if (
            self.evidence_graph.content_hash != receipt.evidence_graph_hash
            or self.evidence_graph.scope_content_hash != receipt.scope_content_hash
            or self.evidence_graph.evaluated_at != receipt.evaluated_at
        ):
            raise ValueError("R7 result evidence graph does not match its input receipt")
        references = tuple(
            R7ForecastObservationReference.from_observation(item)
            for item in self.evidence_graph.forecast_observations
        )
        if references != receipt.forecast_observations:
            raise ValueError("R7 result Signal graph does not match its input receipt")
        outputs = (self.calibration, self.historical_analogy, self.path_research)
        if any(item.policy_version != receipt.policy_version for item in outputs):
            raise ValueError("R7 result policy does not match its input receipt")
        if any(item.scope_hash != receipt.scope_content_hash for item in outputs):
            raise ValueError("R7 result scope does not match its input receipt")
        if any(item.evaluated_at != receipt.evaluated_at for item in outputs):
            raise ValueError("R7 result cutoff does not match its input receipt")
        if self.historical_analogy.evidence_hash != receipt.analogy_evidence_hash:
            raise ValueError("R7 analogy result does not match its input evidence")
        if self.path_research.evidence_hash != receipt.path_evidence_hash:
            raise ValueError("R7 path result does not match its input evidence")
        if (
            self.trains_probability_model
            or self.publishes_model_probability
            or self.produces_decision
            or self.executes_orders
            or not self.research_only
            or not self.must_not_use_for_decision
            or not self.must_not_execute
        ):
            raise ValueError("persisted R7 result must remain non-training and research-only")
        expected = _persisted_r7_research_result_hash(
            result_id=self.result_id,
            result_version=self.result_version,
            evidence_graph=self.evidence_graph,
            input_receipt=self.input_receipt,
            calibration=self.calibration,
            historical_analogy=self.historical_analogy,
            path_research=self.path_research,
            recorded_at=self.recorded_at,
        )
        if self.content_hash != expected:
            raise ValueError("persisted R7 research result content_hash mismatch")


def _r7_research_evidence_graph_hash(
    *,
    graph_version: str,
    scope_content_hash: str,
    evaluated_at: datetime,
    forecast_observations: tuple[ForecastLedgerOutcomeObservation, ...],
    historical_analogy: HistoricalAnalogyStudyEvidence | None,
    path_study: ScenarioPathStudyEvidence | None,
) -> str:
    return hash_components(
        graph_version,
        scope_content_hash,
        evaluated_at.isoformat(),
        *(item.content_hash for item in forecast_observations),
        historical_analogy.content_hash if historical_analogy is not None else "",
        path_study.content_hash if path_study is not None else "",
    )


def _r7_research_input_receipt_hash(
    *,
    receipt_version: str,
    result_id: str,
    result_version: str,
    policy_id: str,
    policy_version: str,
    policy_record_hash: str,
    scope_content_hash: str,
    evaluated_at: datetime,
    evidence_graph_hash: str,
    forecast_observations: tuple[R7ForecastObservationReference, ...],
    analogy_evidence_hash: str | None,
    path_evidence_hash: str | None,
) -> str:
    return hash_components(
        receipt_version,
        result_id,
        result_version,
        policy_id,
        policy_version,
        policy_record_hash,
        scope_content_hash,
        evaluated_at.isoformat(),
        evidence_graph_hash,
        *(
            f"{item.entry_id}|{item.observation_version}|{item.content_hash}"
            for item in forecast_observations
        ),
        analogy_evidence_hash or "",
        path_evidence_hash or "",
    )


def _persisted_r7_research_result_hash(
    *,
    result_id: str,
    result_version: str,
    evidence_graph: R7ResearchEvidenceGraph,
    input_receipt: R7ResearchInputReceipt,
    calibration: ScenarioCalibrationReport,
    historical_analogy: HistoricalAnalogyAssessment,
    path_research: ScenarioPathAssessment,
    recorded_at: datetime,
) -> str:
    return hash_components(
        "persisted-r7-research-result.v1",
        result_id,
        result_version,
        evidence_graph.content_hash,
        input_receipt.content_hash,
        calibration.content_hash,
        historical_analogy.content_hash,
        path_research.content_hash,
        recorded_at.isoformat(),
        "False",
        "False",
        "False",
        "False",
        "True",
        "True",
        "True",
    )


__all__ = [
    "PersistedR7ResearchResult",
    "R7ForecastObservationReference",
    "R7ResearchEvidenceGraph",
    "R7ResearchInputReceipt",
]
