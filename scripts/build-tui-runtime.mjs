import { build } from "esbuild";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
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

const manifestPath = resolve(root, "config/tui/agomtui-runtime.manifest.json");
const files = {};
for (const relative of [
    "frontend/agomtui-runtime/src/api.js",
    "frontend/agomtui-runtime/src/events.js",
    "frontend/agomtui-runtime/src/extensions.js",
    "frontend/agomtui-runtime/src/index.js",
    "frontend/agomtui-runtime/src/pagination.js",
    "frontend/agomtui-runtime/src/performance.js",
    "frontend/agomtui-runtime/src/state.js",
    "static/js/agomtui-runtime-core.js",
    "static/js/tui-workbench.js",
    "static/css/tui-workbench.css",
]) {
    const body = normalizeRuntimeContent(await readFile(resolve(root, relative)));
    files[relative] = createHash("sha256").update(body).digest("hex");
}
const buildHash = createHash("sha256")
    .update(Object.entries(files).map(([path, sha]) => `${path}:${sha}`).join("\n"))
    .digest("hex");
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
    upstream_commit: upstreamCommit,
    build_id: `agomtui-runtime-0.2.0+${buildHash.slice(0, 12)}`,
    direction: "AgomTradePro -> AgOMTUI",
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
