"""Typed field names shared by strategy inspection application and infrastructure."""

from __future__ import annotations

from typing import Literal

StrategyRiskLimitField = Literal[
    "max_single_position_pct",
    "max_total_position_pct",
    "stop_loss_pct",
]

__all__: tuple[str, ...] = ("StrategyRiskLimitField",)
