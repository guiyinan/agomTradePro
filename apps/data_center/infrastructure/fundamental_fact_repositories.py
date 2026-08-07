"""Compatibility exports for canonical fundamental fact repositories."""

from apps.data_center.infrastructure.financial_fact_repository import FinancialFactRepository
from apps.data_center.infrastructure.fund_nav_repository import FundNavRepository
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository

__all__ = ["FinancialFactRepository", "FundNavRepository", "ValuationFactRepository"]
