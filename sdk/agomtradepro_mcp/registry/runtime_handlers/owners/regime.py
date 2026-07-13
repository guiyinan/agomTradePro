"""regime runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _unwrap_canonical_success_data


def _fallback_get_current_regime() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    regime = client.regime.get_current()
    return {
        "dominant_regime": regime.dominant_regime,
        "growth_level": regime.growth_level,
        "inflation_level": regime.inflation_level,
        "growth_indicator": regime.growth_indicator,
        "inflation_indicator": regime.inflation_indicator,
        "growth_value": regime.growth_value,
        "inflation_value": regime.inflation_value,
        "observed_at": regime.observed_at.isoformat(),
    }


def _fallback_get_regime_history(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    parsed_start = date.fromisoformat(start_date) if start_date else None
    parsed_end = date.fromisoformat(end_date) if end_date else None
    regimes = client.regime.history(
        start_date=parsed_start,
        end_date=parsed_end,
        limit=limit,
    )
    history = [
        {
            "dominant_regime": item.dominant_regime,
            "growth_level": item.growth_level,
            "inflation_level": item.inflation_level,
            "observed_at": item.observed_at.isoformat(),
            "confidence": item.confidence,
        }
        for item in regimes
    ]
    return {
        "history": history,
        "total_count": len(history),
    }


def _fallback_get_regime_navigator() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.pulse.get_navigator()
    data = response.get("data") if isinstance(response, dict) else None
    return data if isinstance(data, dict) else response


def _fallback_get_regime_distribution(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    parsed_start = date.fromisoformat(start_date) if start_date else None
    parsed_end = date.fromisoformat(end_date) if end_date else None
    client = AgomTradeProClient()
    distribution = client.regime.get_regime_distribution(
        start_date=parsed_start,
        end_date=parsed_end,
    )
    normalized = {str(regime): int(count) for regime, count in distribution.items()}
    return {
        "distribution": normalized,
        "total_count": sum(normalized.values()),
    }


def _fallback_calculate_regime(
    as_of_date: str | None = None,
    use_pit: bool = True,
    growth_indicator: str = "PMI",
    inflation_indicator: str = "CPI",
    data_source: str = "akshare",
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
    client = AgomTradeProClient()
    return client.regime.calculate_snapshot(
        as_of_date=parsed_date,
        use_pit=use_pit,
        growth_indicator=growth_indicator,
        inflation_indicator=inflation_indicator,
        data_source=data_source,
    )


def _fallback_regime_read_action_recommendation() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.pulse.get_action_recommendation()
    data = _unwrap_canonical_success_data(
        response,
        operation="regime.read.action_recommendation",
    )
    contract = data.get("contract")
    if not isinstance(contract, dict):
        raise ValueError("regime.read.action_recommendation must contain a contract object")
    return data


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_current_regime": _fallback_get_current_regime,
    "get_regime_history": _fallback_get_regime_history,
    "get_regime_navigator": _fallback_get_regime_navigator,
    "get_regime_distribution": _fallback_get_regime_distribution,
    "calculate_regime": _fallback_calculate_regime,
    "regime_read_action_recommendation": _fallback_regime_read_action_recommendation,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
