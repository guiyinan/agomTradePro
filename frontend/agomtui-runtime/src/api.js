export function createRuntimeUrls(config = {}) {
    const apiBase = String(config.apiBase || "/api/tui").replace(/\/+$/, "");
    const configuredBootstrap = config.bootstrapUrl;
    return {
        apiBase,
        catalog: () => `${apiBase}/catalog/`,
        screen: (screenKey) => `${apiBase}/screens/${encodeURIComponent(screenKey)}/`,
        action: (actionKey) => `${apiBase}/actions/${encodeURIComponent(actionKey)}/run/`,
        bootstrap: (screenKey = "") => {
            if (configuredBootstrap === false) {
                return "";
            }
            const base = String(configuredBootstrap || `${apiBase}/bootstrap/`);
            const separator = base.includes("?") ? "&" : "?";
            return screenKey ? `${base}${separator}screen_key=${encodeURIComponent(screenKey)}` : base;
        },
    };
}
