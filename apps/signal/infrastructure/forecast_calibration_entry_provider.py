"""Exact Forecast Ledger/Outcome projection for calibration receipts."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256

from django.db import transaction

from apps.signal.domain.forecast_calibration_sample import (
    ForecastCalibrationEntryOwnerRecord,
    ForecastCalibrationResolution,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding
from apps.signal.infrastructure.forecast_models import ForecastLedgerEntry, ForecastOutcome


class ForecastCalibrationEntryOwnerCorruption(ValueError):
    """Raised when immutable Ledger/Outcome rows cannot prove a resolution state."""


def _source_hash(outcome: ForecastOutcome) -> str:
    payload = {
        "entry_id": outcome.entry_id,
        "outcome_type": outcome.outcome_type,
        "finalized_at": outcome.finalized_at.isoformat(timespec="microseconds"),
        "asset_return": outcome.asset_return,
        "benchmark_return": outcome.benchmark_return,
        "excess_return": outcome.excess_return,
        "hit": outcome.hit,
        "brier_score": outcome.brier_score,
        "scenario_realized": outcome.scenario_realized,
        "subjective_brier_score": outcome.subjective_brier_score,
        "model_brier_score": outcome.model_brier_score,
        "evidence": outcome.evidence,
    }
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ForecastCalibrationEntryOwnerCorruption(
            "ForecastOutcome cannot be sealed canonically"
        ) from exc
    return sha256(encoded).hexdigest()


class DjangoForecastCalibrationEntryOwnerProvider:
    """Read one exact immutable ledger member at a caller-independent PIT."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared Django transaction identity."""

        return f"django:{self._using}"

    def get_entry(
        self,
        *,
        entry_id: str,
        as_of: datetime,
    ) -> ForecastCalibrationEntryOwnerRecord | None:
        """Return resolved or explicit unresolved state without name inference."""

        if not isinstance(entry_id, str) or not entry_id.strip():
            raise ValueError("entry_id is required")
        if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        with transaction.atomic(using=self._using):
            entry = (
                ForecastLedgerEntry._default_manager.using(self._using)
                .select_for_update()
                .filter(entry_id=entry_id, created_at__lte=as_of)
                .first()
            )
            if entry is None:
                return None
            if (
                entry.scenario_revision_id is None
                or entry.scenario_set_revision_id is None
                or entry.subjective_probability is None
                or not entry.subjective_probability_source_version
            ):
                raise ForecastCalibrationEntryOwnerCorruption(
                    "Forecast Ledger scenario binding is incomplete"
                )
            try:
                binding = ScenarioForecastBinding.from_values(
                    scenario_revision_id=entry.scenario_revision_id,
                    scenario_set_revision_id=entry.scenario_set_revision_id,
                    subjective_probability=entry.subjective_probability,
                    subjective_probability_source_version=(
                        entry.subjective_probability_source_version
                    ),
                    model_probability=entry.model_probability,
                    model_probability_source_version=(
                        entry.model_probability_source_version or None
                    ),
                    model_promotion_decision_id=(entry.model_promotion_decision_id or None),
                )
                outcome = (
                    ForecastOutcome._default_manager.using(self._using)
                    .select_for_update()
                    .filter(entry_id=entry.entry_id, finalized_at__lte=as_of)
                    .first()
                )
                if outcome is None:
                    return ForecastCalibrationEntryOwnerRecord.create(
                        entry_id=entry.entry_id,
                        binding=binding,
                        pit_manifest_id=entry.pit_manifest_id,
                        published_at=entry.published_at,
                        horizon_end=entry.horizon_end,
                        entry_recorded_at=entry.created_at,
                        resolution=ForecastCalibrationResolution.UNRESOLVED,
                        scenario_realized=None,
                        outcome_recorded_at=None,
                        outcome_source_type=None,
                        outcome_source_hash=None,
                        invalidation=None,
                    )
                if type(outcome.scenario_realized) is not bool:
                    raise ForecastCalibrationEntryOwnerCorruption(
                        "ForecastOutcome lacks an explicit canonical censored/invalidation contract"
                    )
                return ForecastCalibrationEntryOwnerRecord.create(
                    entry_id=entry.entry_id,
                    binding=binding,
                    pit_manifest_id=entry.pit_manifest_id,
                    published_at=entry.published_at,
                    horizon_end=entry.horizon_end,
                    entry_recorded_at=entry.created_at,
                    resolution=ForecastCalibrationResolution.RESOLVED,
                    scenario_realized=outcome.scenario_realized,
                    outcome_recorded_at=outcome.finalized_at,
                    outcome_source_type=outcome.outcome_type,
                    outcome_source_hash=_source_hash(outcome),
                    invalidation=None,
                )
            except ForecastCalibrationEntryOwnerCorruption:
                raise
            except (AttributeError, TypeError, ValueError) as exc:
                raise ForecastCalibrationEntryOwnerCorruption(
                    "Forecast Ledger/Outcome rows cannot be restored exactly"
                ) from exc


__all__ = [
    "DjangoForecastCalibrationEntryOwnerProvider",
    "ForecastCalibrationEntryOwnerCorruption",
]
