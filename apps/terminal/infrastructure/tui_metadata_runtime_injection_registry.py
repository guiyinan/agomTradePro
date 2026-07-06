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
    RUNTIME_CAPABILITY_ROUTER_MODULE,
    RUNTIME_CAPABILITY_ROUTER_SCREEN,
)
from .tui_metadata_runtime_injection_cli import (
    RUNTIME_CLI_CHAT_ACTION,
    RUNTIME_CLI_GROUP,
    RUNTIME_CLI_MODULE,
    RUNTIME_CLI_SCREEN,
)
from .tui_metadata_runtime_injection_config_center import RUNTIME_CONFIG_CENTER_ACTIONS
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
        actions=(RUNTIME_CLI_CHAT_ACTION,),
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_capability_router_metadata",
        groups=(RUNTIME_CLI_GROUP,),
        modules=(RUNTIME_CAPABILITY_ROUTER_MODULE,),
        screens=(RUNTIME_CAPABILITY_ROUTER_SCREEN,),
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
        coverage_key="runtime_injected_config_center_metadata",
        actions=RUNTIME_CONFIG_CENTER_ACTIONS,
    ),
)
