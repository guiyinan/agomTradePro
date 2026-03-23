"""
Audit Domain Layer

Contains core business entities and services for attribution analysis.
Following four-layer architecture, this layer uses ONLY Python standard library.
"""

from .entities import (
    AttributionConfig,
    AttributionResult,
    LossSource,
    PeriodPerformance,
    RegimePeriod,
    RegimeTransition,
)
from .services import AttributionAnalyzer, analyze_attribution

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
