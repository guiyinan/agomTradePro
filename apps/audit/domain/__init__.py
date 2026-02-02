"""
Audit Domain Layer

Contains core business entities and services for attribution analysis.
Following four-layer architecture, this layer uses ONLY Python standard library.
"""

from .entities import (
    LossSource,
    RegimeTransition,
    RegimePeriod,
    PeriodPerformance,
    AttributionResult,
    AttributionConfig
)

from .services import (
    analyze_attribution,
    AttributionAnalyzer
)

__all__ = [
    # Entities
    "LossSource",
    "RegimeTransition",
    "RegimePeriod",
    "PeriodPerformance",
    "AttributionResult",
    "AttributionConfig",
    # Services
    "analyze_attribution",
    "AttributionAnalyzer",
]
