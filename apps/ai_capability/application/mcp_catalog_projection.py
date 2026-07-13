"""Projection helpers for governed and legacy MCP catalog entries."""

from __future__ import annotations

from typing import Any

from ..domain.entities import (
    CapabilityDefinition,
    RiskLevel,
    RouteGroup,
    SourceType,
    Visibility,
)


def build_legacy_replacement_map(manifests: list[Any]) -> dict[str, str]:
    """Map every declared legacy tool name to its governed capability key."""

    replacements: dict[str, str] = {}
    for manifest in manifests:
        for legacy_tool_name in list(getattr(manifest, "legacy_tool_names", ()) or ()):
            normalized = str(legacy_tool_name or "").strip()
            if normalized:
                replacements[normalized] = manifest.capability_key
    return replacements


def build_governed_mcp_capability(manifest: Any) -> CapabilityDefinition:
    """Project one governed manifest into the internal capability catalog."""

    manifest_tags = list(getattr(manifest, "tags", ()) or ())
    audit_tags = [
        str(tag).strip()
        for tag in list(getattr(manifest, "audit_tags", ()) or ())
        if str(tag).strip()
    ]
    legacy_tool_names = [
        str(name).strip()
        for name in list(getattr(manifest, "legacy_tool_names", ()) or ())
        if str(name).strip()
    ]
    return CapabilityDefinition(
        capability_key=f"mcp_tool.{manifest.capability_key}",
        source_type=SourceType.MCP_TOOL,
        source_ref=manifest.capability_key,
        name=manifest.capability_key,
        summary=manifest.summary,
        description=manifest.description,
        route_group=RouteGroup.TOOL,
        category=manifest.owner_app,
        semantic_key=manifest.capability_key,
        tags=["mcp", "capability", *manifest_tags],
        when_to_use=[],
        when_not_to_use=[],
        examples=[],
        input_schema=getattr(manifest, "input_schema", {}) or {},
        execution_target={
            "type": "mcp_capability",
            "tool_name": "agom_capability_call",
            "capability_key": manifest.capability_key,
            "replacement_for": legacy_tool_names,
            "idempotency": getattr(manifest, "idempotency", "none"),
            "idempotency_argument_name": getattr(
                manifest,
                "idempotency_argument_name",
                "idempotency_key",
            ),
            "audit_tags": audit_tags,
        },
        risk_level=RiskLevel(getattr(manifest, "risk_level", RiskLevel.LOW.value)),
        requires_mcp=True,
        requires_confirmation=bool(getattr(manifest, "requires_confirmation", False)),
        enabled_for_routing=True,
        enabled_for_terminal=True,
        enabled_for_chat=False,
        enabled_for_agent=True,
        visibility=Visibility.PUBLIC,
        auto_collected=True,
        review_status="auto",
        priority_weight=10.0,
    )


def build_legacy_mcp_capability(
    tool: Any,
    *,
    replacement_capability_key: str,
    risk_level: RiskLevel,
    requires_confirmation: bool,
    enabled_for_routing: bool,
) -> CapabilityDefinition:
    """Project one compatibility-only raw MCP tool into the catalog."""

    from .mcp_runtime_gateway import get_sdk_mcp_legacy_disposition

    legacy_disposition = get_sdk_mcp_legacy_disposition(tool.name)
    disposition = str(getattr(legacy_disposition, "disposition", "") or "").strip()
    disposition_reason = str(
        getattr(legacy_disposition, "rationale", "") or ""
    ).strip()
    recommended_capability_keys = [
        str(key).strip()
        for key in list(
            getattr(legacy_disposition, "recommended_capability_keys", ()) or ()
        )
        if str(key).strip()
    ]
    owner_app = str(getattr(legacy_disposition, "owner_app", "") or "").strip()
    tags = ["mcp", "tool", "legacy"]
    if disposition:
        tags.append(f"disposition:{disposition}")

    return CapabilityDefinition(
        capability_key=f"mcp_tool.{tool.name}",
        source_type=SourceType.MCP_TOOL,
        source_ref=tool.name,
        name=tool.name,
        summary=tool.description,
        description=tool.description,
        route_group=RouteGroup.TOOL,
        category=owner_app or "mcp",
        semantic_key=replacement_capability_key or f"legacy.mcp.{tool.name}",
        tags=tags,
        when_to_use=[],
        when_not_to_use=[],
        examples=[],
        input_schema=getattr(tool, "inputSchema", {}) or {},
        execution_target={
            "type": "mcp_tool",
            "tool_name": tool.name,
            "legacy": True,
            "replacement_capability_key": replacement_capability_key,
            "legacy_disposition": disposition,
            "disposition_reason": disposition_reason,
            "recommended_capability_keys": recommended_capability_keys,
        },
        risk_level=risk_level,
        requires_mcp=True,
        requires_confirmation=requires_confirmation,
        enabled_for_routing=enabled_for_routing and legacy_disposition is None,
        enabled_for_terminal=False,
        enabled_for_chat=False,
        enabled_for_agent=False,
        visibility=Visibility.ADMIN,
        auto_collected=True,
        review_status="rejected" if legacy_disposition is not None else "auto",
        priority_weight=(
            0.01
            if legacy_disposition is not None
            else (0.1 if replacement_capability_key else 1.0)
        ),
    )
