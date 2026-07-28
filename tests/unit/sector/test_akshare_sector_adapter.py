from datetime import date

import numpy as np
import pandas as pd
import pytest

from apps.sector.infrastructure.adapters.akshare_sector_adapter import AKShareSectorAdapter


class _StubAK:
    def sw_index_first_info(self):
        return pd.DataFrame(
            {
                "行业代码": ["801010", "801020"],
                "行业名称": ["农林牧渔", "采掘"],
            }
        )

    def index_hist_sw(self, symbol: str, period: str = "day"):
        assert symbol == "801010"
        assert period == "day"
        return pd.DataFrame(
            {
                "代码": ["801010", "801010"],
                "日期": ["2025-03-03", "2025-03-04"],
                "收盘": [1000.0, 1010.0],
                "开盘": [995.0, 1001.0],
                "最高": [1002.0, 1015.0],
                "最低": [990.0, 999.0],
                "成交量": [1000000, 1100000],
                "成交额": [5000000, 5500000],
            }
        )


class _DamagedAK(_StubAK):
    def sw_index_first_info(self):
        return pd.DataFrame(
            {
                "行业代码": ["801010", None, "bad", "801010"],
                "行业名称": ["农林牧渔", "空代码", "坏代码", "农业新版"],
            }
        )

    def index_hist_sw(self, symbol: str, period: str = "day"):
        return pd.DataFrame(
            {
                "日期": ["2025-03-03", "2025-03-04", "2025-03-05"],
                "收盘": [1000.0, float("inf"), 1010.0],
                "开盘": [995.0, 1001.0, -1.0],
                "最高": [1002.0, 1015.0, 1012.0],
                "最低": [990.0, 999.0, 1000.0],
                "成交量": [1000000, 1100000, -5],
                "成交额": [5000000, 5500000, float("inf")],
            }
        )


def test_fetch_sw_industry_classify_maps_live_akshare_payload(mocker) -> None:
    mocker.patch(
        "apps.sector.infrastructure.adapters.akshare_sector_adapter.get_akshare_module",
        return_value=_StubAK(),
    )
    adapter = AKShareSectorAdapter()

    result = adapter.fetch_sw_industry_classify("SW1")

    assert list(result["sector_code"]) == ["801010", "801020"]
    assert list(result["sector_name"]) == ["农林牧渔", "采掘"]
    assert list(result["level"]) == ["SW1", "SW1"]


def test_fetch_sector_index_daily_maps_live_akshare_payload(mocker) -> None:
    mocker.patch(
        "apps.sector.infrastructure.adapters.akshare_sector_adapter.get_akshare_module",
        return_value=_StubAK(),
    )
    adapter = AKShareSectorAdapter()

    result = adapter.fetch_sector_index_daily("801010", "20250301", "20250331")

    assert list(result["trade_date"]) == [date(2025, 3, 3), date(2025, 3, 4)]
    assert list(result["open_price"]) == [995.0, 1001.0]
    assert result.iloc[0]["change_pct"] == 0.0
    assert round(result.iloc[1]["change_pct"], 6) == 1.0


def test_invalid_level_code_and_date_fail_before_sdk_access(mocker) -> None:
    get_ak = mocker.patch(
        "apps.sector.infrastructure.adapters.akshare_sector_adapter.get_akshare_module"
    )
    adapter = AKShareSectorAdapter()

    with pytest.raises(ValueError, match="sector_level_invalid"):
        adapter.fetch_sw_industry_classify("UNKNOWN")
    with pytest.raises(ValueError, match="sector_code_invalid"):
        adapter.fetch_sector_index_daily("../secret", "20250301", "20250331")
    with pytest.raises(ValueError, match="sector_date_invalid"):
        adapter.fetch_sector_index_daily("801010", "bad", "20250331")
    with pytest.raises(ValueError, match="sector_date_range_invalid"):
        adapter.fetch_sector_index_daily("801010", "20250331", "20250301")

    get_ak.assert_not_called()


def test_remote_classification_filters_invalid_and_duplicate_codes(mocker) -> None:
    mocker.patch(
        "apps.sector.infrastructure.adapters.akshare_sector_adapter.get_akshare_module",
        return_value=_DamagedAK(),
    )

    result = AKShareSectorAdapter().fetch_sw_industry_classify("SW1")

    assert result.to_dict("records") == [
        {
            "sector_code": "801010",
            "sector_name": "农业新版",
            "level": "SW1",
            "parent_code": None,
        }
    ]


def test_remote_index_filters_nonfinite_close_and_degrades_negative_fields(mocker) -> None:
    mocker.patch(
        "apps.sector.infrastructure.adapters.akshare_sector_adapter.get_akshare_module",
        return_value=_DamagedAK(),
    )

    result = AKShareSectorAdapter().fetch_sector_index_daily(
        "801010",
        "20250301",
        "20250331",
    )

    assert list(result["trade_date"]) == [date(2025, 3, 3), date(2025, 3, 5)]
    assert np.isnan(result.iloc[1]["open_price"])
    assert np.isnan(result.iloc[1]["volume"])
    assert np.isnan(result.iloc[1]["amount"])


def test_remote_failure_logs_only_exception_type_and_uses_local_fallback(
    mocker,
    caplog,
) -> None:
    get_ak = mocker.patch(
        "apps.sector.infrastructure.adapters.akshare_sector_adapter.get_akshare_module"
    )
    get_ak.return_value.sw_index_first_info.side_effect = RuntimeError(
        "postgresql://admin:raw-secret@example.test/prod"
    )
    mocker.patch(
        "apps.sector.infrastructure.adapters.akshare_sector_adapter._load_local_sector_classify",
        return_value=pd.DataFrame(),
    )

    result = AKShareSectorAdapter().fetch_sw_industry_classify("SW1")

    assert result.empty
    assert "raw-secret" not in caplog.text
    assert "postgresql://" not in caplog.text


def test_batch_index_fetch_isolates_invalid_sector_codes(mocker) -> None:
    adapter = AKShareSectorAdapter()
    fetch = mocker.patch.object(
        adapter,
        "fetch_sector_index_daily",
        return_value=pd.DataFrame({"trade_date": [date(2025, 3, 3)], "close": [1000.0]}),
    )

    result = adapter.fetch_all_sector_index_daily(
        ["bad", "801010"],
        "20250301",
        "20250331",
    )

    fetch.assert_called_once_with("801010", "20250301", "20250331")
    assert result.iloc[0]["sector_code"] == "801010"
