const runtime = globalThis.__AGOMTUI_RUNTIME__ || {};
const previousHooks = runtime.hooks && typeof runtime.hooks === "object" ? runtime.hooks : {};

runtime.apiBase = runtime.apiBase || "/api/tui";
runtime.bootstrapUrl = runtime.bootstrapUrl || "/api/tui/bootstrap/";
runtime.hooks = {
    ...previousHooks,
    isOperatorHomeScreen(screenKey) {
        return String(screenKey || "") === "command-center.overview";
    },
    inferHomeLane(screen) {
        const lane = String(screen?.workflow?.lane || "");
        return ["decision", "governance"].includes(lane) ? lane : "";
    },
    getHomeActions(context = {}) {
        return [
            {
                key: "operator.home.continue_decision_flow",
                label: "继续今日决策流程",
                description: "进入每日投研主流程",
                active: context.preferredLane === "decision",
            },
            {
                key: "operator.home.enter_governance_flow",
                label: "进入系统治理流",
                description: "从 runtime 起点进入治理主线",
                active: context.preferredLane === "governance",
            },
            {
                key: "operator.home.resume_last_workspace",
                label: "恢复上次工作区",
                description: context.lastWorkspace || "最近无可恢复工作区",
            },
            {
                key: "operator.home.open_cli",
                label: "打开 CLI",
                description: "独立入口，不中断当前 TUI",
            },
        ];
    },
    runHomeAction(actionKey, context) {
        if (actionKey === "operator.home.continue_decision_flow") {
            context.persistPreferredLane("decision");
            context.loadScreen("macro-regime.overview");
            return true;
        }
        if (actionKey === "operator.home.enter_governance_flow") {
            context.persistPreferredLane("governance");
            context.loadScreen("api-library.runtime");
            return true;
        }
        if (actionKey === "operator.home.resume_last_workspace") {
            return context.restoreLastWorkspace();
        }
        if (actionKey === "operator.home.open_cli") {
            context.openCliSurface();
            return true;
        }
        return false;
    },
};
runtime.host = {
    ...(runtime.host || {}),
    operatorHomeUrl: "/api/tui/operator/home/",
    governanceQueueUrl: "/api/tui/operator/governance-queue/",
    homePanelActionPrefix: "operator.home.",
    laneActionKeys: {
        decision: "operator.home.continue_decision_flow",
        governance: "operator.home.enter_governance_flow",
    },
    workflowActionKeys: [
        "operator.home.resume_last_workspace",
        "operator.home.open_cli",
    ],
    workflowActionsLane: "governance",
    slowActionScreens: [
        { key: "ai-ops.terminal", label: "打开 AI 交互终端" },
        { key: "capability-router.gateway", label: "打开能力路由接入" },
    ],
    slowActionKeys: [
        "cli.chat_router",
        "terminal.chat_router",
        "capability-router.route-message",
    ],
    singleColumnScreens: ["capability-router.mcp-center"],
    homeActionKeys: [
        "operator.home.continue_decision_flow",
        "operator.home.enter_governance_flow",
        "operator.home.resume_last_workspace",
        "operator.home.open_cli",
    ],
};

globalThis.__AGOMTUI_RUNTIME__ = runtime;
