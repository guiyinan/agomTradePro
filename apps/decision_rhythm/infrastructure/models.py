"""Compatibility exports for Decision Rhythm ORM models.

Model implementations live in focused owner modules. This module remains the
stable import and patch surface used by repositories, tests, and integrations.
"""

from django.apps import apps as django_apps

from .input_snapshot_models import DecisionInputSnapshotModel
from .model_param_models import (
    DecisionModelParamAuditLogModel,
    DecisionModelParamConfigModel,
)
from .recommendation_models import (
    DecisionExecutionLinkModel,
    DecisionFeatureSnapshotModel,
    UnifiedRecommendationModel,
)
from .rhythm_models import (
    CooldownPeriodModel,
    DecisionQuotaModel,
    DecisionRequestModel,
    DecisionResponseModel,
)
from .valuation_models import (
    ExecutionApprovalRequestModel,
    InvestmentRecommendationModel,
    ValuationSnapshotModel,
)

__all__ = [
    "CooldownPeriodModel",
    "DecisionExecutionLinkModel",
    "DecisionInputSnapshotModel",
    "DecisionFeatureSnapshotModel",
    "DecisionModelParamAuditLogModel",
    "DecisionModelParamConfigModel",
    "DecisionQuotaModel",
    "DecisionRequestModel",
    "DecisionResponseModel",
    "ExecutionApprovalRequestModel",
    "InvestmentRecommendationModel",
    "UnifiedRecommendationModel",
    "ValuationSnapshotModel",
]


def __getattr__(name: str):
    """Resolve the portfolio-owned model for legacy repository imports."""

    if name == "PortfolioTransitionPlanModel":
        return django_apps.get_model("portfolio", "PortfolioTransitionPlanModel")
    raise AttributeError(name)
