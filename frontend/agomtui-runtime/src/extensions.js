const HOOK_NAMES = [
    "loadDashboardPanel",
    "loadNavigationBadges",
    "getHomeActions",
    "runHomeAction",
    "isOperatorHomeScreen",
    "inferHomeLane",
];

export function runtimeHooks(config = {}) {
    const hooks = config.hooks && typeof config.hooks === "object" ? config.hooks : {};
    return Object.fromEntries(
        HOOK_NAMES
            .filter((name) => typeof hooks[name] === "function")
            .map((name) => [name, hooks[name]]),
    );
}
