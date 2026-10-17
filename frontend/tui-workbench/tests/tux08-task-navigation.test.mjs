import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";
import { fileURLToPath } from "node:url";
const sourceRoot = fileURLToPath(new URL("../src/", import.meta.url));
const helperSource = fs.readFileSync(`${sourceRoot}/35-next-step-navigation.js`, "utf8");
const viewsSource = fs.readFileSync(`${sourceRoot}/40-views.js`, "utf8");
async function check(name, callback) { await test(name, callback); }

function fixtureActions() {
    const safeField = { key: "fixture_param", input_type: "text", required: true };
    const passwordField = { key: "password", input_type: "password" };
    const secretField = { key: "secret", input_type: "text", presentation_semantic: "secret" };
    const endpointField = { key: "endpoint", input_type: "text", presentation_semantic: "endpoint_url" };
    const continuationField = { key: "continuation_token", input_type: "text", presentation_semantic: "secret" };
    const make = (key, method, risk, confirmationRequired = false) => ({
        key,
        ui_key: `ui.${key}`,
        screen_key: key.startsWith("fixture.target") ? "fixture.target" : "fixture.source",
        method,
        risk,
        confirmation_required: confirmationRequired,
        fields: [safeField, passwordField, secretField, endpointField, continuationField],
    });
    return {
        sourceRead: make("fixture.source-read", "GET", "read"),
        sourceWrite: make("fixture.source-write", "POST", "write", true),
        targetRead: make("fixture.target-read", "GET", "read"),
    };
}

function makeScreen(key, actions) {
    return { screen: { key, label: key }, actions };
}

function makeRuntime({ sourceAction, targetAction, targetActions = [targetAction], deferred = null, failTarget = false, failSource = false, revealResult = true } = {}) {
    const source = sourceAction || fixtureActions().sourceRead;
    const target = targetAction || fixtureActions().targetRead;
    const state = {
        screen: makeScreen("fixture.source", [source]),
        lastAction: source.key,
        lastParams: {
            fixture_param: "source-safe",
            password: "source-password",
            endpoint: "https://source.invalid",
            continuation_token: "source-continuation",
        },
    };
    const statuses = [];
    const loadCalls = [];
    const revealCalls = [];
    const runCalls = [];
    const routes = [];
    const returnControls = [];
    let clearCount = 0;
    let activeScreen = "fixture.source";
    let deferredResolve = null;
    const sourceSpec = makeScreen("fixture.source", [source]);
    const targetSpec = makeScreen("fixture.target", targetActions);
    let revealOutcome = revealResult;
    const deferredPromise = deferred
        ? new Promise((resolve) => { deferredResolve = resolve; })
        : null;
    const runtime = {
        state,
        statuses,
        loadCalls,
        revealCalls,
        runCalls,
        routes,
        returnControls,
        getCurrentScreenKey: () => activeScreen,
        getState: () => state,
        currentAction: (actionRef) => (state.screen.actions || []).find((item) => (
            item.key === actionRef || item.ui_key === actionRef
        )) || null,
        isPassiveRead: (action) => Boolean(
            action && action.method === "GET" && action.risk === "read" && !action.confirmation_required
        ),
        continuationFields: () => new Set(["continuation_token"]),
        loadScreen: async (screenKey, options) => {
            loadCalls.push({ screenKey, options });
            if (failTarget && screenKey === "fixture.target") {
                return null;
            }
            if (failSource && screenKey === "fixture.source") {
                return null;
            }
            if (deferredPromise && screenKey === "fixture.target") {
                const loaded = await deferredPromise;
                activeScreen = loaded.screen.key;
                state.screen = loaded;
                return loaded;
            }
            const loaded = screenKey === "fixture.target" ? targetSpec : sourceSpec;
            activeScreen = loaded.screen.key;
            state.screen = loaded;
            return loaded;
        },
        resolveDeferred: (screenSpec = targetSpec) => deferredResolve?.(screenSpec),
        revealTaskWithParams: (action, params, options) => {
            revealCalls.push({ action, params, options });
            return revealOutcome;
        },
        setRevealResult: (value) => { revealOutcome = value; },
        setFailSource: (value) => { failSource = value; },
        runAction: (actionKey, form, options) => {
            runCalls.push({ actionKey, form, options });
        },
        setStatus: (message) => statuses.push(String(message)),
        syncLocation: (screenKey, actionKey, options) => routes.push({ screenKey, actionKey, options }),
        renderReturnControl: (context, onReturn) => returnControls.push({ context, onReturn }),
        clearReturnControl: () => { clearCount += 1; },
        screenLabel: (screenKey) => `label:${screenKey}`,
        clearCount: () => clearCount,
    };
    return runtime;
}

function newHelper(runtime) {
    const context = {};
    vm.createContext(context);
    vm.runInContext(`${helperSource}\nthis.__create = createNextStepNavigation;`, context, {
        filename: "next-step-navigation.js",
    });
    return context.__create(runtime);
}

async function main() {
    await check("cross-screen target loads with safe reveal and no automatic run", async () => {
        const actions = fixtureActions();
        const runtime = makeRuntime({ targetAction: actions.targetRead });
        const controller = newHelper(runtime);
        const result = await controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: {
                fixture_param: "target-safe",
                password: "target-password",
                endpoint: "https://target.invalid",
                continuation_token: "target-continuation",
                confirmation: "never-copy",
                screen: "fixture.other",
                action: "fixture.other-read",
                finite_bad: NaN,
                infinite_bad: Infinity,
            },
        });
        assert.strictEqual(result.status, "opened");
        assert.strictEqual(runtime.loadCalls.length, 1);
        assert.strictEqual(runtime.loadCalls[0].options.suppressAutoAction, true);
        assert.strictEqual(runtime.loadCalls[0].options.skipRestoreAction, true);
        assert.strictEqual(runtime.loadCalls[0].options.suppressHistory, true);
        assert.strictEqual(runtime.runCalls.length, 0);
        assert.strictEqual(runtime.revealCalls.length, 1);
        assert.strictEqual(runtime.revealCalls[0].action.key, actions.targetRead.key);
        assert.strictEqual(runtime.revealCalls[0].params.fixture_param, "target-safe");
        assert.strictEqual(Object.keys(runtime.revealCalls[0].params).length, 1);
        assert.strictEqual(runtime.routes[0].screenKey, "fixture.target");
        assert.strictEqual(runtime.routes[0].actionKey, actions.targetRead.key);
        assert.strictEqual(runtime.returnControls.length, 1);
        const context = controller.currentContext();
        assert.strictEqual(context.sourceScreenKey, "fixture.source");
        assert.strictEqual(context.sourceActionKey, actions.sourceRead.key);
        assert.strictEqual(context.sourceParams.fixture_param, "source-safe");
        assert.strictEqual(Object.keys(context.sourceParams).length, 1);
        assert.strictEqual(context.targetParams.fixture_param, "target-safe");
        assert.strictEqual(Object.keys(context.targetParams).length, 1);
    });

    await check("return reloads source and refreshes only a passive read", async () => {
        const actions = fixtureActions();
        const runtime = makeRuntime({ targetAction: actions.targetRead });
        const controller = newHelper(runtime);
        await controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: { fixture_param: "target-safe" },
        });
        const result = await controller.returnToSource();
        assert.strictEqual(result.status, "returned");
        assert.strictEqual(result.refreshed, true);
        assert.strictEqual(runtime.loadCalls[1].options.suppressAutoAction, true);
        assert.strictEqual(runtime.loadCalls[1].options.skipRestoreAction, true);
        assert.strictEqual(runtime.runCalls.length, 1);
        assert.strictEqual(runtime.runCalls[0].actionKey, actions.sourceRead.key);
        assert.strictEqual(runtime.runCalls[0].options.params.fixture_param, "source-safe");
        assert.strictEqual(Object.keys(runtime.runCalls[0].options.params).length, 1);
        assert.strictEqual(runtime.routes[1].screenKey, "fixture.source");
        assert.strictEqual(runtime.routes[1].actionKey, actions.sourceRead.key);
        assert.strictEqual(controller.currentContext(), null);
    });

    await check("write source returns to form without replay", async () => {
        const actions = fixtureActions();
        const runtime = makeRuntime({ sourceAction: actions.sourceWrite, targetAction: actions.targetRead });
        const controller = newHelper(runtime);
        await controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: { fixture_param: "target-safe" },
        });
        const result = await controller.returnToSource();
        assert.strictEqual(result.status, "returned");
        assert.strictEqual(result.refreshed, false);
        assert.strictEqual(runtime.runCalls.length, 0);
        assert.strictEqual(runtime.revealCalls.length, 2);
        assert.strictEqual(runtime.revealCalls[1].action.key, actions.sourceWrite.key);
    });

    await check("fresh target metadata rejects stale currentAction and keeps recovery", async () => {
        const actions = fixtureActions();
        const runtime = makeRuntime({ targetAction: actions.targetRead, targetActions: [] });
        const originalCurrentAction = runtime.currentAction;
        runtime.currentAction = (actionRef) => actionRef === actions.targetRead.key
            ? actions.targetRead
            : originalCurrentAction(actionRef);
        const controller = newHelper(runtime);
        const result = await controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: { fixture_param: "target-safe" },
        });
        assert.strictEqual(result.status, "forbidden");
        assert.strictEqual(runtime.revealCalls.length, 0);
        assert.strictEqual(runtime.returnControls.length, 1);
        assert.strictEqual(controller.currentContext().sourceScreenKey, "fixture.source");
        assert.match(runtime.statuses.at(-1), /不可用/);
        const returned = await controller.returnToSource();
        assert.strictEqual(returned.status, "returned");
        assert.strictEqual(runtime.runCalls.length, 1);
    });

    await check("missing loaded screen key cannot claim target and keeps recovery", async () => {
        const actions = fixtureActions();
        const runtime = makeRuntime({ targetAction: actions.targetRead });
        const originalLoadScreen = runtime.loadScreen;
        runtime.loadScreen = async (screenKey, options) => {
            if (screenKey === "fixture.target") {
                runtime.loadCalls.push({ screenKey, options });
                return { actions: [actions.targetRead] };
            }
            return originalLoadScreen(screenKey, options);
        };
        const controller = newHelper(runtime);
        const result = await controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: { fixture_param: "target-safe" },
        });
        assert.strictEqual(result.status, "error");
        assert.strictEqual(runtime.revealCalls.length, 0);
        assert.strictEqual(runtime.returnControls.length, 1);
        assert.strictEqual(controller.currentContext().sourceScreenKey, "fixture.source");
        const returned = await controller.returnToSource();
        assert.strictEqual(returned.status, "returned");
        assert.strictEqual(runtime.runCalls.length, 1);
    });

    await check("required unsafe field reveals source form without passive replay", async () => {
        const actions = fixtureActions();
        const sourceWithRequiredSecret = {
            ...actions.sourceRead,
            fields: actions.sourceRead.fields.map((field) => field.key === "secret"
                ? { ...field, required: true }
                : field),
        };
        const runtime = makeRuntime({ sourceAction: sourceWithRequiredSecret, targetAction: actions.targetRead });
        const controller = newHelper(runtime);
        const opened = await controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: { fixture_param: "target-safe" },
        });
        assert.strictEqual(opened.status, "opened");
        const returned = await controller.returnToSource();
        assert.strictEqual(returned.status, "returned");
        assert.strictEqual(returned.refreshed, false);
        assert.strictEqual(runtime.runCalls.length, 0);
        assert.strictEqual(runtime.revealCalls.length, 2);
        assert.strictEqual(runtime.revealCalls[1].action.key, sourceWithRequiredSecret.key);
        assert.strictEqual(Object.prototype.hasOwnProperty.call(runtime.revealCalls[1].params, "secret"), false);
    });

    await check("false reveal result is unavailable without optimistic open and remains recoverable", async () => {
        const actions = fixtureActions();
        const runtime = makeRuntime({ targetAction: actions.targetRead, revealResult: false });
        const controller = newHelper(runtime);
        const result = await controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: { fixture_param: "target-safe" },
        });
        assert.strictEqual(result.status, "unavailable");
        assert.strictEqual(runtime.runCalls.length, 0);
        assert.strictEqual(controller.currentContext().targetScreenKey, "fixture.target");
        assert.strictEqual(runtime.returnControls.length, 1);
        assert.strictEqual(runtime.routes.length, 0);
        assert.doesNotMatch(runtime.statuses.at(-1), /已打开|已定位/);
        runtime.setRevealResult(true);
        const returned = await controller.returnToSource();
        assert.strictEqual(returned.status, "returned");
        assert.strictEqual(runtime.runCalls.length, 1);
    });

    await check("failed target load preserves a visible source recovery", async () => {
        const actions = fixtureActions();
        const runtime = makeRuntime({ targetAction: actions.targetRead, failTarget: true });
        const controller = newHelper(runtime);
        const result = await controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: { fixture_param: "target-safe" },
        });
        assert.strictEqual(result.status, "error");
        assert.strictEqual(runtime.returnControls.length, 1);
        assert.strictEqual(controller.currentContext().sourceScreenKey, "fixture.source");
        const returned = await controller.returnToSource();
        assert.strictEqual(returned.status, "returned");
        assert.strictEqual(runtime.runCalls.length, 1);
    });

    await check("failed source return keeps context for a later retry", async () => {
        const actions = fixtureActions();
        const runtime = makeRuntime({ targetAction: actions.targetRead });
        const controller = newHelper(runtime);
        await controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: { fixture_param: "target-safe" },
        });
        runtime.setFailSource(true);
        const failedReturn = await controller.returnToSource();
        assert.strictEqual(failedReturn.status, "error");
        assert.strictEqual(controller.currentContext().sourceScreenKey, "fixture.source");
        assert.ok(runtime.returnControls.length >= 2);
        runtime.setFailSource(false);
        const retried = await controller.returnToSource();
        assert.strictEqual(retried.status, "returned");
        assert.strictEqual(runtime.runCalls.length, 1);
    });

    await check("late navigation is discarded after invalidation", async () => {
        const actions = fixtureActions();
        const runtime = makeRuntime({ targetAction: actions.targetRead, deferred: true });
        const controller = newHelper(runtime);
        const pending = controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: { fixture_param: "target-safe" },
        });
        controller.invalidate();
        runtime.resolveDeferred();
        const result = await pending;
        assert.strictEqual(result.status, "stale");
        assert.strictEqual(runtime.revealCalls.length, 0);
        assert.strictEqual(runtime.returnControls.length, 0);
    });

    await check("missing source action returns to screen without replay", async () => {
        const actions = fixtureActions();
        const runtime = makeRuntime({ targetAction: actions.targetRead });
        runtime.state.lastAction = "";
        const controller = newHelper(runtime);
        const opened = await controller.open({
            screen_key: "fixture.target",
            action_key: actions.targetRead.key,
            params: { fixture_param: "target-safe" },
        });
        assert.strictEqual(opened.status, "opened");
        const returned = await controller.returnToSource();
        assert.strictEqual(returned.status, "forbidden");
        assert.strictEqual(runtime.runCalls.length, 0);
        assert.strictEqual(runtime.revealCalls.length, 1);
        assert.strictEqual(runtime.routes.at(-1).screenKey, "fixture.source");
        assert.strictEqual(runtime.routes.at(-1).actionKey, "");
        assert.match(runtime.statuses.at(-1), /原工作区/);
    });

    const viewContext = {
        escapeHtml: (value) => String(value ?? ""),
        state: { screen: { screen: { key: "fixture.source" } } },
        runCalls: [],
        loadCalls: [],
        runAction: (...args) => viewContext.runCalls.push(args),
        loadScreen: (...args) => viewContext.loadCalls.push(args),
        setStatus: () => {},
        document: {},
        URL,
        window: {
            location: {
                href: "https://example.invalid/tui/?screen=fixture.source&action=fixture.source-read&stock_code=old&reauth=1&secret=do-not-copy&arbitraryquery=old",
            },
            history: {},
        },
        els: {},
        createNextStepNavigation: () => { throw new Error("unexpected helper construction"); },
    };
    vm.createContext(viewContext);
    vm.runInContext(`${viewsSource}\nthis.__views = { executeNextStep, renderNextStepReturnControl, clearNextStepReturnControl, syncNextStepLocation };`, viewContext, {
        filename: "40-views.js",
    });

    await check("same-screen next step preserves direct runAction path", async () => {
        viewContext.runCalls.length = 0;
        viewContext.loadCalls.length = 0;
        viewContext.__views.executeNextStep({
            screen_key: "fixture.source",
            action_key: "fixture.source-read",
            params: { fixture_param: "same-screen" },
        });
        assert.strictEqual(viewContext.runCalls.length, 1);
        assert.strictEqual(viewContext.runCalls[0][0], "fixture.source-read");
        assert.strictEqual(viewContext.loadCalls.length, 0);
    });

    await check("candidate mounts a visible return button in the workflow host", async () => {
        let markup = "";
        let clickHandler = null;
        let returnHostCount = 0;
        let returnButtonCount = 0;
        const button = {
            disabled: false,
            addEventListener: (eventName, handler) => {
                if (eventName === "click") clickHandler = handler;
            },
        };
        const returnHost = {
            remove: () => {
                returnHostCount -= 1;
                returnButtonCount -= 1;
            },
        };
        const host = {
            hidden: true,
            innerHTML: "",
            querySelectorAll: (selector) => {
                if (selector === "[data-next-step-return-host]") return returnHostCount ? [returnHost] : [];
                if (selector === "[data-next-step-return]") return returnButtonCount ? [button] : [];
                return [];
            },
            insertAdjacentHTML: (_position, value) => {
                markup += value;
                returnHostCount += 1;
                returnButtonCount += 1;
            },
            querySelector: (selector) => selector === "[data-next-step-return]" && returnButtonCount ? button : null,
        };
        viewContext.els.workflowStrip = host;
        viewContext.__views.renderNextStepReturnControl(
            { sourceScreenKey: "fixture.source", sourceScreenLabel: "Fixture source" },
            async () => ({ status: "returned" }),
        );
        assert.strictEqual(host.hidden, false);
        assert.match(markup, /data-next-step-return/);
        assert.match(markup, /返回原任务/);
        assert.ok(clickHandler);
        assert.strictEqual(returnHostCount, 1);
        viewContext.__views.renderNextStepReturnControl(
            { sourceScreenKey: "fixture.source", sourceScreenLabel: "Fixture source" },
            async () => ({ status: "returned" }),
        );
        assert.strictEqual(returnHostCount, 1);
        assert.strictEqual(returnButtonCount, 1);
        viewContext.__views.clearNextStepReturnControl();
        assert.strictEqual(returnHostCount, 0);
        assert.strictEqual(returnButtonCount, 0);
    });

    await check("cross-screen location clears old business query and history state", async () => {
        const historyCalls = [];
        viewContext.window.location.href = "https://example.invalid/tui/?screen=fixture.source&action=fixture.source-read&stock_code=old&reauth=1&secret=do-not-copy&arbitraryquery=old";
        viewContext.window.history = {
            pushState: (...args) => historyCalls.push({ method: "pushState", args }),
            replaceState: (...args) => historyCalls.push({ method: "replaceState", args }),
        };
        viewContext.__views.syncNextStepLocation(
            "fixture.target",
            "fixture.target-read",
            { replace: true, origin: "next-step" },
        );
        assert.strictEqual(historyCalls.length, 1);
        assert.strictEqual(historyCalls[0].method, "replaceState");
        const nextUrl = new URL(String(historyCalls[0].args[2]));
        assert.deepStrictEqual([...nextUrl.searchParams.entries()], [
            ["screen", "fixture.target"],
            ["action", "fixture.target-read"],
        ]);
        for (const key of ["stock_code", "reauth", "secret", "arbitraryquery"]) {
            assert.strictEqual(nextUrl.searchParams.has(key), false);
        }
        assert.strictEqual(JSON.stringify(historyCalls[0].args[0]), JSON.stringify({
            screen: "fixture.target",
            action: "fixture.target-read",
        }));
        assert.doesNotMatch(JSON.stringify(historyCalls[0].args[0]), /stock_code|reauth|secret|arbitraryquery|old/);
    });

}

await main();
