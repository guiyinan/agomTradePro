"""Tests for the MCP manifest schema validation script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.registry.manifest import (
    CapabilityManifest,
    CapabilityManifestValidationError,
)


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "check_mcp_manifest_schema.py"
    spec = importlib.util.spec_from_file_location("check_mcp_manifest_schema", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_collect_manifest_keys_includes_seed_capabilities():
    module = _load_module()

    keys = module.collect_manifest_keys()

    assert "system.read.regime.current" in keys
    assert "data_center.read.macro_series" in keys


def test_validate_manifest_registry_rejects_registry_size_mismatch():
    module = _load_module()

    class _BrokenLoader(CapabilityRegistryLoader):
        def load_manifests(self):
            return [
                CapabilityManifest(
                    capability_key="system.read.test",
                    title="Test",
                    summary="Test",
                    description="Test",
                    owner_app="test",
                    risk_level="safe",
                    executor_kind="legacy_tool",
                    executor_ref="get_test",
                    input_schema={"type": "object", "properties": {}, "required": []},
                    output_schema={"type": "object", "properties": {}, "required": []},
                )
            ]

        def build_registry(self):
            return {}

    with pytest.raises(ValueError, match="registry size mismatch"):
        module.validate_manifest_registry(_BrokenLoader(module_paths=()))


def test_validate_manifest_registry_surfaces_manifest_validation_error():
    module = _load_module()

    class _InvalidLoader(CapabilityRegistryLoader):
        def load_manifests(self):
            raise CapabilityManifestValidationError("broken manifest")

    with pytest.raises(CapabilityManifestValidationError, match="broken manifest"):
        module.validate_manifest_registry(_InvalidLoader(module_paths=()))


def test_loader_rejects_manifest_with_invalid_audit_tags():
    loader = CapabilityRegistryLoader(module_paths=())
    manifest = CapabilityManifest(
        capability_key="system.read.test",
        title="Test",
        summary="Test",
        description="Test",
        owner_app="test",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_test",
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
        audit_tags=("valid:tag", ""),
    )

    with pytest.raises(CapabilityManifestValidationError, match="audit_tags entries"):
        loader.validate_manifests([manifest])


def test_loader_requires_complete_deprecated_lifecycle_metadata():
    loader = CapabilityRegistryLoader(module_paths=())
    manifest = CapabilityManifest(
        capability_key="system.read.deprecated-test",
        title="Deprecated Test",
        summary="Deprecated test",
        description="Deprecated test",
        owner_app="test",
        risk_level="safe",
        executor_kind="legacy_tool",
        executor_ref="get_deprecated_test",
        lifecycle_status="deprecated",
    )

    with pytest.raises(
        CapabilityManifestValidationError,
        match="deprecated_since must be a non-empty string",
    ):
        loader.validate_manifests([manifest])


def test_filter_manifests_publish_complete_deprecation_contract():
    manifests = [
        manifest
        for manifest in CapabilityRegistryLoader().load_manifests()
        if manifest.owner_app == "filter"
    ]

    assert len(manifests) == 6
    assert {manifest.lifecycle_status for manifest in manifests} == {"deprecated"}
    assert {manifest.deprecated_since for manifest in manifests} == {"0.8.0"}
    assert {manifest.sunset_on for manifest in manifests} == {"2026-09-30"}
    assert all(manifest.replacement_hint for manifest in manifests)
