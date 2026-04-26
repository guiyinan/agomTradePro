"""Pulse application query services."""

from typing import Any

from apps.pulse.infrastructure.providers import get_navigator_asset_config_repository


def list_active_navigator_asset_config_payloads() -> list[dict[str, Any]]:
    """读取激活的 Navigator 资产配置原始载荷。"""
    return get_navigator_asset_config_repository().list_active_config_payloads()


def list_pulse_history_payloads(months: int = 6) -> list[dict[str, Any]]:
    """Return serialized pulse history payloads for interface consumers."""

    from apps.pulse.infrastructure.providers import PulseRepository

    logs = PulseRepository().get_history(months=months)
    return [
        {
            "observed_at": log.observed_at.isoformat(),
            "regime_context": log.regime_context,
            "composite_score": log.composite_score,
            "regime_strength": log.regime_strength,
            "growth_score": log.growth_score,
            "inflation_score": log.inflation_score,
            "liquidity_score": log.liquidity_score,
            "sentiment_score": log.sentiment_score,
            "transition_warning": log.transition_warning,
            "transition_direction": log.transition_direction,
        }
        for log in logs
    ]
