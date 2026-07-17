import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createRuntimeUrls } from "../src/api.js";
import { dashboardDesktopColumns } from "../src/dashboard-layout.js";
import { clientPage } from "../src/pagination.js";
import {
    assertManifestIntegrity,
    normalizeRuntimeContent,
    runtimeContentsEqual,
} from "../../../scripts/tui-runtime-manifest.mjs";

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

test("dashboard layout precedence is explicit metadata then host fallback then journey", () => {
    const host = { singleColumnScreens: ["legacy.single-column"] };

    assert.equal(
        dashboardDesktopColumns(
            {
                key: "legacy.single-column",
                dashboard_layout: "task_flow",
                user_experience: { journey: "workspace" },
            },
            host,
        ),
        1,
    );
    assert.equal(
        dashboardDesktopColumns(
            {
                key: "legacy.single-column",
                dashboard_layout: "adaptive_grid",
                user_experience: { journey: "workspace" },
            },
            host,
        ),
        1,
    );
    assert.equal(
        dashboardDesktopColumns(
            {
                key: "self-service",
                dashboard_layout: "adaptive_grid",
                user_experience: { journey: "self_service" },
            },
            host,
        ),
        2,
    );
    assert.equal(
        dashboardDesktopColumns(
            {
                key: "workspace",
                dashboard_layout: "adaptive_grid",
                user_experience: { journey: "workspace" },
            },
            host,
        ),
        3,
    );
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

test("manifest integrity uses content hashes instead of the repository head", () => {
    const payload = {
        version: "0.2.0",
        source_owner: "AgomTradePro",
        upstream_commit: "a".repeat(40),
        build_id: "agomtui-runtime-0.2.0+abc123",
        direction: "AgomTradePro -> AgOMTUI",
        contracts: { screen_dashboard_layouts: ["adaptive_grid", "task_flow"] },
        files: { "runtime.js": "hash" },
    };
    assert.doesNotThrow(() =>
        assertManifestIntegrity(payload, { ...payload, upstream_commit: "b".repeat(40) }, () => true),
    );
    assert.throws(
        () => assertManifestIntegrity(payload, { ...payload, files: { "runtime.js": "changed" } }),
        /content hashes are stale/,
    );
    assert.throws(
        () => assertManifestIntegrity({ ...payload, upstream_commit: "b".repeat(40) }, payload, () => false),
        /not an ancestor/,
    );
    assert.throws(
        () => assertManifestIntegrity({ ...payload, source_owner: "downstream" }, payload),
        /source_owner must be AgomTradePro/,
    );
});

test("manifest content normalization is independent of checkout line endings", () => {
    assert.deepEqual(normalizeRuntimeContent("alpha\r\nbeta\r\n"), Buffer.from("alpha\nbeta\n"));
    assert.deepEqual(normalizeRuntimeContent(Buffer.from("alpha\nbeta\n")), Buffer.from("alpha\nbeta\n"));
    assert.equal(runtimeContentsEqual("bundle();\r\n", Buffer.from("bundle();\n")), true);
    assert.equal(runtimeContentsEqual("bundle(1);\r\n", Buffer.from("bundle(2);\n")), false);
});
