import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const sourceNames = [
    "00-runtime.js",
    "10-navigation.js",
    "20-dashboard.js",
    "30-actions.js",
    "40-views.js",
    "50-shell.js",
];

test("workbench maintained sources stay split by responsibility", async () => {
    const sourceRoot = resolve(root, "frontend/tui-workbench/src");
    const sources = await Promise.all(
        sourceNames.map((name) => readFile(resolve(sourceRoot, name), "utf8")),
    );
    const lineCounts = sources.map((source) => source.split(/\r?\n/).length);
    assert.ok(lineCounts.every((count) => count <= 1_500), `source lines: ${lineCounts.join(", ")}`);

    const bundle = await readFile(resolve(root, "static/js/tui-workbench.js"), "utf8");
    assert.ok(bundle.split(/\r?\n/).length <= 1_000, "compatibility bundle should stay generated and compact");

    const buildScript = await readFile(resolve(root, "scripts/build-tui-runtime.mjs"), "utf8");
    let previousIndex = -1;
    for (const name of sourceNames) {
        const index = buildScript.indexOf(`frontend/tui-workbench/src/${name}`);
        assert.ok(index > previousIndex, `${name} must appear in declaration order`);
        previousIndex = index;
    }
});
