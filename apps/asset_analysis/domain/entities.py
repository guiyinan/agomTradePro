"""
资产分析模块 - Domain 层实体

本模块定义通用资产分析的实体类，遵循 DDD 原则。
Domain 层不依赖任何外部框架（如 Django），只使用 Python 标准库。
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class AssetType(Enum):
    """资产类型"""
    EQUITY = "equity"          # 股票
    FUND = "fund"              # 基金
    BOND = "bond"              # 债券
    COMMODITY = "commodity"    # 商品
    INDEX = "index"            # 指数
    SECTOR = "sector"          # 行业


class AssetStyle(Enum):
    """资产风格"""
    GROWTH = "growth"          # 成长
    VALUE = "value"            # 价值
    BLEND = "blend"            # 混合
    QUALITY = "quality"        # 质量
    DEFENSIVE = "defensive"    # 防御


class AssetSize(Enum):
    """资产规模"""
    LARGE_CAP = "large"        # 大盘
    MID_CAP = "mid"            # 中盘
    SMALL_CAP = "small"        # 小盘


@dataclass(frozen=True)
class AssetScore:
    """
    通用资产评分实体

    设计原则：
    1. 使用 frozen=True 确保不可变性
    2. 所有维度得分范围 0-100
    3. 支持扩展 custom_scores 用于特定资产类型
    """
    # 资产标识
    asset_type: AssetType
    asset_code: str
    asset_name: str

    # 风格属性
    style: AssetStyle | None = None
    size: AssetSize | None = None
    sector: str | None = None  # 行业

    # 各维度得分（0-100）
    regime_score: float = 0.0
    policy_score: float = 0.0
    sentiment_score: float = 0.0
    signal_score: float = 0.0

    # 特有维度（可扩展）
    # 基金可用：manager_score, fund_flow_score
    # 股票可用：technical_score, fundamental_score
    custom_scores: dict[str, float] = field(default_factory=dict)

    # 综合得分
    total_score: float = 0.0
    rank: int = 0

    # 推荐信息
    allocation_percent: float = 0.0
    risk_level: str = "未知"

    # 元信息
    score_date: date = field(default_factory=date.today)
    context: dict | None = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "asset_type": self.asset_type.value,
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "style": self.style.value if self.style else None,
            "size": self.size.value if self.size else None,
            "sector": self.sector,
            "scores": {
                "regime": self.regime_score,
                "policy": self.policy_score,
                "sentiment": self.sentiment_score,
                "signal": self.signal_score,
                "custom": self.custom_scores,
            },
            "total_score": self.total_score,
            "rank": self.rank,
            "allocation": f"{self.allocation_percent:.1f}%",
            "risk_level": self.risk_level,
        }

    def __post_init__(self):
        """验证数据有效性"""
        # 验证分数范围
        for score_name in ["regime_score", "policy_score", "sentiment_score", "signal_score"]:
            score = getattr(self, score_name)
            if not 0 <= score <= 100:
                raise ValueError(f"{score_name} 必须在 0-100 之间，当前为 {score}")

        # 验证配置比例
        if not 0 <= self.allocation_percent <= 100:
            raise ValueError(f"allocation_percent 必须在 0-100 之间，当前为 {self.allocation_percent}")
