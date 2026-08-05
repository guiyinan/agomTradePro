from __future__ import annotations

import pytest

from apps.config_center.infrastructure.config_summary_repository import (
    DjangoConfigCenterSummaryRepository,
)


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
