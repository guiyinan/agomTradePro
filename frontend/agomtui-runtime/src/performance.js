export function mark(name) {
    if (globalThis.performance?.mark) {
        globalThis.performance.mark(`agomtui:${name}`);
    }
}

export function measure(name, start, end) {
    if (!globalThis.performance?.measure) {
        return null;
    }
    try {
        globalThis.performance.measure(
            `agomtui:${name}`,
            `agomtui:${start}`,
            `agomtui:${end}`,
        );
        return globalThis.performance.getEntriesByName(`agomtui:${name}`).at(-1) || null;
    } catch (_error) {
        return null;
    }
}
