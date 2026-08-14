import { build, transform } from "esbuild";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { readdir } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
    assertManifestIntegrity,
    normalizeRuntimeContent,
    runtimeContentsEqual,
} from "./tui-runtime-manifest.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const check = process.argv.includes("--check");
const targets = [
    {
        entry: resolve(root, "frontend/agomtui-runtime/src/index.js"),
        outfile: resolve(root, "static/js/agomtui-runtime-core.js"),
    },
    {
        entry: resolve(root, "frontend/agomtradepro-host/src/index.js"),
        outfile: resolve(root, "static/js/tui-agomtradepro-adapter.js"),
    },
];
const workbenchSegments = [
    "frontend/tui-workbench/src/00-runtime.js",
    "frontend/tui-workbench/src/10-navigation.js",
    "frontend/tui-workbench/src/20-dashboard.js",
    "frontend/tui-workbench/src/30-actions.js",
    "frontend/tui-workbench/src/40-views.js",
    "frontend/tui-workbench/src/50-shell.js",
];
const workbenchOutfile = resolve(root, "static/js/tui-workbench.js");

async function bundle(target, write) {
    const result = await build({
        entryPoints: [target.entry],
        bundle: true,
        format: "iife",
        platform: "browser",
        target: ["es2020"],
        minify: true,
        sourcemap: false,
        write,
        outfile: target.outfile,
    });
    if (write) {
        return readFile(target.outfile);
    }
    return Buffer.from(result.outputFiles[0].contents);
}

for (const target of targets) {
    const expected = await bundle(target, false);
    if (check) {
        const current = await readFile(target.outfile).catch(() => Buffer.alloc(0));
        if (!runtimeContentsEqual(current, expected)) {
            throw new Error(`Stale TUI bundle: ${target.outfile}`);
        }
    } else {
        await writeFile(target.outfile, expected);
    }
}

async function buildWorkbenchBundle() {
    const body = (await Promise.all(
        workbenchSegments.map((relative) => readFile(resolve(root, relative), "utf8")),
    )).map((content) => content.trimEnd()).join("\n\n");
    const wrapped = `(function () {\n    "use strict";\n${body}\n})();\n`;
    const result = await transform(wrapped, {
        loader: "js",
        minify: true,
        target: "es2020",
    });
    return Buffer.from(result.code, "utf8");
}

const expectedWorkbench = await buildWorkbenchBundle();
if (check) {
    const currentWorkbench = await readFile(workbenchOutfile).catch(() => Buffer.alloc(0));
    if (!runtimeContentsEqual(currentWorkbench, expectedWorkbench)) {
        throw new Error(`Stale TUI bundle: ${workbenchOutfile}`);
    }
} else {
    await writeFile(workbenchOutfile, expectedWorkbench);
}

const manifestPath = resolve(root, "config/tui/agomtui-runtime.manifest.json");
const files = {};
const relativePath = (absolutePath) => relative(root, absolutePath).replaceAll("\\", "/");
const sortedPythonFiles = async (directory, prefix) => {
    const entries = await readdir(directory, { withFileTypes: true });
    return entries
        .filter((entry) => entry.isFile() && entry.name.startsWith(prefix) && entry.name.endsWith(".py"))
        .sort((left, right) => left.name.localeCompare(right.name))
        .map((entry) => resolve(directory, entry.name));
};
const metadataApplicationFiles = await sortedPythonFiles(
    resolve(root, "apps/terminal/application"),
    "tui_metadata",
);
const metadataInfrastructureDirectory = resolve(root, "apps/terminal/infrastructure");
const metadataInfrastructureFiles = [
    resolve(metadataInfrastructureDirectory, "tui_information_architecture.py"),
    resolve(metadataInfrastructureDirectory, "tui_metadata_repository.py"),
    resolve(metadataInfrastructureDirectory, "tui_metadata_signals.py"),
    ...(await sortedPythonFiles(metadataInfrastructureDirectory, "tui_metadata_runtime_")),
];
for (const absolutePath of [
    "config/tui/schema/tui_metadata.schema.v3.json",
    "frontend/agomtui-runtime/src/api.js",
    "frontend/agomtui-runtime/src/dashboard-layout.js",
    "frontend/agomtui-runtime/src/events.js",
    "frontend/agomtui-runtime/src/extensions.js",
    "frontend/agomtui-runtime/src/index.js",
    "frontend/agomtui-runtime/src/pagination.js",
    "frontend/agomtui-runtime/src/performance.js",
    "frontend/agomtui-runtime/src/state.js",
    ...workbenchSegments,
    "static/js/agomtui-runtime-core.js",
    "static/js/tui-workbench.js",
    "static/css/tui-workbench.css",
].map((path) => resolve(root, path)).concat(
    resolve(root, "config/tui/ia/tui_information_architecture.v1.json"),
    metadataApplicationFiles,
    metadataInfrastructureFiles,
)) {
    const path = relativePath(absolutePath);
    const body = normalizeRuntimeContent(await readFile(absolutePath));
    files[path] = createHash("sha256").update(body).digest("hex");
}
const buildHash = createHash("sha256")
    .update(Object.entries(files).map(([path, sha]) => `${path}:${sha}`).join("\n"))
    .digest("hex");
const metadataSchema = JSON.parse(
    await readFile(resolve(root, "config/tui/schema/tui_metadata.schema.v3.json"), "utf8"),
);
const screenDashboardLayouts = metadataSchema?.$defs?.screen?.properties?.dashboard_layout?.enum;
if (!Array.isArray(screenDashboardLayouts) || !screenDashboardLayouts.length) {
    throw new Error("TUI metadata schema must declare screen.dashboard_layout enum values");
}
let upstreamCommit = "unknown";
try {
    upstreamCommit = execFileSync("git", ["rev-parse", "HEAD"], {
        cwd: root,
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
    }).trim();
} catch (_error) {
    // Source archives may not include Git metadata; content hashes remain authoritative.
}
const manifestPayload = {
    version: "0.2.0",
    source_owner: "AgomTradePro",
    upstream_commit: upstreamCommit,
    build_id: `agomtui-runtime-0.2.0+${buildHash.slice(0, 12)}`,
    direction: "AgomTradePro -> AgOMTUI",
    contracts: {
        screen_dashboard_layouts: screenDashboardLayouts,
    },
    files,
};
if (check) {
    let current;
    try {
        current = JSON.parse(await readFile(manifestPath, "utf8"));
    } catch (_error) {
        throw new Error(`Invalid TUI manifest: ${manifestPath}`);
    }
    assertManifestIntegrity(current, manifestPayload, (commit) => {
        try {
            execFileSync("git", ["merge-base", "--is-ancestor", commit, "HEAD"], {
                cwd: root,
                stdio: "ignore",
            });
            return true;
        } catch (_error) {
            return false;
        }
    });
} else {
    await writeFile(manifestPath, `${JSON.stringify(manifestPayload, null, 2)}\n`, "utf8");
}
