"""Exact R3 regime, trial, promotion, and monitoring read contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import cast

from ._runner_support import (
    decimal_text,
    hash_payload,
    require_aware,
    require_finite,
    require_positive,
    require_sha256,
    require_token,
    utc_text,
)
from .baselines import DeterministicErrorMetrics, calculate_error_metrics
from .dated_outputs import DatedMacroFactorOutput
from .entities import ComparisonOperator, RetirementPolicy
from .run_artifacts import ReproducibleMacroFactorRunArtifact


def _require_ordered_unique(values: tuple[str, ...], field_name: str) -> None:
    if not values or values != tuple(sorted(set(values))):
        raise ValueError(f"{field_name} must be non-empty, unique, and ordered")


def _external_payload(artifact: ReproducibleMacroFactorRunArtifact) -> dict[str, object]:
    decoded = json.loads(artifact.external_artifact_bytes)
    if not isinstance(decoded, dict):
        raise ValueError("external artifact payload must be an object")
    return cast(dict[str, object], decoded)


def _external_predictions(
    artifact: ReproducibleMacroFactorRunArtifact,
) -> dict[tuple[str, str], Decimal]:
    raw_predictions = _external_payload(artifact).get("predictions")
    if not isinstance(raw_predictions, list) or not raw_predictions:
        raise ValueError("external artifact predictions are unavailable")
    predictions: dict[tuple[str, str], Decimal] = {}
    for raw_item in raw_predictions:
        if not isinstance(raw_item, dict):
            raise ValueError("external artifact prediction is malformed")
        item = cast(dict[str, object], raw_item)
        fold_id = item.get("fold_id")
        row_id = item.get("row_id")
        predicted_text = item.get("predicted_value")
        if (
            not isinstance(fold_id, str)
            or not isinstance(row_id, str)
            or not isinstance(predicted_text, str)
        ):
            raise ValueError("external artifact prediction identity is malformed")
        try:
            predicted_value = Decimal(predicted_text)
        except InvalidOperation as exc:
            raise ValueError("external artifact prediction value is malformed") from exc
        key = (fold_id, row_id)
        if key in predictions or not predicted_value.is_finite():
            raise ValueError("external artifact prediction identity/value is invalid")
        predictions[key] = predicted_value
    return predictions


def artifact_selection_started_at(artifact: ReproducibleMacroFactorRunArtifact) -> datetime:
    """Return the earliest exact outer-fold final-fit cutoff."""

    raw_selections = _external_payload(artifact).get("fold_selections")
    if not isinstance(raw_selections, list) or not raw_selections:
        raise ValueError("external artifact fold selections are unavailable")
    cutoffs: list[datetime] = []
    for raw_item in raw_selections:
        if not isinstance(raw_item, dict):
            raise ValueError("external artifact fold selection is malformed")
        cutoff_text = cast(dict[str, object], raw_item).get("final_fit_as_of")
        if not isinstance(cutoff_text, str):
            raise ValueError("external artifact final-fit cutoff is malformed")
        try:
            cutoff = datetime.fromisoformat(cutoff_text)
        except ValueError as exc:
            raise ValueError("external artifact final-fit cutoff is malformed") from exc
        require_aware(cutoff, "external artifact final_fit_as_of")
        cutoffs.append(cutoff)
    return min(cutoffs)


@dataclass(frozen=True)
class R3RegimeObservationEvidence:
    """One Regime-owner PIT assignment paired with an exact OOS result."""

    owner: str
    artifact_id: str
    artifact_hash: str
    fold_id: str
    row_id: str
    observation_at: datetime
    actual_available_at: datetime
    actual_value: Decimal
    actual_fact_id: str
    actual_fact_hash: str
    predicted_value: Decimal
    regime_code: str
    regime_version: str
    regime_content_hash: str
    regime_effective_at: datetime
    regime_available_at: datetime

    def __post_init__(self) -> None:
        if self.owner != "regime":
            raise ValueError("R3 regime observation owner must be regime")
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.actual_fact_hash, "actual_fact_hash"),
            (self.regime_content_hash, "regime_content_hash"),
        ):
            require_sha256(value, f"R3RegimeObservationEvidence.{name}")
        for value, name in (
            (self.fold_id, "fold_id"),
            (self.row_id, "row_id"),
            (self.actual_fact_id, "actual_fact_id"),
            (self.regime_code, "regime_code"),
            (self.regime_version, "regime_version"),
        ):
            require_token(value, f"R3RegimeObservationEvidence.{name}")
        for timestamp, timestamp_name in (
            (self.observation_at, "observation_at"),
            (self.actual_available_at, "actual_available_at"),
            (self.regime_effective_at, "regime_effective_at"),
            (self.regime_available_at, "regime_available_at"),
        ):
            require_aware(
                timestamp,
                f"R3RegimeObservationEvidence.{timestamp_name}",
            )
        require_finite(self.actual_value, "R3RegimeObservationEvidence.actual_value")
        require_finite(self.predicted_value, "R3RegimeObservationEvidence.predicted_value")
        if self.actual_available_at < self.observation_at:
            raise ValueError("actual evidence cannot be available before observation")
        if self.regime_effective_at > self.observation_at:
            raise ValueError("regime assignment cannot take effect after observation")

    @property
    def content_hash(self) -> str:
        """Return the complete exact observation seal."""

        return hash_payload(
            {
                "schema": "macro-factor-r3-regime-observation.v1",
                "owner": self.owner,
                "artifact": [self.artifact_id, self.artifact_hash],
                "prediction": [self.fold_id, self.row_id, decimal_text(self.predicted_value)],
                "actual": [
                    self.actual_fact_id,
                    self.actual_fact_hash,
                    utc_text(self.observation_at),
                    utc_text(self.actual_available_at),
                    decimal_text(self.actual_value),
                ],
                "regime": [
                    self.regime_code,
                    self.regime_version,
                    self.regime_content_hash,
                    utc_text(self.regime_effective_at),
                    utc_text(self.regime_available_at),
                ],
            }
        )


@dataclass(frozen=True)
class R3RegimeSegment:
    """Locally recalculated OOS metrics for one exact Regime revision."""

    regime_code: str
    regime_version: str
    regime_content_hash: str
    metrics: DeterministicErrorMetrics
    observation_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        require_token(self.regime_code, "R3RegimeSegment.regime_code")
        require_token(self.regime_version, "R3RegimeSegment.regime_version")
        require_sha256(self.regime_content_hash, "R3RegimeSegment.regime_content_hash")
        _require_ordered_unique(self.observation_hashes, "regime observation_hashes")

    @property
    def content_hash(self) -> str:
        """Return the exact segment seal."""

        return hash_payload(
            {
                "schema": "macro-factor-r3-regime-segment.v1",
                "regime": [self.regime_code, self.regime_version, self.regime_content_hash],
                "metrics": self.metrics.canonical_payload(),
                "observations": list(self.observation_hashes),
            }
        )


@dataclass(frozen=True)
class R3RegimeSegmentReport:
    """Complete exact OOS coverage and Regime-segmented metric report."""

    artifact_id: str
    artifact_hash: str
    source_result_hash: str
    pit_manifest_id: str
    pit_manifest_hash: str
    split_contract_hash: str
    plan_hash: str
    metrics_protocol_hash: str
    evaluated_at: datetime
    observations: tuple[R3RegimeObservationEvidence, ...]
    segments: tuple[R3RegimeSegment, ...]
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.source_result_hash, "source_result_hash"),
            (self.pit_manifest_hash, "pit_manifest_hash"),
            (self.split_contract_hash, "split_contract_hash"),
            (self.plan_hash, "plan_hash"),
            (self.metrics_protocol_hash, "metrics_protocol_hash"),
        ):
            require_sha256(value, f"R3RegimeSegmentReport.{name}")
        require_token(self.pit_manifest_id, "R3RegimeSegmentReport.pit_manifest_id")
        require_aware(self.evaluated_at, "R3RegimeSegmentReport.evaluated_at")
        if not self.observations or not self.segments:
            raise ValueError("R3 regime report requires observations and segments")
        observation_keys = tuple((item.fold_id, item.row_id) for item in self.observations)
        if observation_keys != tuple(sorted(set(observation_keys))):
            raise ValueError("R3 regime observations must be unique and ordered")
        segment_keys = tuple(
            (item.regime_code, item.regime_version, item.regime_content_hash)
            for item in self.segments
        )
        if segment_keys != tuple(sorted(set(segment_keys))):
            raise ValueError("R3 regime segments must be unique and ordered")
        if not all((self.research_only, self.must_not_use_for_decision, self.must_not_execute)):
            raise ValueError("R3 regime report must remain research-only")

    @property
    def content_hash(self) -> str:
        """Return the complete report seal."""

        return hash_payload(
            {
                "schema": "macro-factor-r3-regime-segment-report.v1",
                "artifact": [self.artifact_id, self.artifact_hash, self.source_result_hash],
                "pit_manifest": [self.pit_manifest_id, self.pit_manifest_hash],
                "research_contracts": [
                    self.split_contract_hash,
                    self.plan_hash,
                    self.metrics_protocol_hash,
                ],
                "evaluated_at": utc_text(self.evaluated_at),
                "observations": [item.content_hash for item in self.observations],
                "segments": [item.content_hash for item in self.segments],
                "research_only": True,
                "must_not_use_for_decision": True,
                "must_not_execute": True,
            }
        )


def build_regime_segment_report(
    artifact: ReproducibleMacroFactorRunArtifact,
    observations: tuple[R3RegimeObservationEvidence, ...],
    *,
    evaluated_at: datetime,
) -> R3RegimeSegmentReport:
    """Recalculate complete OOS Regime segments against canonical predictions."""

    require_aware(evaluated_at, "R3 regime evaluated_at")
    predictions = _external_predictions(artifact)
    ordered = tuple(sorted(observations, key=lambda item: (item.fold_id, item.row_id)))
    if {(item.fold_id, item.row_id) for item in ordered} != set(predictions):
        raise ValueError("R3 regime evidence must exactly cover every OOS prediction")
    for item in ordered:
        if item.artifact_id != artifact.artifact_id or item.artifact_hash != artifact.content_hash:
            raise ValueError("R3 regime evidence references another artifact")
        if item.predicted_value != predictions[(item.fold_id, item.row_id)]:
            raise ValueError("R3 regime evidence changed an OOS prediction")
        if item.actual_available_at > evaluated_at or item.regime_available_at > evaluated_at:
            raise ValueError("R3 regime evidence was unavailable at evaluation time")
    grouped: dict[tuple[str, str, str], list[R3RegimeObservationEvidence]] = {}
    for item in ordered:
        key = (item.regime_code, item.regime_version, item.regime_content_hash)
        grouped.setdefault(key, []).append(item)
    segments = tuple(
        R3RegimeSegment(
            regime_code=key[0],
            regime_version=key[1],
            regime_content_hash=key[2],
            metrics=calculate_error_metrics(
                tuple(item.actual_value for item in values),
                tuple(item.predicted_value for item in values),
            ),
            observation_hashes=tuple(sorted(item.content_hash for item in values)),
        )
        for key, values in sorted(grouped.items())
    )
    return R3RegimeSegmentReport(
        artifact_id=artifact.artifact_id,
        artifact_hash=artifact.content_hash,
        source_result_hash=artifact.source_result_hash,
        pit_manifest_id=artifact.pit_manifest_id,
        pit_manifest_hash=artifact.pit_manifest_hash,
        split_contract_hash=artifact.split_contract_hash,
        plan_hash=artifact.plan_hash,
        metrics_protocol_hash=artifact.metrics_protocol_hash,
        evaluated_at=evaluated_at,
        observations=ordered,
        segments=segments,
    )


@dataclass(frozen=True)
class R3ExperimentTrialEvidence:
    """Research-owner preregistered family bound to one exact R3 run."""

    owner: str
    capability: str
    purpose: str
    trial_id: str
    trial_version: str
    family_id: str
    family_version: str
    family_content_hash: str
    family_trial_ids: tuple[str, ...]
    artifact_id: str
    artifact_hash: str
    source_result_hash: str
    external_artifact_hash: str
    pit_manifest_id: str
    pit_manifest_hash: str
    dataset_hash: str
    split_contract_hash: str
    plan_hash: str
    regime_report_hash: str
    minimum_regime_count: int
    registered_at: datetime
    selection_started_at: datetime
    evaluated_at: datetime
    valid_until: datetime
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        if (
            self.owner != "research"
            or self.capability != "macro_factor_r3"
            or self.purpose != "oos_promotion_trial"
        ):
            raise ValueError("R3 trial authority is invalid")
        for value, name in (
            (self.trial_id, "trial_id"),
            (self.trial_version, "trial_version"),
            (self.family_id, "family_id"),
            (self.family_version, "family_version"),
            (self.pit_manifest_id, "pit_manifest_id"),
        ):
            require_token(value, f"R3ExperimentTrialEvidence.{name}")
        for value, name in (
            (self.family_content_hash, "family_content_hash"),
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.source_result_hash, "source_result_hash"),
            (self.external_artifact_hash, "external_artifact_hash"),
            (self.pit_manifest_hash, "pit_manifest_hash"),
            (self.dataset_hash, "dataset_hash"),
            (self.split_contract_hash, "split_contract_hash"),
            (self.plan_hash, "plan_hash"),
            (self.regime_report_hash, "regime_report_hash"),
        ):
            require_sha256(value, f"R3ExperimentTrialEvidence.{name}")
        _require_ordered_unique(self.family_trial_ids, "R3 trial family_trial_ids")
        if self.trial_id not in self.family_trial_ids:
            raise ValueError("R3 trial must belong to its preregistered family")
        require_positive(self.minimum_regime_count, "R3 trial minimum_regime_count")
        if self.minimum_regime_count < 2:
            raise ValueError("R3 trial must preregister at least two Regime segments")
        for timestamp, timestamp_name in (
            (self.registered_at, "registered_at"),
            (self.selection_started_at, "selection_started_at"),
            (self.evaluated_at, "evaluated_at"),
            (self.valid_until, "valid_until"),
        ):
            require_aware(timestamp, f"R3ExperimentTrialEvidence.{timestamp_name}")
        if not (
            self.registered_at <= self.selection_started_at <= self.evaluated_at < self.valid_until
        ):
            raise ValueError("R3 trial registration/evaluation window is invalid")
        if self.family_content_hash != r3_trial_family_content_hash(
            family_id=self.family_id,
            family_version=self.family_version,
            family_trial_ids=self.family_trial_ids,
            registered_at=self.registered_at,
        ):
            raise ValueError("R3 trial family hash differs from preregistration content")
        if not all((self.research_only, self.must_not_use_for_decision, self.must_not_execute)):
            raise ValueError("R3 trial must remain research-only")

    @property
    def content_hash(self) -> str:
        """Return the full preregistration and exact-artifact seal."""

        return hash_payload(
            {
                "schema": "research-macro-factor-r3-trial.v1",
                "authority": [self.owner, self.capability, self.purpose],
                "trial": [self.trial_id, self.trial_version],
                "family": [
                    self.family_id,
                    self.family_version,
                    self.family_content_hash,
                    list(self.family_trial_ids),
                ],
                "artifact": [
                    self.artifact_id,
                    self.artifact_hash,
                    self.source_result_hash,
                    self.external_artifact_hash,
                ],
                "pit": [self.pit_manifest_id, self.pit_manifest_hash, self.dataset_hash],
                "contracts": [self.split_contract_hash, self.plan_hash],
                "regime": [self.regime_report_hash, self.minimum_regime_count],
                "window": [
                    utc_text(self.registered_at),
                    utc_text(self.selection_started_at),
                    utc_text(self.evaluated_at),
                    utc_text(self.valid_until),
                ],
                "research_only": True,
                "must_not_use_for_decision": True,
                "must_not_execute": True,
            }
        )

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the exact trial record is PIT-valid."""

        require_aware(as_of, "R3 trial as_of")
        return self.evaluated_at <= as_of < self.valid_until


def r3_trial_family_content_hash(
    *,
    family_id: str,
    family_version: str,
    family_trial_ids: tuple[str, ...],
    registered_at: datetime,
) -> str:
    """Seal the complete trial family at its preregistration clock."""

    require_token(family_id, "R3 trial family_id")
    require_token(family_version, "R3 trial family_version")
    _require_ordered_unique(family_trial_ids, "R3 trial family_trial_ids")
    require_aware(registered_at, "R3 trial family registered_at")
    return hash_payload(
        {
            "schema": "research-macro-factor-r3-trial-family.v1",
            "family": [family_id, family_version],
            "trial_ids": list(family_trial_ids),
            "registered_at": utc_text(registered_at),
        }
    )


def validate_trial_binding(
    trial: R3ExperimentTrialEvidence,
    artifact: ReproducibleMacroFactorRunArtifact,
    regime_report: R3RegimeSegmentReport,
) -> None:
    """Validate preregistration and every exact run/report binding."""

    if (
        trial.artifact_id != artifact.artifact_id
        or trial.artifact_hash != artifact.content_hash
        or trial.source_result_hash != artifact.source_result_hash
        or trial.external_artifact_hash != artifact.external_artifact_hash
        or trial.pit_manifest_id != artifact.pit_manifest_id
        or trial.pit_manifest_hash != artifact.pit_manifest_hash
        or trial.dataset_hash != artifact.dataset_hash
        or trial.split_contract_hash != artifact.split_contract_hash
        or trial.plan_hash != artifact.plan_hash
        or trial.regime_report_hash != regime_report.content_hash
    ):
        raise ValueError("R3 trial is not bound to the exact artifact/report")
    if trial.selection_started_at != artifact_selection_started_at(artifact):
        raise ValueError("R3 trial selection cutoff differs from the artifact")
    if trial.registered_at > trial.selection_started_at:
        raise ValueError("R3 trial family was registered after selection")
    if trial.evaluated_at < max(artifact.produced_at, regime_report.evaluated_at):
        raise ValueError("R3 trial was evaluated before its complete evidence")
    if len(regime_report.segments) < trial.minimum_regime_count:
        raise ValueError("R3 trial does not cover its preregistered Regime count")


class R3PromotionOutcome(str, Enum):
    """Research-owned decision outcome for one exact trial."""

    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class R3PromotionDecisionEvidence:
    """Exact Research PromotionDecision and owner authorization."""

    owner: str
    capability: str
    purpose: str
    decision_id: str
    decision_version: str
    trial_id: str
    trial_hash: str
    artifact_id: str
    artifact_hash: str
    regime_report_hash: str
    outcome: R3PromotionOutcome
    authorization_id: str
    authorization_hash: str
    decided_at: datetime
    recorded_at: datetime
    valid_until: datetime
    retired_at: datetime | None = None
    research_only: bool = True
    authorizes_read_projection_only: bool = True
    publishes_current: bool = False
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        decision_id: str,
        decision_version: str,
        trial_id: str,
        trial_hash: str,
        artifact_id: str,
        artifact_hash: str,
        regime_report_hash: str,
        outcome: R3PromotionOutcome,
        authorization_id: str,
        decided_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        retired_at: datetime | None = None,
    ) -> R3PromotionDecisionEvidence:
        """Create one exact read-only decision with a derived authorization seal."""

        authorization_hash = r3_promotion_authorization_hash(
            authorization_id=authorization_id,
            decision_id=decision_id,
            decision_version=decision_version,
            trial_id=trial_id,
            trial_hash=trial_hash,
            artifact_id=artifact_id,
            artifact_hash=artifact_hash,
            regime_report_hash=regime_report_hash,
            outcome=outcome,
            decided_at=decided_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
        )
        return cls(
            owner="research",
            capability="macro_factor_r3",
            purpose="production_read_review",
            decision_id=decision_id,
            decision_version=decision_version,
            trial_id=trial_id,
            trial_hash=trial_hash,
            artifact_id=artifact_id,
            artifact_hash=artifact_hash,
            regime_report_hash=regime_report_hash,
            outcome=outcome,
            authorization_id=authorization_id,
            authorization_hash=authorization_hash,
            decided_at=decided_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            retired_at=retired_at,
        )

    def __post_init__(self) -> None:
        if (
            self.owner != "research"
            or self.capability != "macro_factor_r3"
            or self.purpose != "production_read_review"
        ):
            raise ValueError("R3 Promotion authority is invalid")
        if not isinstance(self.outcome, R3PromotionOutcome):
            raise ValueError("R3 Promotion outcome is invalid")
        for value, name in (
            (self.decision_id, "decision_id"),
            (self.decision_version, "decision_version"),
            (self.trial_id, "trial_id"),
            (self.authorization_id, "authorization_id"),
        ):
            require_token(value, f"R3PromotionDecisionEvidence.{name}")
        for value, name in (
            (self.trial_hash, "trial_hash"),
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.regime_report_hash, "regime_report_hash"),
            (self.authorization_hash, "authorization_hash"),
        ):
            require_sha256(value, f"R3PromotionDecisionEvidence.{name}")
        for timestamp, timestamp_name in (
            (self.decided_at, "decided_at"),
            (self.recorded_at, "recorded_at"),
            (self.valid_until, "valid_until"),
        ):
            require_aware(timestamp, f"R3PromotionDecisionEvidence.{timestamp_name}")
        if not self.decided_at <= self.recorded_at < self.valid_until:
            raise ValueError("R3 Promotion decision/record validity window is invalid")
        if self.retired_at is not None:
            require_aware(self.retired_at, "R3PromotionDecisionEvidence.retired_at")
            if self.retired_at <= self.recorded_at:
                raise ValueError("R3 Promotion retirement must follow recording")
        if self.authorization_hash != r3_promotion_authorization_hash(
            authorization_id=self.authorization_id,
            decision_id=self.decision_id,
            decision_version=self.decision_version,
            trial_id=self.trial_id,
            trial_hash=self.trial_hash,
            artifact_id=self.artifact_id,
            artifact_hash=self.artifact_hash,
            regime_report_hash=self.regime_report_hash,
            outcome=self.outcome,
            decided_at=self.decided_at,
            recorded_at=self.recorded_at,
            valid_until=self.valid_until,
        ):
            raise ValueError("R3 Promotion authorization hash differs from decision content")
        if not (
            self.research_only
            and self.authorizes_read_projection_only
            and not self.publishes_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R3 Promotion can authorize only a research read projection")

    @property
    def content_hash(self) -> str:
        """Return the exact decision and authorization seal."""

        return hash_payload(
            {
                "schema": "research-macro-factor-r3-promotion-decision.v1",
                "authority": [self.owner, self.capability, self.purpose],
                "decision": [self.decision_id, self.decision_version, self.outcome.value],
                "trial": [self.trial_id, self.trial_hash],
                "artifact": [self.artifact_id, self.artifact_hash],
                "regime_report_hash": self.regime_report_hash,
                "authorization": [self.authorization_id, self.authorization_hash],
                "window": [
                    utc_text(self.decided_at),
                    utc_text(self.recorded_at),
                    utc_text(self.valid_until),
                    None if self.retired_at is None else utc_text(self.retired_at),
                ],
                "research_only": True,
                "authorizes_read_projection_only": True,
                "publishes_current": False,
                "must_not_use_for_decision": True,
                "must_not_execute": True,
            }
        )

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the approved decision is exact and PIT-active."""

        require_aware(as_of, "R3 Promotion as_of")
        return (
            self.outcome is R3PromotionOutcome.APPROVED
            and self.recorded_at <= as_of < self.valid_until
            and (self.retired_at is None or as_of < self.retired_at)
        )


def r3_promotion_authorization_hash(
    *,
    authorization_id: str,
    decision_id: str,
    decision_version: str,
    trial_id: str,
    trial_hash: str,
    artifact_id: str,
    artifact_hash: str,
    regime_report_hash: str,
    outcome: R3PromotionOutcome,
    decided_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> str:
    """Seal Research authorization to the exact decision, evidence, and clocks."""

    require_token(authorization_id, "R3 Promotion authorization_id")
    require_token(decision_id, "R3 Promotion decision_id")
    require_token(decision_version, "R3 Promotion decision_version")
    require_token(trial_id, "R3 Promotion trial_id")
    for value, name in (
        (trial_hash, "trial_hash"),
        (artifact_id, "artifact_id"),
        (artifact_hash, "artifact_hash"),
        (regime_report_hash, "regime_report_hash"),
    ):
        require_sha256(value, f"R3 Promotion authorization {name}")
    require_aware(decided_at, "R3 Promotion authorization decided_at")
    require_aware(recorded_at, "R3 Promotion authorization recorded_at")
    require_aware(valid_until, "R3 Promotion authorization valid_until")
    if not isinstance(outcome, R3PromotionOutcome):
        raise ValueError("R3 Promotion authorization outcome is invalid")
    return hash_payload(
        {
            "schema": "research-macro-factor-r3-promotion-authorization.v1",
            "authority": ["research", "macro_factor_r3", "production_read_review"],
            "authorization_id": authorization_id,
            "decision": [decision_id, decision_version, outcome.value],
            "trial": [trial_id, trial_hash],
            "artifact": [artifact_id, artifact_hash],
            "regime_report_hash": regime_report_hash,
            "window": [utc_text(decided_at), utc_text(recorded_at), utc_text(valid_until)],
            "authorizes_read_projection_only": True,
            "publishes_current": False,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
    )


def validate_promotion_binding(
    decision: R3PromotionDecisionEvidence,
    trial: R3ExperimentTrialEvidence,
    regime_report: R3RegimeSegmentReport,
) -> None:
    """Validate exact trial, artifact, Regime, and decision clocks."""

    if (
        decision.trial_id != trial.trial_id
        or decision.trial_hash != trial.content_hash
        or decision.artifact_id != trial.artifact_id
        or decision.artifact_hash != trial.artifact_hash
        or decision.regime_report_hash != regime_report.content_hash
    ):
        raise ValueError("R3 PromotionDecision is not bound to the exact trial")
    if decision.decided_at < trial.evaluated_at or decision.recorded_at < decision.decided_at:
        raise ValueError("R3 PromotionDecision predates complete trial evidence")
    if decision.valid_until > trial.valid_until:
        raise ValueError("R3 PromotionDecision extends the trial validity")


def retirement_policy_content_hash(policy: RetirementPolicy) -> str:
    """Seal an existing retirement policy using the lifecycle canonical form."""

    return hash_payload(
        {
            "policy_version": policy.policy_version,
            "owner_ref": policy.owner_ref,
            "evaluation_frequency": policy.evaluation_frequency,
            "retire_on_any": policy.retire_on_any,
            "rules": [
                {
                    "rule_id": rule.rule_id,
                    "metric_name": rule.metric_name,
                    "operator": rule.operator.value,
                    "threshold": decimal_text(rule.threshold),
                    "consecutive_windows": rule.consecutive_windows,
                    "observation_window": rule.observation_window,
                    "rationale": rule.rationale,
                }
                for rule in sorted(policy.rules, key=lambda item: item.rule_id)
            ],
        }
    )


@dataclass(frozen=True)
class R3MonitoringMetricObservation:
    """One immutable monitoring metric fact supplied by the policy owner."""

    metric_name: str
    observation_window: str
    observed_at: datetime
    available_at: datetime
    value: Decimal
    source_fact_id: str
    source_fact_hash: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.metric_name, "metric_name"),
            (self.observation_window, "observation_window"),
            (self.source_fact_id, "source_fact_id"),
        ):
            require_token(value, f"R3MonitoringMetricObservation.{name}")
        require_sha256(self.source_fact_hash, "R3MonitoringMetricObservation.source_fact_hash")
        require_aware(self.observed_at, "R3MonitoringMetricObservation.observed_at")
        require_aware(self.available_at, "R3MonitoringMetricObservation.available_at")
        require_finite(self.value, "R3MonitoringMetricObservation.value")
        if self.available_at < self.observed_at:
            raise ValueError("R3 monitoring fact cannot be available before observation")

    @property
    def content_hash(self) -> str:
        """Return the complete metric fact seal."""

        return hash_payload(
            {
                "schema": "macro-factor-r3-monitoring-observation.v1",
                "metric": [self.metric_name, self.observation_window, decimal_text(self.value)],
                "clock": [utc_text(self.observed_at), utc_text(self.available_at)],
                "source": [self.source_fact_id, self.source_fact_hash],
            }
        )


@dataclass(frozen=True)
class R3MonitoringEvidence:
    """Policy-owner raw monitoring window, never a caller-reported gate result."""

    owner_ref: str
    evidence_id: str
    artifact_id: str
    artifact_hash: str
    source_result_hash: str
    policy: RetirementPolicy
    evaluated_at: datetime
    valid_until: datetime
    observations: tuple[R3MonitoringMetricObservation, ...]

    def __post_init__(self) -> None:
        if self.owner_ref != self.policy.owner_ref:
            raise ValueError("R3 monitoring owner differs from retirement-policy owner")
        require_token(self.owner_ref, "R3MonitoringEvidence.owner_ref")
        require_token(self.evidence_id, "R3MonitoringEvidence.evidence_id")
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.source_result_hash, "source_result_hash"),
        ):
            require_sha256(value, f"R3MonitoringEvidence.{name}")
        require_aware(self.evaluated_at, "R3MonitoringEvidence.evaluated_at")
        require_aware(self.valid_until, "R3MonitoringEvidence.valid_until")
        if self.evaluated_at >= self.valid_until or not self.observations:
            raise ValueError("R3 monitoring window is invalid or empty")
        keys = tuple(
            (item.metric_name, item.observation_window, item.observed_at, item.source_fact_id)
            for item in self.observations
        )
        if keys != tuple(sorted(set(keys))):
            raise ValueError("R3 monitoring observations must be unique and ordered")
        if any(item.available_at > self.evaluated_at for item in self.observations):
            raise ValueError("R3 monitoring evidence contains future knowledge")

    @property
    def policy_hash(self) -> str:
        """Return the exact bound retirement-policy hash."""

        return retirement_policy_content_hash(self.policy)

    @property
    def content_hash(self) -> str:
        """Return the raw owner evidence seal."""

        return hash_payload(
            {
                "schema": "macro-factor-r3-monitoring-evidence.v1",
                "owner": self.owner_ref,
                "evidence_id": self.evidence_id,
                "artifact": [self.artifact_id, self.artifact_hash, self.source_result_hash],
                "policy": [self.policy.policy_version, self.policy_hash],
                "window": [utc_text(self.evaluated_at), utc_text(self.valid_until)],
                "observations": [item.content_hash for item in self.observations],
            }
        )


class R3MonitoringStatus(str, Enum):
    """Derived monitoring status; no state automatically retires a run."""

    HEALTHY = "healthy"
    INCOMPLETE = "incomplete"
    RETIREMENT_REVIEW_REQUIRED = "retirement_review_required"


@dataclass(frozen=True)
class R3MonitoringAssessment:
    """Server-derived evaluation of every versioned retirement rule."""

    evidence_hash: str
    policy_hash: str
    status: R3MonitoringStatus
    missing_rule_ids: tuple[str, ...]
    breached_rule_ids: tuple[str, ...]
    assessed_at: datetime
    valid_until: datetime
    research_only: bool = True
    must_not_auto_retire: bool = True
    must_not_use_for_decision: bool = True

    def __post_init__(self) -> None:
        require_sha256(self.evidence_hash, "R3MonitoringAssessment.evidence_hash")
        require_sha256(self.policy_hash, "R3MonitoringAssessment.policy_hash")
        require_aware(self.assessed_at, "R3MonitoringAssessment.assessed_at")
        require_aware(self.valid_until, "R3MonitoringAssessment.valid_until")
        if self.assessed_at >= self.valid_until:
            raise ValueError("R3 monitoring assessment is stale at creation")
        if self.missing_rule_ids != tuple(sorted(set(self.missing_rule_ids))):
            raise ValueError("R3 monitoring missing rules must be unique and ordered")
        if self.breached_rule_ids != tuple(sorted(set(self.breached_rule_ids))):
            raise ValueError("R3 monitoring breached rules must be unique and ordered")
        if self.status is R3MonitoringStatus.HEALTHY and (
            self.missing_rule_ids or self.breached_rule_ids
        ):
            raise ValueError("healthy monitoring cannot contain blockers")
        if self.status is R3MonitoringStatus.INCOMPLETE and not self.missing_rule_ids:
            raise ValueError("incomplete monitoring requires missing rules")
        if (
            self.status is R3MonitoringStatus.RETIREMENT_REVIEW_REQUIRED
            and not self.breached_rule_ids
        ):
            raise ValueError("retirement review requires breached rules")
        if not all((self.research_only, self.must_not_auto_retire, self.must_not_use_for_decision)):
            raise ValueError("R3 monitoring cannot authorize retirement or decisions")

    @property
    def content_hash(self) -> str:
        """Return the derived monitoring assessment seal."""

        return hash_payload(
            {
                "schema": "macro-factor-r3-monitoring-assessment.v1",
                "evidence_hash": self.evidence_hash,
                "policy_hash": self.policy_hash,
                "status": self.status.value,
                "missing_rules": list(self.missing_rule_ids),
                "breached_rules": list(self.breached_rule_ids),
                "window": [utc_text(self.assessed_at), utc_text(self.valid_until)],
                "research_only": True,
                "must_not_auto_retire": True,
                "must_not_use_for_decision": True,
            }
        )


def _comparison_holds(operator: ComparisonOperator, value: Decimal, threshold: Decimal) -> bool:
    if operator is ComparisonOperator.LT:
        return value < threshold
    if operator is ComparisonOperator.LTE:
        return value <= threshold
    if operator is ComparisonOperator.GT:
        return value > threshold
    return value >= threshold


def assess_monitoring(
    evidence: R3MonitoringEvidence,
    *,
    assessed_at: datetime,
) -> R3MonitoringAssessment:
    """Recalculate rule coverage and persistent breaches from raw facts."""

    require_aware(assessed_at, "R3 monitoring assessed_at")
    if assessed_at < evidence.evaluated_at or assessed_at >= evidence.valid_until:
        raise ValueError("R3 monitoring evidence is not active at assessment time")
    missing: list[str] = []
    breached: list[str] = []
    for rule in evidence.policy.rules:
        matching = tuple(
            sorted(
                (
                    item
                    for item in evidence.observations
                    if item.metric_name == rule.metric_name
                    and item.observation_window == rule.observation_window
                ),
                key=lambda item: (item.observed_at, item.source_fact_id),
            )
        )
        if len(matching) < rule.consecutive_windows:
            missing.append(rule.rule_id)
            continue
        latest = matching[-rule.consecutive_windows :]
        if all(_comparison_holds(rule.operator, item.value, rule.threshold) for item in latest):
            breached.append(rule.rule_id)
    missing_ids = tuple(sorted(missing))
    breached_ids = tuple(sorted(breached))
    if missing_ids:
        status = R3MonitoringStatus.INCOMPLETE
    elif (
        evidence.policy.retire_on_any
        and breached_ids
        or not evidence.policy.retire_on_any
        and len(breached_ids) == len(evidence.policy.rules)
    ):
        status = R3MonitoringStatus.RETIREMENT_REVIEW_REQUIRED
    else:
        status = R3MonitoringStatus.HEALTHY
        breached_ids = ()
    return R3MonitoringAssessment(
        evidence_hash=evidence.content_hash,
        policy_hash=evidence.policy_hash,
        status=status,
        missing_rule_ids=missing_ids,
        breached_rule_ids=breached_ids,
        assessed_at=assessed_at,
        valid_until=evidence.valid_until,
    )


@dataclass(frozen=True)
class R3GovernedReadProjection:
    """Exact production-facing read projection that remains research-only."""

    artifact_id: str
    artifact_hash: str
    output: DatedMacroFactorOutput
    regime_report_hash: str
    trial_id: str
    trial_hash: str
    decision_id: str
    decision_hash: str
    monitoring_assessment_hash: str
    read_as_of: datetime
    valid_until: datetime
    research_only: bool = True
    publishes_current: bool = False
    decision_authorized: bool = False
    execution_authorized: bool = False
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.regime_report_hash, "regime_report_hash"),
            (self.trial_hash, "trial_hash"),
            (self.decision_hash, "decision_hash"),
            (self.monitoring_assessment_hash, "monitoring_assessment_hash"),
        ):
            require_sha256(value, f"R3GovernedReadProjection.{name}")
        require_token(self.trial_id, "R3GovernedReadProjection.trial_id")
        require_token(self.decision_id, "R3GovernedReadProjection.decision_id")
        require_aware(self.read_as_of, "R3GovernedReadProjection.read_as_of")
        require_aware(self.valid_until, "R3GovernedReadProjection.valid_until")
        if (
            self.output.artifact_id != self.artifact_id
            or self.output.artifact_hash != self.artifact_hash
        ):
            raise ValueError("R3 read output differs from the exact artifact")
        if self.read_as_of >= self.valid_until:
            raise ValueError("R3 governed read projection is not PIT-active")
        if not (
            self.research_only
            and not self.publishes_current
            and not self.decision_authorized
            and not self.execution_authorized
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R3 governed read projection cannot authorize production behavior")

    @property
    def content_hash(self) -> str:
        """Return the exact read projection seal."""

        return hash_payload(
            {
                "schema": "macro-factor-r3-governed-read-projection.v1",
                "artifact": [self.artifact_id, self.artifact_hash],
                "output": [self.output.output_id, self.output.content_hash],
                "regime_report_hash": self.regime_report_hash,
                "trial": [self.trial_id, self.trial_hash],
                "decision": [self.decision_id, self.decision_hash],
                "monitoring_assessment_hash": self.monitoring_assessment_hash,
                "window": [utc_text(self.read_as_of), utc_text(self.valid_until)],
                "research_only": True,
                "publishes_current": False,
                "decision_authorized": False,
                "execution_authorized": False,
                "must_not_use_for_decision": True,
                "must_not_execute": True,
            }
        )


__all__ = [
    "R3ExperimentTrialEvidence",
    "R3GovernedReadProjection",
    "R3MonitoringAssessment",
    "R3MonitoringEvidence",
    "R3MonitoringMetricObservation",
    "R3MonitoringStatus",
    "R3PromotionDecisionEvidence",
    "R3PromotionOutcome",
    "R3RegimeObservationEvidence",
    "R3RegimeSegment",
    "R3RegimeSegmentReport",
    "artifact_selection_started_at",
    "assess_monitoring",
    "build_regime_segment_report",
    "r3_promotion_authorization_hash",
    "r3_trial_family_content_hash",
    "retirement_policy_content_hash",
    "validate_promotion_binding",
    "validate_trial_binding",
]
