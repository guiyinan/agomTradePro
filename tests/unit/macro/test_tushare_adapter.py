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
