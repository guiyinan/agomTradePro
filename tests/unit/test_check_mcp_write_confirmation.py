"""Tests for the MCP write-confirmation validation script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "check_mcp_write_confirmation.py"
    spec = importlib.util.spec_from_file_location("check_mcp_write_confirmation", module_path)
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
    requires_confirmation: bool = False,
    idempotency: str = "none",
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
        requires_confirmation=requires_confirmation,
        idempotency=idempotency,
        audit_tags=("test:write",),
    )


def test_collect_manifests_reads_current_registry():
    module = _load_module()

    manifests = module.collect_manifests()

    assert any(item.capability_key == "system.read.regime.current" for item in manifests)


def test_validate_write_confirmation_accepts_read_only_manifests():
    module = _load_module()

    summary = module.validate_write_confirmation_manifests(
        [_manifest("pulse.read.current", risk_level="low", requires_confirmation=False)]
    )

    assert summary["write_like_manifests"] == 0
    assert summary["higher_risk_manifests"] == 0
    assert summary["required_idempotency_manifests"] == 0


def test_validate_write_confirmation_rejects_write_like_manifest_without_confirmation():
    module = _load_module()

    with pytest.raises(ValueError, match="must require confirmation"):
        module.validate_write_confirmation_manifests(
            [
                _manifest(
                    "strategy.update.enabled_state",
                    risk_level="low",
                    requires_confirmation=False,
                    idempotency="required",
                )
            ]
        )


def test_validate_write_confirmation_accepts_sensitive_read_without_confirmation():
    module = _load_module()

    summary = module.validate_write_confirmation_manifests(
        [
            _manifest(
                "system.read.audit",
                risk_level="high",
                requires_confirmation=False,
                idempotency="none",
            )
        ]
    )

    assert summary["write_like_manifests"] == 0
    assert summary["higher_risk_manifests"] == 0
    assert summary["required_idempotency_manifests"] == 0


def test_validate_write_confirmation_rejects_write_like_manifest_without_required_idempotency():
    module = _load_module()

    with pytest.raises(ValueError, match="must require idempotency"):
        module.validate_write_confirmation_manifests(
            [
                _manifest(
                    "strategy.update.enabled_state",
                    risk_level="high",
                    requires_confirmation=True,
                    idempotency="none",
                )
            ]
        )


def test_validate_write_confirmation_accepts_write_like_manifest_with_confirmation():
    module = _load_module()

    summary = module.validate_write_confirmation_manifests(
        [
            _manifest(
                "strategy.update.enabled_state",
                risk_level="high",
                requires_confirmation=True,
                idempotency="required",
            )
        ]
    )

    assert summary["write_like_manifests"] == 1
    assert summary["higher_risk_manifests"] == 1
    assert summary["required_idempotency_manifests"] == 1


def test_validate_write_confirmation_treats_bind_action_as_write_like():
    module = _load_module()

    summary = module.validate_write_confirmation_manifests(
        [
            _manifest(
                "strategy.bind.portfolio",
                risk_level="high",
                requires_confirmation=True,
                idempotency="required",
            )
        ]
    )

    assert summary["write_like_manifests"] == 1
    assert summary["higher_risk_manifests"] == 1
    assert summary["required_idempotency_manifests"] == 1


def test_validate_write_confirmation_treats_apply_template_action_as_write_like():
    module = _load_module()

    summary = module.validate_write_confirmation_manifests(
        [
            _manifest(
                "rotation.apply_template.account_config",
                risk_level="high",
                requires_confirmation=True,
                idempotency="required",
            )
        ]
    )

    assert summary["write_like_manifests"] == 1
    assert summary["higher_risk_manifests"] == 1
    assert summary["required_idempotency_manifests"] == 1


def test_validate_write_confirmation_treats_rollback_action_as_write_like():
    module = _load_module()

    summary = module.validate_write_confirmation_manifests(
        [
            _manifest(
                "policy.rollback.workbench_event",
                risk_level="high",
                requires_confirmation=True,
                idempotency="required",
            )
        ]
    )

    assert summary["write_like_manifests"] == 1
    assert summary["higher_risk_manifests"] == 1
    assert summary["required_idempotency_manifests"] == 1


def test_validate_write_confirmation_treats_override_action_as_write_like():
    module = _load_module()

    summary = module.validate_write_confirmation_manifests(
        [
            _manifest(
                "policy.override.workbench_event",
                risk_level="high",
                requires_confirmation=True,
                idempotency="required",
            )
        ]
    )

    assert summary["write_like_manifests"] == 1
    assert summary["higher_risk_manifests"] == 1
    assert summary["required_idempotency_manifests"] == 1


def test_validate_write_confirmation_treats_clear_action_as_write_like():
    module = _load_module()

    summary = module.validate_write_confirmation_manifests(
        [
            _manifest(
                "sentiment.clear.cache",
                risk_level="high",
                requires_confirmation=True,
                idempotency="required",
            )
        ]
    )

    assert summary["write_like_manifests"] == 1
    assert summary["higher_risk_manifests"] == 1
    assert summary["required_idempotency_manifests"] == 1
