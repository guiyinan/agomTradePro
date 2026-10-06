import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { chromium } from "playwright";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const dashboardTemplate = await readFile(
    resolve(root, "core/templates/dashboard/index.html"),
    "utf8",
);

function functionSource(source, startMarker, endMarker) {
    const start = source.indexOf(startMarker);
    const end = source.indexOf(endMarker, start);
    assert.notEqual(start, -1, `missing source marker: ${startMarker}`);
    assert.notEqual(end, -1, `missing source marker: ${endMarker}`);
    return source.slice(start, end);
}

async function openAlphaRefreshPage() {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const statusRetry = functionSource(
        dashboardTemplate,
        "function retryAlphaRefreshStatus(",
        "function scheduleAlphaAutoRefreshFromPanel(",
    );
    const triggerRefresh = functionSource(
        dashboardTemplate,
        "async function triggerAlphaRealtimeRefresh(",
        "async function discardAlphaPendingRequest(",
    );
    await page.setContent(`
        <button id="alphaRealtimeRefreshBtn">刷新</button>
        <span id="alphaRefreshStatus" role="status"></span>
        <button id="alphaRefreshStatusRetry" onclick="retryAlphaRefreshStatus(10)" hidden>重新读取 Alpha 状态</button>
    `);
    await page.evaluate(() => {
        window.API_URLS = { alphaRefresh: "/api/alpha/refresh/" };
        window.getAlphaScopeMode = () => "general";
        window.getAlphaPortfolioId = () => "";
        window.getAlphaPoolMode = () => "price_covered";
        window.getCookie = () => "csrf-test-token";
        window.hasInlineAlphaStocksTarget = () => true;
        window.refreshAlphaHomepageFallback = () => {};
        window.__statusReads = 0;
        window.__fetchCalls = 0;
        window.__postCalls = 0;
        window.reloadAlphaStocksTable = () => {
            window.__statusReads += 1;
            return Promise.resolve();
        };
        window.fetch = (_url, options) => {
            window.__fetchCalls += 1;
            if (options?.method === "POST") window.__postCalls += 1;
            return new Promise((resolve, reject) => {
                window.__resolveAlphaResponse = resolve;
                window.__rejectAlphaResponse = reject;
            });
        };
    });
    assert.match(dashboardTemplate, /const ALPHA_REFRESH_FEEDBACK_BUDGET_MS = 15000;/);
    await page.addScriptTag({
        content: `
            const ALPHA_REFRESH_FEEDBACK_BUDGET_MS = 300;
            let alphaRefreshRequestInFlight = false;
            ${statusRetry}
            ${triggerRefresh}
        `,
    });
    return { browser, page };
}

test("Classic Alpha refresh shows loading, bounded wait and read-only status retry", async () => {
    const { browser, page } = await openAlphaRefreshPage();
    try {
        await page.evaluate(() => {
            window.__refreshPromise = window.triggerAlphaRealtimeRefresh(
                10,
                document.getElementById("alphaRealtimeRefreshBtn"),
            );
        });
        assert.equal(await page.locator("#alphaRealtimeRefreshBtn").isDisabled(), true);
        assert.match(await page.locator("#alphaRefreshStatus").innerText(), /正在触发 Alpha 刷新/);
        await page.locator("#alphaRefreshStatusRetry").waitFor({ state: "visible" });
        assert.match(await page.locator("#alphaRefreshStatus").innerText(), /等待超过 15 秒/);
        assert.match(await page.locator("#alphaRefreshStatus").innerText(), /请勿再次触发/);
        assert.equal(await page.evaluate(() => window.__fetchCalls), 1);
        assert.equal(await page.evaluate(() => window.__postCalls), 1);

        await page.locator("#alphaRefreshStatusRetry").click();
        assert.equal(await page.evaluate(() => window.__statusReads), 1);
        await page.waitForFunction(() => document.getElementById("alphaRefreshStatus")?.textContent === "Alpha 状态已重新读取。");
        assert.equal(await page.evaluate(() => window.__fetchCalls), 1);
        assert.equal(await page.evaluate(() => window.__postCalls), 1);

        await page.evaluate(() => window.__resolveAlphaResponse(new Response(
            JSON.stringify({ success: true, sync: true, message: "Alpha 刷新已排队" }),
            { status: 200, headers: { "content-type": "application/json" } },
        )));
        await page.waitForFunction(() => document.getElementById("alphaRefreshStatus")?.textContent === "Alpha 刷新已排队");
        assert.equal(await page.locator("#alphaRealtimeRefreshBtn").isDisabled(), false);
        assert.equal(await page.locator("#alphaRefreshStatusRetry").isHidden(), true);
    } finally {
        await browser.close();
    }
});

test("Classic Alpha refresh hides server diagnostics and offers state-first recovery", async () => {
    const { browser, page } = await openAlphaRefreshPage();
    try {
        await page.evaluate(() => {
            window.__refreshPromise = window.triggerAlphaRealtimeRefresh(
                10,
                document.getElementById("alphaRealtimeRefreshBtn"),
            );
            window.__rejectAlphaResponse(new Error("password=private database=internal"));
        });
        await page.waitForFunction(() => document.getElementById("alphaRefreshStatus")?.textContent.includes("未能确认刷新状态"));
        const status = await page.locator("#alphaRefreshStatus").innerText();
        assert.doesNotMatch(status, /password|private|database|internal/);
        assert.equal(await page.locator("#alphaRefreshStatusRetry").isHidden(), false);
        assert.equal(await page.locator("#alphaRealtimeRefreshBtn").isDisabled(), false);

        await page.locator("#alphaRefreshStatusRetry").click();
        assert.equal(await page.evaluate(() => window.__statusReads), 1);
        assert.equal(await page.evaluate(() => window.__fetchCalls), 1);
    } finally {
        await browser.close();
    }
});
