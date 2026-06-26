from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.macro.infrastructure.adapters.base import DataSourceUnavailableError
from apps.macro.infrastructure.adapters.tushare_adapter import TushareAdapter


def test_fetch_shibor_accepts_lowercase_tenor_column():
    adapter = TushareAdapter(token="test-token")
    adapter._pro = SimpleNamespace(
        shibor=lambda start_date, end_date: pd.DataFrame(
            {
                "date": ["20260403", "20260402"],
                "1w": [1.338, 1.404],
            }
        )
    )

    points = adapter.fetch("SHIBOR", date(2026, 4, 1), date(2026, 4, 5))

    assert len(points) == 2
    assert points[0].observed_at == date(2026, 4, 2)
    assert points[0].value == 1.404
    assert points[-1].observed_at == date(2026, 4, 3)
    assert points[-1].value == 1.338
    assert all(point.source == "tushare" for point in points)


def test_fetch_shibor_raises_when_one_week_column_missing():
    adapter = TushareAdapter(token="test-token")
    adapter._pro = SimpleNamespace(
        shibor=lambda start_date, end_date: pd.DataFrame(
            {
                "date": ["20260403"],
                "on": [1.238],
            }
        )
    )

    with pytest.raises(DataSourceUnavailableError, match="缺少 1 周期限字段"):
        adapter.fetch("SHIBOR", date(2026, 4, 1), date(2026, 4, 5))


def test_fetch_cpi_national_yoy_uses_cn_cpi_monthly_data():
    adapter = TushareAdapter(token="test-token")
    adapter._pro = SimpleNamespace(
        cn_cpi=lambda start_m, end_m: pd.DataFrame(
            {
                "month": ["202605", "202604"],
                "nt_yoy": [0.1, -0.1],
                "nt_mom": [-0.2, 0.1],
            }
        )
    )

    points = adapter.fetch("CN_CPI_NATIONAL_YOY", date(2026, 4, 1), date(2026, 5, 31))

    assert len(points) == 2
    assert points[0].observed_at == date(2026, 4, 30)
    assert points[0].value == -0.1
    assert points[0].unit == "%"
    assert points[0].original_unit == "%"
    assert points[-1].observed_at == date(2026, 5, 31)
    assert points[-1].value == 0.1


def test_supported_indicators_include_runtime_macro_index_codes(monkeypatch):
    monkeypatch.setattr(
        "apps.macro.infrastructure.adapters.tushare_adapter.get_runtime_macro_index_codes",
        lambda: ["000300.SH", "000905.SH"],
    )

    adapter = TushareAdapter(token="test-token")

    assert adapter.supports("000300.SH") is True
    assert adapter.supports("000905.SH") is True
