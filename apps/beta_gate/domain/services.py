"""
Beta Gate Domain Services

硬闸门过滤的核心业务逻辑实现。
提供资产可见性的评估算法。

仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .entities import (
    GateConfig,
    GateDecision,
    GateStatus,
    RiskProfile,
    VisibilityUniverse,
    get_default_configs,
)


logger = logging.getLogger(__name__)


class BetaGateEvaluator:
    """
    Beta Gate 评估器

    执行完整的闸门评估逻辑，包括 Regime、Policy、风险画像和组合约束检查。

    Attributes:
        config: 闸门配置

    Example:
        >>> evaluator = BetaGateEvaluator(config)
        >>> decision = evaluator.evaluate(
        ...     asset_code="000001.SH",
        ...     asset_class="a_share金融",
        ...     current_regime="Recovery",
        ...     regime_confidence=0.7,
        ...     policy_level=0
        ... )
        >>> if decision.is_passed:
        ...     print("资产可见")
    """

    def __init__(self, config: GateConfig):
        """
        初始化评估器

        Args:
            config: 闸门配置
        """
        self.config = config

    def evaluate(
        self,
        asset_code: str,
        asset_class: str,
        current_regime: str,
        regime_confidence: float,
        policy_level: int,
        current_portfolio_value: float = 0.0,
        new_position_value: float = 0.0,
        existing_positions: Optional[Dict[str, float]] = None,
    ) -> GateDecision:
        """
        执行完整的闸门评估

        按照以下顺序检查：
        1. Regime 约束
        2. Policy 约束
        3. 组合约束

        任一检查失败即返回拦截。

        Args:
            asset_code: 资产代码
            asset_class: 资产类别
            current_regime: 当前 Regime
            regime_confidence: Regime 置信度
            policy_level: Policy 档位（0-3）
            current_portfolio_value: 当前组合价值
            new_position_value: 新建仓位价值
            existing_positions: 现有持仓（用于相关性检查）

        Returns:
            GateDecision 决策结果
        """
        # Legacy path: dict-based constraints from older domain model.
        if self.config.regime_constraints:
            return self._evaluate_legacy(
                asset_code=asset_code,
                asset_class=asset_class,
                current_regime=current_regime,
                regime_confidence=regime_confidence,
                policy_level=policy_level,
                current_portfolio_value=current_portfolio_value,
                new_position_value=new_position_value,
            )

        # 1. Regime 检查
        regime_passed, regime_reason = self.config.regime_constraint.is_regime_allowed(
            current_regime, regime_confidence
        )

        if not regime_passed:
            return self._create_blocked_decision(
                status=GateStatus.BLOCKED_REGIME,
                asset_code=asset_code,
                asset_class=asset_class,
                current_regime=current_regime,
                policy_level=policy_level,
                regime_confidence=regime_confidence,
                regime_check=(regime_passed, regime_reason),
            )

        # 2. Policy 检查
        policy_passed, policy_reason = self.config.policy_constraint.is_policy_allowed(
            policy_level
        )

        if not policy_passed:
            return self._create_blocked_decision(
                status=GateStatus.BLOCKED_POLICY,
                asset_code=asset_code,
                asset_class=asset_class,
                current_regime=current_regime,
                policy_level=policy_level,
                regime_confidence=regime_confidence,
                regime_check=(regime_passed, regime_reason),
                policy_check=(policy_passed, policy_reason),
            )

        # 3. 组合约束检查（仅在提供了组合参数时执行）
        if current_portfolio_value > 0 or new_position_value > 0:
            portfolio_passed, portfolio_reason = self.config.portfolio_constraint.check_position_limit(
                current_value=current_portfolio_value,
                new_position_value=new_position_value,
                total_portfolio_value=current_portfolio_value + new_position_value,
                existing_positions=existing_positions,
            )

            if not portfolio_passed:
                return self._create_blocked_decision(
                    status=GateStatus.BLOCKED_PORTFOLIO,
                    asset_code=asset_code,
                    asset_class=asset_class,
                    current_regime=current_regime,
                    policy_level=policy_level,
                    regime_confidence=regime_confidence,
                    regime_check=(regime_passed, regime_reason),
                    policy_check=(policy_passed, policy_reason),
                    portfolio_check=(portfolio_passed, portfolio_reason),
                )

        # 全部通过
        return GateDecision(
            status=GateStatus.PASSED,
            asset_code=asset_code,
            asset_class=asset_class,
            current_regime=current_regime,
            policy_level=policy_level,
            regime_confidence=regime_confidence,
            evaluated_at=datetime.now(),
            regime_check=(regime_passed, regime_reason),
            policy_check=(policy_passed, policy_reason),
            portfolio_check=(True, ""),
            risk_check=(True, ""),
        )

    def _evaluate_legacy(
        self,
        asset_code: str,
        asset_class: str,
        current_regime: str,
        regime_confidence: float,
        policy_level: int,
        current_portfolio_value: float = 0.0,
        new_position_value: float = 0.0,
    ) -> GateDecision:
        """Backward-compatible evaluator for legacy dict-based gate configs."""
        if regime_confidence < self.config.confidence_threshold:
            return GateDecision(
                status=GateStatus.BLOCKED_CONFIDENCE,
                asset_code=asset_code,
                asset_class=asset_class,
                current_regime=current_regime,
                policy_level=policy_level,
                regime_confidence=regime_confidence,
                is_passed=False,
                blocking_reason=f"confidence below threshold: {regime_confidence:.2f} < {self.config.confidence_threshold:.2f}",
                evaluation_details={"confidence_check": "failed"},
            )

        regime_match = self.config.regime_constraints.get(current_regime)
        if regime_match is None:
            return GateDecision(
                status=GateStatus.BLOCKED_REGIME,
                asset_code=asset_code,
                asset_class=asset_class,
                current_regime=current_regime,
                policy_level=policy_level,
                regime_confidence=regime_confidence,
                is_passed=False,
                blocking_reason=f"regime {current_regime} not configured",
                evaluation_details={"regime_check": "failed"},
            )

        if asset_code in regime_match.forbidden_assets or asset_class in [str(x).lower() for x in regime_match.forbidden_categories]:
            return GateDecision(
                status=GateStatus.BLOCKED_REGIME,
                asset_code=asset_code,
                asset_class=asset_class,
                current_regime=current_regime,
                policy_level=policy_level,
                regime_confidence=regime_confidence,
                is_passed=False,
                blocking_reason="forbidden by regime constraint",
                evaluation_details={"regime_check": "failed"},
            )

        if regime_match.allowed_categories:
            allowed_categories = {str(x).lower() for x in regime_match.allowed_categories}
            if asset_class.lower() not in allowed_categories:
                # fallback: allow if caller passes broad chinese class names for A-share.
                if not (asset_class.startswith("a_share") and any("a_share" in x for x in allowed_categories)):
                    return GateDecision(
                        status=GateStatus.BLOCKED_REGIME,
                        asset_code=asset_code,
                        asset_class=asset_class,
                        current_regime=current_regime,
                        policy_level=policy_level,
                        regime_confidence=regime_confidence,
                        is_passed=False,
                        blocking_reason="forbidden category in regime",
                        evaluation_details={"regime_check": "failed"},
                    )

        policy_match = self.config.policy_constraints.get(policy_level)
        if policy_match and asset_class in [str(x).lower() for x in policy_match.forbidden_categories]:
            return GateDecision(
                status=GateStatus.BLOCKED_POLICY,
                asset_code=asset_code,
                asset_class=asset_class,
                current_regime=current_regime,
                policy_level=policy_level,
                regime_confidence=regime_confidence,
                is_passed=False,
                blocking_reason="forbidden by policy constraint",
                evaluation_details={"policy_check": "failed"},
            )

        if current_portfolio_value > 0:
            ratio = new_position_value / current_portfolio_value if current_portfolio_value else 0.0
            if ratio > self.config.portfolio_exposure_limit:
                return GateDecision(
                    status=GateStatus.BLOCKED_PORTFOLIO,
                    asset_code=asset_code,
                    asset_class=asset_class,
                    current_regime=current_regime,
                    policy_level=policy_level,
                    regime_confidence=regime_confidence,
                    is_passed=False,
                    blocking_reason="portfolio exposure limit exceeded",
                    evaluation_details={"portfolio_check": "failed"},
                )

        return GateDecision(
            status=GateStatus.PASSED,
            asset_code=asset_code,
            asset_class=asset_class,
            current_regime=current_regime,
            policy_level=policy_level,
            regime_confidence=regime_confidence,
            is_passed=True,
            blocking_reason="",
            evaluation_details={},
        )

    def evaluate_batch(
        self,
        assets: List[Tuple[str, str]],  # [(asset_code, asset_class), ...]
        current_regime: str,
        regime_confidence: float,
        policy_level: int,
        current_portfolio_value: float = 0.0,
    ) -> List[GateDecision]:
        """
        批量评估多个资产

        Args:
            assets: 资产列表 [(asset_code, asset_class), ...]
            current_regime: 当前 Regime
            regime_confidence: Regime 置信度
            policy_level: Policy 档位
            current_portfolio_value: 当前组合价值

        Returns:
            GateDecision 列表
        """
        decisions = []

        for asset_code, asset_class in assets:
            decision = self.evaluate(
                asset_code=asset_code,
                asset_class=asset_class,
                current_regime=current_regime,
                regime_confidence=regime_confidence,
                policy_level=policy_level,
                current_portfolio_value=current_portfolio_value,
            )
            decisions.append(decision)

        return decisions

    def _create_blocked_decision(
        self,
        status: GateStatus,
        asset_code: str,
        asset_class: str,
        current_regime: str,
        policy_level: int,
        regime_confidence: float,
        regime_check: Tuple[bool, str] = (True, ""),
        policy_check: Tuple[bool, str] = (True, ""),
        portfolio_check: Tuple[bool, str] = (True, ""),
    ) -> GateDecision:
        """创建被拦截的决策"""
        return GateDecision(
            status=status,
            asset_code=asset_code,
            asset_class=asset_class,
            current_regime=current_regime,
            policy_level=policy_level,
            regime_confidence=regime_confidence,
            evaluated_at=datetime.now(),
            regime_check=regime_check,
            policy_check=policy_check,
            portfolio_check=portfolio_check,
            risk_check=(True, ""),
        )


class VisibilityUniverseBuilder:
    """
    可见性宇宙构建器

    根据当前环境状态构建可见性宇宙。

    Attributes:
        configs: 不同风险画像的配置映射

    Example:
        >>> builder = VisibilityUniverseBuilder()
        >>> universe = builder.build(
        ...     current_regime="Recovery",
        ...     regime_confidence=0.7,
        ...     policy_level=0,
        ...     risk_profile=RiskProfile.BALANCED
        ... )
    """

    def __init__(self, configs: Optional[Dict[RiskProfile, GateConfig]] = None):
        """
        初始化构建器

        Args:
            configs: 风险画像到配置的映射（默认使用默认配置）
        """
        self.configs = configs or get_default_configs()

    def build(
        self,
        current_regime: str,
        regime_confidence: float,
        policy_level: int,
        risk_profile: RiskProfile,
        config_selector: Optional["GateConfigSelector"] = None,
        regime_snapshot_id: str = "",
        policy_snapshot_id: str = "",
        candidate_assets: Optional[List[Tuple[str, str]]] = None,
    ) -> VisibilityUniverse:
        """
        构建可见性宇宙

        Args:
            current_regime: 当前 Regime
            regime_confidence: Regime 置信度
            policy_level: Policy 档位
            risk_profile: 风险画像
            regime_snapshot_id: Regime 快照 ID
            policy_snapshot_id: Policy 快照 ID
            candidate_assets: 候选资产列表 [(asset_code, asset_class), ...]

        Returns:
            VisibilityUniverse 实例
        """
        from datetime import date

        if config_selector is not None:
            config = config_selector.get_config(risk_profile)
        else:
            config = self.configs.get(risk_profile)
            if config is None:
                config = get_default_configs()[risk_profile]

        # 评估候选资产
        visible_assets = []
        hard_exclusions = []
        watch_list = []

        if candidate_assets:
            evaluator = BetaGateEvaluator(config)
            decisions = evaluator.evaluate_batch(
                assets=candidate_assets,
                current_regime=current_regime,
                regime_confidence=regime_confidence,
                policy_level=policy_level,
            )

            for decision in decisions:
                if decision.is_passed:
                    visible_assets.append((decision.asset_code, decision.asset_class))
                elif decision.is_watch:
                    watch_list.append(decision.asset_code)
                else:
                    hard_exclusions.append((decision.asset_code, decision.blocking_reason))

        # 提取可见资产类别（legacy: prefer explicit visibility map if provided）
        if config.asset_category_visibility:
            visible_asset_categories = [k for k, v in config.asset_category_visibility.items() if v]
            hard_exclusions.extend([k for k, v in config.asset_category_visibility.items() if not v])
        else:
            visible_asset_categories = list(set(asset_class for _, asset_class in visible_assets))

        policy_match = config.policy_constraints.get(policy_level)
        if policy_match:
            for c in policy_match.forbidden_categories:
                if c not in hard_exclusions:
                    hard_exclusions.append(c)

        if regime_confidence < config.confidence_threshold and visible_asset_categories:
            watch_list.extend([str(c) for c in visible_asset_categories])

        # 根据环境确定可见策略
        visible_strategies = self._determine_visible_strategies(
            current_regime, policy_level, risk_profile
        )

        return VisibilityUniverse(
            as_of=date.today(),
            regime_snapshot_id=regime_snapshot_id,
            policy_snapshot_id=policy_snapshot_id,
            risk_profile=risk_profile,
            visible_asset_categories=visible_asset_categories,
            visible_strategies=visible_strategies,
            hard_exclusions=hard_exclusions,
            watch_list=watch_list,
            notes=f"Regime: {current_regime}, Policy: P{policy_level}",
            current_regime=current_regime,
            policy_level=policy_level,
            regime_confidence=regime_confidence,
        )

    def _determine_visible_strategies(
        self,
        current_regime: str,
        policy_level: int,
        risk_profile: RiskProfile,
    ) -> List[str]:
        """
        根据环境确定可见策略

        Args:
            current_regime: 当前 Regime
            policy_level: Policy 档位
            risk_profile: 风险画像

        Returns:
            可见策略列表
        """
        # 基础策略（所有环境都可用）
        base_strategies = ["observe"]

        # 根据 Regime 添加策略
        regime_strategies = {
            "Recovery": ["momentum", "growth", "discretionary"],
            "Overheat": ["value", "commodity", "inflation_hedge"],
            "Stagflation": ["defensive", "quality", "cash_equivalent"],
            "Deflation": ["bond", "dividend", "stable"],
        }

        policy_level_num = self._policy_level_num(policy_level)

        # 根据 Policy 档位调整
        if policy_level_num >= 2:
            # P2/P3: 限制风险策略
            regime_strategies = {
                k: [s for s in v if s in ["observe", "defensive", "bond", "cash_equivalent"]]
                for k, v in regime_strategies.items()
            }

        # 根据风险画像调整
        if risk_profile == RiskProfile.CONSERVATIVE:
            # 保守型：移除高风险策略
            regime_strategies = {
                k: [s for s in v if s not in ["momentum", "commodity"]]
                for k, v in regime_strategies.items()
            }

        # 合并策略
        visible = base_strategies + regime_strategies.get(current_regime, [])

        # 去重并排序
        return sorted(set(visible))

    @staticmethod
    def _policy_level_num(policy_level: Any) -> int:
        """Convert PolicyLevel enum/string/int to numeric level."""
        if isinstance(policy_level, int):
            return policy_level
        if hasattr(policy_level, "name") and str(policy_level.name).startswith("P"):
            try:
                return int(str(policy_level.name)[1:])
            except ValueError:
                return 0
        if hasattr(policy_level, "value") and str(policy_level.value).startswith("P"):
            try:
                return int(str(policy_level.value)[1:])
            except ValueError:
                return 0
        s = str(policy_level)
        if s.startswith("P"):
            try:
                return int(s[1:])
            except ValueError:
                return 0
        return 0


class GateConfigSelector:
    """
    闸门配置选择器

    根据风险画像选择合适的闸门配置。

    Attributes:
        configs: 可用的配置列表

    Example:
        >>> selector = GateConfigSelector()
        >>> config = selector.get_config(RiskProfile.BALANCED)
    """

    def __init__(self, configs: Optional[Iterable[GateConfig] | Dict[RiskProfile, GateConfig]] = None):
        """
        初始化选择器

        Args:
            configs: 配置映射（默认使用默认配置）
        """
        if configs is None:
            self.configs = get_default_configs()
        elif isinstance(configs, dict):
            self.configs = configs
        else:
            self.configs = {cfg.risk_profile: cfg for cfg in configs}

    def get_config(self, risk_profile: RiskProfile) -> GateConfig:
        """
        获取指定风险画像的配置

        Args:
            risk_profile: 风险画像

        Returns:
            闸门配置

        Raises:
            ValueError: 如果配置不存在
        """
        config = self.configs.get(risk_profile)
        if config is None:
            raise ValueError(f"No config found for risk profile: {risk_profile}")

        if not config.is_valid:
            logger.warning(f"Config for {risk_profile} is not valid (inactive or expired)")

        return config

    def get_active_configs(self) -> List[GateConfig]:
        """
        获取所有激活的配置

        Returns:
            激活的配置列表
        """
        return [cfg for cfg in self.configs.values() if cfg.is_valid]

    def add_config(self, config: GateConfig) -> None:
        """
        添加配置

        Args:
            config: 闸门配置
        """
        self.configs[config.risk_profile] = config

    def remove_config(self, risk_profile: RiskProfile) -> bool:
        """
        移除配置

        Args:
            risk_profile: 风险画像

        Returns:
            是否成功移除
        """
        if risk_profile in self.configs:
            del self.configs[risk_profile]
            return True
        return False


# ========== 便捷函数 ==========


def evaluate_visibility(
    asset_code: str,
    asset_class: str,
    current_regime: str,
    regime_confidence: float,
    policy_level: int,
    risk_profile: RiskProfile = RiskProfile.BALANCED,
) -> GateDecision:
    """
    评估资产可见性的便捷函数

    使用默认配置进行快速评估。

    Args:
        asset_code: 资产代码
        asset_class: 资产类别
        current_regime: 当前 Regime
        regime_confidence: Regime 置信度
        policy_level: Policy 档位
        risk_profile: 风险画像

    Returns:
        GateDecision 决策结果

    Example:
        >>> decision = evaluate_visibility(
        ...     asset_code="000001.SH",
        ...     asset_class="a_share金融",
        ...     current_regime="Recovery",
        ...     regime_confidence=0.7,
       ...     policy_level=0
        ... )
        >>> if decision.is_passed:
        ...     print("资产可见")
    """
    configs = get_default_configs()
    config = configs.get(risk_profile, configs[RiskProfile.BALANCED])

    evaluator = BetaGateEvaluator(config)
    return evaluator.evaluate(
        asset_code=asset_code,
        asset_class=asset_class,
        current_regime=current_regime,
        regime_confidence=regime_confidence,
        policy_level=policy_level,
    )


def build_universe(
    current_regime: str,
    regime_confidence: float,
    policy_level: int,
    risk_profile: RiskProfile = RiskProfile.BALANCED,
    candidate_assets: Optional[List[Tuple[str, str]]] = None,
) -> VisibilityUniverse:
    """
    构建可见性宇宙的便捷函数

    Args:
        current_regime: 当前 Regime
        regime_confidence: Regime 置信度
        policy_level: Policy 档位
        risk_profile: 风险画像
        candidate_assets: 候选资产列表

    Returns:
        VisibilityUniverse 实例
    """
    builder = VisibilityUniverseBuilder()
    return builder.build(
        current_regime=current_regime,
        regime_confidence=regime_confidence,
        policy_level=policy_level,
        risk_profile=risk_profile,
        candidate_assets=candidate_assets,
    )
