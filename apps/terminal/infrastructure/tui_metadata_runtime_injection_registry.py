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
from .tui_metadata_runtime_injection_account_overview import (
    RUNTIME_ACCOUNT_OVERVIEW_ACTIONS,
)
from .tui_metadata_runtime_injection_advisor import (
    RUNTIME_ADVISOR_ACTION,
    RUNTIME_ADVISOR_FACTOR_BREAKDOWN_ACTION,
    RUNTIME_ADVISOR_SCREEN,
    RUNTIME_ADVISOR_SELECTOR_ACTION,
)
from .tui_metadata_runtime_injection_agent_runtime import (
    RUNTIME_AGENT_RUNTIME_OPERATOR_ACTIONS,
)
from .tui_metadata_runtime_injection_alpha_ops import RUNTIME_ALPHA_OPS_ACTIONS
from .tui_metadata_runtime_injection_alpha_trigger import (
    RUNTIME_ALPHA_TRIGGER_MUTATION_ACTIONS,
    RUNTIME_ALPHA_TRIGGER_READ_ACTIONS,
)
from .tui_metadata_runtime_injection_asset_analysis import (
    RUNTIME_ASSET_ANALYSIS_ACTIONS,
)
from .tui_metadata_runtime_injection_audit import RUNTIME_AUDIT_ACTIONS
from .tui_metadata_runtime_injection_audit_analytics import (
    RUNTIME_AUDIT_ANALYTICS_ACTIONS,
)
from .tui_metadata_runtime_injection_backtest import RUNTIME_BACKTEST_ACTIONS
from .tui_metadata_runtime_injection_beta_gate import RUNTIME_BETA_GATE_ACTIONS
from .tui_metadata_runtime_injection_broker_execution import (
    RUNTIME_BROKER_EXECUTION_ACTIONS,
    RUNTIME_BROKER_EXECUTION_SCREENS,
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
from .tui_metadata_runtime_injection_config_center import (
    RUNTIME_CONFIG_CENTER_ACTIONS,
    RUNTIME_CONFIG_CENTER_SCREEN,
)
from .tui_metadata_runtime_injection_dashboard_alpha import (
    RUNTIME_DASHBOARD_ALPHA_ACTIONS,
)
from .tui_metadata_runtime_injection_dashboard_overview import (
    RUNTIME_DASHBOARD_OVERVIEW_ACTIONS,
)
from .tui_metadata_runtime_injection_data_center import (
    RUNTIME_DATA_CENTER_ACTIONS,
)
from .tui_metadata_runtime_injection_decision_rhythm import (
    RUNTIME_DECISION_RHYTHM_ACTIONS,
)
from .tui_metadata_runtime_injection_decision_workspace import (
    RUNTIME_DECISION_WORKSPACE_ACTIONS,
)
from .tui_metadata_runtime_injection_equity_analytics import (
    RUNTIME_EQUITY_ANALYTICS_ACTIONS,
)
from .tui_metadata_runtime_injection_equity_config import (
    RUNTIME_EQUITY_CONFIG_ACTIONS,
)
from .tui_metadata_runtime_injection_equity_screen import (
    RUNTIME_EQUITY_SCREEN_ACTIONS,
)
from .tui_metadata_runtime_injection_event_replay import RUNTIME_EVENT_REPLAY_ACTIONS
from .tui_metadata_runtime_injection_factor_calculate import (
    RUNTIME_FACTOR_CALCULATE_ACTIONS,
)
from .tui_metadata_runtime_injection_factor_definitions import (
    RUNTIME_FACTOR_DEFINITION_ACTIONS,
)
from .tui_metadata_runtime_injection_factor_portfolios import (
    RUNTIME_FACTOR_PORTFOLIO_ACTIONS,
)
from .tui_metadata_runtime_injection_fund import RUNTIME_FUND_ACTIONS
from .tui_metadata_runtime_injection_hedge import RUNTIME_HEDGE_ACTIONS
from .tui_metadata_runtime_injection_identity_access import (
    RUNTIME_ACCOUNT_SELF_SERVICE_SCREEN,
    RUNTIME_AI_MY_PROVIDERS_SCREEN,
    RUNTIME_AI_OPS_MODULE,
    RUNTIME_AI_SYSTEM_PROVIDERS_SCREEN,
    RUNTIME_AI_USER_QUOTAS_SCREEN,
    RUNTIME_IDENTITY_ACCESS_ACTIONS,
    RUNTIME_MCP_ACCESS_MODULE,
    RUNTIME_MCP_ADMIN_ACCESS_SCREEN,
    RUNTIME_MCP_SELF_SERVICE_SCREEN,
    RUNTIME_USER_ACCESS_GOVERNANCE_SCREEN,
)
from .tui_metadata_runtime_injection_macro_regime_analytics import (
    RUNTIME_MACRO_REGIME_ANALYTICS_ACTIONS,
)
from .tui_metadata_runtime_injection_macro_trend_filter import (
    RUNTIME_MACRO_TREND_FILTER_ACTIONS,
)
from .tui_metadata_runtime_injection_manual_trade_review import (
    RUNTIME_MANUAL_TRADE_REVIEW_ACTIONS,
)
from .tui_metadata_runtime_injection_operator import RUNTIME_OPERATOR_ACTIONS
from .tui_metadata_runtime_injection_ops import RUNTIME_OPS_SEMANTIC_ACTIONS
from .tui_metadata_runtime_injection_policy import (
    RUNTIME_POLICY_EVENT_ACTIONS,
    RUNTIME_POLICY_RSS_ACTIONS,
)
from .tui_metadata_runtime_injection_prompt import (
    RUNTIME_PROMPT_ACTIONS,
    RUNTIME_PROMPT_SCREEN,
)
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
from .tui_metadata_runtime_injection_rotation import (
    RUNTIME_ROTATION_ACTIONS,
    RUNTIME_ROTATION_CONFIG_ACTIONS,
    RUNTIME_ROTATION_SIGNAL_ACCOUNT_ACTIONS,
)
from .tui_metadata_runtime_injection_sentiment import RUNTIME_SENTIMENT_ACTIONS
from .tui_metadata_runtime_injection_signal import RUNTIME_SIGNAL_ACTIONS
from .tui_metadata_runtime_injection_simulated_trading import (
    RUNTIME_SIMULATED_TRADING_ACTIONS,
)
from .tui_metadata_runtime_injection_strategy import RUNTIME_STRATEGY_ACTIONS
from .tui_metadata_runtime_injection_system_settings import (
    RUNTIME_SYSTEM_SETTINGS_ACTIONS,
    RUNTIME_SYSTEM_SETTINGS_SCREEN,
)
from .tui_metadata_runtime_injection_task_monitor import (
    RUNTIME_TASK_MONITOR_ACTIONS,
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
    for key in ("screen_key", "target_screen"):
        if key not in resolved:
            continue
        current = str(resolved.get(key) or "")
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
            RUNTIME_USER_ACCESS_GOVERNANCE_SCREEN,
            RUNTIME_ACCOUNT_SELF_SERVICE_SCREEN,
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
        coverage_key="runtime_injected_asset_analysis_metadata",
        actions=RUNTIME_ASSET_ANALYSIS_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_account_overview_metadata",
        actions=RUNTIME_ACCOUNT_OVERVIEW_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_audit_metadata",
        actions=RUNTIME_AUDIT_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_audit_analytics_metadata",
        actions=RUNTIME_AUDIT_ANALYTICS_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_manual_trade_review_metadata",
        actions=RUNTIME_MANUAL_TRADE_REVIEW_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_macro_regime_analytics_metadata",
        actions=RUNTIME_MACRO_REGIME_ANALYTICS_ACTIONS,
        replace_existing=True,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_macro_trend_filter_metadata",
        actions=RUNTIME_MACRO_TREND_FILTER_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_agent_runtime_operator_metadata",
        actions=RUNTIME_AGENT_RUNTIME_OPERATOR_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_broker_execution_metadata",
        screens=RUNTIME_BROKER_EXECUTION_SCREENS,
        actions=RUNTIME_BROKER_EXECUTION_ACTIONS,
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
        coverage_key="runtime_injected_factor_calculate_metadata",
        actions=RUNTIME_FACTOR_CALCULATE_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_factor_definition_metadata",
        actions=RUNTIME_FACTOR_DEFINITION_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_factor_portfolio_metadata",
        actions=RUNTIME_FACTOR_PORTFOLIO_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_hedge_metadata",
        actions=RUNTIME_HEDGE_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_fund_metadata",
        actions=RUNTIME_FUND_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_ops_semantic_metadata",
        actions=RUNTIME_OPS_SEMANTIC_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_simulated_trading_metadata",
        actions=RUNTIME_SIMULATED_TRADING_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_strategy_metadata",
        actions=RUNTIME_STRATEGY_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_config_center_metadata",
        screens=(RUNTIME_CONFIG_CENTER_SCREEN,),
        actions=RUNTIME_CONFIG_CENTER_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_prompt_metadata",
        screens=(RUNTIME_PROMPT_SCREEN,),
        actions=RUNTIME_PROMPT_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_system_settings_metadata",
        screens=(RUNTIME_SYSTEM_SETTINGS_SCREEN,),
        actions=RUNTIME_SYSTEM_SETTINGS_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_signal_metadata",
        actions=RUNTIME_SIGNAL_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_sentiment_metadata",
        actions=RUNTIME_SENTIMENT_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_decision_rhythm_metadata",
        actions=RUNTIME_DECISION_RHYTHM_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_decision_workspace_metadata",
        actions=RUNTIME_DECISION_WORKSPACE_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_dashboard_alpha_metadata",
        actions=RUNTIME_DASHBOARD_ALPHA_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_dashboard_overview_metadata",
        actions=RUNTIME_DASHBOARD_OVERVIEW_ACTIONS,
        replace_existing=True,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_data_center_metadata",
        actions=RUNTIME_DATA_CENTER_ACTIONS,
        replace_existing=True,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_equity_config_metadata",
        actions=RUNTIME_EQUITY_CONFIG_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_equity_analytics_metadata",
        actions=RUNTIME_EQUITY_ANALYTICS_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_equity_screen_metadata",
        actions=RUNTIME_EQUITY_SCREEN_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_backtest_metadata",
        actions=RUNTIME_BACKTEST_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_beta_gate_metadata",
        actions=RUNTIME_BETA_GATE_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_alpha_trigger_metadata",
        actions=(
            *RUNTIME_ALPHA_TRIGGER_READ_ACTIONS,
            *RUNTIME_ALPHA_TRIGGER_MUTATION_ACTIONS,
        ),
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_alpha_ops_metadata",
        actions=RUNTIME_ALPHA_OPS_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_policy_metadata",
        actions=(
            *RUNTIME_POLICY_EVENT_ACTIONS,
            *RUNTIME_POLICY_RSS_ACTIONS,
        ),
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_task_monitor_metadata",
        actions=RUNTIME_TASK_MONITOR_ACTIONS,
    ),
    RuntimeMetadataInjectionBundle(
        coverage_key="runtime_injected_rotation_metadata",
        actions=(
            *RUNTIME_ROTATION_ACTIONS,
            *RUNTIME_ROTATION_CONFIG_ACTIONS,
            *RUNTIME_ROTATION_SIGNAL_ACCOUNT_ACTIONS,
        ),
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
