#!/usr/bin/env python
"""Validate that governed write-like MCP capabilities require confirmation and idempotency."""

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

HIGHER_RISK_LEVELS = frozenset(
    {
        "admin",
        "critical",
        "high",
        "medium",
        "write_high",
        "write_low",
    }
)


def collect_manifests(loader: CapabilityRegistryLoader | None = None):
    """Load all configured MCP capability manifests."""
    active_loader = loader or CapabilityRegistryLoader()
    return active_loader.load_manifests()


def validate_write_confirmation_manifests(manifests) -> dict[str, int]:
    """Reject write-like manifests that skip confirmation or required idempotency."""
    total = len(manifests)
    write_like = 0
    higher_risk = 0
    required_idempotency = 0

    for manifest in manifests:
        risk_level = str(getattr(manifest, "risk_level", "") or "").strip().lower()
        write_candidate = is_write_like_manifest(manifest)
        if not write_candidate:
            continue

        write_like += 1
        if risk_level in HIGHER_RISK_LEVELS:
            higher_risk += 1
        if not bool(getattr(manifest, "requires_confirmation", False)):
            raise ValueError(
                "Governed MCP write-like capability must require confirmation: "
                f"{manifest.capability_key}"
            )
        if str(getattr(manifest, "idempotency", "none") or "").strip().lower() != "required":
            raise ValueError(
                "Governed MCP write-like capability must require idempotency: "
                f"{manifest.capability_key}"
            )
        required_idempotency += 1

    return {
        "total_manifests": total,
        "write_like_manifests": write_like,
        "higher_risk_manifests": higher_risk,
        "required_idempotency_manifests": required_idempotency,
    }


def main() -> int:
    """CLI entrypoint for MCP write-confirmation validation."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate that governed write-like MCP capabilities require confirmation "
            "and required idempotency."
        ),
    )
    parser.parse_args()

    manifests = collect_manifests()
    summary = validate_write_confirmation_manifests(manifests)
    print("MCP write-confirmation guard OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
