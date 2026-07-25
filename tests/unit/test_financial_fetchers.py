from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from apps.data_center.infrastructure.macro_sources.base import DataValidationError
from apps.data_center.infrastructure.macro_sources.fetchers.financial_fetchers import (
    FinancialIndicatorFetcher,
)


@pytest.fixture(autouse=True)
def _stub_runtime_macro_metadata(monkeypatch):
    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.fetchers.common.get_runtime_macro_index_metadata_map",
        lambda: {
            "CN_DR007": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_FX_RESERVES": {
                "default_unit": "亿美元",
                "governance_scope": "macro_console",
            },
            "CN_LPR": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_NEW_CREDIT": {
                "default_unit": "亿元",
                "governance_scope": "macro_console",
            },
            "CN_RMB_DEPOSIT": {
                "default_unit": "亿元",
                "governance_scope": "macro_console",
            },
            "CN_RMB_LOAN": {
                "default_unit": "亿元",
                "governance_scope": "macro_console",
            },
            "CN_SHIBOR": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_RRR": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_PBOC_NET_INJECTION": {
                "default_unit": "亿元",
                "governance_scope": "macro_console",
            },
        },
    )


def dummy_validate(code, val, date_val, freq, unit):
    # Depending on the version, sometimes we just don't even need to mock validate like this if dummy_validate ignores arguments
    pass


def dummy_dedup(points):
    return points


def test_fetch_dr007_success():
    ak_mock = MagicMock()
    # attach repo_rate_hist to our mock, so hasattr passes
    ak_mock.repo_rate_hist = MagicMock()

    fetcher = FinancialIndicatorFetcher(ak_mock, "akshare", lambda x: None, dummy_dedup)

    with patch.object(ak_mock, "repo_rate_hist", create=True) as mock_repo_rate:
        mock_repo_rate.side_effect = [
            pd.DataFrame(
                [
                    {"date": "2024-01-01", "FDR007": 1.85},
                    {"date": "2024-12-31", "FDR007": 1.95},
                ]
            ),
            pd.DataFrame(
                [
                    {"date": "2025-01-01", "FDR007": 1.90},
                ]
            ),
        ]

        indicators = fetcher.fetch_dr007(date(2024, 1, 1), date(2025, 1, 31))
        assert len(indicators) == 3
        assert indicators[0].code == "CN_DR007"
        assert indicators[0].value == 1.85
        assert mock_repo_rate.call_count == 2
        assert mock_repo_rate.call_args_list[0].kwargs == {
            "start_date": "20240101",
            "end_date": "20241230",
        }
        assert mock_repo_rate.call_args_list[1].kwargs == {
            "start_date": "20241231",
            "end_date": "20250131",
        }


def test_fetch_dr007_skips_failed_window_and_keeps_valid_rows():
    ak_mock = MagicMock()
    ak_mock.repo_rate_hist = MagicMock()

    fetcher = FinancialIndicatorFetcher(ak_mock, "akshare", lambda x: None, dummy_dedup)

    with patch.object(ak_mock, "repo_rate_hist", create=True) as mock_repo_rate:
        mock_repo_rate.side_effect = [
            pd.DataFrame(
                [
                    {"date": "2026-04-30", "FDR007": 1.39},
                ]
            ),
            KeyError("frValueMap"),
        ]

        indicators = fetcher.fetch_dr007(date(2025, 5, 2), date(2026, 5, 4))

    assert len(indicators) == 1
    assert indicators[0].code == "CN_DR007"
    assert indicators[0].value == 1.39


def test_fetch_lpr_keeps_percent_point_values():
    ak_mock = MagicMock()
    fetcher = FinancialIndicatorFetcher(ak_mock, "akshare", lambda x: None, dummy_dedup)

    with patch.object(ak_mock, "macro_china_lpr", create=True) as mock_lpr:
        mock_lpr.return_value = pd.DataFrame(
            [
                {"TRADE_DATE": "2024-01-20", "LPR1Y": 3.10},
            ]
        )

        indicators = fetcher.fetch_lpr(date(2024, 1, 1), date(2024, 1, 31))

    assert len(indicators) == 1
    assert indicators[0].code == "CN_LPR"
    assert indicators[0].value == 3.10
    assert indicators[0].unit == "%"


def test_fetch_shibor_keeps_percent_point_values():
    ak_mock = MagicMock()
    fetcher = FinancialIndicatorFetcher(ak_mock, "akshare", lambda x: None, dummy_dedup)

    with patch.object(ak_mock, "macro_china_shibor_all", create=True) as mock_shibor:
        mock_shibor.return_value = pd.DataFrame(
            [
                {"日期": "2024-01-20", "O/N-定价": 1.87},
            ]
        )

        indicators = fetcher.fetch_shibor(date(2024, 1, 1), date(2024, 1, 31))

    assert len(indicators) == 1
    assert indicators[0].code == "CN_SHIBOR"
    assert indicators[0].value == 1.87
    assert indicators[0].unit == "%"


def test_fetch_rrr_keeps_percent_point_values():
    ak_mock = MagicMock()
    fetcher = FinancialIndicatorFetcher(ak_mock, "akshare", lambda x: None, dummy_dedup)

    with patch.object(
        ak_mock,
        "macro_china_reserve_requirement_ratio",
        create=True,
    ) as mock_rrr:
        mock_rrr.return_value = pd.DataFrame(
            [
                {
                    "公布时间": "2024年01月25日",
                    "生效时间": "2024年02月05日",
                    "大型金融机构-调整前": 10.0,
                    "大型金融机构-调整后": 9.50,
                },
            ]
        )

        indicators = fetcher.fetch_rrr(date(2024, 2, 1), date(2024, 2, 29))

    assert len(indicators) == 1
    assert indicators[0].code == "CN_RRR"
    assert indicators[0].value == 9.50
    assert indicators[0].observed_at == date(2024, 2, 5)
    assert indicators[0].unit == "%"


def test_fetch_rmb_deposit_uses_total_new_deposits_not_household_subset():
    ak_mock = MagicMock()
    fetcher = FinancialIndicatorFetcher(
        ak_mock,
        "akshare",
        lambda point: None,
        dummy_dedup,
    )

    with patch.object(ak_mock, "macro_rmb_deposit", create=True) as mock_deposit:
        mock_deposit.return_value = pd.DataFrame(
            [
                {
                    "月份": "2024年01月份",
                    "新增存款-数量": "12,000",
                    "新增储蓄存款-数量": "3,500",
                }
            ]
        )

        indicators = fetcher.fetch_rmb_deposit(
            date(2024, 1, 1),
            date(2024, 1, 31),
        )

    assert len(indicators) == 1
    assert indicators[0].code == "CN_RMB_DEPOSIT"
    assert indicators[0].value == 12_000.0
    assert indicators[0].unit == "亿元"


@pytest.mark.parametrize(
    "invalid_value",
    ["--", "not-a-number", "12%", float("inf")],
)
def test_fetch_new_credit_skips_invalid_values_instead_of_writing_zero(invalid_value):
    ak_mock = MagicMock()
    fetcher = FinancialIndicatorFetcher(
        ak_mock,
        "akshare",
        lambda point: None,
        dummy_dedup,
    )

    with patch.object(
        ak_mock,
        "macro_china_new_financial_credit",
        create=True,
    ) as mock_credit:
        mock_credit.return_value = pd.DataFrame([{"月份": "2024年01月份", "当月": invalid_value}])

        indicators = fetcher.fetch_new_credit(
            date(2024, 1, 1),
            date(2024, 1, 31),
        )

    assert indicators == []


def test_fetch_lpr_skips_invalid_dates_and_keeps_valid_rows():
    ak_mock = MagicMock()
    fetcher = FinancialIndicatorFetcher(
        ak_mock,
        "akshare",
        lambda point: None,
        dummy_dedup,
    )

    with patch.object(ak_mock, "macro_china_lpr", create=True) as mock_lpr:
        mock_lpr.return_value = pd.DataFrame(
            [
                {"TRADE_DATE": "invalid", "LPR1Y": 99.0},
                {"TRADE_DATE": "2024-01-20", "LPR1Y": 3.10},
            ]
        )

        indicators = fetcher.fetch_lpr(
            date(2024, 1, 1),
            date(2024, 1, 31),
        )

    assert [(point.observed_at, point.value) for point in indicators] == [(date(2024, 1, 20), 3.10)]


def test_fetch_lpr_rejects_schema_drift_instead_of_guessing_position():
    ak_mock = MagicMock()
    fetcher = FinancialIndicatorFetcher(
        ak_mock,
        "akshare",
        lambda point: None,
        dummy_dedup,
    )

    with patch.object(ak_mock, "macro_china_lpr", create=True) as mock_lpr:
        mock_lpr.return_value = pd.DataFrame([{"unknown_date": "2024-01-20", "unknown_rate": 3.10}])

        with pytest.raises(DataValidationError, match="CN_LPR 数据缺少必需列"):
            fetcher.fetch_lpr(date(2024, 1, 1), date(2024, 1, 31))


def test_fetch_pboc_open_market_success():
    ak_mock = MagicMock()
    # attach macro_china_pboc_open_market so hasattr passes
    ak_mock.macro_china_pboc_open_market = MagicMock()
    fetcher = FinancialIndicatorFetcher(ak_mock, "akshare", lambda x: None, dummy_dedup)

    with patch.object(ak_mock, "macro_china_pboc_open_market", create=True) as mock_pboc:
        mock_pboc.return_value = pd.DataFrame([{"日期": "2024-01-01", "净投放": "1500亿"}])

        indicators = fetcher.fetch_pboc_open_market(date(2024, 1, 1), date(2024, 1, 31))
        assert len(indicators) == 1
        assert indicators[0].code == "CN_PBOC_NET_INJECTION"
        assert indicators[0].value == 1500.0
