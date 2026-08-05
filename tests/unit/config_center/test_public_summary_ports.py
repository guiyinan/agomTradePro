from __future__ import annotations

from types import SimpleNamespace

from apps.config_center.application import public


def test_summary_public_ports_delegate_to_config_center_owner(monkeypatch) -> None:
    """Business consumers receive summaries through the application owner."""

    service = SimpleNamespace(
        get_system_settings_summary=lambda: {"status": "configured"},
        get_runtime_market_visual_tokens=lambda: {"rise": "red"},
        get_runtime_qlib_config=lambda: {"enabled": True},
        get_runtime_alpha_fixed_provider=lambda: "qlib",
        get_runtime_alpha_pool_mode=lambda default: default or "strict",
        get_runtime_benchmark_code=lambda key, default: f"{key}:{default}",
        get_runtime_asset_proxy_map=lambda: {"growth": "000300.SH"},
    )
    monkeypatch.setattr(public, "get_config_center_summary_service", lambda: service)

    assert public.get_system_settings_summary() == {"status": "configured"}
    assert public.get_runtime_market_visual_tokens() == {"rise": "red"}
    assert public.get_runtime_qlib_config() == {"enabled": True}
    assert public.get_runtime_alpha_fixed_provider() == "qlib"
    assert public.get_runtime_alpha_pool_mode() == "strict"
    assert public.get_runtime_benchmark_code("equity", "") == "equity:"
    assert public.get_runtime_asset_proxy_map() == {"growth": "000300.SH"}
