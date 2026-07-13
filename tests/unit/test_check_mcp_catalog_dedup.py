"""Tests for the MCP catalog dedup validation script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.ai_capability.domain.entities import CapabilityDefinition, SourceType


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "check_mcp_catalog_dedup.py"
    spec = importlib.util.spec_from_file_location("check_mcp_catalog_dedup", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _governed_capability():
    return CapabilityDefinition(
        capability_key="mcp_tool.system.read.regime.current",
        source_type=SourceType.MCP_TOOL,
        source_ref="system.read.regime.current",
        name="system.read.regime.current",
        summary="Governed capability",
        semantic_key="system.read.regime.current",
        execution_target={
            "type": "mcp_capability",
            "tool_name": "agom_capability_call",
            "capability_key": "system.read.regime.current",
            "replacement_for": ["get_current_regime"],
        },
        requires_mcp=True,
        enabled_for_terminal=True,
        enabled_for_agent=True,
        enabled_for_chat=False,
        priority_weight=10.0,
    )


def _governed_write_capability():
    return CapabilityDefinition(
        capability_key="mcp_tool.account.import.positions",
        source_type=SourceType.MCP_TOOL,
        source_ref="account.import.positions",
        name="account.import.positions",
        summary="Governed write capability",
        semantic_key="account.import.positions",
        execution_target={
            "type": "mcp_capability",
            "tool_name": "agom_capability_call",
            "capability_key": "account.import.positions",
            "replacement_for": ["import_positions_json"],
            "audit_tags": ["account:import_positions", "mcp:write"],
        },
        requires_mcp=True,
        requires_confirmation=True,
        enabled_for_terminal=True,
        enabled_for_agent=True,
        enabled_for_chat=False,
        risk_level="medium",
        priority_weight=10.0,
    )


def _legacy_wrapper():
    return CapabilityDefinition(
        capability_key="mcp_tool.get_current_regime",
        source_type=SourceType.MCP_TOOL,
        source_ref="get_current_regime",
        name="get_current_regime",
        summary="Legacy tool",
        semantic_key="system.read.regime.current",
        execution_target={
            "type": "mcp_tool",
            "tool_name": "get_current_regime",
            "legacy": True,
            "replacement_capability_key": "system.read.regime.current",
        },
        requires_mcp=True,
        enabled_for_terminal=False,
        enabled_for_chat=False,
        enabled_for_agent=False,
        priority_weight=0.1,
    )


def _classified_legacy_wrapper():
    return CapabilityDefinition(
        capability_key="mcp_tool.explain_current_regime",
        source_type=SourceType.MCP_TOOL,
        source_ref="explain_current_regime",
        name="explain_current_regime",
        summary="Legacy aggregate tool",
        semantic_key="legacy.mcp.explain_current_regime",
        execution_target={
            "type": "mcp_tool",
            "tool_name": "explain_current_regime",
            "legacy": True,
            "replacement_capability_key": "",
            "legacy_disposition": "aggregate",
            "disposition_reason": "Compose the governed regime read.",
            "recommended_capability_keys": ["system.read.regime.current"],
        },
        requires_mcp=True,
        enabled_for_routing=False,
        enabled_for_terminal=False,
        enabled_for_chat=False,
        enabled_for_agent=False,
        review_status="rejected",
        priority_weight=0.01,
    )


def _aggregate_disposition(**overrides):
    values = {
        "tool_name": "explain_current_regime",
        "owner_app": "regime",
        "disposition": "aggregate",
        "rationale": "Compose the governed regime read.",
        "recommended_capability_keys": ("system.read.regime.current",),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_validate_mcp_catalog_dedup_accepts_governed_and_legacy_pair():
    module = _load_module()

    summary = module.validate_mcp_catalog_dedup([_governed_capability(), _legacy_wrapper()])

    assert summary["governed_capabilities"] == 1
    assert summary["legacy_capabilities"] == 1
    assert summary["replacement_links"] == 1


def test_validate_mcp_catalog_dedup_rejects_missing_replacement_target():
    module = _load_module()
    legacy = _legacy_wrapper()

    with pytest.raises(ValueError, match="points to missing replacement"):
        module.validate_mcp_catalog_dedup([legacy])


def test_validate_mcp_catalog_dedup_rejects_legacy_priority_not_lower():
    module = _load_module()
    legacy = CapabilityDefinition.from_dict(
        {
            **_legacy_wrapper().to_dict(),
            "priority_weight": 11.0,
        }
    )

    with pytest.raises(ValueError, match="must rank below governed replacement"):
        module.validate_mcp_catalog_dedup([_governed_capability(), legacy])


def test_validate_mcp_catalog_dedup_rejects_interactive_legacy_wrapper():
    module = _load_module()
    legacy = CapabilityDefinition.from_dict(
        {
            **_legacy_wrapper().to_dict(),
            "enabled_for_terminal": True,
        }
    )

    with pytest.raises(ValueError, match="must stay hidden"):
        module.validate_mcp_catalog_dedup([_governed_capability(), legacy])


def test_validate_mcp_catalog_dedup_rejects_governed_write_missing_audit_tags():
    module = _load_module()
    broken = CapabilityDefinition.from_dict(
        {
            **_governed_write_capability().to_dict(),
            "execution_target": {
                **_governed_write_capability().execution_target,
                "audit_tags": [],
            },
        }
    )

    with pytest.raises(ValueError, match="missing synced audit_tags"):
        module.validate_mcp_catalog_dedup([broken])


def test_validate_mcp_governance_baseline_rejects_stale_counter():
    module = _load_module()
    actual = {
        "legacy_capability_count": 10,
        "replacement_link_count": 8,
        "legacy_without_replacement_count": 2,
    }

    with pytest.raises(ValueError, match="replacement_link_count"):
        module.validate_mcp_governance_baseline(
            actual,
            {**actual, "replacement_link_count": 7},
        )


def test_validate_legacy_disposition_coverage_accepts_exact_partition():
    module = _load_module()

    summary = module.validate_legacy_disposition_coverage(
        [_governed_capability(), _classified_legacy_wrapper()],
        dispositions=[_aggregate_disposition()],
    )

    assert summary == {
        "legacy_disposition_count": 1,
        "legacy_keep_task_count": 0,
        "legacy_unclassified_count": 0,
    }


def test_validate_legacy_disposition_coverage_honors_explicit_empty_registry():
    module = _load_module()

    with pytest.raises(ValueError, match="coverage mismatch"):
        module.validate_legacy_disposition_coverage(
            [_governed_capability(), _classified_legacy_wrapper()],
            dispositions=[],
        )


def test_validate_legacy_disposition_coverage_rejects_missing_recommendation():
    module = _load_module()
    legacy = CapabilityDefinition.from_dict(
        {
            **_classified_legacy_wrapper().to_dict(),
            "execution_target": {
                **_classified_legacy_wrapper().execution_target,
                "recommended_capability_keys": ["regime.read.missing"],
            },
        }
    )

    with pytest.raises(ValueError, match="recommends missing governed capabilities"):
        module.validate_legacy_disposition_coverage(
            [_governed_capability(), legacy],
            dispositions=[
                _aggregate_disposition(
                    recommended_capability_keys=("regime.read.missing",)
                )
            ],
        )
