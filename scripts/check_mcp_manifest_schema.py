#!/usr/bin/env python
"""Validate MCP capability manifests and registry structure."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def collect_manifest_keys(loader: CapabilityRegistryLoader | None = None) -> list[str]:
    """Load manifests and return their capability keys in sorted order."""
    active_loader = loader or CapabilityRegistryLoader()
    manifests = active_loader.load_manifests()
    return sorted(manifest.capability_key for manifest in manifests)


def validate_manifest_registry(loader: CapabilityRegistryLoader | None = None) -> list[str]:
    """Validate manifest loading and registry indexing integrity."""
    active_loader = loader or CapabilityRegistryLoader()
    manifests = active_loader.load_manifests()
    registry = active_loader.build_registry()
    if len(manifests) != len(registry):
        raise ValueError(
            "Capability registry size mismatch: "
            f"{len(manifests)} manifests vs {len(registry)} registry entries"
        )
    return sorted(registry)


def main() -> int:
    """CLI entrypoint for MCP manifest validation."""
    parser = argparse.ArgumentParser(
        description="Validate MCP capability manifests and registry structure.",
    )
    parser.parse_args()

    capability_keys = validate_manifest_registry()
    print(f"MCP manifest registry OK: {len(capability_keys)} capabilities")
    for key in capability_keys:
        print(f"- {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
