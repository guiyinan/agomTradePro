#!/usr/bin/env python
"""Validate that governed write-like MCP capabilities carry audit metadata."""

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


def collect_manifests(loader: CapabilityRegistryLoader | None = None):
    """Load all configured MCP capability manifests."""
    active_loader = loader or CapabilityRegistryLoader()
    return active_loader.load_manifests()


def validate_write_audit_manifests(manifests) -> dict[str, int]:
    """Reject governed write-like manifests that do not carry explicit audit tags."""
    total = len(manifests)
    validated = 0

    for manifest in manifests:
        write_candidate = is_write_like_manifest(manifest)
        if not write_candidate:
            continue

        validated += 1
        audit_tags = tuple(getattr(manifest, "audit_tags", ()) or ())
        if not audit_tags:
            raise ValueError(
                "Governed MCP write-like capability must declare audit_tags: "
                f"{manifest.capability_key}"
            )
        if any(not isinstance(tag, str) or not tag.strip() for tag in audit_tags):
            raise ValueError(
                "Governed MCP write-like capability audit_tags must be non-empty strings: "
                f"{manifest.capability_key}"
            )
        if not any(":" in tag for tag in audit_tags):
            raise ValueError(
                "Governed MCP write-like capability audit_tags must contain scoped tags: "
                f"{manifest.capability_key}"
            )

    return {
        "total_manifests": total,
        "validated_write_like_manifests": validated,
    }


def main() -> int:
    """CLI entrypoint for MCP write-audit validation."""
    parser = argparse.ArgumentParser(
        description=("Validate that governed write-like MCP capabilities declare audit_tags."),
    )
    parser.parse_args()

    manifests = collect_manifests()
    summary = validate_write_audit_manifests(manifests)
    print("MCP write-audit guard OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
