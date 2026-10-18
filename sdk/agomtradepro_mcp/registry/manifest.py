"""Manifest definitions for MCP capability registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CapabilityManifestValidationError(ValueError):
    """Raised when a capability manifest violates registry rules."""


def _is_supported_integer_array_schema(schema: object) -> bool:
    """Return whether a schema declares an integer array, optionally nullable."""

    if type(schema) is not dict:
        return False
    schema_type = schema.get("type")
    valid_array_type = schema_type == "array" or (
        type(schema_type) is list
        and all(type(item) is str for item in schema_type)
        and len(schema_type) == 2
        and set(schema_type) == {"array", "null"}
    )
    items = schema.get("items")
    return valid_array_type and type(items) is dict and items.get("type") == "integer"


@dataclass(frozen=True)
class CapabilityManifest:
    """Stable capability contract exposed through MCP core tools."""

    capability_key: str
    title: str
    summary: str
    description: str
    owner_app: str
    risk_level: str
    executor_kind: str
    executor_ref: str
    tags: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    confirmation_preview_arguments: dict[str, Any] = field(default_factory=dict)
    confirmation_commit_arguments: dict[str, Any] = field(default_factory=dict)
    idempotency: str = "none"
    idempotency_argument_name: str = "idempotency_key"
    requires_mcp_enabled: bool = False
    required_roles: tuple[str, ...] = ()
    audit_tags: tuple[str, ...] = ()
    legacy_tool_names: tuple[str, ...] = ()
    enabled: bool = True
    lifecycle_status: str = "active"
    deprecated_since: str = ""
    sunset_on: str = ""
    replacement_hint: str = ""
    confirmation_commit_argument_bindings: dict[str, str] = field(default_factory=dict, repr=False)

    def _lifecycle_dict(self) -> dict[str, Any]:
        """Return lifecycle metadata only when a capability is not active."""

        if self.lifecycle_status == "active":
            return {}
        return {
            "lifecycle_status": self.lifecycle_status,
            "deprecated_since": self.deprecated_since,
            "sunset_on": self.sunset_on,
            "replacement_hint": self.replacement_hint,
        }

    def to_discovery_dict(self) -> dict[str, Any]:
        """Return compact metadata suitable for bounded capability search."""
        return {
            "capability_key": self.capability_key,
            "title": self.title,
            "summary": self.summary,
            "owner_app": self.owner_app,
            "risk_level": self.risk_level,
            "tags": list(self.tags),
            "requires_confirmation": self.requires_confirmation,
            "required_roles": list(self.required_roles),
            **self._lifecycle_dict(),
        }

    def to_summary_dict(self) -> dict[str, Any]:
        """Return a stable summary payload for discovery endpoints."""
        return {
            "capability_key": self.capability_key,
            "title": self.title,
            "summary": self.summary,
            "owner_app": self.owner_app,
            "risk_level": self.risk_level,
            "tags": list(self.tags),
            "requires_confirmation": self.requires_confirmation,
            "idempotency": self.idempotency,
            "idempotency_argument_name": self.idempotency_argument_name,
            "required_roles": list(self.required_roles),
            "audit_tags": list(self.audit_tags),
            "legacy_tool_names": list(self.legacy_tool_names),
            **self._lifecycle_dict(),
        }

    def to_schema_dict(self) -> dict[str, Any]:
        """Return the full schema payload for one capability."""
        payload = self.to_summary_dict()
        payload.update(
            {
                "description": self.description,
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
                "requires_mcp_enabled": self.requires_mcp_enabled,
                "executor_kind": self.executor_kind,
                "confirmation_preview_arguments": self.confirmation_preview_arguments,
                "confirmation_commit_arguments": self.confirmation_commit_arguments,
            }
        )
        return payload
