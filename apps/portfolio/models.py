"""Django model discovery for portfolio."""

from apps.portfolio.infrastructure.models import (
    CanonicalPortfolioSnapshotModel,
    GovernedOptimizationInputReceiptModel,
    GovernedOptimizationMonitoringAssessmentModel,
    GovernedOptimizationMonitoringAuditSnapshotModel,
    GovernedOptimizationMonitoringObservationModel,
    OrderIntentModel,
    PortfolioExecutionFeedbackModel,
    PortfolioPlanningPolicyDefinitionModel,
    PortfolioPlanningPolicyModel,
    PortfolioR5RelativeValueOutcomeModel,
    PortfolioR8MonitoringFeedbackReceiptModel,
    PortfolioTransitionPlanModel,
    TransitionPlanInactiveApprovalReceiptModel,
    TransitionPlanInactiveApprovalSubjectModel,
)

__all__ = [
    "CanonicalPortfolioSnapshotModel",
    "GovernedOptimizationInputReceiptModel",
    "GovernedOptimizationMonitoringObservationModel",
    "GovernedOptimizationMonitoringAssessmentModel",
    "GovernedOptimizationMonitoringAuditSnapshotModel",
    "OrderIntentModel",
    "PortfolioExecutionFeedbackModel",
    "PortfolioPlanningPolicyModel",
    "PortfolioPlanningPolicyDefinitionModel",
    "PortfolioR5RelativeValueOutcomeModel",
    "PortfolioR8MonitoringFeedbackReceiptModel",
    "PortfolioTransitionPlanModel",
    "TransitionPlanInactiveApprovalReceiptModel",
    "TransitionPlanInactiveApprovalSubjectModel",
]
