"""Capability manifest loading and validation."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any

from .manifest import CapabilityManifest, CapabilityManifestValidationError
from .modules.owners import OWNER_MANIFEST_MODULES

DEFAULT_MANIFEST_MODULES: tuple[str, ...] = (
    *OWNER_MANIFEST_MODULES,
    "agomtradepro_mcp.registry.modules.account_read_capabilities",
    "agomtradepro_mcp.registry.modules.fund_compute_capabilities",
    "agomtradepro_mcp.registry.modules.sector_read_capabilities",
    "agomtradepro_mcp.registry.modules.config_center_read_capabilities",
    "agomtradepro_mcp.registry.modules.audit_write_capabilities",
    "agomtradepro_mcp.registry.modules.alpha_write_capabilities",
)


class CapabilityRegistryLoader:
    """Load capability manifests from a controlled module list."""

    def __init__(self, module_paths: Sequence[str] | None = None) -> None:
        self._module_paths = tuple(module_paths or DEFAULT_MANIFEST_MODULES)

    @property
    def module_paths(self) -> tuple[str, ...]:
        """Return configured module paths."""
        return self._module_paths

    def load_manifests(self) -> list[CapabilityManifest]:
        """Import configured modules and return validated manifests."""
        manifests: list[CapabilityManifest] = []
        for module_path in self._module_paths:
            module = importlib.import_module(module_path)
            raw_items = getattr(module, "MANIFESTS", None)
            if raw_items is None:
                raise CapabilityManifestValidationError(
                    f"Manifest module {module_path} is missing MANIFESTS"
                )
            if not isinstance(raw_items, Sequence):
                raise CapabilityManifestValidationError(
                    f"Manifest module {module_path} must expose MANIFESTS as a sequence"
                )
            for item in raw_items:
                if not isinstance(item, CapabilityManifest):
                    raise CapabilityManifestValidationError(
                        f"Manifest module {module_path} contains a non-manifest item: {type(item)!r}"
                    )
                manifests.append(item)
        self.validate_manifests(manifests)
        return manifests

    def validate_manifests(self, manifests: Sequence[CapabilityManifest]) -> None:
        """Validate uniqueness and required structural fields."""
        seen_keys: set[str] = set()
        for manifest in manifests:
            self._validate_manifest(manifest)
            if manifest.capability_key in seen_keys:
                raise CapabilityManifestValidationError(
                    f"Duplicate capability_key detected: {manifest.capability_key}"
                )
            seen_keys.add(manifest.capability_key)

    def build_registry(self) -> dict[str, CapabilityManifest]:
        """Return a capability-key indexed registry."""
        manifests = self.load_manifests()
        return {manifest.capability_key: manifest for manifest in manifests}

    def _validate_manifest(self, manifest: CapabilityManifest) -> None:
        required_strings = {
            "capability_key": manifest.capability_key,
            "title": manifest.title,
            "summary": manifest.summary,
            "description": manifest.description,
            "owner_app": manifest.owner_app,
            "risk_level": manifest.risk_level,
            "executor_kind": manifest.executor_kind,
            "executor_ref": manifest.executor_ref,
        }
        for field_name, value in required_strings.items():
            if not isinstance(value, str) or not value.strip():
                raise CapabilityManifestValidationError(
                    f"Capability manifest field {field_name} must be a non-empty string"
                )

        if not isinstance(manifest.input_schema, dict):
            raise CapabilityManifestValidationError("input_schema must be a dict")
        if not isinstance(manifest.output_schema, dict):
            raise CapabilityManifestValidationError("output_schema must be a dict")
        if not isinstance(manifest.confirmation_preview_arguments, dict):
            raise CapabilityManifestValidationError("confirmation_preview_arguments must be a dict")
        if not isinstance(manifest.confirmation_commit_arguments, dict):
            raise CapabilityManifestValidationError("confirmation_commit_arguments must be a dict")
        if not isinstance(manifest.audit_tags, tuple):
            raise CapabilityManifestValidationError("audit_tags must be a tuple")
        if any(not isinstance(tag, str) or not tag.strip() for tag in manifest.audit_tags):
            raise CapabilityManifestValidationError("audit_tags entries must be non-empty strings")
        if manifest.idempotency not in {"none", "recommended", "required"}:
            raise CapabilityManifestValidationError(
                f"Unsupported idempotency policy: {manifest.idempotency}"
            )
        if (
            not isinstance(manifest.idempotency_argument_name, str)
            or not manifest.idempotency_argument_name.strip()
        ):
            raise CapabilityManifestValidationError(
                "idempotency_argument_name must be a non-empty string"
            )
        if manifest.executor_kind not in {"legacy_tool", "internal_handler"}:
            raise CapabilityManifestValidationError(
                f"Unsupported executor_kind: {manifest.executor_kind}"
            )
        if manifest.lifecycle_status not in {"active", "deprecated", "sunset"}:
            raise CapabilityManifestValidationError(
                f"Unsupported lifecycle_status: {manifest.lifecycle_status}"
            )
        if manifest.lifecycle_status != "active":
            lifecycle_strings = {
                "deprecated_since": manifest.deprecated_since,
                "sunset_on": manifest.sunset_on,
                "replacement_hint": manifest.replacement_hint,
            }
            for field_name, value in lifecycle_strings.items():
                if not isinstance(value, str) or not value.strip():
                    raise CapabilityManifestValidationError(
                        f"Deprecated capability field {field_name} must be a non-empty string"
                    )

        self._validate_schema(manifest.input_schema, "input_schema")
        self._validate_schema(manifest.output_schema, "output_schema")

    def _validate_schema(self, schema: dict[str, Any], schema_name: str) -> None:
        if not schema:
            return
        schema_type = schema.get("type")
        if schema_type != "object":
            raise CapabilityManifestValidationError(
                f"{schema_name} must be a JSON-schema object with type=object"
            )
        properties = schema.get("properties", {})
        if properties and not isinstance(properties, dict):
            raise CapabilityManifestValidationError(
                f"{schema_name}.properties must be a dict when present"
            )
