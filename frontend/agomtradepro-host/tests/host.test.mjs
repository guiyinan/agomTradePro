import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const sourceUrl = new URL("../src/index.js", import.meta.url);

async function loadHostRuntime() {
    const source = await readFile(sourceUrl, "utf8");
    const context = { globalThis: {} };
    context.globalThis.globalThis = context.globalThis;
    vm.runInNewContext(source, context, { filename: sourceUrl.pathname });
    return context.globalThis.__AGOMTUI_RUNTIME__;
}

test("home lane is read from explicit workflow metadata", async () => {
    const runtime = await loadHostRuntime();

    assert.equal(runtime.hooks.inferHomeLane({ workflow: { lane: "decision" } }), "decision");
    assert.equal(runtime.hooks.inferHomeLane({ workflow: { lane: "governance" } }), "governance");
    assert.equal(runtime.hooks.inferHomeLane({ workflow: { name: "每日投研流程" } }), "");
});

test("home action copy does not hardcode workflow step count", async () => {
    const runtime = await loadHostRuntime();
    const actions = runtime.hooks.getHomeActions({ preferredLane: "decision" });
    const decisionAction = actions.find(
        (action) => action.key === "operator.home.continue_decision_flow"
    );

    assert.equal(decisionAction.description, "进入每日投研主流程");
    assert.doesNotMatch(decisionAction.description, /\d+步/);

    const governanceAction = actions.find(
        (action) => action.key === "operator.home.enter_governance_flow"
    );
    assert.equal(governanceAction.description, "从系统治理起点进入治理主线");
    assert.doesNotMatch(governanceAction.description, /runtime/i);
});

test("home actions are filtered by server-published action keys", async () => {
    const runtime = await loadHostRuntime();
    const actions = runtime.hooks.getHomeActions({
        preferredLane: "decision",
        availableActionKeys: new Set([
            "operator.home.continue_decision_flow",
            "operator.home.resume_last_workspace",
            "operator.home.open_cli",
        ]),
    });

    assert.deepEqual(
        Array.from(actions, (action) => action.key),
        [
            "operator.home.continue_decision_flow",
            "operator.home.resume_last_workspace",
            "operator.home.open_cli",
        ]
    );
});

test("resume action presents a catalog label instead of an internal screen key", async () => {
    const runtime = await loadHostRuntime();
    const actions = runtime.hooks.getHomeActions({
        lastWorkspace: "ai-ops.providers",
        lastWorkspaceLabel: "我的 AI 服务商",
    });
    const resumeAction = actions.find(
        (action) => action.key === "operator.home.resume_last_workspace"
    );

    assert.equal(resumeAction.description, "我的 AI 服务商");
    assert.doesNotMatch(resumeAction.description, /ai-ops\.providers/);

    const fallbackActions = runtime.hooks.getHomeActions({
        lastWorkspace: "unknown.internal-key",
    });
    const fallbackResumeAction = fallbackActions.find(
        (action) => action.key === "operator.home.resume_last_workspace"
    );
    assert.equal(fallbackResumeAction.description, "最近工作区");
});
