"""T3A contracts for the Data Center macro fetcher matrix."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from apps.data_center.infrastructure.macro_sources.fetchers import (
    base_fetchers,
    economic_fetchers,
    financial_fetchers,
    other_fetchers,
    pmi_subitems_fetchers,
    trade_fetchers,
    weekly_indicators_fetchers,
)

START = date(2024, 1, 1)
END = date(2025, 12, 31)


def _units(_code: str) -> tuple[str, str]:
    return "%", "%"


def _identity(points: list[object]) -> list[object]:
    return points


class _AkshareFixture:
    def macro_china_pmi(self) -> pd.DataFrame:
        return pd.DataFrame({"月份": ["2024年1月"], "制造业-指数": [50.2]})

    def macro_china_cpi(self) -> pd.DataFrame:
        values: dict[str, list[object]] = {"月份": ["2024年1月"]}
        for index in range(1, 12):
            values[f"cpi_{index}"] = [100 + index]
        values["全国-当月"] = [100.5]
        return pd.DataFrame(values)

    def macro_china_ppi(self) -> pd.DataFrame:
        return pd.DataFrame({"月份": ["2024年1月"], "当月": [99.5], "同比": [-1.2]})

    def macro_china_money_supply(self) -> pd.DataFrame:
        return pd.DataFrame({"月份": ["2024年1月"], "M2": [300000], "M2同比增长": [8.7]})

    def macro_china_non_man_pmi(self) -> pd.DataFrame:
        return pd.DataFrame({"序号": [1], "日期": ["2024-01-31"], "今值": [51.0]})

    def macro_china_fx_gold(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "月份": ["2024年1月"],
                "a": [0],
                "b": [0],
                "c": [0],
                "国家外汇储备-数值": ["3,200"],
            }
        )

    def macro_china_lpr(self) -> pd.DataFrame:
        return pd.DataFrame({"日期": ["2024-01-20"], "1年期": ["3.45%"]})

    def macro_china_shibor_all(self) -> pd.DataFrame:
        return pd.DataFrame({"日期": ["2024-01-20"], "隔夜": ["1.8%"]})

    def macro_china_reserve_requirement_ratio(self) -> pd.DataFrame:
        return pd.DataFrame(
            [["2024年1月15日", "large bank", 10.5]],
            columns=["日期", "机构", "比例"],
        )

    def macro_china_new_financial_credit(self) -> pd.DataFrame:
        return pd.DataFrame({"月份": ["2024年1月"], "新增": ["4,900"]})

    def macro_rmb_deposit(self) -> pd.DataFrame:
        return pd.DataFrame({"月份": ["2024年1月"], "新增存款-数量": ["1,200"]})

    def macro_rmb_loan(self) -> pd.DataFrame:
        return pd.DataFrame({"月份": ["2024年1月"], "贷款": ["2,300"]})

    def repo_rate_hist(self, **_kwargs: str) -> pd.DataFrame:
        return pd.DataFrame({"date": ["2024-01-20"], "DR007": ["1.9%"]})

    def macro_china_pboc_open_market(self) -> pd.DataFrame:
        return pd.DataFrame({"日期": ["2024-01-20"], "净投放": ["1,000"]})

    def macro_china_gyzjz(self) -> pd.DataFrame:
        return pd.DataFrame([["2024年1月", 6.8]], columns=["月份", "同比"])

    def macro_china_consumer_goods_retail(self) -> pd.DataFrame:
        return pd.DataFrame([["2024年1月", 47000, 5.5]], columns=["月份", "总额", "同比"])

    def macro_china_gdp(self) -> pd.DataFrame:
        return pd.DataFrame(
            [["2024年第1季度", 296299, 5.3]],
            columns=["季度", "国内生产总值-绝对值", "国内生产总值-同比增长"],
        )

    def macro_china_gdzctz(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                ["2023年1月", 0, 0, 0, 100],
                ["2024年1月", 0, 0, 0, 110],
            ],
            columns=["月份", "a", "b", "c", "自年初累计"],
        )

    def macro_china_shrzgm(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "月份": ["202301", "202401"],
                "社会融资规模增量": [5000, 5500],
            }
        )

    def macro_china_hgjck(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                [
                    "2024年1月",
                    200_000_000,
                    7.1,
                    0,
                    180_000_000,
                    4.2,
                ]
            ],
            columns=[
                "月份",
                "当月出口额-金额",
                "当月出口额-同比增长",
                "unused",
                "当月进口额-金额",
                "当月进口额-同比增长",
            ],
        )

    def macro_china_trade_balance(self) -> pd.DataFrame:
        return pd.DataFrame(
            [[1, "2024-01-31", "82.2"]],
            columns=["序号", "日期", "今值"],
        )

    def macro_china_urban_unemployment(self) -> pd.DataFrame:
        return pd.DataFrame({"月份": ["2024年1月"], "城镇调查失业率": ["5.2%"]})

    def macro_china_new_house_price(self) -> pd.DataFrame:
        return pd.DataFrame(
            [["2024-01-31", "北京", 101.5]],
            columns=["日期", "城市", "指数"],
        )

    def energy_oil_hist(self) -> pd.DataFrame:
        return pd.DataFrame({"调价日期": ["2024-01-31"], "汽油最高零售价": [10880]})

    def macro_china_society_electricity(self) -> pd.DataFrame:
        return pd.DataFrame([["2024.01", 900000]], columns=["月份", "用电量"])

    def stock_zh_index_daily_em(self, **_kwargs: str) -> pd.DataFrame:
        return pd.DataFrame({"date": ["2024-01-05"], "close": [2100]})

    def macro_shipping_bdi(self) -> pd.DataFrame:
        return pd.DataFrame([["2024-01-05", 1500]], columns=["日期", "BDI"])

    def macro_shipping_bci(self) -> pd.DataFrame:
        return pd.DataFrame([["2024-01-05", 1700]], columns=["日期", "BCI"])


@pytest.fixture(autouse=True)
def stable_indicator_units(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in (
        base_fetchers,
        economic_fetchers,
        financial_fetchers,
        other_fetchers,
        trade_fetchers,
        weekly_indicators_fetchers,
    ):
        monkeypatch.setattr(module, "resolve_indicator_units", _units)


@pytest.fixture
def akshare_fixture() -> _AkshareFixture:
    return _AkshareFixture()


@pytest.mark.parametrize(
    ("method_name", "expected_code"),
    [
        ("fetch_pmi", "CN_PMI"),
        ("fetch_cpi", "CN_CPI"),
        ("fetch_ppi", "CN_PPI"),
        ("fetch_ppi_yoy", "CN_PPI_YOY"),
        ("fetch_m2", "CN_M2"),
        ("fetch_m2_yoy", "CN_M2_YOY"),
        ("fetch_non_man_pmi", "CN_NON_MAN_PMI"),
    ],
)
def test_base_fetcher_success_matrix(
    akshare_fixture: _AkshareFixture,
    method_name: str,
    expected_code: str,
) -> None:
    fetcher = base_fetchers.BaseIndicatorFetcher(
        akshare_fixture, "fixture", lambda _point: None, _identity
    )

    result = getattr(fetcher, method_name)(START, END)

    assert len(result) == 1
    assert result[0].code == expected_code


@pytest.mark.parametrize(
    "indicator_code",
    [
        "CN_CPI_NATIONAL_YOY",
        "CN_CPI_NATIONAL_MOM",
        "CN_CPI_URBAN_YOY",
        "CN_CPI_URBAN_MOM",
        "CN_CPI_RURAL_YOY",
        "CN_CPI_RURAL_MOM",
    ],
)
def test_cpi_detail_matrix(
    akshare_fixture: _AkshareFixture,
    indicator_code: str,
) -> None:
    fetcher = base_fetchers.BaseIndicatorFetcher(
        akshare_fixture, "fixture", lambda _point: None, _identity
    )
    result = fetcher.fetch_cpi_detailed(START, END, indicator_code)
    assert result[0].code == indicator_code


@pytest.mark.parametrize(
    ("method_name", "expected_code"),
    [
        ("fetch_fx_reserves", "CN_FX_RESERVES"),
        ("fetch_lpr", "CN_LPR"),
        ("fetch_shibor", "CN_SHIBOR"),
        ("fetch_rrr", "CN_RRR"),
        ("fetch_new_credit", "CN_NEW_CREDIT"),
        ("fetch_rmb_deposit", "CN_RMB_DEPOSIT"),
        ("fetch_rmb_loan", "CN_RMB_LOAN"),
        ("fetch_dr007", "CN_DR007"),
        ("fetch_pboc_open_market", "CN_PBOC_NET_INJECTION"),
    ],
)
def test_financial_fetcher_success_matrix(
    akshare_fixture: _AkshareFixture,
    method_name: str,
    expected_code: str,
) -> None:
    fetcher = financial_fetchers.FinancialIndicatorFetcher(
        akshare_fixture, "fixture", lambda _point: None, _identity
    )
    result = getattr(fetcher, method_name)(START, END)
    assert len(result) >= 1
    assert result[0].code == expected_code


@pytest.mark.parametrize(
    ("method_name", "expected_code"),
    [
        ("fetch_value_added", "CN_VALUE_ADDED"),
        ("fetch_retail_sales", "CN_RETAIL_SALES"),
        ("fetch_retail_sales_yoy", "CN_RETAIL_SALES_YOY"),
        ("fetch_gdp", "CN_GDP"),
        ("fetch_gdp_yoy", "CN_GDP_YOY"),
        ("fetch_fixed_investment", "CN_FIXED_INVESTMENT"),
        ("fetch_fixed_investment_yoy", "CN_FAI_YOY"),
        ("fetch_social_financing", "CN_SOCIAL_FINANCING"),
        ("fetch_social_financing_yoy", "CN_SOCIAL_FINANCING_YOY"),
    ],
)
def test_economic_fetcher_success_matrix(
    akshare_fixture: _AkshareFixture,
    method_name: str,
    expected_code: str,
) -> None:
    fetcher = economic_fetchers.EconomicIndicatorFetcher(
        akshare_fixture, "fixture", lambda _point: None, _identity
    )
    result = getattr(fetcher, method_name)(START, END)
    assert len(result) == 1
    assert result[0].code == expected_code


@pytest.mark.parametrize(
    ("method_name", "expected_code"),
    [
        ("fetch_exports", "CN_EXPORTS"),
        ("fetch_export_yoy", "CN_EXPORT_YOY"),
        ("fetch_imports", "CN_IMPORTS"),
        ("fetch_import_yoy", "CN_IMPORT_YOY"),
        ("fetch_trade_balance", "CN_TRADE_BALANCE"),
    ],
)
def test_trade_fetcher_success_matrix(
    akshare_fixture: _AkshareFixture,
    method_name: str,
    expected_code: str,
) -> None:
    fetcher = trade_fetchers.TradeIndicatorFetcher(
        akshare_fixture, "fixture", lambda _point: None, _identity
    )
    result = getattr(fetcher, method_name)(START, END)
    assert result[0].code == expected_code


@pytest.mark.parametrize(
    ("method_name", "expected_code"),
    [
        ("fetch_unemployment", "CN_UNEMPLOYMENT"),
        ("fetch_new_house_price", "CN_NEW_HOUSE_PRICE"),
        ("fetch_oil_price", "CN_OIL_PRICE"),
    ],
)
def test_other_fetcher_success_matrix(
    akshare_fixture: _AkshareFixture,
    method_name: str,
    expected_code: str,
) -> None:
    fetcher = other_fetchers.OtherIndicatorFetcher(
        akshare_fixture, "fixture", lambda _point: None, _identity
    )
    result = getattr(fetcher, method_name)(START, END)
    assert result[0].code == expected_code


@pytest.mark.parametrize(
    ("method_name", "expected_code"),
    [
        ("fetch_power_generation", "CN_POWER_GEN"),
        ("fetch_blast_furnace_utilization", "CN_BLAST_FURNACE"),
        ("fetch_ccfi", "CN_CCFI"),
        ("fetch_scfi", "CN_SCFI"),
    ],
)
def test_weekly_fetcher_success_matrix(
    akshare_fixture: _AkshareFixture,
    method_name: str,
    expected_code: str,
) -> None:
    fetcher = weekly_indicators_fetchers.WeeklyIndicatorFetcher(
        akshare_fixture, "fixture", lambda _point: None, _identity
    )
    result = getattr(fetcher, method_name)(START, END)
    assert result[0].code == expected_code


def test_pmi_subitem_file_loading_and_conversion(tmp_path: Path) -> None:
    fetcher = pmi_subitems_fetchers.PMISubitemsFetcher(
        object(), "fixture", lambda _point: None, _identity
    )
    data_path = tmp_path / "pmi.json"
    data_path.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "reporting_period": "2024-01-31",
                        "new_order": 51,
                        "inventory_finished": 49,
                        "inventory_raw_material": 48,
                        "purchase": 52,
                        "production": 53,
                        "employment": 47,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    fetcher._data_file_path = str(data_path)

    methods: list[Callable[[date, date], list[object]]] = [
        fetcher.fetch_pmi_new_order,
        fetcher.fetch_pmi_inventory,
        fetcher.fetch_pmi_raw_material,
        fetcher.fetch_pmi_purchase,
        fetcher.fetch_pmi_production,
        fetcher.fetch_pmi_employment,
    ]

    assert [method(START, END)[0].value for method in methods] == [
        51,
        49,
        48,
        52,
        53,
        47,
    ]


def test_pmi_subitem_invalid_file_and_records_are_skipped(tmp_path: Path) -> None:
    fetcher = pmi_subitems_fetchers.PMISubitemsFetcher(
        object(), "fixture", lambda _point: None, _identity
    )
    fetcher._data_file_path = str(tmp_path / "missing.json")
    assert fetcher._load_manual_data() == []

    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{", encoding="utf-8")
    fetcher._data_file_path = str(bad_path)
    assert fetcher._load_manual_data() == []

    records = [
        {"reporting_period": "bad", "new_order": 50},
        {"reporting_period": "2023-01-01", "new_order": 50},
        {"reporting_period": "2024-01-31"},
        {"reporting_period": "2024-01-31", "new_order": "bad"},
    ]
    assert (
        fetcher._convert_to_data_points(records, "new_order", "CN_PMI_NEW_ORDER", START, END) == []
    )
