"""
Decision Rhythm Feature Providers

统一推荐的特征数据提供者实现。

实现 Top-down（Regime/Policy/Beta Gate）和
Bottom-up（舆情/资金/技术/基本面/Alpha）特征获取。
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone

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
                try:
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
                except Exception as exc:
                    logger.warning(
                        "Failed to get alpha score from primary service for %s: %s",
                        security_code,
                        exc,
                    )

            # 尝试从 alpha_trigger 获取
            from apps.alpha_trigger.infrastructure.repositories import (
                AlphaCandidateRepository,
            )

            repo = AlphaCandidateRepository()
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

    MAX_FORMAL_VALUATION_AGE_DAYS = 30
    UNUSABLE_QUALITY_FLAGS = frozenset(
        {
            "error",
            "expired",
            "failed",
            "invalid",
            "invalid_pb",
            "jump_alert",
            "missing_pb",
            "source_deviation",
            "stale",
            "unusable",
        }
    )

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
                    payload = {
                        "fair_value": getattr(valuation, "fair_value", 0),
                        "entry_price_low": getattr(valuation, "entry_price_low", 0),
                        "entry_price_high": getattr(valuation, "entry_price_high", 0),
                        "target_price_low": getattr(valuation, "target_price_low", 0),
                        "target_price_high": getattr(valuation, "target_price_high", 0),
                        "stop_loss_price": getattr(valuation, "stop_loss_price", 0),
                        "valuation_date": self._first_present_attr(
                            valuation,
                            (
                                "valuation_date",
                                "as_of_date",
                                "trade_date",
                                "calculated_at",
                                "fetched_at",
                            ),
                        ),
                        "is_valid": getattr(valuation, "is_valid", True),
                        "quality_flag": getattr(valuation, "quality_flag", "ok"),
                        "is_legacy": getattr(valuation, "is_legacy", False),
                        "valuation_source": "asset_analysis",
                    }
                    if self._is_usable_formal_valuation(payload):
                        return payload

            # 尝试从 decision_rhythm 的估值快照获取
            from ..infrastructure.models import ValuationSnapshotModel

            snapshots = ValuationSnapshotModel.objects.filter(
                security_code=security_code,
            ).order_by("-calculated_at")[:10]

            for latest in snapshots:
                payload = {
                    "fair_value": float(latest.fair_value),
                    "entry_price_low": float(latest.entry_price_low),
                    "entry_price_high": float(latest.entry_price_high),
                    "target_price_low": float(latest.target_price_low),
                    "target_price_high": float(latest.target_price_high),
                    "stop_loss_price": float(latest.stop_loss_price),
                    "valuation_method": latest.valuation_method,
                    "valuation_source": "decision_rhythm_snapshot",
                    "valuation_snapshot_id": latest.snapshot_id,
                    "calculated_at": latest.calculated_at,
                    "is_legacy": latest.is_legacy,
                    "input_parameters": latest.input_parameters or {},
                }
                if self._is_usable_formal_valuation(payload):
                    return payload

            fact_payload = self._get_data_center_valuation_fact_payload(security_code)
            if fact_payload is not None:
                return fact_payload

            fallback = self._get_or_create_current_price_fallback(security_code)
            if fallback is not None:
                return self._snapshot_to_payload(
                    fallback,
                    valuation_source="current_price_fallback",
                )

            return None

        except Exception as e:
            logger.warning(f"Failed to get valuation for {security_code}: {e}")
            return None

    @staticmethod
    def _has_positive_valuation(payload: dict[str, Any]) -> bool:
        """Return whether the payload has usable non-zero price contract fields."""
        required_fields = (
            "fair_value",
            "entry_price_low",
            "entry_price_high",
            "target_price_low",
            "target_price_high",
        )
        return all(
            AssetValuationProvider._to_decimal(payload.get(field)) > 0
            for field in required_fields
        )

    @classmethod
    def _is_usable_formal_valuation(cls, payload: dict[str, Any]) -> bool:
        """Validate price contract, freshness and reliability for formal valuations."""
        if not cls._has_positive_valuation(payload):
            return False
        if cls._is_legacy_valuation(payload):
            return False
        if not cls._has_acceptable_quality(payload):
            return False
        valuation_date = cls._extract_payload_date(payload)
        if valuation_date is None:
            return False
        earliest = timezone.localdate() - timedelta(days=cls.MAX_FORMAL_VALUATION_AGE_DAYS)
        return earliest <= valuation_date <= timezone.localdate()

    @staticmethod
    def _is_legacy_valuation(payload: dict[str, Any]) -> bool:
        if payload.get("is_legacy") is True:
            return True
        method = str(payload.get("valuation_method") or "").lower()
        return method == "legacy"

    @classmethod
    def _has_acceptable_quality(cls, payload: dict[str, Any]) -> bool:
        input_parameters = payload.get("input_parameters")
        if isinstance(input_parameters, dict):
            if input_parameters.get("is_valid") is False:
                return False
            nested_flag = input_parameters.get("quality_flag") or input_parameters.get("data_quality_flag")
            if cls._is_unusable_quality_flag(nested_flag):
                return False

        if payload.get("is_valid") is False:
            return False
        quality_flag = payload.get("quality_flag") or payload.get("data_quality_flag")
        return not cls._is_unusable_quality_flag(quality_flag)

    @classmethod
    def _is_unusable_quality_flag(cls, quality_flag: Any) -> bool:
        if quality_flag is None:
            return False
        if isinstance(quality_flag, (list, tuple, set)):
            return any(cls._is_unusable_quality_flag(item) for item in quality_flag)
        normalized = str(quality_flag).strip().lower()
        if not normalized:
            return False
        return normalized in cls.UNUSABLE_QUALITY_FLAGS

    @classmethod
    def _extract_payload_date(cls, payload: dict[str, Any]) -> date | None:
        input_parameters = payload.get("input_parameters")
        candidates = (
            payload.get("valuation_date"),
            payload.get("valuation_fact_date"),
            payload.get("trade_date"),
            payload.get("as_of_date"),
            payload.get("calculated_at"),
            payload.get("fetched_at"),
            payload.get("source_updated_at"),
        )
        for candidate in candidates:
            parsed = cls._coerce_date(candidate)
            if parsed is not None:
                return parsed
        if isinstance(input_parameters, dict):
            for key in (
                "valuation_date",
                "trade_date",
                "as_of_date",
                "calculated_at",
                "fetched_at",
                "source_updated_at",
            ):
                parsed = cls._coerce_date(input_parameters.get(key))
                if parsed is not None:
                    return parsed
        return None

    @staticmethod
    def _coerce_date(value: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if timezone.is_naive(value):
                value = timezone.make_aware(value, timezone.get_current_timezone())
            return timezone.localtime(value).date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            if normalized.endswith("Z"):
                normalized = f"{normalized[:-1]}+00:00"
            try:
                return datetime.fromisoformat(normalized).date()
            except ValueError:
                try:
                    return date.fromisoformat(normalized[:10])
                except ValueError:
                    return None
        return None

    @staticmethod
    def _first_present_attr(source: Any, names: tuple[str, ...]) -> Any:
        for name in names:
            value = getattr(source, name, None)
            if value is not None:
                return value
        return None

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    def _get_data_center_valuation_fact_payload(self, security_code: str) -> dict[str, Any] | None:
        """Build a price contract from formal valuation facts before using fallback."""
        try:
            from apps.data_center.infrastructure.repositories import ValuationFactRepository
        except Exception as exc:
            logger.debug("Data center valuation fact provider unavailable: %s", exc)
            return None

        try:
            repository = ValuationFactRepository()
            fact_candidates = self._get_recent_data_center_valuation_facts(
                repository,
                security_code,
            )
        except Exception as exc:
            logger.debug("Data center valuation fact lookup failed for %s: %s", security_code, exc)
            return None

        for fact in fact_candidates:
            payload = self._build_data_center_valuation_payload(fact)
            if payload is not None:
                return payload

        return None

    def _get_recent_data_center_valuation_facts(
        self,
        repository: Any,
        security_code: str,
    ) -> list[Any]:
        start = timezone.localdate() - timedelta(days=self.MAX_FORMAL_VALUATION_AGE_DAYS)
        get_series = getattr(repository, "get_series", None)
        if callable(get_series):
            facts = get_series(security_code, start=start, end=timezone.localdate())
            if isinstance(facts, list):
                return facts

        latest = repository.get_latest(security_code)
        return [latest] if latest is not None else []

    def _build_data_center_valuation_payload(self, fact: Any) -> dict[str, Any] | None:
        extra = getattr(fact, "extra", None) or {}
        if not isinstance(extra, dict):
            return None

        fair_value = self._pick_decimal(
            extra,
            (
                "fair_value",
                "intrinsic_value_per_share",
                "estimated_fair_value",
                "target_fair_value",
            ),
        )
        if fair_value <= 0:
            return None

        payload = {
            "fair_value": fair_value,
            "entry_price_low": self._pick_decimal(extra, ("entry_price_low", "entry_low")),
            "entry_price_high": self._pick_decimal(extra, ("entry_price_high", "entry_high")),
            "target_price_low": self._pick_decimal(extra, ("target_price_low", "target_low")),
            "target_price_high": self._pick_decimal(extra, ("target_price_high", "target_high")),
            "stop_loss_price": self._pick_decimal(extra, ("stop_loss_price", "stop_loss")),
            "valuation_method": str(extra.get("valuation_method") or "DATA_CENTER_FACT"),
            "valuation_source": "data_center_valuation_fact",
            "valuation_fact_date": getattr(fact, "val_date", None).isoformat()
            if getattr(fact, "val_date", None)
            else None,
            "fetched_at": getattr(fact, "fetched_at", None),
            "is_valid": extra.get("is_valid", True),
            "quality_flag": extra.get("quality_flag") or extra.get("data_quality_flag") or "ok",
        }
        if payload["entry_price_low"] <= 0:
            payload["entry_price_low"] = fair_value * Decimal("0.95")
        if payload["entry_price_high"] <= 0:
            payload["entry_price_high"] = fair_value * Decimal("1.05")
        if payload["target_price_low"] <= 0:
            payload["target_price_low"] = fair_value * Decimal("1.15")
        if payload["target_price_high"] <= 0:
            payload["target_price_high"] = fair_value * Decimal("1.25")
        if payload["stop_loss_price"] <= 0:
            payload["stop_loss_price"] = payload["entry_price_low"] * Decimal("0.90")

        if not self._is_usable_formal_valuation(payload):
            return None
        return {
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in payload.items()
        }

    @classmethod
    def _pick_decimal(cls, payload: dict[str, Any], keys: tuple[str, ...]) -> Decimal:
        for key in keys:
            amount = cls._to_decimal(payload.get(key))
            if amount > 0:
                return amount
        return Decimal("0")

    def _get_or_create_current_price_fallback(self, security_code: str):
        """Reuse today's fallback snapshot or create one from the latest observable price."""
        existing = self._get_today_fallback_snapshot(security_code)
        if existing is not None:
            return existing

        current_price, source = self._get_latest_market_price(security_code)
        if current_price <= 0:
            return None

        from ..domain.services import ValuationSnapshotService
        from ..infrastructure.repositories import ValuationSnapshotRepository

        snapshot = ValuationSnapshotService().create_current_price_fallback_snapshot(
            security_code=security_code,
            current_price=current_price,
            source=source,
        )
        return ValuationSnapshotRepository().save(snapshot)

    def _get_today_fallback_snapshot(self, security_code: str):
        from ..infrastructure.models import ValuationSnapshotModel

        latest = (
            ValuationSnapshotModel.objects.filter(
                security_code=security_code,
                valuation_method="FALLBACK",
            )
            .order_by("-calculated_at")
            .first()
        )
        if latest is None:
            return None
        if timezone.localdate(latest.calculated_at) != timezone.localdate():
            return None
        snapshot = latest.to_domain()
        if not self._has_positive_valuation(self._snapshot_to_payload(snapshot, valuation_source="")):
            return None
        return snapshot

    def _get_latest_market_price(self, security_code: str) -> tuple[Decimal, str]:
        price = self._get_realtime_price(security_code)
        if price > 0:
            return price, "realtime_price_cache"

        price = self._get_latest_close_price(security_code)
        if price > 0:
            return price, "data_center_latest_close"

        return Decimal("0"), "unavailable"

    def _get_realtime_price(self, security_code: str) -> Decimal:
        try:
            from apps.realtime.infrastructure.repositories import RedisRealtimePriceRepository

            latest_price = RedisRealtimePriceRepository().get_latest_price(security_code)
            return self._extract_price_amount(latest_price)
        except Exception as exc:
            logger.debug("Realtime price fallback unavailable for %s: %s", security_code, exc)
            return Decimal("0")

    def _get_latest_close_price(self, security_code: str) -> Decimal:
        try:
            from apps.data_center.infrastructure.repositories import PriceBarRepository

            latest_bar = PriceBarRepository().get_latest(security_code)
            return self._extract_price_amount(latest_bar)
        except Exception as exc:
            logger.debug("Latest close fallback unavailable for %s: %s", security_code, exc)
            return Decimal("0")

    @classmethod
    def _extract_price_amount(cls, price_obj: Any) -> Decimal:
        if price_obj is None:
            return Decimal("0")
        for attr in ("price", "current_price", "close"):
            value = getattr(price_obj, attr, None)
            amount = cls._to_decimal(value)
            if amount > 0:
                return amount
        return Decimal("0")

    @staticmethod
    def _snapshot_to_payload(snapshot, *, valuation_source: str) -> dict[str, Any]:
        return {
            "fair_value": float(snapshot.fair_value),
            "entry_price_low": float(snapshot.entry_price_low),
            "entry_price_high": float(snapshot.entry_price_high),
            "target_price_low": float(snapshot.target_price_low),
            "target_price_high": float(snapshot.target_price_high),
            "stop_loss_price": float(snapshot.stop_loss_price),
            "valuation_method": snapshot.valuation_method,
            "valuation_source": valuation_source,
            "valuation_snapshot_id": snapshot.snapshot_id,
        }


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
            from apps.alpha_trigger.infrastructure.repositories import (
                AlphaCandidateRepository,
                AlphaTriggerRepository,
            )

            # 使用 AlphaTriggerRepository 获取活跃触发器
            trigger_repo = AlphaTriggerRepository()
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
            candidate_repo = AlphaCandidateRepository()
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
            from apps.alpha_trigger.infrastructure.repositories import (
                AlphaCandidateRepository,
            )

            repo = AlphaCandidateRepository()
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
