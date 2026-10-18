from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from apps.terminal.application.tui_metadata import validate_tui_metadata
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_information_architecture import (
    load_tui_information_architecture,
    screen_aliases,
)
from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)

ROOT = Path(__file__).resolve().parents[3]

PUBLISHED_PATH = ROOT / "config" / "tui" / "published" / "tui_operation_graph.published.json"


EXPECTED_AUTHENTICATED_SCREEN_KEYS = {
    "command-center.overview",
    "macro-regime.overview",
    "policy.workbench",
    "command-center.decision-flow",
    "research.signals",
    "execution.accounts",
    "macro-regime.strategy",
    "execution.audit",
    "research.asset-lab",
    "ai-ops.terminal",
    "ai-ops.providers",
    "cli.terminal",
    "capability-router.self-service",
    "account.self-service",
    "prompt.workbench",
    "task.asset-research",
    "task.today-focus",
    "task.portfolio-check",
}

EXPECTED_ADMIN_ONLY_SCREEN_KEYS = {
    "api-library.data-center",
    "ai-ops.system-providers",
    "ai-ops.user-quotas",
    "capability-router.mcp-center",
    "capability-router.admin-access",
    "identity-access.user-governance",
    "system.settings",
    "data-center.calendar-workbench",
    "data-center.egress-config",
    "system.qlib-center",
    "broker-execution.qmt-setup",
}

EXPECTED_TASK_ACTION_OWNERS = {
    "today-focus.market-context": "task.today-focus",
    "today-focus.account-selector": "task.today-focus",
    "today-focus.queue": "task.today-focus",
    "portfolio-check.portfolios": "task.portfolio-check",
    "portfolio-check.recorded-facts": "task.portfolio-check",
    "account.portfolio-recorded-facts": "execution.accounts",
}


class _StaticMetadataRepository:

    def __init__(self, payload: dict) -> None:

        self.payload = payload

    def load_published(self, registry_key: str = "default") -> dict:

        del registry_key

        return self.payload


def _runtime_payload() -> dict:

    raw = json.loads(PUBLISHED_PATH.read_text(encoding="utf-8"))

    repository = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)

    return repository._normalize_runtime_payload(validate_tui_metadata(raw))


def _catalog_screen_keys(catalog: dict) -> list[str]:

    return [
        screen["key"]
        for group in catalog["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    ]


def test_tui_ia_registry_is_the_complete_screen_routing_source() -> None:

    registry = load_tui_information_architecture()

    aliases = screen_aliases(registry)

    assert [group["key"] for group in registry["groups"]] == ["daily", "research", "system"]

    assert len(registry["published_screens"]) == 12

    assert len(registry["runtime_screens"]) == 17

    assert {"task.today-focus", "task.portfolio-check"} <= {
        screen["key"] for screen in registry["runtime_screens"]
    }

    assert len(registry["workflow"]) == 8

    assert sum(len(screen["sources"]) for screen in registry["published_screens"]) == 37

    runtime_source_pairs = [
        (source, screen["key"])
        for screen in registry["published_screens"]
        for source in screen.get("runtime_sources", [])
    ] + [
        (source, screen["key"])
        for screen in registry["runtime_screens"]
        for source in screen["sources"]
    ]

    runtime_sources = dict(runtime_source_pairs)

    assert len(runtime_sources) == len(runtime_source_pairs)

    assert {source: aliases[source] for source in runtime_sources} == runtime_sources

    assert runtime_sources["task.today-focus"] == "task.today-focus"

    assert runtime_sources["task.portfolio-check"] == "task.portfolio-check"

    assert aliases["macro-regime.pulse"] == "macro-regime.overview"

    assert aliases["command-center.auto-advisor"] == "command-center.decision-flow"

    assert aliases["risk-center.overview"] == "macro-regime.strategy"

    assert aliases["realtime-monitor.alerts"] == "execution.audit"

    assert aliases["broker-execution.overview"] == "execution.accounts"

    assert aliases["broker-execution.audit"] == "execution.audit"

    assert aliases["ai-ops.user-quotas"] == "ai-ops.user-quotas"

    assert aliases["capability-router.gateway"] == "capability-router.mcp-center"

    assert aliases["capability-router.admin-access"] == "capability-router.admin-access"


def test_research_navigation_is_split_by_user_task_and_labels_are_unambiguous() -> None:

    registry = load_tui_information_architecture()

    modules = {module["key"]: module for module in registry["modules"]}

    screens = {
        screen["key"]: screen
        for screen in [*registry["published_screens"], *registry["runtime_screens"]]
    }

    assert [module["key"] for module in registry["modules"] if module["group"] == "research"] == [
        "investment-research",
        "ai-workspace",
        "personal-services",
        "personal-settings",
    ]

    assert modules["investment-research"]["label"] == "投资研究"

    assert modules["ai-workspace"]["label"] == "AI 工作台"

    assert modules["personal-services"]["label"] == "个人服务接入"

    assert modules["personal-settings"]["label"] == "个人设置"

    assert screens["research.asset-lab"]["module_key"] == "investment-research"

    assert screens["task.asset-research"]["module_key"] == "investment-research"

    assert screens["task.asset-research"]["default_action_key"] == "equity.research-snapshot"

    assert screens["ai-ops.terminal"]["module_key"] == "ai-workspace"

    assert screens["cli.terminal"]["module_key"] == "ai-workspace"

    assert screens["prompt.workbench"]["module_key"] == "ai-workspace"

    assert screens["ai-ops.providers"]["module_key"] == "personal-services"

    assert screens["capability-router.self-service"]["module_key"] == "personal-services"

    assert screens["account.self-service"]["module_key"] == "personal-settings"

    assert screens["execution.accounts"]["label"] == "账户与持仓"

    assert screens["account.self-service"]["label"] == "个人资料与交易设置"

    assert screens["ai-ops.providers"]["label"] == "我的 AI 服务商"

    assert screens["ai-ops.system-providers"]["label"] == "系统 AI 服务商治理"

    assert screens["ai-ops.terminal"]["label"] == "AI 任务助手"

    assert screens["cli.terminal"]["label"] == "命令行任务台"

    assert screens["capability-router.self-service"]["label"] == "我的 MCP 接入"

    assert screens["capability-router.mcp-center"]["label"] == "MCP 工具治理"

    assert screens["capability-router.admin-access"]["label"] == "MCP 用户与令牌"


def test_research_task_runtime_action_preserves_professional_action_identity() -> None:

    payload = _runtime_payload()

    actions = {action["key"]: action for action in payload["actions"]}

    task_action = actions["equity.research-snapshot"]

    assert task_action["screen_key"] == "task.asset-research"

    assert task_action["endpoint"] == "/api/equity/research-snapshot/<str:stock_code>/"

    assert task_action["risk"] == "read"

    assert task_action["fields"][0]["key"] == "stock_code"

    assert task_action["fields"][0]["binding"] == "path"

    assert actions["equity.valuation-overview"]["screen_key"] == "research.asset-lab"


def test_tui_ia_uses_one_user_facing_terminology_vocabulary() -> None:

    registry = load_tui_information_architecture()

    visible_copy = json.dumps(registry, ensure_ascii=False)

    assert "Regime" not in visible_copy

    assert "Prompt" not in visible_copy

    assert "数据日期" not in visible_copy

    assert "观测日期" not in visible_copy

    assert "宏观象限" in visible_copy

    assert "提示词" in visible_copy

    assert "观测时间" in visible_copy


def test_runtime_screen_registry_publishes_complete_user_experience_contract() -> None:

    registry = load_tui_information_architecture()

    payload = _runtime_payload()

    runtime_screens = {screen["key"]: screen for screen in registry["runtime_screens"]}

    normalized_screens = {screen["key"]: screen for screen in payload["screens"]}

    action_keys = {action["key"] for action in payload["actions"]}

    assert len(runtime_screens) == 17

    assert {"task.today-focus", "task.portfolio-check"} <= set(runtime_screens)

    assert set(runtime_screens) <= set(normalized_screens)

    for key, screen in runtime_screens.items():

        assert screen["summary"]

        assert screen["view_type"] in {"detail", "datagrid", "status", "chart"}

        assert screen["default_action_key"] in action_keys

        experience = screen["user_experience"]

        assert experience["journey"]

        assert experience["primary_task"]

        assert experience["primary_outcome"]

        assert experience["empty_state_hint"]

        assert experience["next_step_hint"]

        normalized = normalized_screens[key]

        assert normalized["summary"] == screen["summary"]

        assert normalized["default_action_key"] == screen["default_action_key"]

        assert normalized["user_experience"] == experience


def test_daily_task_screens_keep_single_task_and_runtime_action_ownership() -> None:

    registry = load_tui_information_architecture()

    payload = _runtime_payload()

    screens = {screen["key"]: screen for screen in registry["runtime_screens"]}

    actions = {action["key"]: action for action in payload["actions"]}

    expected_screens = {
        "task.today-focus": "today-focus.market-context",
        "task.portfolio-check": "portfolio-check.portfolios",
    }

    primary_tasks = set()

    for screen_key, default_action_key in expected_screens.items():

        screen = screens[screen_key]

        assert screen["audience"] == "authenticated"

        assert screen["group"] == "daily"

        assert screen["module_key"] == "daily-decisions"

        assert screen["entry_mode"] == "dashboard"

        assert screen["dashboard_layout"] == "task_flow"

        assert screen["default_action_key"] == default_action_key

        primary_tasks.add(screen["user_experience"]["primary_task"])

        assert screen["user_experience"]["primary_outcome"]

        assert default_action_key in actions

        assert default_action_key in {
            panel.get("action_key") for panel in screen["dashboard_panels"]
        }

    assert len(primary_tasks) == len(expected_screens)

    for action_key, owner_screen_key in EXPECTED_TASK_ACTION_OWNERS.items():

        action = actions[action_key]

        assert action["screen_key"] == owner_screen_key

        assert action["audience"] == "authenticated"

        assert action["effect"] == "read"

        assert action["risk"] == "read"

        assert action["method"] == "GET"

        assert action["raw_debug"] is False

    today_focus = screens["task.today-focus"]

    account_selector = next(
        panel
        for panel in today_focus["dashboard_panels"]
        if panel["key"] == "today-focus-account-selector"
    )

    assert account_selector["user_priority"] == "p0"

    queue_row_action = account_selector["row_actions"][0]

    assert queue_row_action["action_key"] == "today-focus.queue"

    assert queue_row_action["param_map"] == {"account_id": "account_id"}

    assert queue_row_action["result_panel_key"] == "today-focus-queue"

    queue_account_id = next(
        field for field in actions["today-focus.queue"]["fields"] if field["key"] == "account_id"
    )

    assert queue_account_id["required"] is True

    assert queue_account_id.get("default") in ("", None)

    portfolio_check = screens["task.portfolio-check"]

    portfolio_selector = next(
        panel
        for panel in portfolio_check["dashboard_panels"]
        if panel["key"] == "portfolio-check-selector"
    )

    assert portfolio_selector["user_priority"] == "p0"

    facts_row_action = portfolio_selector["row_actions"][0]

    assert facts_row_action["action_key"] == "portfolio-check.recorded-facts"

    assert facts_row_action["param_map"] == {"pk": "id"}

    assert facts_row_action["result_panel_key"] == "portfolio-check-recorded-facts"


def test_execution_audit_copy_matches_its_published_dashboard_panels() -> None:

    registry = load_tui_information_architecture()

    screen = next(
        screen for screen in registry["published_screens"] if screen["key"] == "execution.audit"
    )

    panel_keys = {panel["key"] for panel in screen["dashboard_panels"]}

    business_context = screen["business_context"]

    assert "分享" not in screen["summary"]

    assert "复盘证据" not in business_context["decision_output"]

    assert business_context["checkpoints"] == [
        "审计健康",
        "事件指标",
        "对账差异",
        "操作审计",
    ]

    assert {
        "audit-health",
        "event-metrics",
        "broker-execution-reconciliation",
        "broker-execution-audit",
    } <= panel_keys


def test_runtime_catalog_preserves_authenticated_and_admin_screen_ownership() -> None:

    payload = _runtime_payload()

    service = TuiWorkbenchService(metadata_repository=_StaticMetadataRepository(payload))

    user = SimpleNamespace(
        id=1,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        role="user",
    )

    admin = SimpleNamespace(
        id=2,
        is_authenticated=True,
        is_staff=True,
        is_superuser=True,
        role="admin",
    )

    user_screens = _catalog_screen_keys(service.get_catalog(user=user))

    admin_screens = _catalog_screen_keys(service.get_catalog(user=admin))

    expected_admin_screen_keys = (
        EXPECTED_AUTHENTICATED_SCREEN_KEYS | EXPECTED_ADMIN_ONLY_SCREEN_KEYS
    )

    assert len(user_screens) == len(EXPECTED_AUTHENTICATED_SCREEN_KEYS)

    assert set(user_screens) == EXPECTED_AUTHENTICATED_SCREEN_KEYS

    assert len(admin_screens) == len(expected_admin_screen_keys)

    assert set(admin_screens) == expected_admin_screen_keys

    assert set(admin_screens) == {screen["key"] for screen in payload["screens"]}

    assert set(admin_screens) - set(user_screens) == EXPECTED_ADMIN_ONLY_SCREEN_KEYS

    assert {"task.today-focus", "task.portfolio-check"} <= set(user_screens)

    assert "api-library.data-center" not in user_screens

    assert "ai-ops.system-providers" not in user_screens

    assert "capability-router.mcp-center" not in user_screens

    assert "identity-access.user-governance" not in user_screens

    assert "identity-access.user-governance" in admin_screens

    assert "system.qlib-center" not in user_screens

    assert "system.qlib-center" in admin_screens

    assert "broker-execution.qmt-setup" in admin_screens

    assert "broker-execution.qmt-setup" not in user_screens

    assert "prompt.workbench" in user_screens

    assert "prompt.workbench" in admin_screens


def test_runtime_ia_is_idempotent_and_has_no_dangling_screen_references() -> None:

    raw = json.loads(PUBLISHED_PATH.read_text(encoding="utf-8"))

    repository = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)

    normalized_once = repository._normalize_runtime_payload(validate_tui_metadata(raw))

    normalized_twice = repository._normalize_runtime_payload(validate_tui_metadata(normalized_once))

    assert normalized_twice == normalized_once

    demoted_count = normalized_once["coverage_summary"]["runtime_density_demoted_actions"]
    assert isinstance(demoted_count, int) and not isinstance(demoted_count, bool)
    assert 0 < demoted_count <= len(normalized_once["actions"])
    assert normalized_twice["coverage_summary"]["runtime_density_demoted_actions"] == demoted_count

    screen_keys = {screen["key"] for screen in normalized_once["screens"]}

    action_keys = {action["key"] for action in normalized_once["actions"]}

    registry = load_tui_information_architecture()

    expected_screen_keys = {
        screen["key"] for screen in [*registry["published_screens"], *registry["runtime_screens"]]
    }

    assert screen_keys == expected_screen_keys

    assert len(normalized_once["screens"]) == len(screen_keys)

    assert all(action["screen_key"] in screen_keys for action in normalized_once["actions"])

    assert all(
        not panel.get("action_key") or panel["action_key"] in action_keys
        for screen in normalized_once["screens"]
        for panel in screen.get("dashboard_panels", [])
    )


def test_legacy_screen_keys_resolve_to_canonical_screens() -> None:

    payload = _runtime_payload()

    service = TuiWorkbenchService(metadata_repository=_StaticMetadataRepository(payload))

    user = SimpleNamespace(
        id=1,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        role="user",
    )

    admin = SimpleNamespace(
        id=2,
        is_authenticated=True,
        is_staff=True,
        is_superuser=True,
        role="admin",
    )

    assert service.get_screen("macro-regime.pulse", user=user)["screen"]["key"] == (
        "macro-regime.overview"
    )

    assert service.get_screen("capability-router.gateway", user=admin)["screen"]["key"] == (
        "capability-router.mcp-center"
    )


def test_published_screens_define_panel_and_action_density_contracts() -> None:

    payload = validate_tui_metadata(json.loads(PUBLISHED_PATH.read_text(encoding="utf-8")))

    registry = load_tui_information_architecture()

    task_group_limit = registry["action_density"]["task_group_limit"]

    for screen in payload["screens"]:

        p0_panels = [
            panel
            for panel in screen.get("dashboard_panels", [])
            if panel.get("user_priority") == "p0"
        ]

        if screen["key"] != "command-center.overview":

            assert len(p0_panels) <= 2

        assert screen["action_density"]["primary_operation_limit"] <= 12

        assert screen["action_density"]["task_group_limit"] == task_group_limit

        assert screen["user_experience"]["primary_task"]

        assert screen["user_experience"]["primary_outcome"]


def test_macro_overview_publishes_portable_pulse_history_chart() -> None:

    payload = validate_tui_metadata(json.loads(PUBLISHED_PATH.read_text(encoding="utf-8")))

    screen = next(item for item in payload["screens"] if item["key"] == "macro-regime.overview")

    action = next(item for item in payload["actions"] if item["key"] == "pulse.history")

    pulse_current = next(item for item in payload["actions"] if item["key"] == "pulse.current")

    panel = next(item for item in screen["dashboard_panels"] if item["key"] == "pulse-trend")

    current_panel = next(
        item for item in screen["dashboard_panels"] if item["key"] == "pulse-turning"
    )

    assert current_panel["title"] == "当前脉搏指标"

    assert current_panel["kind"] == "datagrid"

    assert current_panel["presentation_semantic"] == "primary_list"

    assert current_panel["max_rows"] == 7

    assert [column["key"] for column in current_panel["columns"]] == [
        "name",
        "value_display",
        "interpretation",
        "observed_at",
        "is_stale",
    ]

    assert pulse_current["view_model"]["kind"] == current_panel["kind"]

    assert pulse_current["view_model"]["rows_path"] == "indicators"

    assert pulse_current["view_model"]["columns"] == current_panel["columns"]

    assert panel["kind"] == "chart"

    assert panel["action_key"] == "pulse.history"

    assert panel["empty_message"] == "暂无脉搏趋势数据。"

    assert action["view_type"] == "chart"

    assert action["view_model"] == {
        "kind": "chart",
        "rows_path": "data",
        "total_path": "count",
        "columns": [
            {"key": "observed_at", "label": "日期"},
            {"key": "composite_score", "label": "综合脉搏"},
            {"key": "growth_score", "label": "增长"},
            {"key": "inflation_score", "label": "通胀"},
        ],
    }


def test_macro_overview_publishes_independent_sentiment_panels() -> None:

    payload = _runtime_payload()

    screen = next(item for item in payload["screens"] if item["key"] == "macro-regime.overview")

    panels = {item["key"]: item for item in screen["dashboard_panels"]}

    assert panels["sentiment-status"]["title"] == "A股市场情绪（最新观测）"

    assert panels["sentiment-status"]["kind"] == "datagrid"

    assert panels["sentiment-status"]["action_key"] == "sentiment.awareness-summary"

    assert panels["sentiment-status"]["user_priority"] == "p1"

    assert panels["sentiment-status"]["max_rows"] == 1

    assert "不是系统状态" in panels["sentiment-status"]["note"]

    assert panels["sentiment-trend"]["kind"] == "chart"

    assert panels["sentiment-trend"]["action_key"] == "sentiment.awareness-trend"

    assert panels["sentiment-trend"]["empty_message"] == "暂无可用的情绪趋势数据。"


def test_research_signals_publishes_beta_then_alpha_user_journey() -> None:

    payload = _runtime_payload()

    screen = next(item for item in payload["screens"] if item["key"] == "research.signals")

    panels = screen["dashboard_panels"]

    assert screen["label"] == "Beta 态势与 Alpha 选股"

    assert screen["default_action_key"] == "dashboard.beta-market-summary"

    assert [panel["key"] for panel in panels] == [
        "beta-market-summary",
        "alpha-stock-ranking",
        "actionable-candidates",
        "active-signals",
        "signal-create",
        "operation-receipt",
    ]

    assert panels[0]["user_priority"] == "p0"

    assert panels[1]["action_key"] == "dashboard.alpha-ranking"

    assert "入选理由" in [column["label"] for column in panels[1]["columns"]]

    assert "不行动理由" in [column["label"] for column in panels[1]["columns"]]

    assert "不等同于完整 Alpha 排名" in panels[2]["note"]
