import json
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.utils import timezone

import apps.terminal.application.tui_workbench as tui_workbench_module
from apps.account.infrastructure.models import SystemSettingsModel
from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.alpha.infrastructure.models import QlibModelRegistryModel
from apps.share.infrastructure.models import ShareLinkModel, ShareSnapshotModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.terminal.application.tui_metadata import (
    TuiMetadataValidationError,
    compact_tui_metadata_payload,
    validate_tui_metadata,
)
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.models import TerminalAuditLogORM, TuiMetadataRegistryORM
from apps.terminal.infrastructure.tui_adapters import get_tui_action_executor
from apps.terminal.infrastructure.tui_metadata_repository import (
    RUNTIME_ACTION_PATCHES,
    RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS,
    PublishedTuiMetadataRepository,
)


def _metadata_payload(actions=None, screens=None, modules=None, groups=None, default_screen=None):
    payload = {
        "version": "tui-workbench.v2",
        "registry_key": "default",
        "default_screen": default_screen or "command-center.overview",
        "interaction_model": "published-metadata-to-pc-tools",
        "groups": deepcopy(groups or [{"key": "workflow", "label": "Workflow"}]),
        "modules": deepcopy(
            modules
            or [
                {
                    "key": "command-center",
                    "label": "Command Center",
                    "group": "workflow",
                    "summary": "Command tools.",
                    "status": "online",
                }
            ]
        ),
        "screens": deepcopy(
            screens
            or [
                {
                    "key": "command-center.overview",
                    "label": "Command Overview",
                    "module_key": "command-center",
                    "group": "workflow",
                    "summary": "Overview.",
                    "view_type": "status",
                    "status": "online",
                    "default_action_key": "sample.list",
                }
            ]
        ),
        "actions": deepcopy(
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
    groups_payload = payload["groups"]
    modules_payload = payload["modules"]
    screens_payload = payload["screens"]
    actions_payload = payload["actions"]
    screen_keys = {str(screen.get("key") or "") for screen in screens_payload if isinstance(screen, dict)}
    action_keys = {str(action.get("key") or "") for action in actions_payload if isinstance(action, dict)}

    group_keys = {str(group.get("key") or "") for group in groups_payload if isinstance(group, dict)}
    referenced_group_keys = {
        str(screen.get("group") or "")
        for screen in screens_payload
        if isinstance(screen, dict) and str(screen.get("group") or "")
    }
    for group_key in sorted(referenced_group_keys - group_keys):
        groups_payload.append({"key": group_key, "label": group_key})

    group_keys = {str(group.get("key") or "") for group in groups_payload if isinstance(group, dict)}
    module_keys = {str(module.get("key") or "") for module in modules_payload if isinstance(module, dict)}
    referenced_module_keys = {
        str(item.get("module_key") or "")
        for item in [*screens_payload, *actions_payload]
        if isinstance(item, dict) and str(item.get("module_key") or "")
    }
    for module_key in sorted(referenced_module_keys - module_keys):
        group_key = next(
            (
                str(screen.get("group") or "")
                for screen in screens_payload
                if isinstance(screen, dict) and str(screen.get("module_key") or "") == module_key
            ),
            next(iter(group_keys), "workflow"),
        )
        modules_payload.append(
            {
                "key": module_key,
                "label": module_key,
                "group": group_key,
                "summary": f"{module_key} tools.",
                "status": "online",
            }
        )

    actions_by_screen: dict[str, list[str]] = {}
    for action in actions_payload:
        if not isinstance(action, dict):
            continue
        screen_key = str(action.get("screen_key") or "")
        action_key = str(action.get("key") or "")
        if screen_key and action_key:
            actions_by_screen.setdefault(screen_key, []).append(action_key)

    for screen in screens_payload:
        if not isinstance(screen, dict):
            continue
        screen_key = str(screen.get("key") or "")
        panels = screen.get("dashboard_panels")
        if isinstance(panels, list):
            filtered_panels = [
                panel
                for panel in panels
                if not isinstance(panel, dict)
                or str(panel.get("action_key") or "").strip() == ""
                or str(panel.get("action_key") or "").strip() in action_keys
            ]
            if filtered_panels != panels:
                screen["dashboard_panels"] = filtered_panels
        default_action_key = str(screen.get("default_action_key") or "").strip()
        if not default_action_key or default_action_key in action_keys:
            fallback_action_key = next(iter(actions_by_screen.get(screen_key, [])), "")
            if not default_action_key and fallback_action_key:
                screen["default_action_key"] = fallback_action_key
        else:
            fallback_action_key = next(iter(actions_by_screen.get(screen_key, [])), "")
            if fallback_action_key:
                screen["default_action_key"] = fallback_action_key
            else:
                screen["default_action_key"] = ""
        user_experience = screen.get("user_experience")
        if isinstance(user_experience, dict) and str(user_experience.get("journey") or "") == "dashboard":
            if not screen.get("dashboard_panels"):
                screen["user_experience"] = {**user_experience, "journey": "workspace"}

    if str(payload.get("default_screen") or "") not in screen_keys and screens_payload:
        payload["default_screen"] = str(screens_payload[0].get("key") or "")
    return payload


def _runtime_transform_counts(payload: dict[str, object]) -> tuple[int, int]:
    actions = payload.get("actions") or []
    patched = 0
    pruned = 0
    repository = PublishedTuiMetadataRepository()
    for action in actions:
        screen_key = str(action.get("screen_key") or "")
        action_key = str(action.get("key") or "")
        if action_key in RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS.get(screen_key, set()):
            pruned += 1
            continue
        patch = RUNTIME_ACTION_PATCHES.get(action_key)
        if patch and repository._apply_runtime_patch(action, patch)[1]:
            patched += 1
    return patched, pruned


class FakeMetadataRepository:
    def __init__(self, payload=None):
        self.payload = validate_tui_metadata(payload or _metadata_payload())

    def load_published(self, registry_key="default"):
        return self.payload


class FakeAuditRepository:
    def __init__(self):
        self.entries = []

    def save(self, entry):
        self.entries.append(entry)
        return entry

    def get_recent(
        self,
        limit=50,
        username=None,
        command_name=None,
        result_status=None,
    ):
        return self.entries[:limit]


@pytest.fixture
def tui_user(db):
    return User.objects.create_user(username="tui_user", password="test-password")


@pytest.fixture
def tui_admin_user(db):
    return User.objects.create_superuser(
        username="tui_admin",
        email="tui_admin@example.com",
        password="test-password",
    )


def test_tui_workbench_requires_login(client):
    response = client.get("/tui/")

    assert response.status_code == 302
    assert "/account/login/" in response["Location"]


def test_tui_workbench_page_is_standalone(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/tui/")

    assert response.status_code == 200
    assert response.cookies["agom_ui_mode"].value == "tui"
    html = response.content.decode()
    assert "TUI Workbench - AgomTradePro" in html
    assert "tui-workbench.css" in html
    assert "tui-workbench.js" in html
    assert "tui-workbench.js?v=" in html
    assert "data-module-tree" in html
    assert "data-workflow-strip" in html
    assert 'id="tui-location-input"' in html
    assert "data-current-location" in html
    assert 'type="text"' in html
    assert 'value="screen:boot"' in html
    assert 'aria-label="输入 TUI screen 地址后跳转"' in html
    assert "screen:boot" in html
    assert "用户: tui_user" in html
    assert "data-theme-status" in html
    assert "STYLE: B" in html
    assert "data-theme-indicator" in html
    assert "data-theme-indicator-code" in html
    assert "T:B" in html
    assert 'href="/dashboard/"' in html
    assert "<strong>Classic</strong> 界面" in html
    assert "data-toggle-rail" in html
    assert "data-toggle-inspector" in html
    assert "data-inspector-resize-handle" in html
    assert 'aria-label="调整说明栏宽度"' in html
    assert 'tabindex="-1"' in html
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
    assert "function beginInspectorResize" in script


def test_tui_workbench_script_contains_operator_home_state_and_governance_hooks():
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

    assert "agom-tui-last-non-home-screen:v1" in script
    assert "agom-tui-pinned-screen-keys:v1" in script
    assert "agom-tui-preferred-home-lane:v1" in script
    assert "agom-tui-resume-on-boot:v1" in script
    assert "/operator/governance-queue/" in script
    assert "operator.home.enter_governance_flow" in script
    assert "operator.home.resume_last_workspace" in script
    assert "function resizeInspectorByKeyboard" in script
    assert "inspectorWidthStorageKey" in script
    assert "data-toggle-rail" in script
    assert "data-toggle-inspector" in script
    assert "data-inspector-resize-handle" in script
    assert ".tui-app.is-rail-collapsed" in css
    assert ".tui-app.is-inspector-collapsed" in css
    assert ".tui-inspector-resize-handle" in css
    assert ".tui-row-fill-button:disabled" in css


def test_tui_workbench_star_marks_favorites_without_reordering_catalog():
    script = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "js", "tui-workbench.js")
        .read_text(encoding="utf-8")
    )

    assert "收藏工作区" in script
    assert "取消收藏工作区" in script
    assert "置顶工作区" not in script
    assert ".slice().sort((left, right) => {" not in script


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
    assert "root.dataset.tuiTheme = resolvedThemeKey" in script
    assert "function cycleTheme()" in script
    assert "function showThemeStatus()" in script
    assert "window.localStorage?.setItem(themeStorageKey, resolvedThemeKey)" in script
    assert "const HOTKEY_COMMANDS = {" in script
    assert 'F10: "toggle-inspector"' in script
    assert "function keyboardCommandForEvent(event)" in script
    assert 'event.altKey && !event.ctrlKey && !event.shiftKey && lowerKey === "t"' in script
    assert 'event.ctrlKey && !event.altKey && !event.shiftKey && lowerKey === "t"' in script
    assert "els.themeIndicatorCode.textContent = `T:${resolvedThemeKey}`" in script
    assert "els.themeStatus.textContent = `STYLE: ${resolvedThemeKey}`" in script
    assert "setStatus(`主题已切换: ${nextKey}`)" in script
    assert 'showModal("主题"' in script
    assert 'showModal("帮助"' in script
    assert "不刷新页面，不丢失当前状态" in script


def test_tui_workbench_javascript_keeps_api_endpoints_out_of_task_buttons():
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
    assert "function screenKeyFromLocationInput" in script
    assert "function resetLocationInput" in script
    assert "function submitLocationInput" in script
    assert "els.currentLocation.value" in script
    assert "els.currentLocation.dataset.currentAddress" in script
    assert "rawValue.match(/^screen:([^\\s]+)(?:\\s+action:.+)?$/i)" in script
    assert "screen:${screenKey} action:${action.key}" in script
    assert "function loadStoredProgress" in script
    assert "function persistProgress" in script
    assert "progressStorageKey" in script
    assert "sessionStorage" in script
    assert "function actionVerbLabel" in script
    assert "function actionRoleLabel" in script
    assert "function actionMetaLabel" in script
    assert 'valueType === "json" || valueType === "object"' in script
    assert "function actionMatchesFilter" in script
    assert "function focusActionFilter" in script
    assert "data-action-filter" in script
    assert "data-clear-action-filter" in script
    assert "筛选当前任务" in script
    assert "没有匹配任务" in script
    assert "F9" in script
    assert 'grid.classList.remove("is-dashboard")' in script
    assert "可执行操作" in script
    assert "支撑检查" in script
    assert "条件查询" in script
    assert (
        "${escapeHtml(riskLabel(action.risk))} / ${escapeHtml(viewLabel(action.view_type))}"
        not in script
    )
    assert "confirmation_required" in script
    assert "data-confirm-action" in script
    assert "window.__AGOMTUI_RUNTIME__" in script
    assert "function showMissingFieldsPrompt" in script
    assert "const promptAction = result.action || currentAction(actionKey)" in script
    assert "renderField(promptAction" in script
    assert "coerceFieldValue(field, input.value, input.checked)" in script
    assert 'form.querySelector("select, input, textarea")?.focus()' in script
    assert "function showPasswordChallenge" in script
    assert "requestBody.confirmation" in script
    assert "requestBody.reauth" in script
    assert "data-action-ui-key" in script
    assert "data-action-key=" not in script
    assert "function actionUiKey" in script
    assert "function actionRefFromForm" in script
    assert "data-workflow-target" in script
    assert "function renderWorkflowStrip" in script
    assert "function loadWorkflowStep" in script
    assert "function businessContextSections" in script
    assert "function setWorkspaceViewKind(kind)" in script
    assert "grid.dataset.viewKind = String(kind);" in script
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
    assert "function applySelectedRowToActionForm" in script
    assert "function actionCanFillFromRow" in script
    assert "function refreshRowFillButtons" in script
    assert "button.disabled = !enabled" in script
    assert (
        "applySelectedRowToActionForm(form, { onlyIfEmpty: true, silent: true, focus: false });"
        in script
    )
    assert "function triggerActionForm(form)" in script
    assert "state.lastFormTriggerRef" in script
    assert 'els.actions?.addEventListener("submit", (event) => {' in script
    assert 'els.actions?.addEventListener("click", (event) => {' in script
    assert "function bindRenderedActionForms()" in script
    assert 'form.addEventListener("submit", (event) => {' in script
    assert 'actionButton?.addEventListener("click", (event) => {' in script
    assert 'fillButton?.addEventListener("click", (event) => {' in script
    assert "event.stopPropagation();" in script
    assert "scroll-margin-top: 52px;" in css
    assert "scroll-padding-top: 52px;" in css
    assert "function formFieldElement" in script
    assert "function actionResourceBase" in script
    assert "function rowContextWithSource" in script
    assert "function actionCompatibleWithRowSource" in script
    assert "__tui_source_resource_base" in script
    assert 'if (!["pk", "id"].includes(key)) {' in script
    assert (
        'const dynamicSegments = new Set(["pk", "id", "int", "str", "uuid", "slug", "path", "bool", "float", "decimal", "date", "datetime"]);'
        in script
    )
    assert 'if (segments[0] === "auto" || segments[0] === "param") {' in script
    assert 'if (segments[0] === "api" && segments[2] === "api") {' in script
    assert "segments = segments.slice(3);" in script
    assert "return rowResourceBase === targetResourceBase;" in script
    assert "form.elements.namedItem" in script
    assert "function rowFieldCandidates" in script
    assert "const builtInFieldAliases" in script
    assert "function fieldAliasRegistry" in script
    assert "field.semantic" in script
    assert "field.aliases" in script
    assert (
        'from_code: ["from_code", "from_currency_code", "from_currency", "base_currency_code", "base_currency", "code"]'
        in script
    )
    assert (
        'to_code: ["to_code", "to_currency_code", "to_currency", "target_currency_code", "target_currency", "quote_currency_code", "quote_currency"]'
        in script
    )
    assert 'report_id: ["report_id", "report.id"]' in script
    assert 'validation_id: ["validation_id", "validation.id"]' in script
    assert 'summary_id: ["summary_id", "summary.id"]' in script
    assert 'request_id: ["request_id", "request.id"]' in script
    assert 'asset_class: ["asset_class", "code", "category", "name"]' in script
    assert "const rawKey = `__raw_${key}`" in script
    assert 'if (key.startsWith("__")) {' in script
    assert "function actionsAvailableForRow" in script
    assert "function paramsFromRowForAction" in script
    assert "function runInspectorAction" in script
    assert "function inspectorFlowRows(result)" in script
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
    assert '<button class="tui-action-button" type="button">' in script
    assert 'data-action-ui-key="${escapeHtml(actionUiKey(action))}" novalidate' in script
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
    assert "rowsTitle" in script
    assert "完整业务明细已在中间主面板显示。右栏不再重复渲染同一对象。" in script
    assert "结果说明已在中间主面板显示。右栏保留流程导航、业务目标与后续动作。" in script
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


def test_tui_workbench_today_overview_regime_and_alpha_colors_are_column_safe():
    script = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "js", "tui-workbench.js")
        .read_text(encoding="utf-8")
    )

    assert (
        '["current_regime", "dominant_regime", "regime", "regime_name", "state", "name"]' in script
    )
    assert "cellClass(cell, headers[cellIndex])" in script
    assert '["标的", "代码", "名称", "股票", "资产", "证券"]' in script
    assert 'text.includes("观察") || /(进行中|运行中|处理中|同步中|排队中)/.test(text)' in script
    assert 'text.includes("观察") || text.includes("中")' not in script
    assert 'text.includes("-") || text.includes("暂停")' not in script


def test_tui_workbench_javascript_supports_limit_offset_pagination():
    script = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "js", "tui-workbench.js")
        .read_text(encoding="utf-8")
    )

    assert 'pagerMode === "limit_offset" ? "offset" : pagerMode' in script
    assert (
        'const mode = pagination.mode || (pagerMode === "limit_offset" ? "offset" : pagerMode) || inferPaginationMode(action);'
        in script
    )
    assert "const nextOffset = Math.max(0, current + (delta * limit));" in script
    assert (
        "return limitParam ? { [offsetParam]: nextOffset, [limitParam]: limit } : { [offsetParam]: nextOffset };"
        in script
    )


def test_tui_workbench_javascript_supports_image_and_file_runtime_contracts():
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

    assert '"image"' in script
    assert "function renderImage(viewModel)" in script
    assert "function renderImageMarkup(viewModel" in script
    assert "function showImagePreview(trigger)" in script
    assert "data-image-preview" in script
    assert 'input_type === "file"' in script
    assert "function readTextFile(file)" in script
    assert ".tui-image-view" in css
    assert ".tui-image-lightbox" in css


def test_tui_workbench_preserves_selected_row_context_for_follow_up_actions():
    script = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "js", "tui-workbench.js")
        .read_text(encoding="utf-8")
    )

    assert "selectedRowContext: null" in script
    assert "function selectedRowForActions()" in script
    assert 'const byName = typeof form.elements.namedItem === "function"' in script
    assert "const row = rowContextWithSource(state.visibleRows[state.selectedRowIndex]);" in script
    assert 'if (state.currentViewModel && state.currentViewModel.kind === "datagrid") {' in script
    assert "return state.selectedRowContext;" in script
    assert "resetGridState({ preserveRowContext: true });" in script
    assert (
        "state.selectedRowContext = rowContextWithSource(rows[state.selectedRowIndex]);" in script
    )
    assert "state.selectedRowContext = rowContextWithSource(row);" in script
    assert "if (rows.length) {" in script
    assert "} else {" in script
    assert "const rowContext = rowContextWithSource(row);" in script
    assert "暂无可显示数据" in script
    assert "页 -/- | 0 行" in script
    assert "function groupActions" in script
    assert "tui-action-group-title" in script
    assert "function isAdvancedAction" in script
    assert "function actionTier" in script
    assert "function dashboardTargetScreen" in script
    assert 'return String(panel.target_screen || panel.screen_key || "");' in script
    assert '"account-list": "execution.accounts"' not in script
    assert '"account-positions": "execution.accounts"' not in script
    assert 'positions: "execution.accounts"' not in script
    assert "function dashboardLayout(panels)" in script
    assert "function dashboardAreaTemplate(areas, columns)" in script
    assert "data-toggle-support" in script
    assert "data-toggle-advanced" in script
    assert "data-dashboard-target" in script
    assert "data-dashboard-action" in script
    assert "function activateDashboardPanel(targetScreen, actionKey)" in script
    assert "if (normalizedTarget && normalizedTarget !== currentScreenKey)" in script
    assert 'runAction(normalizedActionKey, null, { params: {} });' in script
    assert "支撑检查已显示" in script
    assert "高级查询已显示" in script
    assert "主流程" in script


def test_tui_workbench_limits_generic_pk_fill_to_matching_resource_source():
    script = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "js", "tui-workbench.js")
        .read_text(encoding="utf-8")
    )

    assert (
        'const rowResourceBase = String(row && row.__tui_source_resource_base ? row.__tui_source_resource_base : "");'
        in script
    )
    assert "const targetResourceBase = actionResourceBase(action && action.key);" in script
    assert "return rowResourceBase === targetResourceBase;" in script
    assert (
        "return fields.some((field) => rowValueForField(row, field.key, action) !== undefined);"
        in script
    )
    assert "const value = rowValueForField(row, field.key, action);" in script
    assert "const params = paramsFromRowForAction(row, action);" in script
    assert (
        'if (element.type !== "checkbox" && String(element.value || "").trim() !== "") {' in script
    )


def test_tui_workbench_normalizes_generated_and_hand_authored_action_keys_for_row_source_match():
    script = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "js", "tui-workbench.js")
        .read_text(encoding="utf-8")
    )

    assert 'if (segments[0] === "auto" || segments[0] === "param") {' in script
    assert 'if (segments[0] === "api" && segments[2] === "api") {' in script
    assert "segments = segments.slice(3);" in script
    assert 'return collected.join(".");' in script


def test_tui_workbench_preserves_row_context_for_empty_server_datagrids_but_not_local_filter_misses():
    script = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("static", "js", "tui-workbench.js")
        .read_text(encoding="utf-8")
    )

    assert "if (rows.length) {" in script
    assert (
        "state.selectedRowContext = rowContextWithSource(rows[state.selectedRowIndex]);" in script
    )
    assert "} else {" in script
    assert "state.selectedRowContext = null;" in script


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
    assert "border: 1px dashed var(--tui-border-dim);" in css
    assert "box-shadow: inset 0 0 0 1px var(--tui-accent);" in css
    assert ".tui-system-location input" in css
    assert ".tui-system-location input:focus" in css
    assert "margin: 6px 8px 0 32px" in css
    assert ".tui-empty-guidance" in css
    assert ".tui-inspector-actions" in css
    assert '.tui-workspace-grid[data-view-kind="detail"]' in css
    assert '.tui-workspace-grid[data-view-kind="message"]' in css
    assert (
        "--tui-inspector-width: var(--tui-inspector-user-width, var(--tui-inspector-default-width));"
        in css
    )
    assert "--tui-inspector-default-width: minmax(252px, 0.92fr);" in css
    assert "--tui-inspector-default-width: minmax(280px, 1.04fr);" in css
    assert (
        "grid-template-columns: minmax(208px, 0.7fr) minmax(360px, 1.38fr) var(--tui-inspector-width);"
        in css
    )
    assert (
        "grid-template-columns: minmax(208px, 0.66fr) minmax(320px, 1.16fr) var(--tui-inspector-width);"
        in css
    )
    assert "min-inline-size: 24ch;" in css
    assert "word-break: keep-all;" in css
    assert "overflow-wrap: break-word;" in css
    assert "data-inspector-action" not in css
    assert ".tui-decision-actions" in css
    assert "position: sticky" in css
    assert ".tui-dash-panel:focus" in css


def test_tui_workbench_script_consumes_user_experience_and_semantic_detail_contract():
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

    assert "function screenUserExperience(screen)" in script
    assert "function userExperienceSections(screen)" in script
    assert "function screenEmptyStateHint(screen, fallback = \"\")" in script
    assert "function renderSemanticDetailView(viewModel, semantics, options = {})" in script
    assert "function renderSemanticCopyFields(fields)" in script
    assert "function renderSemanticPromptFields(fields)" in script
    assert "function bindCopyButtons(root = document)" in script
    assert "function fieldLooksLikePrompt(field)" in script
    assert "function fieldLooksLikeCopyable(field)" in script
    assert "event.stopPropagation();" in script
    assert "navigator.clipboard.writeText" in script
    assert "loadScreen(normalizedKey, { suppressAutoAction: true })" in script
    assert "button.addEventListener(\"click\", () => loadScreen(button.dataset.screenKey));" in script
    assert "endpoint_list: \"地址\"" in script
    assert "multiline_prompt: \"提示词\"" in script
    assert "data-panel-priority" in script
    assert "data-panel-semantic" in script
    assert "entryState.empty_copy || screenEmptyStateHint(" in script
    assert ".tui-dash-panel[data-panel-priority=\"p0\"]" in css
    assert ".tui-panel-priority" in css
    assert ".tui-status-hero" in css
    assert ".tui-copy-block" in css
    assert ".tui-copy-action" in css


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
        action for action in payload["actions"] if action["key"] == "terminal.agent_chat"
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

    strategy_response = client.get("/api/tui/screens/macro-regime.strategy/")
    strategy_payload = strategy_response.json()
    strategy_labels = {action["label"] for action in strategy_payload["actions"]}
    assert "策略执行记录（按策略）" in strategy_labels
    assert "By" not in str(strategy_payload)

    portfolio_response = client.get("/api/tui/screens/execution.portfolio-performance/")
    portfolio_payload = portfolio_response.json()
    portfolio_labels = {action["label"] for action in portfolio_payload["actions"]}
    assert "策略绑定（按组合）" in portfolio_labels

    runtime_response = client.get("/api/tui/screens/ai-ops.agent-runtime/")
    runtime_payload = runtime_response.json()
    runtime_labels = {action["label"] for action in runtime_payload["actions"]}
    assert "AI 任务入口" in runtime_labels
    assert "任务详情" in runtime_labels
    assert "任务产物" in runtime_labels
    assert "任务时间线" in runtime_labels
    assert "Agent Runtime" not in str(runtime_payload)


def test_tui_realtime_monitor_exposes_one_owner_workflow(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/realtime-monitor.alerts/")

    assert response.status_code == 200
    payload = response.json()
    screen = payload["screen"]
    actions = {action["key"]: action for action in payload["actions"]}
    panels = {panel["key"]: panel for panel in screen["dashboard_panels"]}
    assert payload["module"]["key"] == "realtime-monitor"
    assert screen["default_action_key"] == "realtime-monitor.list-alerts"
    assert screen["user_experience"]["primary_task"]
    assert screen["user_experience"]["primary_outcome"]
    assert panels["active-alerts"]["user_priority"] == "p0"
    assert panels["active-alerts"]["presentation_semantic"] == "primary_list"
    assert {
        "realtime-monitor.list-alerts",
        "realtime-monitor.create-alert",
        "realtime-monitor.update-alert",
        "realtime-monitor.delete-alert",
        "realtime-monitor.list-subscriptions",
        "realtime-monitor.subscribe",
        "realtime-monitor.unsubscribe",
    } <= set(actions)
    assert actions["realtime-monitor.update-alert"]["confirmation_required"] is True
    assert actions["realtime-monitor.delete-alert"]["fields"][0]["binding"] == "path"
    user_copy = " ".join(
        [screen["label"], screen["summary"]]
        + [action["label"] for action in actions.values()]
        + [action.get("description", "") for action in actions.values()]
    )
    assert "/api/" not in user_copy
    assert "<int:" not in user_copy


def test_tui_event_replay_actions_are_staff_only(client, tui_user):
    client.force_login(tui_user)
    ordinary = client.get("/api/tui/screens/execution.events/").json()
    ordinary_keys = {action["key"] for action in ordinary["actions"]}
    assert "execution.preview-event-replay" not in ordinary_keys
    assert "execution.commit-event-replay" not in ordinary_keys

    tui_user.is_staff = True
    tui_user.save(update_fields=["is_staff"])
    staff = client.get("/api/tui/screens/execution.events/").json()
    staff_actions = {action["key"]: action for action in staff["actions"]}
    assert staff_actions["execution.preview-event-replay"]["risk"] == "admin"
    assert staff_actions["execution.commit-event-replay"]["confirmation_required"] is True
    user_copy = " ".join(
        [staff_actions["execution.preview-event-replay"]["label"]]
        + [staff_actions["execution.preview-event-replay"]["description"]]
        + [staff_actions["execution.commit-event-replay"]["label"]]
        + [staff_actions["execution.commit-event-replay"]["description"]]
    )
    assert "/api/" not in user_copy


def test_tui_risk_center_screen_exposes_read_and_confirmed_write_actions(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/risk-center.overview/")

    assert response.status_code == 200
    payload = response.json()
    action_by_key = {action["key"]: action for action in payload["actions"]}
    assert payload["module"]["key"] == "risk-center"
    assert payload["screen"]["label"] == "集中风控中心"
    assert payload["screen"]["default_action_key"] == "risk-center.effective-policy"
    assert payload["screen"]["entry_state"]["mode"] == "parameter_gate"
    assert payload["screen"]["entry_state"]["field_key"] == "account_id"
    assert action_by_key["risk-center.effective-policy"]["risk"] == "read"
    assert action_by_key["risk-center.effective-policy"]["fields"][0]["key"] == "account_id"
    assert action_by_key["risk-center.pre-trade-check"]["risk"] == "read"
    assert {field["key"] for field in action_by_key["risk-center.pre-trade-check"]["fields"]} >= {
        "account_id",
        "symbol",
        "quantity",
        "price",
        "account_equity",
    }
    assert action_by_key["risk-center.post-investment-check"]["risk"] == "read"
    assert {
        field["key"] for field in action_by_key["risk-center.post-investment-check"]["fields"]
    } >= {
        "account_id",
        "account_equity",
        "positions",
    }
    assert action_by_key["risk-center.daily-report"]["risk"] == "read"
    assert {field["key"] for field in action_by_key["risk-center.daily-report"]["fields"]} >= {
        "account_id",
        "report_date",
        "positions",
    }
    assert action_by_key["risk-center.daily-report-history"]["risk"] == "read"
    assert {
        field["key"] for field in action_by_key["risk-center.daily-report-history"]["fields"]
    } >= {
        "account_id",
        "report_date",
        "start_date",
        "end_date",
    }
    assert action_by_key["risk-center.update-floor"]["confirmation_required"] is True
    assert action_by_key["risk-center.create-exception"]["risk"] == "write"


def test_tui_auto_advisor_screen_defaults_to_account_selector(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/command-center.auto-advisor/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["default_action_key"] == "advisor.today_sheet"
    assert payload["screen"]["entry_state"]["mode"] == "parameter_gate"
    assert payload["screen"]["entry_state"]["field_key"] == "account_id"
    action_by_key = {action["key"]: action for action in payload["actions"]}
    assert "advisor.account_selector" in action_by_key
    assert "advisor.factor_breakdown" in action_by_key
    assert action_by_key["advisor.account_selector"]["fields"] == []
    assert action_by_key["advisor.today_sheet"]["fields"][0]["key"] == "account_id"
    panels = payload["screen"]["dashboard_panels"]
    assert len(panels) == 1
    assert panels[0]["action_key"] == "advisor.account_selector"


def test_tui_operation_fields_use_business_labels(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/research.alpha/")

    assert response.status_code == 200
    payload = response.json()
    action = next(
        action for action in payload["actions"] if action["key"] == "alpha.inference.trigger_batch"
    )
    fields = {field["key"]: field for field in action["fields"]}

    assert fields["top_n"]["label"] == "候选数量"


def test_tui_alpha_scores_exposes_date_control_and_pagination(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/research.alpha/")

    assert response.status_code == 200
    payload = response.json()
    action = next(action for action in payload["actions"] if action["key"] == "alpha.scores")
    fields = {field["key"]: field for field in action["fields"]}

    assert fields["trade_date"]["input_type"] == "date"
    assert fields["trade_date"]["value_type"] == "date"
    assert fields["trade_date"]["default"] == timezone.localdate().isoformat()
    assert fields["limit"]["input_type"] == "hidden"
    assert fields["offset"]["input_type"] == "hidden"


@pytest.mark.django_db
def test_tui_metadata_repository_patches_alpha_scores_for_tui_pagination():
    loaded = PublishedTuiMetadataRepository().load_published()

    action = next(action for action in loaded["actions"] if action["key"] == "alpha.scores")

    assert action["pagination"] == {
        "mode": "offset",
        "offset_param": "offset",
        "limit_param": "limit",
    }
    assert action["view_model"]["rows_path"] == "stocks"
    assert action["view_model"]["total_path"] == "total"


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
        payload["stats"]["actions"] + payload["stats"]["hidden_by_risk"]
        == payload["stats"]["published_actions"]
    )
    assert (
        payload["stats"]["smoke_ok"]
        + payload["stats"].get("smoke_needs_input", 0)
        + payload["stats"].get("smoke_error", 0)
        == payload["stats"]["smoke_total"]
    )
    assert payload["stats"]["business_promoted_actions"] >= 250
    assert payload["stats"]["approved_operation_actions"] >= 6
    assert any(
        screen["key"] == "macro-regime.overview"
        for group in payload["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    )


def test_tui_catalog_hides_admin_only_config_center_from_regular_user(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    screen_keys = {
        screen["key"]
        for group in payload["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    }

    assert "api-library.config-center" not in screen_keys


def test_tui_catalog_shows_admin_only_config_center_to_admin_user(client, tui_admin_user):
    client.force_login(tui_admin_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    screens = {
        screen["key"]: screen
        for group in payload["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    }

    assert "api-library.config-center" in screens
    assert (
        screens["api-library.config-center"]["default_action_key"]
        == "operator.governance.config_center_summary"
    )


def test_tui_catalog_hides_admin_only_mcp_center_from_regular_user(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    modules = {
        module["key"]: module
        for group in payload["groups"]
        for module in group["modules"]
    }
    screen_keys = {
        screen["key"] for module in modules.values() for screen in module["screens"]
    }

    assert "capability-router.mcp-center" not in screen_keys
    assert "capability-router.admin-access" not in screen_keys
    assert "capability-router.gateway" not in screen_keys
    assert "capability-router.self-service" in screen_keys
    assert [screen["key"] for screen in modules["mcp-access"]["screens"]] == [
        "capability-router.self-service"
    ]
    assert "mcp-governance" not in modules
    assert "capability-router-debug" not in modules


def test_tui_catalog_shows_admin_only_mcp_center_to_admin_user(client, tui_admin_user):
    client.force_login(tui_admin_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    modules = {
        module["key"]: module
        for group in payload["groups"]
        for module in group["modules"]
    }
    screens = {
        screen["key"]: screen
        for module in modules.values()
        for screen in module["screens"]
    }

    assert "capability-router.mcp-center" in screens
    assert "capability-router.admin-access" in screens
    assert "capability-router.self-service" in screens
    assert "capability-router.gateway" in screens
    assert [screen["key"] for screen in modules["mcp-access"]["screens"]] == [
        "capability-router.self-service"
    ]
    assert [screen["key"] for screen in modules["mcp-governance"]["screens"]] == [
        "capability-router.mcp-center",
        "capability-router.admin-access",
    ]
    assert [screen["key"] for screen in modules["capability-router-debug"]["screens"]] == [
        "capability-router.gateway"
    ]
    assert screens["capability-router.mcp-center"]["default_action_key"] == (
        "capability-router.mcp-tools-stats"
    )
    assert not screens["capability-router.mcp-center"]["workflow"].get("previous")
    assert not screens["capability-router.self-service"]["workflow"].get("step")


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
        "execution.trading-ledger": "execution.trading-ledger.account-selector",
        "execution.portfolio-performance": "auto.api.get.api.account.portfolios",
        "execution.account-settings": "operator.governance.account_settings_summary",
        "macro-regime.strategy": "auto.api.get.api.strategy.strategies",
        "macro-regime.rotation": "auto.api.get.api.rotation.assets",
        "macro-regime.risk-controls": "auto.api.get.api.decision-rhythm.summary",
        "macro-regime.beta-gate": "auto.api.get.api.beta-gate.decisions",
        "macro-regime.hedge": "auto.api.get.api.hedge.snapshots",
        "research.asset-lab": "auto.api.get.api.asset-analysis.pool-summary",
        "research.fund-sector": "auto.api.get.api.fund.rank",
        "research.screening-sentiment": "auto.api.get.api.filter.indicators",
        "ai-ops.providers": "operator.governance.ai_provider_summary",
        "ai-ops.prompt-workbench": "auto.api.get.api.prompt.templates",
        "api-library.data-center": "operator.governance.data_center_summary",
        "api-library.market-thermometer": "auto.api.get.api.data-center.market-thermometer.history",
        "execution.events": "auto.api.get.api.events.query",
        "execution.share": "auto.api.get.api.share.links",
        "research.alpha-triggers": "auto.api.get.api.alpha-triggers.candidates.actionable",
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
    assert payload["screen"]["label"] == "账户清单与当前持仓"
    actions = payload["actions"]
    action_by_key = {action["key"]: action for action in actions}
    groups = {action["task_group"] for action in actions}
    assert {"01 账户清单", "02 当前持仓", "03 单账户持仓"} <= groups
    assert "auto.api.get.api.account.accounts" in action_by_key
    assert "auto.api.get.api.account.positions" in action_by_key
    assert "param.api.get.api.account.accounts.int.account_id.positions" in action_by_key
    assert all(isinstance(action["sequence"], int) for action in actions)
    assert all(not action["label"].startswith("Get ") for action in actions)
    assert all("endpoint" not in action for action in actions)
    assert all("method" not in action for action in actions)
    assert all("source" not in action for action in actions)
    assert all("view_model" not in action for action in actions)
    assert all("raw_debug" not in action for action in actions)


def test_tui_actions_expose_business_task_tiers(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.accounts/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"]: action for action in payload["actions"]}
    assert actions["auto.api.get.api.account.positions"]["task_tier"] == "primary"
    assert (
        actions["param.api.get.api.account.accounts.int.account_id.positions"]["task_tier"]
        == "primary"
    )
    assert all(action["task_group"] for action in payload["actions"])
    assert all(action["task_tier"] for action in payload["actions"])

    settings_response = client.get("/api/tui/screens/execution.account-settings/")
    settings_payload = settings_response.json()
    settings_actions = {action["key"]: action for action in settings_payload["actions"]}
    assert settings_actions["auto.api.get.api.account.assets"]["task_tier"] == "support"


def test_tui_data_center_screen_exposes_selector_reads(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/api-library.data-center/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"]: action for action in payload["actions"]}
    assert "auto.api.get.api.data-center" not in actions
    assert actions["auto.api.get.api.data-center.indicators"]["task_tier"] == "support"
    assert actions["auto.api.get.api.data-center.indicators"]["task_group"] == "02 指标目录"
    assert actions["auto.api.get.api.data-center.providers"]["task_group"] == "04 服务商"
    assert actions["auto.api.get.api.data-center.publishers"]["task_group"] == "05 发布机构"


def test_tui_account_settings_screen_defaults_to_row_backed_selector(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.account-settings/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["default_action_key"] == "operator.governance.account_settings_summary"


def test_tui_trading_ledger_screen_exposes_account_selector_default(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.trading-ledger/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"]: action for action in payload["actions"]}
    assert payload["screen"]["default_action_key"] == "execution.trading-ledger.account-selector"
    assert actions["execution.trading-ledger.account-selector"]["task_group"] == "02 账户选择"


def test_tui_share_screen_defaults_to_non_empty_overview(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.share/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["default_action_key"] == "auto.api.get.api.share.links"


def test_tui_agent_runtime_and_alpha_trigger_defaults_prefer_non_empty_entrypoints(
    client, tui_user
):
    client.force_login(tui_user)

    runtime_response = client.get("/api/tui/screens/ai-ops.agent-runtime/")
    runtime_payload = runtime_response.json()
    assert (
        runtime_payload["screen"]["default_action_key"]
        == "operator.governance.agent_runtime_summary"
    )

    alpha_response = client.get("/api/tui/screens/research.alpha-triggers/")
    alpha_payload = alpha_response.json()
    assert (
        alpha_payload["screen"]["default_action_key"]
        == "auto.api.get.api.alpha-triggers.candidates.actionable"
    )

    providers_response = client.get("/api/tui/screens/ai-ops.providers/")
    providers_payload = providers_response.json()
    assert (
        providers_payload["screen"]["default_action_key"]
        == "operator.governance.ai_provider_summary"
    )


def test_tui_providers_screen_hides_personal_provider_detail_without_rows(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/ai-ops.providers/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "param.api.get.api.ai.me.providers.pk" not in actions


def test_tui_providers_screen_shows_personal_provider_detail_when_user_has_provider(
    client, tui_user
):
    AIProviderConfig.objects.create(
        name="tui-personal-provider",
        scope="user",
        owner_user=tui_user,
        provider_type="deepseek",
        is_active=True,
        priority=1,
        base_url="https://api.deepseek.com/v1",
        api_key="dummy-key",
        default_model="deepseek-chat",
    )
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/ai-ops.providers/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "param.api.get.api.ai.me.providers.pk" in actions


def test_tui_my_providers_screen_exposes_self_service_actions(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/ai-ops.my-providers/")

    assert response.status_code == 200
    payload = response.json()
    action_keys = {action["key"] for action in payload["actions"]}
    assert payload["screen"]["default_action_key"] == "ai-ops.list-my-providers"
    assert "ai-ops.create-my-provider" in action_keys
    assert "ai-ops.update-my-provider" in action_keys
    assert "ai-ops.toggle-my-provider" in action_keys
    assert "ai-ops.delete-my-provider" in action_keys
    assert "ai-ops.my-quota-current" in action_keys
    assert "ai-ops.my-ai-logs" in action_keys


def test_tui_catalog_hides_admin_ai_management_screens_from_regular_user(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    screen_keys = {
        screen["key"]
        for group in payload["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    }
    assert "ai-ops.system-providers" not in screen_keys
    assert "ai-ops.user-quotas" not in screen_keys


def test_tui_catalog_shows_admin_ai_management_screens_to_admin_user(client, tui_admin_user):
    client.force_login(tui_admin_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    screen_keys = {
        screen["key"]
        for group in payload["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    }
    assert "ai-ops.system-providers" in screen_keys
    assert "ai-ops.user-quotas" in screen_keys


def test_tui_dashboard_screen_hides_alpha_history_detail_without_history_rows(
    client,
    tui_user,
    monkeypatch,
):
    monkeypatch.setattr(tui_workbench_module, "has_dashboard_alpha_history", lambda _user: False)
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/command-center.dashboard/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "param.api.get.api.dashboard.alpha.history.int.run_id" not in actions


def test_tui_dashboard_screen_shows_alpha_history_detail_with_history_rows(
    client,
    tui_user,
    monkeypatch,
):
    monkeypatch.setattr(tui_workbench_module, "has_dashboard_alpha_history", lambda _user: True)
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/command-center.dashboard/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "param.api.get.api.dashboard.alpha.history.int.run_id" in actions


def test_tui_risk_controls_screen_hides_conditional_queries_without_rows(
    client,
    tui_user,
    monkeypatch,
):
    monkeypatch.setattr(tui_workbench_module, "has_decision_quotas", lambda: False)
    monkeypatch.setattr(tui_workbench_module, "has_active_cooldowns", lambda: False)
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/macro-regime.risk-controls/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "auto.api.get.api.decision-rhythm.quotas.by-period" not in actions
    assert "auto.api.get.api.decision-rhythm.cooldowns.remaining-hours" not in actions


def test_tui_risk_controls_screen_shows_conditional_queries_with_rows(
    client,
    tui_user,
    monkeypatch,
):
    monkeypatch.setattr(tui_workbench_module, "has_decision_quotas", lambda: True)
    monkeypatch.setattr(tui_workbench_module, "has_active_cooldowns", lambda: True)
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/macro-regime.risk-controls/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "auto.api.get.api.decision-rhythm.quotas.by-period" in actions
    assert "auto.api.get.api.decision-rhythm.cooldowns.remaining-hours" in actions


def test_tui_runtime_screen_hides_system_statistics_without_task_rows(
    client,
    tui_user,
    monkeypatch,
):
    monkeypatch.setattr(tui_workbench_module, "has_recent_task_failures", lambda: False)
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/api-library.runtime/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "auto.api.get.api.system.statistics" not in actions


def test_tui_runtime_screen_shows_system_statistics_with_task_rows(
    client,
    tui_user,
    monkeypatch,
):
    monkeypatch.setattr(tui_workbench_module, "has_recent_task_failures", lambda: True)
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/api-library.runtime/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "auto.api.get.api.system.statistics" in actions


def test_tui_config_center_screen_hides_training_run_detail_without_rows(
    client,
    tui_admin_user,
    monkeypatch,
):
    monkeypatch.setattr(tui_workbench_module, "has_qlib_training_runs", lambda: False)
    client.force_login(tui_admin_user)

    response = client.get("/api/tui/screens/api-library.config-center/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "config_center.training_run_detail" not in actions


def test_tui_config_center_screen_shows_training_run_detail_with_rows(
    client,
    tui_admin_user,
    monkeypatch,
):
    monkeypatch.setattr(tui_workbench_module, "has_qlib_training_runs", lambda: True)
    client.force_login(tui_admin_user)

    response = client.get("/api/tui/screens/api-library.config-center/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "config_center.training_run_detail" in actions


def test_tui_config_center_screen_exposes_alpha_universe_actions(client, tui_admin_user):
    client.force_login(tui_admin_user)

    response = client.get("/api/tui/screens/api-library.config-center/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"] for action in payload["actions"]}
    assert "config_center.alpha_universes" in actions
    assert "config_center.alpha_universe_members" in actions
    assert "config_center.alpha_universe_save" in actions


def test_tui_rotation_screen_defaults_to_row_backed_assets(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/macro-regime.rotation/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["default_action_key"] == "auto.api.get.api.rotation.assets"


def test_tui_hedge_screen_defaults_to_row_backed_snapshots(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/macro-regime.hedge/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["default_action_key"] == "auto.api.get.api.hedge.snapshots"


def test_tui_screens_expose_daily_workflow_navigation(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.accounts/")

    assert response.status_code == 200
    workflow = response.json()["screen"]["workflow"]
    assert workflow["name"] == "每日投研流程"
    assert workflow["label"] == "账户组合"
    assert workflow["previous"]["key"] == "research.asset-lab"
    assert workflow["next"]["key"] == "macro-regime.strategy"


@pytest.mark.parametrize(
    ("screen_key", "step", "total", "previous_key", "next_key", "default_action_key"),
    [
        (
            "api-library.runtime",
            1,
            6,
            None,
            "api-library.data-center",
            "operator.governance.runtime_summary",
        ),
        (
            "api-library.data-center",
            2,
            6,
            "api-library.runtime",
            "ai-ops.providers",
            "operator.governance.data_center_summary",
        ),
        (
            "ai-ops.providers",
            3,
            6,
            "api-library.data-center",
            "ai-ops.agent-runtime",
            "operator.governance.ai_provider_summary",
        ),
        (
            "ai-ops.agent-runtime",
            4,
            6,
            "ai-ops.providers",
            "execution.account-settings",
            "operator.governance.agent_runtime_summary",
        ),
        (
            "execution.account-settings",
            5,
            6,
            "ai-ops.agent-runtime",
            "api-library.config-center",
            "operator.governance.account_settings_summary",
        ),
        (
            "api-library.config-center",
            6,
            6,
            "execution.account-settings",
            None,
            "operator.governance.config_center_summary",
        ),
    ],
)
def test_tui_governance_screens_expose_operator_workflow_contract(
    client,
    tui_admin_user,
    screen_key,
    step,
    total,
    previous_key,
    next_key,
    default_action_key,
):
    client.force_login(tui_admin_user)

    response = client.get(f"/api/tui/screens/{screen_key}/")

    assert response.status_code == 200
    payload = response.json()
    screen = payload["screen"]
    workflow = screen["workflow"]
    assert screen["default_action_key"] == default_action_key
    assert workflow["name"] == "系统治理流程"
    assert workflow["step"] == step
    assert workflow["total"] == total
    assert screen["business_context"]["objective"]
    assert screen["business_context"]["decision_output"]
    assert screen["business_context"]["checkpoints"]
    assert workflow.get("previous", {}).get("key") == previous_key
    assert workflow.get("next", {}).get("key") == next_key


def test_tui_governance_flow_keeps_config_center_admin_only(client, tui_user, tui_admin_user):
    client.force_login(tui_user)
    regular_catalog = client.get("/api/tui/catalog/").json()
    regular_screen_keys = {
        screen["key"]
        for group in regular_catalog["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    }
    assert "api-library.config-center" not in regular_screen_keys

    client.force_login(tui_admin_user)
    admin_catalog = client.get("/api/tui/catalog/").json()
    admin_screens = {
        screen["key"]: screen
        for group in admin_catalog["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    }
    assert admin_screens["api-library.config-center"]["default_action_key"] == (
        "operator.governance.config_center_summary"
    )


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


def test_tui_decision_flow_publishes_confirmed_daily_workflow_actions(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/command-center.decision-flow/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"]: action for action in payload["actions"]}
    expected_write_actions = {
        "decision.workspace.recommendation_action",
        "decision.workspace.plan_generate",
        "decision.workspace.plan_update",
        "decision.execute.preview",
        "decision.execute.approve",
        "decision.execute.reject",
    }
    assert {
        "auto.api.get.api.decision.workspace.recommendations",
        "auto.api.get.api.decision.workspace.conflicts",
        "param.api.get.api.decision.workspace.plans.str.plan_id",
        *expected_write_actions,
    } - set(actions) == {"param.api.get.api.decision.workspace.plans.str.plan_id"}

    for action_key in expected_write_actions:
        assert actions[action_key]["risk"] == "write"
        assert actions[action_key]["confirmation_required"] is True
        assert "endpoint" not in actions[action_key]
        assert "method" not in actions[action_key]
        assert "source" not in actions[action_key]
        assert "view_model" not in actions[action_key]
    assert actions["decision.execute.preview"]["fields"][0]["key"] == "plan_id"


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
    audit_log = TerminalAuditLogORM._default_manager.latest("created_at")
    assert audit_log.username == "tui_user"
    assert audit_log.mode == "tui-workbench"
    assert audit_log.result_status == "blocked"
    record = json.loads(audit_log.params_summary)
    assert record["schema_version"] == "tui-audit.v1"
    assert record["action_key"] == "data_center.market_thermometer_calculate"
    assert record["outcome"] == "blocked_confirmation_required"


def test_tui_parameterized_read_tools_are_promoted_to_user_screens(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.accounts/")

    assert response.status_code == 200
    payload = response.json()
    action = next(
        action
        for action in payload["actions"]
        if action["key"] == "param.api.get.api.account.accounts.int.account_id.positions"
    )
    assert action["task_group"] == "03 单账户持仓"
    assert action["fields"][0]["key"] == "account_id"
    assert action["fields"][0]["label"] == "账户ID"
    assert action["fields"][0]["placeholder"] in {"请输入账户ID", "请选择账户"}
    assert action["fields"][0]["required"] is True
    assert action["screen_key"] == "execution.accounts"


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


def test_tui_capability_screen_prefers_capability_key_detail_route(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/ai-ops.capabilities/")

    assert response.status_code == 200
    payload = response.json()
    actions = {action["key"]: action for action in payload["actions"]}
    assert "param.api.get.api.ai-capability.capabilities.str.capability_key" in actions
    assert "param.api.get.api.ai-capability.capabilities.pk" not in actions


def test_tui_user_screens_hide_selectorless_technical_queries(client, tui_user):
    client.force_login(tui_user)

    hidden_by_screen = {
        "command-center.dashboard": {"param.api.get.api.dashboard.position.str.asset_code"},
        "command-center.decision-flow": {
            "param.api.get.api.valuation.snapshot.str.snapshot_id",
            "param.api.get.api.decision.workspace.plans.str.plan_id",
        },
        "execution.audit": {"param.api.get.api.audit.indicator-performance.str.indicator_code"},
        "api-library.runtime": {"param.api.get.api.system.status.str.task_id"},
        "macro-regime.risk-controls": {
            "param.api.get.api.decision-rhythm.cooldowns.by-asset.asset_code",
            "param.api.get.api.decision-rhythm.requests.pk",
        },
        "macro-regime.beta-gate": {
            "param.api.get.api.beta-gate.configs.pk",
            "param.api.get.api.beta-gate.decisions.pk",
            "param.api.get.api.beta-gate.universe.pk",
        },
        "research.alpha-triggers": {
            "param.api.get.api.alpha-triggers.triggers.by-regime.regime",
            "param.api.get.api.alpha-triggers.triggers.pk",
            "param.api.get.api.alpha-triggers.candidates.pk",
        },
    }

    for screen_key, hidden_keys in hidden_by_screen.items():
        response = client.get(f"/api/tui/screens/{screen_key}/")
        assert response.status_code == 200
        actions = {action["key"] for action in response.json()["actions"]}
        for hidden_key in hidden_keys:
            assert hidden_key not in actions


def test_tui_user_screens_show_conditional_detail_actions_when_row_sources_exist(
    client,
    tui_user,
    monkeypatch,
):
    monkeypatch.setattr(tui_workbench_module, "has_active_cooldowns", lambda: True)
    monkeypatch.setattr(tui_workbench_module, "has_recent_decision_requests", lambda: True)
    monkeypatch.setattr(tui_workbench_module, "has_beta_gate_configs", lambda: True)
    monkeypatch.setattr(tui_workbench_module, "has_beta_gate_decisions", lambda: True)
    monkeypatch.setattr(tui_workbench_module, "has_beta_gate_universe_snapshots", lambda: True)
    monkeypatch.setattr(tui_workbench_module, "has_alpha_triggers", lambda: True)
    monkeypatch.setattr(tui_workbench_module, "has_alpha_candidates", lambda: True)
    client.force_login(tui_user)

    expected_by_screen = {
        "macro-regime.risk-controls": {
            "param.api.get.api.decision-rhythm.cooldowns.by-asset.asset_code",
            "param.api.get.api.decision-rhythm.requests.pk",
        },
        "macro-regime.beta-gate": {
            "param.api.get.api.beta-gate.configs.pk",
            "param.api.get.api.beta-gate.decisions.pk",
            "param.api.get.api.beta-gate.universe.pk",
        },
        "research.alpha-triggers": {
            "param.api.get.api.alpha-triggers.triggers.by-regime.regime",
            "param.api.get.api.alpha-triggers.triggers.pk",
            "param.api.get.api.alpha-triggers.candidates.pk",
        },
    }

    for screen_key, expected_keys in expected_by_screen.items():
        response = client.get(f"/api/tui/screens/{screen_key}/")
        assert response.status_code == 200
        actions = {action["key"] for action in response.json()["actions"]}
        for expected_key in expected_keys:
            assert expected_key in actions


def test_tui_account_performance_actions_are_rehomed_to_account_screen(client, tui_user):
    client.force_login(tui_user)

    accounts_response = client.get("/api/tui/screens/execution.accounts/")
    portfolio_response = client.get("/api/tui/screens/execution.portfolio-performance/")

    assert accounts_response.status_code == 200
    assert portfolio_response.status_code == 200

    account_actions = {action["key"] for action in accounts_response.json()["actions"]}
    portfolio_actions = {action["key"] for action in portfolio_response.json()["actions"]}
    moved_keys = {
        "param.api.get.api.account.accounts.int.account_id.performance",
        "param.api.get.api.account.accounts.int.account_id.performance-report",
        "param.api.get.api.account.accounts.int.account_id.valuation-snapshot",
        "param.api.get.api.account.accounts.int.account_id.valuation-timeline",
        "param.api.get.api.account.accounts.int.account_id.benchmarks",
        "param.api.get.api.account.accounts.int.account_id.equity-curve",
        "param.api.get.api.account.accounts.int.account_id.inspections",
    }

    for moved_key in moved_keys:
        assert moved_key in account_actions
        assert moved_key not in portfolio_actions


def test_tui_strategy_portfolio_queries_are_rehomed_to_portfolio_screen(client, tui_user):
    client.force_login(tui_user)

    strategy_response = client.get("/api/tui/screens/macro-regime.strategy/")
    portfolio_response = client.get("/api/tui/screens/execution.portfolio-performance/")

    assert strategy_response.status_code == 200
    assert portfolio_response.status_code == 200

    strategy_actions = {action["key"] for action in strategy_response.json()["actions"]}
    portfolio_actions = {action["key"] for action in portfolio_response.json()["actions"]}
    moved_keys = {
        "auto.api.get.api.strategy.assignments.by_portfolio",
        "auto.api.get.api.strategy.execution-logs.by_portfolio",
    }

    for moved_key in moved_keys:
        assert moved_key not in strategy_actions
        assert moved_key in portfolio_actions


def test_tui_terminal_screen_defaults_to_interactive_chat(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/ai-ops.terminal/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["label"] == "AI 交互终端"
    assert payload["screen"]["default_action_key"] == "terminal.agent_chat"
    action = next(
        action for action in payload["actions"] if action["key"] == "terminal.agent_chat"
    )
    assert action["label"] == "发送 AI 请求"
    assert action["risk"] == "ai"
    assert action["fields"][0]["key"] == "message"
    assert action["fields"][0]["label"] == "消息"


def test_tui_catalog_registers_cli_module_entry(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    modules = {module["key"]: module for group in payload["groups"] for module in group["modules"]}
    assert modules["cli"]["label"] == "AI 助手"
    assert modules["cli"]["group"] == "ops"
    assert [screen["key"] for screen in modules["cli"]["screens"]] == ["cli.terminal"]
    assert modules["cli"]["screens"][0]["default_action_key"] == "cli.agent_chat"


def test_tui_cli_screen_defaults_to_runtime_chat_entry(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/cli.terminal/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["module"]["key"] == "cli"
    assert payload["screen"]["label"] == "助手终端"
    assert payload["screen"]["default_action_key"] == "cli.agent_chat"
    action = next(action for action in payload["actions"] if action["key"] == "cli.agent_chat")
    assert action["label"] == "发送助手请求"
    assert action["risk"] == "ai"
    assert action["fields"][0]["key"] == "message"
    assert action["fields"][0]["label"] == "消息"


def test_tui_catalog_registers_capability_router_entry(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    modules = {module["key"]: module for group in payload["groups"] for module in group["modules"]}
    assert modules["mcp-access"]["label"] == "我的 MCP 接入"
    assert modules["mcp-access"]["group"] == "ops"
    assert [screen["key"] for screen in modules["mcp-access"]["screens"]] == [
        "capability-router.self-service",
    ]
    assert (
        modules["mcp-access"]["screens"][0]["default_action_key"]
        == "capability-router.mcp-self-status"
    )


def test_tui_screen_api_returns_bounded_not_found_error(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/not-published.screen/")

    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert set(payload) == {
        "error_code",
        "title",
        "detail",
        "recovery_actions",
        "trace_id",
    }
    assert payload["error_code"] == "tui_screen_not_found"
    assert payload["title"] == "页面不存在"
    assert payload["recovery_actions"] == [
        {"label": "返回首页", "screen_key": "home"}
    ]
    assert payload["trace_id"]
    assert "/api/" not in str(payload)


def test_tui_screen_api_returns_bounded_forbidden_error(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/capability-router.gateway/")

    assert response.status_code == 403
    payload = response.json()
    assert payload["error_code"] == "tui_screen_forbidden"
    assert payload["title"] == "无权访问"
    assert payload["recovery_actions"] == [
        {"label": "返回我的 MCP 接入", "screen_key": "capability-router.self-service"}
    ]
    assert payload["trace_id"]
    assert "admin" not in str(payload).lower()


def test_tui_screen_payload_exposes_registry_identity(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/capability-router.self-service/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"]
    assert payload["registry_key"] == "default"


def test_tui_bootstrap_only_falls_back_for_stale_resume_state():
    script = (Path(__file__).resolve().parents[2] / "static" / "js" / "tui-workbench.js").read_text(
        encoding="utf-8"
    )

    assert "const isResumeAttempt" in script
    assert "if (!loaded && isResumeAttempt)" in script
    assert "if (!loaded && initialScreen !== catalog.default_screen)" not in script


def test_tui_capability_router_screen_uses_unified_route_api(client, tui_admin_user):
    client.force_login(tui_admin_user)

    response = client.get("/api/tui/screens/capability-router.gateway/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["module"]["key"] == "capability-router-debug"
    assert payload["screen"]["label"] == "能力路由接入"
    action = next(
        action
        for action in payload["actions"]
        if action["key"] == "capability-router.route-message"
    )
    assert action["label"] == "测试统一路由"
    assert action["risk"] == "ai"
    assert action["fields"][0]["key"] == "message"
    assert action["fields"][1]["key"] == "entrypoint"
    assert action["fields"][2]["key"] == "context"


def test_tui_mcp_self_service_screen_exposes_status_endpoint_and_prompt_panels(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/capability-router.self-service/")

    assert response.status_code == 200
    payload = response.json()
    panels = payload["screen"]["dashboard_panels"]
    assert [panel["key"] for panel in panels] == [
        "mcp-self-status",
        "mcp-self-endpoints",
        "mcp-self-prompt-guide",
        "mcp-self-tokens",
    ]
    actions = {action["key"]: action for action in payload["actions"]}
    assert "capability-router.mcp-self-endpoints" in actions
    assert "capability-router.mcp-self-prompt-guide" in actions
    assert panels[3]["columns"][1]["key"] == "display_token"


def test_tui_default_screen_returns_user_dashboard_panels(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/command-center.overview/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["chrome_mode"] == "immersive"
    assert payload["screen"]["default_action_key"] == "operator.home.decision_queue"
    panels = payload["screen"]["dashboard_panels"]
    assert [panel["layout_area"] for panel in panels] == [
        "decision_queue",
        "market_context",
        "account_signal_summary",
        "system_exception_summary",
        "data_task_summary",
        "ai_config_summary",
    ]
    assert [panel["target_screen"] for panel in panels] == [
        "command-center.decision-flow",
        "macro-regime.overview",
        "execution.accounts",
        "api-library.runtime",
        "api-library.data-center",
        "ai-ops.providers",
    ]
    assert panels[0]["action_key"] == "operator.home.decision_queue"
    assert panels[1]["action_key"] == "operator.home.market_context"
    assert panels[2]["action_key"] == "operator.home.account_signal_summary"
    assert panels[3]["kind"] == "datagrid"
    assert panels[3]["action_key"] == "operator.home.system_exception_summary"
    assert panels[4]["kind"] == "datagrid"
    assert panels[4]["action_key"] == "operator.home.data_task_summary"
    assert panels[5]["action_key"] == "operator.home.ai_config_summary"
    assert [panel["title"] for panel in panels] == [
        "一、今日待办队列",
        "二、环境与脉搏摘要",
        "三、账户与信号摘要",
        "四、系统异常总览",
        "五、数据与任务异常",
        "六、AI / 配置异常",
    ]
    action_keys = {action["key"] for action in payload["actions"]}
    assert {
        "operator.home.continue_decision_flow",
        "operator.home.enter_governance_flow",
        "operator.home.resume_last_workspace",
        "operator.home.open_cli",
    } <= action_keys


def test_tui_research_asset_lab_screen_returns_overview_panels(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/research.asset-lab/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["chrome_mode"] == ""
    assert payload["screen"]["default_action_key"] == "auto.api.get.api.asset-analysis.pool-summary"
    panels = payload["screen"]["dashboard_panels"]
    assert [panel["layout_area"] for panel in panels] == [
        "pool_summary",
        "current_weight",
        "weight_configs",
    ]
    assert [panel["action_key"] for panel in panels] == [
        "auto.api.get.api.asset-analysis.pool-summary",
        "auto.api.get.api.asset-analysis.current-weight",
        "auto.api.get.api.asset-analysis.weight-configs",
    ]
    assert [panel["kind"] for panel in panels] == ["detail", "detail", "detail"]
    assert [panel["target_screen"] for panel in panels] == [
        "research.asset-lab",
        "research.asset-lab",
        "research.asset-lab",
    ]


def test_tui_beta_gate_screen_returns_overview_panels(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/macro-regime.beta-gate/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["chrome_mode"] == ""
    assert payload["screen"]["default_action_key"] == "auto.api.get.api.beta-gate.decisions"
    panels = payload["screen"]["dashboard_panels"]
    action_keys = [action["key"] for action in payload["actions"]]
    assert [panel["layout_area"] for panel in panels] == [
        "decisions",
        "configs",
        "universe",
        "versions",
    ]
    assert [panel["action_key"] for panel in panels] == [
        "auto.api.get.api.beta-gate.decisions",
        "auto.api.get.api.beta-gate.configs",
        "auto.api.get.api.beta-gate.universe",
        "auto.api.get.api.beta-gate.version.compare",
    ]
    assert [panel["kind"] for panel in panels] == [
        "datagrid",
        "datagrid",
        "datagrid",
        "datagrid",
    ]
    assert all(panel["target_screen"] == "macro-regime.beta-gate" for panel in panels)
    assert [panel["title"] for panel in panels] == [
        "一、最近闸门决策",
        "二、当前配置版本",
        "三、最近标的池快照",
        "四、最近配置版本",
    ]
    assert action_keys == [
        "auto.api.get.api.beta-gate.configs",
        "auto.api.get.api.beta-gate.decisions",
        "auto.api.get.api.beta-gate.universe",
        "auto.api.get.api.beta-gate.version.compare",
    ]


def test_tui_data_center_screen_returns_overview_panels(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/api-library.data-center/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["default_action_key"] == "operator.governance.data_center_summary"
    panels = payload["screen"]["dashboard_panels"]
    assert [panel["layout_area"] for panel in panels] == [
        "governance_summary",
        "providers",
        "indicators",
    ]
    assert [panel["action_key"] for panel in panels] == [
        "operator.governance.data_center_summary",
        "auto.api.get.api.data-center.providers",
        "auto.api.get.api.data-center.indicators",
    ]
    action_keys = [action["key"] for action in payload["actions"]]
    assert "auto.api.get.api.data-center" not in action_keys


def test_tui_events_screen_returns_overview_panels(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.events/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["default_action_key"] == "auto.api.get.api.events.query"
    panels = payload["screen"]["dashboard_panels"]
    assert [panel["layout_area"] for panel in panels] == [
        "events",
        "metrics",
        "status",
    ]
    assert [panel["action_key"] for panel in panels] == [
        "auto.api.get.api.events.query",
        "auto.api.get.api.events.metrics",
        "auto.api.get.api.events.status",
    ]
    action_keys = [action["key"] for action in payload["actions"]]
    assert "auto.api.get.api.events" not in action_keys


def test_tui_share_screen_defaults_to_share_links(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/execution.share/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["screen"]["default_action_key"] == "auto.api.get.api.share.links"
    panels = payload["screen"]["dashboard_panels"]
    assert len(panels) == 1
    assert panels[0]["action_key"] == "auto.api.get.api.share.links"
    action_keys = [action["key"] for action in payload["actions"]]
    assert "auto.api.get.api.share" not in action_keys


def test_tui_alpha_triggers_screen_returns_overview_panels(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/research.alpha-triggers/")

    assert response.status_code == 200
    payload = response.json()
    assert (
        payload["screen"]["default_action_key"]
        == "auto.api.get.api.alpha-triggers.candidates.actionable"
    )
    panels = payload["screen"]["dashboard_panels"]
    assert [panel["layout_area"] for panel in panels] == [
        "actionable",
        "triggers",
        "watch_list",
    ]
    assert [panel["action_key"] for panel in panels] == [
        "auto.api.get.api.alpha-triggers.candidates.actionable",
        "auto.api.get.api.alpha-triggers.triggers.active",
        "auto.api.get.api.alpha-triggers.candidates.watch-list",
    ]
    action_keys = [action["key"] for action in payload["actions"]]
    assert "auto.api.get.api.alpha-triggers" not in action_keys


def test_tui_pulse_and_hedge_screens_return_overview_panels(client, tui_user):
    client.force_login(tui_user)

    pulse_response = client.get("/api/tui/screens/macro-regime.pulse/")
    hedge_response = client.get("/api/tui/screens/macro-regime.hedge/")

    assert pulse_response.status_code == 200
    assert hedge_response.status_code == 200

    pulse_panels = pulse_response.json()["screen"]["dashboard_panels"]
    hedge_panels = hedge_response.json()["screen"]["dashboard_panels"]

    assert [panel["action_key"] for panel in pulse_panels] == [
        "pulse.current",
        "pulse.history",
    ]
    assert [panel["action_key"] for panel in hedge_panels] == [
        "auto.api.get.api.hedge.snapshots.latest",
        "auto.api.get.api.hedge.alerts.active",
        "auto.api.get.api.hedge.pairs.all_effectiveness",
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


@pytest.mark.django_db
def test_tui_admin_config_center_runtime_action_handles_active_model_without_updated_at(
    client,
    tui_admin_user,
):
    client.force_login(tui_admin_user)

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        provider_dir = tmp_path / "qlib" / "cn_data"
        model_dir = tmp_path / "qlib" / "models"
        provider_dir.mkdir(parents=True)
        model_dir.mkdir(parents=True)

        settings_obj = SystemSettingsModel.get_settings()
        settings_obj.qlib_enabled = True
        settings_obj.qlib_provider_uri = str(provider_dir)
        settings_obj.qlib_model_path = str(model_dir)
        settings_obj.save(
            update_fields=[
                "qlib_enabled",
                "qlib_provider_uri",
                "qlib_model_path",
                "updated_at",
            ]
        )

        active_model = QlibModelRegistryModel.objects.create(
            model_name="uat-qlib-model",
            artifact_hash="a" * 64,
            model_type=QlibModelRegistryModel.MODEL_LGB,
            universe="csi300",
            train_config={},
            feature_set_id="alpha158",
            label_id="return_5d",
            data_version="2026-06-22",
            model_path=str(model_dir / "uat.pkl"),
            is_active=True,
        )

        response = client.post(
            "/api/tui/actions/config_center.qlib_runtime/run/",
            {"params": {}},
            content_type="application/json",
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["view_model"]["kind"] == "detail"
        assert (
            payload["debug"]["raw_response"]["data"]["active_model"]["artifact_hash"]
            == active_model.artifact_hash
        )
        assert payload["debug"]["raw_response"]["data"]["active_model"]["updated_at"] == (
            active_model.created_at.isoformat()
        )


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


def test_tui_metadata_validator_rejects_unknown_screen_audience():
    payload = _metadata_payload()
    payload["screens"][0]["audience"] = "operator"

    with pytest.raises(TuiMetadataValidationError, match="unsupported audience"):
        validate_tui_metadata(payload)


def test_tui_metadata_validator_defaults_screen_audience_for_legacy_payload():
    validated = validate_tui_metadata(_metadata_payload())

    assert validated["screens"][0]["audience"] == "authenticated"


def test_tui_metadata_validator_accepts_agomtui_runtime_contract_extensions():
    payload = _metadata_payload()
    payload["field_aliases"] = {"company.keyword": ["keyword", "company_name"]}
    payload["screens"][0]["user_experience"] = {
        "journey": "dashboard",
        "primary_task": "Preview the image result.",
        "primary_outcome": "Confirm the preview is usable.",
        "empty_state_hint": "Run the preview action first.",
        "next_step_hint": "Open the detail view if the preview looks correct.",
    }
    payload["actions"][0].update(
        {
            "view_type": "image",
            "view_model": {"kind": "image"},
            "result_semantics": ["supporting_detail"],
            "pagination": {
                "mode": "offset",
                "offset_param": "offset",
                "limit_param": "limit",
            },
            "fields": [
                {
                    "key": "manifest",
                    "label": "Manifest",
                    "input_type": "file",
                    "accept": ".json",
                    "semantic": "company.keyword",
                    "presentation_semantic": "identifier",
                    "aliases": ["company_name"],
                }
            ],
        }
    )
    payload["screens"][0]["view_type"] = "image"
    payload["screens"][0]["dashboard_panels"] = [
        {
            "key": "preview",
            "title": "Preview",
            "kind": "image",
            "target_screen": "command-center.overview",
            "user_priority": "p0",
            "presentation_semantic": "supporting_detail",
        }
    ]

    validated = validate_tui_metadata(payload)
    action = validated["actions"][0]

    assert action["fields"][0]["value_type"] == "string"
    assert action["pagination"]["mode"] == "offset"
    assert action["view_model"]["kind"] == "image"
    assert (
        validated["screens"][0]["dashboard_panels"][0]["target_screen"] == "command-center.overview"
    )


def test_tui_metadata_validator_rejects_unknown_dashboard_target_screen():
    payload = _metadata_payload()
    payload["screens"][0]["dashboard_panels"] = [
        {
            "key": "preview",
            "title": "Preview",
            "kind": "detail",
            "target_screen": "missing.screen",
        }
    ]

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)


def test_tui_metadata_validator_rejects_copyable_secret_panel_on_datagrid():
    payload = _metadata_payload()
    payload["screens"][0]["dashboard_panels"] = [
        {
            "key": "token-panel",
            "title": "Token",
            "kind": "datagrid",
            "action_key": "quotes.read",
            "user_priority": "p0",
            "presentation_semantic": "copyable_secret",
        }
    ]

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)


def test_tui_metadata_validator_rejects_prompt_field_without_textarea():
    payload = _metadata_payload()
    payload["actions"][0]["fields"] = [
        {
            "key": "agent_prompt",
            "label": "助手提示词",
            "input_type": "text",
            "value_type": "string",
            "presentation_semantic": "prompt_text",
        }
    ]

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)


def test_tui_metadata_validator_rejects_internal_contract_copy_in_user_experience():
    payload = _metadata_payload()
    payload["screens"][0]["user_experience"] = {
        "journey": "workspace",
        "primary_task": "Open /api/account/accounts/ to continue.",
        "primary_outcome": "Review the current screen result.",
        "empty_state_hint": "Run the preview action first.",
        "next_step_hint": "Continue after reviewing the result.",
    }

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)


def test_tui_metadata_validator_adds_user_facing_design_defaults():
    validated = validate_tui_metadata(_metadata_payload())

    assert validated["screens"][0]["user_experience"]["journey"] == "workspace"
    assert validated["actions"][0]["result_semantics"] == []
    assert validated["actions"][0]["fields"] == []


def test_tui_metadata_compact_payload_round_trips_runtime_defaults():
    payload = validate_tui_metadata(_metadata_payload())
    compacted = compact_tui_metadata_payload(payload)
    action = compacted["actions"][0]

    assert "method" not in action
    assert "risk" not in action
    assert "fields" not in action
    assert "view_model" not in action
    assert "raw_debug" not in action
    assert "confirmation_required" not in action
    assert "requires_password" not in action
    assert "audit_required" not in action
    assert "sensitive_level" not in action
    assert "executor" not in action
    assert "module_key" not in action

    restored = validate_tui_metadata(compacted)
    restored_action = restored["actions"][0]
    assert restored_action["method"] == "GET"
    assert restored_action["risk"] == "read"
    assert restored_action["fields"] == []
    assert restored_action["view_model"] == {}
    assert restored_action["raw_debug"] is True
    assert restored_action["confirmation_required"] is False
    assert restored_action["requires_password"] is False
    assert restored_action["audit_required"] is False
    assert restored_action["sensitive_level"] == "none"
    assert restored_action["executor"] == ""
    assert restored_action["module_key"] == "command-center"


def test_tui_metadata_governance_defaults_for_write_action():
    payload = _metadata_payload()
    payload["actions"][0].update(
        {
            "method": "POST",
            "risk": "write",
            "endpoint": "/api/terminal/chat/",
        }
    )

    action = validate_tui_metadata(payload)["actions"][0]

    assert action["confirmation_required"] is True
    assert action["audit_required"] is True
    assert action["sensitive_level"] == "high"
    assert action["requires_password"] is False
    assert action["executor"] == ""


def test_tui_metadata_governed_action_cannot_disable_confirmation_or_audit():
    payload = _metadata_payload()
    payload["actions"][0].update(
        {
            "method": "POST",
            "risk": "write",
            "endpoint": "/api/terminal/chat/",
            "confirmation_required": False,
            "audit_required": False,
        }
    )

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)


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


def test_tui_service_shows_admin_risk_actions_to_admin_user(tui_admin_user):
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
            "key": "admin.runtime",
            "label": "Admin Runtime",
            "method": "GET",
            "endpoint": "/api/system/config-center/qlib/runtime/",
            "intent": "admin_runtime",
            "screen_key": "command-center.overview",
            "module_key": "command-center",
            "view_type": "detail",
            "risk": "admin",
            "fields": [],
        },
    ]

    catalog = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(_metadata_payload(actions=actions))
    ).get_catalog(user=tui_admin_user)

    assert catalog["stats"]["published_actions"] == 2
    assert catalog["stats"]["hidden_by_risk"] == 0
    screen = catalog["groups"][0]["modules"][0]["screens"][0]
    assert screen["action_count"] == 2

    spec = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(_metadata_payload(actions=actions))
    ).get_screen("command-center.overview", user=tui_admin_user)
    assert {action["key"] for action in spec["actions"]} == {"safe.read", "admin.runtime"}


def test_tui_service_runs_admin_get_action_for_admin_user(tui_admin_user):
    class FakeExecutor:
        def __init__(self):
            self.kwargs = None

        def execute(self, **kwargs):
            self.kwargs = kwargs
            return {
                "status_code": 200,
                "payload": {"data": {"configured": True, "latest_run_status": "idle"}},
            }

    executor = FakeExecutor()
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "admin.runtime",
                        "label": "Admin Runtime",
                        "method": "GET",
                        "endpoint": "/api/system/config-center/qlib/runtime/",
                        "intent": "admin_runtime",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "admin",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=executor,
    )

    payload = service.run_action(action_key="admin.runtime", params={}, user=tui_admin_user)

    assert executor.kwargs["endpoint"] == "/api/system/config-center/qlib/runtime/"
    assert payload["confirmation_required"] is False
    assert payload["view_model"]["kind"] == "detail"


def test_tui_service_requires_confirmation_for_admin_post_action(tui_admin_user):
    class FakeExecutor:
        def __init__(self):
            self.calls = 0

        def execute(self, **kwargs):
            self.calls += 1
            return {
                "status_code": 202,
                "payload": {"success": True, "data": {"run_id": "run-1"}},
            }

    executor = FakeExecutor()
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "admin.training.trigger",
                        "label": "Trigger Training",
                        "method": "POST",
                        "endpoint": "/api/system/config-center/qlib/training-runs/trigger/",
                        "intent": "trigger_training",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "admin",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=executor,
    )

    confirmation = service.run_action(
        action_key="admin.training.trigger",
        params={},
        user=tui_admin_user,
    )

    assert confirmation["confirmation_required"] is True
    assert executor.calls == 0

    payload = service.run_action(
        action_key="admin.training.trigger",
        params={},
        user=tui_admin_user,
        confirmed=True,
    )

    assert payload["confirmation_required"] is False
    assert executor.calls == 1


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


def test_tui_service_marks_missing_optional_detail_as_empty_state(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 404,
                "payload": {"detail": "该策略没有 AI 配置"},
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "strategy.ai-config",
                        "label": "策略 / AI 配置",
                        "method": "GET",
                        "endpoint": "/api/strategy/strategies/<pk>/ai_config/",
                        "intent": "read_strategy_ai_config",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "pk",
                                "label": "记录 ID",
                                "input_type": "number",
                                "required": True,
                            }
                        ],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(action_key="strategy.ai-config", params={"pk": 4}, user=tui_user)

    assert payload["response"]["status_code"] == 404
    assert payload["view_model"]["kind"] == "detail"
    assert payload["view_model"]["status"] == "暂无数据"
    assert payload["view_model"]["fields"][0]["value"] == "该策略没有 AI 配置"


def test_tui_service_preserves_backend_auth_challenge_payload(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 401,
                "payload": {"requires_password": True, "title": "Agom-test"},
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "share.public",
                        "label": "分享 / 公开分享 / 详情",
                        "method": "GET",
                        "endpoint": "/api/share/public/<short_code>/",
                        "intent": "read_public_share",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "short_code",
                                "label": "分享码",
                                "input_type": "text",
                                "required": True,
                            }
                        ],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="share.public",
        params={"short_code": "ABC123"},
        user=tui_user,
    )

    assert payload["response"]["status_code"] == 401
    assert payload["view_model"]["kind"] == "detail"
    assert payload["view_model"]["status"] == "需要密码"
    assert payload["view_model"]["fields"][0]["key"] == "requires_password"
    assert payload["view_model"]["fields"][0]["label"] == "需要密码"
    assert payload["view_model"]["fields"][-1]["key"] == "operator_hint"
    assert "验证访问" in payload["view_model"]["fields"][-1]["value"]


def test_tui_share_screen_exposes_public_access_operation(client, tui_user):
    client.force_login(tui_user)

    published = PublishedTuiMetadataRepository().load_published()
    published_action = next(
        action for action in published["actions"] if action["key"] == "share.public.access"
    )
    assert published_action["method"] == "POST"
    assert published_action["risk"] == "read"

    response = client.get("/api/tui/screens/execution.share/")

    assert response.status_code == 200
    payload = response.json()
    action = next(action for action in payload["actions"] if action["key"] == "share.public.access")
    assert action["risk"] == "read"
    assert action["confirmation_required"] is False
    assert action["fields"][0]["key"] == "short_code"
    assert action["fields"][0]["label"] == "短码"
    assert action["fields"][0]["required"] is True
    assert action["fields"][1]["key"] == "password"
    assert action["fields"][1]["label"] == "访问密码"


def _create_share_link_for_tui_flow(
    *,
    owner: User,
    short_code: str,
    requires_password: bool,
) -> ShareLinkModel:
    account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name=f"TUI Share {short_code}",
        account_type="simulated",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("50000.00"),
        current_market_value=Decimal("50000.00"),
        total_value=Decimal("100000.00"),
        start_date=timezone.now().date(),
    )
    share_link = ShareLinkModel.objects.create(
        owner=owner,
        account_id=account.id,
        short_code=short_code,
        title=f"Share {short_code}",
        subtitle="TUI Flow",
        share_level="snapshot",
        status="active",
        password_hash=make_password("testpass") if requires_password else None,
        expires_at=None,
        max_access_count=None,
        access_count=0,
        allow_indexing=False,
        show_amounts=True,
        show_positions=True,
        show_transactions=True,
        show_decision_summary=True,
        show_decision_evidence=False,
        show_invalidation_logic=False,
    )
    ShareSnapshotModel.objects.create(
        share_link=share_link,
        snapshot_version=1,
        summary_payload={
            "account_name": account.account_name,
            "total_value": "100000.00",
            "portfolio_type": "simulated",
        },
        performance_payload={"total_return": 1.23},
        positions_payload={"items": [{"asset_code": "000001.SH", "quantity": 100}]},
        transactions_payload={"items": []},
        decision_payload={"items": []},
        source_range_start=timezone.now().date(),
        source_range_end=timezone.now().date(),
    )
    return share_link


def test_tui_action_api_can_access_public_share_without_password(client, tui_user, monkeypatch):
    share_link = _create_share_link_for_tui_flow(
        owner=tui_user,
        short_code="TUIOPEN123",
        requires_password=False,
    )
    metadata = _metadata_payload(
        actions=[
            {
                "key": "share.public.access",
                "label": "公开分享 / 验证访问",
                "method": "POST",
                "endpoint": "/api/share/public/<str:short_code>/access/",
                "intent": "access_public_share",
                "screen_key": "command-center.overview",
                "module_key": "command-center",
                "view_type": "detail",
                "risk": "read",
                "fields": [
                    {
                        "key": "short_code",
                        "label": "分享码",
                        "input_type": "text",
                        "required": True,
                    },
                    {
                        "key": "password",
                        "label": "访问密码",
                        "input_type": "text",
                        "required": False,
                    },
                ],
                "source": "approved:test",
            }
        ]
    )
    monkeypatch.setattr(
        "apps.terminal.interface.api_views.get_tui_metadata_repository",
        lambda: FakeMetadataRepository(metadata),
    )

    client.force_login(tui_user)
    response = client.post(
        "/api/tui/actions/share.public.access/run/",
        {"params": {"short_code": share_link.short_code}},
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"]["status_code"] == 200
    assert payload["view_model"]["kind"] == "detail"
    assert (
        payload["debug"]["raw_response"]["share_link"]["title"] == f"Share {share_link.short_code}"
    )
    assert payload["debug"]["raw_response"]["snapshot"]["summary"]["account_name"] == (
        f"TUI Share {share_link.short_code}"
    )


def test_tui_action_api_reuses_session_for_password_protected_public_share(
    client,
    tui_user,
    monkeypatch,
):
    share_link = _create_share_link_for_tui_flow(
        owner=tui_user,
        short_code="TUIPWD1234",
        requires_password=True,
    )
    metadata = _metadata_payload(
        actions=[
            {
                "key": "share.public.access",
                "label": "公开分享 / 验证访问",
                "method": "POST",
                "endpoint": "/api/share/public/<str:short_code>/access/",
                "intent": "access_public_share",
                "screen_key": "command-center.overview",
                "module_key": "command-center",
                "view_type": "detail",
                "risk": "read",
                "fields": [
                    {
                        "key": "short_code",
                        "label": "分享码",
                        "input_type": "text",
                        "required": True,
                    },
                    {
                        "key": "password",
                        "label": "访问密码",
                        "input_type": "text",
                        "required": False,
                    },
                ],
                "source": "approved:test",
            },
            {
                "key": "share.public.snapshot",
                "label": "公开分享 / 快照",
                "method": "GET",
                "endpoint": "/api/share/public/<str:short_code>/snapshot/",
                "intent": "read_public_share_snapshot",
                "screen_key": "command-center.overview",
                "module_key": "command-center",
                "view_type": "detail",
                "risk": "read",
                "fields": [
                    {"key": "short_code", "label": "分享码", "input_type": "text", "required": True}
                ],
                "source": "approved:test",
            },
        ]
    )
    monkeypatch.setattr(
        "apps.terminal.interface.api_views.get_tui_metadata_repository",
        lambda: FakeMetadataRepository(metadata),
    )
    monkeypatch.setattr(
        "apps.terminal.interface.api_views.get_tui_action_executor",
        get_tui_action_executor,
    )

    client.force_login(tui_user)
    access_response = client.post(
        "/api/tui/actions/share.public.access/run/",
        {"params": {"short_code": share_link.short_code, "password": "testpass"}},
        content_type="application/json",
    )

    assert access_response.status_code == 200
    access_payload = access_response.json()
    assert access_payload["response"]["status_code"] == 200
    assert access_payload["debug"]["raw_response"]["share_link"]["title"] == (
        f"Share {share_link.short_code}"
    )

    snapshot_response = client.post(
        "/api/tui/actions/share.public.snapshot/run/",
        {"params": {"short_code": share_link.short_code}},
        content_type="application/json",
    )

    assert snapshot_response.status_code == 200
    snapshot_payload = snapshot_response.json()
    assert snapshot_payload["response"]["status_code"] == 200
    assert snapshot_payload["view_model"]["status"] == "正常"
    assert snapshot_payload["debug"]["raw_response"]["summary"]["account_name"] == (
        f"TUI Share {share_link.short_code}"
    )


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


def test_tui_service_audits_blocked_confirmation_with_canonical_record(tui_user):
    class FakeExecutor:
        calls = 0

        def execute(self, **kwargs):
            self.calls += 1
            return {"status_code": 200, "payload": {"status": "ok"}}

    audit_repository = FakeAuditRepository()
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "terminal.write.audit",
                        "label": "审计写入",
                        "method": "POST",
                        "endpoint": "/api/terminal/chat/",
                        "intent": "audit_write",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "write",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
        audit_repository=audit_repository,
    )

    payload = service.run_action(
        action_key="terminal.write.audit",
        params={},
        user=tui_user,
    )

    assert payload["confirmation_required"] is True
    assert len(audit_repository.entries) == 1
    entry = audit_repository.entries[0]
    record = json.loads(entry.params_summary)
    assert record["schema_version"] == "tui-audit.v1"
    assert record["actor"] == "tui_user"
    assert record["action_key"] == "terminal.write.audit"
    assert record["outcome"] == "blocked_confirmation_required"
    assert record["result"]["confirmation_required"] is True
    assert entry.mode == "tui-workbench"
    assert entry.result_status == "blocked"
    assert entry.confirmation_required is True


def test_tui_service_strict_audit_sink_blocks_governed_action_without_repository(tui_user):
    class FakeExecutor:
        calls = 0

        def execute(self, **kwargs):
            self.calls += 1
            return {"status_code": 200, "payload": {"status": "ok"}}

    executor = FakeExecutor()
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "terminal.write.audit-required",
                        "label": "审计必需写入",
                        "method": "POST",
                        "endpoint": "/api/terminal/chat/",
                        "intent": "audit_required_write",
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
        require_audit_sink=True,
    )

    with pytest.raises(RuntimeError):
        service.run_action(
            action_key="terminal.write.audit-required",
            params={},
            user=tui_user,
        )
    assert executor.calls == 0


def test_tui_service_audits_success_and_masks_sensitive_params(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {"status_code": 200, "payload": {"status": "ok"}}

    audit_repository = FakeAuditRepository()
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "terminal.secret.rotate",
                        "label": "轮换密钥",
                        "method": "POST",
                        "endpoint": "/api/terminal/chat/",
                        "intent": "rotate_secret",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "write",
                        "requires_password": True,
                        "fields": [
                            {"key": "secret_id", "label": "Secret ID", "required": True},
                            {"key": "new_password", "label": "New Password", "required": True},
                        ],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
        audit_repository=audit_repository,
    )

    payload = service.run_action(
        action_key="terminal.secret.rotate",
        params={"secret_id": "SEC-1", "new_password": "raw-secret"},
        user=tui_user,
        confirmed=True,
        confirmation={"confirmed": True, "confirmed_at": "2026-06-23T10:00:00Z"},
        reauth={
            "method": "password",
            "credential": "test-password",
            "challenge_id": "terminal.secret.rotate",
        },
    )

    assert payload["response"]["status_code"] == 200
    assert len(audit_repository.entries) == 1
    record = json.loads(audit_repository.entries[0].params_summary)
    assert record["outcome"] == "succeeded"
    assert record["params"]["secret_id"] == "***"
    assert record["params"]["new_password"] == "***"
    assert record["confirmation"]["confirmed"] is True
    assert record["reauth"]["verified"] is True
    assert "credential" not in record["reauth"]
    assert audit_repository.entries[0].result_status == "success"


def test_tui_service_requires_password_before_sensitive_action(tui_user):
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
                        "key": "terminal.secret.write",
                        "label": "敏感写入",
                        "method": "POST",
                        "endpoint": "/api/terminal/chat/",
                        "intent": "secret_write",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "write",
                        "requires_password": True,
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=executor,
    )

    confirmation = service.run_action(
        action_key="terminal.secret.write",
        params={},
        user=tui_user,
    )

    assert confirmation["confirmation_required"] is True
    assert executor.calls == 0

    challenge = service.run_action(
        action_key="terminal.secret.write",
        params={},
        user=tui_user,
        confirmed=True,
    )

    assert challenge["password_challenge_required"] is True
    assert challenge["response"]["status_code"] == 401
    assert challenge["view_model"]["status"] == "需要密码"
    assert executor.calls == 0

    rejected = service.run_action(
        action_key="terminal.secret.write",
        params={},
        user=tui_user,
        confirmed=True,
        reauth={"method": "password", "credential": "wrong-password"},
    )

    assert rejected["password_challenge_required"] is True
    assert executor.calls == 0

    payload = service.run_action(
        action_key="terminal.secret.write",
        params={},
        user=tui_user,
        confirmed=True,
        reauth={"method": "password", "credential": "test-password"},
    )

    assert payload["confirmation_required"] is False
    assert payload["response"]["status_code"] == 200
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
                            {"key": "provider_id", "label": "服务商 ID", "required": True},
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


def test_tui_service_turns_account_id_fields_into_named_select(tui_user):
    account = SimulatedAccountModel.objects.create(
        user=tui_user,
        account_name="稳健一号",
        account_type="simulated",
        initial_capital=100000,
        current_cash=60000,
        current_market_value=40000,
        total_value=100000,
    )
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "advisor.today",
                        "label": "今日自动投顾建议单",
                        "method": "GET",
                        "endpoint": "/api/decision/advisor/sheet/",
                        "intent": "advisor_today",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "account_id",
                                "label": "账户 ID",
                                "input_type": "number",
                                "required": True,
                                "default": "",
                                "binding": "query",
                                "value_type": "integer",
                            }
                        ],
                    }
                ]
            )
        )
    )

    payload = service.get_screen("command-center.overview", user=tui_user)
    field = payload["actions"][0]["fields"][0]

    assert field["input_type"] == "select"
    assert field["value_type"] == "integer"
    assert field["options"][0] == {"value": "", "label": "请选择账户"}
    account_option = next(option for option in field["options"] if option["value"] == account.id)
    assert "稳健一号" in account_option["label"]
    assert f"#{account.id}" in account_option["label"]


def test_tui_service_missing_account_field_returns_named_select_options(tui_user):
    account = SimulatedAccountModel.objects.create(
        user=tui_user,
        account_name="进取二号",
        account_type="real",
        initial_capital=200000,
        current_cash=120000,
        current_market_value=80000,
        total_value=200000,
    )

    class FakeExecutor:
        def execute(self, **kwargs):
            raise AssertionError("Executor should not run when account_id is missing")

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "risk.effective-policy",
                        "label": "查询账户风控策略",
                        "method": "GET",
                        "endpoint": "/api/risk-center/effective-policy/",
                        "intent": "risk_policy",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "account_id",
                                "label": "账户 ID",
                                "input_type": "number",
                                "required": True,
                                "default": "",
                                "binding": "query",
                                "value_type": "integer",
                            }
                        ],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(action_key="risk.effective-policy", params={}, user=tui_user)
    field = payload["missing_fields"][0]

    assert payload["response"]["status_code"] == 400
    assert field["key"] == "account_id"
    assert field["input_type"] == "select"
    account_option = next(option for option in field["options"] if option["value"] == account.id)
    assert "进取二号" in account_option["label"]
    assert payload["action"]["fields"][0]["input_type"] == "select"


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


def test_tui_service_action_runner_infers_limit_offset_pager_from_request_params(tui_user):
    captured: dict[str, object] = {}

    class FakeExecutor:
        def execute(self, **kwargs):
            captured.update(kwargs)
            return {
                "status_code": 200,
                "payload": {
                    "success": True,
                    "items": [
                        {"id": 51, "title": "Event 51"},
                        {"id": 52, "title": "Event 52"},
                    ],
                    "total": 75,
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "policy.workbench_items",
                        "label": "待看事件",
                        "method": "GET",
                        "endpoint": "/api/policy/workbench/items/",
                        "intent": "browse_policy_queue_items",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                        "view_model": {
                            "rows_path": "items",
                            "total_path": "total",
                        },
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="policy.workbench_items",
        params={"limit": "50", "offset": "50"},
        user=tui_user,
    )

    pager = payload["view_model"]["pager"]
    assert captured["params"] == {"limit": "50", "offset": "50"}
    assert pager["pagination_mode"] == "limit_offset"
    assert pager["page"] == 2
    assert pager["page_size"] == 50
    assert pager["offset"] == 50
    assert pager["total_rows"] == 75
    assert pager["has_previous"] is True
    assert pager["has_next"] is False


def test_tui_service_action_runner_applies_field_defaults_to_request_params(tui_user):
    captured: dict[str, object] = {}

    class FakeExecutor:
        def execute(self, **kwargs):
            captured.update(kwargs)
            return {
                "status_code": 200,
                "payload": {
                    "success": True,
                    "data": {
                        "recommendations": [],
                        "total_count": 0,
                        "page": 1,
                        "page_size": 20,
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "decision.workspace.recommendations",
                        "label": "决策工作台建议",
                        "method": "GET",
                        "endpoint": "/api/decision/workspace/recommendations/",
                        "intent": "auto_safe_read_candidate",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "account_id",
                                "label": "账户ID",
                                "input_type": "text",
                                "required": True,
                                "binding": "query",
                                "value_type": "string",
                                "default": "default",
                            }
                        ],
                        "view_model": {
                            "rows_path": "recommendations",
                            "total_path": "total_count",
                            "page_path": "page",
                            "page_size_path": "page_size",
                        },
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="decision.workspace.recommendations",
        params={},
        user=tui_user,
    )

    assert captured["params"] == {"account_id": "default"}
    assert payload["response"]["status_code"] == 200
    assert payload["view_model"]["kind"] == "datagrid"
    assert payload["view_model"]["pager"]["total_rows"] == 0


def test_tui_service_action_runner_applies_dynamic_read_date_defaults(tui_user):
    captured: dict[str, object] = {}

    class FakeExecutor:
        def execute(self, **kwargs):
            captured.update(kwargs)
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
                        "key": "account.trades",
                        "label": "交易流水",
                        "method": "GET",
                        "endpoint": "/api/account/accounts/<int:account_id>/trades/",
                        "intent": "parameterized_safe_read",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "account_id",
                                "label": "账户ID",
                                "input_type": "number",
                                "required": True,
                                "binding": "path",
                                "value_type": "integer",
                                "default": "",
                            },
                            {
                                "key": "start_date",
                                "label": "开始日期",
                                "input_type": "date",
                                "required": True,
                                "binding": "query",
                                "value_type": "date",
                                "default": "",
                            },
                            {
                                "key": "end_date",
                                "label": "结束日期",
                                "input_type": "date",
                                "required": True,
                                "binding": "query",
                                "value_type": "date",
                                "default": "",
                            },
                            {
                                "key": "trade_date",
                                "label": "交易日期",
                                "input_type": "date",
                                "required": False,
                                "binding": "query",
                                "value_type": "date",
                                "default": "",
                            },
                        ],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="account.trades",
        params={"account_id": 365},
        user=tui_user,
    )

    today = timezone.localdate()
    assert captured["params"] == {
        "start_date": (today - timedelta(days=30)).isoformat(),
        "end_date": today.isoformat(),
        "trade_date": today.isoformat(),
    }
    fields = payload["action"]["fields"]
    assert fields[1]["default"] == (today - timedelta(days=30)).isoformat()
    assert fields[2]["default"] == today.isoformat()
    assert fields[3]["default"] == today.isoformat()


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


def test_tui_service_prefers_detail_for_object_payload_with_nested_lists(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "id": 9,
                    "name": "bond_market_analysis",
                    "description": "债券市场投资分析",
                    "placeholders": [
                        {"name": "REGIME", "required": True},
                        {"name": "GROWTH_Z", "required": True},
                    ],
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "prompt.template.detail",
                        "label": "Prompt / 模板 / 详情",
                        "method": "GET",
                        "endpoint": "/api/prompt/templates/9/",
                        "intent": "read_prompt_template",
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
        action_key="prompt.template.detail",
        params={},
        user=tui_user,
    )

    assert payload["view_model"]["kind"] == "detail"
    assert payload["view_model"]["fields"][0]["key"] == "id"
    assert payload["view_model"]["nested"][0]["key"] == "placeholders"


def test_tui_service_hides_success_wrapper_field_in_detail_view(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "success": True,
                    "account": {
                        "account_id": 365,
                        "account_name": "默认组合",
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "account.detail",
                        "label": "账户 / 详情",
                        "method": "GET",
                        "endpoint": "/api/account/accounts/365/",
                        "intent": "read_account_detail",
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
        action_key="account.detail",
        params={},
        user=tui_user,
    )

    field_keys = [field["key"] for field in payload["view_model"]["fields"]]
    assert "success" not in field_keys
    assert "account.account_id" in field_keys


def test_tui_service_translates_share_access_status_codes(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 403,
                "payload": {"error": "revoked"},
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "share.public.access",
                        "label": "公开分享 / 验证访问",
                        "method": "POST",
                        "endpoint": "/api/share/public/<short_code>/access/",
                        "intent": "access_public_share",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "short_code",
                                "label": "分享码",
                                "input_type": "text",
                                "required": True,
                            }
                        ],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="share.public.access",
        params={"short_code": "ABC123"},
        user=tui_user,
    )

    assert payload["response"]["status_code"] == 403
    assert payload["view_model"]["fields"][0]["value"] == "已撤销"


def test_tui_service_localizes_share_snapshot_and_prompt_labels(tui_user):
    class ShareExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "share_link": {
                        "share_level": "snapshot",
                        "visibility": "public",
                    },
                    "snapshot": {
                        "performance": {
                            "annualized_return": 0.12,
                            "benchmark_name": "沪深300",
                        },
                        "transactions": {
                            "total_trades": 4,
                        },
                    },
                    "summary": {
                        "portfolio_type": "simulated",
                    },
                },
            }

    share_service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "share.snapshot",
                        "label": "公开分享 / 快照",
                        "method": "GET",
                        "endpoint": "/api/share/public/ABC123/snapshot/",
                        "intent": "read_share_snapshot",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=ShareExecutor(),
    )

    share_payload = share_service.run_action(action_key="share.snapshot", params={}, user=tui_user)
    share_fields = {field["key"]: field for field in share_payload["view_model"]["fields"]}

    assert share_fields["share_link.share_level"]["label"] == "分享链接 / 分享等级"
    assert share_fields["share_link.share_level"]["value"] == "快照"
    assert share_fields["share_link.visibility"]["label"] == "分享链接 / 可见性"
    assert share_fields["share_link.visibility"]["value"] == "公开"
    assert share_fields["snapshot.performance"]["label"] == "快照 / 绩效"
    assert share_fields["snapshot.transactions"]["label"] == "快照 / 交易"
    assert share_fields["summary.portfolio_type"]["value"] == "模拟"

    class PromptExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "name": "bond_market_analysis",
                            "max_tokens": 2048,
                        }
                    ],
                    "count": 1,
                },
            }

    prompt_service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "prompt.templates",
                        "label": "Prompt Templates",
                        "method": "GET",
                        "endpoint": "/api/prompt/templates/",
                        "intent": "read_prompt_templates",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=PromptExecutor(),
    )

    prompt_payload = prompt_service.run_action(
        action_key="prompt.templates", params={}, user=tui_user
    )

    assert prompt_payload["view_model"]["columns"] == [
        {"key": "name", "label": "名称"},
        {"key": "max_tokens", "label": "最大Token数"},
    ]


def test_tui_service_localizes_alpha_stats_and_agent_runtime_labels(tui_user):
    class DetailExecutor:
        def __init__(self):
            self.calls = 0

        def execute(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "status_code": 200,
                    "payload": {
                        "result": {
                            "total": 10,
                            "actionable": 3,
                            "watch": 2,
                            "candidate": 5,
                            "by_status": {"draft": 4},
                            "by_direction": {"long": 2},
                        }
                    },
                }
            return {
                "status_code": 200,
                "payload": {
                    "request_id": "atr_review_tmp2",
                    "task": {
                        "request_id": "atr_review_tmp2",
                        "schema_version": "v1",
                        "task_domain": "research",
                        "status": "draft",
                        "input_payload": {"foo": "bar"},
                        "current_step": None,
                        "last_error": None,
                        "steps_count": 0,
                        "proposals_count": 1,
                        "artifacts_count": 2,
                        "timeline_events_count": 3,
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "alpha.stats",
                        "label": "Alpha 统计",
                        "method": "GET",
                        "endpoint": "/api/alpha-triggers/candidates/statistics/",
                        "intent": "read_alpha_stats",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                    },
                    {
                        "key": "agent.task.detail",
                        "label": "智能体运行时 / 任务 / 详情",
                        "method": "GET",
                        "endpoint": "/api/agent-runtime/tasks/1/",
                        "intent": "read_agent_task",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                    },
                ]
            )
        ),
        action_executor=DetailExecutor(),
    )

    alpha_payload = service.run_action(action_key="alpha.stats", params={}, user=tui_user)
    alpha_fields = {field["key"]: field for field in alpha_payload["view_model"]["fields"]}
    assert alpha_fields["result.actionable"]["label"] == "结果 / 可操作"
    assert alpha_fields["result.watch"]["label"] == "结果 / 观察"
    assert alpha_fields["result.candidate"]["label"] == "结果 / 候选"
    assert alpha_fields["result.by_status"]["label"] == "结果 / 按状态"
    assert alpha_fields["result.by_direction"]["label"] == "结果 / 按方向"

    task_payload = service.run_action(action_key="agent.task.detail", params={}, user=tui_user)
    task_fields = {field["key"]: field for field in task_payload["view_model"]["fields"]}
    assert task_fields["task.schema_version"]["label"] == "任务 / 结构版本"
    assert task_fields["task.task_domain"]["label"] == "任务 / 任务域"
    assert task_fields["task.task_domain"]["value"] == "研究"
    assert task_fields["task.status"]["value"] == "草稿"
    assert task_fields["task.input_payload"]["label"] == "任务 / 输入参数"
    assert task_fields["task.current_step"]["label"] == "任务 / 当前步骤"
    assert task_fields["task.last_error"]["label"] == "任务 / 最近错误"
    assert task_fields["task.steps_count"]["label"] == "任务 / 步骤数量"
    assert task_fields["task.proposals_count"]["label"] == "任务 / 提案数量"
    assert task_fields["task.artifacts_count"]["label"] == "任务 / 产物数量"
    assert task_fields["task.timeline_events_count"]["label"] == "任务 / 时间线事件数量"


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


def test_tui_service_localizes_asset_and_fund_screen_labels(tui_user):
    class AssetExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "weights.env": 0.4,
                            "weights.policy": 0.35,
                            "weights.sentiment": 0.25,
                            "description.investable": "沪深300",
                            "description.prohibited": "ST",
                        }
                    ],
                    "count": 1,
                },
            }

    asset_service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "asset.analysis.weight",
                        "label": "资产权重",
                        "method": "GET",
                        "endpoint": "/api/asset-analysis/current-weight/",
                        "intent": "read_asset_analysis_weight",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=AssetExecutor(),
    )

    asset_payload = asset_service.run_action(
        action_key="asset.analysis.weight",
        params={},
        user=tui_user,
    )

    assert asset_payload["view_model"]["columns"] == [
        {"key": "weights.env", "label": "权重 / 环境"},
        {"key": "weights.policy", "label": "权重 / 政策"},
        {"key": "weights.sentiment", "label": "权重 / 情绪"},
        {"key": "description.investable", "label": "说明 / 可投资"},
        {"key": "description.prohibited", "label": "说明 / 禁投"},
    ]

    class FundExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "fund_code": "110022",
                            "fund_name": "易方达消费行业",
                            "regime_fit_score": 0.88,
                            "risk_score": 0.74,
                            "scale_score": 0.67,
                            "performance_score": 0.81,
                            "total_score": 0.79,
                        }
                    ],
                    "count": 1,
                },
            }

    fund_service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "fund.rank",
                        "label": "基金排行",
                        "method": "GET",
                        "endpoint": "/api/fund/rank/",
                        "intent": "read_fund_rank",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=FundExecutor(),
    )

    fund_payload = fund_service.run_action(action_key="fund.rank", params={}, user=tui_user)

    assert fund_payload["view_model"]["columns"] == [
        {"key": "fund_code", "label": "基金代码"},
        {"key": "fund_name", "label": "基金名称"},
        {"key": "regime_fit_score", "label": "环境匹配评分"},
        {"key": "risk_score", "label": "风险评分"},
        {"key": "scale_score", "label": "规模评分"},
        {"key": "performance_score", "label": "绩效评分"},
        {"key": "total_score", "label": "总评分"},
    ]


def test_tui_service_localizes_account_settings_labels_and_values(tui_user):
    class DetailExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "display_name": "admin",
                    "risk_tolerance": "moderate",
                    "rbac_role": "owner",
                    "stamp_duty_rate_qian": 1.0,
                    "children_count": 7,
                    "symbol": "¥",
                    "account_type": "real",
                    "start_date": "2024-01-01",
                    "last_trade_date": "2024-06-30",
                    "total_cost": 1234,
                    "total_pnl": 56,
                    "total_pnl_pct": 0.045,
                    "total_capital_inflow": 2000,
                    "total_capital_outflow": 500,
                    "net_capital_flow": 1500,
                },
            }

    detail_service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "account.settings.detail",
                        "label": "账户设置详情",
                        "method": "GET",
                        "endpoint": "/api/account/settings/detail/",
                        "intent": "read_account_settings_detail",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=DetailExecutor(),
    )

    detail_payload = detail_service.run_action(
        action_key="account.settings.detail",
        params={},
        user=tui_user,
    )
    fields = {field["key"]: field for field in detail_payload["view_model"]["fields"]}

    assert fields["display_name"]["value"] == "admin"
    assert fields["risk_tolerance"]["label"] == "风险承受度"
    assert fields["risk_tolerance"]["value"] == "中等"
    assert fields["rbac_role"]["label"] == "角色"
    assert fields["rbac_role"]["value"] == "所有者"
    assert fields["stamp_duty_rate_qian"]["label"] == "千分印花税率"
    assert fields["children_count"]["label"] == "子项数量"
    assert fields["symbol"]["label"] == "符号"
    assert fields["account_type"]["value"] == "实盘"
    assert fields["start_date"]["label"] == "开始日期"
    assert fields["last_trade_date"]["label"] == "最近交易日期"
    assert fields["total_cost"]["label"] == "总成本"
    assert fields["total_pnl"]["label"] == "总盈亏"
    assert fields["total_pnl_pct"]["label"] == "总盈亏率"
    assert fields["total_capital_inflow"]["label"] == "累计资金流入"
    assert fields["total_capital_outflow"]["label"] == "累计资金流出"
    assert fields["net_capital_flow"]["label"] == "净资金流"

    class GridExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "code": "CNY",
                            "symbol": "¥",
                            "name": "人民币",
                        }
                    ],
                    "count": 1,
                },
            }

    grid_service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "currency.list",
                        "label": "币种列表",
                        "method": "GET",
                        "endpoint": "/api/account/currencies/",
                        "intent": "read_currencies",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=GridExecutor(),
    )

    grid_payload = grid_service.run_action(action_key="currency.list", params={}, user=tui_user)

    assert grid_payload["view_model"]["columns"] == [
        {"key": "code", "label": "代码"},
        {"key": "symbol", "label": "符号"},
        {"key": "name", "label": "名称"},
    ]


def test_tui_service_localizes_strategy_and_performance_labels(tui_user):
    class DetailExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "created_by": "alice",
                    "rules_count": 3,
                    "has_script_config": True,
                    "has_ai_config": False,
                    "condition_json": {
                        "indicator": "PMI",
                    },
                    "last_used_at": "2026-06-22T10:00:00+08:00",
                },
            }

    detail_service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "strategy.detail",
                        "label": "策略详情",
                        "method": "GET",
                        "endpoint": "/api/strategy/strategies/4/",
                        "intent": "read_strategy_detail",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=DetailExecutor(),
    )

    detail_payload = detail_service.run_action(
        action_key="strategy.detail",
        params={},
        user=tui_user,
    )
    fields = {field["key"]: field for field in detail_payload["view_model"]["fields"]}

    assert fields["created_by"]["label"] == "创建人"
    assert fields["rules_count"]["label"] == "规则数量"
    assert fields["has_script_config"]["label"] == "已配置脚本"
    assert fields["has_ai_config"]["label"] == "已配置 AI"
    assert fields["condition_json.indicator"]["label"] == "条件 / 指标"
    assert fields["last_used_at"]["label"] == "最近使用时间"

    class GridExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "net_value": 1.023,
                            "drawdown_pct": -0.015,
                        }
                    ],
                    "count": 1,
                },
            }

    grid_service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "performance.curve",
                        "label": "净值曲线",
                        "method": "GET",
                        "endpoint": "/api/account/accounts/365/equity-curve/",
                        "intent": "read_equity_curve",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                    }
                ]
            )
        ),
        action_executor=GridExecutor(),
    )

    grid_payload = grid_service.run_action(action_key="performance.curve", params={}, user=tui_user)

    assert grid_payload["view_model"]["columns"] == [
        {"key": "net_value", "label": "净值"},
        {"key": "drawdown_pct", "label": "回撤率"},
    ]


def test_tui_service_datagrid_pairs_stock_codes_with_names(monkeypatch, tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "rank": 1,
                            "code": "000001.SZ",
                            "score": 0.91,
                        },
                        {
                            "rank": 2,
                            "code": "600519.SH",
                            "name": "贵州茅台",
                            "score": 0.88,
                        },
                    ],
                    "count": 2,
                },
            }

    captured_codes = []

    def fake_resolve_asset_names(codes):
        captured_codes.extend(codes)
        return {"000001.SZ": "平安银行"}

    monkeypatch.setattr(
        "apps.terminal.application.tui_workbench.resolve_asset_names",
        fake_resolve_asset_names,
    )
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "alpha.ranking",
                        "label": "Alpha 排名",
                        "method": "GET",
                        "endpoint": "/api/alpha/inference/cache/",
                        "intent": "read_alpha_ranking",
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

    payload = service.run_action(action_key="alpha.ranking", params={}, user=tui_user)

    assert "000001.SZ" in captured_codes
    assert payload["view_model"]["rows"][0]["code"] == "000001.SZ 平安银行"
    assert payload["view_model"]["rows"][1]["code"] == "600519.SH 贵州茅台"


def test_tui_service_datagrid_preserves_fund_name_over_asset_lookup(monkeypatch, tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "fund_code": "000001",
                            "fund_name": "华夏成长",
                            "regime_fit_score": 0.92,
                        }
                    ],
                    "count": 1,
                },
            }

    captured_codes = []

    def fake_resolve_asset_names(codes):
        captured_codes.extend(codes)
        return {"000001": "平安银行"}

    monkeypatch.setattr(
        "apps.terminal.application.tui_workbench.resolve_asset_names",
        fake_resolve_asset_names,
    )
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "fund.ranking",
                        "label": "基金排行",
                        "method": "GET",
                        "endpoint": "/api/fund/rank/",
                        "intent": "read_fund_ranking",
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

    payload = service.run_action(action_key="fund.ranking", params={}, user=tui_user)

    assert captured_codes == []
    assert payload["view_model"]["columns"] == [
        {"key": "fund_code", "label": "基金代码"},
        {"key": "fund_name", "label": "基金名称"},
        {"key": "regime_fit_score", "label": "环境匹配评分"},
    ]
    assert payload["view_model"]["rows"][0]["fund_code"] == "000001 华夏成长"
    assert payload["view_model"]["rows"][0]["__raw_fund_code"] == "000001"


def test_tui_service_datagrid_preserves_raw_code_for_selected_row_fill(monkeypatch, tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "results": [
                        {
                            "code": "511010",
                            "name": "国债ETF",
                            "score": 0.91,
                        }
                    ],
                    "count": 1,
                },
            }

    monkeypatch.setattr(
        "apps.terminal.application.tui_workbench.resolve_asset_names",
        lambda codes: {},
    )
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "rotation.assets",
                        "label": "轮动资产",
                        "method": "GET",
                        "endpoint": "/api/rotation/assets/",
                        "intent": "read_rotation_assets",
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

    payload = service.run_action(action_key="rotation.assets", params={}, user=tui_user)

    assert payload["view_model"]["rows"][0]["code"] == "511010 国债ETF"
    assert payload["view_model"]["rows"][0]["__raw_code"] == "511010"


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
    assert view_model["rows"][0]["capability_key"] == "builtin.system_status"
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


def test_tui_service_converts_scalar_message_list_to_message(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": [
                    "日净值数据不足（少于 2 个交易日），无法计算 TWR",
                    "无外部现金流记录，跳过 MWR 计算",
                ],
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "portfolio.performance_report",
                        "label": "Prompt Templates",
                        "method": "GET",
                        "endpoint": "/api/account/portfolios/135/performance-report/",
                        "intent": "read_performance_report",
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
        action_key="portfolio.performance_report",
        params={},
        user=tui_user,
    )

    view_model = payload["view_model"]
    assert view_model["kind"] == "message"
    assert view_model["title"] == "提示词模板"
    assert "无法计算 TWR" in view_model["message"]
    assert "跳过 MWR 计算" in view_model["message"]
    assert view_model["sections"][0]["title"] == "摘要"


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


def test_tui_service_treats_health_payload_with_named_list_as_detail(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "status": "healthy",
                    "service": "Filter API",
                    "filters_available": ["HP", "Kalman"],
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "filter.health",
                        "label": "筛选健康",
                        "method": "GET",
                        "endpoint": "/api/filter/health/",
                        "intent": "read_filter_health",
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

    payload = service.run_action(action_key="filter.health", params={}, user=tui_user)
    view_model = payload["view_model"]
    fields = {field["key"]: field for field in view_model["fields"]}

    assert view_model["kind"] == "detail"
    assert fields["status"]["value"] == "健康"
    assert fields["service"]["value"] == "筛选服务"
    assert {
        "key": "filters_available",
        "label": "可用滤波器",
        "count": 2,
    } in view_model["nested"]


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
    assert {
        "key": "capability_count",
        "label": "已登记能力",
        "value": "2 项",
    } in view_model["fields"]
    assert all(item["key"] != "endpoints" for item in view_model["nested"])


def test_tui_service_treats_single_internal_link_directory_as_summary(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "links": "http://testserver/api/share/links/",
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "share.directory",
                        "label": "分享总览",
                        "method": "GET",
                        "endpoint": "/api/share/",
                        "intent": "read_share_directory",
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

    payload = service.run_action(action_key="share.directory", params={}, user=tui_user)
    view_model = payload["view_model"]

    assert view_model["kind"] == "detail"
    assert {
        "key": "capability_count",
        "label": "已登记能力",
        "value": "1 项",
    } in view_model["fields"]
    assert {
        "key": "operator_hint",
        "label": "操作提示",
        "value": "请从左侧业务任务进入具体操作；内部接口路径只在调试抽屉中查看。",
    } in view_model["fields"]


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


@pytest.mark.django_db
def test_tui_metadata_repository_prunes_redundant_capability_pk_actions_from_file():
    payload = _metadata_payload(
        actions=[
            {
                "key": "param.api.get.api.ai-capability.capabilities.str.capability_key",
                "label": "AI Capability Detail",
                "method": "GET",
                "endpoint": "/api/ai-capability/capabilities/<str:capability_key>/",
                "intent": "read_capability_detail",
                "screen_key": "ai-ops.capabilities",
                "module_key": "command-center",
                "view_type": "detail",
                "risk": "read",
                "fields": [{"key": "capability_key", "label": "Capability Key"}],
            },
            {
                "key": "param.api.get.api.ai-capability.capabilities.pk",
                "label": "AI Capability Detail by PK",
                "method": "GET",
                "endpoint": "/api/ai-capability/capabilities/<pk>/",
                "intent": "read_capability_detail_by_pk",
                "screen_key": "ai-ops.capabilities",
                "module_key": "command-center",
                "view_type": "detail",
                "risk": "read",
                "fields": [{"key": "pk", "label": "PK"}],
            },
        ]
    )
    payload["screens"][0]["key"] = "ai-ops.capabilities"
    payload["screens"][0]["label"] = "AI Capabilities"
    payload["screens"][0]["summary"] = "Capabilities."
    payload["screens"][0]["default_action_key"] = (
        "param.api.get.api.ai-capability.capabilities.str.capability_key"
    )
    payload["default_screen"] = "ai-ops.capabilities"
    with TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temp_dir:
        path = Path(temp_dir) / "published.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        loaded = PublishedTuiMetadataRepository(published_path=path).load_published()

        keys = {action["key"] for action in loaded["actions"]}
        assert "param.api.get.api.ai-capability.capabilities.str.capability_key" in keys
        assert "param.api.get.api.ai-capability.capabilities.pk" not in keys
        assert loaded["coverage_summary"]["runtime_pruned_redundant_screen_actions"] == 1
        assert loaded["coverage_summary"]["runtime_patched_actions"] == 0


@pytest.mark.django_db
def test_tui_metadata_repository_runtime_normalization_is_idempotent():
    payload = _metadata_payload(
        actions=[
            {
                "key": "auto.api.get.api.system.list",
                "label": "System List",
                "method": "GET",
                "endpoint": "/api/system/list/",
                "intent": "safe_read",
                "screen_key": "ai-ops.capabilities",
                "module_key": "command-center",
                "view_type": "detail",
                "risk": "read",
                "fields": [],
            },
            {
                "key": "param.api.get.api.ai-capability.capabilities.str.capability_key",
                "label": "AI Capability Detail",
                "method": "GET",
                "endpoint": "/api/ai-capability/capabilities/<str:capability_key>/",
                "intent": "read_capability_detail",
                "screen_key": "ai-ops.capabilities",
                "module_key": "command-center",
                "view_type": "detail",
                "risk": "read",
                "fields": [{"key": "capability_key", "label": "Capability Key"}],
            },
            {
                "key": "param.api.get.api.ai-capability.capabilities.pk",
                "label": "AI Capability Detail by PK",
                "method": "GET",
                "endpoint": "/api/ai-capability/capabilities/<pk>/",
                "intent": "read_capability_detail_by_pk",
                "screen_key": "ai-ops.capabilities",
                "module_key": "command-center",
                "view_type": "detail",
                "risk": "read",
                "fields": [{"key": "pk", "label": "PK"}],
            },
        ]
    )
    payload["screens"][0]["key"] = "ai-ops.capabilities"
    payload["screens"][0]["label"] = "AI Capabilities"
    payload["screens"][0]["summary"] = "Capabilities."
    payload["screens"][0]["default_action_key"] = "auto.api.get.api.system.list"
    payload["default_screen"] = "ai-ops.capabilities"
    repository = PublishedTuiMetadataRepository()

    normalized_once = repository._normalize_runtime_payload(validate_tui_metadata(payload))
    normalized_twice = repository._normalize_runtime_payload(validate_tui_metadata(normalized_once))

    once_keys = {action["key"] for action in normalized_once["actions"]}
    twice_keys = {action["key"] for action in normalized_twice["actions"]}
    assert once_keys == twice_keys
    assert normalized_once["coverage_summary"]["runtime_patched_actions"] == 1
    assert normalized_once["coverage_summary"]["runtime_pruned_redundant_screen_actions"] == 1
    assert normalized_twice["coverage_summary"]["runtime_patched_actions"] == 1
    assert normalized_twice["coverage_summary"]["runtime_pruned_redundant_screen_actions"] == 1


@pytest.mark.django_db
def test_tui_metadata_repository_db_reload_keeps_runtime_coverage_stable():
    payload = _metadata_payload(
        actions=[
            {
                "key": "auto.api.get.api.system.list",
                "label": "System List",
                "method": "GET",
                "endpoint": "/api/system/list/",
                "intent": "safe_read",
                "screen_key": "command-center.overview",
                "module_key": "command-center",
                "view_type": "detail",
                "risk": "read",
                "fields": [],
            },
        ]
    )
    repository = PublishedTuiMetadataRepository()

    model = repository.publish_payload(payload=payload)
    loaded = repository.load_published()

    assert model.payload["coverage_summary"]["runtime_patched_actions"] == 1
    assert model.payload["coverage_summary"]["runtime_pruned_redundant_screen_actions"] == 0
    assert loaded["coverage_summary"]["runtime_patched_actions"] == 1
    assert loaded["coverage_summary"]["runtime_pruned_redundant_screen_actions"] == 0


def test_tui_metadata_repository_keeps_valid_dashboard_panels_when_one_action_is_missing():
    payload = _metadata_payload(
        actions=[
            {
                "key": "auto.api.get.api.asset-analysis.pool-summary",
                "label": "资产池概览",
                "method": "GET",
                "endpoint": "/api/asset-analysis/pool-summary/",
                "intent": "safe_read",
                "screen_key": "research.asset-lab",
                "module_key": "command-center",
                "view_type": "detail",
                "risk": "read",
                "fields": [],
            }
        ],
    )
    payload["screens"] = [
        {
            "key": "research.asset-lab",
            "label": "资产与市场研究",
            "module_key": "command-center",
            "group": "workflow",
            "summary": "Research workspace.",
            "view_type": "datagrid",
            "default_action_key": "auto.api.get.api.asset-analysis.pool-summary",
        }
    ]
    payload["default_screen"] = "research.asset-lab"
    repository = PublishedTuiMetadataRepository()

    loaded = repository._normalize_runtime_payload(validate_tui_metadata(payload))
    screen = next(screen for screen in loaded["screens"] if screen["key"] == "research.asset-lab")
    panels = screen["dashboard_panels"]

    assert screen["default_action_key"] == "auto.api.get.api.asset-analysis.pool-summary"
    assert [panel["action_key"] for panel in panels] == [
        "auto.api.get.api.asset-analysis.pool-summary"
    ]
    assert [panel["title"] for panel in panels] == ["一、资产池概览"]


def test_tui_metadata_repository_skips_dashboard_patch_when_panel_actions_are_absent():
    payload = _metadata_payload()
    repository = PublishedTuiMetadataRepository()

    loaded = repository._normalize_runtime_payload(validate_tui_metadata(payload))
    screen = next(screen for screen in loaded["screens"] if screen["key"] == "command-center.overview")

    assert screen.get("dashboard_panels", []) == []
    assert screen["user_experience"]["journey"] == "workspace"


def test_tui_metadata_repository_injects_ai_ops_module_for_identity_access_screens():
    payload = _metadata_payload()
    repository = PublishedTuiMetadataRepository()

    loaded = repository._normalize_runtime_payload(validate_tui_metadata(payload))
    ai_ops_module = next(module for module in loaded["modules"] if module["key"] == "ai-ops")

    assert ai_ops_module["label"] == "AI 助手"
    assert ai_ops_module["group"] == "ops"
    assert any(screen["module_key"] == "ai-ops" for screen in loaded["screens"])


@pytest.mark.django_db
def test_tui_metadata_repository_patches_system_list_to_datagrid():
    repository = PublishedTuiMetadataRepository()
    loaded = repository._load_published_file()
    raw_payload = json.loads(repository.published_path.read_text(encoding="utf-8"))
    expected_patched, expected_pruned = _runtime_transform_counts(raw_payload)

    action = next(
        action for action in loaded["actions"] if action["key"] == "auto.api.get.api.system.list"
    )
    assert action["view_type"] == "datagrid"
    assert action["view_model"]["rows_path"] == "items"
    assert action["view_model"]["total_path"] == "total"
    assert loaded["coverage_summary"]["runtime_patched_actions"] == expected_patched
    assert loaded["coverage_summary"]["runtime_pruned_redundant_screen_actions"] == expected_pruned


@pytest.mark.django_db
def test_tui_metadata_repository_patches_policy_workbench_items_pagination():
    payload = _metadata_payload(
        actions=[
            {
                "key": "policy.workbench_items",
                "label": "待看事件",
                "method": "GET",
                "endpoint": "/api/policy/workbench/items/",
                "intent": "browse_policy_queue_items",
                "screen_key": "command-center.overview",
                "module_key": "command-center",
                "view_type": "datagrid",
                "risk": "read",
                "fields": [],
                "view_model": {
                    "rows_path": "items",
                    "total_path": "total",
                },
            },
        ]
    )

    loaded = PublishedTuiMetadataRepository()._normalize_runtime_payload(
        validate_tui_metadata(payload)
    )

    action = next(
        action for action in loaded["actions"] if action["key"] == "policy.workbench_items"
    )
    assert action["pagination"] == {
        "mode": "offset",
        "offset_param": "offset",
        "limit_param": "limit",
    }
    assert [field["key"] for field in action["fields"]] == ["limit", "offset"]


@pytest.mark.django_db
def test_tui_metadata_repository_patches_dashboard_alpha_history_to_datagrid():
    loaded = PublishedTuiMetadataRepository().load_published()

    action = next(
        action
        for action in loaded["actions"]
        if action["key"] == "auto.api.get.api.dashboard.alpha.history"
    )
    assert action["view_type"] == "datagrid"
    assert action["view_model"]["rows_path"] == "data"


@pytest.mark.django_db
def test_tui_metadata_repository_rehomes_account_actions_to_account_screen():
    loaded = PublishedTuiMetadataRepository().load_published()

    moved_keys = {
        "auto.api.get.api.account.positions",
        "param.api.get.api.account.accounts.int.account_id.positions",
        "param.api.get.api.account.accounts.int.account_id.performance",
        "param.api.get.api.account.accounts.int.account_id.performance-report",
        "param.api.get.api.account.accounts.int.account_id.valuation-snapshot",
        "param.api.get.api.account.accounts.int.account_id.valuation-timeline",
        "param.api.get.api.account.accounts.int.account_id.benchmarks",
        "param.api.get.api.account.accounts.int.account_id.equity-curve",
        "param.api.get.api.account.accounts.int.account_id.inspections",
    }

    actions = {action["key"]: action for action in loaded["actions"] if action["key"] in moved_keys}

    assert set(actions) == moved_keys
    for action in actions.values():
        assert action["screen_key"] == "execution.accounts"


@pytest.mark.django_db
def test_tui_metadata_repository_rehomes_strategy_portfolio_queries_to_portfolio_screen():
    loaded = PublishedTuiMetadataRepository().load_published()

    moved_keys = {
        "auto.api.get.api.strategy.assignments.by_portfolio",
        "auto.api.get.api.strategy.execution-logs.by_portfolio",
    }

    actions = {action["key"]: action for action in loaded["actions"] if action["key"] in moved_keys}

    assert set(actions) == moved_keys
    for action in actions.values():
        assert action["screen_key"] == "execution.portfolio-performance"


@pytest.mark.django_db
def test_tui_metadata_repository_patches_audit_uuid_detail_fields_to_text():
    loaded = PublishedTuiMetadataRepository().load_published()

    actions = {
        action["key"]: action
        for action in loaded["actions"]
        if action["key"]
        in {
            "param.api.get.api.audit.operation-logs.str.log_id",
            "param.api.get.api.audit.decision-traces.str.request_id",
        }
    }

    assert (
        actions["param.api.get.api.audit.operation-logs.str.log_id"]["fields"][0]["input_type"]
        == "text"
    )
    assert (
        actions["param.api.get.api.audit.operation-logs.str.log_id"]["fields"][0]["value_type"]
        == "string"
    )
    assert (
        actions["param.api.get.api.audit.decision-traces.str.request_id"]["fields"][0]["input_type"]
        == "text"
    )
    assert (
        actions["param.api.get.api.audit.decision-traces.str.request_id"]["fields"][0]["value_type"]
        == "string"
    )


def test_tui_service_renders_terminal_agent_payload_as_detail(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "reply": "all clear",
                    "session_id": "sess-1",
                    "metadata": {
                        "provider": "test-provider",
                        "model": "test-model",
                        "tool_call_count": 1,
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "terminal.agent_chat",
                        "label": "发送 AI 请求",
                        "method": "POST",
                        "endpoint": "/api/terminal/chat/",
                        "intent": "run_terminal_agent_request",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "ai",
                        "fields": [
                            {
                                "key": "message",
                                "label": "消息",
                                "input_type": "textarea",
                                "required": True,
                            }
                        ],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="terminal.agent_chat",
        params={"message": "hello"},
        user=tui_user,
    )

    assert payload["view_model"]["kind"] == "detail"
    assert {field["label"]: field["value"] for field in payload["view_model"]["fields"]}[
        "回复"
    ] == "all clear"
    assert {field["label"]: field["value"] for field in payload["view_model"]["fields"]}[
        "建议下一步"
    ]


def test_tui_service_renders_wrapped_audit_log_detail_as_detail(tui_user):
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "success": True,
                    "log": {
                        "id": "log-1",
                        "request_id": "req-1",
                        "module": "fund",
                        "action": "READ",
                        "response_payload": [{"regime": "Recovery", "limit": 10}],
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "param.api.get.api.audit.operation-logs.str.log_id",
                        "label": "审计 / 操作日志 / 详情",
                        "method": "GET",
                        "endpoint": "/api/audit/operation-logs/<str:log_id>/",
                        "intent": "parameterized_safe_read",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "log_id",
                                "label": "日志 ID",
                                "input_type": "text",
                                "required": True,
                            }
                        ],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    payload = service.run_action(
        action_key="param.api.get.api.audit.operation-logs.str.log_id",
        params={"log_id": "log-1"},
        user=tui_user,
    )

    assert payload["view_model"]["kind"] == "detail"
    fields = {field["label"]: field["value"] for field in payload["view_model"]["fields"]}
    assert fields["Log / ID"] == "log-1"
    assert fields["Log / 请求ID"] == "req-1"
    assert fields["Log / 模块"] == "fund"


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


@pytest.mark.django_db
def test_tui_metadata_repository_publish_is_noop_for_same_compacted_payload():
    payload = _metadata_payload()
    repository = PublishedTuiMetadataRepository()

    first = repository.publish_payload(
        payload=payload,
        review_note="Initial reviewed metadata",
        generation_source="mixed",
        backend_version="test-backend",
    )
    second = repository.publish_payload(
        payload=payload,
        review_note="Repeat deploy publish",
        generation_source="mixed",
        backend_version="test-backend",
    )

    records = list(
        TuiMetadataRegistryORM._default_manager.filter(registry_key="default").order_by("id")
    )

    assert first.pk == second.pk
    assert getattr(second, "_publish_was_noop", False) is True
    assert len(records) == 1
    assert records[0].status == "published"


def test_tui_service_derives_business_context_for_unannotated_screens():
    service = TuiWorkbenchService(metadata_repository=FakeMetadataRepository())

    screen = service.get_screen("command-center.overview")["screen"]
    context = screen["business_context"]

    assert context["objective"] == "Overview."
    assert "业务" in context["decision_output"] or "状态" in context["decision_output"]
    assert "先按主流程任务读取本屏关键判断。" in context["checkpoints"]


def test_published_tui_performance_and_snapshot_actions_expose_required_query_fields():
    metadata_path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "tui"
        / "published"
        / "tui_operation_graph.published.json"
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    actions = {action["key"]: action for action in metadata["actions"]}

    assert [
        field["key"]
        for field in actions[
            "param.api.get.api.account.accounts.int.account_id.performance-report"
        ]["fields"]
    ] == [
        "account_id",
        "start_date",
        "end_date",
    ]
    assert [
        field["key"]
        for field in actions[
            "param.api.get.api.account.accounts.int.account_id.valuation-snapshot"
        ]["fields"]
    ] == [
        "account_id",
        "as_of_date",
    ]
    assert [
        field["key"]
        for field in actions[
            "param.api.get.api.simulated-trading.accounts.int.account_id.performance-report"
        ]["fields"]
    ] == [
        "account_id",
        "start_date",
        "end_date",
    ]
    assert [
        field["key"]
        for field in actions[
            "param.api.get.api.simulated-trading.accounts.int.account_id.valuation-snapshot"
        ]["fields"]
    ] == [
        "account_id",
        "as_of_date",
    ]
    assert actions["auto.api.get.api.sentiment.index.range"]["label"] == "情绪指数区间"


def test_tui_screen_entry_state_contract_for_blocked_and_auto_run_defaults():
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                screens=[
                    {
                        "key": "command-center.overview",
                        "label": "Command Overview",
                        "module_key": "command-center",
                        "group": "workflow",
                        "summary": "Overview.",
                        "view_type": "status",
                        "status": "online",
                        "default_action_key": "quotes.read",
                    },
                    {
                        "key": "command-center.selector",
                        "label": "Selector",
                        "module_key": "command-center",
                        "group": "workflow",
                        "summary": "Selector.",
                        "view_type": "detail",
                        "status": "online",
                        "default_action_key": "advisor.read",
                    },
                ],
                actions=[
                    {
                        "key": "quotes.read",
                        "label": "Quotes",
                        "method": "GET",
                        "endpoint": "/api/quotes/",
                        "intent": "quotes",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                        "description": "Quotes.",
                        "source": "approved:test",
                    },
                    {
                        "key": "advisor.read",
                        "label": "Advisor",
                        "method": "GET",
                        "endpoint": "/api/advisor/",
                        "intent": "advisor",
                        "screen_key": "command-center.selector",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "account_id",
                                "label": "账户 ID",
                                "input_type": "select",
                                "required": True,
                                "default": "",
                                "options": [{"value": "1", "label": "A"}],
                            }
                        ],
                        "description": "Advisor.",
                        "source": "approved:test",
                    },
                ],
            )
        )
    )

    auto_screen = service.get_screen("command-center.overview")["screen"]
    selector_screen = service.get_screen("command-center.selector")["screen"]

    assert auto_screen["entry_state"]["mode"] == "auto_run"
    assert selector_screen["entry_state"]["mode"] == "parameter_gate"
    assert selector_screen["entry_state"]["field_key"] == "account_id"


def test_tui_advisor_today_sheet_returns_business_first_contract():
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "success": True,
                    "data": {
                        "account": {
                            "account_id": "365",
                            "account_name": "默认组合",
                            "available_cash": 10000,
                            "total_asset": 50000,
                            "holding_count": 2,
                        },
                        "today_conclusion": "REVIEW",
                        "data_health": {"status": "blocked", "blocked_reasons": ["行情陈旧"]},
                        "order_summary": {"total": 3, "actionable": 1, "blocked": 2},
                        "holdings": [{}, {}],
                        "order_intents": [{}, {}, {}],
                        "execution_plan": {
                            "execution_mode": "manual_review",
                            "confirmation_status": "PENDING",
                        },
                        "blockers": [{"message": "现金不足"}],
                        "warnings": [],
                        "next_actions": [{"label": "刷新推荐", "hint": "重新生成"}],
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "advisor.today_sheet",
                        "label": "今日自动投顾建议单",
                        "method": "GET",
                        "endpoint": "/api/decision/advisor/sheet/",
                        "intent": "advisor",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "account_id",
                                "label": "账户 ID",
                                "input_type": "text",
                                "required": True,
                                "default": "",
                            }
                        ],
                        "description": "Advisor.",
                        "source": "approved:test",
                    },
                    {
                        "key": "advisor.factor_breakdown",
                        "label": "建议单因子明细",
                        "method": "GET",
                        "endpoint": "/api/decision/advisor/sheet/",
                        "intent": "advisor_factor",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [
                            {
                                "key": "account_id",
                                "label": "账户 ID",
                                "input_type": "text",
                                "required": True,
                                "default": "",
                            }
                        ],
                        "description": "Factor.",
                        "source": "approved:test",
                    },
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    result = service.run_action(
        action_key="advisor.today_sheet",
        params={"account_id": "365"},
        user=None,
    )

    fields = {field["label"]: field["value"] for field in result["view_model"]["fields"]}
    assert result["view_model"]["kind"] == "detail"
    assert fields["账户结论"] == "需要复核"
    assert "建议动作/建议订单" in fields
    assert fields["阻断项"] == "现金不足"
    assert any(step.get("label") == "建议单因子明细" for step in result["next_steps"])


def test_tui_ai_result_maps_provider_config_error_to_user_message():
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "reply": "AI 调用失败: System fallback quota is not configured for this user.",
                    "metadata": {"decision": "chat"},
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                actions=[
                    {
                        "key": "terminal.agent_chat",
                        "label": "发送 AI 请求",
                        "method": "POST",
                        "endpoint": "/api/terminal/chat/",
                        "intent": "chat",
                        "screen_key": "command-center.overview",
                        "module_key": "command-center",
                        "view_type": "detail",
                        "risk": "ai",
                        "fields": [
                            {
                                "key": "message",
                                "label": "消息",
                                "input_type": "textarea",
                                "required": True,
                                "default": "hi",
                            }
                        ],
                        "description": "Chat.",
                        "source": "approved:test",
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    result = service.run_action(action_key="terminal.agent_chat", params={}, user=None)

    assert result["user_error_code"] == "AI_PROVIDER_NOT_CONFIGURED"
    assert "当前账号未配置默认 AI 服务" in result["business_summary"]


def test_tui_mcp_self_service_status_model_prioritizes_token_and_base_url():
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "username": "ops_user",
                    "mcp_enabled": True,
                    "rbac_role": "operator",
                    "token_plaintext_allowed": True,
                    "active_token_count": 1,
                    "default_account_name": "默认账户",
                    "base_url": "https://example.test",
                    "api_root_endpoint": "https://example.test/api/",
                    "route_endpoint": "https://example.test/api/ai-capability/route/",
                    "web_endpoint": "https://example.test/api/ai-capability/web/",
                    "capability_endpoint": "https://example.test/api/ai-capability/capabilities/",
                    "current_token_value": "agtp_live_plaintext_token_value",
                    "current_token_display": "agtp_live_preview_token_value",
                    "agent_bootstrap_token_ready": True,
                    "agent_bootstrap_access_level_label": "只读",
                    "preferred_token": {
                        "name": "router-readonly",
                        "access_level_label": "只读",
                        "display_token": "agtp_live_preview_token_value",
                    },
                    "access_tokens": [{"id": 1}],
                    "agent_bootstrap_prompt": "请按以下信息接入 AgomTradePro：",
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                default_screen="capability-router.self-service",
                groups=[{"key": "ops", "label": "运维"}],
                modules=[
                    {
                        "key": "capability-router",
                        "label": "能力路由",
                        "group": "ops",
                        "summary": "Capability router.",
                    }
                ],
                screens=[
                    {
                        "key": "capability-router.self-service",
                        "label": "我的 MCP 接入",
                        "module_key": "capability-router",
                        "group": "ops",
                        "summary": "Self service.",
                        "view_type": "detail",
                        "status": "online",
                        "default_action_key": "capability-router.mcp-self-status",
                    }
                ],
                actions=[
                    {
                        "key": "capability-router.mcp-self-status",
                        "label": "读取我的 MCP 状态",
                        "method": "GET",
                        "endpoint": "/api/account/mcp/self/",
                        "intent": "read_current_user_mcp_self_service",
                        "screen_key": "capability-router.self-service",
                        "module_key": "capability-router",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                        "description": "Self service.",
                        "source": "approved:test",
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    result = service.run_action(
        action_key="capability-router.mcp-self-status",
        params={},
        user=None,
    )

    assert result["view_model"]["kind"] == "detail"
    fields = {field["label"]: field["value"] for field in result["view_model"]["fields"]}
    assert fields["当前令牌"] == "agtp_live_plaintext_token_value"
    assert fields["基础地址"] == "https://example.test"


def test_tui_mcp_self_service_endpoint_model_exposes_route_and_catalog_urls():
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 200,
                "payload": {
                    "username": "ops_user",
                    "mcp_enabled": True,
                    "base_url": "https://example.test",
                    "api_root_endpoint": "https://example.test/api/",
                    "route_endpoint": "https://example.test/api/ai-capability/route/",
                    "web_endpoint": "https://example.test/api/ai-capability/web/",
                    "capability_endpoint": "https://example.test/api/ai-capability/capabilities/",
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                default_screen="capability-router.self-service",
                groups=[{"key": "ops", "label": "运维"}],
                modules=[
                    {
                        "key": "capability-router",
                        "label": "能力路由",
                        "group": "ops",
                        "summary": "Capability router.",
                    }
                ],
                screens=[
                    {
                        "key": "capability-router.self-service",
                        "label": "我的 MCP 接入",
                        "module_key": "capability-router",
                        "group": "ops",
                        "summary": "Self service.",
                        "view_type": "detail",
                        "status": "online",
                        "default_action_key": "capability-router.mcp-self-endpoints",
                    }
                ],
                actions=[
                    {
                        "key": "capability-router.mcp-self-endpoints",
                        "label": "读取我的接入 Endpoint",
                        "method": "GET",
                        "endpoint": "/api/account/mcp/self/",
                        "intent": "read_current_user_mcp_endpoints",
                        "screen_key": "capability-router.self-service",
                        "module_key": "capability-router",
                        "view_type": "detail",
                        "risk": "read",
                        "fields": [],
                        "description": "Endpoints.",
                        "source": "approved:test",
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    result = service.run_action(
        action_key="capability-router.mcp-self-endpoints",
        params={},
        user=None,
    )

    fields = {field["label"]: field["value"] for field in result["view_model"]["fields"]}
    assert fields["智能路由地址"] == "https://example.test/api/ai-capability/route/"
    assert fields["能力目录地址"] == "https://example.test/api/ai-capability/capabilities/"


def test_tui_mcp_self_service_create_token_model_surfaces_new_token_and_prompt():
    class FakeExecutor:
        def execute(self, **kwargs):
            return {
                "status_code": 201,
                "payload": {
                    "success": True,
                    "message": "已创建新的 MCP 令牌。",
                    "token_payload": {
                        "username": "ops_user",
                        "token_name": "self-readonly",
                        "token": "agtp_new_plaintext_token_value",
                        "access_level": "read_only",
                        "access_level_label": "只读",
                        "generated_at": "2026-07-09T10:00:00+08:00",
                    },
                    "created_agent_prompt": {
                        "agent_bootstrap_prompt": "请使用该令牌接入 AgomTradePro。",
                        "agent_bootstrap_token_ready": True,
                        "agent_bootstrap_token_name": "self-readonly",
                        "agent_bootstrap_access_level": "read_only",
                        "agent_bootstrap_access_level_label": "只读",
                    },
                    "self_service": {
                        "username": "ops_user",
                        "active_token_count": 2,
                        "route_endpoint": "https://example.test/api/ai-capability/route/",
                        "access_tokens": [{"id": 1}, {"id": 2}],
                    },
                },
            }

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                default_screen="capability-router.self-service",
                groups=[{"key": "ops", "label": "运维"}],
                modules=[
                    {
                        "key": "capability-router",
                        "label": "能力路由",
                        "group": "ops",
                        "summary": "Capability router.",
                    }
                ],
                screens=[
                    {
                        "key": "capability-router.self-service",
                        "label": "我的 MCP 接入",
                        "module_key": "capability-router",
                        "group": "ops",
                        "summary": "Self service.",
                        "view_type": "detail",
                        "status": "online",
                        "default_action_key": "capability-router.create-my-mcp-token",
                    }
                ],
                actions=[
                    {
                        "key": "capability-router.create-my-mcp-token",
                        "label": "创建我的 MCP 令牌",
                        "method": "POST",
                        "endpoint": "/api/account/mcp/tokens/",
                        "intent": "create_current_user_mcp_token",
                        "screen_key": "capability-router.self-service",
                        "module_key": "capability-router",
                        "view_type": "detail",
                        "risk": "write",
                        "fields": [],
                        "description": "Create token.",
                        "source": "approved:test",
                        "result_semantics": ["copyable_secret", "multiline_prompt"],
                    }
                ]
            )
        ),
        action_executor=FakeExecutor(),
    )

    result = service.run_action(
        action_key="capability-router.create-my-mcp-token",
        params={},
        user=None,
        confirmed=True,
    )

    assert result["view_model"]["kind"] == "detail"
    fields = {field["label"]: field["value"] for field in result["view_model"]["fields"]}
    assert result["view_model"]["status"] == "已创建"
    assert fields["令牌明文"] == "agtp_new_plaintext_token_value"
    assert fields["智能路由地址"] == "https://example.test/api/ai-capability/route/"
    assert fields["接入提示词"] == "请使用该令牌接入 AgomTradePro。"


@pytest.mark.django_db
def test_tui_capability_router_self_service_screen_publishes_user_facing_semantics(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/screens/capability-router.self-service/")

    assert response.status_code == 200
    payload = response.json()
    screen = payload["screen"]
    panels = {panel["key"]: panel for panel in screen["dashboard_panels"]}
    actions = {action["key"]: action for action in payload["actions"]}

    assert screen["user_experience"]["journey"] == "self_service"
    assert panels["mcp-self-status"]["presentation_semantic"] == "copyable_secret"
    assert panels["mcp-self-endpoints"]["presentation_semantic"] == "endpoint_list"
    assert panels["mcp-self-prompt-guide"]["presentation_semantic"] == "multiline_prompt"
    assert actions["capability-router.mcp-self-status"]["result_semantics"] == [
        "primary_status",
        "copyable_secret",
    ]
    assert actions["capability-router.mcp-self-endpoints"]["result_semantics"] == [
        "endpoint_list"
    ]
    assert actions["capability-router.mcp-self-prompt-guide"]["result_semantics"] == [
        "multiline_prompt"
    ]
    assert actions["capability-router.create-my-mcp-token"]["task_tier"] == "operation"
    assert actions["capability-router.revoke-my-mcp-token"]["task_tier"] == "operation"


@pytest.mark.django_db
def test_tui_dashboard_screens_publish_explicit_user_task_contracts(client, tui_user):
    client.force_login(tui_user)

    overview_payload = client.get("/api/tui/screens/command-center.overview/").json()
    overview_screen = overview_payload["screen"]
    overview_panels = {panel["key"]: panel for panel in overview_screen["dashboard_panels"]}
    assert overview_screen["user_experience"]["journey"] == "dashboard"
    assert overview_panels["today-queue"]["user_priority"] == "p0"
    assert overview_panels["today-queue"]["presentation_semantic"] == "primary_list"

    events_payload = client.get("/api/tui/screens/execution.events/").json()
    events_screen = events_payload["screen"]
    events_panels = {panel["key"]: panel for panel in events_screen["dashboard_panels"]}
    assert events_screen["user_experience"]["primary_task"]
    assert events_panels["events-query"]["user_priority"] == "p0"
    assert events_panels["events-status"]["presentation_semantic"] == "primary_status"

    asset_payload = client.get("/api/tui/screens/research.asset-lab/").json()
    asset_screen = asset_payload["screen"]
    asset_panels = {panel["key"]: panel for panel in asset_screen["dashboard_panels"]}
    assert asset_screen["default_action_key"] == "auto.api.get.api.asset-analysis.pool-summary"
    assert asset_panels["asset-pool-summary"]["presentation_semantic"] == "primary_status"
    assert asset_panels["asset-pool-summary"]["user_priority"] == "p0"


def test_tui_macro_strategy_empty_state_exposes_recovery_actions():
    class FakeExecutor:
        def execute(self, **kwargs):
            return {"status_code": 200, "payload": {"results": [], "count": 0}}

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(
            _metadata_payload(
                default_screen="macro-regime.strategy",
                screens=[
                    {
                        "key": "macro-regime.strategy",
                        "label": "策略与仓位规则",
                        "module_key": "command-center",
                        "group": "workflow",
                        "summary": "Strategy.",
                        "view_type": "datagrid",
                        "status": "online",
                        "default_action_key": "strategy.list",
                    }
                ],
                actions=[
                    {
                        "key": "strategy.list",
                        "label": "策略清单",
                        "method": "GET",
                        "endpoint": "/api/strategy/strategies/",
                        "intent": "strategy",
                        "screen_key": "macro-regime.strategy",
                        "module_key": "command-center",
                        "view_type": "datagrid",
                        "risk": "read",
                        "fields": [],
                        "description": "Strategy.",
                        "source": "approved:test",
                        "view_model": {
                            "kind": "datagrid",
                            "rows_path": "results",
                            "total_path": "count",
                        },
                    }
                ],
            )
        ),
        action_executor=FakeExecutor(),
    )

    result = service.run_action(action_key="strategy.list", params={}, user=None)

    assert [step["label"] for step in result["next_steps"]] == [
        "仓位规则",
        "策略绑定",
        "相关配置/同步任务",
    ]


@pytest.mark.django_db
def test_published_tui_navigation_does_not_expose_planned_screens(client, tui_user):
    client.force_login(tui_user)

    response = client.get("/api/tui/catalog/")

    assert response.status_code == 200
    payload = response.json()
    visible_screens = [
        screen
        for group in payload["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    ]
    assert all(screen["status"] != "planned" for screen in visible_screens)


@pytest.mark.django_db
def test_published_tui_required_field_actions_return_missing_field_contract(client, tui_admin_user):
    client.force_login(tui_admin_user)

    metadata = PublishedTuiMetadataRepository().load_published()
    service = TuiWorkbenchService(
        metadata_repository=PublishedTuiMetadataRepository(),
        action_executor=get_tui_action_executor(),
        registry_key="default",
    )
    visible_action_keys = {
        action["key"] for action in service._visible_actions(metadata, user=tui_admin_user)
    }
    required_actions = []
    for action in metadata["actions"]:
        if action["key"] not in visible_action_keys:
            continue
        required = [
            field["key"]
            for field in (action.get("fields") or [])
            if field.get("required") and field.get("default") in (None, "")
        ]
        if required:
            required_actions.append((action["key"], required))

    failures = []
    for action_key, required in required_actions:
        response = client.post(
            f"/api/tui/actions/{action_key}/run/",
            data=json.dumps({"params": {}}),
            content_type="application/json",
        )
        payload = response.json()
        runtime_required = [
            field["key"]
            for field in (payload.get("action", {}).get("fields") or [])
            if field.get("required") and field.get("default") in (None, "")
        ]
        missing = [field["key"] for field in payload.get("missing_fields", [])]
        view_model = payload.get("view_model", {})
        if not runtime_required:
            continue
        if not (
            response.status_code == 200
            and payload["response"]["status_code"] == 400
            and view_model.get("kind") == "message"
            and view_model.get("status") == "需要参数"
            and set(missing) == set(runtime_required)
        ):
            failures.append(
                {
                    "action_key": action_key,
                    "required": required,
                    "runtime_required": runtime_required,
                    "http": response.status_code,
                    "inner_status": payload.get("response", {}).get("status_code"),
                    "kind": view_model.get("kind"),
                    "status": view_model.get("status"),
                    "missing": missing,
                    "error": payload.get("error"),
                }
            )

    assert not failures, failures[:5]


@pytest.mark.django_db
def test_published_tui_system_list_renders_datagrid_runtime(client, tui_admin_user):
    client.force_login(tui_admin_user)

    response = client.post(
        "/api/tui/actions/auto.api.get.api.system.list/run/",
        data=json.dumps({"params": {}}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"]["status_code"] == 200
    assert payload["view_model"]["kind"] == "datagrid"
    assert payload["view_model"]["pager"]["total_rows"] == 0


@pytest.mark.django_db
def test_published_tui_dashboard_alpha_history_renders_datagrid_runtime(client, tui_admin_user):
    client.force_login(tui_admin_user)

    response = client.post(
        "/api/tui/actions/auto.api.get.api.dashboard.alpha.history/run/",
        data=json.dumps({"params": {}}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"]["status_code"] == 200
    assert payload["view_model"]["kind"] == "datagrid"
    assert "rows" in payload["view_model"]


@pytest.mark.django_db
def test_published_tui_write_and_admin_actions_are_gated_consistently(client, tui_admin_user):
    client.force_login(tui_admin_user)

    metadata = PublishedTuiMetadataRepository().load_published()
    service = TuiWorkbenchService(
        metadata_repository=PublishedTuiMetadataRepository(),
        action_executor=get_tui_action_executor(),
        registry_key="default",
    )
    visible_action_keys = {
        action["key"] for action in service._visible_actions(metadata, user=tui_admin_user)
    }
    guarded_actions = [
        action
        for action in metadata["actions"]
        if action.get("risk") in {"write", "admin"} and action["key"] in visible_action_keys
    ]

    failures = []
    for action in guarded_actions:
        response = client.post(
            f"/api/tui/actions/{action['key']}/run/",
            data=json.dumps({"params": {}}),
            content_type="application/json",
        )
        payload = response.json()
        view_model = payload.get("view_model", {})
        required = [
            field["key"]
            for field in (action.get("fields") or [])
            if field.get("required") and field.get("default") in (None, "")
        ]

        if required:
            if not (
                response.status_code == 200
                and payload["response"]["status_code"] == 400
                and view_model.get("status") == "需要参数"
            ):
                failures.append(
                    {
                        "action_key": action["key"],
                        "expected": "missing_fields",
                        "http": response.status_code,
                        "inner_status": payload.get("response", {}).get("status_code"),
                        "kind": view_model.get("kind"),
                        "status": view_model.get("status"),
                        "error": payload.get("error"),
                    }
                )
            continue

        if str(action.get("method", "")).upper() == "GET":
            if not (
                response.status_code == 200
                and payload.get("confirmation_required") is False
                and payload["response"]["status_code"] == 200
                and payload.get("error") is None
            ):
                failures.append(
                    {
                        "action_key": action["key"],
                        "expected": "admin_read_ok",
                        "http": response.status_code,
                        "inner_status": payload.get("response", {}).get("status_code"),
                        "kind": view_model.get("kind"),
                        "status": view_model.get("status"),
                        "error": payload.get("error"),
                    }
                )
            continue

        if not (
            response.status_code == 200
            and payload.get("confirmation_required") is True
            and payload["response"]["status_code"] == 409
            and view_model.get("status") == "待确认"
        ):
            failures.append(
                {
                    "action_key": action["key"],
                    "expected": "confirmation_required",
                    "http": response.status_code,
                    "inner_status": payload.get("response", {}).get("status_code"),
                    "kind": view_model.get("kind"),
                    "status": view_model.get("status"),
                    "error": payload.get("error"),
                }
            )

    assert not failures, failures[:5]
