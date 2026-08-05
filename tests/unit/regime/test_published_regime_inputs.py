"""Publication-bound input contracts for the Regime V2 use case."""

from __future__ import annotations

from datetime import date

from apps.regime.application.use_cases import CalculateRegimeV2Request, CalculateRegimeV2UseCase
from apps.regime.domain.protocols import MacroIndicator
from apps.regime.domain.services_v2 import ThresholdConfig


class _RecordingRepository:
    """Small repository fake that records the current-data selector."""

    GROWTH_INDICATORS = {"PMI": "CN_PMI"}
    INFLATION_INDICATORS = {"CPI": "CN_CPI_NATIONAL_YOY"}

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self._growth = [50.0, 50.1, 50.2]
        self._inflation = [0.1, 0.2, 0.3]
        self._growth_full = [
            MacroIndicator(code="CN_PMI", value=value, reporting_period=date(2026, 7, index + 1))
            for index, value in enumerate(self._growth)
        ]
        self._inflation_full = [
            MacroIndicator(
                code="CN_CPI_NATIONAL_YOY",
                value=value,
                reporting_period=date(2026, 7, index + 1),
            )
            for index, value in enumerate(self._inflation)
        ]

    def get_growth_series(self, **kwargs):
        self.calls.append(("growth", bool(kwargs["published_only"])))
        return list(self._growth)

    def get_inflation_series(self, **kwargs):
        self.calls.append(("inflation", bool(kwargs["published_only"])))
        return list(self._inflation)

    def get_growth_series_full(self, **kwargs):
        self.calls.append(("growth_full", bool(kwargs["published_only"])))
        return list(self._growth_full)

    def get_inflation_series_full(self, **kwargs):
        self.calls.append(("inflation_full", bool(kwargs["published_only"])))
        return list(self._inflation_full)


def test_v2_published_only_propagates_to_every_regime_input_read() -> None:
    """Both calculation and audit raw-data reads must share publication semantics."""

    repository = _RecordingRepository()
    use_case = CalculateRegimeV2UseCase(repository)
    use_case._load_threshold_config = lambda: ThresholdConfig()  # type: ignore[method-assign]

    response = use_case.execute(
        CalculateRegimeV2Request(
            as_of_date=date(2026, 7, 31),
            use_pit=True,
            published_only=True,
        )
    )

    assert response.success is True
    assert repository.calls == [
        ("growth", True),
        ("inflation", True),
        ("growth_full", True),
        ("inflation_full", True),
    ]
