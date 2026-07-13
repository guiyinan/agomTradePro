"""Compatibility aggregate for owner-scoped read capability shards."""

from __future__ import annotations

from .owners.account_read_capabilities import MANIFESTS as _ACCOUNT_READ_MANIFESTS
from .owners.agent_runtime_read_capabilities import MANIFESTS as _AGENT_RUNTIME_READ_MANIFESTS
from .owners.ai_provider_read_capabilities import MANIFESTS as _AI_PROVIDER_READ_MANIFESTS
from .owners.alpha_read_capabilities import MANIFESTS as _ALPHA_READ_MANIFESTS
from .owners.alpha_trigger_read_capabilities import MANIFESTS as _ALPHA_TRIGGER_READ_MANIFESTS
from .owners.asset_analysis_read_capabilities import MANIFESTS as _ASSET_ANALYSIS_READ_MANIFESTS
from .owners.audit_read_capabilities import MANIFESTS as _AUDIT_READ_MANIFESTS
from .owners.backtest_read_capabilities import MANIFESTS as _BACKTEST_READ_MANIFESTS
from .owners.beta_gate_read_capabilities import MANIFESTS as _BETA_GATE_READ_MANIFESTS
from .owners.config_center_read_capabilities import MANIFESTS as _CONFIG_CENTER_READ_MANIFESTS
from .owners.dashboard_read_capabilities import MANIFESTS as _DASHBOARD_READ_MANIFESTS
from .owners.data_center_read_capabilities import MANIFESTS as _DATA_CENTER_READ_MANIFESTS
from .owners.decision_rhythm_read_capabilities import MANIFESTS as _DECISION_RHYTHM_READ_MANIFESTS
from .owners.equity_read_capabilities import MANIFESTS as _EQUITY_READ_MANIFESTS
from .owners.events_read_capabilities import MANIFESTS as _EVENTS_READ_MANIFESTS
from .owners.factor_read_capabilities import MANIFESTS as _FACTOR_READ_MANIFESTS
from .owners.filter_read_capabilities import MANIFESTS as _FILTER_READ_MANIFESTS
from .owners.fund_read_capabilities import MANIFESTS as _FUND_READ_MANIFESTS
from .owners.hedge_read_capabilities import MANIFESTS as _HEDGE_READ_MANIFESTS
from .owners.policy_read_capabilities import MANIFESTS as _POLICY_READ_MANIFESTS
from .owners.prompt_read_capabilities import MANIFESTS as _PROMPT_READ_MANIFESTS
from .owners.pulse_read_capabilities import MANIFESTS as _PULSE_READ_MANIFESTS
from .owners.realtime_read_capabilities import MANIFESTS as _REALTIME_READ_MANIFESTS
from .owners.regime_read_capabilities import MANIFESTS as _REGIME_READ_MANIFESTS
from .owners.risk_center_read_capabilities import MANIFESTS as _RISK_CENTER_READ_MANIFESTS
from .owners.rotation_read_capabilities import MANIFESTS as _ROTATION_READ_MANIFESTS
from .owners.sentiment_read_capabilities import MANIFESTS as _SENTIMENT_READ_MANIFESTS
from .owners.signal_read_capabilities import MANIFESTS as _SIGNAL_READ_MANIFESTS
from .owners.simulated_trading_read_capabilities import (
    MANIFESTS as _SIMULATED_TRADING_READ_MANIFESTS,
)
from .owners.strategy_read_capabilities import MANIFESTS as _STRATEGY_READ_MANIFESTS
from .owners.task_monitor_read_capabilities import MANIFESTS as _TASK_MONITOR_READ_MANIFESTS

MANIFESTS = [
    *_ACCOUNT_READ_MANIFESTS,
    *_AGENT_RUNTIME_READ_MANIFESTS,
    *_AI_PROVIDER_READ_MANIFESTS,
    *_ALPHA_READ_MANIFESTS,
    *_ALPHA_TRIGGER_READ_MANIFESTS,
    *_ASSET_ANALYSIS_READ_MANIFESTS,
    *_AUDIT_READ_MANIFESTS,
    *_BACKTEST_READ_MANIFESTS,
    *_BETA_GATE_READ_MANIFESTS,
    *_CONFIG_CENTER_READ_MANIFESTS,
    *_DASHBOARD_READ_MANIFESTS,
    *_DATA_CENTER_READ_MANIFESTS,
    *_DECISION_RHYTHM_READ_MANIFESTS,
    *_EQUITY_READ_MANIFESTS,
    *_EVENTS_READ_MANIFESTS,
    *_FACTOR_READ_MANIFESTS,
    *_FILTER_READ_MANIFESTS,
    *_FUND_READ_MANIFESTS,
    *_HEDGE_READ_MANIFESTS,
    *_POLICY_READ_MANIFESTS,
    *_PROMPT_READ_MANIFESTS,
    *_PULSE_READ_MANIFESTS,
    *_REALTIME_READ_MANIFESTS,
    *_REGIME_READ_MANIFESTS,
    *_RISK_CENTER_READ_MANIFESTS,
    *_ROTATION_READ_MANIFESTS,
    *_SENTIMENT_READ_MANIFESTS,
    *_SIGNAL_READ_MANIFESTS,
    *_SIMULATED_TRADING_READ_MANIFESTS,
    *_STRATEGY_READ_MANIFESTS,
    *_TASK_MONITOR_READ_MANIFESTS,
]
