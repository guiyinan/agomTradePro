"""Typed contracts for the immutable Research registry."""

from __future__ import annotations

from datetime import datetime
from typing import Any, NotRequired, Protocol, TypedDict


class DatasetSplitPayload(TypedDict):
    """Frozen dataset-split evidence supplied with one trial."""

    training_window: dict[str, Any]
    validation_window: dict[str, Any]
    out_of_sample_window: dict[str, Any]
    walk_forward_windows: list[dict[str, Any]]
    embargo_days: int


class MetricObservationPayload(TypedDict):
    """One immutable research metric observation."""

    metric_name: str
    value: float
    sample_count: int
    confidence_interval_low: NotRequired[float | None]
    confidence_interval_high: NotRequired[float | None]
    p_value: NotRequired[float | None]
    metadata: NotRequired[dict[str, Any]]


class TrialRegistrationPayload(TypedDict):
    """Validated payload accepted by trial persistence."""

    experiment_id: str
    family_id: str
    planned_trial_count: int
    status: str
    pit_manifest_id: str
    backtest_id: int | None
    backtest_trust_status: str
    code_commit: str
    dependency_lock_hash: str
    engine_version: str
    parameters: dict[str, Any]
    random_seed: int
    benchmark_spec: dict[str, Any]
    cost_spec: dict[str, Any]
    slippage_spec: dict[str, Any]
    universe_spec: dict[str, Any]
    split_spec: DatasetSplitPayload
    metrics: list[MetricObservationPayload]


class ResearchExperimentView(Protocol):
    @property
    def experiment_id(self) -> str: ...

    @property
    def question(self) -> str: ...

    @property
    def hypothesis(self) -> str: ...

    @property
    def status(self) -> str: ...


class ExperimentTrialView(Protocol):
    @property
    def trial_id(self) -> str: ...

    @property
    def experiment_id(self) -> str: ...

    @property
    def family_id(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def parameter_hash(self) -> str: ...

    @property
    def pit_manifest_id(self) -> str: ...


class PromotionDecisionView(Protocol):
    @property
    def decision_id(self) -> str: ...

    @property
    def trial_id(self) -> str: ...

    @property
    def decision(self) -> str: ...

    @property
    def evidence(self) -> dict[str, Any]: ...

    @property
    def decided_at(self) -> datetime: ...


class ResearchRegistryGateway(Protocol):
    """Application-facing persistence contract for the Research registry."""

    def create_experiment(
        self,
        *,
        experiment_id: str,
        question: str,
        hypothesis: str,
        owner_id: int | None,
    ) -> ResearchExperimentView: ...

    def create_trial(
        self,
        payload: TrialRegistrationPayload,
        *,
        trial_id: str,
        actor_user_id: int,
        actor_is_staff: bool,
    ) -> ExperimentTrialView: ...

    def evaluate_promotion(
        self,
        trial_id: str,
        *,
        actor_user_id: int,
        actor_is_staff: bool,
    ) -> PromotionDecisionView: ...


class ResearchAccessDeniedError(PermissionError):
    """Raised when an actor tries to mutate another owner's research."""


class ResearchRecordNotFoundError(LookupError):
    """Raised when a requested experiment or trial does not exist."""


class ResearchConflictError(ValueError):
    """Raised when immutable research identities conflict."""
