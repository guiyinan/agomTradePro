"""Tests for the MCP read-evidence validation script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "check_mcp_read_evidence.py"
    spec = importlib.util.spec_from_file_location("check_mcp_read_evidence", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest() -> CapabilityManifest:
    return CapabilityManifest(
        capability_key="policy.read.workbench.bootstrap",
        title="Test",
        summary="Test",
        description="Test",
        owner_app="policy",
        risk_level="low",
        executor_kind="legacy_tool",
        executor_ref="get_workbench_bootstrap",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
        legacy_tool_names=("get_workbench_bootstrap",),
    )


def _valid_kwargs() -> dict:
    return {
        "raw_tool_index": {"get_workbench_bootstrap": "sdk/agomtradepro_mcp/tools/policy_tools.py"},
        "server_evidence_index": {
            "function_bodies": {
                "_fallback_get_workbench_bootstrap": (
                    "from agomtradepro import AgomTradeProClient\n"
                    "client = AgomTradeProClient()\n"
                    "return client.policy.get_workbench_bootstrap()"
                )
            },
            "legacy_fallbacks": {"get_workbench_bootstrap": "_fallback_get_workbench_bootstrap"},
            "internal_handlers": {},
        },
        "core_registry_test_blocks": [
            (
                "policy.read.workbench.bootstrap get_workbench_bootstrap "
                "INTERNAL_LEGACY_TOOL_FALLBACKS agom_capability_call"
            )
        ],
        "ai_capability_test_blocks": [
            "policy.read.workbench.bootstrap get_workbench_bootstrap " "replacement_capability_key"
        ],
        "sdk_test_blocks": ["result = client.policy.get_workbench_bootstrap()\nassert result"],
        "unsupported_contract_keys": set(),
    }


def test_validate_read_evidence_accepts_complete_read_contract():
    module = _load_module()

    summary = module.validate_read_evidence_manifests(
        [_manifest()],
        **_valid_kwargs(),
    )

    assert summary["read_like_manifests"] == 1
    assert summary["raw_tool_evidence_manifests"] == 1
    assert summary["fallback_evidence_manifests"] == 1
    assert summary["sdk_contract_evidence_manifests"] == 1
    assert summary["core_only_test_evidence_manifests"] == 1
    assert summary["catalog_test_evidence_manifests"] == 1


def test_server_evidence_loads_read_handler_split_from_server_module():
    module = _load_module()

    evidence = module._load_server_evidence_index()

    fallback_name = evidence["legacy_fallbacks"]["get_config_center_snapshot"]
    assert fallback_name == "_fallback_get_config_center_snapshot"
    assert "AgomTradeProClient" in evidence["function_bodies"][fallback_name]


def test_validate_read_evidence_rejects_missing_raw_tool():
    module = _load_module()
    kwargs = _valid_kwargs()
    kwargs["raw_tool_index"] = {}

    with pytest.raises(ValueError, match="missing raw tool evidence"):
        module.validate_read_evidence_manifests([_manifest()], **kwargs)


def test_validate_read_evidence_rejects_missing_fallback():
    module = _load_module()
    kwargs = _valid_kwargs()
    kwargs["server_evidence_index"]["legacy_fallbacks"] = {}

    with pytest.raises(ValueError, match="missing server fallback evidence"):
        module.validate_read_evidence_manifests([_manifest()], **kwargs)


def test_validate_read_evidence_rejects_missing_sdk_contract():
    module = _load_module()
    kwargs = _valid_kwargs()
    kwargs["sdk_test_blocks"] = []

    with pytest.raises(ValueError, match="missing focused SDK contract evidence"):
        module.validate_read_evidence_manifests([_manifest()], **kwargs)


def test_validate_read_evidence_rejects_missing_core_only_test():
    module = _load_module()
    kwargs = _valid_kwargs()
    kwargs["core_registry_test_blocks"] = []

    with pytest.raises(ValueError, match="missing core-only capability-call evidence"):
        module.validate_read_evidence_manifests([_manifest()], **kwargs)


def test_validate_read_evidence_rejects_missing_catalog_test():
    module = _load_module()
    kwargs = _valid_kwargs()
    kwargs["ai_capability_test_blocks"] = []

    with pytest.raises(ValueError, match="missing catalog replacement evidence"):
        module.validate_read_evidence_manifests([_manifest()], **kwargs)


def test_validate_read_evidence_accepts_exhaustive_catalog_projection_matrix():
    module = _load_module()
    kwargs = _valid_kwargs()
    kwargs["ai_capability_test_blocks"] = [
        (
            "legacy_replacements = build_legacy_replacement_map(list(GOVERNED_MANIFESTS))\n"
            "for manifest in GOVERNED_MANIFESTS:\n"
            "    for legacy_tool_name in manifest.legacy_tool_names:\n"
            '        assert legacy.execution_target["replacement_capability_key"] == (\n'
            "            manifest.capability_key\n"
            "        )"
        )
    ]

    summary = module.validate_read_evidence_manifests(
        [_manifest()],
        **kwargs,
    )

    assert summary["catalog_test_evidence_manifests"] == 1


def test_validate_read_evidence_rejects_unsupported_contract_overlap():
    module = _load_module()
    kwargs = _valid_kwargs()
    kwargs["unsupported_contract_keys"] = {"policy.read.workbench.bootstrap"}

    with pytest.raises(ValueError, match="Unsupported legacy contract"):
        module.validate_read_evidence_manifests([_manifest()], **kwargs)


def test_validate_read_evidence_skips_clear_write_capability():
    module = _load_module()
    clear_manifest = CapabilityManifest(
        capability_key="sentiment.clear.cache",
        title="Clear Sentiment Cache",
        summary="Clear the sentiment cache.",
        description="Governed write capability.",
        owner_app="sentiment",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="sentiment_clear_cache",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        idempotency="required",
        tags=("sentiment", "cache", "clear", "write"),
        legacy_tool_names=("clear_sentiment_cache",),
    )

    summary = module.validate_read_evidence_manifests(
        [clear_manifest],
        **_valid_kwargs(),
    )

    assert summary["total_manifests"] == 1
    assert summary["read_like_manifests"] == 0
