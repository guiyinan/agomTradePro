"""
Shared Domain Interfaces and Protocols.

Defines protocols that infrastructure layer must implement.
"""

from typing import Protocol, List
from dataclasses import dataclass


@dataclass(frozen=True)
class TrendResult:
    """趋势计算结果"""
    values: tuple[float, ...]
    z_scores: tuple[float, ...]


class TrendCalculatorProtocol(Protocol):
    """趋势计算协议"""

    def calculate_hp_trend(
        self,
        series: List[float],
        lamb: float = 129600
    ) -> TrendResult:
        """HP 滤波计算趋势"""
        ...

    def calculate_z_scores(
        self,
        series: List[float],
        window: int = 60
    ) -> tuple[float, ...]:
        """计算 Z-score"""
        ...
