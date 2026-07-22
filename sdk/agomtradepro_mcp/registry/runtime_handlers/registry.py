"""Merge explicit owner handler registries with duplicate protection."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any

from .owners import (
    account,
    agent_runtime,
    ai_provider,
    alpha,
    alpha_trigger,
    asset_analysis,
    audit,
    backtest,
    beta_gate,
    broker_execution,
    config_center,
    dashboard,
    data_center,
    decision_rhythm,
    equity,
    events,
    factor,
    filter,
    fund,
    hedge,
    policy,
    prompt,
    pulse,
    realtime,
    regime,
    risk_center,
    rotation,
    sector,
    sentiment,
    signal,
    simulated_trading,
    strategy,
    task_monitor,
    terminal,
)

OWNER_HANDLER_MODULES: tuple[ModuleType, ...] = (
    account,
    agent_runtime,
    ai_provider,
    alpha,
    alpha_trigger,
    asset_analysis,
    audit,
    backtest,
    beta_gate,
    broker_execution,
    config_center,
    dashboard,
    data_center,
    decision_rhythm,
    equity,
    events,
    factor,
    filter,
    fund,
    hedge,
    policy,
    prompt,
    pulse,
    realtime,
    regime,
    risk_center,
    rotation,
    sector,
    sentiment,
    signal,
    simulated_trading,
    strategy,
    task_monitor,
    terminal,
)


def _merge_registry(attribute: str) -> dict[str, Callable[..., Any]]:
    merged: dict[str, Callable[..., Any]] = {}
    for module in OWNER_HANDLER_MODULES:
        entries = getattr(module, attribute)
        duplicates = sorted(set(merged).intersection(entries))
        if duplicates:
            raise RuntimeError(f"Duplicate runtime handlers: {duplicates}")
        merged.update(entries)
    return merged


OWNER_LEGACY_TOOL_FALLBACKS = _merge_registry("LEGACY_TOOL_FALLBACKS")
OWNER_GOVERNED_HANDLERS = _merge_registry("GOVERNED_HANDLERS")
