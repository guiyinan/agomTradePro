from pathlib import Path

import pytest
from django.contrib.auth.models import User

from apps.terminal.application.tui_metadata import (
    TuiMetadataValidationError,
    compact_tui_metadata_payload,
    validate_tui_metadata,
)
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.models import TuiMetadataRegistryORM
from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository


def _metadata_payload(actions=None):
    return {
        "version": "tui-workbench.v2",
        "registry_key": "default",
        "default_screen": "command-center.overview",
        "interaction_model": "published-metadata-to-pc-tools",
        "groups": [{"key": "workflow", "label": "Workflow"}],
        "modules": [
            {
                "key": "command-center",
                "label": "Command Center",
                "group": "workflow",
                "summary": "Command tools.",
                "status": "online",
            }
        ],
        "screens": [
            {
                "key": "command-center.overview",
                "label": "Command Overview",
                "module_key": "command-center",
                "group": "workflow",
                "summary": "Overview.",
                "view_type": "status",
                "status": "online",
            }
        ],
        "actions": (
            actions
            if actions is not None
            else [
                {
                    "key": "sample.list",
                    "label": "Sample List",
                    "method": "GET",
                    "endpoint": "/api/sample/list/",
                    "intent": "sample",
                    "screen_key": "command-center.overview",
                    "module_key": "command-center",
                    "view_type": "datagrid",
                    "risk": "read",
                    "fields": [],
                    "description": "Sample.",
                    "source": "approved:test",
                    "raw_debug": True,
                }
            ]
        ),
    }


class FakeMetadataRepository:
    def __init__(self, payload=None):
        self.payload = validate_tui_metadata(payload or _metadata_payload())

    def load_published(self, registry_key="default"):
        return self.payload


@pytest.fixture
def tui_user(db):
    return User.objects.create_user(username="tui_user", password="test-password")


def test_tui_workbench_requires_login(client):
    response = client.get("/tui/")

    assert response.status_code == 302
    assert "/account/login/" in response["Location"]


def test_tui_workbench_page_is_standalone(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/tui/")

    assert response.status_code == 200
    html = response.content.decode()
    assert "TUI Workbench - AgomTradePro" in html
    assert "tui-workbench.css" in html
    assert "tui-workbench.js" in html
    assert "user-task-43" in html
    assert "data-module-tree" in html
    assert "data-workflow-strip" in html
    assert "data-current-location" in html
    assert "screen:boot" in html
    assert "用户: tui_user" in html
    assert "data-theme-status" in html
    assert "STYLE: B" in html
    assert "data-theme-indicator" in html
    assert "data-theme-indicator-code" in html
    assert "T:B" in html
    assert "data-toggle-rail" in html
    assert "data-toggle-inspector" in html
    assert "tabindex=\"-1\"" in html
    assert "home-layout" not in html
    assert "tui-theme.css" not in html


def test_tui_workbench_page_exposes_pc_tools_interaction_shell(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/tui/")

    assert response.status_code == 200
    html = response.content.decode()
    assert "data-menu-popover" in html
    assert "data-filter-bar" in html
    assert "data-tui-modal" in html
    assert "data-workbench-status" in html
    assert "<strong>F1</strong> 帮助" in html
    assert "<strong>F3</strong> 上屏" in html
    assert "<strong>F4</strong> 下屏" in html
    assert "<strong>F7</strong> 筛选" in html
    assert "<strong>F8</strong> 导出" in html
    assert "<strong>F6</strong> 下一项" in html
    assert "<strong>F9</strong> 任务" in html
    assert "<strong>F10</strong> 说明" in html
    assert "<strong>Alt+A</strong>" not in html
    assert "<strong>Alt+F</strong>" not in html
    assert "<strong>Alt+X</strong>" not in html
    assert "Ctrl+Enter" not in html
    assert "Alt+←/→" not in html
    assert "UI模式" not in html
    assert "DOS风格" not in html
    assert "REGIME:" not in html
    assert "POLICY:" not in html
    assert "自动刷新: <strong>ON" not in html


def test_tui_workbench_uses_system_cursor_and_collapsible_sidebars():
    css = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "css", "tui-workbench.css")
        .read_text(encoding="utf-8")
    )
    script = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "js", "tui-workbench.js")
        .read_text(encoding="utf-8")
    )

    assert ".tui-block-cursor" not in css
    assert "cursor: none" not in css
    assert "cursor: pointer" not in css
    assert "bindBlockCursor" not in script
    assert "function toggleRail" in script
    assert "function toggleInspector" in script
    assert "data-toggle-rail" in script
    assert "data-toggle-inspector" in script
    assert ".tui-app.is-rail-collapsed" in css
    assert ".tui-app.is-inspector-collapsed" in css


def test_tui_workbench_supports_runtime_theme_switching():
    script = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "js", "tui-workbench.js")
        .read_text(encoding="utf-8")
    )

    assert 'const THEME_SEQUENCE = ["A", "B", "C"]' in script
    assert "const THEME_TOKENS = {" in script
    assert "themeStorageKey" in script
    assert 'themeKey: "B"' in script
    assert "function applyTheme(themeKey" in script
    assert "document.documentElement" in script
    assert "root.style.setProperty" in script
    assert 'root.dataset.tuiTheme = resolvedThemeKey' in script
    assert "function cycleTheme()" in script
    assert "function showThemeStatus()" in script
    assert "window.localStorage?.setItem(themeStorageKey, resolvedThemeKey)" in script
    assert "const HOTKEY_COMMANDS = {" in script
    assert 'F10: "toggle-inspector"' in script
    assert "function keyboardCommandForEvent(event)" in script
    assert 'event.altKey && !event.ctrlKey && !event.shiftKey && lowerKey === "t"' in script
    assert 'event.ctrlKey && !event.altKey && !event.shiftKey && lowerKey === "t"' in script
    assert 'els.themeIndicatorCode.textContent = `T:${resolvedThemeKey}`' in script
    assert 'els.themeStatus.textContent = `STYLE: ${resolvedThemeKey}`' in script
    assert 'setStatus(`主题已切换: ${nextKey}`)' in script
    assert 'showModal("主题"' in script
    assert 'showModal("帮助"' in script
    assert "不刷新页面，不丢失当前状态" in script


def test_tui_workbench_javascript_keeps_api_endpoints_out_of_task_buttons():
    script = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "js", "tui-workbench.js")
        .read_text(encoding="utf-8")
    )

    assert "action.endpoint}</span>" not in script
    assert "${escapeHtml(action.method)} ${escapeHtml(action.endpoint)}" not in script
    assert "原始响应" in script
    assert "Debug response" not in script
    assert "Read-only" not in script
    assert 'read: "立即打开"' in script
    assert "直接执行" not in script
    assert 'ai: "AI 协助"' in script
    assert "读取视图" not in script
    assert "function resetCurrentScreenProgress" in script
    assert "function setCurrentLocation" in script
    assert "[data-current-location]" in script
    assert "screen:${screenKey} action:${action.key}" in script
    assert "function loadStoredProgress" in script
    assert "function persistProgress" in script
    assert "progressStorageKey" in script
    assert "sessionStorage" in script
    assert "function actionVerbLabel" in script
    assert "function actionRoleLabel" in script
    assert "function actionMetaLabel" in script
    assert "function actionMatchesFilter" in script
    assert "function focusActionFilter" in script
    assert "data-action-filter" in script
    assert "data-clear-action-filter" in script
    assert "筛选当前任务" in script
    assert "没有匹配任务" in script
    assert "F9" in script
    assert "可执行操作" in script
    assert "支撑检查" in script
    assert "条件查询" in script
    assert "${escapeHtml(riskLabel(action.risk))} / ${escapeHtml(viewLabel(action.view_type))}" not in script
    assert "confirmation_required" in script
    assert "data-confirm-action" in script
    assert "data-action-ui-key" in script
    assert "data-action-key=" not in script
    assert "function actionUiKey" in script
    assert "function actionRefFromForm" in script
    assert "data-workflow-target" in script
    assert "function renderWorkflowStrip" in script
    assert "function loadWorkflowStep" in script
    assert "function businessContextSections" in script
    assert "function renderDecisionCue" in script
    assert "function bindDecisionCueActions" in script
    assert "data-decision-action" in script
    assert "运行下一主流程" in script
    assert "进入流程下一屏" in script
    assert "function resultEvidenceLabel" in script
    assert "function renderEmptyState" in script
    assert "empty_guidance" in script
    assert "清空筛选后查看全部记录" in script
    assert "function humanizeRowKey" in script
    assert "function rowLabelForKey" in script
    assert "function rowDisplayRows" in script
    assert "Object.entries(row).slice(0, 14)" not in script
    assert "function fillActionFromSelectedRow" in script
    assert "function rowFieldCandidates" in script
    assert "function actionsAvailableForRow" in script
    assert "function paramsFromRowForAction" in script
    assert "function runInspectorAction" in script
    assert "选中行可做" in script
    assert "data-inspector-action" in script
    assert "直接使用选中记录填入参数" in script
    assert "function nextPrimaryAction" in script
    assert "function runNextPrimaryAction" in script
    assert "function markActionCompleted" in script
    assert "function screenProgress" in script
    assert "completedActionsByScreen" in script
    assert "data-fill-from-row" in script
    assert "从选中行填充" in script
    assert "业务目标" in script
    assert "判断产出" in script
    assert "当前证据" in script
    assert "本屏下一项" in script
    assert "本屏进度" in script
    assert "function resetCurrentScreenProgress" in script
    assert "本屏进度已重置" in script
    assert "当前任务" in script
    assert "操作" in script
    assert "后续动作" in script
    assert "Status board" not in script
    assert "快捷操作" not in script
    assert "系统信息" not in script
    assert "128MB / 512MB" not in script
    assert "2.3.1 (TUI)" not in script
    assert "Page -/- | 0 rows" not in script
    assert " rows</span>" not in script
    assert "NO MATCHING ROWS" not in script
    assert "NO GRID TO FILTER" not in script
    assert "NO PAGER" not in script
    assert "FILTER READY" not in script
    assert "暂无可显示数据" in script
    assert "页 -/- | 0 行" in script
    assert "function groupActions" in script
    assert "tui-action-group-title" in script
    assert "function isAdvancedAction" in script
    assert "function actionTier" in script
    assert "function dashboardTargetScreen" in script
    assert "data-toggle-support" in script
    assert "data-toggle-advanced" in script
    assert "data-dashboard-target" in script
    assert "支撑检查已显示" in script
    assert "高级查询已显示" in script
    assert "主流程" in script


def test_tui_workbench_css_uses_pc_tools_scrollbar_skin():
    css = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "css", "tui-workbench.css")
        .read_text(encoding="utf-8")
    )

    assert ".tui-rail-body::-webkit-scrollbar" in css
    assert ".tui-main-body::-webkit-scrollbar-thumb" in css
    assert "scrollbar-gutter: stable" in css
    assert "border-radius: 0" in css
    assert "vertical:decrement" in css
    assert "vertical:increment" in css
    assert "horizontal:decrement" in css
    assert "horizontal:increment" in css
    assert "--tui-scroll-track: #263449" in css
    assert "--tui-scroll-face: #58708F" in css
    assert "--tui-menubar-bg:" in css
    assert "--tui-footer-bg:" in css
    assert "--tui-overlay:" in css
    assert "--tui-scroll-arrow-up:" in css
    assert "background-image: var(--tui-scroll-arrow-up);" in css
    assert "background-image: var(--tui-scroll-arrow-right);" in css
    assert "#c9c9c9" not in css
    assert "#02021f" not in css
    assert "#555" not in css
    assert "#d00" not in css
    assert ".tui-action-brief" in css
    assert ".tui-action-filter" in css
    assert ".tui-action-toggle" in css
    assert ".tui-action-group-operation" in css
    assert ".tui-empty-guidance" in css
    assert ".tui-inspector-actions" in css
    assert "data-inspector-action" not in css
    assert ".tui-decision-actions" in css
    assert "position: sticky" in css
    assert ".tui-dash-panel:focus" in css


def test_tui_registry_api_returns_module_contracts(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/registry/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "tui-workbench.v2"
    assert payload["default_module"] == "command-center"
    assert payload["interaction_model"] == "user-task-workbench-to-approved-tools"
    assert payload["groups"]
    assert any(
        module["key"] == "command-center"
        for group in payload["groups"]
        for module in group["modules"]
    )


def test_tui_module_snapshot_api_returns_renderable_spec(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/modules/macro-regime/snapshot/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["module"]["key"] == "macro-regime"
    assert payload["layout"]["type"] == "pc-tools-workbench"
    assert {block["type"] for block in payload["blocks"]} >= {
        "screen-context",
        "actions",
    }
    assert payload["actions"][0]["endpoint"].startswith("/api/")
    assert payload["actions"][0]["method"] == "GET"


def test_tui_action_schema_can_generate_form_controls(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/ai-ops.terminal/")

    assert response.status_code == 200
    payload = response.json()
    router_action = next(
        action for action in payload["actions"] if action["key"] == "terminal.chat_router"
    )
    assert router_action["ui_key"].startswith("task-")
    assert "terminal" not in router_action["ui_key"]
    assert router_action["fields"][0]["key"] == "message"
    assert router_action["fields"][0]["required"] is True


def test_tui_screen_payload_uses_operator_vocabulary(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/ai-ops.prompt-workbench/")

    assert response.status_code == 200
    payload = response.json()
    text = str(payload)
    labels = {action["label"] for action in payload["actions"]}

    assert payload["screen"]["label"] == "提示词与模型配置"
    assert "提示词模板" in labels
    assert "Prompt" not in text
    assert "Chat" not in text

    providers_response = client.get("/api/tui/screens/ai-ops.providers/")
    providers_payload = providers_response.json()
    provider_text = str(providers_payload)
    provider_labels = {action["label"] for action in providers_payload["actions"]}
    assert providers_payload["screen"]["label"] == "AI 服务商与用量"
    assert "我的 AI 服务商" in provider_labels
    assert "对话模型" in provider_labels
    assert "AI Provider" not in provider_text
    assert "Chat" not in provider_text


def test_tui_operation_fields_use_business_labels(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/research.alpha/")

    assert response.status_code == 200
    payload = response.json()
    action = next(action for action in payload["actions"] if action["key"] == "alpha.inference.trigger_batch")
    fields = {field["key"]: field for field in action["fields"]}

    assert fields["top_n"]["label"] == "候选数量"


def test_tui_catalog_api_returns_modules_and_screens(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "tui-workbench.v2"
    assert payload["default_screen"] == "command-center.overview"
    assert payload["stats"]["published_actions"] >= 1
    assert payload["stats"]["safe_read_evidence"] >= payload["stats"]["direct_safe_read_candidates"]
    assert "deferred_path_parameters" in payload["stats"]
    assert (
        payload["stats"]["smoke_ok"] + payload["stats"].get("smoke_needs_input", 0)
        + payload["stats"].get("approved_operation_actions", 0)
        == payload["stats"]["published_actions"]
    )
    assert payload["stats"]["business_promoted_actions"] >= 250
    assert payload["stats"]["approved_operation_actions"] >= 6
    assert any(
        screen["key"] == "macro-regime.overview"
        for group in payload["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    )


def test_tui_catalog_promotes_smoke_checked_tools_into_business_screens(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    screens = {
        screen["key"]: screen
        for group in payload["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    }
    expected_defaults = {
        "command-center.decision-flow": "auto.api.get.api.decision.context.step1",
        "execution.accounts": "auto.api.get.api.account.accounts",
        "execution.trading-ledger": "auto.api.get.api.account.positions",
        "execution.portfolio-performance": "auto.api.get.api.account.portfolios",
        "execution.account-settings": "auto.api.get.api.account.trading-cost-configs",
        "macro-regime.strategy": "auto.api.get.api.strategy.strategies",
        "macro-regime.rotation": "auto.api.get.api.rotation.recommendation",
        "macro-regime.risk-controls": "auto.api.get.api.decision-rhythm.summary",
        "macro-regime.beta-gate": "auto.api.get.api.beta-gate",
        "macro-regime.hedge": "auto.api.get.api.hedge.alerts.active",
        "research.asset-lab": "auto.api.get.api.asset-analysis.pool-summary",
        "research.fund-sector": "auto.api.get.api.fund.rank",
        "research.screening-sentiment": "auto.api.get.api.filter.indicators",
        "ai-ops.providers": "auto.api.get.api.ai.me.providers",
        "ai-ops.prompt-workbench": "auto.api.get.api.prompt.templates",
        "api-library.data-center": "auto.api.get.api.data-center",
        "api-library.market-thermometer": "auto.api.get.api.data-center.market-thermometer.history",
        "execution.events": "auto.api.get.api.events.status",
        "execution.share": "auto.api.get.api.share.links",
    }

    for screen_key, default_action_key in expected_defaults.items():
        assert screen_key in screens
        assert screens[screen_key]["status"] == "online"
        assert screens[screen_key]["default_action_key"] == default_action_key
        assert screens[screen_key]["action_count"] > 0
    assert all(screen["action_count"] > 0 for screen in screens.values())


def test_tui_business_screen_actions_are_grouped_by_user_task(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.accounts/")

    assert response.status_code == 200
    payload = response.json()
    actions = payload["actions"]
    groups = {action["task_group"] for action in actions}
    assert {"01 账户状态", "02 账户组合"} <= groups
    assert all(isinstance(action["sequence"], int) for action in actions)
    assert all(not action["label"].startswith("Get ") for action in actions)
    assert all("endpoint" not in action for action in actions)
    assert all("method" not in action for action in actions)
    assert all("source" not in action for action in actions)
    assert all("view_model" not in action for action in actions)
    assert all("raw_debug" not in action for action in actions)


def test_tui_actions_expose_business_task_tiers(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.trading-ledger/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"]: action for action in payload["actions"]}
    assert actions["auto.api.get.api.account.positions"]["task_tier"] == "primary"
    assert actions[
        "param.api.get.api.account.accounts.int.account_id.positions"
    ]["task_tier"] == "advanced"
    assert all(action["task_group"] for action in payload["actions"])
    assert all(action["task_tier"] for action in payload["actions"])

    settings_response = client.get("/api/tui/screens/execution.account-settings/")
    settings_payload = settings_response.json()
    settings_actions = {action["key"]: action for action in settings_payload["actions"]}
    assert settings_actions["auto.api.get.api.account.assets"]["task_tier"] == "support"


def test_tui_screens_expose_daily_workflow_navigation(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.accounts/")

    assert response.status_code == 200
    workflow = response.json()["screen"]["workflow"]
    assert workflow["name"] == "每日投研流程"
    assert workflow["label"] == "账户组合"
    assert workflow["previous"]["key"] == "research.asset-lab"
    assert workflow["next"]["key"] == "macro-regime.strategy"


def test_tui_screens_expose_business_context_for_operator_flow(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/command-center.decision-flow/")

    assert response.status_code == 200
    context = response.json()["screen"]["business_context"]
    assert "环境、信号、约束" in context["objective"]
    assert "当天行动结论" in context["decision_output"]
    assert context["checkpoints"][0].startswith("按第一步到第六步")


def test_tui_catalog_exposes_confirmation_ready_operations(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/macro-regime.pulse/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"]: action for action in payload["actions"]}
    action = actions["data_center.market_thermometer_calculate"]
    assert action["risk"] == "write"
    assert action["confirmation_required"] is True
    assert action["label"] == "重算市场温度"
    assert action["fields"][0]["input_type"] == "date"


def test_tui_write_action_requires_confirmation_before_execution(client, tui_user):
    client.force_login(tui_user)

    response = client.post(
        "/api/tui/actions/data_center.market_thermometer_calculate/run/",
        {"params": {}},
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["confirmation_required"] is True
    assert payload["action"]["risk"] == "write"
    assert payload["debug"]["raw_available"] is False


def test_tui_parameterized_read_tools_are_promoted_to_user_screens(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.trading-ledger/")

    assert response.status_code == 200
    payload = response.json()
    action = next(
        action
        for action in payload["actions"]
        if action["key"] == "param.api.get.api.account.accounts.int.account_id.positions"
    )
    assert action["task_group"] == "07 条件查询"
    assert action["fields"][0]["key"] == "account_id"
    assert action["fields"][0]["label"] == "账户ID"
    assert action["fields"][0]["placeholder"] == "请输入账户ID"
    assert action["fields"][0]["required"] is True
    assert action["screen_key"] == "execution.trading-ledger"


def test_tui_pagination_fields_are_user_facing(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/ai-ops.capabilities/")

    assert response.status_code == 200
    payload = response.json()
    action = next(action for action in payload["actions"] if action["key"] == "ai_capability.list")
    fields = action["fields"]
    assert fields[0]["key"] == "page"
    assert fields[0]["label"] == "页码"
    assert fields[0]["default"] == "1"


def test_tui_screen_api_returns_pc_tools_contract(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/ai-ops.capabilities/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["layout"]["regions"] == [
        "module_tree",
        "workspace",
        "inspector",
        "status_bar",
        "raw_drawer",
    ]
    assert payload["screen"]["key"] == "ai-ops.capabilities"
    assert payload["screen"]["default_action_key"] == "ai_capability.list"
    assert any(action["key"] == "ai_capability.list" for action in payload["actions"])


def test_tui_terminal_screen_defaults_to_interactive_chat(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/ai-ops.terminal/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["label"] == "AI 交互终端"
    assert payload["screen"]["default_action_key"] == "terminal.chat_router"
    action = next(action for action in payload["actions"] if action["key"] == "terminal.chat_router")
    assert action["label"] == "询问 AI 助手"
    assert action["risk"] == "ai"
    assert action["fields"][0]["key"] == "message"
    assert action["fields"][0]["label"] == "消息"


def test_tui_default_screen_returns_user_dashboard_panels(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/command-center.overview/")

    assert response.status_code == 200
    payload = response.json()
    panels = payload["screen"]["dashboard_panels"]
    assert [panel["layout_area"] for panel in panels] == [
        "regime",
        "pulse",
        "account",
        "alpha",
        "tasks",
    ]
    assert any(panel["action_key"] == "task_monitor.dashboard" for panel in panels)
    assert [panel["title"] for panel in panels] == [
        "一、市场周期象限",
        "二、战术脉搏预警",
        "三、账户与持仓",
        "四、Alpha 排行",
        "五、任务监控",
    ]


def test_tui_business_labels_do_not_leak_endpoint_generated_words(client, tui_user):
    client.force_login(tui_user)

    screen_keys = [
        "command-center.dashboard",
        "macro-regime.strategy",
        "execution.audit",
        "api-library.runtime",
        "ai-ops.capabilities",
    ]
    forbidden_fragments = {
        "Dashboard Alpha",
        "System List",
        "Password Strength",
        "Validate",
        "Assignment",
        "Realtime",
        "Policy",
        "回测s",
        "策略 策略",
    }

    labels = []
    for screen_key in screen_keys:
        response = client.get(f"/api/tui/screens/{screen_key}/")
        assert response.status_code == 200
        labels.extend(action["label"] for action in response.json()["actions"])

    joined_labels = "\n".join(labels)
    for fragment in forbidden_fragments:
        assert fragment not in joined_labels
    assert "今日仪表盘" in labels
    assert "系统任务列表" in labels
    assert "复盘审计总览" in labels


def test_tui_action_runner_returns_business_view_model(client, tui_user):
    client.force_login(tui_user)

    response = client.post(
        "/api/tui/actions/dashboard.alpha_provider_status/run/",
        {"params": {}},
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "tui-workbench.v2"
    assert payload["view_model"]["kind"] in {"detail", "datagrid", "message"}
    assert "raw_response" in payload["debug"]
    assert "request" not in payload
    assert "endpoint" not in payload["action"]
    assert "method" not in payload["action"]
    assert "source" not in payload["action"]


def test_tui_metadata_validator_rejects_non_api_endpoint():
    payload = _metadata_payload()
    payload["actions"][0]["endpoint"] = "/admin/terminal/"

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)


def test_tui_metadata_validator_rejects_unknown_view_model_key():
    payload = _metadata_payload()
    payload["actions"][0]["view_model"] = {"business_specific_magic": "logs"}

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)


def test_tui_metadata_validator_rejects_unknown_default_action():
    payload = _metadata_payload()
    payload["screens"][0]["default_action_key"] = "missing.action"

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)


def test_tui_metadata_validator_rejects_unknown_field_widget():
    payload = _metadata_payload()
    payload["actions"][0]["fields"] = [
        {"key": "amount", "label": "Amount", "input_type": "money_input"}
    ]

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)


def test_tui_metadata_validator_rejects_unknown_source_prefix():
    payload = _metadata_payload()
    payload["actions"][0]["source"] = "ai-made-this-up"

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)


def test_tui_metadata_validator_adds_schema_and_value_type_defaults():
    payload = _metadata_payload()
    payload["actions"][0]["fields"] = [
        {"key": "portfolio_id", "label": "Portfolio ID", "input_type": "number"}
    ]

    validated = validate_tui_metadata(payload)
    field = validated["actions"][0]["fields"][0]

    assert validated["schema_version"] == "tui-metadata.v3"
    assert field["value_type"] == "integer"


def test_tui_metadata_compact_payload_round_trips_runtime_defaults():
    payload = validate_tui_metadata(_metadata_payload())
    compacted = compact_tui_metadata_payload(payload)
    action = compacted["actions"][0]

    assert "method" not in action
    assert "risk" not in action
    assert "fields" not in action
    assert "view_model" not in action
    assert "raw_debug" not in action
    assert "module_key" not in action

    restored = validate_tui_metadata(compacted)
    restored_action = restored["actions"][0]
    assert restored_action["method"] == "GET"
    assert restored_action["risk"] == "read"
    assert restored_action["fields"] == []
    assert restored_action["view_model"] == {}
    assert restored_action["raw_debug"] is True
    assert restored_action["module_key"] == "command-center"


def test_tui_service_reads_published_metadata_and_requires_write_confirmation():
    actions = [
        {
            "key": "safe.read",
            "label": "Safe Read",
            "method": "GET",
            "endpoint": "/api/regime/current/",
            "intent": "safe_read",
            "screen_key": "command-center.overview",
            "module_key": "command-center",
            "view_type": "detail",
            "risk": "read",
            "fields": [],
        },
        {
            "key": "safe.write",
            "label": "Safe Write",
            "method": "POST",
            "endpoint": "/api/terminal/chat/",
            "intent": "safe_write",
            "screen_key": "command-center.overview",
            "module_key": "command-center",
            "view_type": "detail",
            "risk": "write",
            "fields": [],
        },
        {
            "key": "admin.write",
            "label": "Admin Write",
            "method": "POST",
            "endpoint": "/api/account/admin-token/",
            "intent": "admin_write",
            "screen_key": "command-center.overview",
            "module_key": "command-center",
            "view_type": "detail",
            "risk": "admin",
            "fields": [],
        },
    ]

    catalog = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(_metadata_payload(actions=actions))
    ).get_catalog()

    assert catalog["stats"]["published_actions"] == 3
    assert catalog["stats"]["hidden_by_risk"] == 1
    screen = catalog["groups"][0]["modules"][0]["screens"][0]
    assert screen["action_count"] == 2

    spec = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(_metadata_payload(actions=actions))
    ).get_screen("command-center.overview")
    write_action = next(action for action in spec["actions"] if action["key"] == "safe.write")
    assert write_action["confirmation_required"] is True


def test_tui_service_action_runner_wraps_list_as_datagrid(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "code": "AAA",
                            "score": 1,
                            "risk_level": "safe",
                            "requires_confirmation": False,
                        },
                        {
                            "code": "BBB",
                            "score": 2,
                            "risk_level": "safe",
                            "requires_confirmation": False,
                        },
                    ],
                    "count": 2,
                    "page": 1,
                    "page_size": 20,
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "asset.list",
                        "label": "Asset List",
                        "method": "GET",
                        "endpoint": "/api/asset-analysis/pool-summary/",
                        "intent": "list_assets",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )
    payload = service.run_action(
        action_key="asset.list",
        params={},
        user=tui_user,
    )

    assert payload["view_model"]["kind"] == "datagrid"
    assert payload["view_model"]["columns"][0]["key"] == "code"
    assert payload["view_model"]["pager"]["total_rows"] == 2
    assert payload["response"]["status_code"] == 200


def test_tui_service_action_runner_binds_path_parameters(tui_user):
    class FakeExecutor:
        def __init__(self):
            self.kwargs = {}

        def execute(self, **kwargs):
            self.kwargs = kwargs
            return {
                "status_code": 200,
                "payload": {"id": "42", "name": "Position 42"},
            }

    executor = FakeExecutor()
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "position.detail",
                        "label": "Position Detail",
                        "method": "GET",
                        "endpoint": "/api/account/positions/<int:pk>/",
                        "intent": "read_position_detail",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "pk",
                                "label": "PK",
                                "input_type": "number",
                                "required": True,
                            }
                        ],
                    }
                ]
            )
        ),
        action_executor=executor,
    )

    payload = service.run_action(
        action_key="position.detail",
        params={"pk": "42", "page": "2"},
        user=tui_user,
    )

    assert executor.kwargs["endpoint"] == "/api/account/positions/42/"
    assert executor.kwargs["params"] == {"page": "2"}
    assert payload["view_model"]["kind"] == "detail"


def test_tui_service_action_runner_rejects_unsafe_path_parameters(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            raise AssertionError("Executor should not run for unsafe path params")

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "position.detail",
                        "label": "Position Detail",
                        "method": "GET",
                        "endpoint": "/api/account/positions/<int:pk>/",
                        "intent": "read_position_detail",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [{"key": "pk", "label": "PK", "required": True}],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    with pytest.raises(ValueError):
        service.run_action(
            action_key="position.detail",
            params={"pk": "42/extra"},
            user=tui_user,
        )


def test_tui_service_write_action_requires_confirmation_before_execution(tui_user):
    class FakeExecutor:
        def __init__(self):
            self.calls = 0

        def execute(self, **kwargs):
            self.calls += 1
            return {"status_code": 200, "payload": {"status": "ok"}}

    executor = FakeExecutor()
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "terminal.write",
                        "label": "保存视图",
                        "method": "POST",
                        "endpoint": "/api/terminal/chat/",
                        "intent": "save_view",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "write",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=executor,
    )

    confirmation = service.run_action(
        action_key="terminal.write",
        params={},
        user=tui_user,
    )

    assert confirmation["confirmation_required"] is True
    assert confirmation["confirmation"]["confirm_label"] == "确认执行"
    assert executor.calls == 0

    payload = service.run_action(
        action_key="terminal.write",
        params={},
        user=tui_user,
        confirmed=True,
    )

    assert payload["confirmation_required"] is False
    assert payload["view_model"]["kind"] == "detail"
    assert executor.calls == 1


def test_tui_service_validates_required_fields_before_write_confirmation(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            raise AssertionError("Executor should not run when required fields are missing")

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "quotes.sync",
                        "label": "同步最新报价",
                        "method": "POST",
                        "endpoint": "/api/data-center/sync/quotes/",
                        "intent": "sync_quotes",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "write",
                        "fields": [
                            {"key": "provider_id", "label": "Provider ID", "required": True},
                            {"key": "asset_codes", "label": "资产代码", "required": True},
                        ],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(action_key="quotes.sync", params={}, user=tui_user)

    assert payload["confirmation_required"] is False
    assert payload["response"]["status_code"] == 400
    assert payload["view_model"]["kind"] == "message"
    assert payload["view_model"]["status"] == "需要参数"
    assert payload["view_model"]["sections"][0]["title"] == "需要补充参数"
    assert payload["view_model"]["sections"][0]["rows"][0]["label"] == "数据源ID"
    assert "F9" in " ".join(payload["view_model"]["sections"][0]["body"])
    assert [field["key"] for field in payload["missing_fields"]] == ["provider_id", "asset_codes"]
    assert payload["missing_fields"][0]["label"] == "数据源ID"


def test_tui_service_action_runner_uses_metadata_view_model_paths(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "success": True,
                    "records": [
                        {"operation": "refresh", "status": "ok"},
                    ],
                    "meta": {
                        "total": 41,
                        "page": 2,
                        "page_size": 20,
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "audit.operation_logs",
                        "label": "Operation Logs",
                        "method": "GET",
                        "endpoint": "/api/audit/operation-logs/",
                        "intent": "list_audit_logs",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                        "view_model": {
                            "rows_path": "records",
                            "total_path": "meta.total",
                            "page_path": "meta.page",
                            "page_size_path": "meta.page_size",
                        },
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="audit.operation_logs",
        params={},
        user=tui_user,
    )

    assert payload["view_model"]["kind"] == "datagrid"
    assert payload["view_model"]["columns"][0]["key"] == "operation"
    assert payload["view_model"]["pager"]["total_rows"] == 41
    assert payload["view_model"]["pager"]["page"] == 2


def test_tui_service_action_runner_can_detect_generic_nested_lists(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "ok": True,
                    "data": {
                        "records": [
                            {"name": "row-1", "value": 1},
                            {"name": "row-2", "value": 2},
                        ],
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "generic.records",
                        "label": "Generic Records",
                        "method": "GET",
                        "endpoint": "/api/generic/records/",
                        "intent": "list_generic_records",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="generic.records",
        params={},
        user=tui_user,
    )

    assert payload["view_model"]["kind"] == "datagrid"
    assert payload["view_model"]["columns"][0]["key"] == "name"
    assert payload["view_model"]["rows"][1]["value"] == "2"


def test_tui_service_status_action_prefers_detail_over_nested_list_detection(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "state": "RECOVERY",
                    "indicators": [
                        {"code": "PMI", "value": 50.2},
                    ],
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "regime.current",
                        "label": "Current Regime",
                        "method": "GET",
                        "endpoint": "/api/regime/current/",
                        "intent": "read_current_regime",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "status",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="regime.current",
        params={},
        user=tui_user,
    )

    assert payload["view_model"]["kind"] == "detail"
    assert payload["view_model"]["fields"][0]["key"] == "state"
    assert payload["view_model"]["nested"][0]["key"] == "indicators"


def test_tui_service_detail_model_flattens_one_level_nested_objects(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "user": {
                        "username": "admin",
                        "display_name": "Admin User",
                    },
                    "regime": {
                        "current": "Recovery",
                    },
                    "portfolio": {
                        "total_assets": 100000,
                        "cash_balance": 1200,
                        "initial_capital": 1000000,
                        "invested_ratio": 0.75,
                        "total_return_pct": 0.125,
                    },
                    "celery_health": {
                        "is_healthy": False,
                        "pending_tasks_count": 2,
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "dashboard.summary",
                        "label": "Dashboard Summary",
                        "method": "GET",
                        "endpoint": "/api/dashboard/summary/",
                        "intent": "read_dashboard_summary",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                        "view_model": {"kind": "detail"},
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="dashboard.summary",
        params={},
        user=tui_user,
    )

    fields = payload["view_model"]["fields"]
    assert {
        "key": "user.username",
        "label": "用户 / 用户名",
        "value": "admin",
    } in fields
    assert {
        "key": "user.display_name",
        "label": "用户 / 显示名称",
        "value": "Admin User",
    } in fields
    assert {
        "key": "regime.current",
        "label": "环境 / 当前",
        "value": "复苏",
    } in fields
    assert {
        "key": "portfolio.total_assets",
        "label": "组合 / 总资产",
        "value": "100000",
    } in fields
    assert {
        "key": "portfolio.cash_balance",
        "label": "组合 / 现金余额",
        "value": "1200",
    } in fields
    assert {
        "key": "portfolio.initial_capital",
        "label": "组合 / 初始资金",
        "value": "1000000",
    } in fields
    assert {
        "key": "portfolio.total_return_pct",
        "label": "组合 / 总收益率",
        "value": "0.125",
    } in fields
    assert {
        "key": "portfolio.invested_ratio",
        "label": "组合 / 已投资比例",
        "value": "0.75",
    } in fields
    assert {
        "key": "celery_health.is_healthy",
        "label": "Celery健康 / 是否健康",
        "value": "否",
    } in fields
    assert {
        "key": "celery_health.pending_tasks_count",
        "label": "Celery健康 / 待处理任务",
        "value": "2",
    } in fields
    assert payload["view_model"]["status"] == "正常"


def test_tui_service_datagrid_uses_operator_field_labels(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "asset_code": "000001.SH",
                            "asset_name": "上证指数",
                            "score": 0.82,
                            "is_active": True,
                        }
                    ],
                    "count": 1,
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "asset.pool",
                        "label": "资产池",
                        "method": "GET",
                        "endpoint": "/api/asset-analysis/pool-summary/",
                        "intent": "read_asset_pool",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(action_key="asset.pool", params={}, user=tui_user)

    assert payload["view_model"]["status"] == "正常"
    assert payload["view_model"]["columns"] == [
        {"key": "asset_code", "label": "标的代码"},
        {"key": "asset_name", "label": "标的名称"},
        {"key": "score", "label": "评分"},
        {"key": "is_active", "label": "是否启用"},
    ]
    assert payload["view_model"]["rows"][0]["is_active"] == "是"


def test_tui_service_ai_capability_grid_hides_unsafe_api_rows(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "capability_key": "builtin.system_status",
                            "name": "System Status",
                            "summary": "Check system health",
                            "category": "system",
                            "risk_level": "safe",
                            "requires_confirmation": False,
                        },
                        {
                            "capability_key": "api.delete.api.account.portfolios",
                            "name": "Delete Account Portfolios",
                            "summary": "GET /api/account/portfolios/ - list portfolios",
                            "category": "account",
                            "risk_level": "medium",
                            "requires_confirmation": True,
                        },
                    ],
                    "count": 2,
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "ai.capabilities",
                        "label": "AI 能力清单",
                        "method": "GET",
                        "endpoint": "/api/ai-capability/capabilities/",
                        "intent": "list_ai_capabilities",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(action_key="ai.capabilities", params={}, user=tui_user)
    view_model = payload["view_model"]
    text = str(view_model)

    assert view_model["kind"] == "datagrid"
    assert view_model["columns"] == [
        {"key": "name", "label": "名称"},
        {"key": "summary", "label": "说明"},
        {"key": "category", "label": "分类"},
        {"key": "risk_level", "label": "风险等级"},
        {"key": "requires_confirmation", "label": "需要确认"},
    ]
    assert view_model["pager"]["total_rows"] == 1
    assert view_model["rows"][0]["risk_level"] == "安全"
    assert "api.delete" not in text
    assert "/api/" not in text


def test_tui_service_empty_datagrid_returns_user_empty_state(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [],
                    "count": 0,
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "account.positions",
                        "label": "持仓明细",
                        "method": "GET",
                        "endpoint": "/api/account/positions/",
                        "intent": "read_positions",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(action_key="account.positions", params={}, user=tui_user)

    assert payload["view_model"]["kind"] == "datagrid"
    assert payload["view_model"]["columns"] == []
    assert payload["view_model"]["rows"] == []
    assert payload["view_model"]["empty_message"] == "暂无持仓明细数据。"
    assert "F5" in " ".join(payload["view_model"]["empty_guidance"])
    assert "F9" in " ".join(payload["view_model"]["empty_guidance"])


def test_tui_service_converts_html_fragment_payload_to_message(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "html": """
                    <div class="funnel-step-content" style="animation: fadeIn 0.3s;">
                        <h3>阶段 1：环境状态</h3>
                        <p>当前宏观环境可以继续观察。</p>
                        <script>window.bad = true;</script>
                    </div>
                    """,
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "decision.context.step1",
                        "label": "第一步：环境状态",
                        "method": "GET",
                        "endpoint": "/api/decision/context/step1/",
                        "intent": "read_decision_context",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="decision.context.step1",
        params={},
        user=tui_user,
    )

    message = payload["view_model"]["message"]
    assert payload["view_model"]["kind"] == "message"
    assert payload["view_model"]["sections"]
    assert payload["view_model"]["sections"][0]["title"] == "阶段 1：环境状态"
    assert "阶段 1：环境状态" in message
    assert "当前宏观环境可以继续观察。" in message
    assert "<div" not in message
    assert "class=" not in message
    assert "style=" not in message
    assert "window.bad" not in message


def test_tui_service_cleans_html_fragment_inside_detail_field(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "title": "环境状态",
                    "summary": "<p><strong>当前象限：</strong><span>Recovery</span></p>",
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "decision.context.summary",
                        "label": "环境状态",
                        "method": "GET",
                        "endpoint": "/api/decision/context/step1/",
                        "intent": "read_decision_context",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="decision.context.summary",
        params={},
        user=tui_user,
    )

    fields = payload["view_model"]["fields"]
    summary = next(field["value"] for field in fields if field["key"] == "summary")
    assert "当前象限：" in summary
    assert "复苏" in summary
    assert "<strong" not in summary
    assert "<span" not in summary


def test_tui_service_converts_endpoint_directory_to_operator_summary(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "message": "AgomTradePro Beta Gate API",
                    "endpoints": {
                        "configs": "/api/beta-gate/configs/",
                        "decisions": "/api/beta-gate/decisions/",
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "beta.directory",
                        "label": "Beta Gate 状态",
                        "method": "GET",
                        "endpoint": "/api/beta-gate/",
                        "intent": "read_beta_gate",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(action_key="beta.directory", params={}, user=tui_user)
    view_model = payload["view_model"]
    text = str(view_model)

    assert view_model["kind"] == "detail"
    assert {
        "key": "capability_count",
        "label": "已登记能力",
        "value": "2 项",
    } in view_model["fields"]
    assert "/api/" not in text
    assert "Endpoints" not in text
    assert "调试抽屉" in text


def test_tui_service_hides_absolute_internal_api_paths_in_details(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "module": "system",
                    "service": "System tools",
                    "endpoints": [
                        "http://testserver/api/system/health/",
                        "http://testserver/api/system/ready/",
                    ],
                    "links": {"status": "http://testserver/api/system/status/"},
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "system.directory",
                        "label": "系统工具目录",
                        "method": "GET",
                        "endpoint": "/api/system/",
                        "intent": "read_system",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(action_key="system.directory", params={}, user=tui_user)
    view_model = payload["view_model"]
    text = str(view_model)

    assert view_model["kind"] == "detail"
    assert "http://testserver/api/" not in text
    assert "/api/" not in text
    assert "Endpoints" not in text
    assert all(item["key"] != "endpoints" for item in view_model["nested"])


def test_tui_metadata_repository_uses_db_published_override(db):
    db_payload = _metadata_payload()
    db_payload["modules"][0]["label"] = "DB Command Center"
    TuiMetadataRegistryORM._default_manager.create(
        registry_key="default",
        version="tui-workbench.v2",
        status="published",
        payload=db_payload,
    )

    loaded = PublishedTuiMetadataRepository().load_published()

    assert loaded["modules"][0]["label"] == "DB Command Center"


def test_tui_metadata_repository_records_publish_audit_fields(db, tui_user):
    payload = _metadata_payload()
    model = PublishedTuiMetadataRepository().publish_payload(
        payload=payload,
        approved_by=tui_user,
        review_note="Reviewed audit metadata",
        generation_source="mixed",
        backend_version="test-backend",
        source_evidence_hash="a" * 64,
    )

    assert model.schema_version == "tui-metadata.v3"
    assert model.review_status == "approved"
    assert model.generation_source == "mixed"
    assert model.backend_version == "test-backend"
    assert model.source_evidence_hash == "a" * 64
    assert model.changed_fields == ["initial_publish"]
    assert model.approved_by == tui_user


def test_tui_service_derives_business_context_for_unannotated_screens():
    service = TuiWorkbenchService(metadata_repository=FakeMetadataRepository())

    screen = service.get_screen("command-center.overview")["screen"]
    context = screen["business_context"]

    assert context["objective"] == "Overview."
    assert "业务" in context["decision_output"] or "状态" in context["decision_output"]
    assert "先按主流程任务读取本屏关键判断。" in context["checkpoints"]
