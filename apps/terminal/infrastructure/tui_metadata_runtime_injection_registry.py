"""Structured runtime injection bundles for published TUI metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tui_information_architecture import (
    load_tui_information_architecture,
    public_screen_spec,
    screen_aliases,
    screen_specs,
)
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
    RUNTIME_CAPABILITY_ROUTER_SCREEN,
    RUNTIME_MCP_GOVERNANCE_MODULE,
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
    RUNTIME_MCP_ACCESS_MODULE,
    RUNTIME_MCP_ADMIN_ACCESS_SCREEN,
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
    replace_existing: bool = False


_TUI_IA = load_tui_information_architecture()
_SCREEN_ALIASES = screen_aliases(_TUI_IA)
_SCREEN_SPECS = screen_specs(_TUI_IA)
_RUNTIME_SCREEN_KEYS = {str(screen["key"]) for screen in _TUI_IA["runtime_screens"]}


def _canonical_screen_reference(value: Any) -> Any:
    """Recursively replace legacy screen references in runtime metadata."""

    if isinstance(value, list):
        return [_canonical_screen_reference(item) for item in value]
    if not isinstance(value, dict):
        return value
    resolved = {key: _canonical_screen_reference(item) for key, item in value.items()}
    for key in ("screen_key", "target_screen", "key"):
        if key not in resolved:
            continue
        current = str(resolved.get(key) or "")
        if key != "key" or current in _SCREEN_ALIASES:
            resolved[key] = _SCREEN_ALIASES.get(current, current)
    return resolved


def _canonical_runtime_screens(
    screens: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Merge legacy runtime screen fragments into retained canonical screens."""

    fragments: dict[str, list[dict[str, Any]]] = {}
    for screen in screens:
        target = _SCREEN_ALIASES.get(str(screen.get("key") or ""), "")
        if target not in _RUNTIME_SCREEN_KEYS:
            continue
        fragments.setdefault(target, []).append(screen)

    canonical: list[dict[str, Any]] = []
    for target, source_screens in fragments.items():
        exact = next(
            (screen for screen in source_screens if str(screen.get("key") or "") == target),
            source_screens[0],
        )
        merged = _canonical_screen_reference(dict(exact))
        panels: list[dict[str, Any]] = []
        panel_keys: set[str] = set()
        for source_screen in source_screens:
            for panel in source_screen.get("dashboard_panels", []) or []:
                resolved_panel = _canonical_screen_reference(dict(panel))
                panel_key = str(resolved_panel.get("key") or "")
                if panel_key in panel_keys:
                    continue
                panels.append(resolved_panel)
                panel_keys.add(panel_key)
        if panels:
            merged["dashboard_panels"] = panels
        merged.update(public_screen_spec(_SCREEN_SPECS[target]))
        if panels:
            merged["dashboard_panels"] = panels
        canonical.append(merged)
    return tuple(canonical)


def _canonical_runtime_bundle(
    bundle: RuntimeMetadataInjectionBundle,
    *,
    inject_navigation: bool = False,
) -> RuntimeMetadataInjectionBundle:
    """Compile one legacy injection bundle against the canonical IA registry."""

    actions: list[dict[str, Any]] = []
    for source_action in bundle.actions:
        action = _canonical_screen_reference(dict(source_action))
        target = str(action.get("screen_key") or "")
        spec = _SCREEN_SPECS.get(target)
        if not spec:
            continue
        action["module_key"] = spec["module_key"]
        actions.append(action)
    return RuntimeMetadataInjectionBundle(
        coverage_key=bundle.coverage_key,
        groups=(tuple(_TUI_IA["groups"]) if inject_navigation else ()),
        modules=(tuple(_TUI_IA["modules"]) if inject_navigation else ()),
        screens=_canonical_runtime_screens(bundle.screens),
        actions=tuple(actions),
        replace_existing=bundle.replace_existing,
    )


_LEGACY_RUNTIME_METADATA_INJECTIONS: tuple[RuntimeMetadataInjectionBundle, ...] = (
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
        replace_existing=True,
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
        replace_existing=True,
    ),
)

RUNTIME_METADATA_INJECTIONS: tuple[RuntimeMetadataInjectionBundle, ...] = tuple(
    _canonical_runtime_bundle(bundle, inject_navigation=index == 0)
    for index, bundle in enumerate(_LEGACY_RUNTIME_METADATA_INJECTIONS)
)
