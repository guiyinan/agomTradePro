from datetime import date

import pandas as pd

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
