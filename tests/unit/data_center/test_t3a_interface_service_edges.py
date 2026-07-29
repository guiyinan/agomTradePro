"""T3A edge contracts for Data Center application-side interface builders."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from apps.data_center.application import interface_services
from apps.data_center.domain.entities import DataProviderSettings, ProviderConfig


def _provider() -> ProviderConfig:
    return ProviderConfig(
        id=3,
        name="AKShare",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


def test_dynamic_runtime_wrappers_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert interface_services._json_object("invalid") == {}
    monkeypatch.setattr(
        interface_services,
        "_refresh_pulse_snapshot",
        lambda **kwargs: kwargs["target_date"],
    )
    assert interface_services.refresh_pulse_snapshot(target_date=date(2024, 1, 2)) == date(
        2024, 1, 2
    )

    monkeypatch.setattr(interface_services, "_fetch_latest_prices", lambda _codes: None)
    assert interface_services.fetch_latest_prices(["000001.SZ"]) == []
    monkeypatch.setattr(
        interface_services,
        "_fetch_latest_prices",
        lambda _codes: [{"code": "000001.SZ"}, "invalid"],
    )
    assert interface_services.fetch_latest_prices(["000001.SZ"]) == [{"code": "000001.SZ"}]


def test_provider_settings_save_returns_persisted_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[DataProviderSettings] = []
    monkeypatch.setattr(
        interface_services,
        "DataProviderSettingsRepository",
        lambda: SimpleNamespace(save=lambda settings: saved.append(settings) or settings),
    )
    payload = interface_services.save_provider_settings_payload(
        default_source="akshare",
        enable_failover=True,
        failover_tolerance=0.01,
    )
    assert payload == {
        "default_source": "akshare",
        "enable_failover": True,
        "failover_tolerance": 0.01,
    }


def test_scope_quote_sync_handles_empty_missing_failure_and_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert interface_services._sync_scope_quotes([])["status"] == "skipped"

    repository = SimpleNamespace(list_all=lambda: [])
    monkeypatch.setattr(interface_services, "_make_provider_repo", lambda: repository)
    assert interface_services._sync_scope_quotes(["000001.SZ"])["status"] == "skipped"

    repository.list_all = lambda: [_provider()]
    monkeypatch.setattr(
        interface_services,
        "build_provider_registry_for_repo",
        lambda _repository: object(),
    )

    class _FailingUseCase:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def execute(self, _request: object) -> object:
            raise RuntimeError("sync unavailable")

    monkeypatch.setattr(interface_services, "SyncQuoteUseCase", _FailingUseCase)
    assert interface_services._sync_scope_quotes(["000001.sz"]) == {
        "status": "failed",
        "error_message": "sync unavailable",
    }

    class _SuccessUseCase(_FailingUseCase):
        def execute(self, _request: object) -> object:
            return SimpleNamespace(to_dict=lambda: {"status": "success", "stored_count": 1})

    monkeypatch.setattr(interface_services, "SyncQuoteUseCase", _SuccessUseCase)
    assert interface_services._sync_scope_quotes(["000001.sz"])["stored_count"] == 1


def test_pulse_and_alpha_readers_return_registered_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        interface_services,
        "refresh_pulse_snapshot",
        lambda **kwargs: {"date": kwargs["target_date"].isoformat()},
    )
    assert interface_services._build_pulse_refresher()(date(2024, 1, 2)) == {"date": "2024-01-02"}

    reader = interface_services._build_alpha_status_reader(SimpleNamespace(id=7))
    assert reader(date(2024, 1, 2), None)["status"] == "blocked"
    monkeypatch.setattr(
        interface_services,
        "load_alpha_homepage_data",
        lambda **_kwargs: SimpleNamespace(
            meta={"recommendation_ready": True, "scope_hash": "scope-1"},
            actionable_candidates=[1, 2],
            pool={},
        ),
    )
    payload = reader(date(2024, 1, 2), 9)
    assert payload["status"] == "ready"
    assert payload["actionable_candidate_count"] == 2


def test_skipped_thermometer_payload_distinguishes_fresh_and_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SimpleNamespace(get_latest=lambda: None)
    monkeypatch.setattr(
        interface_services,
        "MarketThermometerSnapshotRepository",
        lambda: repository,
    )
    assert (
        interface_services._build_skipped_latest_market_thermometer_payload(thermometer_payload={})
        is None
    )

    latest = SimpleNamespace(
        observed_at=date(2024, 1, 2),
        must_not_use_for_decision=False,
        to_dict=lambda: {"observed_at": "2024-01-02"},
    )
    repository.get_latest = lambda: latest
    assert (
        interface_services._build_skipped_latest_market_thermometer_payload(
            thermometer_payload={"observed_at": "2024-01-02"}
        )
        is None
    )
    latest.must_not_use_for_decision = True
    blocked = interface_services._build_skipped_latest_market_thermometer_payload(
        thermometer_payload={"observed_at": "2024-01-02"}
    )
    assert blocked is not None
    assert blocked["skip_reason"] == "latest_snapshot_must_not_use_for_decision"
