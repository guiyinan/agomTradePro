from datetime import date

from apps.macro.application.indicator_service import (
    IndicatorService,
    IndicatorUnitRuleService,
    UnitDisplayService,
    get_available_indicators_for_frontend,
)


class _FakeIndicatorReadRepository:
    def list_distinct_codes(self) -> list[str]:
        return ["CN_GDP_YOY"]

    def get_latest_indicator(self, code: str) -> dict | None:
        if code != "CN_GDP_YOY":
            return None
        return {
            "code": code,
            "value": 5.2,
            "unit": "%",
            "original_unit": "%",
            "reporting_period": date(2026, 4, 1),
            "period_type": "M",
        }

    def get_indicator_stats(self, code: str, start_date: date) -> dict[str, float | None]:
        assert code == "CN_GDP_YOY"
        return {
            "avg_value": 4.8,
            "max_value": 5.6,
            "min_value": 4.2,
        }

    def get_indicator_history(
        self,
        code: str,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[dict]:
        return [
            {
                "value": 5.2,
                "unit": "%",
                "original_unit": "%",
                "reporting_period": date(2026, 4, 1),
                "period_type": "M",
            }
        ][:limit]

    def get_latest_values_by_codes(self, codes: list[str]) -> list[dict]:
        assert "CN_GDP_YOY" in codes
        assert "CN_GDP" not in codes
        return [
            {"code": "CN_GDP_YOY", "value": 5.1},
        ]

    def get_indicator_unit_config(
        self,
        indicator_code: str,
        source: str | None = None,
    ) -> dict | None:
        if indicator_code == "RUNTIME_ONLY":
            return {"original_unit": "亿元"}
        return None


def _patch_default_rules(monkeypatch, mapping: dict[str, dict[str, object]]):
    monkeypatch.setattr(
        IndicatorUnitRuleService,
        "_get_default_rule",
        classmethod(lambda cls, indicator_code: mapping.get(indicator_code)),
    )


def _patch_metadata_map(monkeypatch, metadata: dict[str, dict[str, object]]):
    monkeypatch.setattr(
        IndicatorService,
        "get_indicator_metadata_map",
        classmethod(lambda cls: metadata),
    )


def test_indicator_unit_rule_service_uses_dynamic_rule_repository(monkeypatch):
    _patch_default_rules(
        monkeypatch,
        {
            "RUNTIME_CODE": {
                "display_unit": "亿元",
                "original_unit": "亿元",
                "storage_unit": "元",
                "multiplier_to_storage": 100000000.0,
            }
        },
    )

    assert IndicatorUnitRuleService.get_unit_for_indicator("RUNTIME_CODE") == "亿元"


def test_indicator_unit_rule_service_uses_absolute_unit_for_cn_gdp(monkeypatch):
    _patch_default_rules(
        monkeypatch,
        {
            "CN_GDP": {
                "display_unit": "亿元",
                "original_unit": "亿元",
                "storage_unit": "元",
                "multiplier_to_storage": 100000000.0,
            }
        },
    )
    assert IndicatorUnitRuleService.get_unit_for_indicator("CN_GDP") == "亿元"


def test_indicator_unit_rule_service_uses_index_and_level_units_for_core_macro_series(monkeypatch):
    _patch_default_rules(
        monkeypatch,
        {
            "CN_CPI": {
                "display_unit": "指数",
                "original_unit": "指数",
                "storage_unit": "指数",
                "multiplier_to_storage": 1.0,
            },
            "CN_PPI": {
                "display_unit": "指数",
                "original_unit": "指数",
                "storage_unit": "指数",
                "multiplier_to_storage": 1.0,
            },
            "CN_M2": {
                "display_unit": "万亿元",
                "original_unit": "万亿元",
                "storage_unit": "元",
                "multiplier_to_storage": 1000000000000.0,
            },
        },
    )
    assert IndicatorUnitRuleService.get_unit_for_indicator("CN_CPI") == "指数"
    assert IndicatorUnitRuleService.get_unit_for_indicator("CN_PPI") == "指数"
    assert IndicatorUnitRuleService.get_unit_for_indicator("CN_M2") == "万亿元"


def test_indicator_service_does_not_fallback_gdp_yoy_to_gdp_level(monkeypatch):
    _patch_metadata_map(
        monkeypatch,
        {
            "CN_GDP_YOY": {"unit": "%"},
            "CN_GDP": {"unit": "亿元"},
        },
    )
    assert IndicatorService.get_code_candidates("CN_GDP_YOY") == ["CN_GDP_YOY"]


def test_indicator_service_blocks_rate_to_index_or_level_fallbacks(monkeypatch):
    _patch_metadata_map(
        monkeypatch,
        {
            "CN_CPI_YOY": {"unit": "%"},
            "CN_CPI_NATIONAL_YOY": {"unit": "%"},
            "CN_PPI_YOY": {"unit": "%"},
            "CN_M2_YOY": {"unit": "%"},
        },
    )
    assert IndicatorService.get_code_candidates("CN_CPI_YOY") == [
        "CN_CPI_YOY",
        "CN_CPI_NATIONAL_YOY",
    ]
    assert IndicatorService.get_code_candidates("CN_PPI_YOY") == ["CN_PPI_YOY"]
    assert IndicatorService.get_code_candidates("CN_M2_YOY") == ["CN_M2_YOY"]


def test_indicator_service_keeps_safe_same_semantics_aliases(monkeypatch):
    _patch_metadata_map(
        monkeypatch,
        {
            "CN_EXPORT_YOY": {"unit": "%"},
            "CN_EXPORTS": {"unit": "亿美元"},
            "CN_IMPORT_YOY": {"unit": "%"},
            "CN_IMPORTS": {"unit": "亿美元"},
            "CN_RETAIL_SALES_YOY": {"unit": "%"},
            "CN_RETAIL_SALES": {"unit": "亿元"},
        },
    )
    assert IndicatorService.get_code_candidates("CN_EXPORT_YOY") == [
        "CN_EXPORT_YOY"
    ]
    assert IndicatorService.get_code_candidates("CN_IMPORT_YOY") == [
        "CN_IMPORT_YOY"
    ]
    assert IndicatorService.get_code_candidates("CN_RETAIL_SALES_YOY") == [
        "CN_RETAIL_SALES_YOY"
    ]


def test_indicator_service_get_available_indicators_uses_read_repository(monkeypatch):
    monkeypatch.setattr(IndicatorService, "read_repository", _FakeIndicatorReadRepository())
    _patch_metadata_map(
        monkeypatch,
        {
            "CN_GDP_YOY": {
                "name": "GDP同比",
                "name_en": "GDP YoY",
                "category": "增长",
                "unit": "%",
                "description": "国内生产总值同比",
                "threshold_bullish": 5.0,
            }
        },
    )

    indicators = IndicatorService.get_available_indicators(include_stats=True)

    assert indicators == [
        {
            "code": "CN_GDP_YOY",
            "name": "GDP同比",
            "name_en": "GDP YoY",
            "category": "增长",
            "unit": "%",
            "description": "国内生产总值同比",
            "latest_value": 5.2,
            "latest_date": "2026-04-01",
            "period_type": "M",
            "threshold_bullish": 5.0,
            "threshold_bearish": None,
            "avg_value": 4.8,
            "max_value": 5.6,
            "min_value": 4.2,
        }
    ]


def test_indicator_service_exposes_clear_metadata_for_direct_level_and_index_series(monkeypatch):
    runtime_only = {
        "CN_GDP": {
            "name": "GDP（国内生产总值累计值）",
            "unit": "亿元",
            "description": "国内生产总值累计值，反映实体经济总量，非同比增速口径。",
        },
        "CN_M2": {
            "name": "M2（广义货币供应量余额）",
            "unit": "万亿元",
            "description": "广义货币供应量余额，反映货币总量，非同比增速口径。",
        },
        "CN_CPI": {
            "name": "CPI（居民消费价格指数）",
            "unit": "指数",
            "description": "居民消费价格指数水平值，非同比涨幅口径。",
        },
        "CN_PPI": {
            "name": "PPI（工业生产者出厂价格指数）",
            "unit": "指数",
            "description": "工业生产者出厂价格指数水平值，非同比涨幅口径。",
        },
    }
    _patch_metadata_map(monkeypatch, runtime_only)

    gdp = IndicatorService.get_indicator_metadata_map()["CN_GDP"]
    m2 = IndicatorService.get_indicator_metadata_map()["CN_M2"]
    cpi = IndicatorService.get_indicator_metadata_map()["CN_CPI"]
    ppi = IndicatorService.get_indicator_metadata_map()["CN_PPI"]

    assert gdp["name"] == "GDP（国内生产总值累计值）"
    assert gdp["unit"] == "亿元"
    assert "非同比增速" in gdp["description"]

    assert m2["name"] == "M2（广义货币供应量余额）"
    assert m2["unit"] == "万亿元"
    assert "非同比增速" in m2["description"]

    assert cpi["name"] == "CPI（居民消费价格指数）"
    assert cpi["unit"] == "指数"
    assert "非同比涨幅" in cpi["description"]

    assert ppi["name"] == "PPI（工业生产者出厂价格指数）"
    assert ppi["unit"] == "指数"
    assert "非同比涨幅" in ppi["description"]


def test_get_available_indicators_for_frontend_uses_batch_projection(monkeypatch):
    fake_repo = _FakeIndicatorReadRepository()
    monkeypatch.setattr(IndicatorService, "read_repository", fake_repo)
    monkeypatch.setattr(UnitDisplayService, "read_repository", fake_repo)
    _patch_metadata_map(
        monkeypatch,
        {
            "CN_GDP_YOY": {
                "name": "GDP同比",
                "category": "增长",
                "unit": "%",
                "threshold_bullish": 5.0,
            }
        },
    )

    indicators = get_available_indicators_for_frontend(include_stats=False)

    assert indicators == [
        {
            "code": "CN_GDP_YOY",
            "name": "GDP同比",
            "category": "增长",
            "latest_value": 5.2,
            "unit": "%",
        }
    ]
