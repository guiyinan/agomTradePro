import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";
import { fileURLToPath } from "node:url";

const sourceRoot = new URL("../src/", import.meta.url);
const runtimeSource = readFileSync(fileURLToPath(new URL("00-runtime.js", sourceRoot)), "utf8");
const workspaceSource = readFileSync(fileURLToPath(new URL("15-workspace-state.js", sourceRoot)), "utf8");

function sourceBetween(source, startMarker, endMarker) {
    const start = source.indexOf(startMarker);
    const end = source.indexOf(endMarker, start);
    assert.notEqual(start, -1, `missing source marker: ${startMarker}`);
    assert.notEqual(end, -1, `missing source marker: ${endMarker}`);
    return source.slice(start, end);
}

const runtimeHelpers = sourceBetween(
    runtimeSource,
    "    function actionUiKey(action) {",
    "    async function fetchJson(url, options) {",
);
const passiveReadHelper = sourceBetween(
    workspaceSource,
    "    function isPassiveRead(action) {",
    "    function safeWorkspaceField(field) {",
);

const actions = [
    { key: "research.lookup", ui_key: "ui.research.lookup", method: "GET", risk: "read" },
    { key: "research.write", ui_key: "ui.research.write", method: "POST", risk: "write", confirmation_required: true },
    { key: "research.confirmed-read", ui_key: "ui.research.confirmed-read", method: "GET", risk: "read", confirmation_required: true },
    { key: "research.other", ui_key: "ui.research.other", method: "POST", risk: "write" },
];

function makeForm(actionRef, { value = "", researchEntry = false, entryForm = true } = {}) {
    const classes = new Set(entryForm ? ["tui-action-entry-form"] : []);
    return {
        dataset: { actionUiKey: actionRef },
        classList: { contains: className => classes.has(className) },
        closest: selector => selector === "[data-research-again-entry]" && researchEntry
            ? { dataset: { researchAgainEntry: "true" } }
            : null,
        submittedValue: value,
    };
}

function makeRuntime() {
    let now = 1000;
    const calls = [];
    const statuses = [];
    const state = {
        screen: { actions },
        lastFormTriggerRef: "",
        lastFormTriggerForm: null,
        lastFormTriggerAt: 0,
    };
    const context = vm.createContext({
        Date: { now: () => now },
        state,
        setStatus: message => statuses.push(message),

        runAction: (actionRef, form, options) => calls.push({
            actionRef,
            form,
            submittedValue: form?.submittedValue,
            options,
        }),
    });
    vm.runInContext(
        `const actionTriggerGuardMs = 250;\n${runtimeHelpers}\n${passiveReadHelper}\nthis.triggerActionForm = triggerActionForm;`,
        context,
        { filename: "candidate/00-runtime.js" },
    );
    return {
        calls,
        context,
        state,
        statuses,
        setNow(value) { now = value; },
    };
}

test("same form keeps the 250 ms duplicate guard at 0, 249 and 250 ms", () => {
    for (const [elapsed, expectedCalls] of [[0, 0], [249, 0], [250, 1]]) {
        const runtime = makeRuntime();
        const form = makeForm("ui.research.lookup");
        runtime.state.lastFormTriggerRef = "ui.research.lookup";
        runtime.state.lastFormTriggerForm = form;
        runtime.state.lastFormTriggerAt = 0;
        runtime.setNow(elapsed);

        runtime.context.triggerActionForm(form);

        assert.equal(runtime.calls.length, expectedCalls, `elapsed=${elapsed}ms`);
    }
});

test("click plus submit from the same passive-read form launches one action", () => {
    const runtime = makeRuntime();
    const form = makeForm("ui.research.lookup", { value: "600000.SH" });

    runtime.context.triggerActionForm(form);
    runtime.context.triggerActionForm(form);

    assert.equal(runtime.calls.length, 1);
    assert.equal(runtime.calls[0].form, form);
});

test("a fresh result research form can immediately submit its changed value", () => {
    const runtime = makeRuntime();
    const previousForm = makeForm("ui.research.lookup", { value: "600000.SH", researchEntry: true });
    const nextForm = makeForm("ui.research.lookup", { value: "NO_MATCH_TUX08", researchEntry: true });
    runtime.state.lastFormTriggerRef = "ui.research.lookup";
    runtime.state.lastFormTriggerForm = previousForm;
    runtime.state.lastFormTriggerAt = 1000;
    runtime.setNow(1001);

    runtime.context.triggerActionForm(nextForm);

    assert.equal(runtime.calls.length, 1);
    assert.equal(runtime.calls[0].actionRef, "ui.research.lookup");
    assert.equal(runtime.calls[0].form, nextForm);
    assert.equal(runtime.calls[0].submittedValue, "NO_MATCH_TUX08");
    assert.equal(runtime.state.lastFormTriggerForm, nextForm);
});

test("a distinct passive-read form outside the result entry stays guarded", () => {
    const runtime = makeRuntime();
    const previousForm = makeForm("ui.research.lookup", { researchEntry: true });
    const unrelatedForm = makeForm("ui.research.lookup", { researchEntry: false });
    runtime.state.lastFormTriggerRef = "ui.research.lookup";
    runtime.state.lastFormTriggerForm = previousForm;
    runtime.state.lastFormTriggerAt = 1000;
    runtime.setNow(1001);

    runtime.context.triggerActionForm(unrelatedForm);

    assert.equal(runtime.calls.length, 0);
});

test("a passive form without the entry class stays guarded under the result host", () => {
    const runtime = makeRuntime();
    runtime.state.lastFormTriggerRef = "ui.research.lookup";
    runtime.state.lastFormTriggerForm = makeForm("ui.research.lookup", { researchEntry: true });
    runtime.state.lastFormTriggerAt = 1000;
    runtime.setNow(1001);

    runtime.context.triggerActionForm(makeForm("ui.research.lookup", { researchEntry: true, entryForm: false }));

    assert.equal(runtime.calls.length, 0);
});

test("new mutation and confirmation-bound read forms remain guarded", () => {
    for (const actionRef of ["ui.research.write", "ui.research.confirmed-read"]) {
        const runtime = makeRuntime();
        runtime.state.lastFormTriggerRef = actionRef;
        runtime.state.lastFormTriggerForm = makeForm(actionRef, { researchEntry: true });
        runtime.state.lastFormTriggerAt = 1000;
        runtime.setNow(1001);

        runtime.context.triggerActionForm(makeForm(actionRef, { researchEntry: true }));

        assert.equal(runtime.calls.length, 0, actionRef);
    }
});

test("unknown actions do not receive the fresh passive-read exemption", () => {
    const runtime = makeRuntime();
    runtime.state.lastFormTriggerRef = "ui.unknown";
    runtime.state.lastFormTriggerForm = makeForm("ui.unknown", { researchEntry: true });
    runtime.state.lastFormTriggerAt = 1000;
    runtime.setNow(1001);

    runtime.context.triggerActionForm(makeForm("ui.unknown", { researchEntry: true }));

    assert.equal(runtime.calls.length, 0);
    assert.deepEqual(runtime.statuses, []);
});

test("a different actionRef resolves and runs its own action independently", () => {
    const runtime = makeRuntime();
    runtime.state.lastFormTriggerRef = "ui.research.lookup";
    runtime.state.lastFormTriggerForm = makeForm("ui.research.lookup", { researchEntry: true });
    runtime.state.lastFormTriggerAt = 1000;
    runtime.setNow(1001);
    const nextForm = makeForm("ui.research.other", { value: "different-action" });

    runtime.context.triggerActionForm(nextForm);

    assert.equal(runtime.calls.length, 1);
    assert.equal(runtime.calls[0].actionRef, "ui.research.other");
    assert.equal(runtime.calls[0].form, nextForm);
});
