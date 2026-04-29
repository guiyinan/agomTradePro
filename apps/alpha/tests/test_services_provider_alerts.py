from datetime import date

from apps.alpha.application.services import AlphaProviderRegistry
from apps.alpha.domain.entities import AlphaResult
from apps.alpha.domain.interfaces import AlphaProviderStatus
from apps.alpha.infrastructure.adapters.base import BaseAlphaProvider


class _FakeProvider(BaseAlphaProvider):
    def __init__(
        self,
        *,
        name: str,
        priority: int,
        health: AlphaProviderStatus = AlphaProviderStatus.AVAILABLE,
        result: AlphaResult | None = None,
    ):
        super().__init__()
        self._name = name
        self._priority = priority
        self._health = health
        self._result = result or AlphaResult(
            success=False,
            scores=[],
            source=name,
            timestamp="2026-04-30",
            status="unavailable",
            error_message=f"{name} unavailable",
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    def health_check(self) -> AlphaProviderStatus:
        return self._health

    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30,
        pool_scope=None,
        user=None,
    ) -> AlphaResult:
        return self._result


class _FakeAlertRepository:
    def __init__(self) -> None:
        self.created_alerts: list[dict] = []

    def create_alert(self, **kwargs):
        self.created_alerts.append(kwargs)
        return kwargs


def test_provider_filter_failure_does_not_create_global_provider_unavailable_alert(monkeypatch):
    alert_repo = _FakeAlertRepository()
    monkeypatch.setattr(
        "apps.alpha.application.services.get_alpha_alert_repository",
        lambda: alert_repo,
    )

    registry = AlphaProviderRegistry()
    registry.register(
        _FakeProvider(
            name="simple",
            priority=100,
            result=AlphaResult(
                success=False,
                scores=[],
                source="simple",
                timestamp="2026-04-30",
                status="unavailable",
                error_message="simple failed",
            ),
        )
    )

    result = registry.get_scores_with_fallback(
        universe_id="csi300",
        intended_trade_date=date(2026, 4, 30),
        top_n=30,
        provider_filter="simple",
    )

    assert result.success is False
    assert result.source == "simple"
    assert result.error_message == "指定的 Provider 'simple' 失败或数据过期"
    assert result.metadata["provider_probe_only"] is True
    assert result.metadata["attempted_providers"] == ["simple"]
    assert alert_repo.created_alerts == []


def test_auto_fallback_failure_still_creates_global_provider_unavailable_alert(monkeypatch):
    alert_repo = _FakeAlertRepository()
    monkeypatch.setattr(
        "apps.alpha.application.services.get_alpha_alert_repository",
        lambda: alert_repo,
    )

    registry = AlphaProviderRegistry()
    registry.register(
        _FakeProvider(
            name="qlib",
            priority=1,
            result=AlphaResult(
                success=False,
                scores=[],
                source="qlib",
                timestamp="2026-04-30",
                status="unavailable",
                error_message="qlib failed",
            ),
        )
    )

    result = registry.get_scores_with_fallback(
        universe_id="csi300",
        intended_trade_date=date(2026, 4, 30),
        top_n=30,
    )

    assert result.success is False
    assert result.source == "none"
    assert result.error_message == "所有 Alpha Provider 失败或数据过期"
    assert len(alert_repo.created_alerts) == 1
    alert = alert_repo.created_alerts[0]
    assert alert["alert_type"] == "provider_unavailable"
    assert alert["message"] == "尝试顺序: qlib"
    assert alert["metadata"]["attempted_providers"] == ["qlib"]
