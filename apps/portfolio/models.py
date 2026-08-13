"""Django model discovery for portfolio."""

from apps.portfolio.infrastructure.models import (
    CanonicalPortfolioSnapshotModel,
    GovernedOptimizationInputReceiptModel,
    GovernedOptimizationMonitoringAssessmentModel,
    GovernedOptimizationMonitoringAuditSnapshotModel,
    GovernedOptimizationMonitoringObservationModel,
    OrderIntentModel,
    PortfolioExecutionFeedbackModel,
    PortfolioPlanningPolicyActivationModel,
    PortfolioPlanningPolicyActivationSubjectModel,
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
    "PortfolioPlanningPolicyActivationModel",
    "PortfolioPlanningPolicyActivationSubjectModel",
    "PortfolioPlanningPolicyModel",
    "PortfolioPlanningPolicyDefinitionModel",
    "PortfolioR5RelativeValueOutcomeModel",
    "PortfolioR8MonitoringFeedbackReceiptModel",
    "PortfolioTransitionPlanModel",
    "TransitionPlanInactiveApprovalReceiptModel",
    "TransitionPlanInactiveApprovalSubjectModel",
]
