"""Contracts and value normalization for dashboard aggregation."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol, TypedDict

from apps.signal.domain.entities import InvestmentSignal
from apps.strategy.domain.protocols import AssetClassValueProtocol


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
