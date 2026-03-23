"""
Domain Layer for Filter App.

Pure business logic with zero external dependencies.
"""

from .entities import (
    FilterResult,
    FilterSeries,
    FilterType,
    HPFilterParams,
    KalmanFilterParams,
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
