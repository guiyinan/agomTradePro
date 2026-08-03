from datetime import date

import pytest

import apps.regime.infrastructure.macro_data_provider as macro_provider
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel
from apps.prompt.infrastructure.adapters.macro_adapter import MacroDataAdapter


@pytest.mark.django_db
def test_prompt_macro_adapter_reads_data_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    IndicatorCatalogModel.objects.update_or_create(
        code="PROMPT_TEST_PMI",
        defaults={
            "name_cn": "采购经理指数",
            "default_unit": "指数",
            "default_period_type": "M",
            "category": "growth",
        },
    )
    MacroFactModel.objects.create(
        indicator_code="PROMPT_TEST_PMI",
        reporting_period=date(2025, 1, 1),
        value=51.1,
        unit="指数",
        source="akshare",
        published_at=date(2025, 1, 3),
    )
    monkeypatch.setattr(
        macro_provider,
        "get_published_macro_fact_series",
        lambda *_args, **_kwargs: {
            "rows": [
                {
                    "indicator_code": "PROMPT_TEST_PMI",
                    "reporting_period": "2025-01-01",
                    "value": 51.1,
                    "unit": "指数",
                    "published_at": "2025-01-03",
                    "source": "akshare",
                    "extra": {"period_type": "M"},
                }
            ],
            "must_not_use_for_decision": False,
        },
    )

    adapter = MacroDataAdapter()

    assert adapter.get_indicator_value("PROMPT_TEST_PMI") == pytest.approx(51.1)


@pytest.mark.django_db
def test_prompt_macro_tools_preserve_publication_cutoff_and_real_trend() -> None:
    IndicatorCatalogModel.objects.update_or_create(
        code="PROMPT_TEST_PMI",
        defaults={
            "name_cn": "采购经理指数",
            "default_unit": "指数",
            "default_period_type": "M",
            "category": "growth",
        },
    )
    MacroFactModel.objects.create(
        indicator_code="PROMPT_TEST_PMI",
        reporting_period=date(2025, 1, 1),
        value=50.0,
        unit="指数",
        source="akshare",
        published_at=date(2025, 1, 3),
    )
    MacroFactModel.objects.create(
        indicator_code="PROMPT_TEST_PMI",
        reporting_period=date(2025, 2, 1),
        value=52.0,
        unit="指数",
        source="akshare",
        published_at=date(2025, 3, 10),
    )
    adapter = MacroDataAdapter()

    assert adapter.get_indicator_value("PROMPT_TEST_PMI", date(2025, 2, 28)) == pytest.approx(50.0)
    assert adapter.get_indicator_value("PROMPT_TEST_PMI", date(2025, 3, 31)) == pytest.approx(52.0)
    assert adapter.calculate_trend("PROMPT_TEST_PMI", "3m", date(2025, 3, 31)) == {
        "indicator": "PROMPT_TEST_PMI",
        "period": "3m",
        "trend": "up",
        "change": 2.0,
        "change_pct": 4.0,
        "start_value": 50.0,
        "end_value": 52.0,
        "data_points": 2,
    }


@pytest.mark.parametrize(
    "publication_payload",
    [
        {
            "rows": [],
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_missing",
        },
        {
            "rows": [],
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_stale",
        },
    ],
)
def test_prompt_current_trend_does_not_fall_back_to_unpublished_macro_facts(
    monkeypatch: pytest.MonkeyPatch,
    publication_payload: dict[str, object],
) -> None:
    """Current prompt trend reads must fail closed when publication is missing/stale."""

    raw_reads = 0

    def _raw_facts(**_kwargs: object) -> list[dict[str, object]]:
        nonlocal raw_reads
        raw_reads += 1
        return [
            {
                "indicator_code": "CN_PMI",
                "reporting_period": "2026-06-01",
                "value": 50.0,
                "unit": "指数",
                "source": "raw",
            },
            {
                "indicator_code": "CN_PMI",
                "reporting_period": "2026-07-01",
                "value": 60.0,
                "unit": "指数",
                "source": "raw",
            },
        ]

    monkeypatch.setattr(macro_provider, "get_macro_fact_series", _raw_facts)
    monkeypatch.setattr(
        macro_provider,
        "get_published_macro_fact_series",
        lambda *_args, **_kwargs: publication_payload,
    )

    result = MacroDataAdapter().calculate_trend("CN_PMI", "3m")

    assert result["trend"] == "unknown"
    assert result["data_points"] == 0
    assert raw_reads == 0
