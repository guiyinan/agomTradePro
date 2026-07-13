#!/usr/bin/env python
"""Validate that governed write-like MCP capabilities expose real preview semantics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
for search_root in (REPO_ROOT, SDK_ROOT):
    if str(search_root) not in sys.path:
        sys.path.insert(0, str(search_root))

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

from scripts.check_mcp_write_evidence import is_write_like_manifest

KNOWN_PREVIEW_CONTROLS = frozenset({"dry_run", "create_request", "preview_only", "commit"})


def collect_manifests(loader: CapabilityRegistryLoader | None = None):
    """Load all configured MCP capability manifests."""
    active_loader = loader or CapabilityRegistryLoader()
    return active_loader.load_manifests()


def validate_write_preview_manifests(manifests) -> dict[str, int]:
    """Reject governed write-like manifests that do not expose preview-first semantics."""
    total = len(manifests)
    validated = 0

    for manifest in manifests:
        write_candidate = is_write_like_manifest(manifest)
        if not write_candidate:
            continue

        validated += 1
        preview_args = dict(getattr(manifest, "confirmation_preview_arguments", {}) or {})
        commit_args = dict(getattr(manifest, "confirmation_commit_arguments", {}) or {})
        if not preview_args:
            raise ValueError(
                "Governed MCP write-like capability must declare confirmation_preview_arguments: "
                f"{manifest.capability_key}"
            )
        if not commit_args:
            raise ValueError(
                "Governed MCP write-like capability must declare confirmation_commit_arguments: "
                f"{manifest.capability_key}"
            )

        changed_keys = {
            key
            for key in set(preview_args) | set(commit_args)
            if preview_args.get(key) != commit_args.get(key)
        }
        if not changed_keys:
            raise ValueError(
                "Governed MCP write-like capability must change arguments between preview and commit: "
                f"{manifest.capability_key}"
            )

        if "dry_run" in preview_args or "dry_run" in commit_args:
            if preview_args.get("dry_run") is not True or commit_args.get("dry_run") is not False:
                raise ValueError(
                    "Governed MCP write-like capability using dry_run must stage True -> False: "
                    f"{manifest.capability_key}"
                )

        if "create_request" in preview_args or "create_request" in commit_args:
            if (
                preview_args.get("create_request") is not False
                or commit_args.get("create_request") is not True
            ):
                raise ValueError(
                    "Governed MCP write-like capability using create_request must stage False -> True: "
                    f"{manifest.capability_key}"
                )

        if not (KNOWN_PREVIEW_CONTROLS & changed_keys):
            raise ValueError(
                "Governed MCP write-like capability must expose an explicit preview control key: "
                f"{manifest.capability_key}"
            )

    return {
        "total_manifests": total,
        "validated_write_like_manifests": validated,
    }


def main() -> int:
    """CLI entrypoint for MCP write-preview validation."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate that governed write-like MCP capabilities expose preview-first "
            "confirmation semantics."
        ),
    )
    parser.parse_args()

    manifests = collect_manifests()
    summary = validate_write_preview_manifests(manifests)
    print("MCP write-preview guard OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
