"""
Expose strategy ORM models at the Django app root for model discovery.
"""

from django.apps import apps as django_apps

from apps.strategy.infrastructure.models import (  # noqa: F401
    AIStrategyConfigModel,
    PortfolioStrategyAssignmentModel,
    PositionManagementRuleModel,
    RuleConditionModel,
    ScriptConfigModel,
    StrategyExecutionLogModel,
    StrategyModel,
    StrategyParamVersionModel,
)


def __getattr__(name: str):
    """Keep the historical order-intent import surface during the owner migration."""

    if name == "OrderIntentModel":
        return django_apps.get_model("portfolio", "OrderIntentModel")
    raise AttributeError(name)
