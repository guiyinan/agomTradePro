import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";
import { fileURLToPath } from "node:url";
const sourceRoot = fileURLToPath(new URL("../src/", import.meta.url));
const sources = Object.fromEntries(Object.entries({navigation:"10-navigation.js", experience:"12-experience.js", actions:"30-actions.js", workspace:"15-workspace-state.js"}).map(([key, name]) => [key, fs.readFileSync(`${sourceRoot}/${name}`, "utf8")]));
test("task entry preserves action identity, unique controls, explicit submit and safe workspace drafts", () => {
function check(_name, callback) { callback(); }
function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
    })[character]);
}

function countMatches(value, pattern) {
    return (String(value).match(pattern) || []).length;
}

const triggerCalls = [];
const context = {
    CSS: { escape: (value) => String(value) },
    escapeHtml,
    actionUiKey: (action) => action.ui_key || action.key,
    actionMetaLabel: () => "读取",
    actionSubmitLabel: (action) => String(action.submit_label || "执行"),
    isActionCompleted: () => false,
    operatorText: (value) => String(value || ""),
    triggerActionForm: (form) => triggerCalls.push(form),
    document: {},
};
vm.createContext(context);

vm.runInContext(sources.navigation, context, { filename: "candidate/10-navigation.js" });
vm.runInContext(sources.experience, context, { filename: "candidate/12-experience.js" });
vm.runInContext(sources.actions, context, { filename: "candidate/30-actions.js" });

const action = {
    key: "fixture.lookup",
    ui_key: "ui.fixture",
    screen_key: "fixture.screen",
    label: "Fixture lookup",
    description: "读取一个离线示例对象。",
    submit_label: "开始读取示例",
    risk: "read",
    confirmation_required: true,
    fields: [
        {
            key: "fixture_param",
            label: "示例参数",
            input_type: "text",
            value_type: "string",
            required: true,
        },
        {
            key: "hidden_hint",
            label: "内部提示",
            input_type: "hidden",
            value_type: "string",
            default: "hidden",
        },
        {
            key: "password",
            label: "密码",
            input_type: "password",
            value_type: "string",
        },
        {
            key: "secret",
            label: "密钥",
            input_type: "text",
            presentation_semantic: "secret",
            value_type: "string",
        },
        {
            key: "endpoint",
            label: "地址",
            input_type: "text",
            presentation_semantic: "endpoint_url",
            value_type: "string",
        },
    ],
};

const sidebarHtml = String(context.renderActionForm(action));
triggerCalls.length = 0;
const entryHtml = String(context.renderActionForm(action, { entry: true, idNamespace: "entry" }));

check("professional form retains heading, metadata, and row-fill", () => {
    assert.match(sidebarHtml, /tui-action-button/);
    assert.match(sidebarHtml, /tui-action-meta/);
    assert.match(sidebarHtml, /tui-row-fill-button/);
});

check("entry form is one-submit and has no professional chrome", () => {
    assert.strictEqual(countMatches(entryHtml, /<button[^>]+type="submit"/g), 1);
    assert.doesNotMatch(entryHtml, /tui-action-meta/);
    assert.doesNotMatch(entryHtml, /tui-row-fill-button/);
    assert.doesNotMatch(entryHtml, /tui-action-desc/);
    assert.match(entryHtml, /tui-action-confirm/);
});

check("entry field is namespaced, labeled, and keeps action identity", () => {
    const sidebarField = sidebarHtml.match(/<input[^>]+id="([^"]+)"[^>]+name="fixture_param"/);
    const entryField = entryHtml.match(/<input[^>]+id="([^"]+)"[^>]+name="fixture_param"/);
    assert.ok(sidebarField && entryField);
    assert.notStrictEqual(entryField[1], sidebarField[1]);
    assert.match(entryField[1], /^tui-entry-/);
    assert.match(entryHtml, /示例参数/);
    assert.ok(entryHtml.includes(`for="${entryField[1]}"`));
    assert.match(entryHtml, /data-action-ui-key="ui\.fixture"/);
    assert.match(sidebarHtml, /data-action-ui-key="ui\.fixture"/);
});

check("rendering does not submit and original submit binder remains", () => {
    assert.strictEqual(triggerCalls.length, 0);
    let submitHandler = null;
    const form = {
        dataset: {},
        querySelector: () => null,
        addEventListener: (eventName, handler) => {
            if (eventName === "submit") submitHandler = handler;
        },
    };
    context.bindRenderedActionForms({ querySelectorAll: () => [form] });
    assert.strictEqual(triggerCalls.length, 0);
    assert.ok(submitHandler);
    let prevented = false;
    let stopped = false;
    submitHandler({
        preventDefault: () => { prevented = true; },
        stopPropagation: () => { stopped = true; },
    });
    assert.strictEqual(triggerCalls.length, 1);
    assert.strictEqual(triggerCalls[0], form);
    assert.strictEqual(prevented, true);
    assert.strictEqual(stopped, true);
});

check("task entry renderer mounts, binds, focuses, and defers submission", () => {
    let taskMarkup = "";
    let renderedTaskForm = null;
    let submitHandler = null;
    let submitBindings = 0;
    let focusCalls = 0;
    let firstVisibleFocused = false;
    const firstVisibleInput = {
        type: "text",
        name: "fixture_param",
        focus: () => { firstVisibleFocused = true; },
    };
    const taskMain = {
        set innerHTML(value) {
            taskMarkup = String(value);
            renderedTaskForm = {
                dataset: { actionUiKey: "ui.fixture" },
                querySelector: (selector) => {
                    if (selector.includes("input")) return firstVisibleInput;
                    return null;
                },
                addEventListener: (eventName, handler) => {
                    if (eventName === "submit") {
                        submitBindings += 1;
                        submitHandler = handler;
                    }
                },
            };
        },
        get innerHTML() {
            return taskMarkup;
        },
        querySelectorAll: (selector) => (
            selector === "[data-action-ui-key]" && renderedTaskForm ? [renderedTaskForm] : []
        ),
        querySelector: (selector) => (
            selector.includes('data-action-ui-key="ui.fixture"') ? renderedTaskForm : null
        ),
    };
    context.window = { requestAnimationFrame: (callback) => callback() };
    context.setTimeout = (callback) => { callback(); return 1; };
    context.els = { main: taskMain };
    context.focusActionFormInPanel = (form) => {
        focusCalls += 1;
        assert.strictEqual(form, renderedTaskForm);
        form.querySelector("input:not([type=hidden]):not([disabled])")?.focus();
    };
    triggerCalls.length = 0;
    context.renderTaskStartEntryState(
        { screen: { label: "Fixture screen", summary: "离线示例" } },
        action,
        { empty_copy: "填写示例参数", help_steps: [] },
        action.fields[0],
    );
    assert.match(taskMarkup, /tui-action-entry-form/);
    assert.strictEqual(submitBindings, 1);
    assert.strictEqual(focusCalls, 1);
    assert.strictEqual(firstVisibleFocused, true);
    assert.strictEqual(triggerCalls.length, 0);
    assert.ok(submitHandler);
    let prevented = false;
    let stopped = false;
    submitHandler({
        preventDefault: () => { prevented = true; },
        stopPropagation: () => { stopped = true; },
    });
    assert.strictEqual(triggerCalls.length, 1);
    assert.strictEqual(triggerCalls[0], renderedTaskForm);
    assert.strictEqual(prevented, true);
    assert.strictEqual(stopped, true);
});

function makeInput(inputType, value) {
    return { input_type: inputType, value, checked: false };
}

function makeForm(values) {
    const fields = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value]));
    return { fields };
}

const workspaceFields = [
    { key: "fixture_param", label: "示例参数", input_type: "text", value_type: "string" },
    { key: "note", label: "备注", input_type: "text", value_type: "string" },
    { key: "password", label: "密码", input_type: "password", value_type: "string" },
    { key: "hidden_hint", label: "内部提示", input_type: "hidden", value_type: "string" },
    { key: "endpoint", label: "地址", input_type: "text", presentation_semantic: "endpoint_url" },
    { key: "secret", label: "密钥", input_type: "text", presentation_semantic: "secret" },
];
const workspaceAction = {
    ...action,
    fields: workspaceFields,
    method: "GET",
    confirmation_required: false,
};
const entryForm = makeForm({
    fixture_param: makeInput("text", "fixture-entry"),
    note: makeInput("text", "entry-note"),
    password: makeInput("password", "entry-secret"),
    hidden_hint: makeInput("hidden", "entry-hidden"),
    endpoint: makeInput("text", "https://entry.invalid"),
    secret: makeInput("text", "entry-secret-value"),
});
const sidebarForm = makeForm({
    fixture_param: makeInput("text", "sidebar-param"),
    note: makeInput("text", "sidebar-note"),
    password: makeInput("password", "sidebar-secret"),
    hidden_hint: makeInput("hidden", "sidebar-hidden"),
    endpoint: makeInput("text", "https://sidebar.invalid"),
    secret: makeInput("text", "sidebar-secret-value"),
});
const professionalMainForm = makeForm({
    fixture_param: makeInput("text", "professional-main-param"),
    note: makeInput("text", "professional-main-note"),
});
let entryEnabled = true;
const mainRoot = {
    scrollTop: 17,
    querySelector: (selector) => {
        if (selector.includes(".tui-action-entry-form")) {
            return entryEnabled ? entryForm : null;
        }
        return professionalMainForm;
    },
};
const actionsRoot = { querySelector: () => sidebarForm };

context.formFieldElement = (form, key) => form?.fields?.[key] || null;
context.currentAction = (reference) => reference === workspaceAction.key ? workspaceAction : null;
context.isExperienceHomeScreen = () => false;
context.actionTier = () => "primary";
context.screenCompletedSet = () => new Set();
context.persistProgress = () => {};
context.els = { main: mainRoot, actions: actionsRoot };
context.state = {
    experienceHomeFresh: false,
    screen: { screen: { key: "fixture.screen" }, actions: [workspaceAction] },
    lastAction: null,
    lastParams: {},
    currentViewModel: null,
    dashboardFilters: {},
    filterText: "",
    clientPage: 1,
    clientPageSize: 20,
    selectedRowIndex: 0,
};
context.runtimeCore = {};
vm.runInContext(
    `${sources.workspace}\nthis.__workspaceProbe = { captureWorkspace, restoreWorkspaceForms, workspaceStates };`,
    context,
    { filename: "candidate/15-workspace-state.js" },
);

const workspaceProbe = context.__workspaceProbe;

check("capture prefers entry form and filters sensitive fields", () => {
    entryEnabled = true;
    context.state.screen.screen.key = "fixture.screen";
    workspaceProbe.captureWorkspace();
    const snapshot = workspaceProbe.workspaceStates.get("fixture.screen");
    assert.ok(snapshot);
    assert.strictEqual(snapshot.drafts[workspaceAction.key].fixture_param, "fixture-entry");
    assert.strictEqual(snapshot.drafts[workspaceAction.key].note, "entry-note");
    assert.strictEqual(Object.keys(snapshot.drafts[workspaceAction.key]).length, 2);
});

check("restore prefers entry form and keeps sensitive fields untouched", () => {
    entryForm.fields.fixture_param.value = "before-restore";
    entryForm.fields.note.value = "before-note";
    entryForm.fields.password.value = "entry-secret";
    workspaceProbe.restoreWorkspaceForms({
        drafts: {
            [workspaceAction.key]: {
                fixture_param: "restored-param",
                note: "restored-note",
                password: "must-not-restore",
            },
        },
    });
    assert.strictEqual(entryForm.fields.fixture_param.value, "restored-param");
    assert.strictEqual(entryForm.fields.note.value, "restored-note");
    assert.strictEqual(entryForm.fields.password.value, "entry-secret");
    assert.strictEqual(sidebarForm.fields.note.value, "sidebar-note");
});

check("without entry form, professional main does not steal sidebar draft", () => {
    entryEnabled = false;
    context.state.screen.screen.key = "fixture.screen-professional";
    workspaceProbe.captureWorkspace();
    const snapshot = workspaceProbe.workspaceStates.get("fixture.screen-professional");
    assert.ok(snapshot);
    assert.strictEqual(snapshot.drafts[workspaceAction.key].note, "sidebar-note");
    assert.notStrictEqual(snapshot.drafts[workspaceAction.key].note, "professional-main-note");
});

});
