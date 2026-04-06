from datetime import date
from types import SimpleNamespace

from apps.equity.infrastructure.adapters import MarketDataRepositoryAdapter


def test_market_data_repository_adapter_falls_back_to_akshare_index_history(mocker) -> None:
    mocker.patch(
        "apps.account.infrastructure.models.SystemSettingsModel.get_runtime_benchmark_code",
        return_value="000300.SH",
    )
    adapter = MarketDataRepositoryAdapter()
    mocker.patch.object(
        adapter,
        "_load_local_index_points",
        return_value=[],
    )
    mocker.patch.object(
        adapter,
        "_load_remote_index_points",
        return_value=[
            (date(2025, 3, 3), 1000.0),
            (date(2025, 3, 4), 1010.0),
            (date(2025, 3, 5), 1005.0),
        ],
    )

    returns = adapter.get_index_daily_returns(
        index_code="000300.SH",
        start_date=date(2025, 3, 1),
        end_date=date(2025, 3, 31),
    )

    assert round(returns[date(2025, 3, 4)], 6) == 0.01
    assert round(returns[date(2025, 3, 5)], 6) == -0.00495


def test_market_data_repository_adapter_persists_secondary_remote_source(mocker) -> None:
    mocker.patch(
        "apps.account.infrastructure.models.SystemSettingsModel.get_runtime_benchmark_code",
        return_value="000300.SH",
    )
    adapter = MarketDataRepositoryAdapter()

    mock_ak = SimpleNamespace(
        stock_zh_index_daily_em=mocker.Mock(side_effect=RuntimeError("primary down")),
        stock_zh_index_daily=mocker.Mock(side_effect=RuntimeError("secondary down")),
        stock_zh_index_daily_tx=mocker.Mock(side_effect=RuntimeError("tertiary down")),
        index_zh_a_hist=mocker.Mock(
            return_value=__import__("pandas").DataFrame(
                {
                    "日期": ["2025-03-03", "2025-03-04", "2025-03-05"],
                    "收盘": [1000.0, 1010.0, 1005.0],
                }
            )
        ),
    )
    mocker.patch(
        "apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module",
        return_value=mock_ak,
    )
    persist_spy = mocker.patch.object(adapter, "_persist_index_points")

    points = adapter._load_remote_index_points(
        index_code="000300.SH",
        start_date=date(2025, 3, 1),
        end_date=date(2025, 3, 31),
    )

    assert points == [
        (date(2025, 3, 3), 1000.0),
        (date(2025, 3, 4), 1010.0),
        (date(2025, 3, 5), 1005.0),
    ]
    persist_spy.assert_called_once()
