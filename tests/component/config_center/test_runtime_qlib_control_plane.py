from __future__ import annotations

import pytest

from apps.account.infrastructure.account_interface_repository import AccountInterfaceRepository
from apps.config_center.application.runtime_public import (
    get_active_domain_runtime_config,
    get_active_runtime_value,
)
from apps.config_center.infrastructure.config_summary_repository import (
    DjangoConfigCenterSummaryRepository,
)
from apps.config_center.infrastructure.models import SystemSettingsModel
from apps.config_center.infrastructure.repositories import ConfigCenterSettingsRepository
from apps.data_center.application.interface_services import (
    load_provider_settings_payload,
    save_provider_settings_payload,
)
from apps.data_center.infrastructure.models import DataProviderSettingsModel


@pytest.mark.django_db
def test_runtime_qlib_summary_prefers_typed_snapshot(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _typed_runtime(environment: str) -> dict[str, object]:
        captured["environment"] = environment
        return {
            "enabled": True,
            "provider_uri": "/srv/qlib/cn_data",
            "region": "CN",
            "model_path": "/srv/qlib/models",
            "default_universe": "csi300",
            "default_feature_set_id": "v1",
            "default_label_id": "return_5d",
            "train_queue_name": "qlib_train",
            "infer_queue_name": "qlib_infer",
            "allow_auto_activate": False,
            "is_configured": True,
        }

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.production")
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.get_active_qlib_runtime_config",
        _typed_runtime,
    )
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.SystemSettingsModel.get_runtime_qlib_config",
        lambda: (_ for _ in ()).throw(AssertionError("legacy SystemSettings path used")),
    )

    result = DjangoConfigCenterSummaryRepository().get_runtime_qlib_config()

    assert result["provider_uri"] == "/srv/qlib/cn_data"
    assert result["is_configured"] is True
    assert captured == {"environment": "production"}


@pytest.mark.django_db
def test_runtime_qlib_summary_blocks_when_snapshot_missing(monkeypatch) -> None:
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.development")
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.get_active_qlib_runtime_config",
        lambda _environment: None,
    )
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.SystemSettingsModel.get_runtime_qlib_config",
        lambda: (_ for _ in ()).throw(AssertionError("legacy SystemSettings path used")),
    )

    assert DjangoConfigCenterSummaryRepository().get_runtime_qlib_config() == {
        "enabled": False,
        "is_configured": False,
        "status": "blocked",
        "source": "config_center_runtime_profile",
        "must_not_use_for_decision": True,
        "blocked_reason": "runtime_config_snapshot_unavailable",
    }


@pytest.mark.django_db
def test_domain_runtime_summary_prefers_complete_typed_snapshot(monkeypatch) -> None:
    typed = {
        "alpha_fixed_provider": "qlib",
        "alpha_pool_mode": "market",
        "market_color_convention": "us_market",
        "benchmark_code_map": {"equity_market_benchmark": "000300.SH"},
        "asset_proxy_code_map": {"A_SHARE_GROWTH": "000300.SH"},
    }
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.production")
    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.get_active_domain_runtime_config",
        lambda environment: typed,
    )
    for method_name in (
        "get_runtime_market_visual_tokens",
        "get_runtime_alpha_fixed_provider",
        "get_runtime_alpha_pool_mode",
        "get_runtime_benchmark_code",
        "get_runtime_asset_proxy_map",
    ):
        monkeypatch.setattr(
            f"apps.config_center.infrastructure.config_summary_repository.SystemSettingsModel.{method_name}",
            lambda *args, _method_name=method_name, **kwargs: (_ for _ in ()).throw(
                AssertionError(f"legacy SystemSettings path used: {_method_name}")
            ),
        )

    repository = DjangoConfigCenterSummaryRepository()
    assert repository.get_runtime_alpha_fixed_provider() == "qlib"
    assert repository.get_runtime_alpha_pool_mode("strict_valuation") == "market"
    assert repository.get_runtime_benchmark_code("equity_market_benchmark") == "000300.SH"
    assert repository.get_runtime_asset_proxy_map() == {"A_SHARE_GROWTH": "000300.SH"}
    assert repository.get_runtime_market_visual_tokens()["convention"] == "us_market"

    class _LegacySettings:
        default_mcp_enabled = False
        allow_token_plaintext_view = False
        market_color_convention = "cn_a_share"
        benchmark_code_map = {"legacy": "000001.SH"}
        asset_proxy_code_map = {"legacy": "510050.SH"}
        updated_at = None

        @staticmethod
        def get_market_visual_tokens():
            return {"label": "A股红涨绿跌"}

    monkeypatch.setattr(
        "apps.config_center.infrastructure.config_summary_repository.SystemSettingsModel.get_settings_for_read",
        lambda: _LegacySettings(),
    )
    monkeypatch.setattr(
        repository,
        "get_runtime_qlib_config",
        lambda: {"enabled": False, "is_configured": False},
    )
    summary = repository.get_system_settings_summary()["summary"]
    assert summary["market_color_convention"] == "us_market"
    assert summary["market_color_label"] == "美股绿涨红跌"
    assert summary["benchmark_map_size"] == 1
    assert summary["asset_proxy_map_size"] == 1


@pytest.mark.django_db
def test_qlib_runtime_update_activates_typed_profile_without_legacy_write(tmp_path) -> None:
    """The Qlib admin mutation must publish a typed revision, not update the singleton."""

    provider_dir = tmp_path / "qlib" / "cn_data"
    model_dir = tmp_path / "qlib" / "models"
    provider_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)
    settings_obj = SystemSettingsModel.get_settings()
    settings_obj.qlib_enabled = False
    settings_obj.save(update_fields=["qlib_enabled", "updated_at"])

    payload = ConfigCenterSettingsRepository().update_runtime_config(
        {
            "enabled": True,
            "provider_uri": str(provider_dir),
            "model_root": str(model_dir),
            "region": "CN",
            "default_universe": "csi300",
            "default_feature_set_id": "v1",
            "default_label_id": "return_5d",
            "train_queue_name": "qlib_train",
            "infer_queue_name": "qlib_infer",
            "allow_auto_activate": False,
            "alpha_fixed_provider": "",
            "alpha_pool_mode": "strict_valuation",
        },
        actor="pytest",
    )

    assert payload["configured"] is True
    assert payload["status"] == "active"
    assert payload["source"] == "config_center_runtime_profile"
    assert SystemSettingsModel.get_settings_for_read().qlib_enabled is False

    governance = ConfigCenterSettingsRepository().update_system_governance(
        {
            "market_color_convention": "us_market",
            "alpha_pool_mode": "market",
            "benchmark_code_map": {"equity_market_benchmark": "000300.SH"},
            "asset_proxy_code_map": {"A_SHARE_GROWTH": "000300.SH"},
        },
        actor="pytest",
    )

    assert governance["market_color_convention"] == "us_market"
    assert governance["alpha_pool_mode"] == "market"
    assert governance["benchmark_code_map"] == {"equity_market_benchmark": "000300.SH"}
    assert governance["asset_proxy_code_map"] == {"A_SHARE_GROWTH": "000300.SH"}


@pytest.mark.django_db
def test_provider_settings_update_uses_typed_failover_values() -> None:
    """Data Center provider settings publish failover values into the runtime profile."""

    payload = save_provider_settings_payload(
        default_source="akshare",
        enable_failover=False,
        failover_tolerance=0.025,
        actor="pytest",
    )

    assert payload["enable_failover"] is False
    assert payload["failover_tolerance"] == pytest.approx(0.025)
    assert payload["default_source"] == "akshare"
    assert load_provider_settings_payload() == payload

    assert (
        get_active_runtime_value(
            environment="development",
            definition_key="data_center.provider.default_source",
        )
        == "akshare"
    )
    assert not DataProviderSettingsModel.objects.filter(pk=1).exists()


@pytest.mark.django_db
def test_account_system_settings_update_uses_typed_market_governance() -> None:
    """The legacy admin form must publish runtime fields through Config Center."""

    legacy = SystemSettingsModel.get_settings()
    legacy.market_color_convention = "cn_a_share"
    legacy.alpha_pool_mode = SystemSettingsModel.ALPHA_POOL_MODE_STRICT_VALUATION
    legacy.benchmark_code_map = {"legacy": "000001.SH"}
    legacy.asset_proxy_code_map = {"legacy": "510050.SH"}
    legacy.save(
        update_fields=[
            "market_color_convention",
            "alpha_pool_mode",
            "benchmark_code_map",
            "asset_proxy_code_map",
            "updated_at",
        ]
    )

    AccountInterfaceRepository().update_system_settings_from_mapping(
        {
            "require_user_approval": "on",
            "auto_approve_first_admin": "on",
            "default_mcp_enabled": "on",
            "allow_token_plaintext_view": "on",
            "market_color_convention": "us_market",
            "alpha_pool_mode": "market",
            "user_agreement_content": "agreement",
            "risk_warning_content": "risk",
            "notes": "typed runtime update",
            "benchmark_code_map": '{"equity_market_benchmark": "000300.SH"}',
            "asset_proxy_code_map": '{"A_SHARE_GROWTH": "000300.SH"}',
        },
        actor="pytest",
    )

    typed = get_active_domain_runtime_config("development")
    assert typed is not None
    assert typed["market_color_convention"] == "us_market"
    assert typed["alpha_pool_mode"] == "market"
    assert typed["benchmark_code_map"] == {"equity_market_benchmark": "000300.SH"}
    assert typed["asset_proxy_code_map"] == {"A_SHARE_GROWTH": "000300.SH"}

    legacy = SystemSettingsModel.get_settings_for_read()
    assert legacy.market_color_convention == "cn_a_share"
    assert legacy.alpha_pool_mode == SystemSettingsModel.ALPHA_POOL_MODE_STRICT_VALUATION
    assert legacy.benchmark_code_map == {"legacy": "000001.SH"}
    assert legacy.asset_proxy_code_map == {"legacy": "510050.SH"}
