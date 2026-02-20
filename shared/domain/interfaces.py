"""
Shared Domain Interfaces and Protocols.

Defines protocols that infrastructure layer must implement.
"""

from typing import Protocol, List, Optional
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


@dataclass(frozen=True)
class DataSourceSecretsDTO:
    """数据源密钥数据传输对象"""
    tushare_token: str
    fred_api_key: str
    juhe_api_key: Optional[str] = None


class DatabaseSecretsLoaderProtocol(Protocol):
    """数据库密钥加载协议"""

    def __call__(self) -> Optional[DataSourceSecretsDTO]:
        """从数据库加载密钥

        Returns:
            Optional[DataSourceSecretsDTO]: 如果数据库中有配置则返回，否则返回 None
        """
        ...
