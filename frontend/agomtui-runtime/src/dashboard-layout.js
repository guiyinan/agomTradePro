const TASK_FLOW_LAYOUT = "task_flow";
const TWO_COLUMN_JOURNEYS = new Set(["self_service", "admin"]);

/**
 * Resolve the desktop dashboard column count from the published screen contract.
 *
 * Explicit metadata is authoritative. Host overrides exist only for legacy screens
 * that have not yet published a dashboard_layout contract, and journey remains a
 * bounded default rather than a screen-specific layout rule.
 */
export function dashboardDesktopColumns(screen = {}, host = {}) {
    const layout = String(screen?.dashboard_layout || "adaptive_grid").trim();
    if (layout === TASK_FLOW_LAYOUT) {
        return 1;
    }

    const screenKey = String(screen?.key || "").trim();
    const singleColumnScreens = Array.isArray(host?.singleColumnScreens)
        ? host.singleColumnScreens
        : [];
    if (screenKey && singleColumnScreens.includes(screenKey)) {
        return 1;
    }

    const journey = String(screen?.user_experience?.journey || "").trim();
    return TWO_COLUMN_JOURNEYS.has(journey) ? 2 : 3;
}
