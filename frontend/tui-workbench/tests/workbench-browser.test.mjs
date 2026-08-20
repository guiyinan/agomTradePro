import assert from "node:assert/strict";
import { setTimeout as delay } from "node:timers/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { chromium } from "playwright";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const bundlePath = resolve(root, "static/js/tui-workbench.js");

const harnessHtml = `<!doctype html>
<html><head><meta charset="utf-8"><title>TUI harness</title></head><body>
<div data-tui-app data-user-key="test-user">
  <button data-menu-command="file">系统</button>
  <button data-menu-command="module">模块</button>
  <button data-menu-command="action">任务</button>
  <button data-menu-command="view">视图</button>
  <button data-menu-command="help">帮助</button>
  <span data-tui-clock></span><span data-theme-status></span><span data-theme-indicator-code></span>
  <input data-current-location value="screen:boot">
  <div data-menu-popover role="menu" hidden></div>
  <aside data-rail-panel><button data-toggle-rail></button><div data-module-tree></div></aside>
  <div class="tui-workspace-grid">
    <section class="tui-panel"><div data-actions-panel></div></section>
    <section><span data-screen-title></span><span data-screen-status></span><span data-main-title></span><div data-workflow-strip></div><div data-main-panel></div></section>
    <section class="tui-panel" data-inspector-panel-shell><button data-toggle-inspector></button><div data-inspector-resize-handle></div><div data-inspector-panel></div></section>
  </div>
  <button data-raw-toggle></button><aside data-raw-drawer hidden><button data-raw-close></button><pre data-raw-panel></pre></aside>
  <section data-filter-bar hidden><input data-filter-input><button data-filter-clear></button></section>
  <section data-tui-modal hidden><div role="dialog"><button data-modal-close>关闭</button><span data-modal-title></span><div data-modal-body></div></div></section>
  <strong data-workbench-status></strong><strong data-last-refresh></strong><span data-pager-status></span>
</div>
</body></html>`;

function action(key, options = {}) {
    return {
        key,
        ui_key: key,
        label: options.label || key,
        method: options.method || "GET",
        endpoint: `/api/test/${key}/`,
        intent: key,
        screen_key: options.screen_key || "test.grid",
        module_key: "test",
        view_type: options.view_type || "detail",
        risk: options.risk || "read",
        fields: options.fields || [],
        effect: options.effect || "",
        description: options.description || "",
        task_tier: options.task_tier || "operation",
        task_group: options.task_group || "测试任务",
        confirmation_required: false,
        sequence: options.sequence || 10,
    };
}

const actions = [
    action("test.list", { label: "读取列表", view_type: "datagrid", task_tier: "primary", sequence: 1 }),
    action("test.detail", {
        label: "读取明细",
        fields: [
            { key: "code", label: "代码", input_type: "text", required: true },
            { key: "context", label: "上下文", input_type: "text", value_type: "object", default: { source: "test" } },
        ],
        sequence: 2,
    }),
    action("test.edit", {
        label: "编辑记录",
        method: "POST",
        risk: "write",
        fields: [
            { key: "code", label: "代码", input_type: "text", required: true },
        ],
        sequence: 2,
    }),
    action("test.upload", {
        label: "上传文本",
        task_tier: "support",
        fields: [
            { key: "note", label: "说明", input_type: "text", required: false },
            { key: "payload", label: "文件", input_type: "file", required: false },
        ],
        sequence: 3,
    }),
    action("test.secure", { label: "敏感操作", risk: "admin", method: "POST", sequence: 4 }),
    action("test.slow", { label: "慢请求", sequence: 5 }),
    action("test.fast", { label: "快请求", sequence: 6 }),
    action("test.next", { label: "下一动作", sequence: 7 }),
    action("test.regime", { label: "Regime 面板", sequence: 8 }),
    action("test.chart", { label: "趋势图", view_type: "chart", sequence: 9 }),
    action("test.kpi", { label: "关键指标", view_type: "kpi_trend", sequence: 10 }),
    action("test.admin-read", {
        label: "管理员只读状态",
        risk: "admin",
        method: "GET",
        task_tier: "primary",
        screen_key: "test.dashboard",
        sequence: 10,
    }),
    action("test.user-list", {
        label: "读取用户准入队列",
        view_type: "datagrid",
        task_tier: "primary",
        screen_key: "test.user-governance",
        sequence: 11,
    }),
    action("test.approve-user", {
        label: "批准用户",
        risk: "admin",
        method: "POST",
        screen_key: "test.user-governance",
        fields: [
            { key: "user_id", label: "用户 ID", input_type: "number", required: true, binding: "path" },
        ],
        sequence: 12,
    }),
    action("test.edit-row", {
        label: "编辑用户",
        risk: "write",
        method: "PATCH",
        effect: "update",
        screen_key: "test.edit-dashboard",
        fields: [
            { key: "user_id", label: "用户 ID", input_type: "number", required: true, binding: "path" },
            { key: "username", label: "用户名", input_type: "text", required: true, binding: "body" },
        ],
        sequence: 13,
    }),
    action("test.password", {
        label: "修改密码",
        risk: "write",
        method: "POST",
        sequence: 14,
        fields: [
            { key: "current_password", label: "当前密码", input_type: "password", required: true },
            { key: "new_password", label: "新密码", input_type: "password", required: true },
        ],
    }),
    action("test.ai-config", {
        label: "更新 AI 服务商",
        risk: "write",
        method: "PATCH",
        sequence: 15,
        fields: [
            { key: "provider_id", label: "服务商 ID", input_type: "number", value_type: "integer", required: true },
            { key: "api_key", label: "API Key", input_type: "password", required: false },
            { key: "is_active", label: "启用", input_type: "select", value_type: "boolean", options: ["true", "false"], default: "true" },
            { key: "fallback_enabled", label: "允许故障切换", input_type: "select", value_type: "boolean", options: ["true", "false"], default: "false" },
        ],
    }),
];

const catalog = {
    default_screen: "test.grid",
    groups: [{
        key: "test",
        label: "测试模块",
        modules: [{
            key: "test",
            label: "测试模块",
            action_count: actions.length,
            screens: [
                { key: "test.grid", label: "测试表格", view_type: "datagrid", action_count: actions.length },
                { key: "test.dashboard", label: "测试概览", view_type: "status", action_count: 2 },
                { key: "test.user-governance", label: "用户准入治理", view_type: "datagrid", action_count: 2 },
                { key: "test.edit-dashboard", label: "可编辑用户列表", view_type: "datagrid", action_count: 2 },
            ],
        }],
    }],
};

const screen = {
    module: { key: "test", label: "测试模块" },
    screen: {
        key: "test.grid",
        label: "测试表格",
        summary: "浏览测试记录。",
        view_type: "datagrid",
        status: "online",
        default_action_key: "test.list",
        entry_state: {},
        workflow: {},
        user_experience: { primary_task: "浏览记录", primary_outcome: "选中正确记录" },
    },
    actions,
};

const dashboardScreen = {
    module: { key: "test", label: "测试模块" },
    screen: {
        key: "test.dashboard",
        label: "测试概览",
        summary: "验证被动 dashboard 行为。",
        view_type: "status",
        status: "online",
        audience: "admin",
        chrome_mode: "immersive",
        entry_state: { mode: "dashboard" },
        workflow: {},
        dashboard_panels: [
            {
                key: "regime",
                title: "当前 Regime",
                kind: "regime_quadrant",
                user_priority: "p0",
                presentation_semantic: "primary_status",
                action_key: "test.regime",
            },
            {
                key: "unsafe",
                title: "敏感操作",
                kind: "detail",
                user_priority: "p1",
                presentation_semantic: "supporting_detail",
                action_key: "test.secure",
            },
            {
                key: "admin-read",
                title: "管理员只读状态",
                kind: "detail",
                user_priority: "p1",
                presentation_semantic: "supporting_detail",
                action_key: "test.admin-read",
            },
        ],
        user_experience: { primary_task: "查看概览", primary_outcome: "不自动执行写操作" },
    },
    actions: actions.filter((item) => ["test.regime", "test.secure", "test.admin-read"].includes(item.key)),
};

const userGovernanceScreen = {
    module: { key: "test", label: "测试模块" },
    screen: {
        key: "test.user-governance",
        label: "用户准入治理",
        summary: "验证管理员行操作、回执与写后刷新。",
        view_type: "datagrid",
        status: "online",
        audience: "admin",
        entry_state: { mode: "dashboard" },
        workflow: {},
        dashboard_panels: [
            {
                key: "users",
                title: "用户准入队列",
                kind: "datagrid",
                user_priority: "p0",
                presentation_semantic: "primary_list",
                action_key: "test.user-list",
                columns: [
                    { key: "user_id", label: "用户 ID" },
                    { key: "username", label: "用户名" },
                    { key: "approval_status", label: "准入状态" },
                ],
                row_actions: [{
                    action_key: "test.approve-user",
                    label_template: "批准 {username}",
                    param_map: { user_id: "user_id" },
                    result_panel_key: "receipt",
                    refresh_panel_key: "users",
                }],
            },
            {
                key: "receipt",
                title: "治理回执",
                kind: "detail",
                user_priority: "p1",
                presentation_semantic: "primary_status",
                empty_message: "从用户列表选择一项治理操作。",
            },
        ],
        user_experience: { primary_task: "处理待审批用户", primary_outcome: "得到治理回执" },
    },
    actions: actions.filter((item) => ["test.user-list", "test.approve-user"].includes(item.key)),
};

const editableDashboardScreen = {
    module: { key: "test", label: "测试模块" },
    screen: {
        key: "test.edit-dashboard",
        label: "可编辑用户列表",
        summary: "验证编辑行操作先打开表单。",
        view_type: "datagrid",
        status: "online",
        audience: "admin",
        entry_state: { mode: "dashboard" },
        workflow: {},
        dashboard_panels: [{
            key: "editable-users",
            title: "用户列表",
            kind: "datagrid",
            user_priority: "p0",
            presentation_semantic: "primary_list",
            action_key: "test.user-list",
            columns: [
                { key: "user_id", label: "用户 ID" },
                { key: "username", label: "用户名" },
            ],
            row_actions: [{
                action_key: "test.edit-row",
                label_template: "编辑 {username}",
                param_map: { user_id: "user_id" },
                refresh_panel_key: "editable-users",
            }],
        }],
        user_experience: { primary_task: "编辑用户", primary_outcome: "提交修改后的用户资料" },
    },
    actions: actions.filter((item) => ["test.user-list", "test.edit-row"].includes(item.key)),
};

function listResult() {
    return {
        action: actions.find((item) => item.key === "test.list"),
        view_model: {
            kind: "datagrid",
            title: "测试记录",
            status: "正常",
            columns: [
                { key: "code", label: "代码" },
                { key: "value", label: "值" },
                { key: "meta", label: "元数据" },
            ],
            rows: Array.from({ length: 205 }, (_, index) => ({
                provider_id: index + 1,
                code: `row-${String(index + 1).padStart(3, "0")}`,
                value: index + 1,
                meta: { source: "test" },
                api_key: "****",
            })),
        },
    };
}

async function openHarness(url = "https://app.test/", options = {}) {
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext();
    const page = await context.newPage();
    page.setDefaultTimeout(5_000);
    const browserErrors = [];
    const requestLog = [];
    page.on("request", (request) => requestLog.push(`REQ ${request.method()} ${request.url()}`));
    page.on("response", (response) => requestLog.push(`RES ${response.status()} ${response.url()}`));
    page.on("pageerror", (error) => browserErrors.push(error.message));
    page.on("console", (message) => {
        if (message.type() === "error") {
            browserErrors.push(message.text());
        }
    });
    await page.addInitScript(() => {
        window.__AGOMTUI_RUNTIME__ = { apiBase: "https://app.test/api/tui", debug: true };
        window.AgomTUIRuntimeCore = {
            clientPage(rows, pageNumber, pageSize) {
                if (rows.length <= pageSize) {
                    return { rows, pager: null };
                }
                const totalPages = Math.ceil(rows.length / pageSize);
                const page = Math.max(1, Math.min(totalPages, pageNumber));
                const start = (page - 1) * pageSize;
                return {
                    rows: rows.slice(start, start + pageSize),
                    pager: {
                        client_side: true,
                        page,
                        total_pages: totalPages,
                        total_rows: rows.length,
                        has_previous: page > 1,
                        has_next: page < totalPages,
                    },
                };
            },
            debounce(callback) {
                return callback;
            },
            dashboardDesktopColumns() {
                return 1;
            },
        };
    });
    await page.route("https://app.test/**", async (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === "/") {
            await route.fulfill({ status: 200, contentType: "text/html", body: harnessHtml });
            return;
        }
        if (url.pathname === "/api/tui/catalog/") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(catalog) });
            return;
        }
        if (url.pathname === "/api/tui/screens/test.grid/") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(screen) });
            return;
        }
        if (url.pathname === "/api/tui/screens/test.dashboard/") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(dashboardScreen) });
            return;
        }
        if (url.pathname === "/api/tui/screens/test.user-governance/") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(userGovernanceScreen) });
            return;
        }
        if (url.pathname === "/api/tui/screens/test.edit-dashboard/") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(editableDashboardScreen) });
            return;
        }
        if (url.pathname.includes("/actions/test.user-list/run/")) {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    view_model: {
                        kind: "datagrid",
                        columns: [
                            { key: "user_id", label: "用户 ID" },
                            { key: "username", label: "用户名" },
                            { key: "approval_status", label: "准入状态" },
                        ],
                        rows: [{ user_id: 42, username: "pending-user", approval_status: "pending" }],
                        total: 1,
                    },
                }),
            });
            return;
        }
        if (url.pathname.includes("/actions/test.approve-user/run/")) {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    view_model: {
                        kind: "detail",
                        title: "已批准 pending-user",
                        status: "成功",
                        fields: [{ label: "用户 ID", value: 42, presentation: "metadata" }],
                    },
                }),
            });
            return;
        }
        if (url.pathname.includes("/actions/test.list/run/")) {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(listResult()) });
            return;
        }
        if (url.pathname.includes("/actions/test.secure/run/")) {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.secure"),
                    password_challenge_required: true,
                    password_challenge: { challenge_id: "challenge-1", message: "请验证密码" },
                    view_model: { kind: "message", title: "等待验证", status: "等待", message: "需要验证" },
                }),
            });
            return;
        }
        if (url.pathname.includes("/actions/test.admin-read/run/")) {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.admin-read"),
                    view_model: {
                        kind: "detail",
                        title: "管理员只读状态",
                        status: "正常",
                        fields: [{ label: "状态", value: "可用" }],
                    },
                }),
            });
            return;
        }
        if (url.pathname.includes("/actions/test.detail/run/")) {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.detail"),
                    view_model: {
                        kind: "datagrid",
                        title: "后续动作",
                        status: "正常",
                        columns: [{ key: "code", label: "代码" }],
                        rows: [],
                        next_steps: [{ label: "继续", action_key: "test.next" }],
                    },
                }),
            });
            return;
        }
        if (url.pathname.includes("/actions/test.regime/run/")) {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.regime"),
                    view_model: {
                        kind: "detail",
                        title: "当前 Regime",
                        status: "正常",
                        fields: options.regimeFields || [
                            { label: "当前判断", key: "current_regime", value: "复苏" },
                            { label: "置信度", key: "confidence", value: "36.88" },
                            { label: "增长与通胀趋势", key: "trend", value: "增长上行 / 通胀下行" },
                            { label: "拐点预警", key: "warning", value: "无" },
                        ],
                    },
                }),
            });
            return;
        }
        if (url.pathname.includes("/actions/test.chart/run/")) {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.chart"),
                    view_model: {
                        kind: "chart",
                        chart_type: "line",
                        title: "脉搏趋势",
                        status: "正常",
                        x_axis_label: "日期",
                        series: [
                            {
                                key: "composite_score",
                                label: "综合脉搏",
                                points: [
                                    { label: "2026-07-24", value: 0.42 },
                                    { label: "2026-07-25", value: 0.57 },
                                ],
                            },
                            {
                                key: "growth_score",
                                label: "增长",
                                points: [
                                    { label: "2026-07-24", value: 0.31 },
                                    { label: "2026-07-25", value: 0.38 },
                                ],
                            },
                        ],
                    },
                }),
            });
            return;
        }
        if (url.pathname.includes("/actions/test.kpi/run/")) {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.kpi"),
                    view_model: {
                        kind: "kpi_trend",
                        title: "关键指标",
                        status: "正常",
                        value: "",
                        trend: [],
                    },
                }),
            });
            return;
        }
        const actionKey = decodeURIComponent(url.pathname.match(/\/actions\/([^/]+)\/run\//)?.[1] || "");
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                action: actions.find((item) => item.key === actionKey),
                view_model: { kind: "detail", title: "完成", status: "正常", fields: [] },
            }),
        });
    });
    try {
        await page.goto(url);
        await page.addScriptTag({ path: bundlePath });
        if (options.waitForInitialRows !== false) {
            await page.waitForSelector('[data-row-index="0"]');
        } else {
            await page.waitForSelector("[data-screen-title]");
        }
        return { browser, page };
    } catch (error) {
        const status = await page.locator("[data-workbench-status]").textContent().catch(() => "");
        const main = await page.locator("[data-main-panel]").innerText().catch(() => "");
        await browser.close();
        throw new Error(`${error.message}\nstatus=${status}\nmain=${main}\nbrowser=${browserErrors.join(" | ")}\nrequests=${requestLog.join(" | ")}`);
    }
}

test("action deep links reveal, focus, and prefill the requested task", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.grid&action=test.edit&code=deep-link-code",
        { waitForInitialRows: false },
    );
    try {
        const input = page.locator('form[data-action-ui-key="test.edit"] input[name="code"]');
        await input.waitFor();
        await page.waitForFunction(() => document.activeElement?.getAttribute("name") === "code");
        assert.equal(await input.inputValue(), "deep-link-code");
        assert.equal(
            await input.evaluate((element) => {
                const fieldRect = element.getBoundingClientRect();
                return fieldRect.top >= 0 && fieldRect.bottom <= window.innerHeight;
            }),
            true,
        );
        assert.match(await page.locator("[data-workbench-status]").innerText(), /编辑记录/);
    } finally {
        await browser.close();
    }
});

test("immersive dashboard deep links locate their matching panel", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.dashboard&action=test.admin-read",
        { waitForInitialRows: false },
    );
    try {
        await page.locator('[data-dashboard-panel="admin-read"]').waitFor();
        assert.match(
            await page.locator("[data-workbench-status]").innerText(),
            /管理员只读状态/,
        );
        assert.equal(
            await page.locator('[data-dashboard-panel="admin-read"]').count(),
            1,
        );
    } finally {
        await browser.close();
    }
});

test("catalog suppresses a redundant single-module heading", async () => {
    const { browser, page } = await openHarness();
    try {
        assert.equal(
            await page.locator('[data-module-tree]').getByText("测试模块", { exact: true }).count(),
            1,
        );
        assert.equal(await page.locator(".tui-group-title").innerText(), "测试模块");
        assert.equal(await page.locator(".tui-tree-module-title").count(), 0);
    } finally {
        await browser.close();
    }
});

test("client pagination keeps second-page row selection aligned", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.locator('[data-page-delta="1"]').click();
        const firstSecondPageRow = page.locator('[data-row-index="100"]');
        await firstSecondPageRow.click();
        await page.locator('form[data-action-ui-key="test.detail"] [data-fill-from-row]').click();
        assert.equal(await page.locator('form[data-action-ui-key="test.detail"] [name="code"]').inputValue(), "row-101");
        await firstSecondPageRow.dblclick();
        assert.match(await page.locator("[data-modal-body]").innerText(), /row-101/);
    } finally {
        await browser.close();
    }
});

test("action filtering and toggles preserve form and file input nodes", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.locator("[data-toggle-support]").click();
        const form = page.locator('form[data-action-ui-key="test.upload"]');
        const note = form.locator('[name="note"]');
        const file = form.locator('[name="payload"]');
        await note.fill("draft-value");
        await file.setInputFiles({ name: "payload.txt", mimeType: "text/plain", buffer: Buffer.from("payload") });
        await file.evaluate((element) => { window.__uploadNode = element; });
        await page.locator("[data-action-filter]").fill("upload");
        assert.equal(await note.inputValue(), "draft-value");
        assert.equal((await file.evaluate((element) => element.files.length)), 1);
        assert.equal(await file.evaluate((element) => element === window.__uploadNode), true);
        await page.locator("[data-toggle-support]").click();
        assert.equal(await file.evaluate((element) => element === window.__uploadNode), true);
    } finally {
        await browser.close();
    }
});

test("password fields render as masked controls and keep values out of markup", async () => {
    const { browser, page } = await openHarness();
    try {
        const form = page.locator('[data-action-ui-key="test.password"]');
        await form.waitFor({ state: "visible" });
        const currentPassword = form.locator('input[name="current_password"]');
        const newPassword = form.locator('input[name="new_password"]');
        assert.equal(await currentPassword.getAttribute("type"), "password");
        assert.equal(await newPassword.getAttribute("type"), "password");
        assert.equal(await currentPassword.getAttribute("value"), "");
        assert.equal(await newPassword.getAttribute("value"), "");
    } finally {
        await browser.close();
    }
});

test("AI configuration preserves boolean selections and never fills masked secrets from rows", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.locator('[data-row-index="0"]').click();
        const form = page.locator('[data-action-ui-key="test.ai-config"]');
        await form.locator('[data-fill-from-row]').click();
        assert.equal(await form.locator('[name="provider_id"]').inputValue(), "1");
        assert.equal(await form.locator('[name="api_key"]').inputValue(), "");
        await form.locator('[name="is_active"]').selectOption("true");
        await form.locator('[name="fallback_enabled"]').selectOption("false");
        const actionRequest = page.waitForRequest((request) =>
            request.url().includes("/actions/test.ai-config/run/"),
        );
        await form.locator('.tui-action-submit').click();
        const request = await actionRequest;
        assert.deepEqual(request.postDataJSON().params, {
            provider_id: 1,
            is_active: true,
            fallback_enabled: false,
        });
    } finally {
        await browser.close();
    }
});

test("next steps without params do not inherit the previous action form", async () => {
    const { browser, page } = await openHarness();
    try {
        const detailForm = page.locator('form[data-action-ui-key="test.detail"]');
        await detailForm.locator('[name="code"]').fill("stale-code");
        await detailForm.locator('.tui-action-submit').click();
        const nextStep = page.locator('[data-next-step-index="0"]');
        await nextStep.waitFor({ state: "visible" });
        const nextRequest = page.waitForRequest((request) => request.url().includes("/actions/test.next/run/"));
        await nextStep.click();
        const request = await nextRequest;
        assert.deepEqual(request.postDataJSON().params, {});
    } finally {
        await browser.close();
    }
});

test("dashboard auto-loads passive reads and never auto-runs sensitive actions", async () => {
    const { browser, page } = await openHarness();
    try {
        let secureRequests = 0;
        let adminReadRequests = 0;
        page.on("request", (request) => {
            if (request.url().includes("/actions/test.secure/run/")) {
                secureRequests += 1;
            }
            if (request.url().includes("/actions/test.admin-read/run/")) {
                adminReadRequests += 1;
            }
        });
        const location = page.locator("[data-current-location]");
        const adminReadResponse = page.waitForResponse((response) =>
            response.url().includes("/actions/test.admin-read/run/"),
        );
        await location.fill("screen:test.dashboard");
        await location.press("Enter");
        await adminReadResponse;
        const marker = page.locator('[data-dashboard-panel="regime"] .q-marker');
        await marker.waitFor({ state: "visible" });
        assert.equal(await marker.getAttribute("style"), "left:25%;top:25%");
        const regimePanelText = await page.locator('[data-dashboard-panel="regime"]').innerText();
        assert.match(regimePanelText, /当前判断:\s*复苏/);
        assert.match(regimePanelText, /置信度:\s*36\.9%/);
        assert.match(regimePanelText, /趋势:\s*增长上行 \/ 通胀下行/);
        assert.match(regimePanelText, /拐点预警:\s*无/);
        assert.match(
            await page.locator('[data-dashboard-panel="unsafe"]').innerText(),
            /敏感操作/,
        );
        assert.equal(secureRequests, 0);
        assert.equal(adminReadRequests, 1);
    } finally {
        await browser.close();
    }
});

test("regime dashboard fails closed when its result contract drifts", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.dashboard",
        {
            waitForInitialRows: false,
            regimeFields: [
                { label: "说明 / 象限", key: "summary.quadrant", value: "复苏" },
                { label: "说明 / 置信度", key: "summary.confidence_percent", value: "36.88" },
            ],
        },
    );
    try {
        const contractError = page.locator(
            '[data-dashboard-panel="regime"] [data-render-contract-error="regime_quadrant"]',
        );
        await contractError.waitFor({ state: "visible" });
        const panelText = await page.locator('[data-dashboard-panel="regime"]').innerText();
        assert.match(panelText, /结果数据不完整/);
        assert.doesNotMatch(panelText, /UNKNOWN/);
        assert.doesNotMatch(panelText, /0%/);
    } finally {
        await browser.close();
    }
});

test("blank KPI results fail closed instead of rendering a synthetic zero", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.grid&action=test.kpi",
        { waitForInitialRows: false },
    );
    try {
        const contractError = page.locator(
            '[data-main-panel] [data-render-contract-error="kpi_trend"]',
        );
        await contractError.waitFor({ state: "visible" });
        const resultText = await page.locator("[data-main-panel]").innerText();
        assert.match(resultText, /指标结果数据不完整/);
        assert.doesNotMatch(resultText, /\b0(?:\.0+)?\b/);
    } finally {
        await browser.close();
    }
});

test("admin governance row action shows a receipt and refreshes the source panel", async () => {
    const { browser, page } = await openHarness();
    try {
        let listRequests = 0;
        page.on("request", (request) => {
            if (request.url().includes("/actions/test.user-list/run/")) {
                listRequests += 1;
            }
        });

        const location = page.locator("[data-current-location]");
        await location.fill("screen:test.user-governance");
        await location.press("Enter");

        const approve = page.locator('[data-dashboard-row-action][aria-label="批准 pending-user"]');
        await approve.waitFor({ state: "visible" });
        const mutationRequest = page.waitForRequest(
            (request) => request.url().includes("/actions/test.approve-user/run/"),
        );
        await approve.click();

        const request = await mutationRequest;
        assert.deepEqual(request.postDataJSON().params, { user_id: 42 });
        await page.locator('[data-dashboard-panel="receipt"]').getByText("已批准 pending-user").waitFor();
        await page.waitForFunction(() => document.querySelectorAll('[data-dashboard-row-action]').length === 1);
        assert.equal(listRequests, 2);
    } finally {
        await browser.close();
    }
});

test("editable dashboard row action opens a form before sending the update", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.edit-dashboard",
        { waitForInitialRows: false },
    );
    try {
        let updateRequests = 0;
        page.on("request", (request) => {
            if (request.url().includes("/actions/test.edit-row/run/")) {
                updateRequests += 1;
            }
        });

        const edit = page.locator('[data-dashboard-row-action][aria-label="编辑 pending-user"]');
        await edit.waitFor({ state: "visible" });
        await edit.click();
        await page.waitForTimeout(150);
        assert.equal(updateRequests, 0);

        const form = page.locator('form[data-action-ui-key="test.edit-row"]');
        await form.waitFor({ state: "visible" });
        assert.equal(await form.locator('[name="user_id"]').inputValue(), "42");
        assert.equal(await form.locator('[name="username"]').inputValue(), "pending-user");
        await form.locator('[name="username"]').fill("updated-user");

        const updateRequest = page.waitForRequest(
            (request) => request.url().includes("/actions/test.edit-row/run/"),
        );
        await form.locator(".tui-action-submit").click();
        const request = await updateRequest;
        assert.deepEqual(request.postDataJSON().params, {
            user_id: 42,
            username: "updated-user",
        });
    } finally {
        await browser.close();
    }
});

test("screen navigation updates shareable history and browser back restores the screen", async () => {
    const { browser, page } = await openHarness();
    try {
        assert.equal(new URL(page.url()).searchParams.get("screen"), "test.grid");
        const location = page.locator("[data-current-location]");
        await location.fill("screen:test.dashboard");
        await location.press("Enter");
        await page.waitForURL(/screen=test\.dashboard/);
        await page.goBack();
        await page.waitForFunction(() => document.querySelector("[data-screen-title]")?.textContent === "测试表格");
        assert.equal(new URL(page.url()).searchParams.get("screen"), "test.grid");
    } finally {
        await browser.close();
    }
});

test("user-owned state is namespaced and structured values never render as object placeholders", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.locator('[data-pin-screen-key="test.grid"]').click();
        const keys = await page.evaluate(() => Object.keys(localStorage));
        assert.equal(
            keys.some((key) => key === "agom-tui-pinned-screen-keys:v1:user:test-user"),
            true,
        );
        assert.equal(await page.locator('form[data-action-ui-key="test.detail"] textarea[name="context"]').count(), 1);
        assert.equal((await page.locator("[data-main-panel]").innerText()).includes("[object Object]"), false);
        assert.match(await page.locator("[data-main-panel]").innerText(), /"source":"test"|"source": "test"/);
    } finally {
        await browser.close();
    }
});

test("menus expose menuitem semantics and return focus on Escape", async () => {
    const { browser, page } = await openHarness();
    try {
        const button = page.locator('[data-menu-command="file"]');
        await button.click();
        assert.equal(await button.getAttribute("aria-expanded"), "true");
        assert.equal(await page.locator('[data-menu-popover] [role="menuitem"]').count(), 2);
        await page.keyboard.press("ArrowDown");
        await page.keyboard.press("Escape");
        assert.equal(await button.getAttribute("aria-expanded"), "false");
        assert.equal(await button.evaluate((element) => element === document.activeElement), true);
    } finally {
        await browser.close();
    }
});

test("chart view renders every series with an accessible text summary", async () => {
    const { browser, page } = await openHarness();
    try {
        const trigger = page.locator('form[data-action-ui-key="test.chart"] .tui-action-button');
        await trigger.focus();
        assert.equal(await trigger.evaluate((element) => element === document.activeElement), true);
        await trigger.press("Enter");
        const chart = page.locator(".tui-chart-view");
        await chart.waitFor({ state: "visible" });

        assert.equal(await chart.locator(".tui-chart-line").count(), 2);
        assert.equal(await chart.locator(".tui-chart-series-legend").count(), 2);
        assert.match(await chart.locator(".tui-chart-accessible-summary").innerText(), /综合脉搏/);
        assert.match(await chart.locator(".tui-chart-accessible-summary").innerText(), /2026-07-25.*0.57/);
        assert.equal(await chart.locator("svg").getAttribute("aria-hidden"), "true");
    } finally {
        await browser.close();
    }
});

test("detail and chart empty results render reviewed task guidance", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.route("**/actions/test.detail/run/", async (route) => {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.detail"),
                    view_model: {
                        kind: "detail",
                        title: "研究摘要",
                        status: "暂无数据",
                        fields: [],
                        empty_message: "当前没有研究摘要。",
                        empty_guidance: ["先检查研究样本和筛选条件。"],
                        next_steps: [{ label: "补齐数据", action_key: "test.next" }],
                    },
                }),
            });
        });
        const detailForm = page.locator('form[data-action-ui-key="test.detail"]');
        await detailForm.locator('[name="code"]').fill("empty-case");
        await detailForm.locator(".tui-action-button").click();
        const detailEmpty = page.locator("[data-main-panel] .tui-empty-state");
        await detailEmpty.getByText("当前没有研究摘要。", { exact: true }).waitFor();
        assert.match(await detailEmpty.innerText(), /先检查研究样本和筛选条件/);
        assert.equal(await detailEmpty.getByRole("button", { name: "补齐数据" }).count(), 1);

        await page.route("**/actions/test.chart/run/", async (route) => {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.chart"),
                    view_model: {
                        kind: "chart",
                        chart_type: "line",
                        title: "研究趋势",
                        status: "暂无数据",
                        series: [],
                        empty_message: "当前没有研究趋势。",
                        empty_guidance: ["先同步研究序列。"],
                    },
                }),
            });
        });
        await page.locator('form[data-action-ui-key="test.chart"] .tui-action-button').click();
        const chartEmpty = page.locator("[data-main-panel] .tui-empty-state");
        await chartEmpty.getByText("当前没有研究趋势。", { exact: true }).waitFor();
        assert.match(await chartEmpty.innerText(), /先同步研究序列/);
    } finally {
        await browser.close();
    }
});

test("chart view has no overlap or page overflow at three acceptance viewports", async () => {
    const viewports = [
        { width: 360, height: 800 },
        { width: 768, height: 1024 },
        { width: 1440, height: 1000 },
    ];
    for (const viewport of viewports) {
        const { browser, page } = await openHarness();
        try {
            await page.setViewportSize(viewport);
            await page.locator('form[data-action-ui-key="test.chart"] .tui-action-button').click();
            const chart = page.locator(".tui-chart-view");
            await chart.waitFor({ state: "visible" });
            const geometry = await page.evaluate(() => {
                const main = document.querySelector("[data-main-panel]").getBoundingClientRect();
                const chartBox = document.querySelector(".tui-chart-view").getBoundingClientRect();
                const summary = document.querySelector(".tui-chart-accessible-summary").getBoundingClientRect();
                return {
                    pageOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
                    chartInsideMain: chartBox.left >= main.left - 1 && chartBox.right <= main.right + 1,
                    summaryBelowChart: summary.top >= chartBox.top && summary.bottom <= chartBox.bottom + 1,
                };
            });
            assert.equal(geometry.pageOverflow, false, JSON.stringify(viewport));
            assert.equal(geometry.chartInsideMain, true, JSON.stringify(viewport));
            assert.equal(geometry.summaryBelowChart, true, JSON.stringify(viewport));
        } finally {
            await browser.close();
        }
    }
});

test("modal traps focus and clears sensitive markup on close", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.locator('form[data-action-ui-key="test.secure"] .tui-action-button').click();
        const modal = page.locator("[data-tui-modal]");
        await modal.waitFor({ state: "visible" });
        const close = page.locator("[data-modal-close]");
        const cancel = page.locator("[data-cancel-action]");
        await cancel.focus();
        await page.keyboard.press("Tab");
        assert.equal(await close.evaluate((element) => element === document.activeElement), true);
        await page.keyboard.press("Shift+Tab");
        assert.equal(await cancel.evaluate((element) => element === document.activeElement), true);
        await page.locator('[name="password"]').fill("secret-value");
        await close.click();
        assert.equal(await page.locator("[data-modal-body]").innerHTML(), "");
    } finally {
        await browser.close();
    }
});

test("task failures render traceable recovery without leaking exception text", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.route("**/actions/test.fast/run/", async (route) => {
            await route.fulfill({
                status: 502,
                contentType: "application/json",
                body: JSON.stringify({
                    error_code: "tui_action_unavailable",
                    title: "任务暂时不可用",
                    detail: "“快请求”暂时无法完成，请稍后重试。",
                    trace_id: "browser-error-trace",
                    recovery_actions: [{ label: "返回测试概览", screen_key: "test.dashboard" }],
                }),
            });
        });
        await page.locator('form[data-action-ui-key="test.fast"] .tui-action-button').click();
        const error = page.locator(".tui-application-error");
        await error.getByText("任务暂时不可用", { exact: true }).waitFor();
        assert.match(await error.innerText(), /快请求/);
        assert.match(await error.innerText(), /browser-error-trace/);
        assert.equal((await error.innerText()).includes("private exception"), false);
        assert.equal(await error.locator("[data-application-retry]").count(), 1);
        await error.getByRole("button", { name: "返回测试概览" }).click();
        await page.waitForFunction(
            () => document.querySelector("[data-screen-title]")?.textContent === "测试概览",
        );
    } finally {
        await browser.close();
    }
});

test("late stale errors cannot replace the latest action result", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.evaluate(() => {
            const originalFetch = window.fetch.bind(window);
            window.fetch = (input, init) => {
                const url = String(input);
                if (url.includes("/actions/test.slow/run/")) {
                    return new Promise((resolve) => window.setTimeout(() => resolve(new Response(
                        JSON.stringify({ detail: "stale failure" }),
                        { status: 500, headers: { "content-type": "application/json" } },
                    )), 180));
                }
                if (url.includes("/actions/test.fast/run/")) {
                    return new Promise((resolve) => window.setTimeout(() => resolve(new Response(
                        JSON.stringify({
                            action: {
                                key: "test.fast",
                                label: "快请求",
                                description: "返回最新结果",
                                risk: "read",
                                confirmation_required: false,
                            },
                            view_model: { kind: "detail", title: "FAST RESULT", status: "正常", fields: [] },
                        }),
                        { status: 200, headers: { "content-type": "application/json" } },
                    )), 20));
                }
                return originalFetch(input, init);
            };
        });
        await page.locator('form[data-action-ui-key="test.slow"] .tui-action-button').click();
        await page.locator('form[data-action-ui-key="test.fast"] .tui-action-button').click();
        await delay(260);
        assert.equal(await page.locator("[data-main-title]").innerText(), "FAST RESULT");
        assert.equal(await page.locator("[data-application-retry]").count(), 0);
    } finally {
        await browser.close();
    }
});
