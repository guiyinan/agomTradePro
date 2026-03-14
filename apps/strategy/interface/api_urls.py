"""Strategy API URL configuration."""

from django.urls import include, path
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView

from apps.strategy.interface.views import (
    AIStrategyConfigViewSet,
    PortfolioStrategyAssignmentViewSet,
    PositionManagementRuleViewSet,
    RuleConditionViewSet,
    ScriptConfigViewSet,
    StrategyExecutionLogViewSet,
    StrategyViewSet,
    bind_strategy,
    execution_evaluate,
    test_script,
    unbind_strategy,
)

app_name = "strategy_api"

router = DefaultRouter()
router.register(r"strategies", StrategyViewSet, basename="strategy")
router.register(r"position-rules", PositionManagementRuleViewSet, basename="positionrule")
router.register(r"rules", RuleConditionViewSet, basename="rulecondition")
router.register(r"script-configs", ScriptConfigViewSet, basename="scriptconfig")
router.register(r"ai-configs", AIStrategyConfigViewSet, basename="aistrategyconfig")
router.register(r"assignments", PortfolioStrategyAssignmentViewSet, basename="portfoliostrategyassignment")
router.register(r"execution-logs", StrategyExecutionLogViewSet, basename="strategyexecutionlog")


class StrategyApiRootView(APIView):
    def get(self, request):
        return Response(
            {
                "endpoints": {
                    "strategies": "/api/strategy/strategies/",
                    "position_rules": "/api/strategy/position-rules/",
                    "rules": "/api/strategy/rules/",
                    "script_configs": "/api/strategy/script-configs/",
                    "ai_configs": "/api/strategy/ai-configs/",
                    "assignments": "/api/strategy/assignments/",
                    "execution_logs": "/api/strategy/execution-logs/",
                    "bind_strategy": "/api/strategy/bind-strategy/",
                    "unbind_strategy": "/api/strategy/unbind-strategy/",
                    "test_script": "/api/strategy/test-script/",
                    "execution_evaluate": "/api/strategy/execution/evaluate/",
                }
            }
        )


urlpatterns = [
    path("", StrategyApiRootView.as_view(), name="api-root"),
    path("", include(router.urls)),
    path("test-script/", test_script, name="test-script"),
    path("execution/evaluate/", execution_evaluate, name="execution-evaluate"),
    path("bind-strategy/", bind_strategy, name="bind-strategy"),
    path("unbind-strategy/", unbind_strategy, name="unbind-strategy"),
]
