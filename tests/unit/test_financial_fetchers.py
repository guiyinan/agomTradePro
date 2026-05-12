from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from apps.macro.infrastructure.adapters.fetchers.financial_fetchers import FinancialIndicatorFetcher


@pytest.fixture(autouse=True)
def _stub_runtime_macro_metadata(monkeypatch):
    monkeypatch.setattr(
        "apps.macro.infrastructure.adapters.fetchers.common.get_runtime_macro_index_metadata_map",
        lambda: {
            "CN_DR007": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_LPR": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_SHIBOR": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_RRR": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_PBOC_NET_INJECTION": {"default_unit": "亿元", "governance_scope": "macro_console"},
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
            pd.DataFrame([
                {"date": "2024-01-01", "FDR007": 1.85},
                {"date": "2024-12-31", "FDR007": 1.95},
            ]),
            pd.DataFrame([
                {"date": "2025-01-01", "FDR007": 1.90},
            ]),
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
            pd.DataFrame([
                {"date": "2026-04-30", "FDR007": 1.39},
            ]),
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
        mock_lpr.return_value = pd.DataFrame([
            {"日期": "2024-01-20", "1年期": 3.10},
        ])

        indicators = fetcher.fetch_lpr(date(2024, 1, 1), date(2024, 1, 31))

    assert len(indicators) == 1
    assert indicators[0].code == "CN_LPR"
    assert indicators[0].value == 3.10
    assert indicators[0].unit == "%"


def test_fetch_shibor_keeps_percent_point_values():
    ak_mock = MagicMock()
    fetcher = FinancialIndicatorFetcher(ak_mock, "akshare", lambda x: None, dummy_dedup)

    with patch.object(ak_mock, "macro_china_shibor_all", create=True) as mock_shibor:
        mock_shibor.return_value = pd.DataFrame([
            {"日期": "2024-01-20", "隔夜": 1.87},
        ])

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
        mock_rrr.return_value = pd.DataFrame([
            ["2024年01月25日", "大型金融机构", 9.50],
        ])

        indicators = fetcher.fetch_rrr(date(2024, 1, 1), date(2024, 1, 31))

    assert len(indicators) == 1
    assert indicators[0].code == "CN_RRR"
    assert indicators[0].value == 9.50
    assert indicators[0].unit == "%"

def test_fetch_pboc_open_market_success():
    ak_mock = MagicMock()
    # attach macro_china_pboc_open_market so hasattr passes
    ak_mock.macro_china_pboc_open_market = MagicMock()
    fetcher = FinancialIndicatorFetcher(ak_mock, "akshare", lambda x: None, dummy_dedup)

    with patch.object(ak_mock, "macro_china_pboc_open_market", create=True) as mock_pboc:
        mock_pboc.return_value = pd.DataFrame([
            {"日期": "2024-01-01", "净投放": "1500亿"}
        ])

        indicators = fetcher.fetch_pboc_open_market(date(2024, 1, 1), date(2024, 1, 31))
        assert len(indicators) == 1
        assert indicators[0].code == "CN_PBOC_NET_INJECTION"
        assert indicators[0].value == 1500.0
