"""Structured runtime injection bundles for published TUI metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tui_metadata_runtime_injection_advisor import (
    RUNTIME_ADVISOR_ACTION,
    RUNTIME_ADVISOR_FACTOR_BREAKDOWN_ACTION,
    RUNTIME_ADVISOR_SCREEN,
    RUNTIME_ADVISOR_SELECTOR_ACTION,
)
from .tui_metadata_runtime_injection_capability_router import (
    RUNTIME_CAPABILITY_ROUTER_ACTIONS,
    RUNTIME_CAPABILITY_ROUTER_DEBUG_MODULE,
    RUNTIME_CAPABILITY_ROUTER_MCP_SCREEN,
    RUNTIME_MCP_GOVERNANCE_MODULE,
    RUNTIME_CAPABILITY_ROUTER_SCREEN,
)
from .tui_metadata_runtime_injection_cli import (
    RUNTIME_CLI_CHAT_ACTION,
    RUNTIME_CLI_GROUP,
    RUNTIME_CLI_MODULE,
    RUNTIME_CLI_SCREEN,
    RUNTIME_CLI_STREAM_ACTION,
)
from .tui_metadata_runtime_injection_config_center import RUNTIME_CONFIG_CENTER_ACTIONS
from .tui_metadata_runtime_injection_event_replay import RUNTIME_EVENT_REPLAY_ACTIONS
from .tui_metadata_runtime_injection_identity_access import (
    RUNTIME_AI_MY_PROVIDERS_SCREEN,
    RUNTIME_AI_OPS_MODULE,
    RUNTIME_AI_SYSTEM_PROVIDERS_SCREEN,
    RUNTIME_AI_USER_QUOTAS_SCREEN,
    RUNTIME_IDENTITY_ACCESS_ACTIONS,
    RUNTIME_MCP_ADMIN_ACCESS_SCREEN,
    RUNTIME_MCP_ACCESS_MODULE,
    RUNTIME_MCP_SELF_SERVICE_SCREEN,
)
from .tui_metadata_runtime_injection_operator import RUNTIME_OPERATOR_ACTIONS
from .tui_metadata_runtime_injection_realtime import (
    RUNTIME_REALTIME_ACTIONS,
    RUNTIME_REALTIME_GROUP,
    RUNTIME_REALTIME_MODULE,
    RUNTIME_REALTIME_SCREEN,
)
from .tui_metadata_runtime_injection_risk_center import (
    RUNTIME_RISK_CENTER_ACTIONS,
    RUNTIME_RISK_CENTER_MODULE,
    RUNTIME_RISK_CENTER_SCREEN,
)


@dataclass(frozen=True)
class RuntimeMetadataInjectionBundle:
    """One runtime metadata injection bundle plus its coverage counter key."""

    coverage_key: str
    groups: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    modules: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    screens: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    actions: tuple[dict[str, Any], ...] = field(default_factory=tuple)


RUNTIME_METADATA_INJECTIONS: tuple[RuntimeMetadataInjectionBundle, ...] = (
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_cli_metadata",
        groups=(RUNTIME_CLI_GROUP,),
        modules=(RUNTIME_CLI_MODULE,),
        screens=(RUNTIME_CLI_SCREEN,),
        actions=(RUNTIME_CLI_CHAT_ACTION, RUNTIME_CLI_STREAM_ACTION),
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_capability_router_metadata",
        groups=(RUNTIME_CLI_GROUP,),
        modules=(
            RUNTIME_MCP_ACCESS_MODULE,
            RUNTIME_MCP_GOVERNANCE_MODULE,
            RUNTIME_CAPABILITY_ROUTER_DEBUG_MODULE,
            RUNTIME_AI_OPS_MODULE,
        ),
        screens=(
            RUNTIME_CAPABILITY_ROUTER_SCREEN,
            RUNTIME_CAPABILITY_ROUTER_MCP_SCREEN,
            RUNTIME_MCP_SELF_SERVICE_SCREEN,
            RUNTIME_MCP_ADMIN_ACCESS_SCREEN,
            RUNTIME_AI_MY_PROVIDERS_SCREEN,
            RUNTIME_AI_SYSTEM_PROVIDERS_SCREEN,
            RUNTIME_AI_USER_QUOTAS_SCREEN,
        ),
        actions=RUNTIME_CAPABILITY_ROUTER_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_advisor_metadata",
        screens=(RUNTIME_ADVISOR_SCREEN,),
        actions=(
            RUNTIME_ADVISOR_SELECTOR_ACTION,
            RUNTIME_ADVISOR_ACTION,
            RUNTIME_ADVISOR_FACTOR_BREAKDOWN_ACTION,
        ),
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_risk_center_metadata",
        modules=(RUNTIME_RISK_CENTER_MODULE,),
        screens=(RUNTIME_RISK_CENTER_SCREEN,),
        actions=RUNTIME_RISK_CENTER_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_realtime_metadata",
        groups=(RUNTIME_REALTIME_GROUP,),
        modules=(RUNTIME_REALTIME_MODULE,),
        screens=(RUNTIME_REALTIME_SCREEN,),
        actions=RUNTIME_REALTIME_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_event_replay_metadata",
        actions=RUNTIME_EVENT_REPLAY_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_config_center_metadata",
        actions=RUNTIME_CONFIG_CENTER_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_operator_metadata",
        actions=RUNTIME_OPERATOR_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_identity_access_metadata",
        screens=(),
        actions=RUNTIME_IDENTITY_ACCESS_ACTIONS,
    ),
)
