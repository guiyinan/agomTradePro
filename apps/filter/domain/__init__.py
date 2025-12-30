"""
Domain Layer for Filter App.

Pure business logic with zero external dependencies.
"""

from .entities import (
    FilterType,
    HPFilterParams,
    KalmanFilterParams,
    FilterResult,
    FilterSeries,
    KalmanFilterState,
)
from .services import (
    HPFilterService,
    KalmanFilterService,
    compare_filters,
    detect_turning_points,
)

__all__ = [
    # Entities
    "FilterType",
    "HPFilterParams",
    "KalmanFilterParams",
    "FilterResult",
    "FilterSeries",
    "KalmanFilterState",
    # Services
    "HPFilterService",
    "KalmanFilterService",
    "compare_filters",
    "detect_turning_points",
]
