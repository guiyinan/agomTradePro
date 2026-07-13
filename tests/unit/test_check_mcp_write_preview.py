"""Tests for the MCP write-preview validation script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "check_mcp_write_preview.py"
    spec = importlib.util.spec_from_file_location("check_mcp_write_preview", module_path)
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
    preview_args: dict | None = None,
    commit_args: dict | None = None,
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
        confirmation_preview_arguments=preview_args or {},
        confirmation_commit_arguments=commit_args or {},
        audit_tags=("test:write",),
    )


def test_validate_write_preview_accepts_read_only_manifests():
    module = _load_module()

    summary = module.validate_write_preview_manifests(
        [_manifest("pulse.read.current", risk_level="low")]
    )

    assert summary["validated_write_like_manifests"] == 0


def test_validate_write_preview_rejects_missing_preview_args():
    module = _load_module()

    with pytest.raises(ValueError, match="confirmation_preview_arguments"):
        module.validate_write_preview_manifests(
            [
                _manifest(
                    "strategy.update.enabled_state",
                    risk_level="high",
                    preview_args={},
                    commit_args={"dry_run": False},
                )
            ]
        )


def test_validate_write_preview_rejects_missing_commit_args():
    module = _load_module()

    with pytest.raises(ValueError, match="confirmation_commit_arguments"):
        module.validate_write_preview_manifests(
            [
                _manifest(
                    "strategy.update.enabled_state",
                    risk_level="high",
                    preview_args={"dry_run": True},
                    commit_args={},
                )
            ]
        )


def test_validate_write_preview_rejects_unchanged_preview_commit_args():
    module = _load_module()

    with pytest.raises(ValueError, match="change arguments between preview and commit"):
        module.validate_write_preview_manifests(
            [
                _manifest(
                    "strategy.update.enabled_state",
                    risk_level="high",
                    preview_args={"dry_run": True},
                    commit_args={"dry_run": True},
                )
            ]
        )


def test_validate_write_preview_rejects_missing_explicit_preview_control():
    module = _load_module()

    with pytest.raises(ValueError, match="explicit preview control key"):
        module.validate_write_preview_manifests(
            [
                _manifest(
                    "strategy.update.enabled_state",
                    risk_level="high",
                    preview_args={"mode": "preview"},
                    commit_args={"mode": "commit"},
                )
            ]
        )


def test_validate_write_preview_accepts_dry_run_transition():
    module = _load_module()

    summary = module.validate_write_preview_manifests(
        [
            _manifest(
                "account.import.positions",
                risk_level="medium",
                preview_args={"dry_run": True},
                commit_args={"dry_run": False},
            )
        ]
    )

    assert summary["validated_write_like_manifests"] == 1


def test_validate_write_preview_accepts_create_request_transition():
    module = _load_module()

    summary = module.validate_write_preview_manifests(
        [
            _manifest(
                "decision.create.execution_request",
                risk_level="medium",
                preview_args={"create_request": False},
                commit_args={"create_request": True},
            )
        ]
    )

    assert summary["validated_write_like_manifests"] == 1


def test_validate_write_preview_accepts_rollback_preview_transition():
    module = _load_module()

    summary = module.validate_write_preview_manifests(
        [
            _manifest(
                "policy.rollback.workbench_event",
                risk_level="high",
                preview_args={"preview_only": True},
                commit_args={"preview_only": False},
            )
        ]
    )

    assert summary["validated_write_like_manifests"] == 1


def test_validate_write_preview_accepts_override_preview_transition():
    module = _load_module()

    summary = module.validate_write_preview_manifests(
        [
            _manifest(
                "policy.override.workbench_event",
                risk_level="high",
                preview_args={"preview_only": True},
                commit_args={"preview_only": False},
            )
        ]
    )

    assert summary["validated_write_like_manifests"] == 1
