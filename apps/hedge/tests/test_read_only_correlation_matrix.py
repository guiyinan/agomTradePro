from datetime import date
from unittest.mock import patch

from apps.hedge.infrastructure.adapters import FailoverHedgeAdapter


def test_failover_adapter_can_skip_success_cache_writes():
    source = type(
        "Source",
        (),
        {"get_asset_prices": lambda self, asset_code, end_date, days, **kwargs: [1.0, 2.0]},
    )()
    adapter = FailoverHedgeAdapter()
    adapter.sources = [source]

    with patch("apps.hedge.infrastructure.adapters._cache_hedge_prices") as cache_prices:
        result = adapter.get_asset_prices(
            "510300",
            date(2026, 7, 11),
            2,
            cache_result=False,
        )

    assert result == [1.0, 2.0]
    cache_prices.assert_not_called()
