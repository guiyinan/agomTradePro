"""Compatibility aggregate for owner-scoped write capability shards."""

from __future__ import annotations

from .owners.account_write_capabilities import MANIFESTS as _ACCOUNT_WRITE_MANIFESTS
from .owners.agent_runtime_write_capabilities import MANIFESTS as _AGENT_RUNTIME_WRITE_MANIFESTS
from .owners.ai_provider_write_capabilities import MANIFESTS as _AI_PROVIDER_WRITE_MANIFESTS
from .owners.alpha_trigger_write_capabilities import MANIFESTS as _ALPHA_TRIGGER_WRITE_MANIFESTS
from .owners.beta_gate_write_capabilities import MANIFESTS as _BETA_GATE_WRITE_MANIFESTS
from .owners.config_center_write_capabilities import MANIFESTS as _CONFIG_CENTER_WRITE_MANIFESTS
from .owners.dashboard_write_capabilities import MANIFESTS as _DASHBOARD_WRITE_MANIFESTS
from .owners.data_center_write_capabilities import MANIFESTS as _DATA_CENTER_WRITE_MANIFESTS
from .owners.decision_rhythm_write_capabilities import MANIFESTS as _DECISION_RHYTHM_WRITE_MANIFESTS
from .owners.equity_write_capabilities import MANIFESTS as _EQUITY_WRITE_MANIFESTS
from .owners.events_write_capabilities import MANIFESTS as _EVENTS_WRITE_MANIFESTS
from .owners.filter_write_capabilities import MANIFESTS as _FILTER_WRITE_MANIFESTS
from .owners.policy_write_capabilities import MANIFESTS as _POLICY_WRITE_MANIFESTS
from .owners.prompt_write_capabilities import MANIFESTS as _PROMPT_WRITE_MANIFESTS
from .owners.risk_center_write_capabilities import MANIFESTS as _RISK_CENTER_WRITE_MANIFESTS
from .owners.rotation_write_capabilities import MANIFESTS as _ROTATION_WRITE_MANIFESTS
from .owners.sentiment_write_capabilities import MANIFESTS as _SENTIMENT_WRITE_MANIFESTS
from .owners.signal_write_capabilities import MANIFESTS as _SIGNAL_WRITE_MANIFESTS
from .owners.simulated_trading_write_capabilities import (
    MANIFESTS as _SIMULATED_TRADING_WRITE_MANIFESTS,
)
from .owners.strategy_write_capabilities import MANIFESTS as _STRATEGY_WRITE_MANIFESTS

MANIFESTS = [
    *_ACCOUNT_WRITE_MANIFESTS,
    *_AGENT_RUNTIME_WRITE_MANIFESTS,
    *_AI_PROVIDER_WRITE_MANIFESTS,
    *_ALPHA_TRIGGER_WRITE_MANIFESTS,
    *_BETA_GATE_WRITE_MANIFESTS,
    *_CONFIG_CENTER_WRITE_MANIFESTS,
    *_DASHBOARD_WRITE_MANIFESTS,
    *_DATA_CENTER_WRITE_MANIFESTS,
    *_DECISION_RHYTHM_WRITE_MANIFESTS,
    *_EQUITY_WRITE_MANIFESTS,
    *_EVENTS_WRITE_MANIFESTS,
    *_FILTER_WRITE_MANIFESTS,
    *_POLICY_WRITE_MANIFESTS,
    *_PROMPT_WRITE_MANIFESTS,
    *_RISK_CENTER_WRITE_MANIFESTS,
    *_ROTATION_WRITE_MANIFESTS,
    *_SENTIMENT_WRITE_MANIFESTS,
    *_SIGNAL_WRITE_MANIFESTS,
    *_SIMULATED_TRADING_WRITE_MANIFESTS,
    *_STRATEGY_WRITE_MANIFESTS,
]
