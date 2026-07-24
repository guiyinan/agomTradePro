from datetime import date

import pytest

from apps.data_center.infrastructure.models import MacroFactModel
from apps.regime.infrastructure.macro_data_provider import DataCenterMacroRepositoryAdapter


def test_regime_macro_repository_blocks_cumulative_level_growth_inputs(monkeypatch):
    adapter = DataCenterMacroRepositoryAdapter()
    called = {"count": 0}

    monkeypatch.setattr(
        adapter,
        "_get_catalog_extra",
        lambda code: {
            "series_semantics": "cumulative_level",
            "regime_input_policy": "derive_required",
        },
    )

    def _unexpected_get_series(**kwargs):
        called["count"] += 1
        return ["should-not-be-read"]

    monkeypatch.setattr(adapter, "get_series", _unexpected_get_series)

    result = adapter.get_growth_series_full("CN_GDP")

    assert result == []
    assert called["count"] == 0


def test_regime_macro_repository_blocks_cumulative_level_inflation_inputs(monkeypatch):
    adapter = DataCenterMacroRepositoryAdapter()
    called = {"count": 0}

    monkeypatch.setattr(
        adapter,
        "_get_catalog_extra",
        lambda code: {
            "series_semantics": "cumulative_level",
            "regime_input_policy": "derive_required",
        },
    )

    def _unexpected_get_series(**kwargs):
        called["count"] += 1
        return ["should-not-be-read"]

    monkeypatch.setattr(adapter, "get_series", _unexpected_get_series)

    result = adapter.get_inflation_series_full("CN_GDP")

    assert result == []
    assert called["count"] == 0


@pytest.mark.parametrize("value", [0.1, -0.1, 0.0, 1.0])
def test_regime_adapter_preserves_canonical_cpi_yoy_percentage_points(value: float) -> None:
    """The V2 Regime adapter must not guess a second scale for canonical facts."""
    normalized = DataCenterMacroRepositoryAdapter._normalize_cpi_value(
        "CN_CPI_NATIONAL_YOY",
        value,
    )

    assert normalized == pytest.approx(value)


def test_regime_adapter_converts_legacy_cpi_index_from_base_100() -> None:
    normalized = DataCenterMacroRepositoryAdapter._normalize_cpi_value("CN_CPI", 100.1)

    assert normalized == pytest.approx(0.1)


@pytest.mark.django_db
def test_regime_adapter_prefers_canonical_fact_over_legacy_revision() -> None:
    """A canonical refresh must not be masked by a stale legacy revision-1 row."""
    common = {
        "indicator_code": "CN_CPI_NATIONAL_YOY",
        "reporting_period": date(2026, 6, 30),
        "unit": "%",
        "source": "akshare",
        "quality": "valid",
    }
    MacroFactModel.objects.create(
        **common,
        value="10.000000",
        revision_number=1,
        extra={"period_type": "M", "source_type": "akshare"},
    )
    MacroFactModel.objects.create(
        **common,
        value="1.000000",
        revision_number=0,
        extra={
            "period_type": "M",
            "source_type": "akshare",
            "provider_name": "AKShare Public",
        },
    )

    rows = DataCenterMacroRepositoryAdapter().get_series(
        "CN_CPI_NATIONAL_YOY",
        source="akshare",
    )

    assert [row.value for row in rows] == pytest.approx([1.0])
