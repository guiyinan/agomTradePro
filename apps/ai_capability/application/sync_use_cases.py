"""Capability catalog synchronization use cases."""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime

from apps.ai_capability.application.dtos import SyncResultDTO
from apps.ai_capability.application.mcp_catalog_projection import (
    build_governed_mcp_capability,
    build_legacy_mcp_capability,
    build_legacy_replacement_map,
)
from apps.ai_capability.application.mcp_runtime_gateway import (
    list_sdk_mcp_capability_manifests as _list_sdk_mcp_capability_manifests,
)
from apps.ai_capability.application.mcp_runtime_gateway import (
    list_sdk_mcp_core_tool_names as _list_sdk_mcp_core_tool_names,
)
from apps.ai_capability.application.mcp_runtime_gateway import (
    list_sdk_mcp_tools as _list_sdk_mcp_tools,
)
from apps.ai_capability.application.repository_provider import (
    DjangoCapabilityRepository,
    DjangoSyncLogRepository,
    build_api_capability_collector,
)
from apps.ai_capability.application.semantic_governance import upsert_collected_capabilities
from apps.ai_capability.application.terminal_gateway import get_terminal_capability_gateway
from apps.ai_capability.domain.entities import (
    CapabilityDefinition,
    CapabilitySyncLog,
    RiskLevel,
    RouteGroup,
    SourceType,
)
from apps.ai_capability.domain.services import BuiltinCapabilityRegistry

logger = logging.getLogger(__name__)

_MCP_MUTATING_KEYWORDS = (
    "activate",
    "add",
    "approve",
    "backfill",
    "cancel",
    "close",
    "create",
    "deactivate",
    "delete",
    "disable",
    "enable",
    "execute",
    "export",
    "fix",
    "import",
    "open",
    "patch",
    "rebalance",
    "refresh",
    "reject",
    "remove",
    "repair",
    "reset",
    "rollback",
    "run",
    "save",
    "set",
    "submit",
    "sync",
    "trade",
    "update",
    "upsert",
    "write",
)


class SyncCapabilitiesUseCase:
    """Use case for synchronizing capabilities from sources."""

    def __init__(
        self,
        capability_repo: DjangoCapabilityRepository | None = None,
        sync_log_repo: DjangoSyncLogRepository | None = None,
    ):
        self.capability_repo = capability_repo or DjangoCapabilityRepository()
        self.sync_log_repo = sync_log_repo or DjangoSyncLogRepository()

    def execute(self, sync_type: str = "full", source: str | None = None) -> SyncResultDTO:
        """Execute capability synchronization."""
        start_time = time.time()
        started_at = datetime.now(UTC)

        total_discovered = 0
        created_count = 0
        updated_count = 0
        disabled_count = 0
        error_count, summary = 0, {}

        try:
            sources = {
                "builtin": self._sync_builtin,
                "terminal_command": self._sync_terminal_commands,
                "mcp_tool": self._sync_mcp_tools,
                "api": self._sync_apis,
            }
            source_names = [source] if source else list(sources.keys())
            for source_name in source_names:
                sync_func = sources[source_name]
                capabilities = sync_func()
                total_discovered += len(capabilities)
                result = upsert_collected_capabilities(self.capability_repo, capabilities)
                created_count += result["created"]
                updated_count += result["updated"]
                disabled = self.capability_repo.disable_missing(
                    source_name,
                    [cap.capability_key for cap in capabilities],
                )
                disabled_count += disabled
                summary[source_name] = {**result, "disabled": disabled}

        except Exception as exc:
            logger.exception("Capability sync failed")
            error_count += 1
            summary["error"] = str(exc)

        finished_at = datetime.now(UTC)
        duration = time.time() - start_time

        sync_log = CapabilitySyncLog(
            sync_type=sync_type,
            started_at=started_at,
            finished_at=finished_at,
            total_discovered=total_discovered,
            created_count=created_count,
            updated_count=updated_count,
            disabled_count=disabled_count,
            error_count=error_count,
            summary_payload=summary,
        )
        self.sync_log_repo.save(sync_log)

        return SyncResultDTO(
            sync_type=sync_type,
            total_discovered=total_discovered,
            created_count=created_count,
            updated_count=updated_count,
            disabled_count=disabled_count,
            error_count=error_count,
            duration_seconds=duration,
            summary=summary,
        )

    def _sync_builtin(self) -> list[CapabilityDefinition]:
        """Sync builtin capabilities."""
        capabilities = []
        for cap_data in BuiltinCapabilityRegistry.get_all():
            cap = CapabilityDefinition.from_dict(cap_data)
            capabilities.append(cap)
        return capabilities

    def _sync_terminal_commands(self) -> list[CapabilityDefinition]:
        """Sync terminal commands."""
        capabilities = []
        commands = get_terminal_capability_gateway().list_active_commands()

        for cmd in commands:
            command_name = str(cmd.get("name", ""))
            description = str(cmd.get("description", "") or "")
            risk_level = str(cmd.get("risk_level", "read") or "read")
            summary = description or f"Terminal command: {command_name}"
            tags = list(cmd.get("tags") or [])
            when_to_use: list[str] = []
            examples: list[str] = []
            if command_name == "market_temperature":
                summary = "Get the current market thermometer score, band, and overheating risk."
                tags.extend(["market", "temperature", "heat", "overheat", "散户热度", "接盘风险"])
                when_to_use = [
                    "User asks whether the market is overheated.",
                    "User asks about market heat, retail heat, or chasing risk.",
                ]
                examples = [
                    "市场是不是过热了",
                    "现在散户热度高吗",
                    "我会不会接盘",
                ]
            cap = CapabilityDefinition(
                capability_key=f"terminal_command.{command_name}",
                source_type=SourceType.TERMINAL_COMMAND,
                source_ref=str(cmd.get("id", "")),
                name=command_name,
                summary=summary,
                description=description,
                route_group=RouteGroup.TOOL,
                category=str(cmd.get("category", "general") or "general"),
                semantic_key=f"terminal.{command_name}",
                tags=tags,
                when_to_use=when_to_use,
                when_not_to_use=[],
                examples=examples,
                input_schema={},
                execution_target={
                    "type": "terminal_command",
                    "command_id": str(cmd.get("pk", "")),
                },
                risk_level=self._map_risk_level(risk_level),
                requires_mcp=bool(cmd.get("requires_mcp", False)),
                requires_confirmation=risk_level in ("write_high", "admin"),
                enabled_for_routing=bool(cmd.get("enabled_in_terminal", False)),
                enabled_for_terminal=True,
                enabled_for_chat=False,
                enabled_for_agent=True,
                auto_collected=True,
                review_status="auto",
            )
            capabilities.append(cap)

        return capabilities

    def _map_risk_level(self, terminal_risk: str) -> str:
        """Map terminal risk level to capability risk level."""
        mapping = {
            "read": "safe",
            "write_low": "low",
            "write_high": "high",
            "admin": "critical",
        }
        return mapping.get(terminal_risk, "medium")

    def _classify_mcp_tool(self, tool_name: str) -> tuple[RiskLevel, bool, bool]:
        normalized = (tool_name or "").lower()
        tokens = set(re.findall(r"[a-z0-9]+", normalized))
        is_mutating = any(keyword in tokens for keyword in _MCP_MUTATING_KEYWORDS)
        if is_mutating:
            return (RiskLevel.HIGH, True, False)
        return (RiskLevel.LOW, True, True)

    def _sync_mcp_tools(self) -> list[CapabilityDefinition]:
        """Sync MCP tools."""
        capabilities = []

        try:
            core_manifests = _list_sdk_mcp_capability_manifests()
            core_tool_names = _list_sdk_mcp_core_tool_names()
            legacy_replacement_map = build_legacy_replacement_map(core_manifests)
            capabilities.extend(
                build_governed_mcp_capability(manifest) for manifest in core_manifests
            )

            for tool in _list_sdk_mcp_tools(include_legacy=True):
                if tool.name in core_tool_names:
                    continue
                risk_level, requires_confirmation, enabled_for_routing = self._classify_mcp_tool(
                    tool.name
                )
                replacement_capability_key = legacy_replacement_map.get(tool.name, "")
                capabilities.append(
                    build_legacy_mcp_capability(
                        tool,
                        replacement_capability_key=replacement_capability_key,
                        risk_level=risk_level,
                        requires_confirmation=requires_confirmation,
                        enabled_for_routing=enabled_for_routing,
                    )
                )
        except Exception as exc:
            logger.warning("Failed to sync MCP tools: %s", exc)

        return capabilities

    def _sync_apis(self) -> list[CapabilityDefinition]:
        """Sync internal APIs."""
        collector = build_api_capability_collector()
        return collector.collect()
