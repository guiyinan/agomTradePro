"""Manifest definitions for MCP capability registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CapabilityManifestValidationError(ValueError):
    """Raised when a capability manifest violates registry rules."""


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
