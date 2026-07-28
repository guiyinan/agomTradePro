import json
import logging
from types import SimpleNamespace

import pytest

from core.application.config_center import (
    _CAPABILITIES,
    _SUMMARY_BUILDERS,
    _safe_summary,
    build_config_center_snapshot,
    list_config_capabilities,
)


def test_list_config_capabilities_contains_core_items():
    capabilities = list_config_capabilities()
    keys = {item["key"] for item in capabilities}

    assert "agent_runtime_operator" in keys
    assert "system_settings" in keys
    assert "valuation_repair" in keys
    assert "beta_gate" in keys
    assert "risk_center" in keys
    assert "ai_provider" in keys
    assert "trading_cost" in keys
    assert "data_center_providers" in keys
    assert "data_center_runtime" in keys


def test_build_config_center_snapshot_filters_staff_items_for_normal_user(monkeypatch):
    monkeypatch.setattr(
        "core.application.config_center._SUMMARY_BUILDERS",
        {
            "account_settings": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "mcp_guide": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "capability_gateway": lambda user: {
                "status": "configured",
                "summary": {"message": "ok"},
            },
            "agent_runtime_operator": lambda user: {
                "status": "configured",
                "summary": {"message": "ok"},
            },
            "system_settings": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "data_center_providers": lambda user: {
                "status": "configured",
                "summary": {"message": "ok"},
            },
            "data_center_runtime": lambda user: {
                "status": "configured",
                "summary": {"message": "ok"},
            },
            "beta_gate": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "risk_center": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "valuation_repair": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "ai_provider": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "trading_cost": lambda user: {"status": "configured", "summary": {"message": "ok"}},
        },
    )

    snapshot = build_config_center_snapshot(SimpleNamespace(is_staff=False))
    item_keys = {item["key"] for section in snapshot["sections"] for item in section["items"]}

    assert "trading_cost" in item_keys
    assert "agent_runtime_operator" not in item_keys
    assert "risk_center" not in item_keys
    assert "valuation_repair" not in item_keys
    assert "system_settings" not in item_keys
    assert "data_center_providers" not in item_keys
    assert "data_center_runtime" not in item_keys
    assert "mcp_guide" in item_keys
    assert "capability_gateway" in item_keys


def test_config_center_capabilities_and_summary_builders_remain_in_sync():
    capabilities = list_config_capabilities()
    capability_keys = {item["key"] for item in capabilities}

    assert capability_keys == set(_SUMMARY_BUILDERS.keys())


def test_safe_summary_redacts_provider_exception_details(caplog):
    def _failing_builder(user):
        raise RuntimeError("postgresql://admin:raw-secret@example.test/prod")

    with caplog.at_level(logging.WARNING):
        payload = _safe_summary(_failing_builder, "测试配置", object())

    assert payload == {
        "status": "attention",
        "summary": {"message": "测试配置 读取失败"},
    }
    assert "raw-secret" not in caplog.text
    assert "postgresql://" not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"status": "configured", "summary": []},
        {"status": "configured", "summary": {1: "non-string-key"}},
        {"status": "configured", "summary": {"score": float("nan")}},
        {"status": "configured\nforged", "summary": {}},
    ],
)
def test_safe_summary_rejects_invalid_dynamic_payloads(payload):
    result = _safe_summary(lambda user: payload, "动态配置", object())

    assert result["status"] == "attention"
    assert result["summary"]["message"] == "动态配置 读取失败"


def test_safe_summary_rejects_oversized_payload():
    result = _safe_summary(
        lambda user: {
            "status": "configured",
            "summary": {"content": "x" * 1_048_576},
        },
        "超大配置",
        object(),
    )

    assert result["status"] == "attention"


def test_safe_summary_detaches_valid_payload():
    source = {"status": "configured", "summary": {"items": ["one"]}}
    result = _safe_summary(lambda user: source, "合法配置", object())
    source["summary"]["items"].append("two")

    assert result == {"status": "configured", "summary": {"items": ["one"]}}
    assert json.dumps(result, allow_nan=False)


def test_string_staff_flag_does_not_publish_staff_capabilities(monkeypatch):
    monkeypatch.setattr(
        "core.application.config_center._SUMMARY_BUILDERS",
        {
            capability.key: (lambda user: {"status": "configured", "summary": {"message": "ok"}})
            for capability in _CAPABILITIES
        },
    )

    snapshot = build_config_center_snapshot(SimpleNamespace(is_staff="false"))
    item_keys = {item["key"] for section in snapshot["sections"] for item in section["items"]}

    assert "system_settings" not in item_keys
    assert "risk_center" not in item_keys
