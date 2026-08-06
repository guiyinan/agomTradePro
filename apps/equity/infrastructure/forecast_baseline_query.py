"""Django exact-query adapter for immutable forecast-baseline trial records."""

from __future__ import annotations

from datetime import datetime

from apps.equity.application.forecast_baseline_materialize import VersionRef
from apps.equity.application.forecast_baseline_query import (
    ExactForecastBaselineTrialRecord,
)

from .forecast_baseline_models import ForecastBaselineTrialResultModel
from .forecast_baseline_repository import DjangoForecastBaselineRepository


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class DjangoExactForecastBaselineTrialQuery:
    """Restore a full Equity trial and expose its owner receipt boundary."""

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Identify the database that owns the immutable trial row."""

        return f"django:{self._using}"

    def get_exact(
        self,
        trial_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> ExactForecastBaselineTrialRecord | None:
        """Return an exact row only after its owner-recorded knowledge time."""

        _require_aware(as_of, "forecast baseline trial as_of")
        model = (
            ForecastBaselineTrialResultModel._default_manager.using(self._using)
            .select_related(
                "spec",
                "spec__approval",
                "artifact",
                "artifact__spec",
                "artifact__spec__approval",
            )
            .filter(
                result_id=trial_ref.stable_id,
                result_version=trial_ref.version,
                recorded_at__lte=as_of,
            )
            .first()
        )
        if model is None:
            return None
        result = DjangoForecastBaselineRepository._trial_from_model(model)
        return ExactForecastBaselineTrialRecord(
            result=result,
            recorded_at=model.recorded_at,
            owner_record_key=model.pk,
        )


__all__ = ["DjangoExactForecastBaselineTrialQuery"]
