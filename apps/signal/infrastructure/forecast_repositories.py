"""Forecast ledger persistence."""

import uuid
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction

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

        entry = ForecastLedgerEntry._default_manager.filter(signal_id=signal_id).first()
        if entry is None:
            if settings.SIGNAL_FORECAST_LEDGER_ENABLED:
                raise ValueError(
                    f"scoreable signal {signal_id} has no forecast ledger entry"
                )
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
            entry.save(update_fields=["status"])
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
        evidence: dict[str, Any],
    ) -> ForecastOutcome:
        entry = ForecastLedgerEntry._default_manager.select_for_update().get(entry_id=entry_id)
        existing = ForecastOutcome._default_manager.filter(entry=entry).first()
        if existing:
            expected = {
                "outcome_type": outcome_type,
                "finalized_at": finalized_at,
                "asset_return": asset_return,
                "benchmark_return": benchmark_return,
                "evidence": evidence,
            }
            if any(getattr(existing, field) != value for field, value in expected.items()):
                raise ValueError("forecast outcome already exists with different evidence")
            return existing
        excess = None
        hit = None
        brier = None
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
        outcome = ForecastOutcome._default_manager.create(
            entry=entry,
            outcome_type=outcome_type,
            finalized_at=finalized_at,
            asset_return=asset_return,
            benchmark_return=benchmark_return,
            excess_return=excess,
            hit=hit,
            brier_score=brier,
            evidence=evidence,
        )
        entry.status = "finalized" if hit is not None else "data_insufficient"
        entry.save(update_fields=["status"])
        return outcome
