from __future__ import annotations

from types import SimpleNamespace

from core.integration import runtime_settings


def test_runtime_config_value_bridge_delegates_to_config_center_provider(monkeypatch) -> None:
    provider = SimpleNamespace(get_runtime_config_value=lambda definition_key: 1)
    monkeypatch.setattr(runtime_settings, "_provider", provider)

    assert runtime_settings.get_runtime_config_value("task_monitor.retention_days") == 1
