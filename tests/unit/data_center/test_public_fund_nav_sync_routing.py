"""Public-port routing contracts for fund NAV synchronization."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from apps.data_center.application import public
from apps.data_center.application.dtos import SyncResult
from apps.data_center.domain.enums import DataCapability


class _Provider:
    def __init__(self, name: str, supports_fund_nav: bool = True) -> None:
        self._name = name
        self._supports_fund_nav = supports_fund_nav

    def provider_name(self) -> str:
        return self._name

    def supports(self, capability: DataCapability) -> bool:
        return self._supports_fund_nav and capability is DataCapability.FUND_NAV


class _SyncUseCase:
    def __init__(self, results: list[SyncResult]) -> None:
        self.results = iter(results)
        self.requests: list[object] = []

    def execute(self, request: object) -> SyncResult:
        self.requests.append(request)
        return next(self.results)


def test_fund_nav_sync_routes_to_active_capability_and_fails_over(monkeypatch) -> None:
    """An empty first provider must not prevent an active fallback provider."""

    configs = [
        SimpleNamespace(id=1, priority=10),
        SimpleNamespace(id=2, priority=20),
    ]
    providers = {
        1: _Provider("akshare-primary"),
        2: _Provider("eastmoney-fallback"),
    }
    use_case = _SyncUseCase(
        [
            SyncResult("fund_nav", "akshare-primary", 0, "noop"),
            SyncResult("fund_nav", "eastmoney-fallback", 2, "success"),
        ]
    )
    monkeypatch.setattr(
        public,
        "get_provider_config_repository",
        lambda: SimpleNamespace(list_active=lambda: configs),
    )
    monkeypatch.setattr(
        public,
        "get_provider_registry",
        lambda: SimpleNamespace(get_by_id=lambda provider_id: providers.get(provider_id)),
    )
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.make_sync_fund_nav_use_case",
        lambda: use_case,
    )

    result = public.sync_fund_nav_from_active_provider(
        "110011",
        start=date(2026, 1, 1),
        end=date(2026, 7, 31),
    )

    assert result["stored_count"] == 2
    assert result["provider_name"] == "eastmoney-fallback"
    assert [request.provider_id for request in use_case.requests] == [1, 2]
    assert use_case.requests[0].fund_code == "110011"


def test_fund_nav_sync_blocks_without_active_capability(monkeypatch) -> None:
    """No active fund-NAV provider is an explicit blocked outcome."""

    monkeypatch.setattr(
        public,
        "get_provider_config_repository",
        lambda: SimpleNamespace(list_active=lambda: []),
    )
    monkeypatch.setattr(
        public,
        "get_provider_registry",
        lambda: SimpleNamespace(get_by_id=lambda _provider_id: None),
    )
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.make_sync_fund_nav_use_case",
        lambda: (_ for _ in ()).throw(AssertionError("sync use case must not be built")),
    )

    result = public.sync_fund_nav_from_active_provider(
        "110011",
        start=date(2026, 1, 1),
        end=date(2026, 7, 31),
    )

    assert result == {
        "domain": "fund_nav",
        "provider_name": "",
        "stored_count": 0,
        "status": "blocked",
        "error_message": "no active provider supports fund_nav",
    }
