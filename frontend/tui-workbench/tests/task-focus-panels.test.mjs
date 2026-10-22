import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import test from "node:test";

// Isolated browser helper contracts. Actual authenticated journeys live in
// tests/component/test_tui_task_focus_browser.py; these are not owner evidence.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const helperSource = await readFile(resolve(root, "frontend/tui-workbench/src/38-task-focus-panels.js"), "utf8");
const paginationSource = await readFile(resolve(root, "frontend/tui-workbench/src/45-pagination.js"), "utf8");
const workspaceSource = await readFile(resolve(root, "frontend/tui-workbench/src/15-workspace-state.js"), "utf8");

function harness(overrides = {}) {
    const state = {
        screen: { screen: { dashboard_panels: [] }, actions: [] },
        dashboardFilters: {}, selectedRowContext: { id: 9 }, selectedRowIndex: 1,
        lastAction: "facts", lastParams: { pk: 9 }, lastPager: { page: 1 },
        currentViewModel: { fields: [{ value: "old private fact" }] },
        currentRows: [{ value: "old row" }], currentColumns: ["value"], visibleRows: [{ value: "old row" }],
        lastRaw: { secret: "old" }, rawResponseAvailable: true,
        pendingController: { abort() {} }, latestRequestId: 42,
    };
    const calls = [];
    const context = vm.createContext({
        state, CSS: { escape: value => value },
        els: { main: { querySelector: () => null } },
        panelPresentationSemantic: panel => panel.presentation_semantic,
        currentAction: key => ({ key, method: "GET", risk: "read", fields: [] }),
        currentDashboardPanel: () => null,
        clearPendingRequest: options => calls.push(["clearPendingRequest", options]),
        updatePager: value => calls.push(["updatePager", value]),
        updateRawDrawer: () => calls.push(["updateRawDrawer"]),
        escapeHtml: value => String(value ?? "").replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;"),
        displayValue: value => value == null ? "未提供" : String(value),
        ...overrides,
    });
    vm.runInContext(workspaceSource, context);
    vm.runInContext(paginationSource, context);
    vm.runInContext(helperSource, context);
    return { context, state, calls, evaluate: code => vm.runInContext(code, context) };
}

test("target recovery retains selected path identity but excludes credentials and handoff values", () => {
    const { context, evaluate } = harness({
        resultContinuations: { continuationFields: () => new Set(["handoff"]) },
    });
    context.action = {
        fields: [
            { key: "pk", binding: "path", input_type: "number" },
            { key: "password", binding: "path", input_type: "password" },
            { key: "credential", binding: "path", secret: true },
            { key: "sensitive", binding: "path", sensitive: true },
            { key: "handoff", input_type: "text" },
            { key: "page", input_type: "number" },
        ],
        pagination: { mode: "page", page_param: "page" },
    };
    context.params = {
        pk: 9, page: 2, password: "secret", credential: "secret", sensitive: "secret",
        handoff: "one-use", user_id: 77, page_size: 500, next: "https://evil.test/",
    };
    assert.deepEqual(JSON.parse(JSON.stringify(evaluate("dashboardTargetParams(action, params)"))), { pk: 9, page: 2 });
});

test("authorization loss invalidates a pending related read before clearing its facts", () => {
    const { state, calls, evaluate } = harness();
    evaluate('clearDashboardSelectorState({ key: "selector", action_key: "list", row_actions: [{action_key: "facts", result_panel_key: "result"}] })');
    assert.equal(state.latestRequestId, 0);
    assert.equal(state.lastAction, "");
    assert.equal(state.currentViewModel, null);
    assert.equal(state.selectedRowContext, null);
    assert.deepEqual(calls.map(([name]) => name), ["clearPendingRequest", "updateRawDrawer", "updatePager"]);
    assert.equal(calls[0][1].abort, true);
});

test("selector invalidation does not abort an unrelated mutation", () => {
    const { context, state, calls, evaluate } = harness({
        currentAction: key => ({ key, method: "POST", risk: "write" }),
    });
    state.lastAction = "mutation";
    evaluate('clearDashboardSelectorState({ key: "selector", action_key: "list", row_actions: [{action_key: "facts", result_panel_key: "result"}] })');
    assert.equal(state.latestRequestId, 42);
    assert.equal(state.lastAction, "mutation");
    assert.equal(calls.length, 0);
});

test("detail sections preserve zero and missing units while escaping stored text", () => {
    const { context, evaluate } = harness();
    context.section = {
        label: "记录持仓", columns: [{ key: "quantity", label: "记录数量" }, { key: "currency", label: "币种" }, { key: "code", label: "代码" }],
        rows: [{ fields: [{ key: "quantity", value: 0 }, { key: "currency", value: null }, { key: "code", value: "<img src=x onerror=alert(1)>" }] }],
    };
    const html = evaluate("renderDetailSectionMarkup(section)");
    assert.match(html, /<td>0<\/td>/);
    assert.match(html, /未提供/);
    assert.match(html, /&lt;img/);
    assert.doesNotMatch(html, /<img/);
    assert.doesNotMatch(html, /<details[^>]*\sopen/);
});

test("page-only owner metadata never invents page size or follows a next URL", () => {
    const { context, evaluate } = harness();
    context.action = { fields: [{ key: "page" }], pagination: { mode: "page", page_param: "page" } };
    context.pager = { page: 2, page_size: 20, has_next: true, next: "https://evil.test/?page=3" };
    const patch = evaluate("paginationParamPatch(action, pager, {page: 2}, 1)");
    assert.deepEqual(JSON.parse(JSON.stringify(patch)), { page: 3 });
    assert.equal(evaluate('paginationParamPatch({fields: []}, {page: 1}, {}, 1)'), null);
});

test("only a published task dashboard exposes the primary result and every restriction", () => {
    const { context, state, evaluate } = harness({
        experienceEntries: () => [{ screen_key: "task.visible" }],
        experienceEntryScreen: entry => entry.screen_key,
    });
    state.screen.screen = { key: "task.visible", entry_state: { mode: "dashboard" } };
    context.model = { title: "facts", status: "结果状态未提供", business_summary: "<record limits>", blocking_reason: "<must stop>" };
    const markup = evaluate("renderTaskDashboardSummary(model)");
    assert.match(markup, /结果状态未提供/);
    assert.match(markup, /&lt;record limits&gt;/);
    assert.match(markup, /&lt;must stop&gt;/);
    state.screen.screen.key = "professional.other";
    assert.equal(evaluate("renderTaskDashboardSummary(model)"), "");
});

test("nested owner authorization takes precedence over transport success", () => {
    const { evaluate } = harness();
    assert.equal(evaluate('dashboardResultStatus({outcome:"success", response:{status_code:403}})'), 403);
    assert.equal(evaluate('dashboardResultStatus({outcome:"failed", response:{status_code:200}})'), 502);
    assert.equal(evaluate('dashboardResultStatus({outcome:"blocked", response:{status_code:200}})'), 400);
});

test("scope invalid is exact and an authorization envelope cannot reuse its old view model", () => {
    const { evaluate } = harness();
    assert.equal(evaluate('isDashboardScopeInvalid({status:400, payload:{user_error_code:"TUI_TASK_SCOPE_INVALID"}})'), true);
    assert.equal(evaluate('isDashboardScopeInvalid({status:400, payload:{view_model:{user_error_code:"TUI_TASK_SCOPE_INVALID"}}})'), true);
    assert.equal(evaluate('isDashboardScopeInvalid({status:400, payload:{user_error_code:"OTHER"}})'), false);
    assert.equal(evaluate('dashboardTargetCanRenderViewModel(403, {view_model:{fields:[{value:"old"}]}})'), false);
    assert.equal(evaluate('dashboardTargetCanRenderViewModel(400, {view_model:{fields:[{value:"blocked"}]}})'), true);
});

test("selection replacement aborts related reads and target panel work, never a mutation", () => {
    let targetAborts = 0;
    const targetContainer = {
        panelViewModel: { fields: [{ value: "old" }] },
        panelRequestController: { abort: () => { targetAborts += 1; } },
        panelRequestPassiveRead: true,
        querySelector: () => null,
        innerHTML: "",
    };
    const panel = { key: "selector", row_actions: [{ action_key: "facts", result_panel_key: "result" }] };
    const { context, state, calls, evaluate } = harness({
        currentDashboardPanel: key => key === "result" ? { key: "result", action_key: "facts" } : null,
        els: { main: { querySelector: () => targetContainer } },
        renderDashboardPanelShell: () => "",
        renderPanelPlaceholder: () => "",
        bindDashboardPanelOpenControls: () => {},
        bindDashboardFilters: () => {},
    });
    state.dashboardFilters.result = { pk: 9 };
    context.panel = panel;
    evaluate("clearDashboardTargetResults(panel)");
    assert.equal(targetAborts, 1);
    assert.equal(state.dashboardFilters.result, undefined);
    assert.equal(state.latestRequestId, 0);
    assert.equal(calls[0][0], "clearPendingRequest");

    targetAborts = 0;
    targetContainer.panelRequestPassiveRead = false;
    const mutationHarness = harness({
        currentAction: key => ({ key, method: "POST", risk: "write" }),
        currentDashboardPanel: key => key === "result" ? { key: "result", action_key: "mutation" } : null,
        els: { main: { querySelector: () => targetContainer } },
        renderDashboardPanelShell: () => "",
        renderPanelPlaceholder: () => "",
        bindDashboardPanelOpenControls: () => {},
        bindDashboardFilters: () => {},
    });
    mutationHarness.context.panel = panel;
    mutationHarness.state.lastAction = "mutation";
    mutationHarness.evaluate("clearDashboardTargetResults(panel)");
    assert.equal(targetAborts, 0);
    assert.equal(mutationHarness.state.latestRequestId, 42);
    assert.equal(mutationHarness.calls.length, 0);
});

test("full-screen passive authorization loss clears stale facts while mutation state survives", () => {
    const { state, calls, evaluate } = harness();
    assert.equal(evaluate('clearFullScreenActionState({key:"facts",method:"GET",risk:"read"},{status:403})'), true);
    assert.equal(state.currentViewModel, null);
    assert.deepEqual(Array.from(state.currentRows), []);
    assert.deepEqual(Object.entries(state.lastParams), []);
    assert.equal(state.lastPager, null);
    assert.equal(state.selectedRowContext, null);
    assert.equal(state.lastRaw, null);
    assert.equal(state.rawResponseAvailable, false);
    assert.equal(state.latestRequestId, 0);
    assert.ok(calls.some(([name]) => name === "updateRawDrawer"));

    const mutation = harness();
    mutation.state.lastAction = "mutation";
    mutation.state.lastParams = { pk: 9 };
    assert.equal(mutation.evaluate('clearFullScreenActionState({key:"mutation",method:"POST",risk:"write"},{status:403})'), false);
    assert.deepEqual(mutation.state.lastParams, { pk: 9 });
    assert.equal(mutation.state.latestRequestId, 42);
});


test("a related mutation keeps its submission context when a selector becomes unavailable", () => {
    const { state, calls, evaluate } = harness({
        currentAction: key => ({ key, method: "POST", risk: "write", confirmation_required: true }),
    });
    state.lastAction = "facts";
    evaluate('clearDashboardSelectorState({key:"selector",row_actions:[{action_key:"facts",result_panel_key:"result"}]})');
    assert.equal(state.lastAction, "facts");
    assert.deepEqual(state.lastParams, { pk: 9 });
    assert.equal(state.latestRequestId, 42);
    assert.equal(calls.length, 0);
});


test("an unauthorized successful-transport envelope never renders its supplied facts", () => {
    const { context, evaluate } = harness();
    const rendered = [];
    context.renderDashboardActionError = (panel, error) => rendered.push(["error", panel, error.status]);
    context.renderDashboardActionResult = () => rendered.push(["facts"]);
    evaluate('renderTargetedDashboardEnvelope({key:"facts",method:"GET",risk:"read"},{outcome:"success",response:{status_code:403},view_model:{kind:"detail",fields:[{value:"old private fact"}]}},{pk:9},"result","")');
    assert.deepEqual(rendered, [["error", "result", 403]]);
});


test("scope invalid with a missing nested status remains a reselect error", () => {
    const { context, evaluate } = harness();
    const errors = [];
    context.renderDashboardActionError = (_panel, error) => errors.push(error.status);
    context.renderDashboardActionResult = () => assert.fail("invalid scope must not display supplied facts");
    evaluate('renderTargetedDashboardEnvelope({key:"facts",method:"GET",risk:"read"},{user_error_code:"TUI_TASK_SCOPE_INVALID",view_model:{kind:"detail",fields:[{value:"old"}]}},{pk:9},"result","")');
    assert.deepEqual(errors, [400]);
});
