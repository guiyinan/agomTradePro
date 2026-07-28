"""
Audit Domain Layer - Repository Protocols

Repository interfaces for audit operations.
"""

from datetime import date
from typing import Protocol, TypedDict


class IndicatorThresholdRecord(TypedDict):
    """Typed persistence projection for an indicator threshold."""

    indicator_code: str
    indicator_name: str
    category: str
    level_low: float | None
    level_high: float | None
    base_weight: float
    min_weight: float
    max_weight: float
    decay_threshold: float
    decay_penalty: float
    improvement_threshold: float
    improvement_bonus: float
    action_thresholds: dict[str, float]
    validation_periods: list[dict[str, object]]
    description: str


class IndicatorPerformanceRecord(TypedDict):
    """Typed persistence projection for indicator performance."""

    id: int
    indicator_code: str
    validation_run_id: str | None
    evaluation_period_start: str
    evaluation_period_end: str
    f1_score: float | None
    precision: float | None
    recall: float | None
    stability_score: float | None
    recommended_action: str | None
    recommended_weight: float | None
    confidence_level: float | None
    decay_rate: float | None


class AttributionReportRecord(TypedDict):
    """JSON-facing projection of one validated attribution report."""

    id: int
    backtest_id: int
    period_start: str
    period_end: str
    attribution_method: str
    attribution_method_display: str
    regime_timing_pnl: float
    asset_selection_pnl: float
    interaction_pnl: float
    total_pnl: float
    regime_accuracy: float
    regime_predicted: str
    regime_actual: str | None
    created_at: str


class LossAnalysisRecord(TypedDict):
    """JSON-facing projection of one validated loss analysis."""

    id: int
    loss_source: str
    loss_source_display: str
    impact: float
    impact_percentage: float
    description: str
    improvement_suggestion: str


class ExperienceSummaryRecord(TypedDict):
    """JSON-facing projection of one governed experience summary."""

    id: int
    lesson: str
    recommendation: str
    priority: str
    is_applied: bool
    applied_at: str | None


class RegimeLogRecord(TypedDict):
    """Typed persistence projection for a Regime observation."""

    observed_at: date
    dominant_regime: str
    confidence: float
    growth_momentum_z: float
    inflation_momentum_z: float
    distribution: dict[str, float]


class AuditRepositoryProtocol(Protocol):
    """Repository protocol for audit data access"""

    def count_operation_logs(self) -> int:
        """Return the number of persisted operation logs."""
        ...

    def get_database_health(self) -> dict[str, str]:
        """Run a lightweight database probe and return connection metadata."""
        ...

    def get_indicator_performance(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        """Get indicator performance records within a date range"""
        ...

    def get_latest_indicator_performance(
        self,
        indicator_code: str,
    ) -> dict[str, object] | None:
        """Get the latest performance record for an indicator"""
        ...

    def get_active_threshold_configs(self) -> list[dict[str, object]]:
        """Get all active threshold configurations"""
        ...

    def get_validation_summary(
        self,
        validation_run_id: str,
    ) -> dict[str, object] | None:
        """Get validation summary by run ID"""
        ...

    def get_recent_validations(self, limit: int = 10) -> list[dict[str, object]]:
        """Get recent validation records"""
        ...


class MacroIndicatorRepositoryProtocol(Protocol):
    """Repository protocol for macro indicator data access"""

    def get_indicator_by_code(self, code: str) -> dict[str, object] | None:
        """Get indicator metadata by code"""
        ...


class RegimeLogRepositoryProtocol(Protocol):
    """Repository protocol for regime log data access"""

    def get_regime_logs_by_date_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        """Get regime logs within a date range"""
        ...
