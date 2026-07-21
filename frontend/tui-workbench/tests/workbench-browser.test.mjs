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
<div data-tui-app>
  <button data-menu-command="file">系统</button>
  <button data-menu-command="module">模块</button>
  <button data-menu-command="action">任务</button>
  <button data-menu-command="view">视图</button>
  <button data-menu-command="help">帮助</button>
  <span data-tui-clock></span><span data-theme-status></span><span data-theme-indicator-code></span>
  <input data-current-location value="screen:boot">
  <div data-menu-popover hidden></div>
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
        fields: [{ key: "code", label: "代码", input_type: "text", required: true }],
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
    action("test.admin-read", {
        label: "管理员只读状态",
        risk: "admin",
        method: "GET",
        task_tier: "primary",
        screen_key: "test.dashboard",
        sequence: 9,
    }),
];

const catalog = {
    default_screen: "test.grid",
    groups: [{
        key: "test",
        label: "测试",
        modules: [{
            key: "test",
            label: "测试模块",
            action_count: actions.length,
            screens: [
                { key: "test.grid", label: "测试表格", view_type: "datagrid", action_count: actions.length },
                { key: "test.dashboard", label: "测试概览", view_type: "status", action_count: 2 },
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
            ],
            rows: Array.from({ length: 205 }, (_, index) => ({
                code: `row-${String(index + 1).padStart(3, "0")}`,
                value: index + 1,
            })),
        },
    };
}

async function openHarness() {
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
                        fields: [{ label: "状态", key: "state", value: "Recovery" }],
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
        await page.goto("https://app.test/");
        await page.addScriptTag({ path: bundlePath });
        await page.waitForSelector('[data-row-index="0"]');
        return { browser, page };
    } catch (error) {
        const status = await page.locator("[data-workbench-status]").textContent().catch(() => "");
        const main = await page.locator("[data-main-panel]").innerText().catch(() => "");
        await browser.close();
        throw new Error(`${error.message}\nstatus=${status}\nmain=${main}\nbrowser=${browserErrors.join(" | ")}\nrequests=${requestLog.join(" | ")}`);
    }
}

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
        await location.fill("screen:test.dashboard");
        await location.press("Enter");
        const marker = page.locator('[data-dashboard-panel="regime"] .q-marker');
        await marker.waitFor({ state: "visible" });
        assert.equal(await marker.getAttribute("style"), "left:25%;top:25%");
        assert.match(
            await page.locator('[data-dashboard-panel="unsafe"]').innerText(),
            /需要填写参数或确认操作/,
        );
        assert.equal(secureRequests, 0);
        assert.equal(adminReadRequests, 1);
    } finally {
        await browser.close();
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
