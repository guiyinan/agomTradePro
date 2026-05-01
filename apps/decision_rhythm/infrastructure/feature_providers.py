"""
Decision Rhythm Feature Providers

统一推荐的特征数据提供者实现。

实现 Top-down（Regime/Policy/Beta Gate）和
Bottom-up（舆情/资金/技术/基本面/Alpha）特征获取。
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from ..application.use_cases import (
    CandidateProviderProtocol,
    FeatureDataProviderProtocol,
    SignalProviderProtocol,
    ValuationProviderProtocol,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Top-down 特征提供者
# ============================================================================


class RegimeFeatureProvider:
    """
    Regime 特征提供者

    从 regime 模块获取当前 Regime 状态。
    """

    def get_regime(self) -> dict[str, Any] | None:
        """
        获取当前 Regime 状态

        Returns:
            Regime 状态字典，包含 regime 和 confidence
        """
        try:
            from apps.regime.application.current_regime import resolve_current_regime

            result = resolve_current_regime()

            return {
                "regime": result.dominant_regime,
                "confidence": result.confidence,
                "observed_at": result.observed_at.isoformat() if result.observed_at else None,
                "data_source": result.data_source,
                "is_fallback": result.is_fallback,
                "warnings": result.warnings,
            }

        except Exception as e:
            logger.error(f"Failed to get regime: {e}", exc_info=True)
            return None


class PolicyFeatureProvider:
    """
    Policy 特征提供者

    从 policy 模块获取当前政策档位。
    """

    def __init__(self):
        self._policy_repository = None

    def _get_policy_repository(self):
        """延迟加载 repository"""
        if self._policy_repository is None:
            from apps.policy.infrastructure.repositories import DjangoPolicyRepository
            self._policy_repository = DjangoPolicyRepository()
        return self._policy_repository

    def get_policy_level(self) -> str | None:
        """
        获取当前政策档位

        Returns:
            政策档位字符串
        """
        try:
            repo = self._get_policy_repository()
            level = repo.get_current_policy_level(date.today())

            if level:
                return level.value if hasattr(level, "value") else str(level)

            return "LEVEL_0"  # 默认档位

        except Exception as e:
            logger.error(f"Failed to get policy level: {e}", exc_info=True)
            return "LEVEL_0"


class BetaGateFeatureProvider:
    """
    Beta Gate 特征提供者

    从 beta_gate 模块检查 Beta Gate 状态。
    """

    def __init__(self):
        self._beta_gate_use_case = None

    def _get_beta_gate_use_case(self):
        """延迟加载 use case"""
        if self._beta_gate_use_case is None:
            from apps.beta_gate.application.use_cases import EvaluateBetaGateUseCase
            from apps.beta_gate.domain.services import GateConfigSelector
            config_selector = GateConfigSelector()
            self._beta_gate_use_case = EvaluateBetaGateUseCase(config_selector)
        return self._beta_gate_use_case

    def check_beta_gate(
        self,
        security_code: str,
        regime: str = "",
        regime_confidence: float = 0.0,
        policy_level: str = "LEVEL_0",
    ) -> bool:
        """
        检查 Beta Gate 是否通过

        Args:
            security_code: 证券代码
            regime: 当前 Regime
            regime_confidence: Regime 置信度
            policy_level: 政策档位

        Returns:
            是否通过 Beta Gate
        """
        try:
            from apps.beta_gate.application.use_cases import EvaluateGateRequest
            from apps.beta_gate.domain.entities import RiskProfile

            # 解析 policy level
            try:
                from apps.policy.domain.entities import PolicyLevel
                policy_enum = PolicyLevel(policy_level)
                policy_int = policy_enum.value if hasattr(policy_enum, "value") else 0
            except (ValueError, ImportError):
                # 尝试从字符串解析数字
                try:
                    policy_int = int(policy_level.replace("LEVEL_", ""))
                except (ValueError, AttributeError):
                    policy_int = 0

            use_case = self._get_beta_gate_use_case()
            request = EvaluateGateRequest(
                asset_code=security_code,
                asset_class="EQUITY",
                current_regime=regime,
                regime_confidence=regime_confidence,
                policy_level=policy_int,
                risk_profile=RiskProfile.BALANCED,
            )

            response = use_case.execute(request)

            if response.success and response.decision:
                decision = response.decision
                if hasattr(decision, "is_passed"):
                    return bool(decision.is_passed)

                gate_status = getattr(getattr(decision, "gate_status", None), "value", None)
                if gate_status is None:
                    gate_status = getattr(getattr(decision, "status", None), "value", None)
                if gate_status is not None:
                    return str(gate_status).lower() in ("pass", "pass_with_warning", "passed")

            return False

        except Exception as e:
            logger.error(f"Failed to check beta gate for {security_code}: {e}", exc_info=True)
            # 默认通过，避免因检查失败而阻塞所有推荐
            return True


# ============================================================================
# Bottom-up 特征提供者
# ============================================================================


class SentimentFeatureProvider:
    """
    舆情特征提供者

    从 sentiment 模块获取舆情分数。
    """

    def __init__(self):
        self._sentiment_repository = None

    def _get_sentiment_repository(self):
        """延迟加载 repository"""
        if self._sentiment_repository is None:
            from apps.sentiment.infrastructure.repositories import SentimentIndexRepository
            self._sentiment_repository = SentimentIndexRepository()
        return self._sentiment_repository

    def get_sentiment_score(self, security_code: str) -> float:
        """
        获取舆情分数

        Args:
            security_code: 证券代码

        Returns:
            舆情分数 (0-1)
        """
        try:
            from datetime import date
            repo = self._get_sentiment_repository()

            # 获取最新的舆情指数（市场级别）
            latest = repo.get_by_date(date.today())

            if latest and hasattr(latest, "composite_index"):
                # composite_index 范围是 -3.0 到 +3.0，归一化到 0-1
                score = float(latest.composite_index)
                normalized = (score + 3.0) / 6.0  # -3~3 -> 0~1
                return max(0.0, min(1.0, normalized))

            return 0.5  # 默认中性

        except Exception as e:
            logger.warning(f"Failed to get sentiment score for {security_code}: {e}")
            return 0.5


class FlowFeatureProvider:
    """
    资金流向特征提供者

    从账户或行情数据获取资金流向分数。
    """

    def __init__(self):
        self._flow_repository = None

    def _get_flow_repository(self):
        """延迟加载 repository"""
        if self._flow_repository is None:
            from apps.realtime.infrastructure.repositories import RedisRealtimePriceRepository
            self._flow_repository = RedisRealtimePriceRepository()
        return self._flow_repository

    def get_flow_score(self, security_code: str) -> float:
        """
        获取资金流向分数

        Args:
            security_code: 证券代码

        Returns:
            资金流向分数 (0-1)
        """
        try:
            # 尝试从行情数据获取资金流向
            repo = self._get_flow_repository()
            price = repo.get_latest_price(security_code)

            if price:
                # 使用成交量作为资金流向的代理指标
                # 成交量越大，表示资金越活跃
                if hasattr(price, "volume") and price.volume:
                    volume = float(price.volume)
                    # 归一化：使用 sigmoid 函数将成交量映射到 0-1
                    # 假设 1亿成交量对应 0.5 分
                    if volume > 0:
                        import math
                        mid_point = 100_000_000  # 1亿
                        score = 1 / (1 + math.exp(-(volume - mid_point) / mid_point))
                        return max(0.0, min(1.0, score))

            return 0.5

        except Exception as e:
            logger.warning(f"Failed to get flow score for {security_code}: {e}")
            return 0.5


class TechnicalFeatureProvider:
    """
    技术面特征提供者

    从技术分析获取技术面分数。
    """

    def __init__(self):
        self._technical_repository = None

    def _get_technical_repository(self):
        """延迟加载 repository"""
        if self._technical_repository is None:
            from apps.equity.infrastructure.repositories import DjangoStockRepository
            self._technical_repository = DjangoStockRepository()
        return self._technical_repository

    def get_technical_score(self, security_code: str) -> float:
        """
        获取技术面分数

        Args:
            security_code: 证券代码

        Returns:
            技术面分数 (0-1)
        """
        try:
            # 尝试从 equity 模块获取技术评分
            # 目前返回默认值，后续可以集成技术分析模块
            repo = self._get_technical_repository()
            stocks = repo.get_all_stocks_with_fundamentals()

            # 查找对应股票
            for stock_info, _, _ in stocks:
                if stock_info.stock_code == security_code:
                    # 使用简单的技术评分逻辑
                    # 后续可以集成更复杂的技术分析
                    return 0.5

            return 0.5

        except Exception as e:
            logger.warning(f"Failed to get technical score for {security_code}: {e}")
            return 0.5


class FundamentalFeatureProvider:
    """
    基本面特征提供者

    从基本面分析获取基本面分数。
    """

    def __init__(self):
        self._fundamental_repository = None

    def _get_fundamental_repository(self):
        """延迟加载 repository"""
        if self._fundamental_repository is None:
            from apps.equity.infrastructure.repositories import DjangoStockRepository
            self._fundamental_repository = DjangoStockRepository()
        return self._fundamental_repository

    def get_fundamental_score(self, security_code: str) -> float:
        """
        获取基本面分数

        Args:
            security_code: 证券代码

        Returns:
            基本面分数 (0-1)
        """
        try:
            # 尝试从 equity 模块获取基本面评分
            repo = self._get_fundamental_repository()
            stocks = repo.get_all_stocks_with_fundamentals()

            # 查找对应股票
            for stock_info, financial_data, _ in stocks:
                if stock_info.stock_code == security_code:
                    # 使用简单的基本面评分逻辑
                    # 基于 ROE 和净利润增长率
                    if hasattr(financial_data, 'roe') and financial_data.roe:
                        roe = float(financial_data.roe)
                        # ROE 10% 对应 0.5 分
                        score = min(1.0, max(0.0, roe / 20.0))
                        return score

            return 0.5

        except Exception as e:
            logger.warning(f"Failed to get fundamental score for {security_code}: {e}")
            return 0.5


class AlphaModelFeatureProvider:
    """
    Alpha 模型特征提供者

    从 alpha 模块获取 Alpha 模型分数。
    """

    def __init__(self):
        self._alpha_service = None

    def _get_alpha_service(self):
        """延迟加载 service"""
        if self._alpha_service is None:
            try:
                from core.integration.alpha_scores import fetch_stock_scores

                self._alpha_service = fetch_stock_scores
            except ImportError:
                pass
        return self._alpha_service

    @staticmethod
    def _normalize_candidate_alpha_score(candidate: Any) -> float:
        """从 Alpha 候选实体推导 0-1 分数。"""
        confidence = float(getattr(candidate, "confidence", 0.5) or 0.5)
        confidence = max(0.0, min(1.0, confidence))

        strength = getattr(candidate, "strength", "")
        strength_value = getattr(strength, "value", strength)
        strength_floor_map = {
            "very_weak": 0.20,
            "weak": 0.35,
            "moderate": 0.60,
            "strong": 0.75,
            "very_strong": 0.90,
        }
        floor = strength_floor_map.get(str(strength_value).lower(), 0.5)
        return max(confidence, floor)

    def get_alpha_model_score(self, security_code: str) -> float:
        """
        获取 Alpha 模型分数

        Args:
            security_code: 证券代码

        Returns:
            Alpha 模型分数 (0-1)
        """
        try:
            service = self._get_alpha_service()

            if service:
                # 获取股票池评分，然后查找目标股票
                from datetime import date
                result = service(
                    universe_id="csi300",
                    intended_trade_date=date.today(),
                )

                if result.success and result.scores:
                    for stock_score in result.scores:
                        if stock_score.code == security_code:
                            # score 范围是 -1 到 1，归一化到 0-1
                            normalized = (float(stock_score.score) + 1) / 2
                            return max(0.0, min(1.0, normalized))

            # 尝试从 alpha_trigger 获取
            from core.integration.alpha_candidates import get_alpha_candidate_repository

            repo = get_alpha_candidate_repository()
            candidates = repo.get_by_asset(security_code)

            if candidates and len(candidates) > 0:
                # 取最新的候选
                top_candidate = candidates[0]
                if hasattr(top_candidate, "alpha_score"):
                    return max(0.0, min(1.0, float(top_candidate.alpha_score)))
                return self._normalize_candidate_alpha_score(top_candidate)

            return 0.5

        except Exception as e:
            logger.warning(f"Failed to get alpha model score for {security_code}: {e}")
            return 0.5


# ============================================================================
# 组合特征提供者
# ============================================================================


class CompositeFeatureProvider(
    FeatureDataProviderProtocol,
    RegimeFeatureProvider,
    PolicyFeatureProvider,
    BetaGateFeatureProvider,
    SentimentFeatureProvider,
    FlowFeatureProvider,
    TechnicalFeatureProvider,
    FundamentalFeatureProvider,
    AlphaModelFeatureProvider,
):
    """
    组合特征提供者

    实现所有特征获取接口。
    """

    def __init__(self) -> None:
        PolicyFeatureProvider.__init__(self)
        BetaGateFeatureProvider.__init__(self)
        SentimentFeatureProvider.__init__(self)
        FlowFeatureProvider.__init__(self)
        TechnicalFeatureProvider.__init__(self)
        FundamentalFeatureProvider.__init__(self)
        AlphaModelFeatureProvider.__init__(self)

    def get_regime(self) -> dict[str, Any] | None:
        return RegimeFeatureProvider.get_regime(self)

    def get_policy_level(self) -> str | None:
        return PolicyFeatureProvider.get_policy_level(self)

    def check_beta_gate(self, security_code: str) -> bool:
        # 先获取 regime 和 policy
        regime_data = self.get_regime() or {}
        policy_level = self.get_policy_level() or "LEVEL_0"

        return BetaGateFeatureProvider.check_beta_gate(
            self,
            security_code=security_code,
            regime=regime_data.get("regime", ""),
            regime_confidence=regime_data.get("confidence", 0.0),
            policy_level=policy_level,
        )

    def get_sentiment_score(self, security_code: str) -> float:
        return SentimentFeatureProvider.get_sentiment_score(self, security_code)

    def get_flow_score(self, security_code: str) -> float:
        return FlowFeatureProvider.get_flow_score(self, security_code)

    def get_technical_score(self, security_code: str) -> float:
        return TechnicalFeatureProvider.get_technical_score(self, security_code)

    def get_fundamental_score(self, security_code: str) -> float:
        return FundamentalFeatureProvider.get_fundamental_score(self, security_code)

    def get_alpha_model_score(self, security_code: str) -> float:
        return AlphaModelFeatureProvider.get_alpha_model_score(self, security_code)


# ============================================================================
# 估值提供者
# ============================================================================


class AssetValuationProvider(ValuationProviderProtocol):
    """
    资产估值提供者

    从估值模块获取估值数据。
    """

    def __init__(self):
        self._service = None

    def _get_service(self):
        """延迟加载 service"""
        if self._service is None:
            try:
                from apps.asset_analysis.application.services import ValuationService
                self._service = ValuationService()
            except ImportError:
                pass
        return self._service

    def get_valuation(self, security_code: str) -> dict[str, Any] | None:
        """
        获取估值数据

        Args:
            security_code: 证券代码

        Returns:
            估值数据字典
        """
        try:
            service = self._get_service()

            if service:
                valuation = service.get_latest_valuation(security_code)
                if valuation:
                    return {
                        "fair_value": getattr(valuation, "fair_value", 0),
                        "entry_price_low": getattr(valuation, "entry_price_low", 0),
                        "entry_price_high": getattr(valuation, "entry_price_high", 0),
                        "target_price_low": getattr(valuation, "target_price_low", 0),
                        "target_price_high": getattr(valuation, "target_price_high", 0),
                        "stop_loss_price": getattr(valuation, "stop_loss_price", 0),
                    }

            # 尝试从 decision_rhythm 的估值快照获取
            from ..infrastructure.models import ValuationSnapshotModel

            latest = ValuationSnapshotModel.objects.filter(
                security_code=security_code
            ).order_by("-calculated_at").first()

            if latest:
                return {
                    "fair_value": float(latest.fair_value),
                    "entry_price_low": float(latest.entry_price_low),
                    "entry_price_high": float(latest.entry_price_high),
                    "target_price_low": float(latest.target_price_low),
                    "target_price_high": float(latest.target_price_high),
                    "stop_loss_price": float(latest.stop_loss_price),
                }

            return None

        except Exception as e:
            logger.warning(f"Failed to get valuation for {security_code}: {e}")
            return None


# ============================================================================
# 信号提供者
# ============================================================================


class AlphaSignalProvider(SignalProviderProtocol):
    """
    Alpha 信号提供者

    从 alpha_trigger 模块获取活跃信号。
    """

    def get_active_signals(
        self,
        security_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        获取活跃信号

        Args:
            security_code: 证券代码（可选）

        Returns:
            信号列表
        """
        try:
            from core.integration.alpha_candidates import get_alpha_candidate_repository
            from core.integration.alpha_triggers import get_alpha_trigger_repository

            # 使用 AlphaTriggerRepository 获取活跃触发器
            trigger_repo = get_alpha_trigger_repository()
            triggers = trigger_repo.get_active(asset_code=security_code)

            # 转换为信号格式
            signals = []
            for t in triggers:
                signals.append({
                    "signal_id": t.trigger_id,
                    "security_code": t.asset_code,
                    "alpha_score": 0.5,  # 触发器没有 alpha_score，使用默认值
                    "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                })

            # 同时从候选中获取
            candidate_repo = get_alpha_candidate_repository()
            if security_code:
                candidates = candidate_repo.get_by_asset(security_code)
            else:
                candidates = candidate_repo.get_actionable()

            for c in candidates:
                signals.append({
                    "signal_id": c.candidate_id,
                    "security_code": c.asset_code,
                    "alpha_score": c.alpha_score if hasattr(c, "alpha_score") else 0.5,
                    "status": c.status.value if hasattr(c.status, "value") else str(c.status),
                })

            return signals

        except Exception as e:
            logger.warning(f"Failed to get active signals: {e}")
            return []


# ============================================================================
# 候选提供者
# ============================================================================


class AlphaCandidateProvider(CandidateProviderProtocol):
    """
    Alpha 候选提供者

    从 alpha_trigger 模块获取活跃候选。
    """

    def get_active_candidates(
        self,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        获取活跃候选

        Args:
            account_id: 账户 ID（可选）

        Returns:
            候选列表
        """
        try:
            from core.integration.alpha_candidates import get_alpha_candidate_repository

            repo = get_alpha_candidate_repository()
            # 使用 get_actionable 获取可操作的候选
            candidates = repo.get_actionable()

            return [
                {
                    "candidate_id": c.candidate_id,
                    "account_id": account_id or "default",
                    "security_code": c.asset_code,
                    "alpha_score": c.alpha_score if hasattr(c, "alpha_score") else 0.5,
                    "direction": c.direction if hasattr(c, "direction") else "BUY",
                }
                for c in candidates
            ]

        except Exception as e:
            logger.warning(f"Failed to get active candidates: {e}")
            return []


# ============================================================================
# 工厂函数
# ============================================================================


def create_feature_provider() -> CompositeFeatureProvider:
    """创建组合特征提供者"""
    return CompositeFeatureProvider()


def create_valuation_provider() -> AssetValuationProvider:
    """创建估值提供者"""
    return AssetValuationProvider()


def create_signal_provider() -> AlphaSignalProvider:
    """创建信号提供者"""
    return AlphaSignalProvider()


def create_candidate_provider() -> AlphaCandidateProvider:
    """创建候选提供者"""
    return AlphaCandidateProvider()
