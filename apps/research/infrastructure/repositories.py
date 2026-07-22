"""Research registry persistence and promotion evidence aggregation."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from django.db import transaction

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
    ) -> ResearchExperiment:
        return ResearchExperiment._default_manager.create(
            experiment_id=experiment_id,
            question=question,
            hypothesis=hypothesis,
            owner_id=owner_id,
        )

    @transaction.atomic
    def create_trial(self, payload: dict[str, Any]) -> ExperimentTrial:
        """Freeze a parameter set and sample split in one transaction."""

        split = payload.pop("split_spec")
        metrics = payload.pop("metrics", [])
        canonical_params = json.dumps(
            payload["parameters"], sort_keys=True, separators=(",", ":"), default=str
        )
        payload["parameter_hash"] = hashlib.sha256(canonical_params.encode("utf-8")).hexdigest()
        family_id = payload.pop("family_id")
        planned_trial_count = int(payload.pop("planned_trial_count"))
        family, created = MultipleTestFamily._default_manager.get_or_create(
            family_id=family_id,
            defaults={
                "experiment_id": payload["experiment_id"],
                "planned_trial_count": planned_trial_count,
            },
        )
        if not created and (
            family.experiment_id != payload["experiment_id"]
            or family.planned_trial_count != planned_trial_count
        ):
            raise ValueError(
                "multiple-test family identity was reused with different evidence"
            )
        trial = ExperimentTrial._default_manager.create(family=family, **payload)
        DatasetSplitSpec._default_manager.create(trial=trial, **split)
        for metric in metrics:
            MetricObservation._default_manager.create(trial=trial, **metric)
        return trial

    @transaction.atomic
    def evaluate_promotion(self, trial_id: str) -> PromotionDecision:
        """Apply PIT, split, family completeness, FDR and DSR gates."""

        trial = (
            ExperimentTrial._default_manager.select_related("family", "split_spec")
            .prefetch_related("family__trials", "metrics")
            .get(trial_id=trial_id)
        )
        existing = PromotionDecision._default_manager.filter(trial=trial).first()
        if existing:
            return existing
        split = trial.split_spec
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
        if not split.out_of_sample_window:
            reasons.append("missing_out_of_sample_window")
        if not split.walk_forward_windows:
            reasons.append("missing_walk_forward")
        if len(family_trials) != trial.family.planned_trial_count:
            reasons.append("family_trial_count_mismatch")
        if any(item.status not in complete_statuses for item in family_trials):
            reasons.append("family_has_unfinished_trials")
        metric_rows = []
        for family_trial in family_trials:
            if family_trial.status in {"failed", "aborted"}:
                continue
            metric = family_trial.metrics.filter(metric_name="sharpe_ratio").first()
            if metric is None or metric.p_value is None:
                reasons.append(f"missing_sharpe_evidence:{family_trial.trial_id}")
                continue
            metric_rows.append(metric)
        q_values = benjamini_hochberg_q_values([metric.p_value for metric in metric_rows])
        for metric, q_value in zip(metric_rows, q_values, strict=True):
            metric.q_value = q_value
            metric.save(update_fields=["q_value"])
        candidate = next((metric for metric in metric_rows if metric.trial_id == trial_id), None)
        dsr = None
        if candidate:
            dsr = deflated_sharpe_ratio(
                candidate.value,
                sample_count=candidate.sample_count,
                trial_count=trial.family.planned_trial_count,
                skewness=float(candidate.metadata.get("skewness", 0.0)),
                excess_kurtosis=float(candidate.metadata.get("excess_kurtosis", 0.0)),
            )
            if candidate.q_value is None or candidate.q_value > trial.family.fdr_threshold:
                reasons.append("fdr_gate_failed")
            if dsr < 0.95:
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
        trial.save(update_fields=["status"])
        return result
