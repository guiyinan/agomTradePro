import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { chromium } from "playwright";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

test("mutation identity survives confirmation and network retry but changes for a new submission", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.grid&action=test.edit&code=identity-code",
        { waitForInitialRows: false, catalog: experienceCatalog },
    );
    const keys = [];
    let failedOnce = false;
    try {
        await page.route('**/actions/test.edit/run/', async route => {
            keys.push(route.request().headers()['idempotency-key']);
            if (route.request().postDataJSON().confirmed && !failedOnce) {
                failedOnce = true;
                await route.abort('failed');
                return;
            }
            await route.fallback();
        });
        const form = page.locator('form[data-action-ui-key="test.edit"]');
        await form.locator('.tui-action-submit').click();
        await page.locator('[data-confirm-action]').waitFor();
        await page.locator('[data-experience-mode="professional"]').evaluate(button => button.click());
        assert.equal(await page.locator('[data-confirm-action]').isVisible(), true);
        assert.equal(keys.length, 1);
        await page.locator('[data-confirm-action]').click();
        await page.locator('[data-action-submission-retry]').waitFor();
        await page.locator('[data-experience-mode="task"]').click();
        assert.equal(await form.locator('[name="code"]').inputValue(), 'identity-code');
        assert.equal(keys.length, 2);
        await page.locator('[data-action-submission-retry]').click();
        await page.waitForFunction(() => document.querySelector('[data-workbench-status]')?.textContent === '操作完成');
        assert.equal(keys.length, 3);
        assert.ok(keys[0]);
        assert.equal(new Set(keys).size, 1);
        await form.locator('[name="code"]').fill('next-submission');
        await delay(500); // A new user submission follows the existing double-click guard.
        await form.locator('.tui-action-submit').click();
        await page.locator('[data-cancel-action]').click();
        assert.equal(keys.length, 4);
        assert.notEqual(keys[3], keys[0]);
    } finally {
        await browser.close();
    }
});

for (const failureMode of ["network abort", "HTTP 503"]) {
    test(`calendar continuation target retries the same confirmed submission after ${failureMode}`, async () => {
        const screen = makeCalendarContinuationScreen();
        const { browser, page, requestLog } = await openHarness(
            "https://app.test/?screen=test.grid&action=calendar.prepare",
            { screen, waitForInitialRows: false },
        );
        const prepareAction = screen.actions.find(item => item.key === "calendar.prepare");
        const confirmAction = screen.actions.find(item => item.key === "calendar.confirm");
        const token = "synthetic-calendar-preview-token";
        const targetRequests = [];
        const prepareRequests = [];
        const browserErrors = [];
        page.on("pageerror", error => browserErrors.push(error.message));
        page.on("console", message => {
            if (message.type() === "error") browserErrors.push(message.text());
        });
        let failFirstConfirmedRequest = true;
        try {
            await page.route("**/actions/calendar.prepare/run/", async route => {
                const request = route.request();
                const requestBody = route.request().postDataJSON();
                prepareRequests.push({
                    body: requestBody,
                    idempotencyKey: request.headers()["idempotency-key"],
                });
                if (!requestBody.confirmed) {
                    await route.fulfill({
                        status: 200,
                        contentType: "application/json",
                        body: JSON.stringify({
                            version: "tui-workbench.v2",
                            action: prepareAction,
                            confirmation_required: true,
                            confirmation: {
                                title: "确认操作",
                                message: "此操作会修改系统状态：准备日历预览。确认后才会执行。",
                                confirm_label: "确认执行",
                                cancel_label: "取消",
                            },
                            response: { status_code: 409 },
                            view_model: { kind: "message", title: "等待确认", status: "等待" },
                            debug: { raw_available: false, raw_response: null },
                        }),
                    });
                    return;
                }
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        version: "tui-workbench.v2",
                        outcome: "success",
                        action: prepareAction,
                        confirmation_required: false,
                        response: { status_code: 200 },
                        view_model: { kind: "detail", title: "已准备", status: "成功" },
                        debug: { raw_available: false, raw_response: null },
                        business_summary: "日历预览已准备。",
                        blocking_reason: "",
                        next_steps: [],
                        debug_hidden_fields: [],
                        user_error_code: "",
                        continuation: {
                            action_key: "calendar.confirm",
                            input: { confirmation_token: token },
                            expires_at: "2099-01-01T00:00:00Z",
                        },
                    }),
                });
            });
            await page.route("**/actions/calendar.confirm/run/", async route => {
                const request = route.request();
                const requestBody = request.postDataJSON();
                targetRequests.push({
                    body: requestBody,
                    idempotencyKey: request.headers()["idempotency-key"],
                });
                if (!requestBody.confirmed) {
                    await route.fulfill({
                        status: 200,
                        contentType: "application/json",
                        body: JSON.stringify({
                            version: "tui-workbench.v2",
                            action: confirmAction,
                            confirmation_required: true,
                            confirmation: {
                                title: "确认操作",
                                message: "此操作会修改系统状态：确认日历发布。确认后才会执行。",
                                confirm_label: "确认执行",
                                cancel_label: "取消",
                            },
                            response: { status_code: 409 },
                            view_model: { kind: "message", title: "等待确认", status: "待确认" },
                            debug: { raw_available: false, raw_response: null },
                            business_summary: "",
                            blocking_reason: "",
                            next_steps: [],
                            debug_hidden_fields: [],
                            user_error_code: "",
                        }),
                    });
                    return;
                }
                if (failFirstConfirmedRequest) {
                    failFirstConfirmedRequest = false;
                    if (failureMode === "network abort") {
                        await route.abort("failed");
                    } else {
                        await route.fulfill({
                            status: 503,
                            contentType: "application/json",
                            body: JSON.stringify({ detail: "暂时不可用" }),
                        });
                    }
                    return;
                }
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        version: "tui-workbench.v2",
                        outcome: "success",
                        action: confirmAction,
                        confirmation_required: false,
                        response: { status_code: 200 },
                        view_model: { kind: "detail", title: "已发布", status: "成功" },
                        debug: { raw_available: false, raw_response: null },
                        business_summary: "日历已发布。",
                        blocking_reason: "",
                        next_steps: [],
                        debug_hidden_fields: [],
                        user_error_code: "",
                    }),
                });
            });

            const firstPrepareResponse = page.waitForResponse(response =>
                response.url().includes("/actions/calendar.prepare/run/"),
            );
            await page.locator('[data-main-panel] form[data-action-ui-key="calendar.prepare"] .tui-action-submit').click();
            await firstPrepareResponse;
            assert.equal(prepareRequests.length, 1);
            assert.equal(prepareRequests[0].body.confirmed, false);

            const confirmedPrepareResponse = page.waitForResponse(response =>
                response.url().includes("/actions/calendar.prepare/run/"),
            );
            await page.locator("[data-confirm-action]").click();
            const sourceResponse = await confirmedPrepareResponse;
            assert.equal(sourceResponse.status(), 200);
            assert.equal(prepareRequests.length, 2);
            assert.equal(prepareRequests[1].body.confirmed, true);
            assert.equal(prepareRequests[1].idempotencyKey, prepareRequests[0].idempotencyKey);

            const continuationButton = page.locator("[data-result-continuation] button");
            await continuationButton.waitFor({ state: "visible", timeout: 1_000 }).catch(async () => {
                const diagnostics = await page.evaluate(() => ({
                    status: document.querySelector("[data-workbench-status]")?.textContent || "",
                    mainText: document.querySelector("[data-main-panel]")?.innerText || "",
                    mainHtml: document.querySelector("[data-main-panel]")?.innerHTML || "",
                    url: window.location.href,
                }));
                diagnostics.mainHtml = diagnostics.mainHtml.replaceAll(token, "<SYNTHETIC_TOKEN>");
                assert.fail(JSON.stringify({
                    stage: "source confirmed response did not render the continuation target",
                    prepareRequests,
                    targetRequests,
                    diagnostics,
                    browserErrors,
                    requestLog,
                }));
            });
            await continuationButton.click();
            await page.locator("[data-confirm-action]").click();

            await page.locator('[data-action-submission-retry="true"]').waitFor({ state: "visible" });
            await assertContinuationTokenNotPersisted(page, token);
            await page.locator('[data-action-submission-retry="true"]').click();
            await page.waitForFunction(
                () => document.querySelector("[data-workbench-status]")?.textContent === "操作完成",
            );

            const confirmedRequests = targetRequests.filter(item => item.body.confirmed);
            assert.equal(confirmedRequests.length, 2);
            assert.equal(targetRequests.length, 3);
            assert.ok(confirmedRequests[0].idempotencyKey);
            assert.equal(confirmedRequests[1].idempotencyKey, confirmedRequests[0].idempotencyKey);
            assert.deepEqual(confirmedRequests[1].body, confirmedRequests[0].body);
            assert.equal(confirmedRequests[0].body.params.confirmation_token, token);
            assert.equal(confirmedRequests[0].body.confirmed, true);
            assert.equal(confirmedRequests[0].body.confirmation.confirmed, true);
            await assertContinuationTokenNotPersisted(page, token);
        } finally {
            await browser.close();
        }
    });
}

test("same-screen unrelated action clears a calendar continuation before target submission", async () => {
    const screen = makeCalendarContinuationScreen();
    const prepareAction = screen.actions.find(item => item.key === "calendar.prepare");
    const confirmAction = screen.actions.find(item => item.key === "calendar.confirm");
    const unrelatedAction = action("calendar.scope", {
        label: "读取日历配置状态",
        method: "GET",
        risk: "read",
        task_tier: "primary",
        screen_key: "test.grid",
    });
    screen.actions.push(unrelatedAction);
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.grid&action=calendar.prepare",
        { screen, waitForInitialRows: false },
    );
    const token = "synthetic-calendar-context-token";
    let targetRequests = 0;
    try {
        await page.route("**/actions/calendar.prepare/run/", async route => {
            if (!route.request().postDataJSON().confirmed) {
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        version: "tui-workbench.v2",
                        action: prepareAction,
                        confirmation_required: true,
                        confirmation: { message: "确认准备" },
                        response: { status_code: 409 },
                        view_model: { kind: "message", title: "等待确认", status: "等待" },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
                return;
            }
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    version: "tui-workbench.v2",
                    outcome: "success",
                    action: prepareAction,
                    confirmation_required: false,
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "已准备", status: "成功" },
                    debug: { raw_available: false, raw_response: null },
                    continuation: {
                        action_key: "calendar.confirm",
                        input: { confirmation_token: token },
                        expires_at: "2099-01-01T00:00:00Z",
                    },
                }),
            });
        });
        await page.route("**/actions/calendar.scope/run/", async route => {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    version: "tui-workbench.v2",
                    outcome: "success",
                    action: unrelatedAction,
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "配置状态", status: "读取完成" },
                    debug: { raw_available: false, raw_response: null },
                }),
            });
        });
        await page.route("**/actions/calendar.confirm/run/", async route => {
            targetRequests += 1;
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    version: "tui-workbench.v2",
                    outcome: "success",
                    action: confirmAction,
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "已发布", status: "成功" },
                    debug: { raw_available: false, raw_response: null },
                }),
            });
        });

        await page.locator('[data-main-panel] form[data-action-ui-key="calendar.prepare"] .tui-action-submit').click();
        await page.locator("[data-confirm-action]").click();
        await page.locator("[data-result-continuation] button").waitFor({ state: "visible" });
        await page.locator('[data-actions-panel] [data-toggle-advanced]').click();
        const targetForm = page.locator('[data-actions-panel] form[data-action-ui-key="calendar.confirm"]');
        await targetForm.waitFor({ state: "visible" });
        await page.locator('[data-action-ui-key="calendar.scope"] .tui-action-submit').click();
        await page.waitForFunction(
            () => document.querySelector("[data-workbench-status]")?.textContent === "读取完成",
        );
        await targetForm.locator(".tui-action-submit").click();
        await page.waitForFunction(
            () => document.querySelector("[data-workbench-status]")?.textContent === "等待重新准备",
        );
        assert.equal(targetRequests, 0);
        await assertContinuationTokenNotPersisted(page, token);
    } finally {
        await browser.close();
    }
});

test("an unconfirmed continuation retry returns through confirmation before publishing", async () => {
    const screen = makeCalendarContinuationScreen();
    const prepareAction = screen.actions.find(item => item.key === "calendar.prepare");
    const confirmAction = screen.actions.find(item => item.key === "calendar.confirm");
    const token = "synthetic-calendar-unconfirmed-retry-token";
    const targetRequests = [];
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.grid&action=calendar.prepare",
        { screen, waitForInitialRows: false },
    );
    try {
        await page.route("**/actions/calendar.prepare/run/", async route => {
            const body = route.request().postDataJSON();
            if (!body.confirmed) {
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        version: "tui-workbench.v2",
                        action: prepareAction,
                        confirmation_required: true,
                        confirmation: { message: "确认准备" },
                        response: { status_code: 409 },
                        view_model: { kind: "message", title: "等待确认", status: "等待" },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
                return;
            }
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    version: "tui-workbench.v2",
                    outcome: "success",
                    action: prepareAction,
                    confirmation_required: false,
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "已准备", status: "成功" },
                    debug: { raw_available: false, raw_response: null },
                    continuation: {
                        action_key: "calendar.confirm",
                        input: { confirmation_token: token },
                        expires_at: "2099-01-01T00:00:00Z",
                    },
                }),
            });
        });
        await page.route("**/actions/calendar.confirm/run/", async route => {
            const request = route.request();
            const body = request.postDataJSON();
            targetRequests.push({ body, key: request.headers()["idempotency-key"] });
            if (!body.confirmed && targetRequests.length === 1) {
                await route.fulfill({
                    status: 503,
                    contentType: "application/json",
                    body: JSON.stringify({ detail: "暂时不可用" }),
                });
                return;
            }
            if (!body.confirmed) {
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        version: "tui-workbench.v2",
                        action: confirmAction,
                        confirmation_required: true,
                        confirmation: {
                            title: "确认操作",
                            message: "此操作会修改系统状态：确认日历发布。确认后才会执行。",
                            confirm_label: "确认执行",
                            cancel_label: "取消",
                        },
                        response: { status_code: 409 },
                        view_model: { kind: "message", title: "等待确认", status: "待确认" },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
                return;
            }
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    version: "tui-workbench.v2",
                    outcome: "success",
                    action: confirmAction,
                    confirmation_required: false,
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "已发布", status: "成功" },
                    debug: { raw_available: false, raw_response: null },
                }),
            });
        });

        await page.locator('[data-main-panel] form[data-action-ui-key="calendar.prepare"] .tui-action-submit').click();
        await page.locator("[data-confirm-action]").click();
        await page.locator("[data-result-continuation] button").waitFor({ state: "visible" });
        await page.locator("[data-result-continuation] button").click();
        await page.locator('[data-action-submission-retry="true"]').waitFor({ state: "visible" });
        await page.locator('[data-action-submission-retry="true"]').click();
        await page.locator("[data-confirm-action]").waitFor({ state: "visible" });
        await page.locator("[data-confirm-action]").click();
        await page.waitForFunction(
            () => document.querySelector("[data-workbench-status]")?.textContent === "操作完成",
        );

        assert.equal(targetRequests.length, 3);
        assert.equal(targetRequests[0].body.confirmed, false);
        assert.equal(targetRequests[1].body.confirmed, false);
        assert.equal(targetRequests[0].key, targetRequests[1].key);
        assert.equal(targetRequests[1].key, targetRequests[2].key);
        assert.equal(targetRequests[0].body.params.confirmation_token, token);
        assert.equal(targetRequests[1].body.params.confirmation_token, token);
        assert.equal(targetRequests[2].body.params.confirmation_token, token);
        assert.equal(targetRequests[2].body.confirmed, true);
        assert.equal(targetRequests[2].body.confirmation.confirmed, true);
        await assertContinuationTokenNotPersisted(page, token);
    } finally {
        await browser.close();
    }
});

test("calendar continuation keeps request identity across a password challenge without retaining the password", async () => {
    const screen = makeCalendarContinuationScreen();
    const prepareAction = screen.actions.find(item => item.key === "calendar.prepare");
    const confirmAction = screen.actions.find(item => item.key === "calendar.confirm");
    confirmAction.risk = "admin";
    const token = "synthetic-calendar-reauth-token";
    const targetRequests = [];
    let failFirstReauth = true;
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.grid&action=calendar.prepare",
        { screen, waitForInitialRows: false },
    );
    try {
        await page.route("**/actions/calendar.prepare/run/", async route => {
            const requestBody = route.request().postDataJSON();
            if (!requestBody.confirmed) {
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        version: "tui-workbench.v2",
                        action: prepareAction,
                        confirmation_required: true,
                        confirmation: { title: "确认", message: "确认准备预览。" },
                        response: { status_code: 409 },
                        view_model: { kind: "message", title: "等待确认", status: "等待" },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
                return;
            }
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    version: "tui-workbench.v2",
                    outcome: "success",
                    action: prepareAction,
                    confirmation_required: false,
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "预览已准备", status: "成功" },
                    debug: { raw_available: false, raw_response: null },
                    continuation: {
                        action_key: "calendar.confirm",
                        input: { confirmation_token: token },
                        expires_at: "2099-01-01T00:00:00Z",
                    },
                }),
            });
        });
        await page.route("**/actions/calendar.confirm/run/", async route => {
            const request = route.request();
            const body = request.postDataJSON();
            targetRequests.push({ body, key: request.headers()["idempotency-key"] });
            if (!body.confirmed) {
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        version: "tui-workbench.v2",
                        action: confirmAction,
                        confirmation_required: true,
                        confirmation: { title: "确认", message: "确认发布日历。" },
                        response: { status_code: 409 },
                        view_model: { kind: "message", title: "等待确认", status: "等待" },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
                return;
            }
            if (!body.reauth) {
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        version: "tui-workbench.v2",
                        action: confirmAction,
                        password_challenge_required: true,
                        password_challenge: { challenge_id: "calendar-password-1", message: "请验证密码" },
                        response: { status_code: 403 },
                        view_model: { kind: "message", title: "等待验密", status: "等待" },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
                return;
            }
            if (body.reauth.credential === "first-password" && failFirstReauth) {
                failFirstReauth = false;
                await route.fulfill({
                    status: 503,
                    contentType: "application/json",
                    body: JSON.stringify({ detail: "暂时不可用" }),
                });
                return;
            }
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    version: "tui-workbench.v2",
                    outcome: "success",
                    action: confirmAction,
                    confirmation_required: false,
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "日历已发布", status: "成功" },
                    debug: { raw_available: false, raw_response: null },
                }),
            });
        });

        await page.locator('[data-main-panel] form[data-action-ui-key="calendar.prepare"] .tui-action-submit').click();
        await page.locator("[data-confirm-action]").click();
        const continuation = page.locator("[data-result-continuation] button");
        await continuation.waitFor({ state: "visible" });
        await continuation.click();
        await page.locator("[data-confirm-action]").click();
        const firstChallenge = page.locator("[data-password-challenge-form]");
        await firstChallenge.waitFor({ state: "visible" });
        await firstChallenge.locator('[name="password"]').fill("first-password");
        await firstChallenge.locator('[type="submit"]').click();
        await page.locator('[data-action-submission-retry="true"]').waitFor({ state: "visible" });
        await assertContinuationTokenNotPersisted(page, token);
        assert.equal((await page.locator("body").innerText()).includes("first-password"), false);

        await page.locator('[data-action-submission-retry="true"]').click();
        const retryChallenge = page.locator("[data-password-challenge-form]");
        await retryChallenge.waitFor({ state: "visible" });
        assert.equal(targetRequests.length, 4);
        assert.equal(targetRequests[3].body.confirmed, true);
        assert.equal(targetRequests[3].body.reauth, undefined);
        await retryChallenge.locator('[name="password"]').fill("second-password");
        await retryChallenge.locator('[type="submit"]').click();
        await page.waitForFunction(
            () => document.querySelector("[data-workbench-status]")?.textContent === "操作完成",
        );

        assert.equal(targetRequests.length, 5);
        assert.equal(new Set(targetRequests.map(item => item.key)).size, 1);
        const confirmed = targetRequests.filter(item => item.body.confirmed);
        assert.equal(new Set(confirmed.map(item => item.body.params.confirmation_token)).size, 1);
        assert.equal(confirmed[0].body.params.confirmation_token, token);
        assert.equal(new Set(confirmed.map(item => JSON.stringify(item.body.confirmation))).size, 1);
        assert.equal(confirmed[2].body.reauth, undefined);
        assert.equal(confirmed[1].body.reauth.credential, "first-password");
        assert.equal(confirmed[3].body.reauth.credential, "second-password");
        await assertContinuationTokenNotPersisted(page, token);
        assert.equal((await page.locator("body").innerText()).includes("second-password"), false);
    } finally {
        await browser.close();
    }
});

const bundlePath = resolve(root, "static/js/tui-workbench.js");
const cssPath = resolve(root, "static/css/tui-workbench.css");

for (const empty of [false, true]) {
    test(`dashboard displays blocking evidence with ${empty ? "empty" : "cached"} rows`, async () => {
        const summaryScreen = structuredClone(dashboardScreen);
        summaryScreen.actions = [action("test.list")];
        summaryScreen.screen.dashboard_panels = [{ key: "alpha", title: "Alpha", kind: "datagrid", action_key: "test.list", user_priority: "p0", presentation_semantic: "primary_list" }];
        const { browser, page } = await openHarness("https://app.test/?screen=test.dashboard", { dashboardScreen: summaryScreen, waitForInitialRows: false });
        try {
            await page.route("**/actions/test.list/run/", async route => {
                const result = listResult();
                result.view_model.business_summary = "Alpha 自动更新异常。评分日期 2026-09-04";
                result.view_model.blocking_reason = "行情口径不一致 <script>unsafe</script>";
                if (empty) result.view_model.rows = [];
                await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(result) });
            });
            await page.reload();
            await page.addStyleTag({ path: cssPath });
            await page.addScriptTag({ path: bundlePath });
            const notice = page.locator("[data-panel-blocking-notice]");
            await notice.waitFor({ state: "visible" });
            assert.match(await notice.innerText(), /2026-09-04/);
            assert.match(await notice.innerText(), /行情口径不一致/);
            assert.equal(await notice.locator("script").count(), 0);
        } finally { await browser.close(); }
    });
}

test("UX summary full-list entry returns to the overview", async () => {
    const summaryScreen = structuredClone(dashboardScreen);
    summaryScreen.actions = [action('test.list')];
    summaryScreen.screen.dashboard_panels = [{ key: 'summary', title: '摘要清单', kind: 'datagrid', action_key: 'test.list', user_priority: 'p0', presentation_semantic: 'primary_list', max_rows: 8 }];
    const { browser, page } = await openHarness('https://app.test/?screen=test.dashboard', { dashboardScreen: summaryScreen, waitForInitialRows: false });
    try {
        await page.locator('[data-panel-full-list]').click();
        await page.locator('.tui-datagrid').waitFor();
        await page.locator('[data-return-dashboard]').click();
        await page.locator('[data-dashboard-panel="summary"]').waitFor();
        await page.waitForFunction(() => document.querySelectorAll('[data-dashboard-panel="summary"] tbody tr').length === 8);
        assert.equal(await page.locator('[data-dashboard-panel="summary"] tbody tr').count(), 8);
    } finally { await browser.close(); }
});

test("UX blocked business outcome removes the operated checklist mark", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.route('**/actions/test.list/run/', async route => {
            const result = listResult(); result.outcome = 'blocked';
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) });
        });
        await page.locator('form[data-action-ui-key="test.list"] .tui-action-button').click();
        await page.waitForFunction(() => !document.querySelector('form[data-action-ui-key="test.list"]').classList.contains('is-completed'));
        assert.match(await page.locator('[data-action-summary]').innerText(), /本次已操作 0/);
    } finally { await browser.close(); }
});

test("UX row task navigation prefills the object without submitting a write", async () => {
    const { browser, page } = await openHarness();
    let writes = 0;
    page.on('request', request => { if (request.url().includes('/actions/test.edit/run/')) writes++; });
    try {
        await page.route('**/actions/test.list/run/', async route => {
            const result = listResult();
            result.view_model.rows = [{ code: 'asset-A', target_screen: 'test.grid', target_action_key: 'test.edit' }];
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) });
        });
        await page.keyboard.press('F5');
        await page.getByText('asset-A', { exact: true }).first().waitFor();
        await page.locator('[data-row-index="0"]').dblclick();
        await page.locator('[data-row-target-screen]').click();
        const input = page.locator('form[data-action-ui-key="test.edit"] [name="code"]');
        await input.waitFor();
        assert.equal(await input.inputValue(), 'asset-A');
        assert.equal(writes, 0);
    } finally { await browser.close(); }
});

test("UX candidate count is independent of page size and preserves every loaded row", async () => {
    const candidateScreen = structuredClone(dashboardScreen);
    candidateScreen.actions = [action('test.list', { fields: [{ key: 'top_n', label: '候选数量', input_type: 'select', options: ['45'], default: '45', presentation_semantic: 'primary_selector' }] })];
    candidateScreen.screen.dashboard_panels = [{ key: 'candidates', title: '候选清单', kind: 'datagrid', action_key: 'test.list', filter_fields: ['top_n'], user_priority: 'p0', presentation_semantic: 'primary_list' }];
    const { browser, page } = await openHarness('https://app.test/', { dashboardScreen: candidateScreen });
    let requests = 0;
    try {
        await page.route('**/actions/test.list/run/', async route => {
            requests++;
            if (requests === 2) {
                await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ title: '暂时不可用' }) });
                return;
            }
            const result = listResult(); result.view_model.rows = result.view_model.rows.slice(0, 45);
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) });
        });
        await page.locator('[data-current-location]').fill('screen:test.dashboard');
        await page.locator('[data-current-location]').press('Enter');
        const panel = page.locator('[data-dashboard-panel="candidates"]');
        await panel.locator('[data-panel-page-delta="1"]').waitFor();
        assert.equal(await panel.locator('tbody tr').count(), 20);
        await panel.locator('[data-panel-page-delta="1"]').click();
        assert.match(await panel.locator('tbody').innerText(), /row-021/);
        await panel.locator('[data-panel-page-delta="1"]').click();
        assert.equal(await panel.locator('tbody tr').count(), 5);
        assert.match(await panel.locator('tbody').innerText(), /row-045/);
        assert.equal(requests, 1);
        await panel.getByRole('button', { name: '更新清单' }).click();
        await panel.locator('.tui-panel-error').waitFor();
        await panel.getByRole('button', { name: '更新清单' }).click();
        await panel.locator('tbody tr').first().waitFor();
        assert.equal(requests, 3);
    } finally { await browser.close(); }
});

test("UX navigation never restores password drafts", async () => {
    const { browser, page } = await openHarness('https://app.test/?screen=test.grid&action=test.password', { waitForInitialRows: false });
    try {
        await page.locator('form[data-action-ui-key="test.password"] [name="new_password"]').fill('not-for-storage');
        await page.locator('[data-current-location]').fill('screen:test.dashboard');
        await page.locator('[data-current-location]').press('Enter');
        await page.locator('[data-dashboard-panel]').first().waitFor();
        await page.goBack();
        await page.waitForFunction(() => document.querySelector('[data-current-location]')?.value === 'screen:test.grid');
        const secret = page.locator('form[data-action-ui-key="test.password"] [name="new_password"]');
        await secret.waitFor();
        assert.equal(await secret.inputValue(), '');
        assert.equal(await page.evaluate(() => JSON.stringify({ ...sessionStorage, ...localStorage }).includes('not-for-storage')), false);
    } finally { await browser.close(); }
});

test("UX unknown cursor totals are not presented as zero or random pages", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.route('**/actions/test.list/run/', async route => {
            const result = listResult(); result.view_model.rows = result.view_model.rows.slice(0, 20);
            result.view_model.pager = { pagination_mode: 'cursor', has_next: true, has_previous: false, next_cursor: 'next' };
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) });
        });
        await page.keyboard.press('F5');
        await page.getByText(/总量未知/).waitFor();
        assert.equal(await page.locator('[data-page-number]').count(), 0);
        assert.doesNotMatch(await page.locator('.tui-datagrid-pager').innerText(), /共 0 行/);
    } finally { await browser.close(); }
});

test("UX pagination offers page size, range and direct page navigation", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.locator('[data-page-size]').selectOption('20');
        assert.equal(await page.locator('[data-row-index]').count(), 20);
        await page.locator('[data-page-number]').fill('3');
        await page.locator('[data-page-number]').press('Enter');
        await page.locator('[data-row-index="40"]').waitFor();
        assert.match(await page.locator('.tui-datagrid-pager').innerText(), /41–60/);
    } finally { await browser.close(); }
});

test("UX returning to a screen restores safe drafts, filter and client page", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.locator('[data-page-delta="1"]').click();
        await page.locator('form[data-action-ui-key="test.detail"] [name="code"]').fill('draft-code');
        await page.locator('[data-current-location]').fill('screen:test.dashboard');
        await page.locator('[data-current-location]').press('Enter');
        await page.locator('[data-dashboard-panel]').first().waitFor();
        await page.goBack();
        await page.locator('[data-row-index="20"]').waitFor();
        assert.equal(await page.locator('form[data-action-ui-key="test.detail"] [name="code"]').inputValue(), 'draft-code');
    } finally { await browser.close(); }
});

test("UX refreshing a queued AI run only observes the existing run", async () => {
    const { browser, page } = await openHarness('https://app.test/?screen=test.grid&action=test.queued', { waitForInitialRows: false });
    let submissions = 0;
    page.on('request', request => { if (request.url().includes('/actions/test.queued/run/')) submissions++; });
    try {
        const form = page.locator('form[data-action-ui-key="test.queued"]');
        await form.locator('[name="task_id"]').fill('7');
        await form.locator('[name="message"]').fill('Observe this task');
        await form.locator('.tui-action-button').click();
        await page.waitForFunction(() => document.querySelector('[data-workbench-status]').textContent.includes('已完成'));
        await page.keyboard.press('F5');
        await delay(250);
        assert.equal(submissions, 1);
    } finally { await browser.close(); }
});

test("UX server pagination retains the table and recovers from a failed page", async () => {
    const { browser, page } = await openHarness();
    const requests = [];
    try {
        await page.route('**/actions/test.list/run/', async route => {
            const params = route.request().postDataJSON().params;
            requests.push(params);
            if (params.page === 2) {
                await delay(250);
                await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ title: '暂时不可用' }) });
            } else {
                const result = listResult();
                result.view_model.rows = result.view_model.rows.slice(0, 20);
                result.view_model.pager = { page: 1, page_size: 20, total_rows: 45, total_pages: 3, has_next: true, has_previous: false };
                await delay(150);
                await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) });
            }
        });
        await page.keyboard.press('F5');
        await page.waitForFunction(() => document.querySelector('[data-page-number]')?.max === '3');
        await page.waitForFunction(() => document.querySelectorAll('[data-row-index]').length === 20);
        await page.keyboard.press('F7');
        assert.match(await page.locator('[data-filter-input]').getAttribute('placeholder'), /当前页/);
        await page.keyboard.press('Escape');
        await page.locator('[data-page-delta="1"]').click();
        assert.equal(await page.locator('[data-row-index]').count(), 20);
        await page.locator('[data-grid-retry]').waitFor();
        assert.equal(await page.locator('[data-row-index]').first().innerText().then(text => text.includes('row-001')), true);
        assert.equal(requests.at(-1).page, 2);
    } finally { await browser.close(); }
});

const harnessHtml = `<!doctype html>
<html><head><meta charset="utf-8"><title>TUI harness</title></head><body>
<div data-tui-app data-user-key="test-user">
  <button data-menu-command="file">系统</button>
  <button data-menu-command="module">模块</button>
  <button data-menu-command="action">任务</button>
  <button data-menu-command="view">视图</button>
  <button data-menu-command="help">帮助</button>
  <nav data-experience-controls hidden><div role="tablist">
    <button role="tab" data-experience-mode="task" aria-selected="false">任务模式</button>
    <button role="tab" data-experience-mode="professional" aria-selected="false">专业模式</button>
  </div><button data-experience-home hidden>返回任务首页</button></nav>
  <span data-tui-clock></span><span data-theme-status></span><span data-theme-indicator-code></span>
  <input data-current-location value="screen:boot">
  <div data-menu-popover role="menu" hidden></div>
  <aside data-rail-panel><button data-toggle-rail></button><div data-module-tree></div></aside>
  <div class="tui-workspace-grid">
    <section class="tui-panel"><div class="tui-panel-body" data-actions-panel></div></section>
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
        confirmation_required: Boolean(options.confirmation_required),
        result_semantics: options.result_semantics || [],
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
        effect: "update",
        task_tier: "advanced",
        confirmation_required: true,
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
        task_tier: "advanced",
        screen_key: "test.edit-dashboard",
        fields: [
            { key: "user_id", label: "用户 ID", input_type: "number", required: true, binding: "path" },
            { key: "username", label: "用户名", input_type: "text", required: true, binding: "body" },
        ],
        sequence: 13,
    }),
    action("test.lookup-user", {
        label: "查询用户",
        view_type: "detail",
        task_tier: "support",
        screen_key: "test.edit-dashboard",
        fields: [
            { key: "user_id", label: "用户 ID", input_type: "number", required: true },
        ],
        sequence: 18,
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
    action("test.queued", {
        label: "排队执行助手任务",
        risk: "ai",
        method: "POST",
        effect: "create",
        result_semantics: ["primary_status"],
        sequence: 16,
        fields: [
            { key: "task_id", label: "已有任务 ID", input_type: "number", value_type: "integer", required: true },
            { key: "message", label: "任务说明", input_type: "textarea", value_type: "string", required: true },
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

const experienceCatalog = {
    ...catalog,
    default_screen: "test.dashboard",
    diagnostics: { raw_response_allowed: false },
    experience: {
        home_screen_key: "test.dashboard",
        default_mode: "task",
        modes: [
            {
                key: "task",
                label: "任务模式",
                entries: [
                    {
                        key: "today",
                        kind: "screen",
                        label: "今日关注",
                        description: "查看今日任务。",
                        screen_key: "test.dashboard",
                    },
                    {
                        key: "research",
                        kind: "screen",
                        label: "研究标的",
                        description: "进入研究工作区。",
                        screen_key: "test.grid",
                    },
                    {
                        key: "portfolio",
                        kind: "screen",
                        label: "检查组合",
                        description: "查看组合事实。",
                        screen_key: "test.user-governance",
                    },
                ],
            },
            { key: "professional", label: "专业模式", entries: [] },
        ],
        utilities: [
            {
                key: "resume",
                kind: "resume",
                label: "继续上次任务",
                description: "回到最近工作区。",
            },
        ],
    },
};

function makeCalendarContinuationScreen() {
    const prepare = action("calendar.prepare", {
        label: "准备日历预览",
        method: "POST",
        risk: "write",
        task_tier: "primary",
        confirmation_required: true,
        screen_key: "test.grid",
    });
    prepare.session_auth_required = true;
    prepare.result_continuation = {
        target_action_key: "calendar.confirm",
        field_map: { confirmation_token: "confirmation_token" },
    };
    const confirm = action("calendar.confirm", {
        label: "确认日历发布",
        method: "POST",
        risk: "write",
        task_tier: "advanced",
        confirmation_required: true,
        screen_key: "test.grid",
        fields: [{
            key: "confirmation_token",
            label: "确认令牌",
            input_type: "hidden",
            value_type: "string",
            required: true,
            binding: "body",
            presentation_semantic: "api_token",
            default: "",
        }],
    });
    confirm.session_auth_required = true;
    return {
        ...screen,
        screen: { ...screen.screen, default_action_key: prepare.key },
        actions: [prepare, confirm],
    };
}

async function assertContinuationTokenNotPersisted(page, token) {
    const found = await page.evaluate(expected => {
        const retained = [
            window.location.href,
            document.documentElement.outerHTML,
            JSON.stringify(Object.entries(window.localStorage)),
            JSON.stringify(Object.entries(window.sessionStorage)),
        ].join("\\n");
        return retained.includes(expected);
    }, token);
    assert.equal(found, false, "continuation token must stay out of URL, DOM and browser storage");
}

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
                    { key: "observed_at", label: "观测时间" },
                    { key: "approval_status", label: "准入状态" },
                ],
                row_actions: [
                    ["批准", "receipt", "users"],
                    ["复核", "receipt", ""],
                    ["查看", "receipt", ""],
                    ["停用", "receipt", "users"],
                    ["撤销", "receipt", "users"],
                ].map(([label, resultPanelKey, refreshPanelKey]) => ({
                    action_key: "test.approve-user",
                    label_template: `${label} {username}`,
                    param_map: { user_id: "user_id" },
                    result_panel_key: resultPanelKey,
                    ...(refreshPanelKey ? { refresh_panel_key: refreshPanelKey } : {}),
                })),
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
        dashboard_panels: [
            {
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
            },
            {
                key: "edit-user",
                title: "编辑用户资料",
                kind: "detail",
                user_priority: "p0",
                presentation_semantic: "primary_action",
                action_key: "test.edit-row",
                note: "填写用户 ID 和用户名后提交。",
            },
            {
                key: "lookup-user",
                title: "查询用户资料",
                kind: "detail",
                user_priority: "p0",
                presentation_semantic: "supporting_detail",
                action_key: "test.lookup-user",
                note: "填写用户 ID 后查询。",
            },
        ],
        user_experience: { primary_task: "编辑用户", primary_outcome: "提交修改后的用户资料" },
    },
    actions: actions.filter((item) => ["test.user-list", "test.edit-row", "test.lookup-user"].includes(item.key)),
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
    await page.addInitScript((initialSessionStorage) => {
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
        const currentDate = new Date().toLocaleDateString("en-CA");
        Object.entries(initialSessionStorage || {}).forEach(([key, value]) => {
            window.sessionStorage.setItem(
                key,
                String(value).replaceAll("__CURRENT_DATE__", currentDate),
            );
        });
    }, options.initialSessionStorage || {});
    await page.route("https://app.test/**", async (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === "/") {
            await route.fulfill({ status: 200, contentType: "text/html", body: options.html || harnessHtml });
            return;
        }
        if (url.pathname === "/api/tui/catalog/") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(options.catalog || catalog) });
            return;
        }
        if (url.pathname === "/api/tui/screens/test.grid/") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(options.screen || screen) });
            return;
        }
        if (url.pathname === "/api/tui/screens/test.dashboard/") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(options.dashboardScreen || dashboardScreen) });
            return;
        }
        if (url.pathname === "/api/tui/screens/test.user-governance/") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(userGovernanceScreen) });
            return;
        }
        if (url.pathname === "/api/tui/screens/test.edit-dashboard/") {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(options.editableDashboardScreen || editableDashboardScreen) });
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
                            { key: "observed_at", label: "观测时间" },
                            { key: "approval_status", label: "准入状态" },
                        ],
                        rows: [{
                            user_id: 42,
                            username: "pending-user",
                            observed_at: "2026-08-28T09:30:00+08:00",
                            approval_status: "pending",
                        }],
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
                        confidence_unit: options.regimeConfidenceUnit,
                        quadrant_distribution: options.quadrantDistribution || [],
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
        if (url.pathname.includes("/actions/test.queued/run/")) {
            await route.fulfill({
                status: 202,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.queued"),
                    view_model: {
                        kind: "detail",
                        title: "排队执行助手任务",
                        status: "已排队",
                        fields: [
                            { key: "run_id", label: "运行编号", value: "run-tui-queued-0001" },
                            { key: "task_id", label: "任务 ID", value: "17" },
                            { key: "run_status", label: "运行状态", value: "已排队" },
                            { key: "event_summary", label: "服务器进度", value: "等待服务器端 Worker 返回进度" },
                        ],
                        business_summary: "任务已提交到服务器端队列。",
                        queued_run: {
                            run_id: "run-tui-queued-0001",
                            task_id: 17,
                            status: "queued",
                            status_url: "/api/terminal/runs/run-tui-queued-0001/",
                            events_url: "/api/terminal/runs/run-tui-queued-0001/events/",
                            cancel_url: "/api/terminal/runs/run-tui-queued-0001/cancel/",
                            event_cursor: 0,
                            events: [],
                        },
                    },
                }),
            });
            return;
        }
        if (url.pathname === "/api/terminal/runs/run-tui-queued-0001/events/") {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    run_id: "run-tui-queued-0001",
                    events: [{
                        event_id: "event-1",
                        event_type: "server_progress",
                        sequence: 1,
                        occurred_at: "2026-08-22T00:00:01+00:00",
                        data: { status: "running" },
                    }],
                }),
            });
            return;
        }
        if (url.pathname === "/api/terminal/runs/run-tui-queued-0001/") {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    run_id: "run-tui-queued-0001",
                    status: "completed",
                    updated_at: "2026-08-22T00:00:02+00:00",
                    status_url: "/api/terminal/runs/run-tui-queued-0001/",
                    events_url: "/api/terminal/runs/run-tui-queued-0001/events/",
                    cancel_url: "/api/terminal/runs/run-tui-queued-0001/cancel/",
                    error_code: null,
                    result_ref: "result-1",
                }),
            });
            return;
        }
        const actionKey = decodeURIComponent(url.pathname.match(/\/actions\/([^/]+)\/run\//)?.[1] || "");
        const requestBody = route.request().postDataJSON?.() || {};
        if (actionKey === "test.dashboard-summary") {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: options.dashboardSummaryAction,
                    view_model: {
                        kind: "detail",
                        title: "组合摘要",
                        status: "正常",
                        fields: options.dashboardSummaryFields || [],
                    },
                }),
            });
            return;
        }
        if (actionKey === "test.edit" && !requestBody.confirmed) {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === actionKey),
                    confirmation_required: true,
                    confirmation: { title: "确认操作", message: "确认保存编辑。" },
                    view_model: { kind: "message", title: "等待确认", status: "等待", message: "等待确认" },
                }),
            });
            return;
        }
        if (actionKey === "test.edit" && options.confirmedMutationDelayMs) {
            await delay(options.confirmedMutationDelayMs);
        }
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
        await page.addStyleTag({ path: cssPath });
        await page.addScriptTag({ path: bundlePath });
        if (options.waitForInitialRows !== false) {
            await page.waitForSelector('[data-row-index="0"]');
        } else {
            await page.waitForFunction(() => Boolean(
                document.querySelector("[data-screen-title]")?.textContent?.trim(),
            ));
        }
        return { browser, page, requestLog, browserErrors };
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

test("F9 exposes support and advanced tasks before focusing the task search", async () => {
    const { browser, page } = await openHarness();
    try {
        const form = page.locator('form[data-action-ui-key="test.edit"]');
        assert.equal(await form.isVisible(), false);
        await page.keyboard.press("F9");
        await form.waitFor({ state: "visible" });
        assert.equal(
            await page.locator("[data-action-filter]").evaluate(
                (element) => element === document.activeElement,
            ),
            true,
        );
        const submit = form.locator(".tui-action-submit");
        await submit.scrollIntoViewIfNeeded();
        assert.equal(
            await submit.evaluate((element) => {
                const rect = element.getBoundingClientRect();
                const scrollHost = element.closest(".tui-panel-body");
                const hostRect = scrollHost?.getBoundingClientRect();
                return Boolean(hostRect)
                    && rect.top >= hostRect.top
                    && rect.bottom <= hostRect.bottom;
            }),
            true,
        );
    } finally {
        await browser.close();
    }
});

test("confirmed mutations leave loading only after the real response settles", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.grid&action=test.edit&code=settlement-code",
        { waitForInitialRows: false, confirmedMutationDelayMs: 150 },
    );
    try {
        const form = page.locator('form[data-action-ui-key="test.edit"]');
        await form.locator(".tui-action-submit").click();
        await page.locator("[data-confirm-action]").click();
        assert.equal(await page.locator("[data-workbench-status]").innerText(), "读取数据");
        await page.waitForFunction(
            () => document.querySelector("[data-workbench-status]")?.textContent === "操作完成",
        );
        assert.match(await page.locator("[data-main-panel]").innerText(), /正常 \/ 完成/);
        assert.equal(await page.locator(".tui-error").count(), 0);
    } finally {
        await browser.close();
    }
});

test("queued Agent action submits once and replays server status and events", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.grid&action=test.queued",
        { waitForInitialRows: false },
    );
    try {
        let submitRequests = 0;
        let eventRequests = 0;
        let statusRequests = 0;
        page.on("request", (request) => {
            if (request.url().includes("/actions/test.queued/run/")) {
                submitRequests += 1;
            }
            if (request.url().includes("/api/terminal/runs/run-tui-queued-0001/events/")) {
                eventRequests += 1;
            }
            if (request.url().endsWith("/api/terminal/runs/run-tui-queued-0001/")) {
                statusRequests += 1;
            }
        });
        const form = page.locator('form[data-action-ui-key="test.queued"]');
        await form.waitFor({ state: "visible" });
        await form.locator('[name="task_id"]').fill("17");
        await form.locator('[name="message"]').fill("检查服务器端运行状态");
        const submit = page.waitForRequest((request) => request.url().includes("/actions/test.queued/run/"));
        await form.locator(".tui-action-submit").click();
        const request = await submit;
        assert.equal(request.postDataJSON().params.task_id, 17);
        assert.equal(request.postDataJSON().params.message, "检查服务器端运行状态");
        await page.waitForFunction(() => document.querySelector("[data-main-panel]")?.innerText.includes("已完成"));
        assert.equal(submitRequests, 1);
        assert.equal(eventRequests, 1);
        assert.equal(statusRequests, 1);
        assert.match(await page.locator("[data-main-panel]").innerText(), /server_progress/);
        assert.match(await page.locator("[data-workbench-status]").innerText(), /服务器端任务已完成/);
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

test("non-immersive dashboard deep links prioritize the explicit read", async () => {
    const { browser, page, requestLog } = await openHarness(
        "https://app.test/?screen=test.user-governance&action=test.user-list",
        { waitForInitialRows: false },
    );
    try {
        await delay(500);
        assert.equal(
            requestLog.filter((entry) => (
                entry.startsWith("REQ ") && entry.includes("/actions/test.user-list/run/")
            )).length,
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
        const firstSecondPageRow = page.locator('[data-row-index="20"]');
        await firstSecondPageRow.click();
        await page.locator('form[data-action-ui-key="test.detail"] [data-fill-from-row]').click();
        assert.equal(await page.locator('form[data-action-ui-key="test.detail"] [name="code"]').inputValue(), "row-021");
        await firstSecondPageRow.dblclick();
        assert.match(await page.locator("[data-modal-body]").innerText(), /row-021/);
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

test("production shell exposes screen address and restores it after Escape", async () => {
    const template = await readFile(resolve(root, "core/templates/terminal/tui_workbench.html"), "utf8");
    const html = template
        .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "")
        .replace(/<link\b[^>]*>/g, "")
        .replace(/{%[\s\S]*?%}/g, "")
        .replace(/{{[\s\S]*?}}/g, "test-user");
    const { browser, page } = await openHarness("https://app.test/", { html });
    try {
        const location = page.getByRole("textbox", { name: "TUI屏幕地址" });
        for (const width of [1440, 768, 390]) {
            await page.setViewportSize({ width, height: 1000 });
            assert.equal(await location.isVisible(), true);
            const box = await location.boundingBox();
            assert.ok(box.width > 100 && box.x >= 0 && box.x + box.width <= width);
        }
        await location.fill("screen:test.dashboard");
        await location.press("Enter");
        await page.waitForFunction(() => new URL(window.location.href).searchParams.get("screen") === "test.dashboard");
        assert.equal(await location.inputValue(), "screen:test.dashboard");
        await location.fill("screen:unfinished");
        await location.press("Escape");
        assert.equal(await location.inputValue(), "screen:test.dashboard");
    } finally {
        await browser.close();
    }
});

test("primary list selectors update the same panel without truncating requested rows", async () => {
    const filterScreen = structuredClone(dashboardScreen);
    filterScreen.actions = [action("test.list", { fields: [
        { key: "top_n", label: "展示数量", input_type: "select", value_type: "integer", default: 10, options: ["10", "20"], presentation_semantic: "primary_selector" },
        { key: "portfolio_id", label: "投资组合", input_type: "select", value_type: "integer", options: [{ value: "", label: "通用研究" }, { value: 7, label: "我的组合" }], presentation_semantic: "primary_selector" },
    ] })];
    filterScreen.screen.dashboard_panels = [{ key: "list", title: "候选清单", kind: "datagrid", action_key: "test.list", user_priority: "p0", presentation_semantic: "primary_list", filter_fields: ["portfolio_id", "top_n"], max_rows: 10 }];
    const { browser, page } = await openHarness("https://app.test/", { dashboardScreen: filterScreen });
    const received = [];
    try {
        await page.route("**/actions/test.list/run/", async (route) => {
            const params = route.request().postDataJSON().params;
            received.push(params);
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ view_model: {
                kind: "datagrid", columns: [{ key: "code", label: "证券代码" }],
                rows: Array.from({ length: params.top_n || 10 }, (_, i) => ({ code: `stock-${i}` })),
            } }) });
        });
        await page.locator("[data-current-location]").fill("screen:test.dashboard");
        await page.locator("[data-current-location]").press("Enter");
        const panel = page.locator('[data-dashboard-panel="list"]');
        await panel.getByText("实际展示 10 条").waitFor();
        await panel.getByLabel("展示数量").selectOption("20");
        await panel.getByLabel("投资组合").selectOption("7");
        await panel.getByRole("button", { name: "更新清单" }).click();
        await panel.getByText("实际展示 20 条").waitFor();
        assert.equal(await panel.locator("tbody tr").count(), 20);
        assert.deepEqual(received.at(-1), { top_n: 20, portfolio_id: 7 });
        assert.equal(await panel.getByLabel("投资组合").inputValue(), "7");
        assert.equal(await panel.getByLabel("展示数量").inputValue(), "20");
        for (const width of [390, 768, 1440]) {
            await page.setViewportSize({ width, height: 900 });
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        }
    } finally {
        await browser.close();
    }
});

test("collapsed support panels load once on expansion and remain open", async () => {
    const lazyScreen = structuredClone(dashboardScreen);
    lazyScreen.screen.dashboard_panels.find((panel) => panel.key === "admin-read").user_priority = "p2";
    const { browser, page, requestLog } = await openHarness("https://app.test/", { dashboardScreen: lazyScreen });
    const requestCount = () => requestLog.filter((line) => line.startsWith("REQ") && line.includes("/actions/test.admin-read/run/")).length;
    try {
        await page.locator("[data-current-location]").fill("screen:test.dashboard");
        await page.locator("[data-current-location]").press("Enter");
        await page.locator('[data-dashboard-panel="regime"] .q-marker').waitFor({ state: "visible" });
        await delay(150);
        assert.equal(requestCount(), 0);
        const panel = page.locator('[data-dashboard-panel="admin-read"]');
        assert.equal(await panel.locator('.tui-loading').count(), 0);
        assert.match(await panel.locator('[data-panel-idle]').textContent(), /展开后读取/);
        await Promise.all([
            page.waitForRequest(request => request.url().includes('/actions/test.admin-read/run/')),
            panel.locator("summary").click(),
        ]);
        await panel.locator(".tui-loading").waitFor({ state: "hidden" });
        assert.equal(requestCount(), 1);
        assert.equal(await panel.locator("details").getAttribute("open"), "");
        await panel.locator("summary").click();
        await panel.locator("summary").click();
        await delay(100);
        assert.equal(requestCount(), 1);
    } finally {
        await browser.close();
    }
});

test("leaving a dashboard aborts obsolete panel requests", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.route("**/actions/test.regime/run/", async (route) => {
            await delay(1500);
            await route.abort().catch(() => {});
        });
        const requested = page.waitForRequest((request) => request.url().includes("/actions/test.regime/run/"));
        await page.locator("[data-current-location]").fill("screen:test.dashboard");
        await page.locator("[data-current-location]").press("Enter");
        await requested;
        const aborted = page.waitForEvent("requestfailed", { predicate: (request) => request.url().includes("/actions/test.regime/run/") });
        await page.locator("[data-current-location]").fill("screen:test.grid");
        await page.locator("[data-current-location]").press("Enter");
        const failed = await aborted;
        assert.match(failed.failure().errorText, /ABORTED/);
        await page.locator("[data-main-panel] tbody tr").first().waitFor({ state: "visible" });
        assert.match(await page.locator("[data-current-location]").inputValue(), /^screen:test.grid(?: action:test.list)?$/);
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

test("dashboard action guidance renders once when panel note and action copy match", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.edit-dashboard",
        { waitForInitialRows: false },
    );
    try {
        const panel = page.locator('[data-dashboard-panel="edit-user"]');
        await panel.locator(".tui-entry-action").waitFor({ state: "visible" });
        const text = await panel.innerText();
        assert.equal((text.match(/填写用户 ID 和用户名后提交。/g) || []).length, 1);
        assert.equal(await panel.locator(".tui-dashboard-action-prompt p").count(), 0);
    } finally {
        await browser.close();
    }
});

test("shell pager is visible only for a paginated result", async () => {
    const { browser, page } = await openHarness();
    try {
        const pager = page.locator("[data-pager-status]");
        assert.equal(await pager.isHidden(), false);
        assert.match(await pager.innerText(), /页 1\/11 \| 205 行/);

        const location = page.locator("[data-current-location]");
        await location.fill("screen:test.dashboard");
        await location.press("Enter");
        await page.locator('[data-dashboard-panel="regime"] .q-marker').waitFor({ state: "visible" });
        assert.equal(await pager.isHidden(), true);
        assert.equal(await pager.textContent(), "");
    } finally {
        await browser.close();
    }
});

test("wide governance rows scroll horizontally without breaking dates or row actions", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.user-governance",
        { waitForInitialRows: false },
    );
    try {
        await page.setViewportSize({ width: 420, height: 720 });
        const tableScroll = page.locator('[data-dashboard-panel="users"] .tui-table-scroll');
        await tableScroll.waitFor({ state: "visible" });
        const dateCell = tableScroll.getByRole("cell", {
            name: "2026-08-28T09:30:00+08:00",
        });
        const rowActions = tableScroll.locator(".tui-row-actions");
        assert.equal(await rowActions.locator("button").count(), 5);
        const styles = await page.evaluate(() => {
            const scroll = document.querySelector('[data-dashboard-panel="users"] .tui-table-scroll');
            const date = Array.from(scroll.querySelectorAll("td")).find((cell) =>
                cell.textContent.includes("2026-08-28T09:30:00+08:00")
            );
            const actions = scroll.querySelector(".tui-row-actions");
            return {
                overflowX: getComputedStyle(scroll).overflowX,
                dateWhiteSpace: getComputedStyle(date).whiteSpace,
                actionWrap: getComputedStyle(actions).flexWrap,
                scrollWidth: scroll.scrollWidth,
                clientWidth: scroll.clientWidth,
            };
        });
        assert.equal(styles.overflowX, "auto");
        assert.equal(styles.dateWhiteSpace, "nowrap");
        assert.equal(styles.actionWrap, "nowrap");
        assert.ok(styles.scrollWidth > styles.clientWidth);
        assert.equal(await dateCell.count(), 1);
    } finally {
        await browser.close();
    }
});

test("regime dashboard shows four probabilities and keeps explicit percentages below one", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.dashboard",
        {
            waitForInitialRows: false,
            regimeConfidenceUnit: "percent",
            regimeFields: [
                { key: "current_regime", value: "复苏" },
                { key: "confidence", value: "0.5" },
                { key: "trend", value: "源观测 2026-10-01；数据基准日 2026-10-21" },
                { key: "warning", value: "无" },
            ],
            quadrantDistribution: [
                { regime: "Recovery", probability_percent: 0.5 },
                { regime: "Overheat", probability_percent: 49.5 },
                { regime: "Stagflation", probability_percent: 25 },
                { regime: "Deflation", probability_percent: 25 },
            ],
        },
    );
    try {
        const panel = page.locator('[data-dashboard-panel="regime"]');
        await panel.locator('[data-quadrant-probability="Recovery"]').waitFor();
        assert.equal(await panel.locator('[data-quadrant-probability]').count(), 4);
        assert.equal(await panel.locator('[data-quadrant-probability="Recovery"]').textContent(), "0.5%");
        assert.match(await panel.textContent(), /置信度:\s*0\.5%/);
        assert.match(await panel.textContent(), /源观测 2026-10-01/);
        assert.match(await panel.textContent(), /数据基准日 2026-10-21/);
        assert.match(await panel.textContent(), /通胀：左侧较低/);
        assert.equal(await panel.locator('.q-marker[aria-label="复苏象限"]').count(), 1);
        await page.setViewportSize({ width: 420, height: 720 });
        assert.equal(await panel.locator('[data-quadrant-probability="Recovery"]').isVisible(), true);
    } finally {
        await browser.close();
    }
});

test("portfolio summary respects explicit percentage field units", async () => {
    const summaryAction = action("test.dashboard-summary", {
        label: "组合摘要",
        view_type: "detail",
        screen_key: "test.dashboard",
    });
    const summaryScreen = structuredClone(dashboardScreen);
    summaryScreen.actions.push(summaryAction);
    summaryScreen.screen.dashboard_panels.push({
        key: "portfolio-summary",
        title: "组合摘要",
        kind: "detail",
        action_key: summaryAction.key,
        user_priority: "p1",
        presentation_semantic: "supporting_detail",
        field_rules: [
            { label: "环境 / 置信度", format: "percentage", percentage_unit: "fraction" },
            { label: "组合 / 总收益率", format: "percentage", percentage_unit: "percent" },
        ],
    });
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.dashboard",
        {
            waitForInitialRows: false,
            dashboardScreen: summaryScreen,
            dashboardSummaryAction: summaryAction,
            dashboardSummaryFields: [
                { label: "环境 / 置信度", value: "0.8" },
                { label: "组合 / 总收益率", value: 0.5 },
            ],
        },
    );
    try {
        const panel = page.locator('[data-dashboard-panel="portfolio-summary"]');
        await panel.getByText("80%", { exact: true }).waitFor();
        await panel.getByText("0.5%", { exact: true }).waitFor();
        assert.equal(await panel.getByText("80%", { exact: true }).count(), 1);
        assert.equal(await panel.getByText("0.5%", { exact: true }).count(), 1);
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
        await page.waitForFunction(() => document.querySelectorAll('[data-dashboard-row-action]').length === 5);
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

        const form = page.locator('form[data-action-ui-key="test.edit-row"]:visible');
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

test("public immersive row edit opens a prefilled modal without HTTP metadata", async () => {
    const config = structuredClone(editableDashboardScreen);
    config.screen.chrome_mode = "immersive";
    config.actions.forEach(item => { delete item.method; });
    const { browser, page } = await openHarness("https://app.test/?screen=test.edit-dashboard", {
        waitForInitialRows: false, editableDashboardScreen: config,
    });
    try {
        let writes = 0;
        page.on("request", request => { if (request.url().includes("/actions/test.edit-row/run/")) writes++; });
        await page.locator('[data-dashboard-row-action][aria-label="编辑 pending-user"]').click();
        const form = page.locator('form[data-action-ui-key="test.edit-row"]:visible');
        await form.waitFor();
        assert.equal(await form.locator('[name="username"]').inputValue(), "pending-user");
        assert.equal(writes, 0);
    } finally { await browser.close(); }
});

test("advanced action referenced by a dashboard panel remains reachable", async () => {
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

        const open = page.locator('[data-dashboard-panel="edit-user"] .tui-entry-action');
        await open.waitFor({ state: "visible" });
        await open.click();

        const form = page.locator('form[data-action-ui-key="test.edit-row"]');
        await form.waitFor({ state: "visible" });
        assert.equal(updateRequests, 0);
        assert.equal(
            await form.locator('[name="user_id"]').evaluate((element) => element === document.activeElement),
            true,
        );
        assert.match(await page.locator("[data-workbench-status]").innerText(), /编辑用户/);
    } finally {
        await browser.close();
    }
});

test("required read action referenced by a dashboard panel waits for form input", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.edit-dashboard",
        { waitForInitialRows: false },
    );
    try {
        let lookupRequests = 0;
        page.on("request", (request) => {
            if (request.url().includes("/actions/test.lookup-user/run/")) {
                lookupRequests += 1;
            }
        });

        const open = page.locator('[data-dashboard-panel="lookup-user"] .tui-entry-action');
        await open.waitFor({ state: "visible" });
        await open.click();

        const form = page.locator('form[data-action-ui-key="test.lookup-user"]');
        await form.waitFor({ state: "visible" });
        assert.equal(lookupRequests, 0);
        assert.equal(
            await form.locator('[name="user_id"]').evaluate((element) => element === document.activeElement),
            true,
        );
        assert.match(await page.locator("[data-workbench-status]").innerText(), /查询用户/);
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


test("audit unsafe defaults only reveal a form on navigation and refresh", async () => {
    const unsafe = structuredClone(screen);
    unsafe.screen.default_action_key = 'test.ai-default';
    unsafe.actions = [action('test.ai-default', { method: 'POST', risk: 'ai', task_tier: 'primary', fields: [{ key: 'message', label: '问题', input_type: 'textarea', required: true, default: '分析账户' }] })];
    const { browser, page, requestLog } = await openHarness('https://app.test/?screen=test.grid', { screen: unsafe, waitForInitialRows: false });
    try {
        const input = page.locator('[data-main-panel] form[data-action-ui-key="test.ai-default"] textarea');
        await input.waitFor({ state: 'visible' });
        assert.equal(await input.inputValue(), '分析账户');
        await page.keyboard.press('F5');
        await delay(200);
        assert.equal(requestLog.filter(item => item.startsWith('REQ') && item.includes('/actions/test.ai-default/run/')).length, 0);
    } finally { await browser.close(); }
});

test("audit access package stays masked until explicitly revealed", async () => {
    const { browser, page } = await openHarness();
    try {
        await page.route('**/actions/test.list/run/', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ action: actions[0], view_model: { kind: 'detail', title: '接入包', status: '已读取', fields: [{ key: 'package', label: '完整接入包', presentation: 'secret', value: 'test-only-credential\nhttps://example.test' }] } }) }));
        await page.keyboard.press('F5');
        await page.locator('[data-secret-toggle]').waitFor();
        assert.doesNotMatch(await page.locator('[data-secret-value]').innerText(), /test-only-credential/);
        await page.locator('[data-secret-toggle]').click();
        assert.match(await page.locator('[data-secret-value]').innerText(), /test-only-credential/);
        await page.locator('[data-secret-toggle]').click();
        assert.doesNotMatch(await page.locator('[data-secret-value]').innerText(), /test-only-credential/);
    } finally { await browser.close(); }
});


test("audit wide tables retain columns and conditional row tasks in the full list", async () => {
    const spec = structuredClone(dashboardScreen);
    spec.actions = [action("test.list"), actions.find(item => item.key === "test.admin-read")];
    spec.screen.dashboard_panels = [
        { key: 'receipt', title: '操作回执', kind: 'detail', user_priority: 'p2', presentation_semantic: 'supporting_detail' },
        { key: 'queue', title: '审核队列', kind: 'datagrid', action_key: 'test.list', user_priority: 'p0', presentation_semantic: 'primary_list', max_rows: 8, columns: [{ key: 'code', label: '对象' }, { key: 'missing_state', label: '审核状态' }], row_actions: [{ action_key: 'test.admin-read', label_template: '查看 {code}', param_map: {}, result_panel_key: 'receipt', visible_when: { field: 'code', values: ['row-001'] } }] },
    ];
    const queueSpec = spec.screen.dashboard_panels[1];
    queueSpec.row_actions.push({ ...queueSpec.row_actions[0], label_template: '再次查看 {code}' });
    const { browser, page } = await openHarness('https://app.test/?screen=test.dashboard', { dashboardScreen: spec, waitForInitialRows: false });
    try {
        const queue = page.locator('[data-dashboard-panel="queue"]');
        await queue.locator('tbody tr').first().waitFor();
        assert.equal(await queue.locator('[data-dashboard-row-action]').count(), 2);
        assert.match(await queue.locator('thead').innerText(), /审核状态/);
        const more = queue.locator('.tui-row-action-menu summary');
        const moreBounds = await more.boundingBox();
        const tableBounds = await queue.locator('.tui-table-scroll').boundingBox();
        assert.ok(moreBounds.x + moreBounds.width <= tableBounds.x + tableBounds.width + 1);
        await more.click();
        await more.click();
        for (const width of [1280, 1440]) {
            await page.setViewportSize({ width, height: 1000 });
            assert.ok((await queue.boundingBox()).width > 600);
            assert.ok((await page.locator('[data-dashboard-panel="receipt"]').boundingBox()).height < 110);
        }
        await queue.locator('[data-panel-full-list]').click();
        assert.equal(await page.locator('[data-dashboard-row-action]').count(), 2);
        await page.locator('[data-dashboard-row-action]').first().click();
        await page.locator('[data-dashboard-panel]').first().waitFor();
        assert.equal(await page.locator('[data-dashboard-panel="receipt"] details').getAttribute('open'), '');
    } finally { await browser.close(); }
});

test("server experience renders a quiet task landing with three permission-filtered entries", async () => {
    const { browser, page, requestLog } = await openHarness("https://app.test/", {
        catalog: experienceCatalog,
        waitForInitialRows: false,
    });
    try {
        await page.locator("[data-task-home]").waitFor({ state: "attached" });
        if (await page.locator("[data-task-home]").count() === 0) {
            throw new Error(`experience landing missing; status=${await page.locator("[data-workbench-status]").innerText()} main=${await page.locator("[data-main-panel]").innerText()}`);
        }
        assert.equal(await page.locator("[data-experience-entry]").count(), 3);
        assert.deepEqual(await page.locator("[data-experience-entry] strong").allTextContents(), [
            "今日关注",
            "研究标的",
            "检查组合",
        ]);
        assert.equal(await page.locator("[data-dashboard-panel]").count(), 0);
        assert.equal(new URL(page.url()).search, "");
        assert.equal(requestLog.some((item) => item.includes("/actions/")), false);
    } finally {
        await browser.close();
    }
});

test("experience mode switch only changes navigation and preserves URL, result DOM and requests", async () => {
    const { browser, page, requestLog } = await openHarness("https://app.test/", {
        catalog: experienceCatalog,
        waitForInitialRows: false,
    });
    try {
        await page.locator("[data-task-home]").waitFor({ state: "attached" });
        const beforeRequests = requestLog.length;
        const beforeUrl = page.url();
        const beforeStatus = await page.locator("[data-workbench-status]").innerText();
        await page.locator('[data-experience-mode="professional"]').click();
        await page.locator('[data-experience-mode="professional"]').waitFor({ state: "visible" });
        assert.equal(await page.locator('[data-experience-mode="professional"]').getAttribute("aria-selected"), "true");
        assert.equal(await page.locator("[data-experience-entry]").count(), 0);
        assert.ok((await page.locator('[data-module-tree] [data-screen-key]').count()) >= 4);
        assert.equal(page.url(), beforeUrl);
        assert.equal(requestLog.length, beforeRequests);
        assert.equal(await page.locator("[data-workbench-status]").innerText(), beforeStatus);
        await page.locator('[data-experience-mode="task"]').focus();
        await page.locator('[data-experience-mode="task"]').press("ArrowRight");
        assert.equal(await page.locator('[data-experience-mode="professional"]').getAttribute("aria-selected"), "true");
        await page.locator('[data-experience-mode="task"]').click();
        assert.equal(await page.locator("[data-experience-entry]").count(), 3);
        assert.equal(page.url(), beforeUrl);
        assert.equal(requestLog.length, beforeRequests);
    } finally {
        await browser.close();
    }
});

test("explicit Today entry exits the quiet landing and loads its dashboard", async () => {
    const { browser, page } = await openHarness("https://app.test/", {
        catalog: experienceCatalog,
        waitForInitialRows: false,
    });
    try {
        await page.locator('[data-experience-entry="today"]').waitFor({ state: "attached" });
        await page.locator('[data-experience-entry="today"]').click();
        await page.locator('[data-dashboard-panel="regime"]').waitFor();
        assert.match(new URL(page.url()).search, /screen=test\.dashboard/);
        assert.ok(await page.locator("[data-dashboard-panel]").count() > 0);
        await page.goBack();
        await page.locator("[data-task-home]").waitFor();
        assert.equal(new URL(page.url()).search, "");
        assert.equal(await page.locator("[data-dashboard-panel]").count(), 0);
        await page.goForward();
        await page.locator('[data-dashboard-panel="regime"]').waitFor();
        assert.match(new URL(page.url()).search, /screen=test\.dashboard/);
        await page.locator('[data-experience-mode="professional"]').click();
        await page.locator('[data-experience-home]').click();
        await page.locator('[data-experience-entry="today"]').waitFor();
        assert.equal(await page.locator('[data-dashboard-panel]').count(), 0);
        assert.equal(new URL(page.url()).search, "");
        assert.equal(await page.locator('[data-experience-mode="task"]').getAttribute('aria-selected'), 'true');
    } finally {
        await browser.close();
    }
});

test("quiet task landing preserves full home portfolio and row filters", async () => {
    const filterScreen = structuredClone(dashboardScreen);
    filterScreen.actions = [action("test.list", { fields: [
        { key: "top_n", label: "展示数量", input_type: "select", value_type: "integer", default: 10, options: ["10", "20"], presentation_semantic: "primary_selector" },
        { key: "portfolio_id", label: "投资组合", input_type: "select", value_type: "integer", options: [{ value: "", label: "通用研究" }, { value: 7, label: "我的组合" }], presentation_semantic: "primary_selector" },
    ] })];
    filterScreen.screen.dashboard_panels = [{ key: "list", title: "候选清单", kind: "datagrid", action_key: "test.list", user_priority: "p0", presentation_semantic: "primary_list", filter_fields: ["portfolio_id", "top_n"], max_rows: 10 }];
    const { browser, page } = await openHarness("https://app.test/", {
        catalog: experienceCatalog, dashboardScreen: filterScreen, waitForInitialRows: false,
    });
    try {
        await page.route("**/actions/test.list/run/", async route => {
            const params = route.request().postDataJSON().params;
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ view_model: {
                kind: "datagrid", columns: [{ key: "code", label: "证券代码" }],
                rows: Array.from({ length: params.top_n || 10 }, (_, i) => ({ code: `stock-${i}` })),
            } }) });
        });
        await page.locator('[data-experience-entry="today"]').click();
        const panel = page.locator('[data-dashboard-panel="list"]');
        await panel.getByText("实际展示 10 条").waitFor();
        await panel.getByLabel("展示数量").selectOption("20");
        await panel.getByLabel("投资组合").selectOption("7");
        await panel.getByRole("button", { name: "更新清单" }).click();
        await panel.getByText("实际展示 20 条").waitFor();
        await page.locator('[data-experience-home]').click();
        await page.locator('[data-experience-entry="today"]').waitFor();
        assert.equal(await page.locator('[data-dashboard-panel]').count(), 0);
        await page.locator('[data-experience-entry="today"]').click();
        await panel.getByLabel("展示数量").waitFor();
        assert.equal(await panel.getByLabel("展示数量").inputValue(), "20");
        assert.equal(await panel.getByLabel("投资组合").inputValue(), "7");
        await panel.getByText("实际展示 20 条").waitFor();
    } finally { await browser.close(); }
});

test("legacy catalogs retain professional navigation and hide experience controls", async () => {
    const { browser, page } = await openHarness("https://app.test/", { waitForInitialRows: false });
    try {
        await page.locator('[data-screen-key="test.grid"]').waitFor();
        assert.equal(await page.locator("[data-experience-controls]").isHidden(), true);
        assert.equal(await page.locator('[data-experience-mode="task"]').count(), 1);
        assert.equal(await page.locator('[data-experience-mode="task"]').isHidden(), true);
    } finally {
        await browser.close();
    }
});

test("raw response control stays hidden without server diagnostic authority", async () => {
    const { browser, page } = await openHarness("https://app.test/", {
        catalog: experienceCatalog,
        waitForInitialRows: false,
    });
    try {
        await page.locator("[data-task-home]").waitFor({ state: "attached" });
        assert.equal(await page.locator("[data-raw-toggle]").isHidden(), true);
        await page.locator('[data-menu-command="view"]').click();
        assert.equal(await page.locator('[data-menu-popover] [data-menu-action="raw"]').count(), 0);
    } finally {
        await browser.close();
    }
});


test("task landing reload and per-user mode preference retain routing intent", async () => {
    const { browser, page, requestLog } = await openHarness("https://app.test/", {
        catalog: experienceCatalog, waitForInitialRows: false,
    });
    try {
        await page.locator('[data-experience-entry="today"]').waitFor();
        const reloadShell = async (userKey = "test-user") => {
            await page.reload();
            await page.locator('[data-tui-app]').evaluate((node, key) => node.dataset.userKey = key, userKey);
            await page.addStyleTag({ path: cssPath });
            await page.addScriptTag({ path: bundlePath });
            await page.locator('[data-task-home]').waitFor();
        };
        await reloadShell();
        assert.equal(await page.locator('[data-dashboard-panel]').count(), 0);
        assert.equal(new URL(page.url()).search, "");
        assert.equal(requestLog.some(line => line.includes('/actions/')), false);
        await page.locator('[data-experience-mode="professional"]').click();
        assert.equal(await page.evaluate(() => localStorage.getItem('agom-tui-experience-mode:v1:user:test-user')), 'professional');
        await reloadShell("another-user");
        assert.equal(await page.locator('[data-experience-mode="task"]').getAttribute('aria-selected'), 'true');
        assert.equal(await page.evaluate(() => localStorage.getItem('agom-tui-experience-mode:v1:user:test-user')), 'professional');
        assert.equal(await page.locator('[data-dashboard-panel]').count(), 0);
    } finally { await browser.close(); }
});

test("mode changes preserve partial result and nullable counts while denied diagnostics close", async () => {
    const { browser, page, requestLog, browserErrors } = await openHarness("https://app.test/", {
        catalog: { ...experienceCatalog, diagnostics: { raw_response_allowed: true } },
        waitForInitialRows: false,
    });
    try {
        await page.locator('[data-experience-entry="research"]').waitFor();
        let permitted = true;
        await page.route('**/actions/test.list/run/', async route => {
            const owner = { outcome: 'partial', success: true, requested: 2, succeeded: 1, failed: 1, stored: null, counts_unavailable: true, confirmed_trade_count: 2 };
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
                action: actions.find(item => item.key === 'test.list'),
                response: { status_code: 200 },
                outcome: owner.outcome,
                view_model: { kind: 'detail', title: '部分完成', status: '部分失败', fields: [
                    { label: '已确认成交', value: 2, presentation: 'metadata' },
                    { label: '写入数量', value: '未知', presentation: 'metadata' },
                ] },
                debug: { raw_available: permitted, raw_response: permitted ? owner : null },
            }) });
        });
        await page.locator('[data-experience-entry="research"]').click();
        await page.locator('[data-raw-toggle]').waitFor({ state: 'visible' }).catch(async error => {
            throw new Error(`${error.message} STATUS=${await page.locator('[data-workbench-status]').innerText()} MAIN=${await page.locator('[data-main-panel]').innerText()} REQUESTS=${JSON.stringify(requestLog)} ERRORS=${JSON.stringify(browserErrors)}`);
        });
        await page.locator('[data-raw-toggle]').click();
        const raw = page.locator('[data-raw-panel]');
        assert.equal(JSON.parse(await raw.textContent()).stored, null);
        assert.equal(JSON.parse(await raw.textContent()).confirmed_trade_count, 2);
        const before = { requests: requestLog.length, url: page.url(), text: await page.locator('[data-main-panel]').innerText(), status: await page.locator('[data-workbench-status]').innerText() };
        await page.locator('[data-experience-mode="professional"]').click();
        await page.locator('[data-experience-mode="task"]').click();
        assert.equal(requestLog.length, before.requests);
        assert.equal(page.url(), before.url);
        assert.equal(await page.locator('[data-main-panel]').innerText(), before.text);
        assert.equal(await page.locator('[data-workbench-status]').innerText(), before.status);
        assert.equal(JSON.parse(await raw.textContent()).counts_unavailable, true);
        permitted = false;
        await page.locator('[data-raw-close]').click();
        await delay(500);
        await page.locator('form[data-action-ui-key="test.list"] .tui-action-button').click();
        await page.waitForFunction(() => document.querySelector('[data-raw-toggle]').hidden);
        assert.equal(await page.locator('[data-raw-drawer]').isHidden(), true);
        assert.doesNotMatch(await raw.textContent(), /confirmed_trade_count/);
    } finally { await browser.close(); }
});

function makeKeyboardEntryScreen() {
    const entryAction = action("test.detail", {
        label: "读取示例记录",
        task_tier: "primary",
        fields: [{ key: "code", label: "代码", input_type: "text", required: true }],
    });
    return {
        ...screen,
        screen: {
            ...screen.screen,
            default_action_key: entryAction.key,
            entry_state: {
                mode: "parameter_gate",
                field_key: "code",
                empty_copy: "填写示例代码后读取。",
            },
        },
        actions: [entryAction],
    };
}

function makeNonPassiveKeyboardEntryScreen() {
    const entryAction = action("test.edit", {
        label: "提交示例变更",
        method: "POST",
        risk: "write",
        task_tier: "primary",
        confirmation_required: true,
        fields: [{ key: "code", label: "代码", input_type: "text", required: true }],
    });
    return {
        ...screen,
        screen: {
            ...screen.screen,
            default_action_key: entryAction.key,
            entry_state: {
                mode: "parameter_gate",
                field_key: "code",
                empty_copy: "填写示例代码后提交。",
            },
        },
        actions: [entryAction],
    };
}

function makeTargetKeyboardDashboardScreen() {
    const targetAction = action("test.regime", {
        label: "读取目标面板",
        task_tier: "primary",
        screen_key: "test.dashboard",
        fields: [{ key: "code", label: "代码", input_type: "text", required: true }],
    });
    return {
        ...structuredClone(dashboardScreen),
        screen: {
            ...structuredClone(dashboardScreen.screen),
            dashboard_panels: [{
                key: "target",
                title: "目标面板",
                kind: "detail",
                user_priority: "p0",
                presentation_semantic: "primary_status",
                action_key: targetAction.key,
            }],
        },
        actions: [targetAction],
    };
}

const keyboardHarnessHtml = harnessHtml
    .replace('<div data-tui-app data-user-key="test-user">', '<div class="tui-app" data-tui-app data-user-key="test-user">')
    .replace('<aside data-rail-panel>', '<aside class="tui-rail tui-module-rail" data-rail-panel>')
    .replace('<div class="tui-workspace-grid">', '<main class="tui-shell"><section class="tui-workspace"><div class="tui-workspace-grid">')
    .replace('<section class="tui-panel"><div class="tui-panel-body" data-actions-panel></div></section>', '<section class="tui-panel tui-actions-panel"><div class="tui-panel-body" data-actions-panel></div></section>')
    .replace('<section><span data-screen-title>', '<section class="tui-panel tui-main-panel"><span data-screen-title>')
    .replace('<section class="tui-panel" data-inspector-panel-shell>', '<section class="tui-panel tui-inspector-panel" data-inspector-panel-shell>')
    .replace('  </div>\n  <button data-raw-toggle>', '  </div></section></main>\n  <button data-raw-toggle>');

test("F6 uses the focused visible professional form and preserves its typed value", async () => {
    const { browser, page, requestLog } = await openHarness(
        "https://app.test/?screen=test.grid",
        { catalog: experienceCatalog, screen: makeKeyboardEntryScreen(), html: keyboardHarnessHtml, waitForInitialRows: false },
    );
    try {
        await page.setViewportSize({ width: 1440, height: 1000 });
        await page.locator('[data-experience-mode="task"]').waitFor();
        await page.locator('[data-experience-mode="professional"]').click();
        assert.equal(await page.locator(".tui-rail").isVisible(), true);
        assert.equal(await page.locator(".tui-actions-panel").isVisible(), true);
        assert.equal(await page.locator(".tui-inspector-panel").isVisible(), true);
        const mainForm = page.locator('[data-main-panel] form[data-action-ui-key="test.detail"]');
        const professionalForm = page.locator('[data-actions-panel] form[data-action-ui-key="test.detail"]');
        await mainForm.waitFor({ state: "visible" });
        await professionalForm.waitFor({ state: "visible" });
        await mainForm.locator('[name="code"]').fill("main-old-value");
        await professionalForm.locator('[name="code"]').fill("professional-current-value");
        await professionalForm.locator('[name="code"]').focus();
        const request = page.waitForRequest("**/actions/test.detail/run/");
        await page.keyboard.press("F6");
        const sent = await request;
        assert.equal(sent.postDataJSON().params.code, "professional-current-value");
        assert.equal(requestLog.filter((line) => line.includes("/actions/test.detail/run/") && line.startsWith("REQ")).length, 1);
    } finally { await browser.close(); }
});

for (const firstOutcome of ["failed", "partial"]) {
    test(`F6 task entry keeps a typed code after a ${firstOutcome} result`, async () => {
        const { browser, page } = await openHarness(
            "https://app.test/?screen=test.grid",
            { catalog: experienceCatalog, screen: makeKeyboardEntryScreen(), html: keyboardHarnessHtml, waitForInitialRows: false },
        );
        let attempts = 0;
        try {
            await page.route("**/actions/test.detail/run/", async (route) => {
                attempts += 1;
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify(attempts === 1 ? {
                        action: actions.find((item) => item.key === "test.detail"),
                        outcome: firstOutcome,
                        response: { status_code: firstOutcome === "partial" ? 200 : 503 },
                        view_model: {
                            kind: "datagrid",
                            title: "示例结果",
                            status: firstOutcome === "partial" ? "部分返回" : "失败",
                            columns: [{ key: "code", label: "代码" }],
                            rows: [{ code: "row-context-old" }],
                        },
                        debug: { raw_available: false, raw_response: null },
                    } : {
                        action: actions.find((item) => item.key === "test.detail"),
                        outcome: "success",
                        response: { status_code: 200 },
                        view_model: { kind: "detail", title: "读取完成", status: "完成", fields: [{ label: "代码", value: "typed-new-value" }] },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
            });
            const entry = page.locator('[data-main-panel] form.tui-action-entry-form');
            await entry.waitFor({ state: "visible" });
            await entry.locator('[name="code"]').fill("typed-first-value");
            await entry.locator(".tui-entry-submit").click();
            await page.locator("[data-research-again-entry]").waitFor();
            const reentry = page.locator("[data-research-again-entry] form.tui-action-entry-form");
            await page.keyboard.press("F9");
            await reentry.waitFor({ state: "visible" });
            await reentry.locator('[name="code"]').fill("typed-new-value");
            await delay(300); // Respect the existing 250ms same-action trigger guard.
            const retry = page.waitForRequest("**/actions/test.detail/run/");
            await page.keyboard.press("F6");
            const request = await retry;
            assert.equal(request.postDataJSON().params.code, "typed-new-value");
            assert.equal(attempts, 2);
        } finally { await browser.close(); }
    });
}

test("task F6 re-reads the default primary entry after a successful result", async () => {
    const { browser, page } = await openHarness(
        "https://app.test/?screen=test.grid",
        { catalog: experienceCatalog, screen: makeKeyboardEntryScreen(), html: keyboardHarnessHtml, waitForInitialRows: false },
    );
    let attempts = 0;
    try {
        await page.route("**/actions/test.detail/run/", async (route) => {
            attempts += 1;
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.detail"),
                    outcome: "success",
                    response: { status_code: 200 },
                    view_model: {
                        kind: "detail",
                        title: "读取完成",
                        status: "完成",
                        fields: [{ label: "代码", value: attempts === 1 ? "first-value" : "second-value" }],
                    },
                    debug: { raw_available: false, raw_response: null },
                }),
            });
        });
        const entry = page.locator('[data-main-panel] form.tui-action-entry-form');
        await entry.waitFor({ state: "visible" });
        await entry.locator('[name="code"]').fill("first-value");
        await entry.locator(".tui-entry-submit").click();
        await page.locator("[data-research-again-entry]").waitFor();
        const reentry = page.locator("[data-research-again-entry] form.tui-action-entry-form");
        await page.keyboard.press("F9");
        await reentry.waitFor({ state: "visible" });
        await reentry.locator('[name="code"]').fill("second-value");
        await delay(300); // This is an intentional second submission, not a duplicate keypress.
        const request = page.waitForRequest("**/actions/test.detail/run/");
        await page.keyboard.press("F6");
        const sent = await request;
        assert.equal(sent.postDataJSON().params.code, "second-value");
        assert.equal(attempts, 2);
    } finally { await browser.close(); }
});

for (const firstOutcome of ["success", "failed"]) {
    test(`F6 keeps a closed ${firstOutcome} reentry closed until F9 reveals it`, async () => {
        const { browser, page, requestLog } = await openHarness(
            "https://app.test/?screen=test.grid",
            { catalog: experienceCatalog, screen: makeKeyboardEntryScreen(), html: keyboardHarnessHtml, waitForInitialRows: false },
        );
        let attempts = 0;
        try {
            await page.route("**/actions/test.detail/run/", async (route) => {
                attempts += 1;
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        action: actions.find((item) => item.key === "test.detail"),
                        outcome: firstOutcome,
                        response: { status_code: firstOutcome === "failed" ? 503 : 200 },
                        view_model: {
                            kind: "detail",
                            title: "示例读取结果",
                            status: firstOutcome === "failed" ? "失败" : "完成",
                            fields: [{ label: "代码", value: "first-value" }],
                        },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
            });
            const entry = page.locator('[data-main-panel] form.tui-action-entry-form');
            await entry.waitFor({ state: "visible" });
            await entry.locator('[name="code"]').fill("first-value");
            await entry.locator(".tui-entry-submit").click();
            const reentry = page.locator("[data-research-again-entry]");
            await reentry.waitFor();
            const expectedStatus = firstOutcome === "failed"
                ? "读取失败，请检查结果后重试"
                : "读取完成";
            await page.waitForFunction(
                (value) => document.querySelector("[data-workbench-status]")?.textContent === value,
                expectedStatus,
            );
            assert.equal(await reentry.evaluate((element) => element.open), false);
            const requestCount = () => requestLog.filter(
                (line) => line.includes("/actions/test.detail/run/") && line.startsWith("REQ"),
            ).length;
            assert.equal(attempts, 1);
            await page.keyboard.press("F6");
            await delay(75);
            assert.equal(attempts, 1);
            assert.equal(requestCount(), 1);
            assert.equal(await reentry.evaluate((element) => element.open), false);
            assert.match(await page.locator("[data-workbench-status]").innerText(), /暂不可见|展开任务入口/);

            await page.keyboard.press("F9");
            await reentry.waitFor({ state: "visible" });
            assert.equal(await reentry.evaluate((element) => element.open), true);
            await page.waitForFunction(() => Boolean(
                document.activeElement?.closest?.("[data-research-again-entry] form.tui-action-entry-form"),
            ));
            await reentry.locator('[name="code"]').fill("typed-after-reveal");
            await delay(300); // Keep the transport duplicate guard unchanged.
            const secondRequest = page.waitForRequest("**/actions/test.detail/run/");
            await page.keyboard.press("F6");
            assert.equal((await secondRequest).postDataJSON().params.code, "typed-after-reveal");
            assert.equal(attempts, 2);
            assert.equal(requestCount(), 2);
        } finally { await browser.close(); }
    });
}

test("folded or hidden task entry keeps F2/F10 away from the form", async () => {
    const { browser, page, requestLog } = await openHarness(
        "https://app.test/?screen=test.grid",
        { catalog: experienceCatalog, screen: makeKeyboardEntryScreen(), html: keyboardHarnessHtml, waitForInitialRows: false },
    );
    try {
        await page.route("**/actions/test.detail/run/", async (route) => {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: actions.find((item) => item.key === "test.detail"),
                    outcome: "success",
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "完成", status: "完成", fields: [] },
                    debug: { raw_available: false, raw_response: null },
                }),
            });
        });
        const entry = page.locator('[data-main-panel] form.tui-action-entry-form');
        await entry.waitFor({ state: "visible" });
        await entry.locator('[name="code"]').fill("folded-code");
        await entry.locator(".tui-entry-submit").click();
        const reentry = page.locator("[data-research-again-entry]");
        await reentry.waitFor();
        const taskMode = page.locator('[data-experience-mode="task"]');
        const requestCount = () => requestLog.filter(
            (line) => line.includes("/actions/test.detail/run/") && line.startsWith("REQ"),
        ).length;
        for (const hidden of [false, true]) {
            await reentry.evaluate((element, shouldHide) => { element.hidden = shouldHide; }, hidden);
            await taskMode.focus();
            await page.keyboard.press("F2");
            await page.keyboard.press("F10");
            assert.equal(await reentry.evaluate((element) => element.open), false);
            assert.equal(await taskMode.evaluate((element) => element === document.activeElement), true);
            assert.equal(requestCount(), 1);
        }
        assert.match(await page.locator("[data-workbench-status]").innerText(), /任务入口/);
    } finally { await browser.close(); }
});

test("task and professional F6 do not bypass completed non-passive primary work", async () => {
    const nonPassiveScreen = makeNonPassiveKeyboardEntryScreen();
    nonPassiveScreen.actions = [
        ...nonPassiveScreen.actions,
        action("test.other-primary", {
            label: "另一个主任务",
            task_tier: "primary",
            sequence: 2,
        }),
    ];
    const { browser, page, requestLog } = await openHarness(
        "https://app.test/?screen=test.grid",
        { catalog: experienceCatalog, screen: nonPassiveScreen, html: keyboardHarnessHtml, waitForInitialRows: false },
    );
    try {
        let otherRequests = 0;
        await page.route("**/actions/test.edit/run/", async (route) => {
            const body = route.request().postDataJSON();
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify(body.confirmed ? {
                    action: actions.find((item) => item.key === "test.edit"),
                    outcome: "success",
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "提交完成", status: "完成", fields: [{ label: "代码", value: "write-code" }] },
                    debug: { raw_available: false, raw_response: null },
                } : {
                    action: actions.find((item) => item.key === "test.edit"),
                    confirmation_required: true,
                    confirmation: { title: "确认提交", message: "示例写入需要明确确认。", confirm_label: "确认执行", cancel_label: "取消" },
                    response: { status_code: 409 },
                    view_model: { kind: "message", title: "等待确认", status: "待确认" },
                    debug: { raw_available: false, raw_response: null },
                }),
            });
        });
        await page.route("**/actions/test.other-primary/run/", async (route) => {
            otherRequests += 1;
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
                action: nonPassiveScreen.actions.find((item) => item.key === "test.other-primary"),
                outcome: "success",
                response: { status_code: 200 },
                view_model: { kind: "detail", title: "不应执行", status: "错误" },
            }) });
        });
        const entry = page.locator('[data-main-panel] form.tui-action-entry-form');
        await entry.waitFor({ state: "visible" });
        await entry.locator('[name="code"]').fill("write-code");
        await page.keyboard.press("F6");
        await page.locator("[data-confirm-action]").click();
        await page.waitForFunction(() => document.querySelector("[data-workbench-status]")?.textContent === "操作完成");
        const requestCount = () => requestLog.filter(
            (line) => line.includes("/actions/test.edit/run/") && line.startsWith("REQ"),
        ).length;
        assert.equal(requestCount(), 2);
        await page.keyboard.press("F6");
        assert.equal(requestCount(), 2);
        assert.equal(otherRequests, 0);
        await page.locator('[data-experience-mode="professional"]').click();
        await page.keyboard.press("F9");
        const completedForm = page.locator('[data-actions-panel] form[data-action-ui-key="test.edit"]');
        await completedForm.locator(".tui-action-submit").focus();
        await page.keyboard.press("F6");
        await delay(100);
        assert.equal(requestCount(), 2);
        assert.equal(otherRequests, 0);
        assert.match(await page.locator("[data-workbench-status]").innerText(), /本任务已完成/);
    } finally { await browser.close(); }
});

test("F6 uses the visible professional form when focus is outside all action forms", async () => {
        const { browser, page } = await openHarness(
            "https://app.test/?screen=test.grid",
            { catalog: experienceCatalog, screen: makeKeyboardEntryScreen(), html: keyboardHarnessHtml, waitForInitialRows: false },
    );
    try {
        await page.setViewportSize({ width: 1440, height: 1000 });
        await page.locator('[data-experience-mode="professional"]').click();
        assert.equal(await page.locator(".tui-rail").isVisible(), true);
        assert.equal(await page.locator(".tui-actions-panel").isVisible(), true);
        assert.equal(await page.locator(".tui-inspector-panel").isVisible(), true);
        const mainForm = page.locator('[data-main-panel] form[data-action-ui-key="test.detail"]');
        const professionalForm = page.locator('[data-actions-panel] form[data-action-ui-key="test.detail"]');
        await mainForm.waitFor({ state: "visible" });
        await professionalForm.waitFor({ state: "visible" });
        await mainForm.locator('[name="code"]').fill("main-stale-value");
        await professionalForm.locator('[name="code"]').fill("sidebar-current-value");
        await page.locator("[data-current-location]").click();
        const request = page.waitForRequest("**/actions/test.detail/run/");
        await page.keyboard.press("F6");
        const sent = await request;
        assert.equal(sent.postDataJSON().params.code, "sidebar-current-value");
    } finally { await browser.close(); }
});

test("F6 preserves an explicitly unchecked row checkbox and typed text", async () => {
    const checkboxAction = action("test.checkbox-read", {
        label: "读取带开关的合成记录",
        task_tier: "primary",
        sequence: 2,
        fields: [
            { key: "code", label: "代码", input_type: "text", required: true },
            {
                key: "value",
                label: "采用行值",
                input_type: "checkbox",
                value_type: "boolean",
                default: true,
            },
        ],
    });
    const selectedScreen = structuredClone(screen);
    selectedScreen.actions = [
        action("test.list", { view_type: "datagrid", task_tier: "primary", sequence: 1 }),
        checkboxAction,
    ];
    const { browser, page, requestLog } = await openHarness("https://app.test/?screen=test.grid", {
        catalog: experienceCatalog,
        screen: selectedScreen,
        html: keyboardHarnessHtml,
    });
    try {
        await page.locator('[data-experience-mode="professional"]').click();
        await page.locator('[data-row-index="0"]').click();
        const form = page.locator('[data-actions-panel] form[data-action-ui-key="test.checkbox-read"]');
        await form.waitFor({ state: "visible" });
        await form.locator('[name="value"]').check();
        await form.locator('[name="value"]').uncheck();
        await form.locator('[name="code"]').fill("typed-checkbox-code");
        await page.route("**/actions/test.checkbox-read/run/", async (route) => {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: checkboxAction,
                    outcome: "success",
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "合成读取完成", status: "完成", fields: [] },
                    debug: { raw_available: false, raw_response: null },
                }),
            });
        });
        const request = page.waitForRequest("**/actions/test.checkbox-read/run/");
        await page.keyboard.press("F6");
        const sent = await request;
        assert.deepEqual(sent.postDataJSON().params, {
            code: "typed-checkbox-code",
            value: false,
        });
        assert.equal(
            requestLog.filter((line) => line.includes("/actions/test.checkbox-read/run/") && line.startsWith("REQ")).length,
            1,
        );
    } finally { await browser.close(); }
});

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    test(`task keyboard focus stays visible through result reentry at ${viewport.width}px`, async () => {
        const { browser, page, requestLog } = await openHarness(
            "https://app.test/?screen=test.grid",
            { catalog: experienceCatalog, screen: makeKeyboardEntryScreen(), html: keyboardHarnessHtml, waitForInitialRows: false },
        );
        try {
            await page.setViewportSize(viewport);
            const entry = page.locator('[data-main-panel] form.tui-action-entry-form');
            await entry.waitFor({ state: "visible" });
            const assertTaskChromeHidden = async () => {
                assert.equal(await page.locator(".tui-rail").isVisible(), false);
                assert.equal(await page.locator(".tui-actions-panel").isVisible(), false);
                assert.equal(await page.locator(".tui-inspector-panel").isVisible(), false);
                assert.equal(await page.evaluate(() => Boolean(document.activeElement?.getClientRects?.().length)), true);
            };
            await assertTaskChromeHidden();
            await page.keyboard.press("F9");
            assert.equal(await page.evaluate(() => document.activeElement?.closest(".tui-action-entry-form") !== null), true);

            await page.keyboard.press("F2");
            await assertTaskChromeHidden();
            assert.equal(await page.evaluate(() => document.activeElement?.closest(".tui-action-entry-form") !== null), true);
            assert.match(await page.locator("[data-workbench-status]").innerText(), /专业模式/);
            await page.keyboard.press("F10");
            await assertTaskChromeHidden();
            assert.equal(await page.evaluate(() => document.activeElement?.closest(".tui-action-entry-form") !== null), true);
            assert.match(await page.locator("[data-workbench-status]").innerText(), /专业模式/);

            await entry.locator('[name="code"]').fill("typed-entry-value");
            const response = page.waitForResponse((item) => item.url().includes("/actions/test.detail/run/"));
            await page.keyboard.press("F6");
            await response;
            await page.locator("[data-research-again-entry]").waitFor();
            const actionRequestCount = () => requestLog.filter(
                (line) => line.includes("/actions/test.detail/run/") && line.startsWith("REQ"),
            ).length;
            assert.equal(actionRequestCount(), 1);

            await page.keyboard.press("F9");
            await assertTaskChromeHidden();
            const reentry = page.locator("[data-research-again-entry]");
            assert.equal(await reentry.evaluate((element) => element.open), true);
            assert.equal(await page.evaluate(() => document.activeElement?.closest(".tui-action-entry-form") !== null), true);
            const focusedVisible = await page.evaluate(() => {
                const element = document.activeElement;
                return Boolean(element && element.getClientRects().length && element.closest(".tui-action-entry-form"));
            });
            assert.equal(focusedVisible, true);

            await page.keyboard.press("F2");
            await page.keyboard.press("F10");
            await assertTaskChromeHidden();
            assert.equal(actionRequestCount(), 1);
            assert.equal(await page.evaluate(() => document.activeElement?.closest(".tui-action-entry-form") !== null), true);

            const focusBeforeHelp = await page.evaluate(() => {
                window.__tux10HelpFocus = document.activeElement;
                return {
                    name: document.activeElement?.getAttribute("name") || "",
                    value: "value" in (document.activeElement || {}) ? document.activeElement.value : "",
                };
            });
            await page.keyboard.press("F1");
            await page.locator("[data-tui-modal]").waitFor({ state: "visible" });
            await page.keyboard.press("Escape");
            assert.deepEqual(await page.evaluate((expected) => {
                const active = document.activeElement;
                const sameNode = active === window.__tux10HelpFocus;
                const sameValue = ("value" in (active || {}) ? active.value : "") === expected.value;
                const sameName = (active?.getAttribute("name") || "") === expected.name;
                delete window.__tux10HelpFocus;
                return { sameNode, sameValue, sameName };
            }, focusBeforeHelp), { sameNode: true, sameValue: true, sameName: true });
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true);
        } finally { await browser.close(); }
    });
}

test("F6 deduplicates and preserves dashboard target panel options", async () => {
    const targetScreen = makeTargetKeyboardDashboardScreen();
    const { browser, page, requestLog } = await openHarness(
        "https://app.test/?screen=test.dashboard",
        {
            catalog: experienceCatalog,
            dashboardScreen: targetScreen,
            html: keyboardHarnessHtml,
            waitForInitialRows: false,
        },
    );
    let requests = 0;
    try {
        await page.route("**/actions/test.regime/run/", async (route) => {
            requests += 1;
            await delay(150);
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: targetScreen.actions[0],
                    outcome: "success",
                    response: { status_code: 200 },
                    view_model: {
                        kind: "detail",
                        title: "合成目标结果",
                        status: "仅用于交互验证",
                        fields: [{ label: "代码", value: "fixture-target" }],
                    },
                    debug: { raw_available: false, raw_response: null },
                }),
            });
        });
        await page.locator('[data-experience-mode="professional"]').click();
        await page.keyboard.press("F9");
        const form = page.locator('[data-actions-panel] form[data-action-ui-key="test.regime"]');
        await form.waitFor({ state: "visible" });
        assert.equal(await form.evaluate(element => element.closest(".tui-panel").hidden), false);
        assert.equal(requestLog.filter(line => line.startsWith("REQ") && line.includes("/actions/test.regime/run/")).length, 0);
        await form.locator('[name="code"]').fill("fixture-target");
        await form.evaluate((element) => {
            element.dataset.dashboardResultPanelKey = "target";
            element.dataset.dashboardRefreshPanelKey = "target";
            element.querySelector(".tui-action-submit")?.focus();
        });
        const response = page.waitForResponse((item) => item.url().includes("/actions/test.regime/run/"));
        await page.keyboard.press("F6");
        await page.keyboard.press("F6");
        await response;
        await page.locator('[data-dashboard-panel="target"] h3').waitFor();
        assert.equal(requests, 1);
        assert.equal(requestLog.filter(
            (line) => line.includes("/actions/test.regime/run/") && line.startsWith("REQ"),
        ).length, 1);
        assert.match(await page.locator('[data-dashboard-panel="target"]').innerText(), /合成目标结果/);
    } finally { await browser.close(); }
});

for (const mismatch of ["missing default action", "mismatched entry form"]) {
    test(`task F6 stops without choosing another primary for ${mismatch}`, async () => {
        const taskScreen = makeKeyboardEntryScreen();
        taskScreen.actions = [
            ...taskScreen.actions,
            action("test.other-primary", { label: "另一个主任务", task_tier: "primary", sequence: 2 }),
        ];
        if (mismatch === "missing default action") {
            taskScreen.screen.default_action_key = "test.missing";
        }
        const { browser, page, requestLog } = await openHarness(
            "https://app.test/?screen=test.grid",
            { catalog: experienceCatalog, screen: taskScreen, html: keyboardHarnessHtml, waitForInitialRows: false },
        );
        try {
            const entry = page.locator('[data-main-panel] form.tui-action-entry-form');
            await entry.waitFor({ state: "visible" });
            await entry.locator('[name="code"]').fill("strict-task-code");
            if (mismatch === "mismatched entry form") {
                await entry.evaluate((form) => { form.dataset.actionUiKey = "test.other-primary"; });
            }
            await page.keyboard.press("F6");
            await delay(100);
            assert.equal(requestLog.filter((line) => line.includes("/actions/") && line.startsWith("REQ")).length, 0);
            assert.match(await page.locator("[data-workbench-status]").innerText(), /入口|默认任务/);
        } finally { await browser.close(); }
    });
}

test("task F6 stops when the required entry form is hidden", async () => {
    const { browser, page, requestLog } = await openHarness(
        "https://app.test/?screen=test.grid",
        { catalog: experienceCatalog, screen: makeKeyboardEntryScreen(), html: keyboardHarnessHtml, waitForInitialRows: false },
    );
    try {
        const entry = page.locator('[data-main-panel] form.tui-action-entry-form');
        await entry.waitFor({ state: "visible" });
        await entry.evaluate((form) => { form.hidden = true; });
        await page.keyboard.press("F6");
        await delay(100);
        assert.equal(requestLog.filter((line) => line.includes("/actions/") && line.startsWith("REQ")).length, 0);
        assert.match(await page.locator("[data-workbench-status]").innerText(), /可见入口|入口/);
    } finally { await browser.close(); }
});

for (const failureMode of ["HTTP 503", "network abort"]) {
    test(`passive read failure keeps a closed entry and F9 reveals it without reading (${failureMode})`, async () => {
        const { browser, page, requestLog } = await openHarness(
            "https://app.test/?screen=test.grid",
            { catalog: experienceCatalog, screen: makeKeyboardEntryScreen(), html: keyboardHarnessHtml, waitForInitialRows: false },
        );
        let attempts = 0;
        try {
            await page.route("**/actions/test.detail/run/", async (route) => {
                attempts += 1;
                if (failureMode === "network abort") {
                    await route.abort("failed");
                    return;
                }
                await route.fulfill({
                    status: 503,
                    contentType: "application/json",
                    body: JSON.stringify({ title: "合成暂时不可用" }),
                });
            });
            const entry = page.locator('[data-main-panel] form.tui-action-entry-form');
            await entry.waitFor({ state: "visible" });
            await entry.locator('[name="code"]').fill("retryable-code");
            await entry.locator(".tui-entry-submit").click();
            const reentry = page.locator("[data-research-again-entry]");
            await reentry.waitFor({ state: "visible" });
            assert.equal(await reentry.evaluate((element) => element.open), false);
            assert.equal(attempts, 1);
            await page.keyboard.press("F9");
            await reentry.waitFor({ state: "visible" });
            assert.equal(await reentry.evaluate((element) => element.open), true);
            assert.equal(await reentry.locator('[name="code"]').inputValue(), "retryable-code");
            assert.equal(attempts, 1);
            assert.equal(requestLog.filter(
                (line) => line.includes("/actions/test.detail/run/") && line.startsWith("REQ"),
            ).length, 1);
        } finally { await browser.close(); }
    });
}


test("F6 preserves an edited professional scope after a different row was selected", async () => {
    const selectedScreen = structuredClone(screen);
    selectedScreen.actions = [
        action("test.list", { view_type: "datagrid", task_tier: "primary", sequence: 1 }),
        action("test.detail", {
            task_tier: "primary", sequence: 2,
            fields: [{ key: "code", label: "代码", input_type: "text", required: true }],
        }),
    ];
    const { browser, page } = await openHarness("https://app.test/?screen=test.grid", {
        catalog: experienceCatalog, screen: selectedScreen, html: keyboardHarnessHtml,
    });
    try {
        await page.locator('[data-experience-mode="professional"]').click();
        await page.locator('[data-row-index="0"]').click();
        const form = page.locator('[data-actions-panel] form[data-action-ui-key="test.detail"]');
        await form.locator('[data-fill-from-row]').click();
        assert.equal(await form.locator('[name="code"]').inputValue(), "row-001");
        await form.locator('[name="code"]').fill("deliberately-edited-scope");
        await form.locator('[name="code"]').focus();
        const request = page.waitForRequest("**/actions/test.detail/run/");
        await page.keyboard.press("F6");
        assert.equal((await request).postDataJSON().params.code, "deliberately-edited-scope");
    } finally { await browser.close(); }
});

test("fresh task home keeps F6 and Ctrl+Enter quiet until Today is explicit", async () => {
    const passiveAction = action("test.passive-status", {
        label: "合成被动读取", risk: "read", method: "GET", task_tier: "primary",
        screen_key: "test.dashboard",
    });
    const passiveDashboard = structuredClone(dashboardScreen);
    passiveDashboard.actions = [
        ...passiveDashboard.actions.filter(item => item.key !== "test.admin-read"), passiveAction,
    ];
    passiveDashboard.screen.dashboard_panels = passiveDashboard.screen.dashboard_panels.map(panel => (
        panel.action_key === "test.admin-read"
            ? { ...panel, action_key: passiveAction.key, title: "合成被动读取" } : panel
    ));
    const { browser, page, requestLog } = await openHarness("https://app.test/", {
        catalog: experienceCatalog,
        dashboardScreen: passiveDashboard,
        waitForInitialRows: false,
    });
    try {
        await page.route("**/actions/test.passive-status/run/", async route => {
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
                action: passiveAction, outcome: "success", response: { status_code: 200 },
                view_model: { kind: "detail", title: "合成读取完成", status: "完成", fields: [] },
                debug: { raw_available: false, raw_response: null },
            }) });
        });
        await page.locator("[data-task-home]").waitFor({ state: "attached" });
        const beforeUrl = page.url();
        const beforeHistory = await page.evaluate(() => history.length);
        const taskMode = page.locator('[data-experience-mode="task"]');
        await taskMode.focus();
        await page.keyboard.press("F2");
        assert.match(await page.locator("[data-workbench-status]").innerText(), /任务首页/);
        await page.keyboard.press("F9");
        await page.waitForFunction(() => Boolean(
            document.activeElement?.matches?.("[data-task-home] [data-experience-entry]"),
        ));
        assert.equal(await page.evaluate(() => Boolean(
            document.activeElement?.getClientRects?.().length
            && document.activeElement?.matches?.("[data-task-home] [data-experience-entry]"),
        )), true);
        await page.keyboard.press("F10");
        assert.match(await page.locator("[data-workbench-status]").innerText(), /任务首页/);
        assert.equal(page.url(), beforeUrl);
        assert.equal(await page.evaluate(() => history.length), beforeHistory);
        await page.keyboard.press("F6");
        await page.keyboard.press("Control+Enter");
        await delay(100);
        assert.equal(requestLog.some((line) => line.includes("/actions/") && line.startsWith("REQ")), false);
        assert.equal(page.url(), beforeUrl);
        assert.equal(await page.evaluate(() => history.length), beforeHistory);
        assert.match(await page.locator("[data-workbench-status]").innerText(), /选择任务/);
        const initialPassiveRead = page.waitForResponse(response => response.url().includes("/actions/test.passive-status/run/"));
        await page.locator('[data-experience-entry="today"]').click();
        await initialPassiveRead;
        await page.locator('[data-dashboard-panel="regime"]').waitFor();
        await page.locator('[data-experience-mode="professional"]').click();
        await page.keyboard.press("F9");
        const explicitReadForm = page.locator('[data-actions-panel] form[data-action-ui-key="test.passive-status"]');
        await explicitReadForm.waitFor({ state: "visible" });
        assert.equal(await explicitReadForm.evaluate(element => element.closest(".tui-panel").hidden), false);
        await explicitReadForm.locator(".tui-action-submit").focus();
        requestLog.length = 0;
        const safeRead = page.waitForRequest("**/actions/test.passive-status/run/");
        await page.keyboard.press("F6");
        const request = await safeRead;
        assert.equal(request.method(), "POST");
        const body = request.postDataJSON();
        assert.equal(body.confirmed, false);
        assert.equal(body.confirmation, undefined);
        assert.equal(body.idempotency_key, undefined);
        assert.equal(requestLog.filter(
            (line) => line.includes("/actions/test.passive-status/run/") && line.startsWith("REQ"),
        ).length, 1);
        await page.waitForFunction(() => document.querySelector("[data-workbench-status]")?.textContent === "读取完成");
        await delay(300); // An explicit second read must keep the original duplicate guard.
        await explicitReadForm.locator(".tui-action-submit").focus();
        const reread = page.waitForRequest("**/actions/test.passive-status/run/");
        await page.keyboard.press("F6");
        assert.equal((await reread).method(), "POST");
        assert.equal(requestLog.filter(
            line => line.startsWith("REQ") && line.includes("/actions/test.passive-status/run/"),
        ).length, 2);
    } finally { await browser.close(); }
});

test("F9 does not focus a hidden task entry form", async () => {
    const { browser, page, requestLog } = await openHarness(
        "https://app.test/?screen=test.grid",
        { catalog: experienceCatalog, screen: makeKeyboardEntryScreen(), html: keyboardHarnessHtml, waitForInitialRows: false },
    );
    try {
        const entry = page.locator('[data-main-panel] form.tui-action-entry-form');
        await entry.waitFor({ state: "visible" });
        await page.locator('[data-experience-mode="task"]').focus();
        await entry.evaluate((form) => { form.hidden = true; });
        await page.keyboard.press("F9");
        await delay(50);
        const focus = await page.evaluate(() => {
            const active = document.activeElement;
            return {
                visible: Boolean(active && active.getClientRects().length),
                insideEntry: Boolean(active?.closest?.("form.tui-action-entry-form")),
            };
        });
        assert.equal(focus.visible, true);
        assert.equal(focus.insideEntry, false);
        assert.match(await page.locator("[data-workbench-status]").innerText(), /暂不可见|展开任务入口/);
        assert.equal(requestLog.some((line) => line.includes("/actions/") && line.startsWith("REQ")), false);
    } finally { await browser.close(); }
});

test("mode tabs keep roving focus reachable through Home, End, and Tab", async () => {
    const { browser, page, requestLog } = await openHarness("https://app.test/", {
        catalog: experienceCatalog,
        waitForInitialRows: false,
    });
    try {
        await page.locator("[data-task-home]").waitFor({ state: "attached" });
        const taskTab = page.locator('[data-experience-mode="task"]');
        const professionalTab = page.locator('[data-experience-mode="professional"]');
        await taskTab.focus();
        await taskTab.press("End");
        assert.equal(await professionalTab.getAttribute("aria-selected"), "true");
        assert.equal(await professionalTab.getAttribute("tabindex"), "0");
        assert.equal(await taskTab.getAttribute("tabindex"), "-1");
        assert.equal(await professionalTab.evaluate((element) => element === document.activeElement), true);
        await professionalTab.press("Home");
        assert.equal(await taskTab.getAttribute("aria-selected"), "true");
        assert.equal(await taskTab.getAttribute("tabindex"), "0");
        assert.equal(await taskTab.evaluate((element) => element === document.activeElement), true);
        await taskTab.press("Tab");
        const focus = await page.evaluate(() => {
            const active = document.activeElement;
            return {
                visible: Boolean(active && active.getClientRects().length),
                inactiveMode: Boolean(active?.matches?.('[data-experience-mode][tabindex="-1"]')),
            };
        });
        assert.equal(focus.visible, true);
        assert.equal(focus.inactiveMode, false);
        assert.equal(requestLog.some((line) => line.includes("/actions/") && line.startsWith("REQ")), false);
    } finally { await browser.close(); }
});

test("task dashboard keeps F2/F9/F10 on the visible focused CSS surface", async () => {
    const { browser, page, requestLog } = await openHarness(
        "https://app.test/?screen=test.dashboard",
        {
            catalog: experienceCatalog,
            dashboardScreen,
            html: keyboardHarnessHtml,
            waitForInitialRows: false,
        },
    );
    try {
        await page.locator("[data-task-dashboard]").waitFor({ state: "attached" });
        const actionRequestCount = () => requestLog.filter(
            (line) => line.includes("/actions/") && line.startsWith("REQ"),
        ).length;
        const initialRequests = actionRequestCount();
        const taskMode = page.locator('[data-experience-mode="task"]');
        await taskMode.focus();
        const assertDashboardSurface = async () => {
            assert.equal(await page.locator(".tui-rail").isVisible(), false);
            assert.equal(await page.locator(".tui-actions-panel").isVisible(), false);
            assert.equal(await page.locator(".tui-inspector-panel").isVisible(), false);
            assert.equal(await page.locator(".tui-workspace-grid.is-dashboard").count(), 1);
            assert.equal(await page.locator("[data-task-dashboard]").count(), 1);
            assert.equal(await page.evaluate(() => Boolean(
                document.activeElement && document.activeElement.getClientRects().length,
            )), true);
            assert.equal(await page.evaluate(() => Boolean(
                document.activeElement?.closest?.(".tui-rail, .tui-actions-panel, .tui-inspector-panel"),
            )), false);
        };
        await page.keyboard.press("F2");
        await assertDashboardSurface();
        assert.match(await page.locator("[data-workbench-status]").innerText(), /当前任务/);
        await page.keyboard.press("F10");
        await assertDashboardSurface();
        assert.match(await page.locator("[data-workbench-status]").innerText(), /当前任务/);
        await page.keyboard.press("F9");
        await page.waitForFunction(() => Boolean(
            document.activeElement?.closest?.("[data-dashboard-panel]"),
        ));
        assert.equal(await page.evaluate(() => Boolean(
            document.activeElement?.closest?.("[data-dashboard-panel]")
            && document.activeElement.getClientRects().length,
        )), true);
        await assertDashboardSurface();
        assert.equal(actionRequestCount(), initialRequests);
    } finally { await browser.close(); }
});

test("targeted retry stays on the retry button and reuses the passive target once", async () => {
    const targetScreen = makeTargetKeyboardDashboardScreen();
    const { browser, page, requestLog } = await openHarness(
        "https://app.test/?screen=test.dashboard",
        {
            catalog: experienceCatalog,
            dashboardScreen: targetScreen,
            html: keyboardHarnessHtml,
            waitForInitialRows: false,
        },
    );
    let attempts = 0;
    try {
        await page.route("**/actions/test.regime/run/", async (route) => {
            attempts += 1;
            if (attempts === 1) {
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        action: targetScreen.actions[0],
                        outcome: "failed",
                        response: { status_code: 503 },
                        view_model: { kind: "detail", title: "目标读取暂不可用", status: "失败", fields: [] },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
                return;
            }
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    action: targetScreen.actions[0],
                    outcome: "success",
                    response: { status_code: 200 },
                    view_model: { kind: "detail", title: "目标读取完成", status: "完成", fields: [{ label: "代码", value: "fixture-target" }] },
                    debug: { raw_available: false, raw_response: null },
                }),
            });
        });
        await page.locator('[data-experience-mode="professional"]').click();
        await page.keyboard.press("F9");
        const form = page.locator('[data-actions-panel] form[data-action-ui-key="test.regime"]');
        await form.waitFor({ state: "visible" });
        assert.equal(await form.evaluate(element => element.closest(".tui-panel").hidden), false);
        assert.equal(requestLog.filter(line => line.startsWith("REQ") && line.includes("/actions/test.regime/run/")).length, 0);
        await form.locator('[name="code"]').fill("fixture-target");
        await form.evaluate((element) => {
            element.dataset.dashboardResultPanelKey = "target";
            element.dataset.dashboardRefreshPanelKey = "target";
        });
        await form.locator(".tui-action-submit").click();
        const retry = page.locator('button[data-targeted-read-retry]');
        await retry.waitFor({ state: "visible" });
        assert.equal(await page.locator('button[data-panel-retry][data-targeted-read-retry]').count(), 1);
        const successfulRead = page.waitForResponse((item) => item.url().includes("/actions/test.regime/run/"));
        await retry.click();
        await successfulRead;
        await page.getByText("目标读取完成", { exact: true }).waitFor();
        assert.equal(attempts, 2);
        assert.equal(requestLog.filter(
            (line) => line.includes("/actions/test.regime/run/") && line.startsWith("REQ"),
        ).length, 2);
    } finally { await browser.close(); }
});


test("F6 leaves blank required fields empty until explicit row fill", async () => {
    const selectedScreen = structuredClone(screen);
    selectedScreen.actions = [
        action("test.list", { view_type: "datagrid", task_tier: "primary", sequence: 1 }),
        action("test.detail", {
            task_tier: "primary", sequence: 2,
            fields: [{ key: "code", label: "代码", input_type: "text", required: true }],
        }),
    ];
    const { browser, page, requestLog } = await openHarness("https://app.test/?screen=test.grid", {
        catalog: experienceCatalog, screen: selectedScreen, html: keyboardHarnessHtml,
    });
    try {
        await page.locator('[data-experience-mode="professional"]').click();
        await page.locator('[data-row-index="0"]').click();
        const form = page.locator('[data-actions-panel] form[data-action-ui-key="test.detail"]');
        await form.locator('[name="code"]').fill("");
        requestLog.length = 0;
        await page.keyboard.press("F6");
        await delay(100);
        assert.equal(await form.locator('[name="code"]').inputValue(), "");
        assert.equal(requestLog.filter(line => line.startsWith("REQ") && line.includes("/actions/")).length, 0);
        assert.match(await page.locator("[data-workbench-status]").innerText(), /需要参数/);
        await form.locator('[data-fill-from-row]').click();
        assert.equal(await form.locator('[name="code"]').inputValue(), "row-001");
        const request = page.waitForRequest("**/actions/test.detail/run/");
        await page.keyboard.press("F6");
        assert.equal((await request).postDataJSON().params.code, "row-001");
        assert.equal(requestLog.filter(line => line.startsWith("REQ") && line.includes("/actions/test.detail/run/")).length, 1);
    } finally { await browser.close(); }
});

for (const resultCase of [
    { outcome: "blocked", expectedStatus: "结果受阻，未形成可用结果" },
    { outcome: "failed", expectedStatus: "操作未完成，请检查结果后重试" },
]) {
    test(`confirmed ${resultCase.outcome} owner result is not reported as completed`, async () => {
        const mutation = action("test.edit", {
            label: "保存记录",
            method: "POST",
            risk: "write",
            effect: "update",
            task_tier: "primary",
            confirmation_required: true,
            fields: [{ key: "code", label: "代码", input_type: "text", required: true }],
        });
        const mutationScreen = {
            ...screen,
            screen: { ...screen.screen, default_action_key: mutation.key },
            actions: [mutation],
        };
        const { browser, page } = await openHarness(
            "https://app.test/?screen=test.grid&action=test.edit",
            { catalog: experienceCatalog, screen: mutationScreen, waitForInitialRows: false },
        );
        try {
            await page.route("**/actions/test.edit/run/", async route => {
                if (!route.request().postDataJSON().confirmed) {
                    await route.fallback();
                    return;
                }
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        version: "tui-workbench.v2",
                        action: mutation,
                        outcome: resultCase.outcome,
                        confirmation_required: false,
                        response: { status_code: 200 },
                        view_model: {
                            kind: "detail",
                            title: "保存记录",
                            status: resultCase.outcome,
                            outcome: resultCase.outcome,
                            fields: [],
                        },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
            });
            const form = page.locator('form[data-action-ui-key="test.edit"]');
            await form.locator('[name="code"]').fill("asset-A");
            await form.locator(".tui-action-submit").click();
            await page.locator("[data-confirm-action]").click();
            await page.waitForFunction(
                expected => document.querySelector("[data-workbench-status]")?.textContent === expected,
                resultCase.expectedStatus,
            );
            assert.equal(await page.locator("[data-workbench-status]").innerText(), resultCase.expectedStatus);
            assert.match(await page.locator("[data-action-summary]").innerText(), new RegExp("本次已操作 0/1"));
        } finally {
            await browser.close();
        }
    });
}


for (const resultCase of [
    { outcome: "blocked", expectedStatus: "结果受阻，未形成可用结果", expectedCompleted: false },
    { outcome: "failed", expectedStatus: "操作未完成，请检查结果后重试", expectedCompleted: false },
    { outcome: "success", expectedStatus: "操作完成，列表已刷新", expectedCompleted: true },
]) {
    test(`confirmed dashboard-panel ${resultCase.outcome} mutation reports its persisted completion state`, async () => {
        const mutation = action("test.dashboard-write", {
            label: "提交治理操作",
            method: "POST",
            risk: "write",
            effect: "update",
            task_tier: "primary",
            confirmation_required: true,
            screen_key: "test.dashboard",
            fields: [{ key: "user_id", label: "用户 ID", input_type: "hidden", required: true, binding: "path" }],
        });
        const listAction = {
            ...actions.find(item => item.key === "test.user-list"),
            screen_key: "test.dashboard",
            task_tier: "support",
        };
        const panelScreen = {
            ...structuredClone(dashboardScreen),
            screen: {
                ...structuredClone(dashboardScreen.screen),
                user_experience: { primary_task: "处理治理操作", primary_outcome: "得到处理结果" },
                dashboard_panels: [{
                    key: "users",
                    title: "用户队列",
                    kind: "datagrid",
                    user_priority: "p0",
                    presentation_semantic: "primary_list",
                    action_key: listAction.key,
                    columns: [{ key: "username", label: "用户名" }],
                    row_actions: [{
                        action_key: mutation.key,
                        label_template: "提交 {username}",
                        param_map: { user_id: "user_id" },
                    }],
                }],
            },
            actions: [listAction, mutation],
        };
        const initialSessionStorage = resultCase.expectedCompleted
            ? {}
            : {
                "agom-tui-primary-progress:v1:user:test-user": JSON.stringify({
                    "test.dashboard:__CURRENT_DATE__": [mutation.key],
                }),
            };
        const { browser, page } = await openHarness(
            "https://app.test/?screen=test.dashboard",
            {
                catalog: experienceCatalog,
                dashboardScreen: panelScreen,
                initialSessionStorage,
                waitForInitialRows: false,
            },
        );
        const mutationBodies = [];
        let refreshedListRequests = 0;
        try {
            await page.locator('[data-dashboard-panel="users"] [data-dashboard-row-action][aria-label="提交 pending-user"]').waitFor();
            page.on("request", request => {
                if (request.url().includes("/actions/test.user-list/run/")) refreshedListRequests += 1;
            });
            await page.route("**/actions/test.dashboard-write/run/", async route => {
                const body = route.request().postDataJSON();
                mutationBodies.push(body);
                if (!body.confirmed) {
                    await route.fulfill({
                        status: 200,
                        contentType: "application/json",
                        body: JSON.stringify({
                            version: "tui-workbench.v2",
                            action: mutation,
                            confirmation_required: true,
                            confirmation: { title: "确认操作", message: "确认后提交治理操作。" },
                            response: { status_code: 409 },
                            view_model: { kind: "message", title: "等待确认", status: "待确认" },
                            debug: { raw_available: false, raw_response: null },
                        }),
                    });
                    return;
                }
                await route.fulfill({
                    status: 200,
                    contentType: "application/json",
                    body: JSON.stringify({
                        version: "tui-workbench.v2",
                        action: mutation,
                        outcome: resultCase.outcome,
                        confirmation_required: false,
                        response: { status_code: 200 },
                        view_model: {
                            kind: "detail",
                            title: "治理操作结果",
                            status: resultCase.outcome,
                            outcome: resultCase.outcome,
                            fields: [],
                        },
                        debug: { raw_available: false, raw_response: null },
                    }),
                });
            });

            await page.locator('[data-dashboard-panel="users"] [data-dashboard-row-action][aria-label="提交 pending-user"]').click();
            await page.locator("[data-confirm-action]").waitFor({ state: "visible" });
            const confirmedResponse = page.waitForResponse(response =>
                response.url().includes("/actions/test.dashboard-write/run/")
                    && Boolean(response.request().postDataJSON().confirmed),
            );
            await page.locator("[data-confirm-action]").click();
            const result = await confirmedResponse;
            assert.equal(result.status(), 200);
            await page.waitForFunction(
                expected => document.querySelector("[data-workbench-status]")?.textContent === expected,
                resultCase.expectedStatus,
            );
            assert.deepEqual(mutationBodies.map(body => Boolean(body.confirmed)), [false, true]);
            const progressHandle = await page.waitForFunction(
                ({ actionKey, expectedCompleted }) => {
                    const app = document.querySelector("[data-tui-app]");
                    const userKey = String(app?.dataset.userKey || "anonymous")
                        .trim()
                        .replace(/[^a-zA-Z0-9_-]+/g, "_");
                    const storageKey = `agom-tui-primary-progress:v1:user:${userKey || "anonymous"}`;
                    const raw = window.sessionStorage.getItem(storageKey);
                    if (raw === null) return false;
                    let progress;
                    try { progress = JSON.parse(raw); } catch (_error) { return false; }
                    const screenDayKey = `test.dashboard:${new Date().toLocaleDateString("en-CA")}`;
                    const actionKeys = Array.isArray(progress?.[screenDayKey]) ? progress[screenDayKey] : [];
                    if (actionKeys.includes(actionKey) !== expectedCompleted) return false;
                    return { storageKey, raw, screenDayKey, actionKeys };
                },
                { actionKey: mutation.key, expectedCompleted: resultCase.expectedCompleted },
            );
            const progressSnapshot = await progressHandle.jsonValue();
            assert.equal(progressSnapshot.storageKey, "agom-tui-primary-progress:v1:user:test-user");
            assert.notEqual(progressSnapshot.raw, null);
            assert.equal(
                progressSnapshot.actionKeys.includes(mutation.key),
                resultCase.expectedCompleted,
            );
            assert.equal(refreshedListRequests, 1);
            assert.ok(await page.locator('[data-dashboard-panel="users"] [data-dashboard-row-action]').count() > 0);
        } finally {
            await browser.close();
        }
    });
}
