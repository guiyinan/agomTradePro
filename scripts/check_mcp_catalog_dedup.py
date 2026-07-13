#!/usr/bin/env python
"""Validate MCP catalog dedup and legacy replacement invariants."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
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


def main() -> int:
    """CLI entrypoint for MCP catalog dedup validation."""
    parser = argparse.ArgumentParser(
        description="Validate MCP catalog dedup and legacy replacement invariants.",
    )
    parser.parse_args()

    capabilities = collect_mcp_sync_capabilities()
    summary = validate_mcp_catalog_dedup(capabilities)
    print("MCP catalog dedup OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
