"""Research registry persistence and promotion evidence aggregation."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from copy import deepcopy
from typing import cast

from django.db import transaction

from apps.research.domain.contracts import (
    ExperimentTrialView,
    PromotionDecisionView,
    ResearchAccessDeniedError,
    ResearchConflictError,
    ResearchExperimentView,
    ResearchRecordNotFoundError,
    TrialRegistrationPayload,
)
from apps.research.domain.statistics import (
    benjamini_hochberg_q_values,
    deflated_sharpe_ratio,
)
from core.integration.research_integrity_registry import (
    get_backtest_evidence,
    get_pit_manifest_evidence,
)

from .models import (
    DatasetSplitSpec,
    ExperimentTrial,
    MetricObservation,
    MultipleTestFamily,
    PromotionDecision,
    ResearchExperiment,
)


class ResearchRegistryRepository:
    """Transactional registry for experiments, trials and decisions."""

    def create_experiment(
        self, *, experiment_id: str, question: str, hypothesis: str, owner_id: int | None
    ) -> ResearchExperimentView:
        """Persist one owner-bound research question and hypothesis."""

        return cast(
            ResearchExperimentView,
            ResearchExperiment._default_manager.create(
                experiment_id=experiment_id,
                question=question,
                hypothesis=hypothesis,
                owner_id=owner_id,
            ),
        )

    @transaction.atomic
    def create_trial(
        self,
        payload: TrialRegistrationPayload,
        *,
        trial_id: str,
        actor_user_id: int,
        actor_is_staff: bool,
    ) -> ExperimentTrialView:
        """Freeze a parameter set and sample split in one transaction."""

        try:
            experiment = ResearchExperiment._default_manager.select_for_update().get(
                experiment_id=payload["experiment_id"]
            )
        except ResearchExperiment.DoesNotExist as exc:
            raise ResearchRecordNotFoundError("experiment_not_found") from exc
        _require_research_owner(
            owner_id=experiment.owner_id,
            actor_user_id=actor_user_id,
            actor_is_staff=actor_is_staff,
        )

        canonical_params = json.dumps(
            payload["parameters"],
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        parameter_hash = hashlib.sha256(canonical_params.encode("utf-8")).hexdigest()
        family, created = MultipleTestFamily._default_manager.get_or_create(
            family_id=payload["family_id"],
            defaults={
                "experiment": experiment,
                "planned_trial_count": payload["planned_trial_count"],
            },
        )
        if not created and (
            family.experiment_id != experiment.experiment_id
            or family.planned_trial_count != payload["planned_trial_count"]
        ):
            raise ResearchConflictError(
                "multiple-test family identity was reused with different evidence"
            )
        trial = ExperimentTrial._default_manager.create(
            trial_id=trial_id,
            experiment=experiment,
            family=family,
            status=payload["status"],
            pit_manifest_id=payload["pit_manifest_id"],
            backtest_id=payload["backtest_id"],
            backtest_trust_status=payload["backtest_trust_status"],
            code_commit=payload["code_commit"],
            dependency_lock_hash=payload["dependency_lock_hash"],
            engine_version=payload["engine_version"],
            parameters=deepcopy(payload["parameters"]),
            parameter_hash=parameter_hash,
            random_seed=payload["random_seed"],
            benchmark_spec=deepcopy(payload["benchmark_spec"]),
            cost_spec=deepcopy(payload["cost_spec"]),
            slippage_spec=deepcopy(payload["slippage_spec"]),
            universe_spec=deepcopy(payload["universe_spec"]),
        )
        split = payload["split_spec"]
        DatasetSplitSpec._default_manager.create(
            trial=trial,
            training_window=deepcopy(split["training_window"]),
            validation_window=deepcopy(split["validation_window"]),
            out_of_sample_window=deepcopy(split["out_of_sample_window"]),
            walk_forward_windows=deepcopy(split["walk_forward_windows"]),
            embargo_days=split["embargo_days"],
        )
        MetricObservation._default_manager.bulk_create(
            [
                MetricObservation(
                    trial=trial,
                    metric_name=metric["metric_name"],
                    value=metric["value"],
                    sample_count=metric["sample_count"],
                    confidence_interval_low=metric.get("confidence_interval_low"),
                    confidence_interval_high=metric.get("confidence_interval_high"),
                    p_value=metric.get("p_value"),
                    metadata=deepcopy(metric.get("metadata", {})),
                )
                for metric in payload["metrics"]
            ]
        )
        return cast(ExperimentTrialView, trial)

    @transaction.atomic
    def evaluate_promotion(
        self,
        trial_id: str,
        *,
        actor_user_id: int,
        actor_is_staff: bool,
    ) -> PromotionDecisionView:
        """Apply PIT, split, family completeness, FDR and DSR gates."""

        try:
            trial = (
                ExperimentTrial._default_manager.select_for_update()
                .select_related("experiment", "family", "split_spec")
                .prefetch_related("family__trials", "metrics")
                .get(trial_id=trial_id)
            )
        except ExperimentTrial.DoesNotExist as exc:
            raise ResearchRecordNotFoundError("trial_not_found") from exc
        _require_research_owner(
            owner_id=trial.experiment.owner_id,
            actor_user_id=actor_user_id,
            actor_is_staff=actor_is_staff,
        )
        existing = PromotionDecision._default_manager.filter(trial=trial).first()
        if existing:
            return cast(PromotionDecisionView, existing)
        try:
            split = trial.split_spec
        except DatasetSplitSpec.DoesNotExist:
            split = None
        family_trials = list(trial.family.trials.all())
        complete_statuses = {"completed", "failed", "aborted"}
        reasons: list[str] = []
        if trial.status != "completed":
            reasons.append("trial_not_completed")
        if trial.backtest_trust_status != "pit_verified" or not trial.pit_manifest_id:
            reasons.append("pit_not_verified")
        manifest = get_pit_manifest_evidence(trial.pit_manifest_id)
        if manifest is None:
            reasons.append("pit_manifest_missing")
        elif not manifest["verified"]:
            reasons.append("pit_manifest_unverified")
        if trial.backtest_id is None:
            reasons.append("missing_backtest")
        else:
            backtest = get_backtest_evidence(trial.backtest_id)
            if backtest is None:
                reasons.append("backtest_missing")
            elif (
                backtest["status"] != "completed"
                or backtest["trust_status"] != "pit_verified"
                or backtest["data_manifest_id"] != trial.pit_manifest_id
                or backtest["research_trial_id"] != trial.trial_id
            ):
                reasons.append("backtest_evidence_mismatch")
        if split is None:
            reasons.append("missing_split_spec")
        elif not split.out_of_sample_window:
            reasons.append("missing_out_of_sample_window")
        if split is None or not split.walk_forward_windows:
            reasons.append("missing_walk_forward")
        if len(family_trials) != trial.family.planned_trial_count:
            reasons.append("family_trial_count_mismatch")
        if any(item.status not in complete_statuses for item in family_trials):
            reasons.append("family_has_unfinished_trials")
        metric_rows: list[MetricObservation] = []
        p_values: list[float] = []
        for family_trial in family_trials:
            if family_trial.status in {"failed", "aborted"}:
                continue
            metric = family_trial.metrics.filter(metric_name="sharpe_ratio").first()
            if metric is None or metric.p_value is None:
                reasons.append(f"missing_sharpe_evidence:{family_trial.trial_id}")
                continue
            p_value = _finite_float(metric.p_value)
            if p_value is None or not 0 <= p_value <= 1:
                reasons.append(f"invalid_sharpe_evidence:{family_trial.trial_id}")
                continue
            metric_rows.append(metric)
            p_values.append(p_value)
        q_values = benjamini_hochberg_q_values(p_values)
        for metric, q_value in zip(metric_rows, q_values, strict=True):
            metric.q_value = q_value
            metric.save(update_fields=["q_value"])  # type: ignore[no-untyped-call]
        candidate = next((metric for metric in metric_rows if metric.trial_id == trial_id), None)
        dsr = None
        if candidate:
            metric_value = _finite_float(candidate.value)
            skewness = _finite_float(candidate.metadata.get("skewness", 0.0))
            excess_kurtosis = _finite_float(candidate.metadata.get("excess_kurtosis", 0.0))
            if metric_value is None or skewness is None or excess_kurtosis is None:
                reasons.append("nonfinite_metric_evidence")
            else:
                dsr = deflated_sharpe_ratio(
                    metric_value,
                    sample_count=candidate.sample_count,
                    trial_count=trial.family.planned_trial_count,
                    skewness=skewness,
                    excess_kurtosis=excess_kurtosis,
                )
            if candidate.q_value is None or candidate.q_value > trial.family.fdr_threshold:
                reasons.append("fdr_gate_failed")
            if dsr is None or dsr < 0.95:
                reasons.append("deflated_sharpe_gate_failed")
        decision = "approved" if not reasons else "rejected"
        evidence = {
            "reasons": sorted(set(reasons)),
            "family_id": trial.family_id,
            "planned_trial_count": trial.family.planned_trial_count,
            "actual_trial_count": len(family_trials),
            "q_value": candidate.q_value if candidate else None,
            "deflated_sharpe": dsr,
            "pit_manifest_id": trial.pit_manifest_id,
            "parameter_hash": trial.parameter_hash,
        }
        result = PromotionDecision._default_manager.create(
            decision_id=uuid.uuid5(uuid.NAMESPACE_URL, f"promotion:{trial_id}").hex,
            trial=trial,
            decision=decision,
            evidence=evidence,
        )
        trial.status = "eligible_for_promotion" if decision == "approved" else "rejected"
        trial.save(update_fields=["status"])  # type: ignore[no-untyped-call]
        return cast(PromotionDecisionView, result)


def _require_research_owner(
    *,
    owner_id: int | None,
    actor_user_id: int,
    actor_is_staff: bool,
) -> None:
    """Require experiment ownership unless the actor is staff."""

    if actor_is_staff:
        return
    if owner_id is None or owner_id != actor_user_id:
        raise ResearchAccessDeniedError("research_owner_required")


def _finite_float(value: object) -> float | None:
    """Return a finite float from persisted metric evidence."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    normalized = float(value)
    return normalized if math.isfinite(normalized) else None
