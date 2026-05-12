"""
资产分析模块 - Domain 层值对象

值对象（Value Objects）是不可变的、通过属性值相等的对象。
用于封装评分过程中的配置和上下文信息。
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class WeightConfig:
    """
    权重配置（值对象）

    定义多维度评分中各维度的权重分配。
    权重总和必须等于 1.0。
    """
    regime_weight: float = 0.40
    policy_weight: float = 0.25
    sentiment_weight: float = 0.20
    signal_weight: float = 0.15

    def __post_init__(self):
        """验证权重配置"""
        # 1. 先验证每个权重为非负数
        for name, value in [
            ("regime_weight", self.regime_weight),
            ("policy_weight", self.policy_weight),
            ("sentiment_weight", self.sentiment_weight),
            ("signal_weight", self.signal_weight),
        ]:
            if value < 0:
                raise ValueError(f"{name} 必须为非负数，当前为 {value}")

        # 2. 再验证权重总和为 1.0（容差 0.01）
        total = (
            self.regime_weight +
            self.policy_weight +
            self.sentiment_weight +
            self.signal_weight
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"权重总和必须为1.0，当前为 {total:.4f}")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "regime": self.regime_weight,
            "policy": self.policy_weight,
            "sentiment": self.sentiment_weight,
            "signal": self.signal_weight,
        }


@dataclass(frozen=True)
class ScoreContext:
    """
    评分上下文（值对象）

    封装评分时所需的外部环境信息。
    这些信息会影响资产的各维度得分计算。
    """
    current_regime: str            # 当前 Regime: Recovery/Overheat/Stagflation/Deflation
    policy_level: str              # 政策档位: P0/P1/P2/P3
    sentiment_index: float         # 情绪指数: -3.0 ~ +3.0
    active_signals: list           # 激活的投资信号列表
    score_date: date = date.today()

    def __post_init__(self):
        """验证数据有效性"""
        # 验证情绪指数范围
        if not -3.0 <= self.sentiment_index <= 3.0:
            raise ValueError(f"sentiment_index 必须在 -3.0 到 +3.0 之间，当前为 {self.sentiment_index}")

        # 验证 Regime 值
        valid_regimes = {"Recovery", "Overheat", "Stagflation", "Deflation"}
        if self.current_regime not in valid_regimes:
            raise ValueError(f"current_regime 必须是 {valid_regimes} 之一，当前为 {self.current_regime}")

        # 验证 Policy 档位
        valid_policies = {"P0", "P1", "P2", "P3"}
        if self.policy_level not in valid_policies:
            raise ValueError(f"policy_level 必须是 {valid_policies} 之一，当前为 {self.policy_level}")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "regime": self.current_regime,
            "policy_level": self.policy_level,
            "sentiment_index": self.sentiment_index,
            "active_signals_count": len(self.active_signals),
            "score_date": self.score_date.isoformat(),
        }
