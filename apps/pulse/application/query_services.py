"""Pulse application query services."""

from typing import Any

from apps.data_center.application.public import get_macro_runtime_metadata
from apps.pulse.application.repository_provider import (
    get_navigator_asset_config_repository,
    get_pulse_repository,
)
from apps.pulse.domain.entities import PulseIndicatorReading

_SIGNAL_LABELS: dict[str, str] = {
    "bullish": "偏积极",
    "bearish": "偏谨慎",
    "neutral": "中性",
}
_DIRECTION_LABELS: dict[str, str] = {
    "improving": "近期改善",
    "deteriorating": "近期走弱",
    "stable": "近期稳定",
}


def list_active_navigator_asset_config_payloads() -> list[dict[str, Any]]:
    """读取激活的 Navigator 资产配置原始载荷。"""
    return get_navigator_asset_config_repository().list_active_config_payloads()


def list_pulse_history_payloads(
    months: int = 6,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return serialized pulse history payloads for interface consumers."""
    logs = get_pulse_repository().get_history(months=months, limit=limit)
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


def build_pulse_indicator_display_payloads(
    readings: list[PulseIndicatorReading],
) -> dict[str, dict[str, object]]:
    """Build user-facing Pulse rows from one canonical metadata snapshot."""

    metadata_by_code = get_macro_runtime_metadata()
    payloads: dict[str, dict[str, object]] = {}
    for reading in readings:
        metadata = metadata_by_code.get(reading.code, {})
        unit = str(metadata.get("unit") or metadata.get("default_unit") or "").strip()
        signal_label = _SIGNAL_LABELS.get(reading.signal, reading.signal)
        direction_label = _DIRECTION_LABELS.get(reading.direction, reading.direction)
        payloads[reading.code] = {
            "unit": unit or "—",
            "value_display": _format_indicator_value(reading.value, unit),
            "signal_label": signal_label,
            "direction_label": direction_label,
            "interpretation": f"{signal_label}；{direction_label}",
        }
    return payloads


def _format_indicator_value(value: float, unit: str) -> str:
    """Format an observed indicator value without changing its canonical unit."""

    number = f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{number} {unit}".strip()
