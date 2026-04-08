"""
Regime Navigator Use Cases

BuildRegimeNavigatorUseCase: 构建完整导航仪输出
GetActionRecommendationUseCase: 获取联合行动建议（Regime + Pulse）

配置优先从数据库加载，fallback 到 Domain 层默认值。
"""

import logging
from datetime import date

from apps.regime.domain.action_mapper import (
    ActionMapperConfig,
    RegimeActionRecommendation,
    map_regime_pulse_to_action,
)
from apps.regime.domain.entities import (
    AssetWeightRange,
    RegimeAssetGuidance,
    RegimeMovement,
    RegimeNavigatorOutput,
    WatchIndicator,
)
from apps.regime.domain.navigator_services import (
    RegimeAssetConfig,
    WatchIndicatorConfig,
    assess_regime_movement,
    determine_watch_indicators,
    map_regime_to_asset_guidance,
)

logger = logging.getLogger(__name__)


def _load_asset_config_from_db() -> RegimeAssetConfig | None:
    """从数据库加载 Navigator 资产配置，失败返回 None（使用 Domain 默认）"""
    try:
        from apps.pulse.infrastructure.models import NavigatorAssetConfigModel

        db_configs = list(NavigatorAssetConfigModel.objects.filter(is_active=True))
        if not db_configs:
            return None

        asset_ranges: dict[str, dict[str, tuple[float, float]]] = {}
        risk_budget: dict[str, float] = {}
        sectors: dict[str, list[str]] = {}
        styles: dict[str, list[str]] = {}

        for cfg in db_configs:
            regime = cfg.regime_name
            # asset_weight_ranges: {"equity": [0.5, 0.7], ...}
            ranges_dict = {}
            for cat, (lo, hi) in cfg.asset_weight_ranges.items():
                ranges_dict[cat] = (float(lo), float(hi))
            asset_ranges[regime] = ranges_dict
            risk_budget[regime] = cfg.risk_budget
            sectors[regime] = cfg.recommended_sectors
            styles[regime] = cfg.benefiting_styles

        return RegimeAssetConfig(
            asset_ranges=asset_ranges,
            risk_budget=risk_budget,
            sectors=sectors,
            styles=styles,
        )
    except Exception as e:
        logger.warning(f"Failed to load navigator asset config from DB: {e}")
        return None


class BuildRegimeNavigatorUseCase:
    """
    构建 Regime 导航仪完整输出

    编排流程:
    1. 调用 CalculateRegimeV2UseCase 获取基础 regime 判定
    2. 调用 assess_regime_movement() 判定移动方向
    3. 从 DB 加载配置（fallback Domain 默认值）
    4. 调用 map_regime_to_asset_guidance() 生成资产指引
    5. 调用 determine_watch_indicators() 确定关注指标
    6. 组合为 RegimeNavigatorOutput
    """

    def __init__(self, macro_repo=None):
        self.macro_repo = macro_repo

    def execute(self, as_of_date: date | None = None) -> RegimeNavigatorOutput | None:
        target_date = as_of_date or date.today()

        try:
            from apps.regime.application.use_cases import (
                CalculateRegimeV2Request,
                CalculateRegimeV2UseCase,
            )

            # 获取 macro repo
            repo = self.macro_repo
            if repo is None:
                from apps.regime.infrastructure.macro_data_provider import MacroRepositoryAdapter
                repo = MacroRepositoryAdapter()

            # 1. 基础 regime 判定
            use_case = CalculateRegimeV2UseCase(repo)
            result = use_case.execute(CalculateRegimeV2Request(
                as_of_date=target_date,
                use_pit=True,
                growth_indicator="PMI",
                inflation_indicator="CPI",
            ))

            if not result.success or not result.result:
                logger.warning(f"Regime calculation failed: {result.error}")
                return None

            calc_result = result.result
            regime = calc_result.regime

            # 2. 移动方向
            direction, target, probability, reasons = assess_regime_movement(
                regime, calc_result.trend_indicators
            )

            # 构建动量摘要
            momentum_parts = []
            for ti in calc_result.trend_indicators:
                if ti.indicator_code == "PMI":
                    momentum_parts.append(
                        f"PMI {'上升' if ti.direction == 'up' else ('下降' if ti.direction == 'down' else '持平')}"
                    )
                elif ti.indicator_code == "CPI":
                    momentum_parts.append(
                        f"CPI {'上升' if ti.direction == 'up' else ('下降' if ti.direction == 'down' else '持平')}"
                    )

            movement = RegimeMovement(
                direction=direction,
                transition_target=target,
                transition_probability=probability,
                leading_indicators=reasons,
                momentum_summary=" + ".join(momentum_parts) if momentum_parts else "数据不足",
            )

            # 3. 从 DB 加载配置（fallback）
            asset_config = _load_asset_config_from_db()

            # 4. 资产配置指引
            guidance_dict = map_regime_to_asset_guidance(
                regime, calc_result.confidence, config=asset_config
            )

            weight_ranges = [
                AssetWeightRange(
                    category=wr["category"],
                    lower=wr["lower"],
                    upper=wr["upper"],
                    label=wr["label"],
                )
                for wr in guidance_dict["weight_ranges"]
            ]

            asset_guidance = RegimeAssetGuidance(
                weight_ranges=weight_ranges,
                risk_budget_pct=guidance_dict["risk_budget"],
                recommended_sectors=guidance_dict["sectors"],
                benefiting_styles=guidance_dict["styles"],
                reasoning=guidance_dict["reasoning"],
            )

            # 5. 关注指标
            watch_dicts = determine_watch_indicators(regime, direction, target)
            watch_indicators = [
                WatchIndicator(
                    code=w["code"],
                    name=w["name"],
                    threshold=w["threshold"],
                    significance=w["significance"],
                )
                for w in watch_dicts
            ]

            # 6. 组合输出
            return RegimeNavigatorOutput(
                regime_name=regime.value,
                confidence=calc_result.confidence,
                distribution=calc_result.distribution,
                movement=movement,
                asset_guidance=asset_guidance,
                watch_indicators=watch_indicators,
                generated_at=target_date,
                data_freshness="fresh",
            )

        except Exception as e:
            logger.exception(f"Error building regime navigator: {e}")
            return None


class GetActionRecommendationUseCase:
    """
    获取联合行动建议

    编排流程:
    1. 调用 BuildRegimeNavigatorUseCase 获取导航仪输出
    2. 调用 GetLatestPulseUseCase（从 pulse 模块）获取最新脉搏
    3. 调用 map_regime_pulse_to_action() 计算具体配置
    4. 返回 RegimeActionRecommendation
    """

    def __init__(self, macro_repo=None):
        self.macro_repo = macro_repo

    def execute(self, as_of_date: date | None = None) -> RegimeActionRecommendation | None:
        target_date = as_of_date or date.today()

        try:
            # 1. 获取导航仪输出
            nav_use_case = BuildRegimeNavigatorUseCase(macro_repo=self.macro_repo)
            navigator = nav_use_case.execute(target_date)

            if not navigator:
                return None

            # 2. 获取 Pulse 快照
            pulse_score = 0.0
            pulse_strength = "moderate"

            try:
                from apps.pulse.application.use_cases import GetLatestPulseUseCase
                pulse_use_case = GetLatestPulseUseCase()
                pulse = pulse_use_case.execute(
                    as_of_date=target_date,
                    require_reliable=True,
                    refresh_if_stale=True,
                )
                if pulse:
                    pulse_score = pulse.composite_score
                    pulse_strength = pulse.regime_strength
            except Exception as e:
                logger.warning(f"Pulse not available, using defaults: {e}")

            # 3. 调用 action mapper
            guidance = navigator.asset_guidance
            weight_ranges = [
                {
                    "category": wr.category,
                    "lower": wr.lower,
                    "upper": wr.upper,
                }
                for wr in guidance.weight_ranges
            ]

            action_rec = map_regime_pulse_to_action(
                regime_name=navigator.regime_name,
                weight_ranges=weight_ranges,
                risk_budget=guidance.risk_budget_pct,
                sectors=guidance.recommended_sectors,
                styles=guidance.benefiting_styles,
                reasoning=guidance.reasoning,
                pulse_composite_score=pulse_score,
                pulse_regime_strength=pulse_strength,
                confidence=navigator.confidence,
                as_of_date=target_date,
            )

            # 持久化 ActionRecommendationLog
            try:
                from apps.regime.infrastructure.repositories import DjangoNavigatorRepository
                repo = DjangoNavigatorRepository()
                repo.save_action_recommendation(
                    observed_at=target_date,
                    data={
                        "regime_name": navigator.regime_name,
                        "pulse_strength": pulse_strength,
                        "asset_weights": action_rec.asset_weights,
                        "risk_budget_pct": action_rec.risk_budget_pct,
                        "recommended_sectors": action_rec.recommended_sectors,
                        "benefiting_styles": action_rec.benefiting_styles,
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to save ActionRecommendationLog: {e}")

            return action_rec

        except Exception as e:
            logger.exception(f"Error getting action recommendation: {e}")
            return None


class GetRegimeNavigatorHistoryUseCase:
    """
    获 Regime 导航仪的历史数据叠加

    输出格式：
    {
      "period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
      "regime_transitions": [...],
      "pulse_history": [...],
      "action_history": [...]
    }
    """

    def execute(self, start_date: date, end_date: date) -> dict:
        try:
            from apps.regime.infrastructure.repositories import DjangoNavigatorRepository
            repo = DjangoNavigatorRepository()

            # 1. Regime Transitions
            regimes = repo.get_regimes_in_range(start_date, end_date)

            regime_transitions = []
            last_regime = None
            for r in regimes:
                if r.dominant_regime != last_regime:
                    regime_transitions.append({
                        "date": r.observed_at.isoformat(),
                        "from_regime": last_regime,
                        "to_regime": r.dominant_regime,
                        "confidence": r.confidence,
                    })
                    last_regime = r.dominant_regime

            # 如果在这段时间内没有发生变化，也要在开头放一个当前状态
            if not regime_transitions and regimes.exists():
                r = regimes.first()
                regime_transitions.append({
                    "date": r.observed_at.isoformat(),
                    "from_regime": None,
                    "to_regime": r.dominant_regime,
                    "confidence": r.confidence,
                })

            # 2. Pulse History
            pulses = repo.get_pulses_in_range(start_date, end_date)
            
            pulse_history = [
                {
                    "date": p.observed_at.isoformat(),
                    "composite_score": p.composite_score,
                    "growth_score": p.growth_score,
                    "inflation_score": p.inflation_score,
                    "liquidity_score": p.liquidity_score,
                    "sentiment_score": p.sentiment_score,
                }
                for p in pulses
            ]

            # 3. Action History
            actions = repo.get_actions_in_range(start_date, end_date)
            
            action_history = [
                {
                    "date": a.observed_at.isoformat(),
                    "risk_budget_pct": a.risk_budget_pct,
                    "equity_weight": a.asset_weights.get("equity", 0),
                    "bond_weight": a.asset_weights.get("bond", 0),
                    "commodity_weight": a.asset_weights.get("commodity", 0),
                    "cash_weight": a.asset_weights.get("cash", 0),
                }
                for a in actions
            ]

            return {
                "period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
                "regime_transitions": regime_transitions,
                "pulse_history": pulse_history,
                "action_history": action_history,
            }

        except Exception as e:
            logger.exception(f"Error getting regime navigator history: {e}")
            return {
                "period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
                "regime_transitions": [],
                "pulse_history": [],
                "action_history": [],
                "error": str(e)
            }
