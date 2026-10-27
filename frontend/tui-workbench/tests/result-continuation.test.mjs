import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const helperPath = resolve(root, "frontend/tui-workbench/src/05-result-continuation.js");
const helperSource = await readFile(helperPath, "utf8");
const shellPath = resolve(root, "frontend/tui-workbench/src/50-shell.js");
const shellSource = await readFile(shellPath, "utf8");

function makeActions() {
    const source = {
        key: "calendar.prepare",
        screen_key: "calendar.workbench",
        method: "POST",
        risk: "write",
        session_auth_required: true,
        confirmation_required: true,
        result_continuation: {
            target_action_key: "calendar.confirm",
            field_map: { confirmation_token: "confirmation_token" },
        },
    };
    const target = {
        key: "calendar.confirm",
        screen_key: "calendar.workbench",
        method: "POST",
        risk: "write",
        session_auth_required: true,
        confirmation_required: true,
        fields: [{
            key: "confirmation_token",
            input_type: "hidden",
            value_type: "string",
            required: true,
            binding: "body",
            presentation_semantic: "api_token",
            default: "",
        }],
    };
    return [source, target];
}

function makeReadbackActions() {
    const source = {
        key: "simulated-trading.fee-correction-preview",
        screen_key: "execution.accounts",
        method: "POST",
        risk: "read",
        effect: "read",
        session_auth_required: true,
        result_continuation: {
            target_action_key: "simulated-trading.fee-correction-confirm",
            field_map: {
                account_id: "account_id",
                trade_id: "trade_id",
                confirmation_token: "confirmation_token",
            },
            reuse_source_idempotency_key: true,
            readback_action_key: "simulated-trading.fee-correction-head",
        },
    };
    const target = {
        key: "simulated-trading.fee-correction-confirm",
        screen_key: "execution.accounts",
        method: "POST",
        risk: "write",
        session_auth_required: true,
        confirmation_required: true,
        fields: [
            ...["account_id", "trade_id", "confirmation_token"].map(key => ({
                key,
                input_type: "hidden",
                value_type: "string",
                required: true,
                binding: "body",
                presentation_semantic: "api_token",
                default: "",
            })),
        ],
    };
    const readback = {
        key: "simulated-trading.fee-correction-head",
        screen_key: "execution.accounts",
        method: "GET",
        risk: "read",
        effect: "read",
        session_auth_required: true,
        confirmation_required: false,
        fields: ["account_id", "trade_id"].map(key => ({
            key,
            input_type: "hidden",
            value_type: "string",
            required: true,
            binding: "body",
            presentation_semantic: "api_token",
            default: "",
        })),
    };
    return [source, target, readback];
}

test("public readback projection validates scope without exposing endpoint", () => {
    const actions = makeReadbackActions();
    delete actions[1].endpoint;
    delete actions[2].endpoint;
    const controller = loadController();

    const incoming = controller.incomingForReadback(actions, "simulated-trading.fee-correction-head");

    assert.equal(incoming.status, "ready");
    assert.deepEqual([...incoming.readbackPathFields], ["account_id", "trade_id"]);
});

function loadController() {
    const context = { globalThis: {} };
    runInNewContext(helperSource, context);
    return context.globalThis.AgomTUIResultContinuations.createController();
}

test("authenticated read-only POST preview may seed a confirmed continuation target", () => {
    const actions = makeActions();
    actions[0].risk = "read";
    actions[0].effect = "read";
    actions[0].confirmation_required = false;
    const controller = loadController();

    assert.equal(controller.startSource(actions[0], actions).status, "ready");
});

test("broker preview carries both hidden digests while confirm reselects the same CSV", () => {
    const actions = [
        {
            key: "audit.manual-trade-import-preview",
            screen_key: "execution.audit",
            method: "POST",
            risk: "read",
            effect: "read",
            session_auth_required: true,
            result_continuation: {
                target_action_key: "audit.manual-trade-import",
                field_map: {
                    expected_fact_set_fingerprint: "expected_fact_set_fingerprint",
                    expected_balance_fingerprint: "expected_balance_fingerprint",
                },
            },
        },
        {
            key: "audit.manual-trade-import",
            screen_key: "execution.audit",
            method: "POST",
            risk: "write",
            session_auth_required: true,
            confirmation_required: true,
            fields: [
                { key: "file", input_type: "file", required: true },
                {
                    key: "expected_fact_set_fingerprint",
                    input_type: "hidden",
                    value_type: "string",
                    required: false,
                    binding: "body",
                    presentation_semantic: "api_token",
                },
                {
                    key: "expected_balance_fingerprint",
                    input_type: "hidden",
                    value_type: "string",
                    required: false,
                    binding: "body",
                    presentation_semantic: "api_token",
                },
            ],
        },
    ];
    const controller = loadController();
    const [source, target] = actions;
    controller.startSource(source, actions);
    const result = {
        outcome: "success",
        response: { status_code: 200 },
        view_model: { kind: "datagrid", rows: [] },
        debug: { raw_available: false, raw_response: null },
        continuation: {
            action_key: target.key,
            input: {
                expected_fact_set_fingerprint: "fact-set-private",
                expected_balance_fingerprint: "balance-private",
            },
            expires_at: "2099-01-01T00:00:00Z",
        },
    };

    assert.equal(controller.acceptResult(source, actions, result, 1).status, "stored");
    assert.equal(JSON.stringify(result.view_model).includes("private"), false);
    assert.equal(JSON.stringify(result.debug).includes("private"), false);
    const confirmed = controller.targetParams(
        target,
        actions,
        {
            file: "same-user-reselected-csv",
            baseline_decision: "excluded",
        },
        2,
    );
    assert.equal(confirmed.status, "ready");
    assert.equal(confirmed.params.file, "same-user-reselected-csv");
    assert.equal(confirmed.params.expected_fact_set_fingerprint, "fact-set-private");
    assert.equal(confirmed.params.expected_balance_fingerprint, "balance-private");
});

test("broker pending fact save may continue when a successful preview has no CAS context", () => {
    const actions = [
        {
            key: "audit.manual-trade-import-preview",
            screen_key: "execution.audit",
            method: "POST",
            risk: "read",
            effect: "read",
            session_auth_required: true,
            result_continuation: {
                target_action_key: "audit.manual-trade-import",
                field_map: {
                    expected_fact_set_fingerprint: "expected_fact_set_fingerprint",
                    expected_balance_fingerprint: "expected_balance_fingerprint",
                },
            },
        },
        {
            key: "audit.manual-trade-import",
            screen_key: "execution.audit",
            method: "POST",
            risk: "write",
            session_auth_required: true,
            confirmation_required: true,
            fields: [
                { key: "file", input_type: "file", required: true },
                {
                    key: "expected_fact_set_fingerprint",
                    input_type: "hidden",
                    value_type: "string",
                    required: false,
                    binding: "body",
                    presentation_semantic: "api_token",
                },
                {
                    key: "expected_balance_fingerprint",
                    input_type: "hidden",
                    value_type: "string",
                    required: false,
                    binding: "body",
                    presentation_semantic: "api_token",
                },
            ],
        },
    ];
    const controller = loadController();
    const [source, target] = actions;
    assert.equal(controller.startSource(source, actions).status, "ready");
    assert.equal(controller.acceptResult(source, actions, {
        outcome: "success",
        response: { status_code: 200 },
        view_model: { kind: "datagrid", rows: [] },
        debug: { raw_available: false, raw_response: null },
    }, 1).status, "optional_missing");
    assert.equal(controller.targetParams(target, actions, {
        file: "same-user-reselected-csv",
        baseline_decision: "pending",
    }, 2).status, "missing");
});

function sourceBetween(source, startMarker, endMarker) {
    const start = source.indexOf(startMarker);
    const end = source.indexOf(endMarker, start);
    assert.notEqual(start, -1, `missing source marker: ${startMarker}`);
    assert.notEqual(end, -1, `missing source marker: ${endMarker}`);
    return source.slice(start, end);
}

function loadActionConfirmationGlue(actions, controller) {
    const modalCancelState = sourceBetween(
        shellSource,
        "    let modalCancelHandler = null;",
        "    function modalFocusableElements()",
    );
    const confirmation = sourceBetween(
        shellSource,
        "    function showActionConfirmation(",
        "    function showPasswordChallenge(",
    );
    const closeModal = sourceBetween(
        shellSource,
        "    function closeModal(",
        "    function openSelectedRowDetail(",
    );
    const listeners = new Map();
    const modalBody = {
        innerHTML: "",
        querySelector(selector) {
            const button = {
                addEventListener(eventName, callback) {
                    listeners.set(`${selector}:${eventName}`, callback);
                },
                focus() {},
            };
            return button;
        },
    };
    const state = {
        screen: { actions },
        modalReturnFocus: null,
    };
    const els = {
        modal: {
            hidden: true,
            classList: { add() {}, remove() {} },
            dataset: {},
        },
        modalTitle: { textContent: "" },
        modalBody,
        modalClose: { focus() {} },
    };
    const runCalls = [];
    const statusCalls = [];
    const context = {
        Date,
        HTMLElement: class HTMLElement {},
        document: { activeElement: null, contains: () => false },
        state,
        els,
        resultContinuations: controller,
        clearContinuationSourceTriggerGuard: () => false,
        escapeHtml: value => String(value ?? ""),
        runAction: (...args) => runCalls.push(args),
        setStatus: value => statusCalls.push(value),
    };
    runInNewContext(
        `${modalCancelState}\n${confirmation}\n${closeModal}\n` +
            "globalThis.glue = { showActionConfirmation, closeModal };",
        context,
    );
    return {
        glue: context.glue,
        els,
        listeners,
        runCalls,
        statusCalls,
    };
}

function loadPasswordChallengeGlue(actions, controller) {
    const challenge = sourceBetween(
        shellSource,
        "    function showPasswordChallenge(",
        "    function closeModal(",
    );
    const listeners = new Map();
    let onCancel = null;
    const passwordInput = { value: "", focus() {} };
    const cancelButton = {
        addEventListener(eventName, callback) {
            listeners.set(`cancel:${eventName}`, callback);
        },
    };
    const form = {
        addEventListener(eventName, callback) {
            listeners.set(`form:${eventName}`, callback);
        },
        querySelector(selector) {
            return selector === "input" || selector === "[name='password']" ? passwordInput : null;
        },
    };
    const modalBody = {
        querySelector(selector) {
            if (selector === "[data-password-challenge-form]") return form;
            if (selector === "[data-cancel-action]") return cancelButton;
            return null;
        },
    };
    const runCalls = [];
    const statusCalls = [];
    const context = {
        Date,
        state: { screen: { actions } },
        els: { modalBody },
        resultContinuations: controller,
        clearContinuationSourceTriggerGuard: () => false,
        escapeHtml: value => String(value ?? ""),
        showModal(_title, _markup, options = {}) { onCancel = options.onCancel || null; },
        closeModal(options = {}) {
            const callback = onCancel;
            onCancel = null;
            if (options.cancel !== false && callback) callback();
        },
        runAction: (...args) => runCalls.push(args),
        setStatus: value => statusCalls.push(value),
    };
    runInNewContext(
        `${challenge}\nglobalThis.glue = { showPasswordChallenge };`,
        context,
    );
    return { glue: context.glue, listeners, passwordInput, runCalls, statusCalls };
}

function loadCloseTopLayer(shellContext) {
    const closeTopLayer = sourceBetween(
        shellSource,
        "    function closeTopLayer()",
        "    function keyboardCommandForEvent(",
    );
    runInNewContext(
        `${closeTopLayer}\nglobalThis.closeTopLayer = closeTopLayer;`,
        shellContext,
    );
    return shellContext.closeTopLayer;
}

function successfulResult(token, expiresAt = "2099-01-01T00:00:00Z") {
    return {
        outcome: "success",
        response: { status_code: 200 },
        view_model: { kind: "detail", status: "已准备" },
        debug: { raw_available: false, raw_response: null },
        continuation: {
            action_key: "calendar.confirm",
            input: { confirmation_token: token },
            expires_at: expiresAt,
        },
    };
}

test("same-tab handoff keeps token in memory and cancellation discards the pending confirmation", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    assert.equal(controller.startSource(source, actions).status, "ready");
    assert.equal(controller.acceptResult(source, actions, successfulResult("synthetic-only"), 1).status, "stored");

    const beforeConfirm = controller.targetParams(target, actions, { note: "visible input" }, 2);
    assert.equal(beforeConfirm.status, "ready");
    assert.equal(beforeConfirm.params.confirmation_token, "synthetic-only");
    assert.equal(beforeConfirm.params.note, "visible input");

    const cancelled = controller.cancelTargetConfirmation(target, actions, beforeConfirm.params, 3);
    assert.equal(cancelled.status, "cancelled");
    const confirmed = controller.consumeTarget(target, actions, {}, 4);
    assert.equal(confirmed.status, "missing");
    assert.equal(controller.targetParams(target, actions, {}, 5).status, "missing");
});

test("cancelling the actual confirmation modal discards only its matching handoff", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    controller.acceptResult(source, actions, successfulResult("synthetic-only"), 1);
    const modal = loadActionConfirmationGlue(actions, controller);

    modal.glue.showActionConfirmation(
        { confirmation: { message: "确认发布" } },
        target.key,
        { confirmation_token: "synthetic-only" },
    );
    modal.listeners.get("[data-cancel-action]:click")();

    assert.equal(controller.targetParams(target, actions, {}, 2).status, "missing");
    assert.deepEqual(modal.statusCalls, ["已取消"]);
    assert.equal(modal.els.modal.hidden, true);
});

test("closing the source confirmation modal invalidates its late response", () => {
    const controller = loadController();
    const actions = makeActions();
    const source = actions[0];
    const started = controller.startSource(source, actions);
    const modal = loadActionConfirmationGlue(actions, controller);

    modal.glue.showActionConfirmation(
        { confirmation: { message: "获取预览" } },
        source.key,
        {},
    );
    modal.glue.closeModal();

    assert.equal(controller.acceptResult(
        source,
        actions,
        successfulResult("late-preview"),
        2,
        started.requestToken,
    ).status, "stale");
    assert.equal(controller.targetParams(actions[1], actions, {}, 3).status, "missing");
});

test("closing an old source modal does not cancel a newer source request", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    const oldRequest = controller.startSource(source, actions);
    const modal = loadActionConfirmationGlue(actions, controller);

    modal.glue.showActionConfirmation(
        { confirmation: { message: "获取旧预览" } },
        source.key,
        {},
    );
    const newRequest = controller.startSource(source, actions);
    modal.glue.closeModal();

    assert.equal(controller.acceptResult(
        source,
        actions,
        successfulResult("new-preview"),
        2,
        newRequest.requestToken,
    ).status, "stored");
    assert.equal(controller.acceptResult(
        source,
        actions,
        successfulResult("late-old-preview"),
        3,
        oldRequest.requestToken,
    ).status, "stale");
    assert.equal(controller.targetParams(target, actions, {}, 4).params.confirmation_token, "new-preview");
});

test("cancelling an ordinary confirmation modal leaves unrelated handoff state unchanged", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    const ordinary = {
        key: "calendar.refresh",
        screen_key: "calendar.workbench",
        method: "POST",
        risk: "write",
        session_auth_required: true,
        confirmation_required: true,
    };
    const screenActions = [...actions, ordinary];
    controller.acceptResult(source, screenActions, successfulResult("keep-preview"), 1);
    const modal = loadActionConfirmationGlue(screenActions, controller);

    modal.glue.showActionConfirmation(
        { confirmation: { message: "确认普通操作" } },
        ordinary.key,
        {},
    );
    modal.listeners.get("[data-cancel-action]:click")();

    assert.equal(controller.targetParams(target, screenActions, {}, 2).params.confirmation_token, "keep-preview");
});

test("Escape route closes the actual confirmation modal through cancellation cleanup", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    controller.acceptResult(source, actions, successfulResult("escape-preview"), 1);
    const modal = loadActionConfirmationGlue(actions, controller);
    modal.glue.showActionConfirmation(
        { confirmation: { message: "确认发布" } },
        target.key,
        { confirmation_token: "escape-preview" },
    );
    const shellContext = {
        els: {
            modal: { hidden: false },
            filterBar: { hidden: true },
            menuPopover: { hidden: true },
            rawDrawer: { hidden: true },
        },
        closeModal: modal.glue.closeModal,
        hideFilterBar() {},
        closeMenu() {},
        toggleRawDrawer() {},
    };
    const closeTopLayer = loadCloseTopLayer(shellContext);

    assert.equal(closeTopLayer(), true);
    assert.equal(controller.targetParams(target, actions, {}, 2).status, "missing");
    assert.match(shellSource, /els\.modalClose\.addEventListener\("click", closeModal\)/);
});

test("confirming the actual modal keeps the handoff until the target submission consumes it", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    controller.acceptResult(source, actions, successfulResult("synthetic-only"), 1);
    const modal = loadActionConfirmationGlue(actions, controller);

    modal.glue.showActionConfirmation(
        { confirmation: { message: "确认发布" } },
        target.key,
        { confirmation_token: "synthetic-only" },
    );
    modal.listeners.get("[data-confirm-action]:click")();

    assert.equal(modal.runCalls.length, 1);
    assert.equal(modal.runCalls[0][2].confirmed, true);
    assert.equal(controller.targetParams(target, actions, {}, 2).status, "ready");
    assert.equal(controller.consumeTarget(target, actions, {}, 3).params.confirmation_token, "synthetic-only");
});

test("an old modal cannot discard a newer preview for the same target", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    controller.acceptResult(source, actions, successfulResult("old-preview"), 1);
    const oldParams = controller.targetParams(target, actions, {}, 2).params;
    controller.startSource(source, actions);
    controller.acceptResult(source, actions, successfulResult("new-preview"), 3);

    assert.equal(controller.cancelTargetConfirmation(target, actions, oldParams, 4).status, "stale");
    assert.equal(controller.targetParams(target, actions, {}, 5).params.confirmation_token, "new-preview");
});

test("new preview invalidates an earlier handoff and a failed result cannot restore it", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    controller.acceptResult(source, actions, successfulResult("old-value"), 1);
    controller.startSource(source, actions);
    const failed = controller.acceptResult(source, actions, {
        outcome: "failed",
        response: { status_code: 502 },
    }, 2);
    assert.equal(failed.status, "none");
    assert.equal(controller.targetParams(target, actions, {}, 3).status, "missing");
});

test("out-of-order source responses and cancelled pending previews cannot replace a newer handoff", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    const first = controller.startSource(source, actions);
    const second = controller.startSource(source, actions);

    assert.equal(controller.acceptResult(
        source,
        actions,
        successfulResult("new-preview"),
        2,
        second.requestToken,
    ).status, "stored");
    assert.equal(controller.acceptResult(
        source,
        actions,
        successfulResult("late-old-preview"),
        3,
        first.requestToken,
    ).status, "stale");
    assert.equal(controller.targetParams(target, actions, {}, 4).params.confirmation_token, "new-preview");

    const cancelled = controller.startSource(source, actions);
    assert.equal(controller.cancelSource(source, actions, cancelled.requestToken), true);
    assert.equal(controller.acceptResult(
        source,
        actions,
        successfulResult("cancelled-preview"),
        5,
        cancelled.requestToken,
    ).status, "stale");
    assert.equal(controller.targetParams(target, actions, {}, 6).status, "missing");
});

test("expired or malformed owner continuation fails closed and is not retained", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    assert.equal(controller.acceptResult(source, actions, successfulResult("expired", "1970-01-01T00:00:00Z"), 2).status, "expired");
    assert.equal(controller.acceptResult(source, actions, successfulResult("bad", "2099-01-01T00:00:00+08:00"), 2).status, "invalid");
    const nonString = successfulResult(42);
    assert.equal(controller.acceptResult(source, actions, nonString, 2).status, "invalid");
    const wrong = successfulResult("wrong-action");
    wrong.continuation.action_key = "calendar.other";
    assert.equal(controller.acceptResult(source, actions, wrong, 2).status, "invalid");
    assert.equal(controller.targetParams(target, actions, {}, 3).status, "missing");
});

test("continuation values duplicated into render or debug data are rejected", () => {
    const controller = loadController();
    const actions = makeActions();
    const source = actions[0];
    const result = successfulResult("synthetic-only");
    result.view_model.summary = "synthetic-only";
    assert.equal(controller.acceptResult(source, actions, result, 1).status, "leaked");
    assert.equal(controller.acceptResult(source, actions, successfulResult("safe"), 1).status, "stored");
});

test("readback scope may appear in view data but the confirmation token still may not", () => {
    const actions = makeReadbackActions();
    const [source, target] = actions;
    const makeResult = token => {
        const result = successfulResult(token);
        result.continuation.action_key = target.key;
        result.continuation.input = {
            account_id: "41",
            trade_id: "600000",
            confirmation_token: token,
        };
        result.view_model = { kind: "detail", asset_code: "600000" };
        return result;
    };

    const controller = loadController();
    const sourceRequest = controller.startSource(source, actions);
    assert.equal(controller.acceptResult(
        source,
        actions,
        makeResult("private-token"),
        1,
        sourceRequest.requestToken,
        "source-key",
    ).status, "stored");

    const leakedController = loadController();
    const leakedSourceRequest = leakedController.startSource(source, actions);
    const leakedResult = makeResult("private-token");
    leakedResult.view_model.message = "private-token";
    assert.equal(leakedController.acceptResult(
        source,
        actions,
        leakedResult,
        1,
        leakedSourceRequest.requestToken,
        "source-key",
    ).status, "leaked");
});

test("handoff state is isolated by controller and never enters safe UI parameters", () => {
    const firstTab = loadController();
    const secondTab = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    firstTab.acceptResult(source, actions, successfulResult("tab-one"), 1);
    assert.equal(secondTab.targetParams(target, actions, {}, 2).status, "missing");
    assert.equal(JSON.stringify(firstTab.safeUiParams(
        target,
        { confirmation_token: "tab-one", note: "ok" },
        actions,
    )), JSON.stringify({ note: "ok" }));
    firstTab.clearScreen(target.screen_key);
    assert.equal(firstTab.targetParams(target, actions, {}, 2).status, "missing");
});

test("confirmed continuation retry retains exact private request identity without retaining reauth", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    controller.acceptResult(source, actions, successfulResult("private-token"), 1);
    const ready = controller.consumeTarget(target, actions, { note: "release" }, 2);
    assert.equal(ready.status, "ready");
    const confirmation = {
        confirmed: true,
        confirmed_at: "2026-10-17T02:00:00.000Z",
        message: "确认发布",
    };
    assert.equal(controller.rememberTargetRequest(target, actions, {
        params: ready.params,
        idempotencyKey: "same-key",
        confirmed: true,
        confirmation,
        expiresAt: ready.expiresAt,
        reauth: { credential: "password-must-not-be-retained" },
    }, 3).status, "stored");

    const retry = controller.targetRequestForRetry(target, actions, 4);
    assert.equal(retry.status, "ready");
    assert.equal(JSON.stringify(retry.params), JSON.stringify({ note: "release", confirmation_token: "private-token" }));
    assert.equal(retry.idempotencyKey, "same-key");
    assert.equal(retry.confirmed, true);
    assert.equal(JSON.stringify(retry.confirmation), JSON.stringify(confirmation));
    assert.equal(Object.hasOwn(retry, "reauth"), false);
    retry.params.confirmation_token = "mutated-copy";
    assert.equal(controller.targetRequestForRetry(target, actions, 5).params.confirmation_token, "private-token");
    assert.equal(JSON.stringify(controller.safeUiParams(
        target,
        retry.params,
        actions,
    )), JSON.stringify({ note: "release" }));
});

test("retry request context expires and is cleared by cancellation, a new preview, and screen exit", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    const expiresAt = "1970-01-01T00:00:10Z";
    controller.acceptResult(source, actions, successfulResult("expiring-token", expiresAt), 1);
    const handoff = controller.targetParams(target, actions, {}, 2);
    assert.equal(controller.rememberTargetRequest(target, actions, {
        params: handoff.params,
        idempotencyKey: "retry-key",
        confirmed: false,
        confirmation: null,
        expiresAt,
    }, 3).status, "stored");
    assert.equal(controller.targetRequestForRetry(target, actions, 10_000).status, "expired");

    controller.acceptResult(source, actions, successfulResult("cancel-token"), 1);
    const cancelParams = controller.targetParams(target, actions, {}, 2).params;
    assert.equal(controller.rememberTargetRequest(target, actions, {
        params: cancelParams,
        idempotencyKey: "cancel-key",
        confirmed: false,
        confirmation: null,
        expiresAt: "2099-01-01T00:00:00Z",
    }, 3).status, "stored");
    assert.equal(controller.cancelTargetConfirmation(target, actions, cancelParams, 4).status, "cancelled");
    assert.equal(controller.targetRequestForRetry(target, actions, 5).status, "missing");

    controller.acceptResult(source, actions, successfulResult("old-token"), 6);
    const oldParams = controller.targetParams(target, actions, {}, 7).params;
    controller.rememberTargetRequest(target, actions, {
        params: oldParams,
        idempotencyKey: "old-key",
        confirmed: false,
        confirmation: null,
        expiresAt: "2099-01-01T00:00:00Z",
    }, 8);
    controller.startSource(source, actions);
    assert.equal(controller.targetRequestForRetry(target, actions, 9).status, "missing");

    controller.acceptResult(source, actions, successfulResult("screen-token"), 10);
    const screenParams = controller.targetParams(target, actions, {}, 11).params;
    controller.rememberTargetRequest(target, actions, {
        params: screenParams,
        idempotencyKey: "screen-key",
        confirmed: false,
        confirmation: null,
        expiresAt: "2099-01-01T00:00:00Z",
    }, 12);
    controller.clearScreen(target.screen_key);
    assert.equal(controller.targetRequestForRetry(target, actions, 13).status, "missing");
});

test("same-screen unrelated action clears an unconsumed continuation", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    const unrelated = {
        key: "calendar.scope",
        screen_key: source.screen_key,
        method: "GET",
        risk: "read",
    };
    actions.push(unrelated);

    controller.startSource(source, actions);
    assert.equal(controller.acceptResult(source, actions, successfulResult("pending-token"), 1).status, "stored");

    controller.retainActionContext(unrelated, actions);

    assert.equal(controller.targetParams(target, actions, {}, 2).status, "missing");
});

test("same-screen unrelated action clears a continuation retry context", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;
    const unrelated = {
        key: "calendar.scope",
        screen_key: source.screen_key,
        method: "GET",
        risk: "read",
    };
    actions.push(unrelated);

    controller.startSource(source, actions);
    assert.equal(controller.acceptResult(source, actions, successfulResult("retry-token"), 1).status, "stored");
    const consumed = controller.consumeTarget(target, actions, {}, 2);
    assert.equal(consumed.status, "ready");
    assert.equal(controller.rememberTargetRequest(target, actions, {
        params: consumed.params,
        idempotencyKey: "same-retry-key",
        confirmed: true,
        confirmation: {
            confirmed: true,
            confirmed_at: "2026-10-17T02:00:00Z",
            message: "确认发布",
        },
        expiresAt: consumed.expiresAt,
    }, 3).status, "stored");

    controller.retainActionContext(unrelated, actions);

    assert.equal(controller.targetRequestForRetry(target, actions, 4).status, "missing");
});

test("same-key continuation survives the confirmation prompt and permits only same-key retries", () => {
    const controller = loadController();
    const actions = makeReadbackActions();
    const [source, target] = actions;
    const sourceRequest = controller.startSource(source, actions);
    const result = successfulResult("signed-owner-token");
    result.continuation.action_key = target.key;
    result.continuation.input = {
        account_id: "41",
        trade_id: "73",
        confirmation_token: "signed-owner-token",
    };
    assert.equal(controller.acceptResult(
        source,
        actions,
        result,
        1,
        sourceRequest.requestToken,
        "original-source-key",
    ).status, "stored");

    const firstHandoff = controller.targetParams(target, actions, {}, 2);
    assert.equal(controller.rememberTargetRequest(target, actions, {
        params: firstHandoff.params,
        idempotencyKey: firstHandoff.idempotencyKey,
        confirmed: false,
        confirmation: null,
        expiresAt: firstHandoff.expiresAt,
    }, 3).status, "stored");

    // This models the first POST returning confirmation_required. The signed
    // continuation must remain available for the explicit confirmation POST.
    assert.equal(controller.clearTargetRequest(target, { preservePending: true }), true);
    const confirmationHandoff = controller.consumeTarget(target, actions, {}, 4);
    assert.equal(confirmationHandoff.status, "ready");
    assert.equal(confirmationHandoff.idempotencyKey, "original-source-key");

    const confirmation = {
        confirmed: true,
        confirmed_at: "2026-10-27T00:00:00Z",
        message: "确认更正",
    };
    const confirmedRequest = {
        params: confirmationHandoff.params,
        idempotencyKey: confirmationHandoff.idempotencyKey,
        confirmed: true,
        confirmation,
        expiresAt: confirmationHandoff.expiresAt,
    };
    assert.equal(controller.rememberTargetRequest(target, actions, confirmedRequest, 5).status, "stored");

    const retry = controller.targetRequestForRetry(target, actions, 6);
    assert.equal(retry.status, "ready");
    assert.equal(retry.idempotencyKey, "original-source-key");
    assert.equal(controller.rememberTargetRequest(target, actions, {
        ...confirmedRequest,
        params: retry.params,
        idempotencyKey: retry.idempotencyKey,
    }, 7).status, "stored");
    assert.equal(controller.rememberTargetRequest(target, actions, {
        ...confirmedRequest,
        params: retry.params,
        idempotencyKey: "different-key",
    }, 8).status, "invalid");
});

test("action-context retention preserves the active pair and rejects a superseded source result", () => {
    const controller = loadController();
    const actions = makeActions();
    const [source, target] = actions;

    assert.equal(controller.retainActionContext(source, actions), true);
    const first = controller.startSource(source, actions);
    assert.equal(controller.retainActionContext(source, actions), true);
    const current = controller.startSource(source, actions);
    assert.equal(controller.acceptResult(
        source,
        actions,
        successfulResult("stale-token"),
        1,
        first.requestToken,
    ).status, "stale");
    assert.equal(controller.acceptResult(
        source,
        actions,
        successfulResult("current-token"),
        2,
        current.requestToken,
    ).status, "stored");
    assert.equal(controller.targetParams(target, actions, {}, 3).params.confirmation_token, "current-token");
});

test("opted-in continuation reuses the source key and keeps only exact-key readback after expiry", () => {
    const controller = loadController();
    const actions = makeReadbackActions();
    const [source, target, readback] = actions;
    const sourceRequest = controller.startSource(source, actions);
    const result = successfulResult("owner-token", "1970-01-01T00:00:10Z");
    result.continuation.action_key = target.key;
    result.continuation.input = {
        account_id: "41",
        trade_id: "73",
        confirmation_token: "signed-owner-token",
    };
    assert.equal(controller.acceptResult(
        source,
        actions,
        result,
        1,
        sourceRequest.requestToken,
        "tui-original-key",
    ).status, "stored");

    const handoff = controller.targetParams(target, actions, {}, 2);
    assert.equal(handoff.status, "ready");
    assert.equal(handoff.idempotencyKey, "tui-original-key");
    assert.deepEqual(JSON.parse(JSON.stringify(handoff.params)), {
        account_id: "41",
        trade_id: "73",
        confirmation_token: "signed-owner-token",
    });
    assert.equal(controller.rememberTargetRequest(target, actions, {
        params: handoff.params,
        idempotencyKey: handoff.idempotencyKey,
        confirmed: true,
        confirmation: {
            confirmed: true,
            confirmed_at: "2026-10-27T00:00:00Z",
            message: "确认更正",
        },
        expiresAt: handoff.expiresAt,
    }, 3).status, "stored");
    assert.equal(controller.markTargetUnknown(target, actions), true);

    const unknownSubmit = controller.targetRequestForRetry(target, actions, 20_000);
    assert.equal(unknownSubmit.status, "unknown");
    assert.equal(controller.targetParams(target, actions, {}, 20_000).status, "missing");

    const recovery = controller.readbackRequestForAction(readback, actions, 20_000);
    assert.equal(recovery.status, "ready");
    assert.equal(recovery.idempotencyKey, "tui-original-key");
    assert.deepEqual(JSON.parse(JSON.stringify(recovery.params)), {
        account_id: "41",
        trade_id: "73",
    });
    assert.equal(Object.hasOwn(recovery.params, "confirmation_token"), false);
});

test("unresolved readback cannot be discarded and always blocks a new source", () => {
    const controller = loadController();
    const actions = makeReadbackActions();
    const [source, target, readback] = actions;
    const sourceRequest = controller.startSource(source, actions);
    const result = successfulResult("pending-token");
    result.continuation.action_key = target.key;
    result.continuation.input = {
        account_id: "41",
        trade_id: "73",
        confirmation_token: "apply-token",
    };
    controller.acceptResult(source, actions, result, 1, sourceRequest.requestToken, "source-key");
    const handoff = controller.targetParams(target, actions, {}, 2);
    controller.rememberTargetRequest(target, actions, {
        params: handoff.params,
        idempotencyKey: handoff.idempotencyKey,
        confirmed: true,
        confirmation: {
            confirmed: true,
            confirmed_at: "2026-10-27T00:00:00Z",
            message: "确认更正",
        },
        expiresAt: handoff.expiresAt,
    }, 3);
    assert.equal(controller.markTargetRequestDispatched(target, actions, "source-key"), true);
    controller.markTargetUnknown(target, actions);

    const unrelated = { key: "account.summary", screen_key: source.screen_key, method: "GET" };
    const screenActions = [...actions, unrelated];
    controller.retainActionContext(unrelated, screenActions);
    assert.equal(controller.readbackRequestForAction(readback, screenActions, 4).status, "ready");
    controller.retainActionContext(source, screenActions);
    assert.equal(controller.startSource(source, actions).status, "readback_pending");
    assert.equal(controller.readbackRequestForAction(readback, actions, 4).status, "ready");
    assert.equal(controller.discardReadback, undefined);
    controller.clearScreen(source.screen_key);
    assert.equal(controller.startSource(source, actions).status, "readback_pending");
    assert.equal(controller.readbackRequestForAction(readback, actions, 5).status, "ready");
});

test("screen exit retains only unresolved readback key and path scope", () => {
    const controller = loadController();
    const actions = makeReadbackActions();
    const [source, target, readback] = actions;
    const sourceRequest = controller.startSource(source, actions);
    const result = successfulResult("pending-token");
    result.continuation.action_key = target.key;
    result.continuation.input = {
        account_id: "41",
        trade_id: "73",
        confirmation_token: "apply-token",
    };
    controller.acceptResult(source, actions, result, 1, sourceRequest.requestToken, "source-key");
    const handoff = controller.targetParams(target, actions, {}, 2);
    controller.rememberTargetRequest(target, actions, {
        params: handoff.params,
        idempotencyKey: handoff.idempotencyKey,
        confirmed: true,
        confirmation: {
            confirmed: true,
            confirmed_at: "2026-10-27T00:00:00Z",
            message: "确认更正",
        },
        expiresAt: handoff.expiresAt,
    }, 3);
    assert.equal(controller.markTargetRequestDispatched(target, actions, "source-key"), true);
    controller.clearScreen(source.screen_key);
    const recovery = controller.readbackRequestForAction(readback, actions, 4);
    assert.equal(recovery.status, "ready");
    assert.equal(recovery.idempotencyKey, "source-key");
    assert.deepEqual(JSON.parse(JSON.stringify(recovery.params)), {
        account_id: "41",
        trade_id: "73",
    });
    assert.equal(Object.hasOwn(recovery.params, "confirmation_token"), false);
    assert.equal(controller.startSource(source, actions).status, "readback_pending");
    assert.equal(controller.markTargetRequestResponseReceived(target, actions, "source-key"), true);
    assert.equal(controller.readbackRequestForAction(readback, actions, 5).status, "ready");
});

test("a new source click marks an in-flight confirmed request unknown before abort", () => {
    const controller = loadController();
    const actions = makeReadbackActions();
    const [source, target, readback] = actions;
    const sourceRequest = controller.startSource(source, actions);
    const result = successfulResult("pending-token");
    result.continuation.action_key = target.key;
    result.continuation.input = {
        account_id: "41",
        trade_id: "73",
        confirmation_token: "apply-token",
    };
    controller.acceptResult(source, actions, result, 1, sourceRequest.requestToken, "source-key");
    const handoff = controller.targetParams(target, actions, {}, 2);
    controller.rememberTargetRequest(target, actions, {
        params: handoff.params,
        idempotencyKey: handoff.idempotencyKey,
        confirmed: true,
        confirmation: {
            confirmed: true,
            confirmed_at: "2026-10-27T00:00:00Z",
            message: "确认更正",
        },
        expiresAt: handoff.expiresAt,
    }, 3);
    assert.equal(controller.markTargetRequestDispatched(target, actions, "source-key"), true);

    assert.equal(controller.startSource(source, actions).status, "readback_pending");
    const recovery = controller.readbackRequestForAction(readback, actions, 4);
    assert.equal(recovery.status, "ready");
    assert.equal(recovery.idempotencyKey, "source-key");
    assert.deepEqual(JSON.parse(JSON.stringify(recovery.params)), {
        account_id: "41",
        trade_id: "73",
    });
    assert.equal(Object.hasOwn(recovery.params, "confirmation_token"), false);
});

test("late response for an old idempotency key cannot settle a newer dispatched target", () => {
    const controller = loadController();
    const actions = makeReadbackActions();
    const [source, target, readback] = actions;
    const prepareRequest = (idempotencyKey, tradeId, token, nowMs) => {
        const sourceRequest = controller.startSource(source, actions);
        assert.equal(sourceRequest.status, "ready");
        const result = successfulResult(token);
        result.continuation.action_key = target.key;
        result.continuation.input = {
            account_id: "41",
            trade_id: tradeId,
            confirmation_token: token,
        };
        assert.equal(controller.acceptResult(
            source,
            actions,
            result,
            nowMs,
            sourceRequest.requestToken,
            idempotencyKey,
        ).status, "stored");
        const handoff = controller.targetParams(target, actions, {}, nowMs + 1);
        assert.equal(controller.rememberTargetRequest(target, actions, {
            params: handoff.params,
            idempotencyKey,
            confirmed: true,
            confirmation: {
                confirmed: true,
                confirmed_at: "2026-10-27T00:00:00Z",
                message: "确认更正",
            },
            expiresAt: handoff.expiresAt,
        }, nowMs + 2).status, "stored");
        assert.equal(controller.markTargetRequestDispatched(
            target,
            actions,
            idempotencyKey,
        ), true);
    };

    prepareRequest("source-key-A", "73", "token-A", 1);
    controller.clearScreen(source.screen_key);
    assert.equal(controller.resolveReadback(readback, actions, {
        outcome: "success",
        response: { status_code: 200 },
    }, "source-key-A"), true);

    prepareRequest("source-key-B", "74", "token-B", 10);
    assert.equal(controller.markTargetRequestResponseReceived(
        target,
        actions,
        "source-key-A",
    ), false);
    controller.clearScreen(source.screen_key);

    const recovery = controller.readbackRequestForAction(readback, actions, 20);
    assert.equal(recovery.status, "ready");
    assert.equal(recovery.idempotencyKey, "source-key-B");
    assert.deepEqual(JSON.parse(JSON.stringify(recovery.params)), {
        account_id: "41",
        trade_id: "74",
    });
});

test("unconfirmed target request failures never become unknown readback state", () => {
    const controller = loadController();
    const actions = makeReadbackActions();
    const [source, target, readback] = actions;
    const sourceRequest = controller.startSource(source, actions);
    const result = successfulResult("unconfirmed-token");
    result.continuation.action_key = target.key;
    result.continuation.input = {
        account_id: "41",
        trade_id: "73",
        confirmation_token: "unconfirmed-token",
    };
    controller.acceptResult(source, actions, result, 1, sourceRequest.requestToken, "source-key");
    const handoff = controller.targetParams(target, actions, {}, 2);
    controller.rememberTargetRequest(target, actions, {
        params: handoff.params,
        idempotencyKey: handoff.idempotencyKey,
        confirmed: false,
        confirmation: null,
        expiresAt: handoff.expiresAt,
    }, 3);
    assert.equal(controller.markTargetRequestDispatched(target, actions, "source-key"), true);
    assert.equal(controller.markTargetUnknown(target, actions), false);
    const retry = controller.targetRequestForRetry(target, actions, 4);
    assert.equal(retry.status, "ready");
    assert.equal(retry.confirmed, false);
    assert.equal(controller.readbackRequestForAction(readback, actions, 5).status, "missing");
});

test("partial readback preserves unknown state; only an explicit successful receipt resolves it", () => {
    const controller = loadController();
    const actions = makeReadbackActions();
    const [source, target, readback] = actions;
    const sourceRequest = controller.startSource(source, actions);
    const result = successfulResult("pending-token");
    result.continuation.action_key = target.key;
    result.continuation.input = {
        account_id: "41",
        trade_id: "73",
        confirmation_token: "apply-token",
    };
    controller.acceptResult(source, actions, result, 1, sourceRequest.requestToken, "source-key");
    const handoff = controller.targetParams(target, actions, {}, 2);
    controller.rememberTargetRequest(target, actions, {
        params: handoff.params,
        idempotencyKey: handoff.idempotencyKey,
        confirmed: true,
        confirmation: {
            confirmed: true,
            confirmed_at: "2026-10-27T00:00:00Z",
            message: "确认更正",
        },
        expiresAt: handoff.expiresAt,
    }, 3);
    controller.markTargetUnknown(target, actions);

    const readbackRequest = controller.readbackRequestForAction(readback, actions, 20_000);
    assert.deepEqual(JSON.parse(JSON.stringify(readbackRequest.params)), {
        account_id: "41",
        trade_id: "73",
    });
    assert.equal(readbackRequest.idempotencyKey, "source-key");
    assert.equal(controller.resolveReadback(readback, actions, {
        outcome: "partial",
        response: { status_code: 200 },
    }, "source-key"), false);
    assert.equal(controller.readbackRequestForAction(readback, actions, 20_001).status, "ready");
    assert.equal(controller.resolveReadback(readback, actions, {
        outcome: "success",
        response: { status_code: 200 },
    }, "wrong-key"), false);
    assert.equal(controller.readbackRequestForAction(readback, actions, 20_002).status, "ready");
    assert.equal(controller.resolveReadback(readback, actions, {
        outcome: "success",
        response: { status_code: 200 },
    }, "source-key"), true);
    assert.equal(controller.readbackRequestForAction(readback, actions, 20_002).status, "missing");
});

test("readback metadata fails closed for a write action or different path scope", () => {
    const controller = loadController();
    const actions = makeReadbackActions();
    const [source, _target, readback] = actions;
    assert.equal(controller.incomingForReadback(actions, readback.key).status, "ready");

    readback.method = "POST";
    assert.equal(controller.incomingForReadback(actions, readback.key).status, "invalid");

    readback.method = "GET";
    readback.fields = readback.fields.map(field => field.key === "account_id"
        ? { ...field, key: "other_account_id" }
        : field);
    assert.equal(controller.startSource(source, actions).status, "invalid");
});

test("password challenge submission preserves retry context but cancellation discards it", () => {
    const actions = makeActions();
    const [source, target] = actions;
    const controller = loadController();
    controller.acceptResult(source, actions, successfulResult("reauth-token"), 1);
    const handoff = controller.consumeTarget(target, actions, {}, 2);
    const confirmation = {
        confirmed: true,
        confirmed_at: "2026-10-17T02:00:00.000Z",
        message: "确认发布",
    };
    controller.rememberTargetRequest(target, actions, {
        params: handoff.params,
        idempotencyKey: "reauth-key",
        confirmed: true,
        confirmation,
        expiresAt: handoff.expiresAt,
    }, 3);
    const submitted = loadPasswordChallengeGlue(actions, controller);
    submitted.glue.showPasswordChallenge(
        { password_challenge: { challenge_id: "challenge-1" } },
        target.key,
        handoff.params,
        { continuationRetry: true, confirmed: true, idempotencyKey: "reauth-key", confirmation },
    );
    submitted.passwordInput.value = "synthetic-password";
    let prevented = false;
    submitted.listeners.get("form:submit")({ preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
    assert.equal(submitted.runCalls.length, 1);
    assert.equal(submitted.runCalls[0][2].reauth.credential, "synthetic-password");
    assert.equal(controller.targetRequestForRetry(target, actions, 4).status, "ready");

    const cancelled = loadPasswordChallengeGlue(actions, controller);
    cancelled.glue.showPasswordChallenge(
        { password_challenge: { challenge_id: "challenge-2" } },
        target.key,
        handoff.params,
        { continuationRetry: true, confirmed: true, idempotencyKey: "reauth-key", confirmation },
    );
    cancelled.listeners.get("cancel:click")();
    assert.deepEqual(cancelled.statusCalls, ["已取消"]);
    assert.equal(controller.targetRequestForRetry(target, actions, 5).status, "missing");
});
