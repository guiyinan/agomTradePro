"""
资产分析模块 - Application 层数据传输对象（DTO）

DTO 用于在 Interface 层和 Application 层之间传输数据。
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


@dataclass
class ScreenRequest:
    """
    多维度筛选请求 DTO
    """
    asset_type: str                           # 资产类型：fund/equity/bond
    filters: dict[str, object] = field(default_factory=dict)   # 过滤条件
    weights: dict[str, float] | None = None  # 自定义权重（可选）
    max_count: int = 30                       # 最大返回数量

    def __post_init__(self):
        """验证请求数据"""
        valid_asset_types = {"fund", "equity", "bond", "commodity", "index", "sector"}
        if self.asset_type not in valid_asset_types:
            raise ValueError(f"asset_type 必须是 {valid_asset_types} 之一")

        if self.weights:
            total = sum(self.weights.values())
            if abs(total - 1.0) > 0.01:
                raise ValueError(f"权重总和必须为1.0，当前为 {total}")

        if self.max_count <= 0:
            raise ValueError(f"max_count 必须大于 0，当前为 {self.max_count}")


@dataclass
class AssetScoreDTO:
    """
    资产评分响应 DTO
    """
    asset_code: str
    asset_name: str
    asset_type: str
    style: str | None = None
    size: str | None = None
    sector: str | None = None

    # 各维度得分
    regime_score: float = 0.0
    policy_score: float = 0.0
    sentiment_score: float = 0.0
    signal_score: float = 0.0
    custom_scores: dict[str, float] = field(default_factory=dict)

    # 综合得分
    total_score: float = 0.0
    rank: int = 0

    # 推荐信息
    allocation: str = "0%"
    risk_level: str = "未知"

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "asset_type": self.asset_type,
            "style": self.style,
            "size": self.size,
            "sector": self.sector,
            "scores": {
                "regime": self.regime_score,
                "policy": self.policy_score,
                "sentiment": self.sentiment_score,
                "signal": self.signal_score,
                "custom": self.custom_scores,
                "total": self.total_score,
            },
            "rank": self.rank,
            "allocation": self.allocation,
            "risk_level": self.risk_level,
        }


@dataclass
class ScreenResponse:
    """
    多维度筛选响应 DTO
    """
    success: bool
    timestamp: str
    context: dict[str, object]                # 评分上下文
    weights: dict[str, float]                 # 使用的权重
    assets: list[AssetScoreDTO]               # 资产评分列表
    message: str | None = None             # 额外消息

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "success": self.success,
            "timestamp": self.timestamp,
            "context": self.context,
            "weights": self.weights,
            "assets": [asset.to_dict() for asset in self.assets],
            "message": self.message,
        }


@dataclass
class WeightConfigDTO:
    """
    权重配置响应 DTO
    """
    name: str
    description: str | None
    regime_weight: float
    policy_weight: float
    sentiment_weight: float
    signal_weight: float
    asset_type: str | None
    market_condition: str | None
    is_active: bool
    priority: int

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "weights": {
                "regime": self.regime_weight,
                "policy": self.policy_weight,
                "sentiment": self.sentiment_weight,
                "signal": self.signal_weight,
            },
            "asset_type": self.asset_type,
            "market_condition": self.market_condition,
            "is_active": self.is_active,
            "priority": self.priority,
        }
