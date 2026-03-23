"""
Dashboard Query Services.

Application 层查询服务，为 Dashboard 视图提供数据聚合。

重构说明 (2026-03-11):
- 将跨模块数据获取逻辑从 views.py 移至 Query Services
- 隐藏 ORM 实现细节
- 提供简化的 API 给视图层使用
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from django.utils import timezone as django_timezone

logger = logging.getLogger(__name__)


# ============================================================================
# Alpha Visualization Query Service
# ============================================================================

@dataclass(frozen=True)
class AlphaVisualizationData:
    """Alpha 可视化数据"""
    stock_scores: list[dict[str, Any]]
    provider_status: dict[str, Any]
    coverage_metrics: dict[str, Any]
    ic_trends: list[dict[str, Any]]
    ic_trends_meta: dict[str, Any]


class AlphaVisualizationQuery:
    """
    Alpha 可视化查询服务

    聚合 Alpha 选股评分、Provider 状态、覆盖率指标和 IC 趋势数据。

    Example:
        >>> query = AlphaVisualizationQuery()
        >>> data = query.execute(top_n=10, ic_days=30)
        >>> print(len(data.stock_scores))
    """

    def execute(self, top_n: int = 10, ic_days: int = 30) -> AlphaVisualizationData:
        """
        执行查询

        Args:
            top_n: 返回的股票数量
            ic_days: IC 趋势天数

        Returns:
            AlphaVisualizationData
        """
        ic_trends = self._get_ic_trends(ic_days)
        return AlphaVisualizationData(
            stock_scores=self._get_stock_scores(top_n),
            provider_status=self._get_provider_status(),
            coverage_metrics=self._get_coverage_metrics(),
            ic_trends=ic_trends,
            ic_trends_meta=self._build_ic_trends_meta(ic_trends),
        )

    def _get_stock_scores(self, top_n: int) -> list[dict[str, Any]]:
        """获取 Alpha 选股评分结果"""
        try:
            from apps.alpha.application.services import AlphaService

            service = AlphaService()
            result = service.get_stock_scores(
                universe_id="csi300",
                intended_trade_date=date.today(),
                top_n=top_n
            )

            if result.success and result.scores:
                code_to_name = self._resolve_security_names(
                    [score.code for score in result.scores[:top_n]]
                )
                return [
                    {
                        "code": score.code,
                        "name": code_to_name.get(score.code, ""),
                        "score": round(score.score, 4),
                        "rank": score.rank,
                        "source": score.source,
                        "confidence": round(score.confidence, 3),
                        "factors": score.factors,
                        "asof_date": score.asof_date.isoformat() if score.asof_date else None,
                    }
                    for score in result.scores[:top_n]
                ]
            return []
        except Exception as e:
            logger.warning(f"Failed to get alpha stock scores: {e}")
            return []

    def _resolve_security_names(self, codes: list[str]) -> dict[str, str]:
        """根据代码解析证券名称"""
        unique_codes = [c for c in {code for code in codes if code}]
        if not unique_codes:
            return {}

        name_map: dict[str, str] = {}

        # 尝试从股票信息获取
        try:
            from apps.equity.infrastructure.models import StockInfoModel

            stock_rows = StockInfoModel._default_manager.filter(
                stock_code__in=unique_codes
            ).values("stock_code", "name")
            for row in stock_rows:
                name_map[row["stock_code"]] = row["name"]
        except Exception as e:
            logger.debug(f"Failed to resolve stock names: {e}")

        # 尝试从基金信息获取未解析的代码
        unresolved = [code for code in unique_codes if code not in name_map]
        if unresolved:
            try:
                from apps.fund.infrastructure.models import FundInfoModel

                code_to_fund_code = {code: code.split(".")[0] for code in unresolved}
                fund_rows = FundInfoModel._default_manager.filter(
                    fund_code__in=list(set(code_to_fund_code.values()))
                ).values("fund_code", "fund_name")
                fund_map = {row["fund_code"]: row["fund_name"] for row in fund_rows}
                for code, fund_code in code_to_fund_code.items():
                    if fund_code in fund_map:
                        name_map[code] = fund_map[fund_code]
            except Exception as e:
                logger.debug(f"Failed to resolve fund names: {e}")

        return name_map

    def _get_provider_status(self) -> dict[str, Any]:
        """获取 Alpha Provider 状态"""
        try:
            from apps.alpha.application.services import AlphaService
            from shared.infrastructure.metrics import get_alpha_metrics

            service = AlphaService()
            provider_status = service.get_provider_status()
            metrics = get_alpha_metrics()

            provider_metrics = {}
            for provider_name in provider_status.keys():
                success_rate = metrics.registry.get_metric(
                    "alpha_provider_success_rate",
                    {"provider": provider_name}
                )
                latency = metrics.registry.get_metric(
                    "alpha_provider_latency_ms",
                    {"provider": provider_name}
                )

                provider_metrics[provider_name] = {
                    "success_rate": round(success_rate.value, 3) if success_rate else 0.0,
                    "latency_ms": int(latency.value) if latency else 0,
                }

            return {
                "providers": provider_status,
                "metrics": provider_metrics,
                "timestamp": django_timezone.now().isoformat(),
                "status": "available",
                "data_source": "live",
                "warning_message": None,
            }
        except Exception as e:
            logger.warning(f"Failed to get alpha provider status: {e}")
            return {
                "providers": {},
                "metrics": {},
                "timestamp": None,
                "status": "degraded",
                "data_source": "fallback",
                "warning_message": "provider_status_unavailable",
            }

    def _get_coverage_metrics(self) -> dict[str, Any]:
        """获取 Alpha 覆盖率指标"""
        try:
            from shared.infrastructure.metrics import get_alpha_metrics

            metrics = get_alpha_metrics()

            coverage = metrics.registry.get_metric("alpha_coverage_ratio")
            request_count = metrics.registry.get_metric("alpha_score_request_count")
            cache_hit_rate = metrics.registry.get_metric("alpha_cache_hit_rate")

            return {
                "coverage_ratio": round(coverage.value, 3) if coverage else 0.0,
                "total_requests": int(request_count.value) if request_count else 0,
                "cache_hit_rate": round(cache_hit_rate.value, 3) if cache_hit_rate else 0.0,
                "timestamp": django_timezone.now().isoformat(),
                "status": "available",
                "data_source": "live",
                "warning_message": None,
            }
        except Exception as e:
            logger.warning(f"Failed to get alpha coverage metrics: {e}")
            return {
                "coverage_ratio": 0.0,
                "total_requests": 0,
                "cache_hit_rate": 0.0,
                "timestamp": None,
                "status": "degraded",
                "data_source": "fallback",
                "warning_message": "coverage_metrics_unavailable",
            }

    def _get_ic_trends(self, days: int) -> list[dict[str, Any]]:
        """获取 Alpha IC/ICIR 趋势数据"""
        try:
            from apps.alpha.infrastructure.models import QlibModelRegistryModel

            active_models = QlibModelRegistryModel._default_manager.filter(is_active=True)

            if not active_models.exists():
                return self._empty_ic_data(days)

            trends = []
            base_date = date.today()

            for i in range(days):
                check_date = base_date - timedelta(days=i)

                model_metrics = QlibModelRegistryModel._default_manager.filter(
                    created_at__date=check_date
                ).first()

                if model_metrics:
                    trends.append({
                        "date": check_date.isoformat(),
                        "ic": round(float(model_metrics.ic), 4) if model_metrics.ic else None,
                        "icir": round(float(model_metrics.icir), 4) if model_metrics.icir else None,
                        "rank_ic": round(float(model_metrics.rank_ic), 4) if model_metrics.rank_ic else None,
                    })
                else:
                    trends.append({
                        "date": check_date.isoformat(),
                        "ic": None,
                        "icir": None,
                        "rank_ic": None,
                    })

            return list(reversed(trends))

        except Exception as e:
            logger.warning(f"Failed to get alpha IC trends: {e}")
            return self._empty_ic_data(days)

    def _empty_ic_data(self, days: int) -> list[dict[str, Any]]:
        """返回显式 unavailable 的空 IC 时间序列。"""
        trends = []
        base_date = date.today()

        for i in range(days):
            check_date = base_date - timedelta(days=days - i)
            trends.append({
                "date": check_date.isoformat(),
                "ic": None,
                "icir": None,
                "rank_ic": None,
            })

        return trends

    def _build_ic_trends_meta(self, trends: list[dict[str, Any]]) -> dict[str, Any]:
        has_live_data = any(
            row.get("ic") is not None or row.get("icir") is not None or row.get("rank_ic") is not None
            for row in trends
        )
        if has_live_data:
            return {
                "status": "available",
                "data_source": "live",
                "warning_message": None,
            }
        return {
            "status": "unavailable",
            "data_source": "fallback",
            "warning_message": "ic_trends_unavailable",
        }


# ============================================================================
# Decision Plane Query Service
# ============================================================================

@dataclass(frozen=True)
class DecisionPlaneData:
    """决策平面数据"""
    beta_gate_visible_classes: str
    alpha_watch_count: int
    alpha_candidate_count: int
    alpha_actionable_count: int
    quota_total: int
    quota_used: int
    quota_remaining: int
    quota_usage_percent: float
    actionable_candidates: list[Any]
    pending_requests: list[Any]


class DecisionPlaneQuery:
    """
    决策平面查询服务

    聚合 Beta Gate、Alpha 触发器、配额和候选数据。

    Example:
        >>> query = DecisionPlaneQuery()
        >>> data = query.execute()
        >>> print(data.quota_remaining)
    """

    def execute(self, max_candidates: int = 5, max_pending: int = 10) -> DecisionPlaneData:
        """
        执行查询

        Args:
            max_candidates: 最大候选数量
            max_pending: 最大待处理请求数量

        Returns:
            DecisionPlaneData
        """
        return DecisionPlaneData(
            beta_gate_visible_classes=self._get_beta_gate_visible_classes(),
            alpha_watch_count=self._get_alpha_status_count("WATCH"),
            alpha_candidate_count=self._get_alpha_status_count("CANDIDATE"),
            alpha_actionable_count=self._get_alpha_status_count("ACTIONABLE"),
            quota_total=self._get_quota_total(),
            quota_used=self._get_quota_used(),
            quota_remaining=self._get_quota_remaining(),
            quota_usage_percent=self._get_quota_usage_percent(),
            actionable_candidates=self._get_actionable_candidates(max_candidates),
            pending_requests=self._get_pending_requests(max_pending)
        )

    def _get_beta_gate_visible_classes(self) -> str:
        """获取 Beta Gate 允许的可见资产类别"""
        try:
            from apps.beta_gate.infrastructure.models import GateConfigModel

            config = GateConfigModel._default_manager.active().first()
            if config:
                regime_c = config.regime_constraints if isinstance(config.regime_constraints, dict) else {}
                allowed_classes = regime_c.get('allowed_asset_classes', [])
                if allowed_classes:
                    return ", ".join(allowed_classes[:3])
            return "全部"
        except Exception as e:
            logger.warning(f"Failed to get beta gate visible classes: {e}")
            return "-"

    def _get_alpha_status_count(self, status: str) -> int:
        """获取 Alpha 候选状态计数"""
        try:
            from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel

            return AlphaCandidateModel._default_manager.filter(status=status).count()
        except Exception as e:
            logger.warning(f"Failed to get alpha status count for {status}: {e}")
            return 0

    def _get_quota_total(self) -> int:
        """获取决策配额总数"""
        try:
            from apps.decision_rhythm.domain.entities import QuotaPeriod
            from apps.decision_rhythm.infrastructure.models import DecisionQuotaModel

            quota = (
                DecisionQuotaModel._default_manager
                .filter(period=QuotaPeriod.WEEKLY.value)
                .order_by('-period_start')
                .first()
            )
            return getattr(quota, "max_decisions", 10) if quota else 10
        except Exception as e:
            logger.warning(f"Failed to get quota total: {e}")
            return 10

    def _get_quota_used(self) -> int:
        """获取已使用的决策配额"""
        try:
            from apps.decision_rhythm.domain.entities import QuotaPeriod
            from apps.decision_rhythm.infrastructure.models import DecisionQuotaModel

            quota = (
                DecisionQuotaModel._default_manager
                .filter(period=QuotaPeriod.WEEKLY.value)
                .order_by('-period_start')
                .first()
            )
            return getattr(quota, "used_decisions", 0) if quota else 0
        except Exception as e:
            logger.warning(f"Failed to get quota used: {e}")
            return 0

    def _get_quota_remaining(self) -> int:
        """获取剩余决策配额"""
        try:
            from apps.decision_rhythm.domain.entities import QuotaPeriod
            from apps.decision_rhythm.infrastructure.models import DecisionQuotaModel

            quota = (
                DecisionQuotaModel._default_manager
                .filter(period=QuotaPeriod.WEEKLY.value)
                .order_by('-period_start')
                .first()
            )
            if quota:
                max_decisions = getattr(quota, "max_decisions", 10)
                used_decisions = getattr(quota, "used_decisions", 0)
                return max(0, max_decisions - used_decisions)
            return 10
        except Exception as e:
            logger.warning(f"Failed to get quota remaining: {e}")
            return 10

    def _get_quota_usage_percent(self) -> float:
        """获取决策配额使用百分比"""
        try:
            total = self._get_quota_total()
            used = self._get_quota_used()
            if total > 0:
                return round(used / total * 100, 1)
            return 0.0
        except Exception as e:
            logger.warning(f"Failed to get quota usage percent: {e}")
            return 0.0

    def _get_actionable_candidates(self, max_count: int) -> list[Any]:
        """获取可操作候选列表"""
        try:
            from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel
            from apps.decision_rhythm.infrastructure.models import DecisionRequestModel
            from apps.equity.infrastructure.models import ValuationRepairTrackingModel

            # 获取已批准但未执行的资产代码
            pending_codes = set(
                (code or "").upper()
                for code in DecisionRequestModel._default_manager
                .filter(
                    response__approved=True,
                    execution_status__in=['PENDING', 'FAILED']
                )
                .values_list('asset_code', flat=True)
            )

            candidates = list(
                AlphaCandidateModel._default_manager
                .filter(status='ACTIONABLE')
                .order_by('-confidence', '-created_at')[:50]
            )

            # 批量获取估值修复状态
            candidate_codes = [
                (getattr(item, "asset_code", "") or "").upper()
                for item in candidates
            ]
            repair_map = {}
            try:
                repair_records = ValuationRepairTrackingModel._default_manager.filter(
                    stock_code__in=[c for c in candidate_codes if c],
                    is_active=True
                ).values(
                    'stock_code', 'current_phase', 'signal', 'composite_percentile',
                    'repair_progress', 'repair_speed_per_30d', 'estimated_days_to_target'
                )
                repair_map = {r['stock_code']: r for r in repair_records}
            except Exception as e:
                logger.warning(f"Failed to get valuation repair info: {e}")

            deduped = []
            seen_codes = set()
            for item in candidates:
                code = (getattr(item, "asset_code", "") or "").upper()
                if not code or code in seen_codes or code in pending_codes:
                    continue
                seen_codes.add(code)

                # 添加估值修复信息
                if code in repair_map:
                    r = repair_map[code]
                    repair_payload = {
                        'phase': r.get('current_phase'),
                        'signal': r.get('signal'),
                        'composite_percentile': r.get('composite_percentile'),
                        'repair_progress': r.get('repair_progress'),
                        'repair_speed_per_30d': r.get('repair_speed_per_30d'),
                        'estimated_days_to_target': r.get('estimated_days_to_target'),
                    }
                    item.valuation_repair = repair_payload
                    item._valuation_repair = repair_payload
                else:
                    item.valuation_repair = None
                    item._valuation_repair = None

                deduped.append(item)
                if len(deduped) >= max_count:
                    break

            return deduped
        except Exception as e:
            logger.warning(f"Failed to get actionable candidates: {e}")
            return []

    def _get_pending_requests(self, max_count: int) -> list[Any]:
        """获取待处理请求列表"""
        try:
            from apps.decision_rhythm.infrastructure.models import DecisionRequestModel

            requests = list(
                DecisionRequestModel._default_manager
                .filter(
                    response__approved=True,
                    execution_status__in=['PENDING', 'FAILED']
                )
                .order_by('-requested_at')[:50]
            )

            deduped = []
            seen_codes = set()
            for item in requests:
                code = (getattr(item, "asset_code", "") or "").upper()
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                deduped.append(item)
                if len(deduped) >= max_count:
                    break

            return deduped
        except Exception as e:
            logger.warning(f"Failed to get pending requests: {e}")
            return []


# ============================================================================
# Regime Summary Query Service
# ============================================================================

@dataclass(frozen=True)
class RegimeSummaryData:
    """Regime 摘要数据"""
    current_regime: str
    regime_date: date | None
    regime_confidence: float
    growth_momentum_z: float
    inflation_momentum_z: float
    pmi_value: float | None
    cpi_value: float | None
    regime_distribution: dict[str, int]
    regime_data_health: bool
    regime_warnings: list[str]


class RegimeSummaryQuery:
    """
    Regime 摘要查询服务

    聚合当前 Regime 状态和宏观指标数据。

    Example:
        >>> query = RegimeSummaryQuery()
        >>> data = query.execute()
        >>> print(data.current_regime)
    """

    def execute(self, user_id: int | None = None) -> RegimeSummaryData:
        """
        执行查询

        Args:
            user_id: 用户 ID（用于某些个性化数据）

        Returns:
            RegimeSummaryData
        """
        try:
            from apps.regime.infrastructure.repositories import DjangoRegimeRepository

            regime_repo = DjangoRegimeRepository()
            current_state = regime_repo.get_current_regime()

            if current_state:
                return RegimeSummaryData(
                    current_regime=current_state.dominant_regime or "Unknown",
                    regime_date=current_state.observed_at,
                    regime_confidence=float(current_state.confidence or 0.0),
                    growth_momentum_z=float(current_state.growth_momentum_z),
                    inflation_momentum_z=float(current_state.inflation_momentum_z),
                    pmi_value=self._get_latest_macro_value("PMI"),
                    cpi_value=self._get_latest_macro_value("CPI"),
                    regime_distribution={},
                    regime_data_health=True,
                    regime_warnings=[]
                )

            # 返回默认值
            return RegimeSummaryData(
                current_regime="Unknown",
                regime_date=None,
                regime_confidence=0.0,
                growth_momentum_z=0.0,
                inflation_momentum_z=0.0,
                pmi_value=None,
                cpi_value=None,
                regime_distribution={},
                regime_data_health=False,
                regime_warnings=["No regime data available"]
            )

        except Exception as e:
            logger.warning(f"Failed to get regime summary: {e}")
            return RegimeSummaryData(
                current_regime="Unknown",
                regime_date=None,
                regime_confidence=0.0,
                growth_momentum_z=0.0,
                inflation_momentum_z=0.0,
                pmi_value=None,
                cpi_value=None,
                regime_distribution={},
                regime_data_health=False,
                regime_warnings=[str(e)]
            )

    def _get_latest_macro_value(self, indicator_code: str) -> float | None:
        """获取最新宏观指标值"""
        try:
            from apps.macro.infrastructure.models import MacroIndicator

            latest = (
                MacroIndicator._default_manager
                .filter(code=indicator_code)
                .order_by('-reporting_period')
                .first()
            )
            if latest:
                return float(latest.value)
            return None
        except Exception as e:
            logger.debug(f"Failed to get macro value for {indicator_code}: {e}")
            return None


class DashboardDetailQuery:
    """Dashboard 详情查询服务。"""

    def get_position_detail(self, user_id: int, asset_code: str) -> dict[str, Any]:
        """获取持仓详情和相关信号。"""
        try:
            from apps.account.infrastructure.models import PositionModel
            from apps.signal.infrastructure.models import InvestmentSignalModel

            position = PositionModel._default_manager.get(
                user_id=user_id,
                asset_code=asset_code,
            )
            related_signals = list(
                InvestmentSignalModel._default_manager.filter(
                    asset_code=asset_code,
                    status='active',
                ).order_by('-created_at')[:5]
            )
            return {
                "position": position,
                "related_signals": related_signals,
                "asset_code": asset_code,
                "error": None,
            }
        except PositionModel.DoesNotExist:
            return {
                "position": None,
                "related_signals": [],
                "asset_code": asset_code,
                "error": f'未找到持仓 {asset_code}',
            }
        except Exception as e:
            logger.warning(f"Failed to get position detail for {asset_code}: {e}")
            return {
                "position": None,
                "related_signals": [],
                "asset_code": asset_code,
                "error": str(e),
            }

    def generate_alpha_candidates(self) -> dict[str, int]:
        """批量生成 Alpha 候选并返回统计结果。"""
        from apps.alpha_trigger.application.use_cases import (
            GenerateCandidateRequest,
            GenerateCandidateUseCase,
        )
        from apps.alpha_trigger.domain.entities import CandidateStatus
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel, AlphaTriggerModel
        from apps.alpha_trigger.infrastructure.repositories import (
            get_candidate_repository,
            get_trigger_repository,
        )

        trigger_repo = get_trigger_repository()
        candidate_repo = get_candidate_repository()
        use_case = GenerateCandidateUseCase(trigger_repo, candidate_repo)

        active_triggers = list(
            AlphaTriggerModel._default_manager
            .filter(status__in=[AlphaTriggerModel.ACTIVE, AlphaTriggerModel.TRIGGERED])
            .order_by('-created_at')[:50]
        )
        trigger_ids = [t.trigger_id for t in active_triggers]
        existing_trigger_ids = set(
            AlphaCandidateModel._default_manager
            .filter(trigger_id__in=trigger_ids, status__in=['WATCH', 'CANDIDATE', 'ACTIONABLE'])
            .values_list('trigger_id', flat=True)
        )

        generated = 0
        promoted = 0
        failed = 0
        skipped = 0

        for trigger in active_triggers:
            if trigger.trigger_id in existing_trigger_ids:
                skipped += 1
                continue

            resp = use_case.execute(
                GenerateCandidateRequest(
                    trigger_id=trigger.trigger_id,
                    time_window_days=90,
                )
            )
            if not resp.success or not resp.candidate:
                failed += 1
                continue

            generated += 1
            if float(resp.candidate.confidence or 0) >= 0.70:
                try:
                    candidate_repo.update_status(resp.candidate.candidate_id, CandidateStatus.ACTIONABLE)
                    promoted += 1
                except Exception:
                    pass

        actionable_count = AlphaCandidateModel._default_manager.filter(status='ACTIONABLE').count()
        return {
            "generated": generated,
            "promoted_to_actionable": promoted,
            "skipped_existing": skipped,
            "failed": failed,
            "active_trigger_count": len(active_triggers),
            "actionable_count": actionable_count,
        }


# ============================================================================
# Singleton accessors
# ============================================================================

_alpha_visualization_query: AlphaVisualizationQuery | None = None
_decision_plane_query: DecisionPlaneQuery | None = None
_regime_summary_query: RegimeSummaryQuery | None = None
_dashboard_detail_query: DashboardDetailQuery | None = None


def get_alpha_visualization_query() -> AlphaVisualizationQuery:
    """获取 Alpha 可视化查询服务单例"""
    global _alpha_visualization_query
    if _alpha_visualization_query is None:
        _alpha_visualization_query = AlphaVisualizationQuery()
    return _alpha_visualization_query


def get_decision_plane_query() -> DecisionPlaneQuery:
    """获取决策平面查询服务单例"""
    global _decision_plane_query
    if _decision_plane_query is None:
        _decision_plane_query = DecisionPlaneQuery()
    return _decision_plane_query


def get_regime_summary_query() -> RegimeSummaryQuery:
    """获取 Regime 摘要查询服务单例"""
    global _regime_summary_query
    if _regime_summary_query is None:
        _regime_summary_query = RegimeSummaryQuery()
    return _regime_summary_query


def get_dashboard_detail_query() -> DashboardDetailQuery:
    """获取 dashboard 详情查询服务单例。"""
    global _dashboard_detail_query
    if _dashboard_detail_query is None:
        _dashboard_detail_query = DashboardDetailQuery()
    return _dashboard_detail_query
