"""Django model discovery exports for fixed-income research."""

from apps.fixed_income.infrastructure.models import FixedIncomeResearchResultModel
from apps.fixed_income.infrastructure.relative_value_models import (
    FixedIncomeR5InputReceiptModel,
    FixedIncomeR5ResultModel,
)

__all__ = [
    "FixedIncomeR5InputReceiptModel",
    "FixedIncomeR5ResultModel",
    "FixedIncomeResearchResultModel",
]
