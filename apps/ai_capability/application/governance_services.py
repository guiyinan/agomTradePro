"""Application services for AI capability catalog governance."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from apps.ai_capability.application.repository_provider import (
    build_api_capability_collector,
    get_capability_repository,
)
from apps.ai_capability.application.use_cases import (
    _list_sdk_mcp_capability_manifests,
    _list_sdk_mcp_core_tool_names,
    _list_sdk_mcp_tools,
)
from apps.ai_capability.domain.entities import (
    CapabilityDefinition,
    ReviewStatus,
    RiskLevel,
    RouteGroup,
    SourceType,
)


@dataclass(frozen=True)
class CapabilityGovernanceResult:
    """Result summary for one catalog governance run."""

    apply: bool
    total_reviewed: int
    changed_count: int
    stale_count: int
    stale_deleted_count: int
    routing_enabled_count: int
    routing_disabled_count: int
    approved_count: int
    pending_count: int
    rejected_count: int
    by_reason: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "apply": self.apply,
            "total_reviewed": self.total_reviewed,
            "changed_count": self.changed_count,
            "stale_count": self.stale_count,
            "stale_deleted_count": self.stale_deleted_count,
            "routing_enabled_count": self.routing_enabled_count,
            "routing_disabled_count": self.routing_disabled_count,
            "approved_count": self.approved_count,
            "pending_count": self.pending_count,
            "rejected_count": self.rejected_count,
            "by_reason": dict(self.by_reason),
        }


class CapabilityCatalogGovernanceService:
    """Apply conservative routing governance to auto-collected capabilities."""

    GOVERNED_SOURCES = (SourceType.API.value, SourceType.MCP_TOOL.value)
    READ_METHODS = {"GET", "HEAD", "OPTIONS"}
    SAFE_RISKS = {RiskLevel.SAFE, RiskLevel.LOW}
    DANGEROUS_RISKS = {RiskLevel.HIGH, RiskLevel.CRITICAL}
    MCP_REVIEWED_READ_PREFIXES = (
        "asset_",
        "check_",
        "compare_",
        "export_",
        "get_",
        "list_",
        "preview_",
        "recommend_",
    )
    MCP_REVIEWED_READ_NAMES = {
        "asset_multidim_screen",
        "asset_pool_screen",
        "asset_pool_summary",
        "run_audit_validation",
        "run_backtest",
        "run_decision_replay_backtest",
    }

    def __init__(self, capability_repo=None):
        self.capability_repo = capability_repo or get_capability_repository()

    def execute(
        self,
        *,
        apply: bool = False,
        purge_stale: bool = True,
        current_keys_by_source: dict[str, set[str]] | None = None,
    ) -> CapabilityGovernanceResult:
        """Review current catalog entries and optionally persist governance changes."""

        current_keys = current_keys_by_source or self._discover_current_keys_by_source()
        stale_keys: list[str] = []
        changed: list[CapabilityDefinition] = []
        counts = {
            "routing_enabled": 0,
            "routing_disabled": 0,
            "approved": 0,
            "pending": 0,
            "rejected": 0,
        }
        by_reason: dict[str, int] = {}

        reviewed = 0
        for source_type in self.GOVERNED_SOURCES:
            capabilities = self.capability_repo.get_by_source_type(source_type)
            source_current_keys = current_keys.get(source_type, set())

            for capability in capabilities:
                if (
                    capability.auto_collected
                    and capability.capability_key not in source_current_keys
                ):
                    stale_keys.append(capability.capability_key)
                    self._increment(by_reason, "stale_not_in_current_source")
                    continue

                reviewed += 1
                updated, reason = self._govern_current_capability(capability)
                self._increment(by_reason, reason)

                if updated.enabled_for_routing:
                    counts["routing_enabled"] += 1
                else:
                    counts["routing_disabled"] += 1

                if updated.review_status == ReviewStatus.APPROVED:
                    counts["approved"] += 1
                elif updated.review_status == ReviewStatus.PENDING:
                    counts["pending"] += 1
                elif updated.review_status == ReviewStatus.REJECTED:
                    counts["rejected"] += 1

                if updated != capability:
                    changed.append(updated)

        deleted_count = 0
        if apply:
            for capability in changed:
                self.capability_repo.save(capability)
            if purge_stale and stale_keys:
                deleted_count = self.capability_repo.delete_by_keys(stale_keys)

        return CapabilityGovernanceResult(
            apply=apply,
            total_reviewed=reviewed,
            changed_count=len(changed),
            stale_count=len(stale_keys),
            stale_deleted_count=deleted_count,
            routing_enabled_count=counts["routing_enabled"],
            routing_disabled_count=counts["routing_disabled"],
            approved_count=counts["approved"],
            pending_count=counts["pending"],
            rejected_count=counts["rejected"],
            by_reason=by_reason,
        )

    def _discover_current_keys_by_source(self) -> dict[str, set[str]]:
        api_capabilities = build_api_capability_collector().collect()
        mcp_tools = _list_sdk_mcp_tools()
        core_tool_names = _list_sdk_mcp_core_tool_names()
        core_capabilities = _list_sdk_mcp_capability_manifests()
        return {
            SourceType.API.value: {cap.capability_key for cap in api_capabilities},
            SourceType.MCP_TOOL.value: {
                *(f"mcp_tool.{tool.name}" for tool in mcp_tools if tool.name not in core_tool_names),
                *(f"mcp_tool.{cap.capability_key}" for cap in core_capabilities),
            },
        }

    def _govern_current_capability(
        self,
        capability: CapabilityDefinition,
    ) -> tuple[CapabilityDefinition, str]:
        if capability.source_type == SourceType.API:
            return self._govern_api_capability(capability)
        if capability.source_type == SourceType.MCP_TOOL:
            return self._govern_mcp_capability(capability)
        return capability, "source_not_governed"

    def _govern_api_capability(
        self,
        capability: CapabilityDefinition,
    ) -> tuple[CapabilityDefinition, str]:
        if (
            capability.route_group == RouteGroup.UNSAFE_API
            or capability.risk_level == RiskLevel.CRITICAL
        ):
            return (
                replace(
                    capability,
                    enabled_for_routing=False,
                    requires_confirmation=True,
                    review_status=ReviewStatus.REJECTED,
                ),
                "api_unsafe_rejected",
            )

        method = str(capability.execution_target.get("method", "GET")).upper()
        if (
            capability.route_group == RouteGroup.READ_API
            and capability.risk_level in self.SAFE_RISKS
            and method in self.READ_METHODS
        ):
            return (
                replace(
                    capability,
                    enabled_for_routing=True,
                    requires_confirmation=False,
                    review_status=ReviewStatus.APPROVED,
                ),
                "api_safe_read_approved",
            )

        if capability.route_group == RouteGroup.WRITE_API:
            return (
                replace(
                    capability,
                    enabled_for_routing=True,
                    requires_confirmation=True,
                    review_status=ReviewStatus.APPROVED,
                ),
                "api_write_confirmation_approved",
            )

        return (
            replace(
                capability,
                enabled_for_routing=False,
                requires_confirmation=True,
                review_status=ReviewStatus.PENDING,
            ),
            "api_ambiguous_pending",
        )

    def _govern_mcp_capability(
        self,
        capability: CapabilityDefinition,
    ) -> tuple[CapabilityDefinition, str]:
        if self._is_reviewed_mcp_read_capability(capability):
            reviewed_risk = (
                RiskLevel.MEDIUM
                if capability.name.startswith(("export_", "preview_", "run_"))
                else RiskLevel.LOW
            )
            return (
                replace(
                    capability,
                    risk_level=reviewed_risk,
                    enabled_for_routing=True,
                    requires_confirmation=True,
                    review_status=ReviewStatus.APPROVED,
                ),
                "mcp_reviewed_read_approved",
            )

        if capability.risk_level in self.DANGEROUS_RISKS:
            return (
                replace(
                    capability,
                    enabled_for_routing=False,
                    requires_confirmation=True,
                    review_status=ReviewStatus.REJECTED,
                ),
                "mcp_mutating_rejected",
            )

        if capability.risk_level in self.SAFE_RISKS:
            return (
                replace(
                    capability,
                    enabled_for_routing=True,
                    requires_confirmation=True,
                    review_status=ReviewStatus.APPROVED,
                ),
                "mcp_read_tool_approved",
            )

        return (
            replace(
                capability,
                enabled_for_routing=False,
                requires_confirmation=True,
                review_status=ReviewStatus.PENDING,
            ),
            "mcp_ambiguous_pending",
        )

    def _increment(self, counts: dict[str, int], key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    def _is_reviewed_mcp_read_capability(self, capability: CapabilityDefinition) -> bool:
        name = capability.name or capability.capability_key.removeprefix("mcp_tool.")
        return name in self.MCP_REVIEWED_READ_NAMES or name.startswith(
            self.MCP_REVIEWED_READ_PREFIXES
        )
