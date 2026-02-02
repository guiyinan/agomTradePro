"""
Asset Allocation Matrix Domain Layer

Defines the allocation matrix for different Regime and risk preference combinations.
Pure domain logic using only Python standard library.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class RegimeType(Enum):
    """Regime类型枚举"""
    RECOVERY = "Recovery"       # 复苏：增长↑，通胀↓
    OVERHEAT = "Overheat"       # 过热：增长↑，通胀↑
    STAGFLATION = "Stagflation" # 滞胀：增长↓，通胀↑
    DEFLATION = "Deflation"     # 衰退：增长↓，通胀↓


class RiskProfile(Enum):
    """风险偏好枚举"""
    AGGRESSIVE = "aggressive"   # 激进型：追求高收益，能承受高波动
    MODERATE = "moderate"       # 稳健型：平衡收益与风险
    CONSERVATIVE = "conservative" # 保守型：优先保值，波动容忍低
    DEFENSIVE = "defensive"     # 防御型：极度保守，避免损失


@dataclass(frozen=True)
class AssetAllocation:
    """资产配置比例（值对象）"""
    equity: float      # 权益类（股票、股票基金）
    fixed_income: float # 固定收益（债券、债券基金）
    commodity: float   # 商品类（黄金ETF、商品基金）
    cash: float        # 现金类（货币基金、现金）

    def __post_init__(self):
        """验证配置比例总和为1"""
        total = self.equity + self.fixed_income + self.commodity + self.cash
        if not (0.99 <= total <= 1.01):  # 允许轻微浮点误差
            raise ValueError(f"配置比例总和必须为1，当前为{total:.4f}")

    def to_percentage_dict(self) -> Dict[str, float]:
        """转换为百分比字典"""
        return {
            "equity": round(self.equity * 100, 1),
            "fixed_income": round(self.fixed_income * 100, 1),
            "commodity": round(self.commodity * 100, 1),
            "cash": round(self.cash * 100, 1),
        }


@dataclass(frozen=True)
class AllocationTarget:
    """资产配置目标（包含推荐理由）"""
    allocation: AssetAllocation
    reasoning: str  # 配置理由
    expected_return: Optional[float] = None  # 预期年化收益
    expected_volatility: Optional[float] = None  # 预期波动率
    sharpe_ratio: Optional[float] = None  # 夏普比率


# ============================================================
# 资产配置矩阵定义
# ============================================================

# 16种配置矩阵：4种Regime × 4种风险偏好
# 每个数字表示该资产类别的配置比例

ALLOCATION_MATRIX: Dict[RegimeType, Dict[RiskProfile, AllocationTarget]] = {
    # ==================== RECOVERY（复苏期）：增长↑，通胀↓ ====================
    # 特征：经济复苏，企业盈利改善，股市表现较好
    RegimeType.RECOVERY: {
        RiskProfile.AGGRESSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.70, fixed_income=0.15, commodity=0.05, cash=0.10),
            reasoning="复苏期权益资产表现优异，激进型可高配股票，充分享受经济增长红利",
            expected_return=0.12,
            expected_volatility=0.18,
            sharpe_ratio=0.67,
        ),
        RiskProfile.MODERATE: AllocationTarget(
            allocation=AssetAllocation(equity=0.55, fixed_income=0.25, commodity=0.05, cash=0.15),
            reasoning="复苏期股市走强，稳健型适度增加权益仓位，债券提供稳定收益",
            expected_return=0.09,
            expected_volatility=0.14,
            sharpe_ratio=0.64,
        ),
        RiskProfile.CONSERVATIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.40, fixed_income=0.35, commodity=0.05, cash=0.20),
            reasoning="复苏期可适度参与股市，保守型以债券为主，权益仓位适中",
            expected_return=0.06,
            expected_volatility=0.10,
            sharpe_ratio=0.60,
        ),
        RiskProfile.DEFENSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.25, fixed_income=0.45, commodity=0.05, cash=0.25),
            reasoning="防御型优先保值，复苏期少量参与股市，主要持有债券和现金",
            expected_return=0.04,
            expected_volatility=0.07,
            sharpe_ratio=0.57,
        ),
    },

    # ==================== OVERHEAT（过热期）：增长↑，通胀↑ ====================
    # 特征：经济过热，通胀压力，央行可能收紧，股市波动加大
    RegimeType.OVERHEAT: {
        RiskProfile.AGGRESSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.50, fixed_income=0.20, commodity=0.15, cash=0.15),
            reasoning="过热期通胀上升，商品表现好，激进型可加配商品对冲通胀",
            expected_return=0.08,
            expected_volatility=0.20,
            sharpe_ratio=0.40,
        ),
        RiskProfile.MODERATE: AllocationTarget(
            allocation=AssetAllocation(equity=0.40, fixed_income=0.30, commodity=0.10, cash=0.20),
            reasoning="过热期政策收紧风险加大，适度降低权益，增加商品和债券",
            expected_return=0.06,
            expected_volatility=0.15,
            sharpe_ratio=0.40,
        ),
        RiskProfile.CONSERVATIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.25, fixed_income=0.40, commodity=0.10, cash=0.25),
            reasoning="过热期风险加大，保守型降低权益，增加债券和现金仓位",
            expected_return=0.04,
            expected_volatility=0.10,
            sharpe_ratio=0.40,
        ),
        RiskProfile.DEFENSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.15, fixed_income=0.45, commodity=0.10, cash=0.30),
            reasoning="防御型大幅降低风险，过热期以债券和现金为主",
            expected_return=0.03,
            expected_volatility=0.06,
            sharpe_ratio=0.50,
        ),
    },

    # ==================== STAGFLATION（滞胀期）：增长↓，通胀↑ ====================
    # 特征：经济停滞+通胀，最差宏观环境，股债双杀
    RegimeType.STAGFLATION: {
        RiskProfile.AGGRESSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.30, fixed_income=0.25, commodity=0.20, cash=0.25),
            reasoning="滞胀期股债双杀，激进型大幅降低权益，增加商品和现金避险",
            expected_return=0.03,
            expected_volatility=0.15,
            sharpe_ratio=0.20,
        ),
        RiskProfile.MODERATE: AllocationTarget(
            allocation=AssetAllocation(equity=0.20, fixed_income=0.35, commodity=0.15, cash=0.30),
            reasoning="滞胀期风险极高，稳健型以债券和现金为主，少量商品对冲通胀",
            expected_return=0.02,
            expected_volatility=0.12,
            sharpe_ratio=0.17,
        ),
        RiskProfile.CONSERVATIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.10, fixed_income=0.45, commodity=0.15, cash=0.30),
            reasoning="滞胀期极度不利，保守型以债券和现金为主，避免权益风险",
            expected_return=0.01,
            expected_volatility=0.08,
            sharpe_ratio=0.13,
        ),
        RiskProfile.DEFENSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.05, fixed_income=0.40, commodity=0.15, cash=0.40),
            reasoning="滞胀期防御型最大限度降低风险，以现金为主，商品对冲通胀",
            expected_return=0.00,
            expected_volatility=0.05,
            sharpe_ratio=0.00,
        ),
    },

    # ==================== DEFLATION（衰退期）：增长↓，通胀↓ ====================
    # 特征：经济衰退，通缩压力，央行宽松，债券表现好
    RegimeType.DEFLATION: {
        RiskProfile.AGGRESSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.40, fixed_income=0.35, commodity=0.05, cash=0.20),
            reasoning="衰退期债券表现优异，激进型适度配置债券，等待股市反弹机会",
            expected_return=0.05,
            expected_volatility=0.15,
            sharpe_ratio=0.33,
        ),
        RiskProfile.MODERATE: AllocationTarget(
            allocation=AssetAllocation(equity=0.25, fixed_income=0.45, commodity=0.05, cash=0.25),
            reasoning="衰退期央行宽松利好债券，稳健型以债券为主，降低权益仓位",
            expected_return=0.04,
            expected_volatility=0.10,
            sharpe_ratio=0.40,
        ),
        RiskProfile.CONSERVATIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.15, fixed_income=0.55, commodity=0.05, cash=0.25),
            reasoning="衰退期债券表现最佳，保守型以债券为主，现金防守",
            expected_return=0.03,
            expected_volatility=0.07,
            sharpe_ratio=0.43,
        ),
        RiskProfile.DEFENSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.10, fixed_income=0.50, commodity=0.05, cash=0.35),
            reasoning="防御型以债券和现金为主，衰退期最大限度降低波动",
            expected_return=0.02,
            expected_volatility=0.05,
            sharpe_ratio=0.40,
        ),
    },
}


# ============================================================
# Policy档位调整系数
# ============================================================

class PolicyLevel(Enum):
    """政策档位枚举"""
    P0 = "P0"  # 正常：无特殊政策干预
    P1 = "P1"  # 轻度限制：政策轻微收紧
    P2 = "P2"  # 中度限制：政策明显收紧
    P3 = "P3"  # 极度限制：政策极度收紧，危机模式


# Policy档位对权益仓位的调整系数
POLICY_EQUITY_ADJUSTMENT: Dict[PolicyLevel, float] = {
    PolicyLevel.P0: 1.0,   # 正常：不调整
    PolicyLevel.P1: 0.8,   # 轻度限制：权益仓位×0.8
    PolicyLevel.P2: 0.6,   # 中度限制：权益仓位×0.6
    PolicyLevel.P3: 0.3,   # 极度限制：权益仓位×0.3
}


def get_allocation_target(regime: str, risk_profile: str, policy_level: Optional[str] = None) -> AllocationTarget:
    """
    根据Regime和风险偏好获取目标配置

    Args:
        regime: 当前Regime（Recovery/Overheat/Stagflation/Deflation）
        risk_profile: 风险偏好（aggressive/moderate/conservative/defensive）
        policy_level: 政策档位（P0/P1/P2/P3），None表示P0

    Returns:
        AllocationTarget: 目标配置

    Raises:
        ValueError: 如果输入参数不在预设范围内
    """
    try:
        regime_enum = RegimeType(regime)
    except ValueError:
        raise ValueError(f"无效的Regime: {regime}，必须是 {list(RegimeType)} 之一")

    try:
        risk_enum = RiskProfile(risk_profile)
    except ValueError:
        raise ValueError(f"无效的风险偏好: {risk_profile}，必须是 {list(RiskProfile)} 之一")

    # 获取基础配置
    target = ALLOCATION_MATRIX[regime_enum][risk_enum]

    # 如果没有Policy档位，直接返回
    if policy_level is None:
        return target

    # 应用Policy档位调整
    try:
        policy_enum = PolicyLevel(policy_level)
    except ValueError:
        raise ValueError(f"无效的Policy档位: {policy_level}，必须是 {list(PolicyLevel)} 之一")

    adjustment_factor = POLICY_EQUITY_ADJUSTMENT[policy_enum]

    # 调整权益仓位，其他资产按比例重新分配
    original_equity = target.allocation.equity
    adjusted_equity = original_equity * adjustment_factor
    equity_reduction = original_equity - adjusted_equity

    # 减少的权益仓位按比例分配到债券和现金
    other_total = target.allocation.fixed_income + target.allocation.cash
    if other_total > 0:
        fixed_income_add = equity_reduction * (target.allocation.fixed_income / other_total)
        cash_add = equity_reduction * (target.allocation.cash / other_total)
    else:
        fixed_income_add = equity_reduction * 0.5
        cash_add = equity_reduction * 0.5

    adjusted_allocation = AssetAllocation(
        equity=adjusted_equity,
        fixed_income=target.allocation.fixed_income + fixed_income_add,
        commodity=target.allocation.commodity,  # 商品不变
        cash=target.allocation.cash + cash_add,
    )

    # 更新理由
    if adjustment_factor < 1.0:
        policy_note = f"【{policy_level}政策收紧】权益仓位已从{original_equity*100:.0f}%降至{adjusted_equity*100:.0f}%"
        reasoning = f"{target.reasoning}。{policy_note}"
    else:
        reasoning = target.reasoning

    return AllocationTarget(
        allocation=adjusted_allocation,
        reasoning=reasoning,
        expected_return=target.expected_return * (0.5 + 0.5 * adjustment_factor) if target.expected_return else None,
        expected_volatility=target.expected_volatility * 0.8 if target.expected_volatility else None,
        sharpe_ratio=target.sharpe_ratio * 0.9 if target.sharpe_ratio else None,
    )
