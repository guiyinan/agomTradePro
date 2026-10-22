"""Django admin autodiscovery entry point for Equity registrations."""

from apps.equity.interface.admin import ScoringWeightConfigAdmin

__all__ = ["ScoringWeightConfigAdmin"]
