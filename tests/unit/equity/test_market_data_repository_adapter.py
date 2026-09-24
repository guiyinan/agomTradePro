from datetime import date
from types import SimpleNamespace

from apps.equity.infrastructure.adapters import MarketDataRepositoryAdapter


def test_market_data_repository_adapter_falls_back_to_akshare_index_history(mocker) -> None:
    mocker.patch(
        "apps.equity.infrastructure.adapters.get_runtime_benchmark_code",
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


def test_market_data_repository_adapter_delegates_remote_history_to_data_center(mocker) -> None:
    mocker.patch(
        "apps.equity.infrastructure.adapters.get_runtime_benchmark_code",
        return_value="000300.SH",
    )
    adapter = MarketDataRepositoryAdapter()

    model_market_port = SimpleNamespace(
        index_history=mocker.Mock(
            return_value=[
                SimpleNamespace(trade_date=date(2025, 3, 3), close=1000.0),
                SimpleNamespace(trade_date=date(2025, 3, 4), close=1010.0),
                SimpleNamespace(trade_date=date(2025, 3, 5), close=1005.0),
            ]
        )
    )
    mocker.patch(
        "apps.equity.infrastructure.adapters.get_model_market_data_port",
        return_value=model_market_port,
    )

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
    model_market_port.index_history.assert_called_once_with(
        "000300.SH",
        date(2025, 3, 1),
        date(2025, 3, 31),
    )
