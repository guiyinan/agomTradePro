"""Forecast ledger persistence."""

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction

from apps.signal.domain.forecast_scenario_evidence import (
    ScenarioForecastBinding,
    ScenarioForecastOutcomeEvidence,
    ScenarioProbabilitySource,
)

from .forecast_models import ForecastEvaluation, ForecastLedgerEntry, ForecastOutcome


class ForecastEvaluationRepository:
    def create_entry(self, **kwargs: Any) -> ForecastLedgerEntry:
        """Create an immutable ledger entry idempotently by entry id."""

        entry_id = str(kwargs.pop("entry_id", "") or uuid.uuid4().hex)
        entry, created = ForecastLedgerEntry._default_manager.get_or_create(
            entry_id=entry_id, defaults=kwargs
        )
        if not created and any(getattr(entry, field) != value for field, value in kwargs.items()):
            raise ValueError("forecast entry idempotency key was reused with different evidence")
        return entry

    @transaction.atomic
    def record_evaluation_for_signal(
        self,
        *,
        signal_id: str,
        checked_at: datetime,
        data_version_ids: list[int],
        conditions: list[dict[str, Any]],
        missing_reason: str,
    ) -> ForecastEvaluation | None:
        """Append a scheduled check for a linked signal, failing closed after cutover."""

        entry = ForecastLedgerEntry._default_manager.filter(signal_id=int(signal_id)).first()
        if entry is None:
            if bool(getattr(settings, "SIGNAL_FORECAST_LEDGER_ENABLED", False)):
                raise ValueError(f"scoreable signal {signal_id} has no forecast ledger entry")
            return None
        return self.record_evaluation(
            entry_id=entry.entry_id,
            checked_at=checked_at,
            data_version_ids=data_version_ids,
            conditions=conditions,
            triggered=any(bool(item.get("triggered")) for item in conditions),
            missing_reason=missing_reason,
        )

    @transaction.atomic
    def record_evaluation(
        self,
        *,
        entry_id: str,
        checked_at: datetime,
        data_version_ids: list[int],
        conditions: list[dict[str, Any]],
        triggered: bool,
        missing_reason: str,
    ) -> ForecastEvaluation:
        entry = ForecastLedgerEntry._default_manager.select_for_update().get(entry_id=entry_id)
        if checked_at < entry.published_at:
            raise ValueError("checked_at must not precede forecast publication")
        key = f"{entry_id}:{checked_at.isoformat()}"
        prior_trigger = entry.evaluations.filter(triggered=True).order_by("checked_at").first()
        first_triggered_at = (
            prior_trigger.first_triggered_at or prior_trigger.checked_at
            if prior_trigger
            else (checked_at if triggered else None)
        )
        evaluation, created = ForecastEvaluation._default_manager.get_or_create(
            idempotency_key=key,
            defaults={
                "evaluation_id": uuid.uuid5(uuid.NAMESPACE_URL, key).hex,
                "entry": entry,
                "checked_at": checked_at,
                "data_version_ids": data_version_ids,
                "conditions": conditions,
                "triggered": triggered,
                "first_triggered_at": first_triggered_at,
                "status_transition": (
                    "invalidated" if triggered and entry.status == "open" else ""
                ),
                "missing_reason": missing_reason,
            },
        )
        if not created and any(
            (
                evaluation.data_version_ids != data_version_ids,
                evaluation.conditions != conditions,
                evaluation.triggered != triggered,
                evaluation.missing_reason != missing_reason,
            )
        ):
            raise ValueError(
                "forecast evaluation idempotency key was reused with different evidence"
            )
        if created and triggered:
            entry.status = "invalidated"
            entry.save(update_fields=["status"])  # type: ignore[no-untyped-call]
        return evaluation

    @transaction.atomic
    def finalize_outcome(
        self,
        *,
        entry_id: str,
        finalized_at: datetime,
        outcome_type: str,
        asset_return: float | None,
        benchmark_return: float | None,
        neutral_band: float,
        scenario_realized: bool | None,
        evidence: dict[str, Any],
    ) -> ForecastOutcome:
        entry = ForecastLedgerEntry._default_manager.select_for_update().get(entry_id=entry_id)
        if finalized_at < entry.published_at:
            raise ValueError("finalized_at must not precede forecast publication")
        if scenario_realized is not None:
            if entry.scenario_revision_id is None:
                raise ValueError("scenario_realized requires a scenario revision binding")
            if finalized_at < entry.horizon_end:
                raise ValueError("scenario realization cannot be finalized before horizon_end")
        existing = ForecastOutcome._default_manager.filter(entry=entry).first()
        if existing:
            expected = {
                "outcome_type": outcome_type,
                "finalized_at": finalized_at,
                "asset_return": asset_return,
                "benchmark_return": benchmark_return,
                "scenario_realized": scenario_realized,
                "evidence": evidence,
            }
            if any(getattr(existing, field) != value for field, value in expected.items()):
                raise ValueError("forecast outcome already exists with different evidence")
            return existing
        excess = None
        hit = None
        brier = None
        subjective_brier = None
        model_brier = None
        if asset_return is not None and benchmark_return is not None:
            excess = asset_return - benchmark_return
            if entry.direction == "LONG":
                hit = excess > neutral_band
            elif entry.direction == "SHORT":
                hit = excess < -neutral_band
            elif entry.direction == "NEUTRAL":
                hit = abs(excess) <= neutral_band
            if hit is not None:
                brier = (entry.probability - float(hit)) ** 2
        if scenario_realized is not None:
            if entry.subjective_probability is None:
                raise ValueError("scenario binding has no subjective probability")
            observed = float(scenario_realized)
            subjective_brier = (float(entry.subjective_probability) - observed) ** 2
            if entry.model_probability is not None:
                model_brier = (float(entry.model_probability) - observed) ** 2
        outcome = ForecastOutcome._default_manager.create(
            entry=entry,
            outcome_type=outcome_type,
            finalized_at=finalized_at,
            asset_return=asset_return,
            benchmark_return=benchmark_return,
            excess_return=excess,
            hit=hit,
            brier_score=brier,
            scenario_realized=scenario_realized,
            subjective_brier_score=subjective_brier,
            model_brier_score=model_brier,
            evidence=evidence,
        )
        entry.status = (
            "finalized" if hit is not None or scenario_realized is not None else "data_insufficient"
        )
        entry.save(update_fields=["status"])  # type: ignore[no-untyped-call]
        return outcome

    def list_scenario_outcomes(
        self,
        *,
        scenario_revision_id: UUID,
        scenario_set_revision_id: UUID | None,
        probability_source: ScenarioProbabilitySource | None,
    ) -> tuple[ScenarioForecastOutcomeEvidence, ...]:
        """Return exact revision-bound row scores without calibration inference."""

        queryset = ForecastOutcome._default_manager.select_related("entry").filter(
            entry__scenario_revision_id=scenario_revision_id,
            scenario_realized__isnull=False,
            subjective_brier_score__isnull=False,
        )
        if scenario_set_revision_id is not None:
            queryset = queryset.filter(entry__scenario_set_revision_id=scenario_set_revision_id)
        if probability_source is ScenarioProbabilitySource.MODEL_INFERRED:
            queryset = queryset.filter(model_brier_score__isnull=False)
        observations: list[ScenarioForecastOutcomeEvidence] = []
        for outcome in queryset.order_by("finalized_at", "entry_id"):
            entry = outcome.entry
            if (
                entry.scenario_revision_id is None
                or entry.subjective_probability is None
                or outcome.scenario_realized is None
                or outcome.subjective_brier_score is None
            ):
                raise ValueError("persisted scenario forecast evidence is incomplete")
            binding = ScenarioForecastBinding.from_values(
                scenario_revision_id=entry.scenario_revision_id,
                scenario_set_revision_id=entry.scenario_set_revision_id,
                subjective_probability=entry.subjective_probability,
                subjective_probability_source_version=(entry.subjective_probability_source_version),
                model_probability=entry.model_probability,
                model_probability_source_version=(entry.model_probability_source_version or None),
                model_promotion_decision_id=(entry.model_promotion_decision_id or None),
            )
            observations.append(
                ScenarioForecastOutcomeEvidence(
                    entry_id=entry.entry_id,
                    binding=binding,
                    finalized_at=outcome.finalized_at,
                    scenario_realized=outcome.scenario_realized,
                    subjective_brier_score=outcome.subjective_brier_score,
                    model_brier_score=outcome.model_brier_score,
                )
            )
        return tuple(observations)
