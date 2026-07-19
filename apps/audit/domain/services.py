"""Compatibility exports for Audit domain services.

Service implementations live in focused owner modules (heuristic attribution,
Brinson attribution, indicator performance evaluation, and operation log
factory). This module remains the stable import and patch surface used by
applications, interfaces, and tests.

仅使用 Python 标准库。
"""

from .attribution_services import (
    AttributionAnalyzer,
    analyze_attribution,
)
from .attribution_services import (
    _build_period_attributions as _build_period_attributions,
)
from .attribution_services import (
    _build_regime_periods as _build_regime_periods,
)
from .attribution_services import (
    _calculate_period_performances as _calculate_period_performances,
)
from .attribution_services import (
    _calculate_total_transaction_cost as _calculate_total_transaction_cost,
)
from .attribution_services import (
    _generate_lessons as _generate_lessons,
)
from .attribution_services import (
    _heuristic_pnl_decomposition as _heuristic_pnl_decomposition,
)
from .attribution_services import (
    _identify_loss_source as _identify_loss_source,
)
from .brinson_services import (
    _calculate_average_return as _calculate_average_return,
)
from .brinson_services import (
    _calculate_average_weight as _calculate_average_weight,
)
from .brinson_services import (
    _calculate_weighted_return as _calculate_weighted_return,
)
from .brinson_services import (
    _generate_brinson_period_breakdown as _generate_brinson_period_breakdown,
)
from .brinson_services import (
    calculate_brinson_attribution,
)
from .entities import (
    AttributionConfig,
    AttributionResult,
    BrinsonAttributionResult,
    IndicatorPerformanceReport,
    IndicatorThresholdConfig,
    LossSource,
    OperationLog,
    PeriodPerformance,
    RecommendedAction,
    RegimePeriod,
    RegimeSnapshot,
    SignalEvent,
)
from .operation_log_services import OperationLogFactory
from .performance_services import (
    IndicatorPerformanceAnalyzer,
    ThresholdValidator,
)

__all__ = [
    "AttributionAnalyzer",
    "AttributionConfig",
    "AttributionResult",
    "BrinsonAttributionResult",
    "IndicatorPerformanceAnalyzer",
    "IndicatorPerformanceReport",
    "IndicatorThresholdConfig",
    "LossSource",
    "OperationLog",
    "OperationLogFactory",
    "PeriodPerformance",
    "RecommendedAction",
    "RegimePeriod",
    "RegimeSnapshot",
    "SignalEvent",
    "ThresholdValidator",
    "analyze_attribution",
    "calculate_brinson_attribution",
]
