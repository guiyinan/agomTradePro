const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const RUNTIME_SOURCE_OWNER = "AgomTradePro";

export function normalizeRuntimeContent(content) {
    const text = Buffer.isBuffer(content) ? content.toString("utf8") : String(content);
    return Buffer.from(text.replace(/\r\n/g, "\n"), "utf8");
}

export function runtimeContentsEqual(left, right) {
    return normalizeRuntimeContent(left).equals(normalizeRuntimeContent(right));
}

export function deterministicManifestPayload(manifest) {
    return {
        version: manifest.version,
        source_owner: manifest.source_owner,
        build_id: manifest.build_id,
        direction: manifest.direction,
        contracts: manifest.contracts,
        files: manifest.files,
    };
}

export function assertManifestIntegrity(current, expected, isAncestor = () => true) {
    if (!current || typeof current !== "object") {
        throw new Error("TUI manifest must be a JSON object");
    }
    if (current.source_owner !== RUNTIME_SOURCE_OWNER) {
        throw new Error(`TUI manifest source_owner must be ${RUNTIME_SOURCE_OWNER}`);
    }
    const actualPayload = deterministicManifestPayload(current);
    const expectedPayload = deterministicManifestPayload(expected);
    if (JSON.stringify(actualPayload) !== JSON.stringify(expectedPayload)) {
        throw new Error("TUI manifest content hashes are stale");
    }

    const commit = current.upstream_commit;
    if (commit === "unknown") {
        return;
    }
    if (typeof commit !== "string" || !COMMIT_PATTERN.test(commit)) {
        throw new Error("TUI manifest upstream_commit must be a lowercase 40-character SHA or unknown");
    }
    if (!isAncestor(commit)) {
        throw new Error("TUI manifest upstream_commit is not an ancestor of the current source tree");
    }
}
