"""Read-only Research adapter tests for Signal calibration samples."""

from __future__ import annotations

from datetime import timedelta

from apps.research.domain.scenario_probability_contracts import ScenarioResearchScope
from apps.research.infrastructure.r7_forecast_calibration_sample_provider import (
    SignalForecastCalibrationSampleProvider,
)
from apps.signal.application.forecast_calibration_sample import (
    ExactForecastCalibrationSampleCommand,
)
from apps.signal.domain.forecast_calibration_sample import ForecastCalibrationSampleReceipt
from tests.unit.signal.test_forecast_calibration_sample import (
    NOW,
    REVISION_A,
    REVISION_B,
    SET_REVISION,
    WINDOW_END,
    WINDOW_START,
    _receipt,
)


def _scope() -> ScenarioResearchScope:
    return ScenarioResearchScope.create(
        scope_version="scope.v1",
        scenario_set_revision_id=SET_REVISION,
        scenario_revision_ids=(REVISION_A, REVISION_B),
        forecast_horizon=timedelta(days=10),
        censoring_rule_version="censor.v1",
        path_horizon_periods=2,
        path_initial_state_revision_ids=(REVISION_A,),
    )


class _Query:
    unit_of_work_key = "django:default"

    def __init__(self, value: ForecastCalibrationSampleReceipt | None) -> None:
        self.value = value
        self.calls: list[ExactForecastCalibrationSampleCommand] = []

    def execute(
        self,
        command: ExactForecastCalibrationSampleCommand,
    ) -> ForecastCalibrationSampleReceipt | None:
        self.calls.append(command)
        return self.value


def test_adapter_preserves_full_denominator_and_raw_outcome_absence() -> None:
    """Resolved and unresolved/censored members are projected without synthesis."""

    scope = _scope()
    query = _Query(_receipt(scope.content_hash))
    provider = SignalForecastCalibrationSampleProvider(query)

    observations = provider.list_exact(
        scope=scope,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        as_of=NOW,
    )

    assert len(query.calls) == 1
    assert len(observations) == 4
    assert observations[0].scenario_realized is True
    assert observations[1].scenario_realized is False
    assert observations[2].scenario_realized is None
    assert observations[2].outcome_recorded_at is None
    assert observations[2].outcome_evidence_valid_until is None
    assert observations[3].scenario_realized is None
    assert observations[3].outcome_recorded_at is None


def test_adapter_preserves_empty_owner_as_empty_observation_set() -> None:
    """Missing owner data stays empty so R7 remains evidence-blocked."""

    scope = _scope()
    query = _Query(None)
    provider = SignalForecastCalibrationSampleProvider(query)

    assert (
        provider.list_exact(
            scope=scope,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            as_of=NOW,
        )
        == ()
    )
