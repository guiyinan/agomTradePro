"""
Dashboard Application Use Cases

首页数据聚合用例。
"""

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from time import perf_counter
from typing import Any, Protocol, TypedDict

from apps.account.domain.entities import (
    AccountProfile,
    PortfolioSnapshot,
    Position,
    RegimeMatchAnalysis,
)
from apps.account.domain.interfaces import (
    AccountRepositoryProtocol,
    PortfolioRepositoryProtocol,
    PositionRepositoryProtocol,
)
from apps.dashboard.application.repository_provider import (
    get_account_repository,
    get_dashboard_ai_insight_client,
    get_dashboard_overview_repository,
    get_portfolio_repository,
    get_position_repository,
    get_signal_repository,
)
from apps.signal.domain.entities import InvestmentSignal, SignalStatus
from apps.strategy.domain.protocols import (
    AssetClassValueProtocol,
    PositionLikeProtocol,
)
from core.exceptions import ResourceNotFoundError

logger = logging.getLogger(__name__)
_DASHBOARD_DATA_PERF_WARNING_MS = 3000
_ALLOCATION_ASSET_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{0,19}$")
_ALLOCATION_ASSET_CLASSES = frozenset({"equity", "fixed_income", "commodity", "cash"})
_ALLOCATION_REGIMES = frozenset({"Recovery", "Overheat", "Stagflation", "Deflation"})
_ALLOCATION_RISK_PROFILES = frozenset({"conservative", "moderate", "aggressive", "defensive"})


@dataclass
class _AllocationAssetClassValue:
    """Strategy-facing asset-class value isolated from Account entities."""

    value: str


@dataclass(frozen=True)
class _AllocationPosition:
    """Validated position projection consumed by Strategy allocation."""

    asset_code: str
    market_value: Decimal
    asset_class: AssetClassValueProtocol


class _MacroDataHealth(TypedDict):
    """Health summary for the macro inputs used by the dashboard."""

    is_healthy: bool
    warnings: list[str]


class _DashboardRegimeState(TypedDict):
    """Dashboard projection of the canonical current-Regime result."""

    current_regime: str
    regime_date: date | None
    regime_confidence: float
    growth_momentum_z: float
    inflation_momentum_z: float
    regime_distribution: dict[str, float]
    regime_data_health: str
    regime_warnings: list[str]


class _MacroObservation(Protocol):
    """Date fields required to assess macro observation staleness."""

    published_at: date | None
    reporting_period: date


class _SignalRepository(Protocol):
    """Dashboard-facing signal repository contract."""

    def get_user_signals(
        self,
        user_id: int,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[InvestmentSignal]: ...


class _DashboardOverviewRepository(Protocol):
    """Cross-app read model consumed by the dashboard overview use case."""

    def get_user_simulated_account_totals(self, user_id: int) -> dict[str, float] | None: ...

    def get_simulated_positions(self, user_id: int) -> list[dict[str, Any]]: ...

    def get_policy_environment(
        self, user_id: int
    ) -> tuple[str | None, date | None, int, list[dict[str, Any]]]: ...

    def get_growth_series(
        self,
        indicator_code: str,
        end_date: date,
        *,
        use_pit: bool = False,
        full: bool = False,
    ) -> list[Any]: ...

    def get_inflation_series(
        self,
        indicator_code: str,
        end_date: date,
        *,
        use_pit: bool = False,
        full: bool = False,
    ) -> list[Any]: ...

    def get_primary_system_ai_provider_payload(self) -> dict[str, Any] | None: ...

    def list_global_investment_rule_payloads(self) -> list[dict[str, Any]]: ...

    def get_portfolio_snapshot_performance_data(
        self, portfolio_id: int
    ) -> list[dict[str, Any]]: ...

    def get_simulated_performance_data(
        self,
        *,
        user_id: int,
        account_id: int | None,
        days: int,
    ) -> list[dict[str, Any]]: ...


def _display_risk_tolerance(risk_tolerance: Any) -> str:
    """Return a human-readable risk tolerance label for domain or ORM values."""
    value = getattr(risk_tolerance, "value", risk_tolerance)
    labels = {
        "conservative": "保守型",
        "moderate": "稳健型",
        "aggressive": "激进型",
        "defensive": "防御型",
    }
    return labels.get(str(value), str(value))


def _risk_tolerance_value(risk_tolerance: Any) -> str:
    """Normalize risk tolerance enum/value to the string expected by strategy layer."""
    return str(getattr(risk_tolerance, "value", risk_tolerance))


def _normalize_regime_distribution(
    current_regime: str,
    raw_distribution: dict[str, float] | None = None,
) -> dict[str, float]:
    """Return a template-safe quadrant distribution for the dashboard."""
    quadrant_keys = ("Recovery", "Overheat", "Deflation", "Stagflation")
    normalized = dict.fromkeys(quadrant_keys, 0.0)

    if raw_distribution:
        for key in quadrant_keys:
            value = raw_distribution.get(key)
            if value is not None:
                normalized[key] = float(value)
        if any(value > 0 for value in normalized.values()):
            return normalized
    return normalized


@dataclass
class DashboardData:
    """首页数据DTO"""

    # 用户信息
    user_id: int
    username: str
    display_name: str

    # 宏观环境
    current_regime: str
    regime_date: date | None
    regime_confidence: float

    # 资产总览
    total_assets: float
    initial_capital: float
    total_return: float
    total_return_pct: float
    cash_balance: float
    invested_value: float
    invested_ratio: float

    # 持仓分析
    positions: list[dict[str, Any]]
    position_count: int
    regime_match_score: float
    regime_recommendations: list[str]

    # 投资信号
    active_signals: list[dict[str, Any]]
    signal_stats: dict[str, int]

    # 资产配置
    asset_allocation: list[dict[str, Any]]

    # AI建议
    ai_insights: list[str]

    # 资产配置建议（新增）
    allocation_advice: dict[str, Any] | None = None

    # 图表数据（用于前端渲染）
    allocation_data: dict[str, float] = field(default_factory=dict)  # 资产配置饼图数据
    performance_data: list[dict[str, Any]] = field(default_factory=list)  # 收益趋势图数据

    # 有默认值的字段放最后
    # 政策环境（新增）
    current_policy_level: str | None = None
    current_policy_date: date | None = None
    pending_review_count: int = 0
    recent_policies: list[dict[str, Any]] = field(default_factory=list)
    # 宏观环境额外数据
    growth_momentum_z: float = 0.0
    inflation_momentum_z: float = 0.0
    regime_distribution: dict[str, float] = field(default_factory=dict)
    pmi_value: float | None = None
    cpi_value: float | None = None
    regime_data_health: str = "unknown"
    regime_warnings: list[str] = field(default_factory=list)


class GetDashboardDataUseCase:
    """获取首页数据用例"""

    MAX_MACRO_STALENESS_DAYS = 45
    INDICATOR_STALENESS_DAYS = {
        "PMI": 70,
        "CPI": 70,
    }
    MIN_MACRO_POINTS = 12

    def __init__(
        self,
        account_repo: AccountRepositoryProtocol | None = None,
        portfolio_repo: PortfolioRepositoryProtocol | None = None,
        position_repo: PositionRepositoryProtocol | None = None,
        regime_repo: object | None = None,
        signal_repo: _SignalRepository | None = None,
        overview_repo: _DashboardOverviewRepository | None = None,
    ) -> None:
        self.account_repo = account_repo or get_account_repository()
        self.portfolio_repo = portfolio_repo or get_portfolio_repository()
        self.position_repo = position_repo or get_position_repository()
        # Kept for constructor compatibility; current Regime data is resolver-owned.
        self.regime_repo = regime_repo
        self.signal_repo = signal_repo or get_signal_repository()
        self.overview_repo = overview_repo or get_dashboard_overview_repository()

    def execute(self, user_id: int) -> DashboardData:
        """
        获取首页所有数据

        聚合数据来源：
        1. 用户账户配置
        2. 当前Regime状态（公共数据）
        3. 投资组合快照
        4. 持仓列表及Regime匹配度
        5. 投资信号统计
        6. AI建议生成
        """
        started_at = perf_counter()
        step_durations_ms: dict[str, int] = {}

        def _track_step(step_name: str, step_started_at: float) -> None:
            step_durations_ms[step_name] = int((perf_counter() - step_started_at) * 1000)

        # 1. 获取用户配置，如果不存在则自动创建
        step_started_at = perf_counter()
        profile = self.account_repo.get_by_user_id(user_id)
        if not profile:
            # 自动创建默认账户配置
            profile = self.account_repo.create_default_profile(user_id)
        _track_step("profile", step_started_at)

        # 2. 实时计算当前Regime（使用 V2 水平法）
        # V2 水平法：基于 PMI/CPI 的绝对水平判定
        # - PMI >= 50 → 经济扩张
        # - CPI > 2% → 高通胀
        # 判定矩阵：Recovery (PMI>50, CPI<=2%), Overheat (PMI>50, CPI>2%),
        #          Stagflation (PMI<50, CPI>2%), Deflation (PMI<50, CPI<=2%)
        step_started_at = perf_counter()
        health = self._assess_macro_data_health(
            growth_indicator="PMI",
            inflation_indicator="CPI",
            as_of_date=date.today(),
        )
        _track_step("macro_health", step_started_at)

        step_started_at = perf_counter()
        regime_state = self._resolve_regime_state(as_of_date=date.today(), health=health)
        current_regime = regime_state["current_regime"]
        regime_date = regime_state["regime_date"]
        regime_confidence = regime_state["regime_confidence"]
        growth_momentum_z = regime_state["growth_momentum_z"]
        inflation_momentum_z = regime_state["inflation_momentum_z"]
        regime_distribution = regime_state["regime_distribution"]
        regime_data_health = regime_state["regime_data_health"]
        regime_warnings = regime_state["regime_warnings"]
        _track_step("regime_resolution", step_started_at)

        # 获取最新的 PMI 和 CPI 值
        step_started_at = perf_counter()
        pmi_value, cpi_value = self._get_latest_macro_values()
        _track_step("macro_values", step_started_at)

        # 3. 获取投资组合快照
        step_started_at = perf_counter()
        portfolio_id = self.account_repo.get_or_create_default_portfolio(user_id)
        snapshot = self.portfolio_repo.get_portfolio_snapshot(portfolio_id)
        if snapshot is None:
            raise ResourceNotFoundError(
                "默认投资组合快照不存在",
                details={"portfolio_id": portfolio_id, "user_id": user_id},
            )
        account_totals = self._get_user_account_totals(user_id)
        _track_step("portfolio_snapshot", step_started_at)

        # 4. 获取持仓列表（优先展示当前模拟账户体系的持仓）
        step_started_at = perf_counter()
        simulated_positions = self._get_simulated_positions(user_id)
        positions_dict = simulated_positions or self._format_positions(snapshot.positions)
        _track_step("positions", step_started_at)

        # 5. 计算Regime匹配度
        from apps.account.domain.services import PositionService

        step_started_at = perf_counter()
        match_analysis = PositionService.calculate_regime_match_score(
            positions=snapshot.positions,
            current_regime=current_regime,
        )
        _track_step("regime_match", step_started_at)

        # 6. 获取投资信号
        step_started_at = perf_counter()
        active_signals = self._get_user_signals(user_id)
        signal_stats = self._calculate_signal_stats(user_id)
        _track_step("signals", step_started_at)

        # 7. 资产配置分布
        step_started_at = perf_counter()
        asset_allocation = (
            self._format_simulated_asset_allocation(simulated_positions)
            if simulated_positions
            else self._format_asset_allocation(snapshot.positions)
        )
        _track_step("asset_allocation", step_started_at)

        # 8. 获取政策环境信息
        step_started_at = perf_counter()
        current_policy_level, current_policy_date, pending_review_count, recent_policies = (
            self._get_policy_environment(user_id)
        )
        _track_step("policy_environment", step_started_at)

        # 9. 生成AI建议
        step_started_at = perf_counter()
        ai_insights = self._generate_ai_insights(
            current_regime=current_regime,
            snapshot=snapshot,
            match_analysis=match_analysis,
            active_signals=active_signals,
            policy_level=current_policy_level,
        )
        _track_step("ai_insights", step_started_at)

        # 10. 生成资产配置建议（新增）
        step_started_at = perf_counter()
        allocation_advice = self._generate_allocation_advice(
            current_regime=current_regime,
            policy_level=current_policy_level,
            profile=profile,
            total_assets=float(snapshot.total_value),
            positions=snapshot.positions,
        )
        _track_step("allocation_advice", step_started_at)

        # 11. 生成图表数据
        step_started_at = perf_counter()
        allocation_data = self._generate_allocation_chart_data(asset_allocation)
        performance_data = self._generate_performance_chart_data(user_id=user_id)
        _track_step("charts", step_started_at)

        dashboard_data = DashboardData(
            user_id=user_id,
            username="",  # 由视图层填充
            display_name=profile.display_name,
            current_regime=current_regime,
            regime_date=regime_date,
            regime_confidence=regime_confidence,
            growth_momentum_z=growth_momentum_z,
            inflation_momentum_z=inflation_momentum_z,
            regime_distribution=regime_distribution,
            pmi_value=pmi_value,
            cpi_value=cpi_value,
            regime_data_health=regime_data_health,
            regime_warnings=regime_warnings,
            total_assets=account_totals["total_assets"],
            initial_capital=account_totals["initial_capital"] or float(profile.initial_capital),
            total_return=account_totals["total_return"],
            total_return_pct=account_totals["total_return_pct"],
            cash_balance=account_totals["cash_balance"],
            invested_value=account_totals["invested_value"],
            invested_ratio=account_totals["invested_ratio"],
            positions=positions_dict,
            position_count=len(positions_dict),
            regime_match_score=match_analysis.total_match_score,
            regime_recommendations=match_analysis.recommendations,
            active_signals=active_signals,
            signal_stats=signal_stats,
            asset_allocation=asset_allocation,
            ai_insights=ai_insights,
            allocation_advice=allocation_advice,  # 新增
            current_policy_level=current_policy_level,
            current_policy_date=current_policy_date,
            pending_review_count=pending_review_count,
            recent_policies=recent_policies,
            allocation_data=allocation_data,
            performance_data=performance_data,
        )

        total_duration_ms = int((perf_counter() - started_at) * 1000)
        log_method = (
            logger.warning if total_duration_ms >= _DASHBOARD_DATA_PERF_WARNING_MS else logger.info
        )
        log_method(
            "Dashboard data aggregation completed",
            extra={
                "event": "dashboard_data_aggregation_completed",
                "user_id": user_id,
                "duration_ms": total_duration_ms,
                "step_durations_ms": step_durations_ms,
                "position_count": len(positions_dict),
                "signal_count": len(active_signals),
                "ai_insight_count": len(ai_insights),
                "regime": current_regime,
                "policy_level": current_policy_level,
                "used_simulated_positions": bool(simulated_positions),
            },
        )
        return dashboard_data

    def _resolve_regime_state(
        self,
        *,
        as_of_date: date,
        health: _MacroDataHealth,
    ) -> _DashboardRegimeState:
        """Project the canonical resolver result without reviving stale snapshots."""
        from apps.regime.application.current_regime import resolve_current_regime

        current = resolve_current_regime(as_of_date=as_of_date)
        warnings = list(current.warnings)
        for warning in health["warnings"]:
            if warning not in warnings:
                warnings.append(warning)

        is_usable = current.dominant_regime != "Unknown" and not current.must_not_use_for_decision
        current_regime = current.dominant_regime if is_usable else "Unknown"
        regime_distribution = (
            _normalize_regime_distribution(
                current_regime=current_regime,
                raw_distribution=current.distribution,
            )
            if is_usable
            else _normalize_regime_distribution(current_regime="Unknown")
        )

        if is_usable:
            regime_data_health = "healthy" if health["is_healthy"] and not warnings else "degraded"
        else:
            if current.blocked_reason == "regime_data_unavailable":
                regime_data_health = "unavailable"
            else:
                regime_data_health = "degraded"
            if not warnings:
                warnings.append("Regime 当前数据不可用于决策")

        return {
            "current_regime": current_regime,
            "regime_date": current.observed_at,
            "regime_confidence": float(current.confidence or 0.0),
            "growth_momentum_z": float(current.growth_momentum_z or 0.0),
            "inflation_momentum_z": float(current.inflation_momentum_z or 0.0),
            "regime_distribution": regime_distribution,
            "regime_data_health": regime_data_health,
            "regime_warnings": warnings,
        }

    def _get_user_account_totals(self, user_id: int) -> dict[str, float]:
        """Prefer the current simulated-account system for dashboard totals."""
        account_totals = self.overview_repo.get_user_simulated_account_totals(user_id)
        if account_totals is None:
            portfolio_id = self.account_repo.get_or_create_default_portfolio(user_id)
            snapshot = self.portfolio_repo.get_portfolio_snapshot(portfolio_id)
            if snapshot is None:
                raise ResourceNotFoundError(
                    "默认投资组合快照不存在",
                    details={"portfolio_id": portfolio_id, "user_id": user_id},
                )
            profile = self.account_repo.get_by_user_id(user_id)
            initial_capital = (
                float(profile.initial_capital)
                if profile is not None
                else float(snapshot.total_value - snapshot.total_return)
            )
            total_assets = float(snapshot.total_value)
            cash_balance = float(snapshot.cash_balance)
            invested_value = float(snapshot.invested_value)
            invested_ratio = snapshot.get_invested_ratio()
            return {
                "total_assets": total_assets,
                "initial_capital": initial_capital,
                "cash_balance": cash_balance,
                "invested_value": invested_value,
                "invested_ratio": invested_ratio,
                "total_return": float(snapshot.total_return),
                "total_return_pct": snapshot.total_return_pct,
            }
        return account_totals

    def _assess_macro_data_health(
        self,
        growth_indicator: str,
        inflation_indicator: str,
        as_of_date: date,
    ) -> _MacroDataHealth:
        """评估 Regime 输入数据健康度（时效+完整性）。"""
        warnings: list[str] = []

        growth_full = self.overview_repo.get_growth_series(
            indicator_code=growth_indicator,
            end_date=as_of_date,
            use_pit=False,
            full=True,
        )
        inflation_full = self.overview_repo.get_inflation_series(
            indicator_code=inflation_indicator,
            end_date=as_of_date,
            use_pit=False,
            full=True,
        )

        growth_points = len(growth_full)
        inflation_points = len(inflation_full)

        if growth_points < self.MIN_MACRO_POINTS:
            warnings.append(f"增长指标样本不足（{growth_points} 条）")
        if inflation_points < self.MIN_MACRO_POINTS:
            warnings.append(f"通胀指标样本不足（{inflation_points} 条）")

        if growth_full:
            growth_staleness = self._get_staleness_days(growth_full[-1], as_of_date)
            growth_threshold = self.INDICATOR_STALENESS_DAYS.get(
                growth_indicator,
                self.MAX_MACRO_STALENESS_DAYS,
            )
            if growth_staleness > growth_threshold:
                warnings.append(f"PMI 数据陈旧（距今 {growth_staleness} 天）")
        else:
            warnings.append("PMI 无可用数据")

        if inflation_full:
            inflation_staleness = self._get_staleness_days(inflation_full[-1], as_of_date)
            inflation_threshold = self.INDICATOR_STALENESS_DAYS.get(
                inflation_indicator,
                self.MAX_MACRO_STALENESS_DAYS,
            )
            if inflation_staleness > inflation_threshold:
                warnings.append(f"CPI 数据陈旧（距今 {inflation_staleness} 天）")
        else:
            warnings.append("CPI 无可用数据")

        return {
            "is_healthy": not warnings,
            "warnings": warnings,
        }

    @staticmethod
    def _get_staleness_days(indicator: _MacroObservation, as_of_date: date) -> int:
        """优先用 published_at 计算时效，缺失时回退 reporting_period。"""
        anchor_date = indicator.published_at or indicator.reporting_period
        return (as_of_date - anchor_date).days

    def _format_positions(self, positions: list[Position]) -> list[dict[str, Any]]:
        """格式化持仓数据为字典"""
        return [
            {
                "id": p.id,
                "asset_code": p.asset_code,
                "asset_class": p.asset_class.value,
                "asset_class_display": self._get_asset_class_display(p.asset_class.value),
                "region": p.region.value,
                "region_display": self._get_region_display(p.region.value),
                "shares": p.shares,
                "avg_cost": float(p.avg_cost),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pnl": float(p.unrealized_pnl),
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
                "opened_at": p.opened_at.strftime("%Y-%m-%d"),
            }
            for p in positions
        ]

    def _get_simulated_positions(self, user_id: int) -> list[dict[str, Any]]:
        """Load holdings from the active simulated-account system."""
        sim_positions = self.overview_repo.get_simulated_positions(user_id)
        if not sim_positions:
            return []

        return [
            {
                "id": pos["id"],
                "asset_code": pos["asset_code"],
                "asset_name": pos["asset_name"],
                "asset_class": pos["asset_class"],
                "asset_class_display": self._get_asset_class_display(pos["asset_class"]),
                "region": "CN",
                "region_display": self._get_region_display("CN"),
                "shares": pos["shares"],
                "avg_cost": pos["avg_cost"],
                "current_price": pos["current_price"],
                "market_value": pos["market_value"],
                "unrealized_pnl": pos["unrealized_pnl"],
                "unrealized_pnl_pct": pos["unrealized_pnl_pct"],
                "opened_at": pos["opened_at"],
            }
            for pos in sim_positions
        ]

    def _get_asset_class_display(self, value: str) -> str:
        """获取资产大类显示名称"""
        display_map = {
            "equity": "股票",
            "fixed_income": "债券",
            "commodity": "商品",
            "currency": "外汇",
            "cash": "现金",
            "fund": "基金",
            "derivative": "衍生品",
            "other": "其他",
        }
        return display_map.get(value, value)

    def _get_region_display(self, value: str) -> str:
        """获取地区显示名称"""
        display_map = {
            "CN": "中国",
            "US": "美国",
            "EU": "欧洲",
            "JP": "日本",
            "EM": "新兴市场",
            "GLOBAL": "全球",
            "OTHER": "其他",
        }
        return display_map.get(value, value)

    def _get_user_signals(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        """获取用户活跃信号"""
        signals = self.signal_repo.get_user_signals(
            user_id=user_id,
            status="approved",
            limit=limit,
        )
        signal_list = list(signals)

        # 批量解析资产名称
        from apps.asset_analysis.application.asset_name_service import resolve_asset_names

        asset_codes = [s.asset_code for s in signal_list if s.asset_code]
        asset_name_map = resolve_asset_names(asset_codes)

        return [
            {
                "id": s.id,
                "asset_code": s.asset_code,
                "asset_name": asset_name_map.get(s.asset_code, s.asset_code),
                "direction": s.direction,
                "status": s.status.value,
                "logic_desc": (
                    s.logic_desc[:100] + "..." if len(s.logic_desc) > 100 else s.logic_desc
                ),
                "created_at": s.created_at.strftime("%Y-%m-%d") if s.created_at else "",
            }
            for s in signal_list
        ]

    def _calculate_signal_stats(self, user_id: int) -> dict[str, int]:
        """计算信号统计"""
        all_signals = self.signal_repo.get_user_signals(user_id)
        return {
            "total": len(all_signals),
            "approved": len([s for s in all_signals if s.status is SignalStatus.APPROVED]),
            "pending": len([s for s in all_signals if s.status is SignalStatus.PENDING]),
            "rejected": len([s for s in all_signals if s.status is SignalStatus.REJECTED]),
        }

    def _format_asset_allocation(self, positions: list[Position]) -> list[dict[str, Any]]:
        """格式化资产配置"""
        from apps.account.domain.services import PositionService

        allocations = PositionService.calculate_asset_allocation(positions, "asset_class")
        return [
            {
                "dimension": "asset_class",
                "dimension_value": a.dimension_value,
                "dimension_display": self._get_asset_class_display(a.dimension_value),
                "count": a.count,
                "market_value": float(a.market_value),
                "percentage": round(a.percentage, 1),
            }
            for a in allocations
        ]

    def _format_simulated_asset_allocation(
        self, positions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Format allocation data from simulated positions."""
        total_market_value = sum(float(item.get("market_value") or 0.0) for item in positions)
        if total_market_value <= 0:
            return []

        grouped: dict[str, dict[str, float]] = {}
        for item in positions:
            key = str(item.get("asset_class") or "other")
            bucket = grouped.setdefault(key, {"count": 0, "market_value": 0.0})
            bucket["count"] += 1
            bucket["market_value"] += float(item.get("market_value") or 0.0)

        return [
            {
                "dimension": "asset_class",
                "dimension_value": key,
                "dimension_display": self._get_asset_class_display(key),
                "count": bucket["count"],
                "market_value": bucket["market_value"],
                "percentage": round(bucket["market_value"] / total_market_value * 100, 1),
            }
            for key, bucket in sorted(
                grouped.items(), key=lambda item: item[1]["market_value"], reverse=True
            )
        ]

    def _generate_ai_insights(
        self,
        current_regime: str,
        snapshot: PortfolioSnapshot,
        match_analysis: RegimeMatchAnalysis,
        active_signals: list[dict[str, Any]],
        policy_level: str | None = None,
    ) -> list[str]:
        """调用 AI 生成投资建议"""
        from django.conf import settings

        insights = []

        if not getattr(settings, "DASHBOARD_SYNC_AI_INSIGHTS_ENABLED", False):
            return self._enhanced_fallback_insights(
                current_regime, snapshot, match_analysis, active_signals, policy_level
            )

        # 1. 准备 AI 请求的上下文信息
        context = {
            "current_regime": current_regime,
            "total_assets": float(snapshot.total_value),
            "total_return_pct": snapshot.total_return_pct,
            "invested_ratio": snapshot.get_invested_ratio(),
            "cash_ratio": 1 - snapshot.get_invested_ratio(),
            "regime_match_score": match_analysis.total_match_score,
            "position_count": len(snapshot.positions),
            "active_signal_count": len(active_signals),
            "policy_level": policy_level or "P0",
        }

        # 如果有敌对资产，添加到上下文
        if match_analysis.hostile_assets:
            context["hostile_assets"] = match_analysis.hostile_assets[:5]

        # 如果有活跃信号，添加信号信息
        if active_signals:
            context["recent_signals"] = [
                {"asset": s["asset_code"], "direction": s["direction"]} for s in active_signals[:3]
            ]

        # 2. 构建 AI 提示词
        prompt = f"""作为 AgomTradePro 投资助手，基于以下当前投资组合状态，给出 3-5 条简洁的投资建议（每条不超过30字）：

【宏观环境】
- 当前 Regime: {current_regime}
- 政策档位: {policy_level or "P0"}
- Regime 匹配度: {match_analysis.total_match_score:.0f} 分

【资产组合】
- 总资产: ¥{snapshot.total_value:,.0f}
- 收益率: {snapshot.total_return_pct:+.2f}%
- 仓位比例: {snapshot.get_invested_ratio() * 100:.0f}% 股票 / {(1 - snapshot.get_invested_ratio()) * 100:.0f}% 现金
- 持仓数量: {len(snapshot.positions)} 个
- 活跃信号: {len(active_signals)} 个

{f"【不匹配资产】{', '.join(match_analysis.hostile_assets[:3])}" if match_analysis.hostile_assets else ""}

请给出 3-5 条具体、可操作的投资建议，每条建议单独一行，不要太长。"""

        # 3. 调用 AI API
        try:
            provider = self.overview_repo.get_primary_system_ai_provider_payload()

            if not provider:
                # 如果没有配置 AI，使用数据库规则作为后备
                return self._enhanced_fallback_insights(
                    current_regime, snapshot, match_analysis, active_signals, policy_level
                )

            insights = get_dashboard_ai_insight_client().generate_insights(
                provider=provider,
                prompt=prompt,
            )
            if insights:
                return insights

        except Exception as e:
            # AI 调用失败，使用增强后备方案
            logger.warning(f"AI 调用失败: {e}，使用增强数据库规则")

        # 后备方案：使用增强数据库规则
        return self._enhanced_fallback_insights(
            current_regime, snapshot, match_analysis, active_signals, policy_level
        )

    def _enhanced_fallback_insights(
        self,
        current_regime: str,
        snapshot: PortfolioSnapshot,
        match_analysis: RegimeMatchAnalysis,
        active_signals: list[dict[str, Any]],
        policy_level: str | None = None,
    ) -> list[str]:
        """
        从数据库规则生成投资建议（AI 失败时的增强后备方案）

        易用性改进 - AI助手降级增强：
        - 支持Regime+Policy组合规则
        - 支持匹配度+仓位组合规则
        - 支持多层规则优先级
        - 永不空白，至少返回静态建议
        """
        insights: list[str] = []
        invested_ratio = snapshot.get_invested_ratio()
        match_score = match_analysis.total_match_score

        # Policy档位转换为数字（用于比较）
        policy_level_num = self._policy_to_numeric(policy_level or "P0")

        # 获取所有启用的全局规则
        all_rules = self.overview_repo.list_global_investment_rule_payloads()

        # ==================== Level 1: 组合规则（最高优先级） ====================

        # 1. Regime + Policy 组合规则
        combo_rules = self._select_rule_payloads(all_rules, "regime_policy_combo")
        for rule in combo_rules:
            conditions = rule.get("conditions") or {}
            if conditions.get("regime") == current_regime:
                min_policy = conditions.get("min_policy_level", 0)
                if policy_level_num >= min_policy:
                    advice = str(rule.get("advice_template") or "").format(
                        regime=current_regime,
                        policy_level=policy_level or "P0",
                        match_score=f"{match_score:.0f}",
                        invested_ratio=f"{invested_ratio * 100:.0f}%",
                    )
                    insights.append(advice)
                    break  # 只取第一个匹配的

        # 2. 匹配度 + 仓位 组合规则
        if not insights:  # 只在前面没有匹配时检查
            match_pos_rules = self._select_rule_payloads(all_rules, "match_position_combo")
            for rule in match_pos_rules:
                conditions = rule.get("conditions") or {}
                max_match = conditions.get("max_match_score", 100)
                min_invested = conditions.get("min_invested_ratio", 0)
                max_invested = conditions.get("max_invested_ratio", 1)

                if match_score <= max_match and min_invested <= invested_ratio <= max_invested:
                    advice = str(rule.get("advice_template") or "").format(
                        match_score=f"{match_score:.0f}",
                        invested_ratio=f"{invested_ratio * 100:.0f}%",
                    )
                    insights.append(advice)
                    break

        # 3. Regime + 仓位 组合规则
        if not insights:
            regime_pos_rules = self._select_rule_payloads(all_rules, "regime_position_combo")
            for rule in regime_pos_rules:
                conditions = rule.get("conditions") or {}
                if conditions.get("regime") == current_regime:
                    min_invested = conditions.get("min_invested_ratio", 0)
                    max_invested = conditions.get("max_invested_ratio", 1)
                    if min_invested <= invested_ratio <= max_invested:
                        advice = str(rule.get("advice_template") or "").format(
                            regime=current_regime,
                            invested_ratio=f"{invested_ratio * 100:.0f}%",
                        )
                        insights.append(advice)
                        break

        # ==================== Level 2: 单维度规则 ====================

        # 4. Regime环境建议
        if len(insights) < 3:  # 限制建议数量
            regime_rules = self._select_rule_payloads(all_rules, "regime_advice")
            for rule in regime_rules:
                conditions = rule.get("conditions") or {}
                if conditions.get("regime") == current_regime:
                    advice = str(rule.get("advice_template") or "").format(
                        regime=current_regime,
                        growth_direction="↑" if current_regime in ["Recovery", "Overheat"] else "↓",
                        inflation_direction=(
                            "↑" if current_regime in ["Overheat", "Stagflation"] else "↓"
                        ),
                    )
                    insights.append(advice)
                    break

        # 5. Policy档位建议
        if len(insights) < 3:
            policy_rules = self._select_rule_payloads(all_rules, "policy_advice")
            for rule in policy_rules:
                conditions = rule.get("conditions") or {}
                min_policy = conditions.get("min_policy_level", 0)
                max_policy = conditions.get("max_policy_level", 3)
                if min_policy <= policy_level_num <= max_policy:
                    advice = str(rule.get("advice_template") or "").format(
                        policy_level=policy_level or "P0",
                    )
                    insights.append(advice)
                    break

        # 6. 仓位建议
        if len(insights) < 3:
            position_rules = self._select_rule_payloads(all_rules, "position_advice")
            for rule in position_rules:
                conditions = rule.get("conditions") or {}
                min_invested = conditions.get("min_invested_ratio", 0)
                max_invested = conditions.get("max_invested_ratio", 1)
                if min_invested <= invested_ratio <= max_invested:
                    advice = str(rule.get("advice_template") or "").format(
                        invested_ratio=f"{invested_ratio * 100:.0f}%",
                        cash_ratio=f"{(1 - invested_ratio) * 100:.0f}%",
                    )
                    insights.append(advice)
                    break

        # 7. 匹配度建议
        if len(insights) < 3:
            match_rules = self._select_rule_payloads(all_rules, "match_advice")
            for rule in match_rules:
                conditions = rule.get("conditions") or {}
                min_match = conditions.get("min_match_score", 0)
                max_match = conditions.get("max_match_score", 100)
                if min_match <= match_score <= max_match:
                    advice = str(rule.get("advice_template") or "").format(
                        match_score=f"{match_score:.0f}",
                    )
                    insights.append(advice)
                    break

            # 如果有敌对资产，添加额外提示
            if match_analysis.hostile_assets and match_score < 50:
                hostile_codes = [a.split()[0] for a in match_analysis.hostile_assets[:3]]
                insights.append(f"建议关注: {', '.join(hostile_codes)} 与当前环境不匹配")

        # 8. 信号建议
        if len(insights) < 3:
            signal_rules = self._select_rule_payloads(all_rules, "signal_advice")
            for rule in signal_rules:
                conditions = rule.get("conditions") or {}
                min_count = conditions.get("min_signal_count", 0)
                has_active = conditions.get("has_active_signals", True)

                match = False
                if has_active and len(active_signals) >= min_count:
                    match = True
                elif not has_active and len(active_signals) == 0:
                    match = True

                if match:
                    advice = str(rule.get("advice_template") or "").format(
                        signal_count=len(active_signals),
                    )
                    insights.append(advice)
                    break

        # 9. 风险提示
        if len(insights) < 3:
            risk_rules = self._select_rule_payloads(all_rules, "risk_alert")
            for rule in risk_rules:
                conditions = rule.get("conditions") or {}
                min_return = conditions.get("min_return_pct", -100)
                max_return = conditions.get("max_return_pct", 100)
                if min_return <= snapshot.total_return_pct <= max_return:
                    advice = str(rule.get("advice_template") or "").format(
                        return_pct=f"{snapshot.total_return_pct:.0f}",
                    )
                    insights.append(advice)
                    break

        # ==================== Level 3: 静态保底规则（永不空白） ====================

        if len(insights) < 2:
            static_rules = self._select_rule_payloads(all_rules, "static_advice")
            for rule in static_rules:
                insights.append(str(rule.get("advice_template") or ""))
                if len(insights) >= 2:
                    break

        # 确保至少有一条建议
        if not insights:
            insights.append("定期查看持仓与Regime的匹配度，关注市场变化")

        return insights[:5]  # 最多返回5条建议

    @staticmethod
    def _select_rule_payloads(
        rules: list[dict[str, Any]],
        rule_type: str,
    ) -> list[dict[str, Any]]:
        """Filter investment rule payloads by type."""
        return [rule for rule in rules if rule.get("rule_type") == rule_type]

    def _policy_to_numeric(self, policy_level: str) -> int:
        """将Policy档位转换为数字"""
        policy_map = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        return policy_map.get(policy_level, 0)

    def _fallback_insights(
        self,
        current_regime: str,
        snapshot: PortfolioSnapshot,
        match_analysis: RegimeMatchAnalysis,
        active_signals: list[dict[str, Any]],
    ) -> list[str]:
        """从数据库规则生成投资建议（AI 失败时的后备方案）- 保留兼容性"""
        return self._enhanced_fallback_insights(
            current_regime, snapshot, match_analysis, active_signals, None
        )

    def _get_latest_macro_values(self) -> tuple[float | None, float | None]:
        """获取最新的 PMI 和 CPI 值"""
        # 获取最新 PMI
        try:
            pmi_series = self.overview_repo.get_growth_series(
                indicator_code="PMI", end_date=date.today(), use_pit=False
            )
            pmi_value = float(pmi_series[-1]) if pmi_series else None
        except Exception:
            pmi_value = None

        # 获取最新 CPI
        try:
            cpi_series = self.overview_repo.get_inflation_series(
                indicator_code="CPI", end_date=date.today(), use_pit=False
            )
            cpi_value = float(cpi_series[-1]) if cpi_series else None
        except Exception:
            cpi_value = None

        return pmi_value, cpi_value

    def _get_policy_environment(
        self, user_id: int
    ) -> tuple[str | None, date | None, int, list[dict[str, Any]]]:
        """获取政策环境信息"""
        return self.overview_repo.get_policy_environment(user_id)

    @staticmethod
    def _normalize_policy_level_for_strategy(policy_level: str | None) -> str | None:
        """Convert dashboard policy states into strategy-supported levels."""
        if policy_level in {"P0", "P1", "P2", "P3"}:
            return policy_level
        return None

    def _generate_allocation_advice(
        self,
        current_regime: str,
        policy_level: str | None,
        profile: AccountProfile,
        total_assets: float,
        positions: list[Position],
    ) -> dict[str, Any] | None:
        """生成资产配置建议"""
        try:
            from apps.strategy.application.allocation_service import AllocationService

            # 获取用户风险偏好
            risk_profile = _risk_tolerance_value(profile.risk_tolerance)
            prepared_positions = self._prepare_allocation_positions(
                total_assets,
                positions,
            )
            if (
                current_regime not in _ALLOCATION_REGIMES
                or risk_profile not in _ALLOCATION_RISK_PROFILES
                or prepared_positions is None
            ):
                return None
            normalized_total_assets, allocation_positions = prepared_positions
            effective_policy_level = self._normalize_policy_level_for_strategy(policy_level)

            # 调用AllocationService计算建议
            advice = AllocationService.calculate_allocation_advice(
                current_regime=current_regime,
                risk_profile=risk_profile,
                policy_level=effective_policy_level,
                total_assets=normalized_total_assets,
                current_positions=allocation_positions,
            )

            # 转换为字典格式
            return {
                "current_allocation": advice.current_allocation,
                "target_allocation": advice.target_allocation,
                "allocation_diff": advice.allocation_diff,
                "trade_actions": [
                    {
                        "asset_code": a.asset_code,
                        "asset_name": a.asset_name,
                        "action": a.action,
                        "amount": round(a.amount, 2),
                        "reason": a.reason,
                        "asset_class": a.asset_class,
                        "asset_class_display": self._get_asset_class_display(a.asset_class),
                        "priority": a.priority,
                    }
                    for a in advice.trade_actions
                ],
                "summary": advice.summary,
                "expected_return": advice.expected_return,
                "expected_volatility": advice.expected_volatility,
                "sharpe_ratio": advice.sharpe_ratio,
                "regime": advice.regime,
                "risk_profile_display": _display_risk_tolerance(profile.risk_tolerance),
            }
        except Exception as exc:
            logger.warning(
                "生成资产配置建议失败 exception_type=%s",
                type(exc).__name__,
            )
            return None

    @staticmethod
    def _prepare_allocation_positions(
        total_assets: object,
        positions: list[Position],
    ) -> tuple[float, list[PositionLikeProtocol]] | None:
        """Validate portfolio totals and adapt Account positions for Strategy."""

        if (
            isinstance(total_assets, bool)
            or not isinstance(total_assets, (int, float))
            or not math.isfinite(float(total_assets))
            or total_assets < 0
        ):
            return None
        normalized_total = float(total_assets)
        total_decimal = Decimal(str(normalized_total))
        invested_value = Decimal("0")
        adapted: list[PositionLikeProtocol] = []

        for position in positions:
            asset_code = position.asset_code.strip().upper()
            asset_class = position.asset_class.value
            market_value = position.market_value
            if (
                not _ALLOCATION_ASSET_CODE_PATTERN.fullmatch(asset_code)
                or asset_class not in _ALLOCATION_ASSET_CLASSES
                or not isinstance(market_value, Decimal)
                or not market_value.is_finite()
                or market_value < 0
            ):
                return None
            invested_value += market_value
            adapted.append(
                _AllocationPosition(
                    asset_code=asset_code,
                    market_value=market_value,
                    asset_class=_AllocationAssetClassValue(asset_class),
                )
            )

        if invested_value > total_decimal + Decimal("0.01"):
            return None
        return normalized_total, adapted

    def _generate_allocation_chart_data(
        self, asset_allocation: list[dict[str, Any]]
    ) -> dict[str, float]:
        """
        生成资产配置图表数据

        Args:
            asset_allocation: 资产配置列表

        Returns:
            Dict[str, float]: {"股票": 100000, "债券": 50000, ...}
        """
        allocation_chart_data: dict[str, float] = {}
        for alloc in asset_allocation:
            dimension_display = str(
                alloc.get("dimension_display", alloc.get("dimension_value", "Unknown"))
            )
            market_value = float(alloc.get("market_value") or 0.0)
            allocation_chart_data[dimension_display] = market_value
        return allocation_chart_data

    def _generate_performance_chart_data(
        self,
        user_id: int | None = None,
        account_id: int | None = None,
        days: int = 30,
        portfolio_id: int | None = None,
        current_total_return_pct: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        生成收益趋势图表数据。

        Args:
            user_id: 用户ID
            account_id: 可选账户ID，为 None 时汇总所有账户
            days: 获取最近N天的数据
            portfolio_id: 向后兼容参数，使用组合快照生成趋势图
            current_total_return_pct: 向后兼容参数，当前未使用

        Returns:
            List[Dict]: [{"date": "2026-01-01", "return_pct": 5.2}, ...]
        """
        if portfolio_id is not None:
            return self.overview_repo.get_portfolio_snapshot_performance_data(portfolio_id)

        if user_id is None:
            return []

        return self.overview_repo.get_simulated_performance_data(
            user_id=user_id,
            account_id=account_id,
            days=days,
        )
