from datetime import date

import pandas as pd

from apps.macro.infrastructure.adapters.fetchers.base_fetchers import BaseIndicatorFetcher
from apps.macro.infrastructure.adapters.fetchers.economic_fetchers import (
    EconomicIndicatorFetcher,
    parse_chinese_quarter,
)
from apps.macro.infrastructure.adapters.fetchers.other_fetchers import OtherIndicatorFetcher
from apps.macro.infrastructure.adapters.fetchers.trade_fetchers import TradeIndicatorFetcher


class _NoOpAK:
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


class _BrokenUnemploymentAK:
    def macro_china_urban_unemployment(self):
        raise ValueError("JSON decode failed")


def _validate(point):
    return point


def _sort(points):
    return points


def test_parse_chinese_quarter_supports_cumulative_quarter_labels() -> None:
    assert parse_chinese_quarter("2025年第1-4季度") == "2025-12-01"
    assert parse_chinese_quarter("2025年第1-3季度") == "2025-09-01"


def test_fetch_gdp_uses_named_absolute_value_column() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_gdp(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_GDP"
    assert points[0].value == 1349084.0
    assert points[0].observed_at == date(2025, 12, 1)


def test_fetch_gdp_yoy_uses_named_growth_column() -> None:
    fetcher = EconomicIndicatorFetcher(_NoOpAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_gdp_yoy(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].code == "CN_GDP_YOY"
    assert points[0].value == 5.0
    assert points[0].unit == "%"
    assert points[0].observed_at == date(2025, 12, 1)


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
    assert points[0].value == 12.4
    assert points[0].observed_at == date(2025, 3, 1)


def test_fetch_unemployment_gracefully_skips_upstream_parse_failure() -> None:
    fetcher = OtherIndicatorFetcher(_BrokenUnemploymentAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_unemployment(date(2025, 1, 1), date(2025, 12, 31))

    assert points == []
