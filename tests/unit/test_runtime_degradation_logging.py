import logging
from datetime import date
from unittest.mock import Mock

import pytest

from apps.alpha.application.services import AlphaProviderRegistry
from apps.alpha.domain.entities import AlphaResult, StockScore
from apps.alpha.domain.interfaces import AlphaProvider
from apps.hedge.infrastructure.adapters import FailoverHedgeAdapter, HedgeDataSource
from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider
from apps.rotation.infrastructure.adapters import price_adapter as rotation_price_adapter
from apps.task_monitor.infrastructure import repositories as task_monitor_repositories


class _StaticAlphaProvider(AlphaProvider):
    def __init__(
        self,
        *,
        name: str,
        priority: int,
        result: AlphaResult,
        max_staleness_days: int = 2,
    ) -> None:
        self._name = name
        self._priority = priority
        self._result = result
        self._max_staleness_days = max_staleness_days

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def max_staleness_days(self) -> int:
        return self._max_staleness_days

    def health_check(self):
        from apps.alpha.domain.interfaces import AlphaProviderStatus

        return AlphaProviderStatus.AVAILABLE

    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30,
        **kwargs,
    ) -> AlphaResult:
        return self._result

    def get_factor_exposure(self, stock_code: str, trade_date: date) -> dict[str, float]:
        return {}

    def supports(self, universe_id: str, **kwargs) -> bool:
        return True


@pytest.mark.django_db
def test_task_monitor_preflight_unreachable_is_not_warning_noise(caplog):
    task_monitor_repositories._PREFLIGHT_UNREACHABLE_CACHE.clear()

    mock_app = Mock()
    mock_app.conf.broker_url = "redis://127.0.0.1:6379/0"
    mock_app.conf.result_backend = "redis://127.0.0.1:6379/1"

    checker = task_monitor_repositories.CeleryHealthChecker(mock_app)
    checker._preflight_transport_endpoint = Mock(return_value=False)

    with caplog.at_level(logging.WARNING):
        checker.check_health()
        checker.check_health()

    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_rotation_price_service_silences_expected_missing_history(monkeypatch, caplog):
    monkeypatch.setattr(
        rotation_price_adapter,
        "fetch_close_prices_from_data_center",
        lambda **kwargs: [],
    )

    with caplog.at_level(logging.WARNING):
        result = rotation_price_adapter.RotationPriceDataService._fetch_from_data_center(
            "510300",
            date.today(),
            5,
        )

    assert result is None
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_hedge_failover_is_quiet_when_all_sources_return_none(caplog):
    class NullSource(HedgeDataSource):
        def get_asset_prices(self, asset_code: str, end_date: date, days: int = 60):
            return None

    adapter = FailoverHedgeAdapter()
    adapter.sources = [NullSource(), NullSource(), NullSource()]

    with caplog.at_level(logging.WARNING):
        result = adapter.get_asset_prices("510300", date.today(), 5)

    assert result is None
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_alpha_registry_fallback_to_next_provider_is_quiet(caplog):
    registry = AlphaProviderRegistry()
    stale_or_failed = _StaticAlphaProvider(
        name="qlib",
        priority=1,
        result=AlphaResult(
            success=False,
            scores=[],
            source="qlib",
            timestamp=date.today().isoformat(),
            status="degraded",
            error_message="缓存缺失，同步推理未生成可用结果",
        ),
    )
    fallback = _StaticAlphaProvider(
        name="etf",
        priority=1000,
        result=AlphaResult(
            success=True,
            scores=[
                StockScore(
                    code="510300.SH",
                    score=0.8,
                    rank=1,
                    factors={},
                    source="etf",
                    confidence=0.9,
                )
            ],
            source="etf",
            timestamp=date.today().isoformat(),
            status="available",
        ),
    )
    registry.register(stale_or_failed)
    registry.register(fallback)

    with caplog.at_level(logging.WARNING):
        result = registry.get_scores_with_fallback("csi300", date.today(), 30)

    assert result.success is True
    assert result.source == "etf"
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_qlib_provider_no_worker_path_is_quiet(monkeypatch, caplog):
    provider = QlibAlphaProvider()
    monkeypatch.setattr(provider, "_get_from_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(provider, "_resolve_live_inference_queue", lambda: None)
    monkeypatch.setattr(provider, "_can_run_inline_inference", lambda pool_scope: False)

    with caplog.at_level(logging.WARNING):
        result = provider.get_stock_scores("csi300", date.today(), 10)

    assert result.success is False
    assert result.metadata["inference_trigger_status"] == "no_worker"
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
