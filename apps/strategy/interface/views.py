"""Django REST Framework Views for Strategy System (compatibility export surface).

Interface层:
- 提供REST API接口，使用DRF ViewSet组织API
- 只做输入验证和输出格式化，禁止业务逻辑

视图实现已拆分到同目录关注点模块（``page_views``、``execution_views``、
``strategy_api_views``、``rule_api_views``、``assignment_api_views``、
``execution_log_api_views``）；本模块保留稳定的导入面与 legacy monkeypatch
面（``django_apps.get_model`` 解析出的 ORM Model 别名，例如
``PortfolioStrategyAssignmentModel``）。策略创建/编辑/绑定等高风险写路径仍在
owner 模块中通过 ``with transaction.atomic()`` 包裹的多步保存块完成。
"""

from django.apps import apps as django_apps

from apps.strategy.interface.assignment_api_views import (
    PortfolioStrategyAssignmentViewSet,
    bind_strategy,
    unbind_strategy,
)
from apps.strategy.interface.execution_log_api_views import StrategyExecutionLogViewSet
from apps.strategy.interface.execution_views import (
    execution_evaluate,
    strategy_execute,
    test_script,
    test_strategy,
)
from apps.strategy.interface.page_views import (
    strategy_create,
    strategy_detail,
    strategy_edit,
    strategy_list,
    strategy_toggle_status,
)
from apps.strategy.interface.rule_api_views import (
    PositionManagementRuleViewSet,
    RuleConditionViewSet,
)
from apps.strategy.interface.strategy_api_views import (
    AIStrategyConfigViewSet,
    ScriptConfigViewSet,
    StrategyViewSet,
)

# Legacy monkeypatch surface: ORM model aliases resolved exactly as before.
AIStrategyConfigModel = django_apps.get_model("strategy", "AIStrategyConfigModel")
PortfolioStrategyAssignmentModel = django_apps.get_model("strategy", "PortfolioStrategyAssignmentModel")
PositionManagementRuleModel = django_apps.get_model("strategy", "PositionManagementRuleModel")
RuleConditionModel = django_apps.get_model("strategy", "RuleConditionModel")
ScriptConfigModel = django_apps.get_model("strategy", "ScriptConfigModel")
StrategyExecutionLogModel = django_apps.get_model("strategy", "StrategyExecutionLogModel")
StrategyModel = django_apps.get_model("strategy", "StrategyModel")


__all__ = [
    "AIStrategyConfigModel",
    "AIStrategyConfigViewSet",
    "PortfolioStrategyAssignmentModel",
    "PortfolioStrategyAssignmentViewSet",
    "PositionManagementRuleModel",
    "PositionManagementRuleViewSet",
    "RuleConditionModel",
    "RuleConditionViewSet",
    "ScriptConfigModel",
    "ScriptConfigViewSet",
    "StrategyExecutionLogModel",
    "StrategyExecutionLogViewSet",
    "StrategyModel",
    "StrategyViewSet",
    "bind_strategy",
    "execution_evaluate",
    "strategy_create",
    "strategy_detail",
    "strategy_edit",
    "strategy_execute",
    "strategy_list",
    "strategy_toggle_status",
    "test_script",
    "test_strategy",
    "unbind_strategy",
]
