from datetime import date

import pandas as pd
import pytest

from apps.data_center.infrastructure.macro_sources.base import (
    DataValidationError,
    MacroDataPoint,
)
from apps.data_center.infrastructure.macro_sources.fetchers.base_fetchers import (
    BaseIndicatorFetcher,
)
from apps.data_center.infrastructure.macro_sources.fetchers.common import resolve_indicator_units
from apps.data_center.infrastructure.macro_sources.fetchers.economic_fetchers import (
    EconomicIndicatorFetcher,
    parse_chinese_quarter,
)
from apps.data_center.infrastructure.macro_sources.fetchers.other_fetchers import (
    OtherIndicatorFetcher,
)
from apps.data_center.infrastructure.macro_sources.fetchers.trade_fetchers import (
    TradeIndicatorFetcher,
)


class _NoOpAK:
    def macro_china_gyzjz(self):
        return pd.DataFrame(
            {
                "发布时间": ["2025-04-16"],
                "月份": ["2025年03月份"],
                "同比增长": [6.2],
                "累计增长": [6.5],
            }
        )

    def macro_china_gdp(self):
        return pd.DataFrame(
            {
                "季度": ["2025年第1-4季度"],
                "国内生产总值-绝对值": [1349084.0],
                "国内生产总值-同比增长": [5.0],
            }
        )

    def macro_china_money_supply(self):
        return pd.DataFrame(
            {
                "月份": ["2025年03月份"],
                "货币和准货币(M2)-数量(亿元)": [3261300.0],
                "货币和准货币(M2)-同比增长": [7.0],
            }
        )

    def macro_china_exports_yoy(self):
        return pd.DataFrame(
            {
                "商品": ["中国出口年率"],
                "日期": ["2025-03-01"],
                "今值": [12.4],
                "预测值": [10.0],
                "前值": [7.1],
            }
        )

    def macro_china_gdzctz(self):
        return pd.DataFrame(
            {
                "月份": ["2024年03月份", "2025年03月份"],
                "当月": [38000.0, 40940.0],
                "同比增长": [3.5, 4.6],
                "环比增长": [0.2, 0.3],
                "自年初累计": [100000.0, 112000.0],
            }
        )

    def macro_china_hgjck(self):
        return pd.DataFrame(
            {
                "月份": ["2025年03月份"],
                "当月出口额-金额": [321032652.74],
                "当月出口额-同比增长": [2.5],
                "当月出口额-环比增长": [7.1],
                "当月进口额-金额": [269903560.06],
                "当月进口额-同比增长": [27.8],
                "当月进口额-环比增长": [29.1],
                "累计出口额-金额": [977493896.094],
                "累计出口额-同比增长": [14.7],
                "累计进口额-金额": [713160870.19],
                "累计进口额-同比增长": [22.7],
            }
        )

    def macro_china_shrzgm(self):
        return pd.DataFrame(
            {
                "月份": ["202403", "202503"],
                "社会融资规模增量": [10000.0, 12500.0],
            }
        )

    def macro_china_consumer_goods_retail(self):
        return pd.DataFrame(
            {
                "月份": ["2025年03月份"],
                "当月": [40940.0],
                "同比增长": [4.6],
                "环比增长": [0.3],
                "累计": [124671.0],
                "累计-同比增长": [4.5],
            }
        )

    def macro_china_fx_gold(self):
        return pd.DataFrame(
            {
                "月份": ["2025年03月份"],
                "国家外汇储备-数值": [32407.0],
            }
        )


class _BrokenUnemploymentAK:
    def macro_china_urban_unemployment(self):
        raise ValueError("JSON decode failed")


class _RateLikeOtherAK:
    def macro_china_urban_unemployment(self):
        return pd.DataFrame(
            {
                "date": ["202503", "202503"],
                "item": ["全国城镇调查失业率", "31个大城市城镇调查失业率"],
                "value": [5.2, 5.1],
            }
        )

    def macro_china_new_house_price(self):
        return pd.DataFrame(
            {
                "日期": ["2025-03-01", "2025-03-01"],
                "城市": ["上海", "北京"],
                "新建商品住宅价格指数-同比": [109.9, 101.4],
            }
        )

    def energy_oil_hist(self):
        return pd.DataFrame(
            {
                "调整日期": ["2025-03-01"],
                "汽油价格": [8_160.0],
                "柴油价格": [7_200.0],
            }
        )


class _InvalidUnemploymentValueAK(_RateLikeOtherAK):
    def macro_china_urban_unemployment(self):
        return pd.DataFrame(
            {
                "date": ["202502", "202503"],
                "item": ["全国城镇调查失业率", "全国城镇调查失业率"],
                "value": ["--", 0.0],
            }
        )


class _UnemploymentSchemaDriftAK(_RateLikeOtherAK):
    def macro_china_urban_unemployment(self):
        return pd.DataFrame(
            {
                "月份": ["202503"],
                "指标": ["全国城镇调查失业率"],
                "数值": [5.2],
            }
        )


def _validate(point):
    return point


def _sort(points):
    return points


@pytest.fixture(autouse=True)
def governed_macro_runtime_metadata(monkeypatch) -> None:
    class _ThousandUsdRule:
        original_unit = "千美元"
        storage_unit = "元"
        display_unit = "亿美元"

    class _UnitRuleRepository:
        @staticmethod
        def resolve_active_rule(
            indicator_code,
            *,
            source_type="",
            original_unit="",
        ):
            if (
                indicator_code in {"CN_EXPORTS", "CN_IMPORTS", "CN_TRADE_BALANCE"}
                and source_type == "akshare"
                and original_unit == "千美元"
            ):
                return _ThousandUsdRule()
            return None

    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.fetchers.common.get_runtime_macro_index_metadata_map",
        lambda: {
            "CN_GDP": {"default_unit": "亿元", "governance_scope": "macro_console"},
            "CN_GDP_YOY": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_VALUE_ADDED": {
                "default_unit": "%",
                "governance_scope": "macro_console",
            },
            "CN_M2_YOY": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_EXPORTS": {"default_unit": "亿美元", "governance_scope": "macro_console"},
            "CN_EXPORT_YOY": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_IMPORTS": {"default_unit": "亿美元", "governance_scope": "macro_console"},
            "CN_IMPORT_YOY": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_RETAIL_SALES": {"default_unit": "亿元", "governance_scope": "macro_console"},
            "CN_RETAIL_SALES_YOY": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_FIXED_INVESTMENT": {
                "default_unit": "亿元",
                "governance_scope": "macro_console",
            },
            "CN_FAI_YOY": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_SOCIAL_FINANCING": {
                "default_unit": "亿元",
                "governance_scope": "macro_console",
            },
            "CN_SOCIAL_FINANCING_YOY": {
                "default_unit": "%",
                "governance_scope": "macro_console",
            },
            "CN_FX_RESERVES": {"default_unit": "亿美元", "governance_scope": "macro_console"},
            "CN_UNEMPLOYMENT": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_NEW_HOUSE_PRICE": {
                "default_unit": "%",
                "governance_scope": "macro_console",
            },
            "CN_OIL_PRICE": {
                "default_unit": "元/吨",
                "governance_scope": "macro_console",
            },
        },
    )
    monkeypatch.setattr(
        "apps.data_center.composition.get_indicator_unit_rule_repository",
        lambda: _UnitRuleRepository(),
    )


def test_parse_chinese_quarter_supports_cumulative_quarter_labels() -> None:
    assert parse_chinese_quarter("2025年第1-4季度") == "2025-12-01"
    assert parse_chinese_quarter("2025年第1-3季度") == "2025-09-01"
    assert parse_chinese_quarter("2025年第5季度") == "2025年第5季度"
    assert parse_chinese_quarter("2025年第4-1季度") == "2025年第4-1季度"


def test_resolve_indicator_units_prefers_runtime_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.fetchers.common.get_runtime_macro_index_metadata_map",
        lambda: {"TEST.RUNTIME": {"default_unit": "亿千瓦时"}},
    )

    assert resolve_indicator_units("TEST.RUNTIME") == ("亿千瓦时", "亿千瓦时")


def test_resolve_indicator_units_blocks_governed_fallback_without_metadata_or_rule(
    monkeypatch,
) -> None:
    class _EmptyRuleRepo:
        @staticmethod
        def resolve_active_rule(*args, **kwargs):
            return None

    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.fetchers.common.get_runtime_macro_index_metadata_map",
        lambda: {"TEST.GOV": {"governance_scope": "macro_console"}},
    )
    monkeypatch.setattr(
        "apps.data_center.composition.get_indicator_unit_rule_repository",
        lambda: _EmptyRuleRepo(),
    )

    with pytest.raises(ValueError, match="Governed indicator TEST.GOV"):
        resolve_indicator_units("TEST.GOV")


def test_resolve_indicator_units_blocks_ungoverned_missing_metadata_without_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.fetchers.common.get_runtime_macro_index_metadata_map",
        lambda: {},
    )

    with pytest.raises(ValueError, match="Indicator TEST.GOV"):
        resolve_indicator_units("TEST.GOV")


def test_macro_data_point_published_at_prefers_runtime_publication_lags(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.base.get_runtime_macro_publication_lags",
        lambda: {"TEST.RUNTIME": {"days": 7, "description": "T+7"}},
    )

    point = MacroDataPoint(
        code="TEST.RUNTIME",
        value=1.0,
        observed_at=date(2025, 3, 1),
    )

    assert point.published_at == date(2025, 3, 8)


def test_fetch_gdp_uses_named_absolute_value_column() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_gdp(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_GDP"
    assert points[0].value == 1349084.0
    assert points[0].observed_at == date(2025, 12, 1)


def test_fetch_gdp_uses_resolved_units(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.fetchers.economic_fetchers.resolve_indicator_units",
        lambda indicator_code: ("测试单位", "测试单位"),
    )
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_gdp(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].unit == "测试单位"
    assert points[0].original_unit == "测试单位"


def test_fetch_gdp_yoy_uses_named_growth_column() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_gdp_yoy(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_GDP_YOY"
    assert points[0].value == 5.0
    assert points[0].unit == "%"
    assert points[0].observed_at == date(2025, 12, 1)


def test_fetch_value_added_uses_named_yoy_column() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_value_added(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_VALUE_ADDED"
    assert points[0].value == 6.2
    assert points[0].unit == "%"
    assert points[0].observed_at == date(2025, 3, 1)


class _DriftedGdpAK(_NoOpAK):
    def macro_china_gdp(self):
        return pd.DataFrame(
            {
                "unknown_period": ["2025年第1-4季度"],
                "unknown_value": [1349084.0],
            }
        )


def test_fetch_gdp_rejects_schema_drift_instead_of_guessing_position() -> None:
    fetcher = EconomicIndicatorFetcher(_DriftedGdpAK(), "akshare", _validate, _sort)

    with pytest.raises(DataValidationError, match="CN_GDP 数据缺少必需列"):
        fetcher.fetch_gdp(date(2025, 1, 1), date(2025, 12, 31))


def test_fetch_m2_yoy_uses_named_growth_column() -> None:
    fetcher = BaseIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_m2_yoy(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_M2_YOY"
    assert points[0].value == 7.0
    assert points[0].unit == "%"
    assert points[0].observed_at == date(2025, 3, 31)


def test_fetch_exports_accepts_current_value_column() -> None:
    fetcher = TradeIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_exports(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_EXPORTS"
    assert points[0].value == pytest.approx(321032652.74)
    assert points[0].unit == "千美元"
    assert points[0].observed_at == date(2025, 3, 1)


def test_fetch_export_yoy_uses_monthly_growth_column() -> None:
    fetcher = TradeIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_export_yoy(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_EXPORT_YOY"
    assert points[0].value == 2.5
    assert points[0].unit == "%"


def test_fetch_imports_accepts_amount_column() -> None:
    fetcher = TradeIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_imports(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_IMPORTS"
    assert points[0].value == pytest.approx(269903560.06)
    assert points[0].unit == "千美元"


def test_fetch_import_yoy_uses_monthly_growth_column() -> None:
    fetcher = TradeIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_import_yoy(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_IMPORT_YOY"
    assert points[0].value == 27.8
    assert points[0].unit == "%"


def test_fetch_trade_balance_is_derived_from_same_month_customs_amounts() -> None:
    fetcher = TradeIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_trade_balance(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_TRADE_BALANCE"
    assert points[0].value == pytest.approx(51129092.68)
    assert points[0].unit == "千美元"
    assert points[0].observed_at == date(2025, 3, 1)


class _DriftedTradeAK(_NoOpAK):
    def macro_china_hgjck(self):
        return pd.DataFrame(
            {
                "月份": ["2025年03月份"],
                "出口": [321032652.74],
                "进口": [269903560.06],
            }
        )


class _PartiallyInvalidTradeAK(_NoOpAK):
    def macro_china_hgjck(self):
        return pd.DataFrame(
            {
                "月份": ["2025年01月份", "2025年02月份", "2025年03月份"],
                "当月出口额-金额": ["--", 0.0, 321032652.74],
                "当月进口额-金额": [250000000.0, 250000000.0, 269903560.06],
            }
        )


def test_fetch_trade_balance_rejects_schema_drift() -> None:
    fetcher = TradeIndicatorFetcher(_DriftedTradeAK(), "akshare", _validate, _sort)

    with pytest.raises(DataValidationError, match="CN_TRADE_BALANCE 数据缺少必需列"):
        fetcher.fetch_trade_balance(date(2025, 1, 1), date(2025, 12, 31))


def test_fetch_trade_balance_skips_invalid_row_and_keeps_valid_month() -> None:
    fetcher = TradeIndicatorFetcher(
        _PartiallyInvalidTradeAK(),
        "akshare",
        _validate,
        _sort,
    )

    points = fetcher.fetch_trade_balance(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].observed_at == date(2025, 3, 1)
    assert points[0].value == pytest.approx(51129092.68)


def test_fetch_retail_sales_uses_monthly_level_column() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_retail_sales(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_RETAIL_SALES"
    assert points[0].value == 40940.0
    assert points[0].unit == "亿元"


def test_fetch_retail_sales_yoy_uses_growth_column() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_retail_sales_yoy(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_RETAIL_SALES_YOY"
    assert points[0].value == 4.6
    assert points[0].unit == "%"


def test_fetch_fixed_investment_uses_cumulative_level_column() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_fixed_investment(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_FIXED_INVESTMENT"
    assert points[0].value == 112000.0
    assert points[0].unit == "亿元"


def test_fetch_fixed_investment_yoy_derives_from_cumulative_values() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_fixed_investment_yoy(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_FAI_YOY"
    assert points[0].value == pytest.approx(12.0)
    assert points[0].unit == "%"


@pytest.mark.parametrize(
    ("prior_value", "current_value"),
    [(0.0, 112000.0), (-100000.0, 112000.0), (100000.0, -112000.0)],
)
def test_fetch_fixed_investment_yoy_skips_non_positive_cumulative_values(
    prior_value,
    current_value,
) -> None:
    class _NonPositiveInvestmentAK(_NoOpAK):
        def macro_china_gdzctz(self):
            return pd.DataFrame(
                {
                    "月份": ["2024年03月份", "2025年03月份"],
                    "自年初累计": [prior_value, current_value],
                }
            )

    fetcher = EconomicIndicatorFetcher(
        _NonPositiveInvestmentAK(),
        "akshare",
        _validate,
        _sort,
    )

    points = fetcher.fetch_fixed_investment_yoy(
        date(2025, 1, 1),
        date(2025, 12, 31),
    )

    assert points == []


def test_fetch_social_financing_uses_monthly_flow_column() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_social_financing(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_SOCIAL_FINANCING"
    assert points[0].value == 12500.0
    assert points[0].unit == "亿元"


def test_fetch_social_financing_yoy_derives_from_same_month_flow() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_social_financing_yoy(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_SOCIAL_FINANCING_YOY"
    assert points[0].value == pytest.approx(25.0)
    assert points[0].unit == "%"


class _NegativeBaseSocialFinancingAK(_NoOpAK):
    def macro_china_shrzgm(self):
        return pd.DataFrame(
            {
                "月份": ["202404", "202504"],
                "社会融资规模增量": [-658.0, 11599.0],
            }
        )


def test_fetch_social_financing_yoy_skips_non_positive_prior_flow_base() -> None:
    fetcher = EconomicIndicatorFetcher(
        _NegativeBaseSocialFinancingAK(), "akshare", _validate, _sort
    )

    points = fetcher.fetch_social_financing_yoy(date(2025, 1, 1), date(2025, 12, 31))

    assert points == []


def test_fetch_fx_reserves_keeps_catalog_unit_in_hundred_million_usd() -> None:
    from apps.data_center.infrastructure.macro_sources.fetchers.financial_fetchers import (
        FinancialIndicatorFetcher,
    )

    fetcher = FinancialIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_fx_reserves(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_FX_RESERVES"
    assert points[0].value == 32407.0
    assert points[0].unit == "亿美元"


def test_fetch_unemployment_propagates_upstream_failure() -> None:
    fetcher = OtherIndicatorFetcher(_BrokenUnemploymentAK(), "akshare", _validate, _sort)

    with pytest.raises(ValueError, match="JSON decode failed"):
        fetcher.fetch_unemployment(date(2025, 1, 1), date(2025, 12, 31))


def test_fetch_unemployment_keeps_percent_point_values() -> None:
    fetcher = OtherIndicatorFetcher(_RateLikeOtherAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_unemployment(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_UNEMPLOYMENT"
    assert points[0].value == 5.2
    assert points[0].unit == "%"


def test_fetch_unemployment_does_not_turn_invalid_text_into_zero() -> None:
    fetcher = OtherIndicatorFetcher(
        _InvalidUnemploymentValueAK(),
        "akshare",
        _validate,
        _sort,
    )

    points = fetcher.fetch_unemployment(date(2025, 1, 1), date(2025, 12, 31))

    assert points == []


def test_fetch_unemployment_rejects_schema_drift() -> None:
    fetcher = OtherIndicatorFetcher(
        _UnemploymentSchemaDriftAK(),
        "akshare",
        _validate,
        _sort,
    )

    with pytest.raises(DataValidationError, match="缺少必需列"):
        fetcher.fetch_unemployment(date(2025, 1, 1), date(2025, 12, 31))


def test_fetch_new_house_price_returns_percent_point_change() -> None:
    fetcher = OtherIndicatorFetcher(_RateLikeOtherAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_new_house_price(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_NEW_HOUSE_PRICE"
    assert points[0].value == pytest.approx(1.4)
    assert points[0].unit == "%"


def test_fetch_oil_price_keeps_governed_source_unit_without_density_guess() -> None:
    fetcher = OtherIndicatorFetcher(_RateLikeOtherAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_oil_price(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_OIL_PRICE"
    assert points[0].value == 8_160.0
    assert points[0].unit == "元/吨"
