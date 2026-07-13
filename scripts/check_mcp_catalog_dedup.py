#!/usr/bin/env python
"""Validate MCP catalog dedup and legacy replacement invariants."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
GOVERNANCE_BASELINE_PATH = REPO_ROOT / "governance" / "governance_baseline.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))


def setup_django() -> None:
    """Initialize Django so application-layer sync code can be imported safely."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
    import django

    django.setup()


def collect_mcp_sync_capabilities():
    """Collect the in-memory MCP capability set used by catalog sync."""
    setup_django()
    from apps.ai_capability.application.use_cases import SyncCapabilitiesUseCase

    return SyncCapabilitiesUseCase()._sync_mcp_tools()


def validate_mcp_catalog_dedup(capabilities) -> dict[str, int]:
    """Validate governed/legacy MCP capability dedup and replacement invariants."""
    from apps.ai_capability.domain.services import CapabilitySemanticDeduper

    governed = [
        cap
        for cap in capabilities
        if (cap.execution_target or {}).get("type") == "mcp_capability"
    ]
    legacy = [
        cap
        for cap in capabilities
        if (cap.execution_target or {}).get("type") == "mcp_tool"
    ]

    governed_by_catalog_key = {cap.capability_key: cap for cap in governed}
    governed_semantic_keys: set[str] = set()
    for cap in governed:
        semantic_key = cap.semantic_key.strip()
        if not semantic_key:
            raise ValueError(f"Governed MCP capability missing semantic_key: {cap.capability_key}")
        if semantic_key in governed_semantic_keys:
            raise ValueError(
                f"Duplicate governed MCP semantic_key detected: {semantic_key}"
            )
        governed_semantic_keys.add(semantic_key)
        execution_target = cap.execution_target or {}
        audit_tags = list(execution_target.get("audit_tags") or [])
        looks_write_like = bool(cap.requires_confirmation) or cap.risk_level.value in {
            "high",
            "medium",
            "write_high",
            "write_low",
        }
        if looks_write_like and not audit_tags:
            raise ValueError(
                f"Governed MCP capability missing synced audit_tags: {cap.capability_key}"
            )

    replacement_count = 0
    for cap in legacy:
        target = cap.execution_target or {}
        replacement_capability_key = str(target.get("replacement_capability_key") or "").strip()
        if not replacement_capability_key:
            continue
        replacement_count += 1
        governed_catalog_key = f"mcp_tool.{replacement_capability_key}"
        replacement = governed_by_catalog_key.get(governed_catalog_key)
        if replacement is None:
            raise ValueError(
                f"Legacy tool {cap.capability_key} points to missing replacement "
                f"{replacement_capability_key}"
            )
        if cap.semantic_key != replacement_capability_key:
            raise ValueError(
                f"Legacy tool {cap.capability_key} semantic_key must equal replacement "
                f"{replacement_capability_key}"
            )
        if cap.priority_weight >= replacement.priority_weight:
            raise ValueError(
                f"Legacy tool {cap.capability_key} must rank below governed replacement "
                f"{replacement.capability_key}"
            )
        if cap.enabled_for_terminal or cap.enabled_for_chat or cap.enabled_for_agent:
            raise ValueError(
                f"Legacy replacement wrapper must stay hidden from interactive MCP surfaces: "
                f"{cap.capability_key}"
            )
        replacement_for = list((replacement.execution_target or {}).get("replacement_for") or [])
        if cap.source_ref not in replacement_for:
            raise ValueError(
                f"Governed replacement {replacement.capability_key} must declare replacement_for "
                f"{cap.source_ref}"
            )

    deduper = CapabilitySemanticDeduper()
    semantic_groups: dict[str, list] = {}
    for cap in capabilities:
        semantic_key = cap.semantic_key.strip()
        if semantic_key:
            semantic_groups.setdefault(semantic_key, []).append(cap)

    checked_semantic_groups = 0
    for semantic_key, group in semantic_groups.items():
        if len(group) < 2:
            continue
        checked_semantic_groups += 1
        result = deduper.deduplicate(group, entrypoint="terminal")
        if len(result) != 1:
            raise ValueError(
                f"Terminal dedup must select exactly one capability for semantic_key {semantic_key}"
            )
        selected = result[0]
        selected_target = selected.execution_target or {}
        if any(
            str((cap.execution_target or {}).get("replacement_capability_key") or "").strip()
            == semantic_key
            for cap in group
        ):
            if selected_target.get("type") != "mcp_capability":
                raise ValueError(
                    f"Terminal dedup must prefer governed MCP capability for semantic_key "
                    f"{semantic_key}"
                )

    return {
        "total_capabilities": len(capabilities),
        "governed_capabilities": len(governed),
        "legacy_capabilities": len(legacy),
        "replacement_links": replacement_count,
        "checked_semantic_groups": checked_semantic_groups,
    }


def validate_legacy_disposition_coverage(
    capabilities,
    *,
    dispositions=None,
) -> dict[str, int]:
    """Require every unreplaced raw tool to have one enforced disposition."""

    from agomtradepro.unsupported_legacy_contracts import (
        get_unsupported_legacy_contract_for_tool,
    )
    from agomtradepro_mcp.legacy_dispositions import (
        list_legacy_tool_dispositions,
    )

    records = list(
        list_legacy_tool_dispositions() if dispositions is None else dispositions
    )
    by_tool_name = {record.tool_name: record for record in records}
    if len(by_tool_name) != len(records):
        raise ValueError("Duplicate legacy MCP disposition tool_name detected")

    governed_keys = {
        cap.source_ref
        for cap in capabilities
        if (cap.execution_target or {}).get("type") == "mcp_capability"
    }
    unreplaced = {
        cap.source_ref: cap
        for cap in capabilities
        if (cap.execution_target or {}).get("type") == "mcp_tool"
        and not str(
            (cap.execution_target or {}).get("replacement_capability_key") or ""
        ).strip()
    }
    missing = sorted(set(unreplaced) - set(by_tool_name))
    extra = sorted(set(by_tool_name) - set(unreplaced))
    if missing or extra:
        raise ValueError(
            "Legacy MCP disposition coverage mismatch: "
            f"missing={missing}, extra={extra}"
        )

    keep_task_count = 0
    for tool_name, cap in unreplaced.items():
        record = by_tool_name[tool_name]
        target = cap.execution_target or {}
        if target.get("legacy_disposition") != record.disposition:
            raise ValueError(
                f"Legacy tool {tool_name} catalog disposition does not match registry"
            )
        if target.get("disposition_reason") != record.rationale:
            raise ValueError(
                f"Legacy tool {tool_name} catalog rationale does not match registry"
            )
        recommended = list(record.recommended_capability_keys)
        if list(target.get("recommended_capability_keys") or []) != recommended:
            raise ValueError(
                f"Legacy tool {tool_name} catalog recommendations do not match registry"
            )
        missing_recommendations = sorted(set(recommended) - governed_keys)
        if missing_recommendations:
            raise ValueError(
                f"Legacy tool {tool_name} recommends missing governed capabilities: "
                f"{missing_recommendations}"
            )
        if cap.enabled_for_routing:
            raise ValueError(
                f"Classified legacy tool {tool_name} must not be enabled for routing"
            )
        if record.disposition == "unsupported":
            if get_unsupported_legacy_contract_for_tool(tool_name) is None:
                raise ValueError(
                    f"Unsupported legacy tool {tool_name} is absent from the contract registry"
                )
        if record.disposition == "keep_task":
            keep_task_count += 1

    return {
        "legacy_disposition_count": len(records),
        "legacy_keep_task_count": keep_task_count,
        "legacy_unclassified_count": 0,
    }


def collect_mcp_governance_metrics(
    capabilities,
    *,
    dedup_summary: dict[str, int],
) -> dict[str, int]:
    """Measure every MCP governance counter stored in the machine baseline."""

    from agomtradepro.unsupported_legacy_contracts import (
        list_unsupported_legacy_contracts,
    )
    from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
    from agomtradepro_mcp.tools.core_tools import CORE_TOOL_NAMES

    from scripts.check_mcp_write_evidence import is_write_like_manifest

    manifests = CapabilityRegistryLoader().load_manifests()
    write_count = sum(1 for manifest in manifests if is_write_like_manifest(manifest))
    legacy_count = dedup_summary["legacy_capabilities"]
    replacement_count = dedup_summary["replacement_links"]
    disposition_summary = validate_legacy_disposition_coverage(capabilities)
    return {
        "default_top_level_tool_count": len(CORE_TOOL_NAMES),
        "governed_manifest_count": len(manifests),
        "governed_read_capability_count": len(manifests) - write_count,
        "governed_write_like_capability_count": write_count,
        "catalog_candidate_count": len(capabilities),
        "legacy_capability_count": legacy_count,
        "replacement_link_count": replacement_count,
        "legacy_without_replacement_count": legacy_count - replacement_count,
        **disposition_summary,
        "unsupported_legacy_contract_count": len(list_unsupported_legacy_contracts()),
        "raw_tool_file_count": len(
            list((SDK_ROOT / "agomtradepro_mcp" / "tools").glob("*_tools.py"))
        ),
    }


def validate_mcp_governance_baseline(
    actual: dict[str, int],
    expected: dict[str, int],
) -> None:
    """Reject stale, missing, or extra MCP counters in the machine baseline."""

    if actual == expected:
        return
    details = []
    for key in sorted(set(actual) | set(expected)):
        if actual.get(key) != expected.get(key):
            details.append(
                f"{key}: actual={actual.get(key)!r}, baseline={expected.get(key)!r}"
            )
    raise ValueError("MCP governance baseline mismatch:\n- " + "\n- ".join(details))


def main() -> int:
    """CLI entrypoint for MCP catalog dedup validation."""
    parser = argparse.ArgumentParser(
        description="Validate MCP catalog dedup and legacy replacement invariants.",
    )
    parser.parse_args()

    capabilities = collect_mcp_sync_capabilities()
    summary = validate_mcp_catalog_dedup(capabilities)
    disposition_summary = validate_legacy_disposition_coverage(capabilities)
    baseline = json.loads(GOVERNANCE_BASELINE_PATH.read_text(encoding="utf-8"))
    governance_metrics = collect_mcp_governance_metrics(
        capabilities,
        dedup_summary=summary,
    )
    validate_mcp_governance_baseline(
        governance_metrics,
        baseline["mcp_governance"],
    )
    print("MCP catalog dedup OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    print("Legacy MCP dispositions OK")
    for key, value in disposition_summary.items():
        print(f"- {key}: {value}")
    print("MCP governance baseline OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
