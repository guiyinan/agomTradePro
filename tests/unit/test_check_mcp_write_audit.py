"""Tests for the MCP write-audit validation script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "check_mcp_write_audit.py"
    spec = importlib.util.spec_from_file_location("check_mcp_write_audit", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest(
    capability_key: str,
    *,
    risk_level: str = "low",
    audit_tags: tuple[str, ...] = (),
):
    return CapabilityManifest(
        capability_key=capability_key,
        title="Test",
        summary="Test",
        description="Test",
        owner_app="test",
        risk_level=risk_level,
        executor_kind="legacy_tool",
        executor_ref="test_tool",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        idempotency="required",
        confirmation_preview_arguments={"dry_run": True},
        confirmation_commit_arguments={"dry_run": False},
        audit_tags=audit_tags,
    )


def test_validate_write_audit_accepts_read_only_manifests():
    module = _load_module()

    summary = module.validate_write_audit_manifests(
        [_manifest("pulse.read.current", risk_level="low")]
    )

    assert summary["validated_write_like_manifests"] == 0


def test_validate_write_audit_rejects_missing_audit_tags():
    module = _load_module()

    with pytest.raises(ValueError, match="must declare audit_tags"):
        module.validate_write_audit_manifests(
            [_manifest("strategy.update.enabled_state", risk_level="high", audit_tags=())]
        )


def test_validate_write_audit_rejects_unscoped_audit_tags():
    module = _load_module()

    with pytest.raises(ValueError, match="must contain scoped tags"):
        module.validate_write_audit_manifests(
            [
                _manifest(
                    "strategy.update.enabled_state",
                    risk_level="high",
                    audit_tags=("write",),
                )
            ]
        )


def test_validate_write_audit_accepts_scoped_audit_tags():
    module = _load_module()

    summary = module.validate_write_audit_manifests(
        [
            _manifest(
                "account.import.positions",
                risk_level="medium",
                audit_tags=("account:import_positions", "mcp:write"),
            )
        ]
    )

    assert summary["validated_write_like_manifests"] == 1


def test_validate_write_audit_treats_rollback_action_as_write_like():
    module = _load_module()

    summary = module.validate_write_audit_manifests(
        [
            _manifest(
                "policy.rollback.workbench_event",
                risk_level="high",
                audit_tags=("policy:rollback_workbench_event", "mcp:write"),
            )
        ]
    )

    assert summary["validated_write_like_manifests"] == 1


def test_validate_write_audit_treats_override_action_as_write_like():
    module = _load_module()

    summary = module.validate_write_audit_manifests(
        [
            _manifest(
                "policy.override.workbench_event",
                risk_level="high",
                audit_tags=("policy:override_workbench_event", "mcp:write"),
            )
        ]
    )

    assert summary["validated_write_like_manifests"] == 1
