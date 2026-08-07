"""Runtime adapters and fallback prompt configuration for capability routing."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.regime.application.current_regime import resolve_current_regime

from .terminal_gateway import get_terminal_capability_gateway


class CapabilityRegimeAdapter:
    """Adapter for exposing regime queries to tool registry."""

    def get_current_regime(self, as_of_date: date | None = None) -> dict[str, Any]:
        """Return the current regime in registry-compatible form."""

        result = resolve_current_regime(as_of_date=as_of_date)
        return {
            "dominant_regime": result.dominant_regime,
            "confidence": result.confidence,
            "observed_at": result.observed_at.isoformat() if result.observed_at else None,
            "data_source": result.data_source,
            "warnings": result.warnings,
            "distribution": result.distribution or {},
            "is_fallback": result.is_fallback,
        }

    def get_regime_distribution(self, as_of_date: date | None = None) -> dict[str, Any]:
        """Return the current regime probability distribution."""

        result = resolve_current_regime(as_of_date=as_of_date)
        return {
            "observed_at": result.observed_at.isoformat() if result.observed_at else None,
            "distribution": result.distribution or {},
            "dominant_regime": result.dominant_regime,
            "confidence": result.confidence,
            "data_source": result.data_source,
            "warnings": result.warnings,
            "is_fallback": result.is_fallback,
        }


DEFAULT_FALLBACK_CHAT_SYSTEM_PROMPT = (
    "You are the AgomTradePro system assistant for an investment decision platform. "
    "Prioritize answers within AgomTradePro operational context, including system status, "
    "macro environment, market regime, policy level, portfolio, positions, signals, "
    "backtest, audit, AI provider configuration, terminal commands, RSS ingestion, "
    "policy news, hotspot events, and other system modules already present in the platform. "
    "If the user asks an ambiguous question such as recommendations, interpret it in this platform context first. "
    "Do not drift into unrelated lifestyle topics like fitness, travel, entertainment, or generic life coaching. "
    "If the request is underspecified, ask a short clarifying question tied to the platform context, "
    "or provide the most relevant system-oriented answer."
)


def get_fallback_chat_system_prompt() -> str:
    """Return the configured prompt or the stable system fallback."""

    settings_data = get_terminal_capability_gateway().get_runtime_settings()
    custom_prompt = str(settings_data.get("fallback_chat_system_prompt", "") or "").strip()
    return custom_prompt or DEFAULT_FALLBACK_CHAT_SYSTEM_PROMPT


_CapabilityRegimeAdapter = CapabilityRegimeAdapter
_get_fallback_chat_system_prompt = get_fallback_chat_system_prompt

__all__ = ["_get_fallback_chat_system_prompt"]
