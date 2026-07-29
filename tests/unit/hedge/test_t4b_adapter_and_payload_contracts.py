"""Failover, cache, and interface payload contracts for Hedge."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.hedge.application import interface_services
from apps.hedge.domain.entities import HedgeEffectiveness
from apps.hedge.infrastructure import adapters


def test_base_adapter_contract_is_abstract_by_behavior() -> None:
    with pytest.raises(NotImplementedError):
        adapters.HedgeDataSource().get_asset_prices(
            "510300",
            date(2026, 7, 25),
        )


@pytest.mark.parametrize(
    ("asset_code", "expected"),
    [
        ("510300", "510300.SH"),
        ("600000", "600000.SH"),
        ("000001", "000001.SZ"),
        ("300001", "300001.SZ"),
        ("900001", "900001"),
        ("510300.SH", "510300.SH"),
    ],
)
def test_tushare_adapter_normalizes_codes(asset_code: str, expected: str) -> None:
    adapter = adapters.TushareHedgeAdapter.__new__(adapters.TushareHedgeAdapter)
    assert adapter._convert_to_ts_code(asset_code) == expected


def test_persisted_price_adapters_return_ordered_tail_empty_and_failure() -> None:
    bars = [
        SimpleNamespace(close=1),
        SimpleNamespace(close=2),
        SimpleNamespace(close=3),
    ]
    repository = Mock()
    repository.get_bars.return_value = bars
    tushare = adapters.TushareHedgeAdapter.__new__(adapters.TushareHedgeAdapter)
    tushare._repo = repository

    assert tushare.get_asset_prices("510300", date(2026, 7, 25), days=2) == [
        2.0,
        1.0,
    ]
    assert repository.get_bars.call_args.kwargs["limit"] == 8

    repository.get_bars.return_value = []
    assert tushare.get_asset_prices("510300", date(2026, 7, 25)) is None
    repository.get_bars.side_effect = RuntimeError("store unavailable")
    assert tushare.get_asset_prices("510300", date(2026, 7, 25)) is None

    repository.get_bars.side_effect = None
    repository.get_bars.return_value = bars
    akshare = adapters.AkshareHedgeAdapter.__new__(adapters.AkshareHedgeAdapter)
    akshare._repo = repository
    assert akshare._convert_to_symbol("510300") == "510300"
    assert akshare.get_asset_prices("510300", date(2026, 7, 25), days=5) == [
        3.0,
        2.0,
        1.0,
    ]
    repository.get_bars.return_value = []
    assert akshare.get_asset_prices("510300", date(2026, 7, 25)) is None
    repository.get_bars.side_effect = ValueError("malformed")
    assert akshare.get_asset_prices("510300", date(2026, 7, 25)) is None


def test_cache_helpers_contain_cache_backend_failures() -> None:
    cache = Mock()
    with patch("django.core.cache.cache", cache):
        adapters._cache_hedge_prices("510300", [1.0, 2.0])
        cache.set.assert_called_once_with(
            "hedge:prices:510300",
            [1.0, 2.0],
            timeout=86400,
        )
        cache.get.return_value = [2.0]
        assert adapters._get_cached_hedge_prices("510300") == [2.0]

    cache.set.side_effect = RuntimeError("cache down")
    cache.get.side_effect = RuntimeError("cache down")
    with patch("django.core.cache.cache", cache):
        adapters._cache_hedge_prices("510300", [1.0])
        assert adapters._get_cached_hedge_prices("510300") is None


def test_cached_adapter_uses_history_then_realtime_then_none() -> None:
    adapter = adapters.CachedHedgeAdapter()

    with (
        patch(
            "apps.hedge.infrastructure.adapters._get_cached_hedge_prices",
            return_value=[1.0, 2.0, 3.0],
        ),
        patch.object(adapter, "_get_realtime_price") as realtime,
    ):
        assert adapter.get_asset_prices(
            "510300",
            date(2026, 7, 25),
            days=2,
        ) == [2.0, 3.0]
        realtime.assert_not_called()

    with (
        patch(
            "apps.hedge.infrastructure.adapters._get_cached_hedge_prices",
            return_value=[],
        ),
        patch.object(adapter, "_get_realtime_price", return_value=4.5),
    ):
        assert adapter.get_asset_prices(
            "510300",
            date(2026, 7, 25),
            days=3,
        ) == [4.5, 4.5, 4.5]

    with (
        patch(
            "apps.hedge.infrastructure.adapters._get_cached_hedge_prices",
            return_value=None,
        ),
        patch.object(adapter, "_get_realtime_price", return_value=None),
    ):
        assert (
            adapter.get_asset_prices(
                "510300",
                date(2026, 7, 25),
            )
            is None
        )


def test_realtime_price_lookup_validates_positive_price_and_contains_errors() -> None:
    repository = Mock()
    with patch(
        "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository",
        return_value=repository,
    ):
        repository.get_latest_price.return_value = SimpleNamespace(price=3.2)
        assert adapters.CachedHedgeAdapter._get_realtime_price("510300") == 3.2
        repository.get_latest_price.return_value = SimpleNamespace(price=0)
        assert adapters.CachedHedgeAdapter._get_realtime_price("510300") is None
        repository.get_latest_price.return_value = None
        assert adapters.CachedHedgeAdapter._get_realtime_price("510300") is None
        repository.get_latest_price.side_effect = RuntimeError("redis down")
        assert adapters.CachedHedgeAdapter._get_realtime_price("510300") is None


def test_failover_skips_errors_caches_primary_results_and_handles_exhaustion() -> None:
    first = Mock(spec=adapters.HedgeDataSource)
    second = Mock(spec=adapters.HedgeDataSource)
    cached = adapters.CachedHedgeAdapter()
    first.get_asset_prices.return_value = None
    second.get_asset_prices.return_value = [3.0, 4.0]
    failover = adapters.FailoverHedgeAdapter.__new__(adapters.FailoverHedgeAdapter)
    failover.sources = [first, second, cached]

    with patch("apps.hedge.infrastructure.adapters._cache_hedge_prices") as cache:
        assert failover.get_asset_prices(
            "510300",
            date(2026, 7, 25),
        ) == [3.0, 4.0]
        cache.assert_called_once_with("510300", [3.0, 4.0])

    first.get_asset_prices.side_effect = RuntimeError("primary failed")
    second.get_asset_prices.side_effect = RuntimeError("secondary failed")
    with patch.object(cached, "get_asset_prices", return_value=None):
        assert (
            failover.get_asset_prices(
                "510300",
                date(2026, 7, 25),
                cache_result=False,
            )
            is None
        )


def test_adapter_provider_is_singleton() -> None:
    with (
        patch(
            "apps.hedge.infrastructure.adapters._hedge_adapter_instance",
            None,
        ),
        patch(
            "apps.hedge.infrastructure.adapters.FailoverHedgeAdapter",
            return_value=Mock(),
        ) as constructor,
    ):
        first = adapters.get_hedge_adapter()
        second = adapters.get_hedge_adapter()

    assert first is second
    constructor.assert_called_once_with()


def _effectiveness() -> HedgeEffectiveness:
    return HedgeEffectiveness(
        pair_name="CSI300",
        correlation=-0.7,
        beta=-0.5,
        hedge_ratio=0.8,
        hedge_method="beta",
        effectiveness=0.75,
        rating="good",
        trend="stable",
        recommendation="hold",
    )


def test_interface_effectiveness_matrix_and_metric_empty_states() -> None:
    service = Mock()
    service.check_hedge_effectiveness.side_effect = [None, _effectiveness()]
    service.get_correlation_matrix.return_value = [[1.0, -0.7], [-0.7, 1.0]]
    service.get_all_effectiveness.return_value = [_effectiveness()]
    metric = SimpleNamespace(
        asset1="510300",
        asset2="510500",
        calc_date=date(2026, 7, 25),
        window_days=20,
        correlation=-0.71234,
        covariance=0.0,
        beta=-0.45678,
        correlation_trend="stable",
        correlation_ma=None,
        alert=True,
        alert_type="breakdown",
    )
    service.calculate_correlation.side_effect = [None, metric]

    with patch.object(
        interface_services,
        "_get_integration_service",
        return_value=service,
    ):
        assert interface_services.get_hedge_effectiveness_payload(pair_name="missing") is None
        effectiveness = interface_services.get_hedge_effectiveness_payload(pair_name="CSI300")
        matrix = interface_services.get_correlation_matrix_payload(
            asset_codes=["510300", "510500"],
            window_days=20,
        )
        all_effectiveness = interface_services.get_all_effectiveness_payload()
        assert (
            interface_services.get_correlation_metric_payload(
                asset1="a",
                asset2="b",
                window_days=20,
            )
            is None
        )
        serialized_metric = interface_services.get_correlation_metric_payload(
            asset1="510300",
            asset2="510500",
            window_days=20,
        )

    assert effectiveness["rating"] == "good"
    assert matrix["matrix"][0][1] == -0.7
    assert all_effectiveness["count"] == 1
    assert serialized_metric["correlation"] == -0.7123
    assert serialized_metric["covariance"] is None
    assert serialized_metric["beta"] == -0.4568


def test_interface_operational_payloads_serialize_dates_counts_and_defaults() -> None:
    service = Mock()
    service.get_all_pairs.return_value = [
        SimpleNamespace(name="empty"),
        SimpleNamespace(name="active"),
    ]
    service.get_hedge_portfolio.side_effect = [
        None,
        SimpleNamespace(
            pair_name="active",
            trade_date=date(2026, 7, 25),
            long_weight=0.6,
            hedge_weight=0.4,
            hedge_ratio=0.75,
            current_correlation=-0.6,
            hedge_effectiveness=0.8,
            rebalance_needed=True,
            rebalance_reason="drift",
        ),
    ]
    service.update_all_portfolios.return_value = [
        SimpleNamespace(
            pair_name="active",
            trade_date=date(2026, 7, 25),
            hedge_ratio=0.7555,
            rebalance_needed=False,
        )
    ]
    alert = SimpleNamespace(
        pair_name="active",
        alert_date=date(2026, 7, 25),
        alert_type=SimpleNamespace(value="correlation"),
        severity="warning",
        message="changed",
        action_required=True,
        action_priority=2,
    )
    service.get_recent_alerts.return_value = [alert]
    service.monitor_hedge_pairs.return_value = [alert]
    service.calculate_hedge_ratio.side_effect = [
        None,
        (0.81234, {}),
    ]

    with patch.object(
        interface_services,
        "_get_integration_service",
        return_value=service,
    ):
        snapshots = interface_services.get_latest_snapshots_payload()
        updated = interface_services.update_all_portfolios_payload()
        recent = interface_services.get_recent_alerts_payload(days=7)
        monitored = interface_services.monitor_hedge_pairs_payload()
        assert interface_services.get_hedge_ratio_payload(pair_name="none") is None
        ratio = interface_services.get_hedge_ratio_payload(pair_name="active")

    assert snapshots["count"] == 1
    assert snapshots["results"][0]["long_weight"] == 60.0
    assert updated["portfolios"][0]["hedge_ratio"] == 0.755
    assert recent["results"][0]["alert_type"] == "correlation"
    assert monitored["generated_alerts"] == 1
    assert ratio == {
        "pair_name": "active",
        "hedge_ratio": 0.8123,
        "method": "unknown",
        "details": {},
    }


def test_interface_deactivate_pair_composes_repository_and_use_case() -> None:
    repository = Mock()
    use_case = Mock()
    expected = SimpleNamespace(success=True, pair_id=7)
    use_case.execute.return_value = expected

    with (
        patch.object(
            interface_services,
            "get_hedge_pair_repository",
            return_value=repository,
        ),
        patch.object(
            interface_services,
            "DeactivateHedgePairUseCase",
            return_value=use_case,
        ) as constructor,
    ):
        result = interface_services.deactivate_hedge_pair(pair_id=7)

    assert result is expected
    constructor.assert_called_once_with(repository)
    assert use_case.execute.call_args.args[0].pair_id == 7
