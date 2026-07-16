import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createRuntimeUrls } from "../src/api.js";
import { clientPage } from "../src/pagination.js";

test("runtime urls support optimized bootstrap and legacy endpoints", () => {
    const urls = createRuntimeUrls({ apiBase: "/api/tui", bootstrapUrl: "/api/tui/bootstrap/" });
    assert.equal(urls.catalog(), "/api/tui/catalog/");
    assert.equal(urls.screen("screen one"), "/api/tui/screens/screen%20one/");
    assert.equal(urls.bootstrap("home"), "/api/tui/bootstrap/?screen_key=home");
});

test("client pagination activates only above the configured page size", () => {
    const rows = Array.from({ length: 205 }, (_, index) => ({ index }));
    const page = clientPage(rows, 2, 100);
    assert.equal(page.rows[0].index, 100);
    assert.equal(page.rows.length, 100);
    assert.equal(page.pager.total_pages, 3);
    assert.equal(clientPage(rows.slice(0, 10), 1, 100).pager, null);
});

test("generic bundle does not contain AgomTradePro business identifiers", () => {
    const bundles = [
        "../../../static/js/agomtui-runtime-core.js",
        "../../../static/js/tui-workbench.js",
    ].map((relative) => readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8"));
    for (const forbidden of [
        "operator.governance.",
        "operator.home.",
        "ai-ops.providers",
        "capability-router.mcp-center",
        "api-library.runtime",
        "/api/operator/",
        "Terminal/TUI 运行面状态",
    ]) {
        assert.equal(bundles.some((bundle) => bundle.includes(forbidden)), false, `business identifier leaked: ${forbidden}`);
    }
});
