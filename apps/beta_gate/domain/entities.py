"""
Beta Gate Domain Entities

硬闸门过滤的核心实体定义。
通过 Regime + Policy + 风险画像的组合约束，实现资产的"可见性裁剪"。

仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class GateStatus(Enum):
    """
    闸门状态枚举

    定义资产在 Beta Gate 评估后可能的状态。
    """

    PASSED = "passed"
    """通过闸门，资产可见"""

    BLOCKED_REGIME = "blocked_regime"
    """被 Regime 约束拦截"""

    BLOCKED_POLICY = "blocked_policy"
    """被 Policy 约束拦截"""

    BLOCKED_RISK = "blocked_risk"
    """被风险画像约束拦截"""

    BLOCKED_CONFIDENCE = "blocked_confidence"
    """被置信度约束拦截"""

    BLOCKED_PORTFOLIO = "blocked_portfolio"
    """被组合约束拦截"""

    WATCH = "watch"
    """进入观察列表（暂不可执行）"""


class RiskProfile(Enum):
    """
    风险画像枚举

    定义投资者的风险偏好类型。
    """

    CONSERVATIVE = "conservative"
    """保守型：低风险偏好，优先保护本金"""

    BALANCED = "balanced"
    """平衡型：中等风险偏好，追求风险调整后收益"""

    AGGRESSIVE = "aggressive"
    """激进型：高风险偏好，追求最大收益"""


@dataclass(frozen=True)
class RegimeConstraint:
    """
    Regime 约束配置

    定义哪些 Regime 环境下允许该资产/策略可见。

    Attributes:
        allowed_regimes: 允许的 Regime 列表（如 ["Recovery", "Overheat"]）
        min_confidence: 最低置信度阈值
        require_high_confidence: 是否要求高置信度（>0.5）
        disallowed_regimes: 明确禁止的 Regime 列表（优先级高于 allowed）

    Example:
        >>> constraint = RegimeConstraint(
        ...     allowed_regimes=["Recovery", "Overheat"],
        ...     min_confidence=0.4,
        ...     require_high_confidence=False
        ... )
        >>> is_allowed, reason = constraint.is_regime_allowed("Recovery", 0.6)
    """

    allowed_regimes: List[str] = field(default_factory=list)
    min_confidence: float = 0.3
    require_high_confidence: bool = False
    disallowed_regimes: List[str] = field(default_factory=list)
    # Backward compatibility fields
    current_regime: Optional[str] = None
    confidence: Optional[float] = None
    allowed_asset_classes: List[str] = field(default_factory=list)

    def is_regime_allowed(self, regime: str, confidence: float) -> Tuple[bool, str]:
        """
        检查 Regime 是否允许

        Args:
            regime: 当前 Regime（如 "Recovery"、"Overheat"）
            confidence: Regime 置信度（0-1）

        Returns:
            (是否允许, 原因描述)
        """
        # 优先检查明确禁止的 Regime
        if regime in self.disallowed_regimes:
            return False, f"Regime {regime} 在禁止列表中"

        # 检查是否在允许列表中
        if self.allowed_regimes and regime not in self.allowed_regimes:
            return False, f"Regime {regime} 不在允许列表中（需要: {', '.join(self.allowed_regimes)}）"

        # 检查置信度下限
        if confidence < self.min_confidence:
            return False, f"置信度 {confidence:.2f} 低于阈值 {self.min_confidence}"

        # 检查是否要求高置信度
        if self.require_high_confidence and confidence <= 0.5:
            return False, f"要求高置信度，当前仅 {confidence:.2f}"

        return True, ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "allowed_regimes": self.allowed_regimes,
            "min_confidence": self.min_confidence,
            "require_high_confidence": self.require_high_confidence,
            "disallowed_regimes": self.disallowed_regimes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegimeConstraint":
        """从字典创建"""
        return cls(
            allowed_regimes=data.get("allowed_regimes", []),
            min_confidence=data.get("min_confidence", 0.3),
            require_high_confidence=data.get("require_high_confidence", False),
            disallowed_regimes=data.get("disallowed_regimes", []),
        )


@dataclass(frozen=True)
class PolicyConstraint:
    """
    Policy 约束配置

    定义 Policy 档位对资产可见性的约束。

    Attributes:
        max_allowed_level: 最高允许档位（0-3，P0-P3）
        veto_on_p3: P3 档位是否自动否决
        allowed_on_p2: P2 档位是否允许（默认 False）
        allowed_on_p1: P1 档位是否允许（默认 True）

    Example:
        >>> constraint = PolicyConstraint(
        ...     max_allowed_level=2,
        ...     veto_on_p3=True
        ... )
        >>> is_allowed, reason = constraint.is_policy_allowed(1)
    """

    max_allowed_level: int = 2
    veto_on_p3: bool = True
    allowed_on_p2: bool = False
    allowed_on_p1: bool = True
    # Backward compatibility fields
    current_level: int = 0
    max_risk_exposure: float = 100.0
    hard_exclusions: List[str] = field(default_factory=list)

    def is_policy_allowed(self, policy_level: int) -> Tuple[bool, str]:
        """
        检查 Policy 是否允许

        Args:
            policy_level: Policy 档位（0-3）

        Returns:
            (是否允许, 原因描述)
        """
        # P3 自动否决
        if self.veto_on_p3 and policy_level >= 3:
            return False, f"P{policy_level} 档位自动否决"

        # 检查是否超过最大允许档位
        if policy_level > self.max_allowed_level:
            return False, f"Policy 档位 P{policy_level} 超过最大允许 P{self.max_allowed_level}"

        # P2 档位特殊处理
        if policy_level == 2 and not self.allowed_on_p2:
            return False, f"P2 档位下不允许该资产"

        # P1 档位特殊处理
        if policy_level == 1 and not self.allowed_on_p1:
            return False, f"P1 档位下不允许该资产"

        return True, ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "max_allowed_level": self.max_allowed_level,
            "veto_on_p3": self.veto_on_p3,
            "allowed_on_p2": self.allowed_on_p2,
            "allowed_on_p1": self.allowed_on_p1,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyConstraint":
        """从字典创建"""
        return cls(
            max_allowed_level=data.get("max_allowed_level", 2),
            veto_on_p3=data.get("veto_on_p3", True),
            allowed_on_p2=data.get("allowed_on_p2", False),
            allowed_on_p1=data.get("allowed_on_p1", True),
        )


@dataclass(frozen=True)
class PortfolioConstraint:
    """
    组合约束配置

    定义组合层面的约束条件。

    Attributes:
        max_total_position_pct: 最大总仓位百分比
        max_single_position_pct: 单资产最大仓位百分比
        max_correlated_exposure: 最大相关性敞口百分比
        require_diversification: 是否要求分散化
        min_cash_pct: 最低现金比例

    Example:
        >>> constraint = PortfolioConstraint(
        ...     max_total_position_pct=95.0,
        ...     max_single_position_pct=20.0
        ... )
    """

    max_total_position_pct: float = 95.0
    max_single_position_pct: float = 20.0
    max_correlated_exposure: float = 60.0
    require_diversification: bool = True
    min_cash_pct: float = 5.0
    # Backward compatibility fields
    max_positions: Optional[int] = None
    max_single_position_weight: Optional[float] = None
    max_concentration_ratio: Optional[float] = None

    def __post_init__(self):
        if self.max_single_position_weight is not None:
            object.__setattr__(self, "max_single_position_pct", self.max_single_position_weight)
        if self.max_concentration_ratio is not None:
            object.__setattr__(self, "max_correlated_exposure", self.max_concentration_ratio)

    def check_position_limit(
        self,
        current_value: float,
        new_position_value: float,
        total_portfolio_value: float,
        existing_positions: Optional[Dict[str, float]] = None,
    ) -> Tuple[bool, str]:
        """
        检查仓位限制

        Args:
            current_value: 当前持仓价值
            new_position_value: 新建仓位价值
            total_portfolio_value: 组合总价值
            existing_positions: 现有持仓（可选，用于相关性检查）

        Returns:
            (是否允许, 原因描述)
        """
        new_total = current_value + new_position_value

        if total_portfolio_value <= 0:
            return True, ""

        new_pct = (new_total / total_portfolio_value) * 100

        # 检查总仓位限制
        if new_pct > self.max_total_position_pct:
            return False, f"总仓位 {new_pct:.1f}% 超过限制 {self.max_total_position_pct}%"

        # 检查单资产仓位限制
        if (new_position_value / total_portfolio_value * 100) > self.max_single_position_pct:
            return False, f"单资产仓位 {new_position_value / total_portfolio_value * 100:.1f}% 超过限制 {self.max_single_position_pct}%"

        # 检查最低现金要求
        cash_pct = ((total_portfolio_value - new_total) / total_portfolio_value) * 100
        if cash_pct < self.min_cash_pct:
            return False, f"现金比例 {cash_pct:.1f}% 低于最低要求 {self.min_cash_pct}%"

        return True, ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "max_total_position_pct": self.max_total_position_pct,
            "max_single_position_pct": self.max_single_position_pct,
            "max_correlated_exposure": self.max_correlated_exposure,
            "require_diversification": self.require_diversification,
            "min_cash_pct": self.min_cash_pct,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PortfolioConstraint":
        """从字典创建"""
        return cls(
            max_total_position_pct=data.get("max_total_position_pct", 95.0),
            max_single_position_pct=data.get("max_single_position_pct", 20.0),
            max_correlated_exposure=data.get("max_correlated_exposure", 60.0),
            require_diversification=data.get("require_diversification", True),
            min_cash_pct=data.get("min_cash_pct", 5.0),
        )


@dataclass(frozen=True)
class GateDecision:
    """
    闸门决策结果

    记录 Beta Gate 评估的完整结果，包括各项检查的详细状态。

    Attributes:
        status: 闸门状态
        asset_code: 资产代码
        asset_class: 资产类别
        current_regime: 当前 Regime
        policy_level: 当前 Policy 档位
        regime_confidence: Regime 置信度
        evaluated_at: 评估时间
        regime_check: Regime 检查结果 (是否通过, 原因)
        policy_check: Policy 检查结果
        risk_check: 风险画像检查结果
        portfolio_check: 组合约束检查结果
        suggested_alternatives: 建议的替代资产
        waiting_period_days: 建议等待天数
        score: 综合评分（可选）

    Example:
        >>> decision = GateDecision(
        ...     status=GateStatus.PASSED,
        ...     asset_code="000001.SH",
        ...     asset_class="a_share金融",
        ...     current_regime="Recovery",
        ...     policy_level=0,
        ...     regime_confidence=0.7,
        ...     evaluated_at=datetime.now()
        ... )
        >>> if decision.is_passed:
        ...     print(f"{decision.asset_code} 通过闸门")
    """

    status: GateStatus
    asset_code: str
    asset_class: str
    current_regime: str
    policy_level: int
    regime_confidence: float
    evaluated_at: datetime
    regime_check: Tuple[bool, str] = (True, "")
    policy_check: Tuple[bool, str] = (True, "")
    risk_check: Tuple[bool, str] = (True, "")
    portfolio_check: Tuple[bool, str] = (True, "")
    suggested_alternatives: List[str] = field(default_factory=list)
    waiting_period_days: Optional[int] = None
    score: Optional[float] = None

    @property
    def is_passed(self) -> bool:
        """是否通过闸门"""
        return self.status == GateStatus.PASSED

    @property
    def is_blocked(self) -> bool:
        """是否被拦截"""
        return self.status.value.startswith("blocked_")

    @property
    def is_watch(self) -> bool:
        """是否进入观察列表"""
        return self.status == GateStatus.WATCH

    @property
    def blocking_reason(self) -> str:
        """
        获取拦截原因

        Returns:
            主要拦截原因的描述
        """
        if self.is_passed:
            return ""

        checks = [
            ("Regime", self.regime_check),
            ("Policy", self.policy_check),
            ("Risk", self.risk_check),
            ("Portfolio", self.portfolio_check),
        ]

        for name, (passed, reason) in checks:
            if not passed:
                return f"[{name}] {reason}"

        return "未知原因"

    @property
    def all_checks_passed(self) -> bool:
        """所有检查是否都通过"""
        return all(
            check[0]
            for check in [
                self.regime_check,
                self.policy_check,
                self.risk_check,
                self.portfolio_check,
            ]
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "status": self.status.value,
            "asset_code": self.asset_code,
            "asset_class": self.asset_class,
            "current_regime": self.current_regime,
            "policy_level": self.policy_level,
            "regime_confidence": self.regime_confidence,
            "evaluated_at": self.evaluated_at.isoformat(),
            "regime_check": {"passed": self.regime_check[0], "reason": self.regime_check[1]},
            "policy_check": {"passed": self.policy_check[0], "reason": self.policy_check[1]},
            "risk_check": {"passed": self.risk_check[0], "reason": self.risk_check[1]},
            "portfolio_check": {"passed": self.portfolio_check[0], "reason": self.portfolio_check[1]},
            "suggested_alternatives": self.suggested_alternatives,
            "waiting_period_days": self.waiting_period_days,
            "score": self.score,
        }


@dataclass(frozen=True)
class GateConfig:
    """
    闸门全局配置

    定义 Beta Gate 的完整约束配置。

    Attributes:
        config_id: 配置唯一标识
        risk_profile: 风险画像
        regime_constraint: Regime 约束
        policy_constraint: Policy 约束
        portfolio_constraint: 组合约束
        version: 配置版本
        is_active: 是否激活
        effective_date: 生效日期
        expires_at: 过期日期（可选）

    Example:
        >>> config = GateConfig(
        ...     config_id="gate_config_balanced_v1",
        ...     risk_profile=RiskProfile.BALANCED,
        ...     regime_constraint=RegimeConstraint(...),
        ...     policy_constraint=PolicyConstraint(...),
        ...     portfolio_constraint=PortfolioConstraint(...)
        ... )
    """

    config_id: str
    risk_profile: RiskProfile
    regime_constraint: RegimeConstraint
    policy_constraint: PolicyConstraint
    portfolio_constraint: PortfolioConstraint
    version: int = 1
    is_active: bool = True
    is_valid: Optional[bool] = None
    effective_date: date = field(default_factory=date.today)
    expires_at: Optional[date] = None

    def __post_init__(self):
        if self.is_valid is None:
            object.__setattr__(self, "is_valid", self.is_active and not self.is_expired)

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        if self.expires_at is None:
            return False
        return date.today() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "config_id": self.config_id,
            "risk_profile": self.risk_profile.value,
            "regime_constraint": self.regime_constraint.to_dict(),
            "policy_constraint": self.policy_constraint.to_dict(),
            "portfolio_constraint": self.portfolio_constraint.to_dict(),
            "version": self.version,
            "is_active": self.is_active,
            "is_valid": self.is_valid,
            "effective_date": self.effective_date.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GateConfig":
        """从字典创建"""
        return cls(
            config_id=data["config_id"],
            risk_profile=RiskProfile(data["risk_profile"]),
            regime_constraint=RegimeConstraint.from_dict(data["regime_constraint"]),
            policy_constraint=PolicyConstraint.from_dict(data["policy_constraint"]),
            portfolio_constraint=PortfolioConstraint.from_dict(data["portfolio_constraint"]),
            version=data.get("version", 1),
            is_active=data.get("is_active", True),
            effective_date=date.fromisoformat(data.get("effective_date", date.today().isoformat())),
            expires_at=date.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
        )


@dataclass(frozen=True)
class VisibilityUniverse:
    """
    可见性宇宙

    定义当前环境下的可见资产集合。

    Attributes:
        as_of: 截止日期
        regime_snapshot_id: Regime 快照 ID
        policy_snapshot_id: Policy 快照 ID
        risk_profile: 风险画像
        visible_asset_categories: 可见资产类别列表
        visible_strategies: 可见策略列表
        hard_exclusions: 硬性排除列表 [(asset_class, reason), ...]
        watch_list: 观察列表
        notes: 备注

    Example:
        >>> universe = VisibilityUniverse(
        ...     as_of=date.today(),
        ...     regime_snapshot_id="regime_123",
        ...     policy_snapshot_id="policy_456",
        ...     risk_profile=RiskProfile.BALANCED,
        ...     visible_asset_categories=["a_share_growth", "bond"],
        ...     visible_strategies=["momentum", "value"],
        ...     hard_exclusions=[("commodity", "P3档位禁止")]
        ... )
    """

    as_of: date
    regime_snapshot_id: str
    policy_snapshot_id: str
    risk_profile: RiskProfile
    visible_asset_categories: List[str] = field(default_factory=list)
    visible_strategies: List[str] = field(default_factory=list)
    hard_exclusions: List[Tuple[str, str]] = field(default_factory=list)
    watch_list: List[str] = field(default_factory=list)
    notes: str = ""

    def is_asset_visible(self, asset_class: str) -> bool:
        """
        检查资产类别是否可见

        Args:
            asset_class: 资产类别

        Returns:
            是否可见
        """
        return asset_class in self.visible_asset_categories

    def is_strategy_visible(self, strategy: str) -> bool:
        """
        检查策略是否可见

        Args:
            strategy: 策略名称

        Returns:
            是否可见
        """
        return strategy in self.visible_strategies

    def get_exclusion_reason(self, asset_class: str) -> Optional[str]:
        """
        获取资产被排除的原因

        Args:
            asset_class: 资产类别

        Returns:
            排除原因，如果未被排除则返回 None
        """
        for excluded_asset, reason in self.hard_exclusions:
            if excluded_asset == asset_class:
                return reason
        return None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "as_of": self.as_of.isoformat(),
            "regime_snapshot_id": self.regime_snapshot_id,
            "policy_snapshot_id": self.policy_snapshot_id,
            "risk_profile": self.risk_profile.value,
            "visible_asset_categories": self.visible_asset_categories,
            "visible_strategies": self.visible_strategies,
            "hard_exclusions": self.hard_exclusions,
            "watch_list": self.watch_list,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisibilityUniverse":
        """从字典创建"""
        return cls(
            as_of=date.fromisoformat(data["as_of"]),
            regime_snapshot_id=data["regime_snapshot_id"],
            policy_snapshot_id=data["policy_snapshot_id"],
            risk_profile=RiskProfile(data["risk_profile"]),
            visible_asset_categories=data.get("visible_asset_categories", []),
            visible_strategies=data.get("visible_strategies", []),
            hard_exclusions=data.get("hard_exclusions", []),
            watch_list=data.get("watch_list", []),
            notes=data.get("notes", ""),
        )


# ========== 便捷工厂函数 ==========


def create_gate_config(
    risk_profile: RiskProfile = RiskProfile.BALANCED,
    allowed_regimes: Optional[List[str]] = None,
    min_confidence: float = 0.3,
    max_policy_level: int = 2,
    veto_on_p3: bool = True,
    max_total_position: float = 95.0,
    max_single_position: float = 20.0,
) -> GateConfig:
    """
    创建闸门配置的便捷函数

    Args:
        risk_profile: 风险画像
        allowed_regimes: 允许的 Regime 列表
        min_confidence: 最低置信度
        max_policy_level: 最高允许 Policy 档位
        veto_on_p3: P3 自动否决
        max_total_position: 最大总仓位
        max_single_position: 最大单资产仓位

    Returns:
        GateConfig 实例
    """
    from uuid import uuid4

    return GateConfig(
        config_id=str(uuid4()),
        risk_profile=risk_profile,
        regime_constraint=RegimeConstraint(
            allowed_regimes=allowed_regimes or ["Recovery", "Overheat", "Deflation", "Stagflation"],
            min_confidence=min_confidence,
        ),
        policy_constraint=PolicyConstraint(
            max_allowed_level=max_policy_level,
            veto_on_p3=veto_on_p3,
        ),
        portfolio_constraint=PortfolioConstraint(
            max_total_position_pct=max_total_position,
            max_single_position_pct=max_single_position,
        ),
    )


def get_default_configs() -> Dict[RiskProfile, GateConfig]:
    """
    获取默认的闸门配置

    Returns:
        风险画像到配置的映射
    """
    return {
        RiskProfile.CONSERVATIVE: create_gate_config(
            risk_profile=RiskProfile.CONSERVATIVE,
            allowed_regimes=["Recovery", "Deflation"],
            min_confidence=0.5,
            max_policy_level=1,
            veto_on_p3=True,
            max_total_position=80.0,
            max_single_position=15.0,
        ),
        RiskProfile.BALANCED: create_gate_config(
            risk_profile=RiskProfile.BALANCED,
            allowed_regimes=["Recovery", "Overheat", "Deflation"],
            min_confidence=0.4,
            max_policy_level=2,
            veto_on_p3=True,
            max_total_position=90.0,
            max_single_position=20.0,
        ),
        RiskProfile.AGGRESSIVE: create_gate_config(
            risk_profile=RiskProfile.AGGRESSIVE,
            allowed_regimes=["Recovery", "Overheat", "Deflation", "Stagflation"],
            min_confidence=0.3,
            max_policy_level=2,
            veto_on_p3=False,
            max_total_position=95.0,
            max_single_position=25.0,
        ),
    }
