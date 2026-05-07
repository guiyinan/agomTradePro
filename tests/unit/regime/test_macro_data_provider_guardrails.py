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
