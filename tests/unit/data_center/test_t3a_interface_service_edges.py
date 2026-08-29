"""T3A edge contracts for Data Center application-side interface builders."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from apps.data_center.application import interface_services
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure import config_summary_repository


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
    active_values: dict[str, object] = {}
    runtime_patches: list[dict[str, object]] = []

    def _activate(**kwargs: object) -> dict[str, int]:
        patch = dict(kwargs["patch"])
        runtime_patches.append(patch)
        active_values.update(patch)
        return {"profile_version": 1}

    monkeypatch.setattr(
        interface_services,
        "activate_runtime_profile_patch",
        _activate,
    )
    monkeypatch.setattr(
        interface_services,
        "get_active_runtime_value",
        lambda *, definition_key, environment: active_values.get(definition_key),
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
        "status": "active",
        "source": "config_center_runtime_profile",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
    }
    assert runtime_patches == [
        {
            "data_center.provider.default_source": "akshare",
            "data_center.provider.enable_failover": True,
            "data_center.provider.failover_tolerance": 0.01,
        }
    ]


def test_provider_settings_payload_prefers_typed_default_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "data_center.provider.default_source": "tushare",
        "data_center.provider.enable_failover": False,
        "data_center.provider.failover_tolerance": 0.025,
    }
    monkeypatch.setattr(
        interface_services,
        "get_active_runtime_value",
        lambda *, definition_key, environment: values.get(definition_key),
    )

    assert interface_services.load_provider_settings_payload() == {
        "default_source": "tushare",
        "enable_failover": False,
        "failover_tolerance": 0.025,
        "status": "active",
        "source": "config_center_runtime_profile",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
    }


@pytest.mark.parametrize(
    ("values", "reason"),
    [
        ({}, "provider_runtime_default_source_missing"),
        (
            {
                "data_center.provider.default_source": "legacy",
                "data_center.provider.enable_failover": True,
                "data_center.provider.failover_tolerance": 0.01,
            },
            "provider_runtime_default_source_invalid",
        ),
        (
            {
                "data_center.provider.default_source": "akshare",
                "data_center.provider.enable_failover": "true",
                "data_center.provider.failover_tolerance": 0.01,
            },
            "provider_runtime_failover_enabled_invalid",
        ),
    ],
)
def test_provider_settings_payload_fails_closed_without_complete_typed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, object],
    reason: str,
) -> None:
    monkeypatch.setattr(
        interface_services,
        "get_active_runtime_value",
        lambda *, definition_key, environment: values.get(definition_key),
    )

    assert interface_services.load_provider_settings_payload() == {
        "default_source": None,
        "enable_failover": None,
        "failover_tolerance": None,
        "status": "blocked",
        "source": "config_center_runtime_profile",
        "must_not_use_for_decision": True,
        "blocked_reason": reason,
    }


def test_provider_summary_prefers_typed_provider_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Rows:
        def values(self, *_fields: str) -> list[dict[str, object]]:
            return []

    monkeypatch.setattr(
        config_summary_repository,
        "ProviderConfigModel",
        SimpleNamespace(_default_manager=SimpleNamespace(all=lambda: _Rows())),
    )
    monkeypatch.setattr(
        config_summary_repository,
        "_resolve_default_source",
        lambda *_args, **_kwargs: "tushare",
    )
    monkeypatch.setattr(
        config_summary_repository,
        "_resolve_failover_enabled",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        config_summary_repository,
        "_resolve_failover_tolerance",
        lambda *_args, **_kwargs: 0.025,
    )

    summary = (
        config_summary_repository.DjangoDataCenterConfigSummaryRepository().get_provider_summary()
    )

    assert summary["summary"] == {
        "message": "当前没有配置 Provider 记录。",
        "total_providers": 0,
        "active_providers": 0,
        "default_source": "tushare",
        "enable_failover": False,
        "failover_tolerance": 0.025,
        "custom_http_url_count": 0,
        "missing_api_key_count": 0,
        "runtime_status": "active",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
    }


def test_provider_summary_fails_closed_when_typed_runtime_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Rows:
        def values(self, *_fields: str) -> list[dict[str, object]]:
            return []

    monkeypatch.setattr(
        config_summary_repository,
        "ProviderConfigModel",
        SimpleNamespace(_default_manager=SimpleNamespace(all=lambda: _Rows())),
    )
    monkeypatch.setattr(
        config_summary_repository,
        "_resolve_default_source",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("provider_runtime_default_source_missing")
        ),
    )

    summary = (
        config_summary_repository.DjangoDataCenterConfigSummaryRepository().get_provider_summary()
    )

    assert summary["status"] == "blocked"
    assert summary["summary"]["default_source"] is None
    assert summary["summary"]["must_not_use_for_decision"] is True
    assert summary["summary"]["blocked_reason"] == "provider_runtime_default_source_missing"


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

    monkeypatch.setattr(
        interface_services._decision_sync,
        "make_system_audited_sync_quote_use_case",
        lambda **_kwargs: _FailingUseCase(),
    )
    assert interface_services._sync_scope_quotes(["000001.sz"]) == {
        "status": "failed",
        "error_class": "RuntimeError",
    }

    class _SuccessUseCase(_FailingUseCase):
        def execute(self, _request: object) -> object:
            return SimpleNamespace(to_dict=lambda: {"status": "success", "stored_count": 1})

    monkeypatch.setattr(
        interface_services._decision_sync,
        "make_system_audited_sync_quote_use_case",
        lambda **_kwargs: _SuccessUseCase(),
    )
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
