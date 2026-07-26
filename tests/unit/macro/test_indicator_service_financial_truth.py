from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from apps.macro.application import indicator_service
from apps.macro.application.indicator_service import (
    IndicatorService,
    IndicatorUnitRuleService,
    UnitDisplayService,
)


def test_catalog_extra_cannot_override_canonical_metadata(monkeypatch) -> None:
    catalog = SimpleNamespace(
        code="CN_GDP",
        name_cn="国内生产总值",
        name_en="GDP",
        category="增长",
        description="正式说明",
        extra={
            "name": "伪造名称",
            "category": "伪造分类",
            "unit": "伪造单位",
            "description": "伪造说明",
            "series_semantics": "cumulative_level",
        },
    )
    monkeypatch.setattr(
        indicator_service,
        "get_indicator_catalog_repository",
        lambda: SimpleNamespace(list_all=lambda: [catalog]),
    )
    monkeypatch.setattr(
        indicator_service,
        "get_indicator_unit_rule_repository",
        lambda: SimpleNamespace(
            resolve_active_rule=lambda code: SimpleNamespace(
                display_unit="亿元",
                original_unit="亿元",
                storage_unit="元",
            )
        ),
    )

    metadata = IndicatorService.get_indicator_metadata_map()["CN_GDP"]

    assert metadata["name"] == "国内生产总值"
    assert metadata["category"] == "增长"
    assert metadata["unit"] == "亿元"
    assert metadata["description"] == "正式说明"
    assert metadata["series_semantics"] == "cumulative_level"


def test_unit_conversion_rejects_non_finite_and_invalid_rules(monkeypatch) -> None:
    with pytest.raises(ValueError, match="finite"):
        UnitDisplayService.convert_for_display(float("nan"), "元", "亿元")
    with pytest.raises(ValueError, match="precision"):
        UnitDisplayService.format_for_display(1.0, "元", "元", precision=True)

    monkeypatch.setattr(
        IndicatorUnitRuleService,
        "_get_default_rule",
        classmethod(
            lambda cls, code: {
                "multiplier_to_storage": 0,
                "storage_unit": "元",
            }
        ),
    )
    with pytest.raises(ValueError, match="multiplier"):
        IndicatorUnitRuleService.get_normalized_unit_and_value("CN_GDP", 1.0)


def test_failed_display_conversion_keeps_truthful_storage_unit() -> None:
    value, unit = UnitDisplayService.convert_for_display(
        10.0,
        "指数",
        "亿元",
    )

    assert value == 10.0
    assert unit == "指数"


class _InvalidValueRepository:
    def list_distinct_codes(self) -> list[str]:
        return ["GOOD", "BAD"]

    def get_latest_indicator(self, code: str) -> dict[str, object]:
        return {
            "value": 1.5 if code == "GOOD" else float("inf"),
            "reporting_period": date(2026, 7, 1),
            "period_type": "M",
            "unit": "%",
        }

    def get_indicator_stats(
        self,
        code: str,
        start_date: date,
    ) -> dict[str, object]:
        return {
            "avg_value": float("nan"),
            "max_value": 2.0,
            "min_value": 1.0,
        }

    def get_indicator_history(
        self,
        code: str,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[dict[str, object]]:
        return [
            {
                "value": float("nan"),
                "reporting_period": date(2026, 6, 1),
                "period_type": "M",
            },
            {
                "value": 1.5,
                "reporting_period": "not-a-date",
                "period_type": "M",
            },
            {
                "value": 1.6,
                "reporting_period": date(2026, 7, 1),
                "period_type": "M",
            },
        ]


def test_indicator_outputs_drop_non_finite_and_malformed_points(monkeypatch) -> None:
    monkeypatch.setattr(IndicatorService, "read_repository", _InvalidValueRepository())
    monkeypatch.setattr(
        IndicatorService,
        "get_indicator_metadata_map",
        classmethod(lambda cls: {}),
    )

    available = IndicatorService.get_available_indicators(include_stats=True)
    history = IndicatorService.get_indicator_history("GOOD", periods=12)

    assert [item["code"] for item in available] == ["GOOD"]
    assert available[0]["avg_value"] is None
    assert history == [
        {
            "date": "2026-07-01",
            "value": 1.6,
            "unit": "",
            "period_type": "M",
        }
    ]
    with pytest.raises(ValueError, match="1 to 1200"):
        IndicatorService.get_indicator_history("GOOD", periods=0)
