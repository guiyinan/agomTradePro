
    const runtimeCore = window.AgomTUIRuntimeCore || {};
    const state = {
        catalog: null,
        screen: null,
        screenBadges: {},
        screenBadgeDrilldowns: {},
        homePanelBadges: {},
        lastAction: null,
        lastParams: {},
        lastRaw: null,
        lastPager: null,
        currentViewModel: null,
        currentColumns: [],
        currentRows: [],
        visibleRows: [],
        selectedRowContext: null,
        filterText: "",
        selectedRowIndex: 0,
        activeMenu: null,
        lastFormTriggerRef: "",
        lastFormTriggerAt: 0,
        showSupportTasks: false,
        showAdvancedQueries: false,
        actionFilterText: "",
        completedActionsByScreen: {},
        railCollapsed: false,
        inspectorCollapsed: false,
        inspectorWidth: null,
        themeKey: "B",
        pinnedScreenKeys: new Set(),
        preferredHomeLane: "decision",
        lastNonHomeScreen: "",
        pendingRequestId: 0,
        latestRequestId: 0,
        pendingController: null,
        slowActionTimer: null,
        clientPage: 1,
        clientPageSize: 100,
        operatorHomePayload: null,
        operatorHomePromise: null,
        modalReturnFocus: null,
    };

    const els = {
        app: document.querySelector("[data-tui-app]"),
        railPanel: document.querySelector("[data-rail-panel]"),
        moduleTree: document.querySelector("[data-module-tree]"),
        screenTitle: document.querySelector("[data-screen-title]"),
        screenStatus: document.querySelector("[data-screen-status]"),
        actions: document.querySelector("[data-actions-panel]"),
        mainTitle: document.querySelector("[data-main-title]"),
        main: document.querySelector("[data-main-panel]"),
        workflowStrip: document.querySelector("[data-workflow-strip]"),
        inspector: document.querySelector("[data-inspector-panel]"),
        rawDrawer: document.querySelector("[data-raw-drawer]"),
        rawPanel: document.querySelector("[data-raw-panel]"),
        rawToggle: document.querySelector("[data-raw-toggle]"),
        rawClose: document.querySelector("[data-raw-close]"),
        pager: document.querySelector("[data-pager-status]"),
        clock: document.querySelector("[data-tui-clock]"),
        menuPopover: document.querySelector("[data-menu-popover]"),
        filterBar: document.querySelector("[data-filter-bar]"),
        filterInput: document.querySelector("[data-filter-input]"),
        filterClear: document.querySelector("[data-filter-clear]"),
        modal: document.querySelector("[data-tui-modal]"),
        modalTitle: document.querySelector("[data-modal-title]"),
        modalBody: document.querySelector("[data-modal-body]"),
        modalClose: document.querySelector("[data-modal-close]"),
        status: document.querySelector("[data-workbench-status]"),
        lastRefresh: document.querySelector("[data-last-refresh]"),
        currentLocation: document.querySelector("[data-current-location]"),
        railToggle: document.querySelector("[data-toggle-rail]"),
        inspectorShell: document.querySelector("[data-inspector-panel-shell]"),
        inspectorToggle: document.querySelector("[data-toggle-inspector]"),
        inspectorResizeHandle: document.querySelector("[data-inspector-resize-handle]"),
        themeStatus: document.querySelector("[data-theme-status]"),
        themeIndicatorCode: document.querySelector("[data-theme-indicator-code]"),
    };

    const menuItems = {
        file: [
            ["refresh", "刷新当前视图", "F5"],
            ["export", "导出当前表格", "F8"],
        ],
        module: [
            ["toggle-rail", "展开/收起模块导航", "F2"],
            ["previous-workflow", "上一个流程屏", "F3"],
            ["next-workflow", "下一个流程屏", "F4"],
        ],
        action: [
            ["run-next-primary", "执行下一主流程", "F6"],
            ["focus-actions", "定位任务区", "F9"],
            ["row-detail", "打开选中行", "Enter"],
        ],
        view: [
            ["filter", "筛选表格", "F7"],
            ["filter-actions", "筛选当前任务", "菜单"],
            ["toggle-inspector", "展开/收起说明栏", "F10"],
            ["reset-progress", "重置本屏进度", "菜单"],
            ["raw", "原始响应", "菜单"],
        ],
        help: [
            ["help", "键盘帮助", "F1"],
        ],
    };

    const HOTKEY_COMMANDS = {
        F1: "help",
        F2: "toggle-rail",
        F3: "previous-workflow",
        F4: "next-workflow",
        F5: "refresh",
        F6: "run-next-primary",
        F7: "filter",
        F8: "export",
        F9: "focus-actions",
        F10: "toggle-inspector",
    };

    const progressStorageKey = "agom-tui-primary-progress:v1";
    const themeStorageKey = "agom-tui-theme:v1";
    const inspectorWidthStorageKey = "agom-tui-inspector-width:v1";
    const lastNonHomeScreenStorageKey = "agom-tui-last-non-home-screen:v1";
    const pinnedScreensStorageKey = "agom-tui-pinned-screen-keys:v1";
    const preferredHomeLaneStorageKey = "agom-tui-preferred-home-lane:v1";
    const resumeOnBootStorageKey = "agom-tui-resume-on-boot:v1";
    const inspectorWidthMin = 220;
    const inspectorWidthMax = 640;
    const inspectorDesktopBreakpoint = 980;
    const inspectorMaxWidthRatio = 0.56;
    const actionTriggerGuardMs = 250;
    const actionFilterDebounceMs = 120;
    const dashboardIdleTimeoutMs = 250;
    const slowActionTimeoutMs = 15000;
    const maxTextFileBytes = 2 * 1024 * 1024;
    const THEME_SEQUENCE = ["A", "B", "C"];
    const THEME_TOKENS = {
        A: {
            background: "#001A8D",
            panelBackground: "#000B55",
            primaryText: "#FFFFFF",
            secondaryText: "#C0C0C0",
            border: "#00FFFF",
            highlight: "#FFFF00",
            accent: "#C0C0C0",
            success: "#00FF80",
            warning: "#FFFF00",
            error: "#FF4040",
            grid: "#002070",
        },
        B: {
            background: "#07090F",
            panelBackground: "#101827",
            primaryText: "#E8EEF8",
            secondaryText: "#AAB6C5",
            border: "#58708F",
            highlight: "#F7C948",
            accent: "#38BDF8",
            success: "#2EE59D",
            warning: "#F7C948",
            error: "#FF5A5F",
            grid: "#263449",
        },
        C: {
            background: "#02060A",
            panelBackground: "#071018",
            primaryText: "#BFFFE0",
            secondaryText: "#6FAF93",
            border: "#123B33",
            highlight: "#39FF88",
            accent: "#2DE2E6",
            success: "#39FF88",
            warning: "#FFCC66",
            error: "#FF3B3B",
            grid: "#0E2A24",
        },
    };

    const runtimeConfig = window.__AGOMTUI_RUNTIME__ || {};
    const apiBase = String(runtimeConfig.apiBase || "/api/tui").replace(/\/+$/, "");
    const runtimeUrls = typeof runtimeCore.createRuntimeUrls === "function"
        ? runtimeCore.createRuntimeUrls(runtimeConfig)
        : null;
    const runtimeHooks = typeof runtimeCore.runtimeHooks === "function"
        ? runtimeCore.runtimeHooks(runtimeConfig)
        : (runtimeConfig.hooks || {});
    const allowSvgDataImages = runtimeConfig.allowSvgDataImages !== false;
    const rendererRegistry = new Map();

    function browserStorage(storageName) {
        try {
            return window[storageName] || null;
        } catch (_error) {
            return null;
        }
    }

    function safeStorageGet(storageName, key, fallback = null) {
        try {
            return browserStorage(storageName)?.getItem(key) ?? fallback;
        } catch (_error) {
            return fallback;
        }
    }

    function safeStorageSet(storageName, key, value) {
        try {
            browserStorage(storageName)?.setItem(key, value);
        } catch (_error) {
            // Persisted UI state is optional; the current session remains usable.
        }
    }

    function safeStorageRemove(storageName, key) {
        try {
            browserStorage(storageName)?.removeItem(key);
        } catch (_error) {
            // Persisted UI state is optional; the current session remains usable.
        }
    }
    const builtInRendererNames = new Set([
        "datagrid",
        "detail",
        "message",
        "chart",
        "image",
        "line",
        "bar",
        "pie",
        "kpi-trend",
        "kpi_trend",
        "table-chart",
        "table_chart",
        "host-slot",
        "host_slot",
    ]);
    function registerRenderer(name, rendererFn) {
        const rendererName = String(name || "").trim();
        if (!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(rendererName) || typeof rendererFn !== "function") {
            return false;
        }
        rendererRegistry.set(rendererName, rendererFn);
        return true;
    }

    const previousRendererApi = window.AgomTUIRenderers || {};
    window.AgomTUIRenderers = {
        register: registerRenderer,
        get(name) {
            return rendererRegistry.get(String(name || "").trim()) || null;
        },
        has(name) {
            return rendererRegistry.has(String(name || "").trim());
        },
    };
    if (Array.isArray(previousRendererApi.pending)) {
        previousRendererApi.pending.forEach((item) => {
            if (Array.isArray(item)) {
                registerRenderer(item[0], item[1]);
            }
        });
    }

    function catalogUrl() {
        return runtimeUrls ? runtimeUrls.catalog() : `${apiBase}/catalog/`;
    }

    function screenUrl(screenKey) {
        return runtimeUrls ? runtimeUrls.screen(screenKey) : `${apiBase}/screens/${encodeURIComponent(screenKey)}/`;
    }

    function actionRunUrl(actionKey) {
        return runtimeUrls ? runtimeUrls.action(actionKey) : `${apiBase}/actions/${encodeURIComponent(actionKey)}/run/`;
    }

    function bootstrapUrl(screenKey = "") {
        return runtimeUrls ? runtimeUrls.bootstrap(screenKey) : "";
    }

    function operatorHomeUrl() {
        return String(runtimeConfig.host?.operatorHomeUrl || "");
    }

    function governanceQueueUrl(domain = "") {
        const baseUrl = String(runtimeConfig.host?.governanceQueueUrl || "");
        if (!baseUrl) {
            return "";
        }
        const suffix = domain ? `?domain=${encodeURIComponent(domain)}` : "";
        return `${baseUrl}${suffix}`;
    }

    function isOperatorHomeScreen(screenKey) {
        if (typeof runtimeHooks.isOperatorHomeScreen === "function") {
            return Boolean(runtimeHooks.isOperatorHomeScreen(screenKey));
        }
        return false;
    }

    function isHomeClientAction(actionKey) {
        return (runtimeConfig.host?.homeActionKeys || []).includes(String(actionKey || ""));
    }

    function operatorHomePanelSectionKey(panel) {
        const actionKey = String(panel?.action_key || "").trim();
        const prefix = String(runtimeConfig.host?.homePanelActionPrefix || "");
        if (!prefix || !actionKey.startsWith(prefix)) {
            return "";
        }
        if (isHomeClientAction(actionKey)) {
            return "";
        }
        return actionKey.slice(prefix.length);
    }

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (char) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        }[char]));
    }

    function badgeCountsFromRows(rows) {
        return (rows || []).reduce((counts, row) => {
            const severity = String(row?.severity || "").trim().toLowerCase();
            if (severity === "blocked") {
                counts.blockedCount += 1;
            } else if (severity === "warning") {
                counts.warningCount += 1;
            }
            return counts;
        }, { blockedCount: 0, warningCount: 0 });
    }

    function sumBadgeCounts(badges) {
        return (badges || []).reduce((counts, badge) => {
            counts.blockedCount += Number(badge?.blockedCount || 0);
            counts.warningCount += Number(badge?.warningCount || 0);
            return counts;
        }, { blockedCount: 0, warningCount: 0 });
    }

    function badgeCountsForScreenKeys(screenKeys) {
        return sumBadgeCounts(
            (screenKeys || []).map((screenKey) => state.screenBadges[screenKey] || {})
        );
    }

    function hasBadgeCounts(badge) {
        return Number(badge?.blockedCount || 0) > 0 || Number(badge?.warningCount || 0) > 0;
    }

    function badgeMarkup(badge, options = {}) {
        if (!hasBadgeCounts(badge)) {
            return "";
        }
        const blockedCount = Number(badge?.blockedCount || 0);
        const warningCount = Number(badge?.warningCount || 0);
        const severity = blockedCount > 0 ? "blocked" : "warning";
        const count = blockedCount > 0 ? blockedCount : warningCount;
        const label = blockedCount > 0 ? "阻断" : "预警";
        const extraClass = options.compact ? " tui-badge--compact" : "";
        return `<span class="tui-badge tui-badge--${escapeHtml(severity)}${extraClass}" aria-label="${escapeHtml(label)} ${count}">${escapeHtml(count)}</span>`;
    }

    function badgeSeverityRank(severity) {
        if (severity === "blocked") {
            return 0;
        }
        if (severity === "warning") {
            return 1;
        }
        return 2;
    }

    function badgeDrilldownsByScreen(items) {
        return (items || []).reduce((next, item) => {
            const severity = String(item?.severity || "").trim().toLowerCase();
            const screenKey = String(item?.target_screen || "").trim();
            const actionKey = String(item?.target_action_key || "").trim();
            if (!["blocked", "warning"].includes(severity) || !screenKey || !actionKey) {
                return next;
            }
            const candidate = {
                screenKey,
                actionKey,
                severity,
                title: String(item?.title || "").trim(),
                nextAction: String(item?.next_action || "").trim(),
            };
            const existing = next[screenKey];
            if (!existing || badgeSeverityRank(severity) < badgeSeverityRank(existing.severity)) {
                next[screenKey] = candidate;
            }
            return next;
        }, {});
    }

    function badgeDrilldownForScreen(screenKey) {
        return state.screenBadgeDrilldowns[String(screenKey || "").trim()] || null;
    }

    function actionFormElement(action) {
        if (!action) {
            return null;
        }
        return els.actions.querySelector(
            `[data-action-ui-key="${CSS.escape(actionUiKey(action))}"]`
        );
    }

    function screenBadgeMarkup(screenKey) {
        const badge = state.screenBadges[screenKey];
        if (!hasBadgeCounts(badge)) {
            return "";
        }
        const drilldown = badgeDrilldownForScreen(screenKey);
        const badgeHtml = badgeMarkup(badge, { compact: true });
        if (!drilldown?.actionKey) {
            return badgeHtml;
        }
        const title = drilldown.title || drilldown.nextAction || "查看治理摘要";
        return `
            <button
                class="tui-badge-button"
                type="button"
                data-badge-screen-key="${escapeHtml(screenKey)}"
                title="${escapeHtml(title)}"
                aria-label="${escapeHtml(title)}"
            >${badgeHtml}</button>
        `;
    }

    async function openScreenFromCatalog(screenKey) {
        const normalizedKey = String(screenKey || "").trim();
        if (!normalizedKey) {
            return null;
        }
        const drilldown = badgeDrilldownForScreen(normalizedKey);
        if (!drilldown?.actionKey) {
            return loadScreen(normalizedKey);
        }
        const screenSpec = await loadScreen(normalizedKey, { suppressAutoAction: true });
        if (!screenSpec) {
            return screenSpec;
        }
        const action = currentAction(drilldown.actionKey);
        if (!action) {
            return screenSpec;
        }
        await runAction(action.key, actionFormElement(action));
        return screenSpec;
    }

    function getCookie(name) {
        const cookies = document.cookie ? document.cookie.split(";") : [];
        for (const cookie of cookies) {
            const [rawKey, ...rawValue] = cookie.trim().split("=");
            if (rawKey === name) {
                return decodeURIComponent(rawValue.join("="));
            }
        }
        return "";
    }

    function setStatus(message) {
        if (els.status) {
            els.status.textContent = message;
        }
    }

    function normalizeThemeKey(themeKey) {
        return THEME_SEQUENCE.includes(themeKey) ? themeKey : "B";
    }

    function hexToRgb(hex) {
        const normalized = String(hex || "").replace("#", "");
        if (!/^[0-9a-f]{6}$/i.test(normalized)) {
            return null;
        }
        return {
            r: Number.parseInt(normalized.slice(0, 2), 16),
            g: Number.parseInt(normalized.slice(2, 4), 16),
            b: Number.parseInt(normalized.slice(4, 6), 16),
        };
    }

    function rgbaFromHex(hex, alpha) {
        const rgb = hexToRgb(hex);
        if (!rgb) {
            return `rgba(0, 0, 0, ${alpha})`;
        }
        return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
    }

    function svgArrowDataUrl(direction, color) {
        const fill = encodeURIComponent(String(color || "#ffffff"));
        const paths = {
            up: "M8 4 L3 11 H13 Z",
            down: "M3 6 H13 L8 13 Z",
            left: "M4 8 L11 3 V13 Z",
            right: "M6 3 L13 8 L6 13 Z",
        };
        return `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='17' height='17' viewBox='0 0 17 17'%3E%3Cpath d='${paths[direction]}' fill='${fill}'/%3E%3C/svg%3E")`;
    }

    function applyTheme(themeKey, options = {}) {
        const resolvedThemeKey = normalizeThemeKey(themeKey);
        const theme = THEME_TOKENS[resolvedThemeKey];
        const root = document.documentElement;
        const variables = {
            "--tui-bg": theme.background,
            "--tui-bg-deep": theme.background,
            "--tui-panel": theme.panelBackground,
            "--tui-panel-strong": theme.border,
            "--tui-border": theme.border,
            "--tui-border-dim": theme.grid,
            "--tui-text": theme.primaryText,
            "--tui-muted": theme.secondaryText,
            "--tui-inverse": theme.background,
            "--tui-command": theme.background,
            "--tui-accent": theme.highlight,
            "--tui-accent-strong": theme.accent,
            "--tui-warn": theme.warning,
            "--tui-danger": theme.error,
            "--tui-green": theme.success,
            "--tui-scroll-face": theme.border,
            "--tui-scroll-light": theme.primaryText,
            "--tui-scroll-track": theme.grid,
            "--tui-scroll-shadow": theme.background,
            "--tui-scroll-dark": theme.background,
            "--tui-menubar-bg": theme.grid,
            "--tui-menubar-text": theme.primaryText,
            "--tui-footer-bg": theme.grid,
            "--tui-footer-text": theme.primaryText,
            "--tui-footer-divider": theme.border,
            "--tui-footer-hotkey": theme.highlight,
            "--tui-footer-emphasis": theme.warning,
            "--tui-system-source-accent": theme.accent,
            "--tui-grid-strong": rgbaFromHex(theme.primaryText, 0.66),
            "--tui-overlay": rgbaFromHex(theme.background, 0.82),
            "--tui-scroll-arrow-up": svgArrowDataUrl("up", theme.primaryText),
            "--tui-scroll-arrow-down": svgArrowDataUrl("down", theme.primaryText),
            "--tui-scroll-arrow-left": svgArrowDataUrl("left", theme.primaryText),
            "--tui-scroll-arrow-right": svgArrowDataUrl("right", theme.primaryText),
        };
        Object.entries(variables).forEach(([name, value]) => {
            root.style.setProperty(name, value);
        });
        root.dataset.tuiTheme = resolvedThemeKey;
        state.themeKey = resolvedThemeKey;
        if (els.themeStatus) {
            els.themeStatus.textContent = `STYLE: ${resolvedThemeKey}`;
        }
        if (els.themeIndicatorCode) {
            els.themeIndicatorCode.textContent = `T:${resolvedThemeKey}`;
        }
        if (!options.silent) {
            safeStorageSet("localStorage", themeStorageKey, resolvedThemeKey);
        }
        return resolvedThemeKey;
    }

    function loadStoredTheme() {
        return normalizeThemeKey(safeStorageGet("localStorage", themeStorageKey, "B"));
    }

    function cycleTheme() {
        const currentIndex = THEME_SEQUENCE.indexOf(normalizeThemeKey(state.themeKey));
        const nextKey = THEME_SEQUENCE[(currentIndex + 1) % THEME_SEQUENCE.length];
        applyTheme(nextKey);
        setStatus(`主题已切换: ${nextKey}`);
    }

    function twoDigits(value) {
        return String(value).padStart(2, "0");
    }

    function currentDateTime() {
        const now = new Date();
        return [
            now.getFullYear(),
            twoDigits(now.getMonth() + 1),
            twoDigits(now.getDate()),
        ].join("-") + " " + [
            twoDigits(now.getHours()),
            twoDigits(now.getMinutes()),
            twoDigits(now.getSeconds()),
        ].join(":");
    }

    function setLastRefresh() {
        if (els.lastRefresh) {
            els.lastRefresh.textContent = currentDateTime();
        }
    }

    function setCurrentLocation(action) {
        if (!els.currentLocation) {
            return;
        }
        const screen = state.screen?.screen || {};
        const module = state.screen?.module || {};
        const screenKey = screen.key || "boot";
        const address = action?.key
            ? `screen:${screenKey} action:${action.key}`
            : `screen:${screenKey}`;
        const labelPath = [
            module.label,
            screen.label,
            action?.label,
        ].filter(Boolean).join(" / ");
        if (els.currentLocation.value !== address) {
            els.currentLocation.value = address;
        }
        els.currentLocation.dataset.currentAddress = address;
        els.currentLocation.title = labelPath ? `${labelPath} | ${address}` : address;
    }

    function screenKeyFromLocationInput(value) {
        const rawValue = String(value || "").trim();
        if (!rawValue) {
            return "";
        }
        const screenMatch = rawValue.match(/^screen:([^\s]+)(?:\s+action:.+)?$/i);
        if (screenMatch) {
            return screenMatch[1];
        }
        if (/^[a-z0-9][a-z0-9._-]*$/i.test(rawValue)) {
            return rawValue;
        }
        return "";
    }

    function resetLocationInput() {
        if (!els.currentLocation) {
            return;
        }
        els.currentLocation.value = els.currentLocation.dataset.currentAddress || `screen:${state.screen?.screen?.key || "boot"}`;
    }

    function submitLocationInput() {
        if (!els.currentLocation) {
            return;
        }
        const screenKey = screenKeyFromLocationInput(els.currentLocation.value);
        if (!screenKey) {
            resetLocationInput();
            setStatus("位置格式无效");
            return;
        }
        els.currentLocation.blur();
        loadScreen(screenKey);
    }

    function loadStoredProgress() {
        try {
            const raw = safeStorageGet("sessionStorage", progressStorageKey);
            if (!raw) {
                return;
            }
            const parsed = JSON.parse(raw);
            Object.entries(parsed || {}).forEach(([screenKey, actionKeys]) => {
                if (Array.isArray(actionKeys)) {
                    state.completedActionsByScreen[screenKey] = new Set(actionKeys.filter(Boolean));
                }
            });
        } catch (error) {
            state.completedActionsByScreen = {};
        }
    }

    function loadStoredOperatorState() {
        try {
            state.lastNonHomeScreen = String(
                safeStorageGet("localStorage", lastNonHomeScreenStorageKey, "")
            ).trim();
            const storedLane = String(
                safeStorageGet("localStorage", preferredHomeLaneStorageKey, "decision")
            ).trim();
            state.preferredHomeLane = storedLane === "governance" ? "governance" : "decision";
            const rawPinned = safeStorageGet("localStorage", pinnedScreensStorageKey);
            const parsed = rawPinned ? JSON.parse(rawPinned) : [];
            state.pinnedScreenKeys = new Set(
                Array.isArray(parsed)
                    ? parsed.map((value) => String(value || "").trim()).filter(Boolean)
                    : []
            );
        } catch (_error) {
            state.lastNonHomeScreen = "";
            state.preferredHomeLane = "decision";
            state.pinnedScreenKeys = new Set();
        }
    }

    function persistProgress() {
        try {
            const serializable = {};
            Object.entries(state.completedActionsByScreen || {}).forEach(([screenKey, actionSet]) => {
                if (actionSet && actionSet.size) {
                    serializable[screenKey] = Array.from(actionSet);
                }
            });
            safeStorageSet("sessionStorage", progressStorageKey, JSON.stringify(serializable));
        } catch (error) {
            // Session progress is a UI convenience; ignore storage failures.
        }
    }

    function persistLastNonHomeScreen(screenKey) {
        const normalizedKey = String(screenKey || "").trim();
        state.lastNonHomeScreen = normalizedKey;
        if (normalizedKey) {
            safeStorageSet("localStorage", lastNonHomeScreenStorageKey, normalizedKey);
        } else {
            safeStorageRemove("localStorage", lastNonHomeScreenStorageKey);
        }
    }

    function persistPreferredHomeLane(lane) {
        state.preferredHomeLane = lane === "governance" ? "governance" : "decision";
        safeStorageSet("localStorage", preferredHomeLaneStorageKey, state.preferredHomeLane);
    }

    function persistPinnedScreens() {
        safeStorageSet(
            "localStorage",
            pinnedScreensStorageKey,
            JSON.stringify(Array.from(state.pinnedScreenKeys))
        );
    }

    function shouldResumeOnBoot() {
        return safeStorageGet("sessionStorage", resumeOnBootStorageKey) === "1";
    }

    function clearResumeOnBootFlag() {
        safeStorageRemove("sessionStorage", resumeOnBootStorageKey);
    }

    function markResumeOnBoot() {
        if (state.screen?.screen?.key && !isOperatorHomeScreen(state.screen.screen.key)) {
            safeStorageSet("sessionStorage", resumeOnBootStorageKey, "1");
        } else {
            safeStorageRemove("sessionStorage", resumeOnBootStorageKey);
        }
    }

    function openCliSurface() {
        window.open("/terminal/", "_blank", "noopener,noreferrer");
        setStatus("CLI 已在新标签页打开");
    }

    function restoreLastWorkspace() {
        const target = String(state.lastNonHomeScreen || "").trim();
        if (!target) {
            setStatus("没有可恢复的最近工作区");
            return false;
        }
        loadScreen(target);
        return true;
    }

    function executeHomeAction(actionKey) {
        const normalizedKey = String(actionKey || "").trim();
        if (typeof runtimeHooks.runHomeAction === "function") {
            return Boolean(runtimeHooks.runHomeAction(normalizedKey, {
                loadScreen,
                openCliSurface,
                persistPreferredLane: persistPreferredHomeLane,
                restoreLastWorkspace,
            }));
        }
        return false;
    }

    function inferLaneFromScreen(screen) {
        if (typeof runtimeHooks.inferHomeLane === "function") {
            return String(runtimeHooks.inferHomeLane(screen) || "");
        }
        return "";
    }

    function badgeCountsByScreen(items) {
        const next = {};
        (items || []).forEach((item) => {
            const severity = String(item?.severity || "").trim().toLowerCase();
            if (!["blocked", "warning"].includes(severity)) {
                return;
            }
            const screenKey = String(item?.target_screen || "").trim();
            if (!screenKey) {
                return;
            }
            if (!next[screenKey]) {
                next[screenKey] = { blockedCount: 0, warningCount: 0 };
            }
            if (severity === "blocked") {
                next[screenKey].blockedCount += 1;
            } else {
                next[screenKey].warningCount += 1;
            }
        });
        return next;
    }

    function refreshVisibleHomePanelBadges() {
        if (!isOperatorHomeScreen(state.screen?.screen?.key) || !els.main) {
            return;
        }
        els.main.querySelectorAll("[data-dashboard-panel]").forEach((panelElement) => {
            const panelKey = panelElement.dataset.dashboardPanel;
            const badge = state.homePanelBadges[panelKey];
            const badgeHost = panelElement.querySelector("[data-panel-badge]");
            if (!badgeHost) {
                return;
            }
            badgeHost.innerHTML = badgeMarkup(badge, { compact: true });
        });
    }

    function applyNavigationBadges(navigationBadges) {
        const counts = navigationBadges?.counts_by_screen || {};
        state.screenBadges = Object.fromEntries(
            Object.entries(counts).map(([screenKey, value]) => [
                screenKey,
                {
                    blockedCount: Number(value?.blocked_count || 0),
                    warningCount: Number(value?.warning_count || 0),
                },
            ]),
        );
        if (state.catalog) {
            refreshCatalogBadges();
        }
        refreshVisibleHomePanelBadges();
    }

    async function loadOperatorHomeAggregate() {
        if (state.operatorHomePayload) {
            return state.operatorHomePayload;
        }
        if (!state.operatorHomePromise) {
            const url = operatorHomeUrl();
            if (!url) {
                return null;
            }
            state.operatorHomePromise = fetchJson(url)
                .then((payload) => {
                    state.operatorHomePayload = payload;
                    applyNavigationBadges(payload?.navigation_badges);
                    return payload;
                })
                .finally(() => {
                    state.operatorHomePromise = null;
                });
        }
        return state.operatorHomePromise;
    }

    async function refreshGovernanceBadges() {
        try {
            if (typeof runtimeHooks.loadNavigationBadges === "function") {
                const navigationBadges = await runtimeHooks.loadNavigationBadges({
                    fetchJson,
                    screen: state.screen,
                });
                if (navigationBadges) {
                    applyNavigationBadges(navigationBadges);
                    return;
                }
            }
            if (isOperatorHomeScreen(state.screen?.screen?.key)) {
                await loadOperatorHomeAggregate();
                return;
            }
        } catch (_error) {
            return;
        }
        const queueUrl = governanceQueueUrl();
        if (!queueUrl) {
            return;
        }
        try {
            const payload = await fetchJson(queueUrl);
            state.screenBadges = badgeCountsByScreen(payload.items || []);
            state.screenBadgeDrilldowns = badgeDrilldownsByScreen(payload.items || []);
            if (state.catalog) {
                refreshCatalogBadges();
            }
            refreshVisibleHomePanelBadges();
        } catch (_error) {
            state.screenBadges = {};
            state.screenBadgeDrilldowns = {};
            if (state.catalog) {
                refreshCatalogBadges();
            }
        }
    }

    function inspectorGrid() {
        return els.inspectorShell?.closest?.(".tui-workspace-grid") || null;
    }

    function inspectorWidthBounds() {
        const grid = inspectorGrid();
        if (!grid || window.matchMedia?.(`(max-width: ${inspectorDesktopBreakpoint}px)`)?.matches) {
            return null;
        }
        const gridWidth = grid.getBoundingClientRect().width || window.innerWidth;
        const max = Math.max(inspectorWidthMin, Math.min(inspectorWidthMax, Math.round(gridWidth * inspectorMaxWidthRatio)));
        return { min: inspectorWidthMin, max };
    }

    function clampInspectorWidth(width) {
        const bounds = inspectorWidthBounds();
        if (!bounds) {
            return null;
        }
        return Math.round(Math.min(bounds.max, Math.max(bounds.min, Number(width) || bounds.min)));
    }

    function applyInspectorWidth(width, options = {}) {
        const grid = inspectorGrid();
        const nextWidth = clampInspectorWidth(width);
        if (!grid || !nextWidth) {
            return null;
        }
        state.inspectorWidth = nextWidth;
        grid.style.setProperty("--tui-inspector-user-width", `${nextWidth}px`);
        if (els.inspectorResizeHandle) {
            const bounds = inspectorWidthBounds();
            els.inspectorResizeHandle.setAttribute("aria-valuemin", String(bounds?.min || inspectorWidthMin));
            els.inspectorResizeHandle.setAttribute("aria-valuemax", String(bounds?.max || inspectorWidthMax));
            els.inspectorResizeHandle.setAttribute("aria-valuenow", String(nextWidth));
        }
        if (options.persist) {
            safeStorageSet("localStorage", inspectorWidthStorageKey, String(nextWidth));
        }
        return nextWidth;
    }

    function loadStoredInspectorWidth() {
        const rawWidth = safeStorageGet("localStorage", inspectorWidthStorageKey);
        if (rawWidth === null || rawWidth === undefined) {
            return;
        }
        const storedWidth = Number(rawWidth);
        if (Number.isFinite(storedWidth)) {
            applyInspectorWidth(storedWidth);
        }
    }

    function riskLabel(risk) {
        const labels = {
            read: "立即打开",
            ai: "AI 协助",
            write: "提交确认",
            unsafe: "受限工具",
            admin: "管理工具",
        };
        return labels[String(risk || "").toLowerCase()] || "任务";
    }

    function actionVerbLabel(action) {
        const risk = String(action.risk || "read").toLowerCase();
        const intent = String(action.intent || "").toLowerCase();
        const label = String(action.label || "").toLowerCase();
        if (risk === "write") {
            return "提交变更";
        }
        if (risk === "admin") {
            return action.method === "GET" ? "打开管理视图" : "提交管理变更";
        }
        if (risk === "ai") {
            return "发起问答";
        }
        if ((action.fields || []).some((field) => field.input_type !== "hidden")) {
            return "按条件查询";
        }
        if (intent.includes("health") || intent.includes("status") || label.includes("检查")) {
            return "运行检查";
        }
        if (action.view_type === "datagrid") {
            return "打开清单";
        }
        if (action.view_type === "detail" || action.view_type === "status") {
            return "查看详情";
        }
        return "生成视图";
    }

    function actionRoleLabel(action) {
        const tier = actionTier(action);
        const risk = String(action.risk || "read").toLowerCase();
        if (tier === "operation") {
            if (risk === "ai") {
                return "AI 操作";
            }
            if (risk === "write") {
                return "可执行操作";
            }
            if (risk === "admin") {
                return "管理操作";
            }
            return "操作";
        }
        if (tier === "primary") {
            return "主流程";
        }
        if (tier === "advanced") {
            return "条件查询";
        }
        return "支撑检查";
    }

    function actionMetaLabel(action, completed) {
        const parts = [];
        if (completed) {
            parts.push("已完成");
        }
        parts.push(actionRoleLabel(action));
        parts.push(actionVerbLabel(action));
        const visibleFields = (action.fields || []).filter((field) => field.input_type !== "hidden").length;
        if (visibleFields) {
            parts.push(`${visibleFields} 项参数`);
        }
        if (action.confirmation_required) {
            parts.push("执行前确认");
        }
        return parts.join(" / ");
    }

    function viewLabel(viewType) {
        const labels = {
            status: "状态",
            detail: "详情",
            datagrid: "表格",
            message: "说明",
            queue_workbench: "队列",
            auto: "自动",
        };
        return labels[String(viewType || "").toLowerCase()] || "工作区";
    }

    function operatorText(value) {
        return String(value ?? "")
            .replace(/自动批准的只读/g, "已发布的")
            .replace(/只读详情工具/g, "详情工具")
            .replace(/只读/g, "可查看")
            .replace(/读取业务视图/g, "打开业务视图")
            .replace(/直接读取/g, "直接打开");
    }

    function humanizeRowKey(key) {
        const labels = {
            account_id: "账户ID",
            asset_code: "标的代码",
            asset_codes: "资产代码",
            fund_code: "基金代码",
            id: "ID",
            pk: "记录ID",
            portfolio_id: "组合ID",
            provider_id: "数据源ID",
            risk_level: "风险等级",
            short_code: "短码",
            task_id: "任务ID",
        };
        const normalized = String(key || "");
        if (labels[normalized]) {
            return labels[normalized];
        }
        return normalized
            .replace(/[_-]+/g, " ")
            .replace(/\b\w/g, (char) => char.toUpperCase())
            .replace(/\bId\b/g, "ID")
            .replace(/\bPct\b/g, "比例")
            .replace(/\bAt\b/g, "时间");
    }

    function rowLabelForKey(key) {
        const column = state.currentColumns.find((item) => item.key === key);
        return column?.label || humanizeRowKey(key);
    }

    function rowDisplayRows(row, limit = Infinity) {
        if (!row) {
            return [];
        }
        const orderedKeys = [];
        state.currentColumns.forEach((column) => {
            if (Object.prototype.hasOwnProperty.call(row, column.key)) {
                orderedKeys.push(column.key);
            }
        });
        Object.keys(row).forEach((key) => {
            if (key.startsWith("__")) {
                return;
            }
            if (!orderedKeys.includes(key)) {
                orderedKeys.push(key);
            }
        });
        return orderedKeys.slice(0, limit).map((key) => [rowLabelForKey(key), row[key]]);
    }

    function actionUiKey(action) {
        return action.ui_key || action.key;
    }

    function currentAction(actionRef) {
        return ((state.screen && state.screen.actions) || [])
            .find((action) => action.key === actionRef || actionUiKey(action) === actionRef) || null;
    }

    function actionRefFromForm(form) {
        return form?.dataset?.actionUiKey || form?.dataset?.actionKey || "";
    }

    function triggerActionForm(form) {
        const actionRef = actionRefFromForm(form);
        if (!actionRef) {
            setStatus("任务未找到");
            return;
        }
        const now = Date.now();
        if (state.lastFormTriggerRef === actionRef && now - state.lastFormTriggerAt < actionTriggerGuardMs) {
            return;
        }
        state.lastFormTriggerRef = actionRef;
        state.lastFormTriggerAt = now;
        runAction(actionRef, form);
    }

    async function fetchJson(url, options) {
        const requestOptions = options || {};
        const method = (requestOptions.method || "GET").toUpperCase();
        const headers = {
            "Accept": "application/json",
            ...(requestOptions.headers || {}),
        };
        if (method !== "GET") {
            headers["Content-Type"] = "application/json";
            headers["X-CSRFToken"] = getCookie("csrftoken");
        }
        const response = await fetch(url, {
            credentials: "same-origin",
            ...requestOptions,
            headers,
        });
        const contentType = response.headers.get("content-type") || "";
        if (!response.ok) {
            let errorPayload = null;
            if (contentType.includes("application/json")) {
                try {
                    errorPayload = await response.json();
                } catch (parseError) {
                    errorPayload = null;
                }
            }
            const error = new Error("业务请求未完成");
            error.status = response.status;
            error.payload = errorPayload;
            throw error;
        }
        if (!contentType.includes("application/json")) {
            throw new Error("业务数据格式不可渲染");
        }
        return response.json();
    }

    function boundedTuiError(error) {
        const statusCode = Number(error?.status || 0);
        const payload = error?.payload && typeof error.payload === "object" ? error.payload : {};
        const isStructured = String(payload.error_code || "").startsWith("tui_");
        const defaults = {
            403: ["无权访问", "当前账号不能完成这项操作。"],
            404: ["内容不存在", "目标内容没有发布，或已被移除。"],
            502: ["服务暂时不可用", "服务暂时无法完成请求，请稍后重试。"],
            503: ["服务正在恢复", "服务尚未就绪，请稍后重试。"],
        };
        const fallback = defaults[statusCode] || ["暂时无法完成请求", "请稍后重试，或返回可用工作区。"];
        const recoveryActions = isStructured && Array.isArray(payload.recovery_actions)
            ? payload.recovery_actions
                .filter((item) => item && typeof item === "object" && item.screen_key)
                .map((item) => ({
                    label: String(item.label || "前往可用工作区"),
                    screenKey: String(item.screen_key),
                }))
            : [];
        return {
            title: isStructured ? String(payload.title || fallback[0]) : fallback[0],
            detail: isStructured ? String(payload.detail || fallback[1]) : fallback[1],
            traceId: isStructured ? String(payload.trace_id || "") : "",
            recoveryActions,
        };
    }

    function renderDashboardPanelError(panel, error) {
        const bounded = boundedTuiError(error);
        return `
            <div class="tui-panel-error" role="status">
                <strong>${escapeHtml(bounded.title)}</strong>
                <p>${escapeHtml(bounded.detail)}</p>
                ${bounded.traceId ? `<small>追踪编号：${escapeHtml(bounded.traceId)}</small>` : ""}
                <div class="tui-panel-error-actions">
                    <button class="tui-panel-retry" type="button" data-panel-retry>重试</button>
                    ${bounded.recoveryActions.map((item) => `
                        <button
                            class="tui-panel-recovery"
                            type="button"
                            data-panel-recovery-screen="${escapeHtml(item.screenKey)}"
                        >${escapeHtml(item.label)}</button>
                    `).join("")}
                </div>
                ${panel.note ? `<small>${escapeHtml(panel.note)}</small>` : ""}
            </div>
        `;
    }

    function bindDashboardPanelRecovery(root, panel) {
        root.querySelector("[data-panel-retry]")?.addEventListener("click", () => loadDashboardPanel(panel));
        root.querySelectorAll("[data-panel-recovery-screen]").forEach((button) => {
            button.addEventListener("click", () => loadScreen(button.dataset.panelRecoveryScreen));
        });
    }

    function renderBoundedApplicationError(error, options = {}) {
        if (runtimeConfig.debug === true && window.console?.error) {
            window.console.error("TUI request failed", error);
        }
        const bounded = boundedTuiError(error);
        els.mainTitle.textContent = bounded.title;
        els.main.innerHTML = `
            <section class="tui-application-error" role="alert">
                <strong>${escapeHtml(bounded.title)}</strong>
                <p>${escapeHtml(bounded.detail)}</p>
                ${bounded.traceId ? `<small>追踪编号：${escapeHtml(bounded.traceId)}</small>` : ""}
                <div class="tui-panel-error-actions">
                    <button class="tui-panel-retry" type="button" data-application-retry>重试</button>
                    ${bounded.recoveryActions.map((item) => `
                        <button
                            class="tui-panel-recovery"
                            type="button"
                            data-panel-recovery-screen="${escapeHtml(item.screenKey)}"
                        >${escapeHtml(item.label)}</button>
                    `).join("")}
                </div>
            </section>
        `;
        els.main.querySelector("[data-application-retry]")?.addEventListener("click", () => {
            const screenKey = String(options.retryScreenKey || state.screen?.screen?.key || state.catalog?.default_screen || "home");
            loadScreen(screenKey);
        });
        els.main.querySelectorAll("[data-panel-recovery-screen]").forEach((button) => {
            button.addEventListener("click", () => loadScreen(button.dataset.panelRecoveryScreen));
        });
        setStatus("请求未完成");
    }

    let requestSequence = 0;

    function clearPendingRequest(options = {}) {
        const { abort = false } = options;
        if (state.slowActionTimer) {
            window.clearTimeout(state.slowActionTimer);
            state.slowActionTimer = null;
        }
        if (abort && state.pendingController) {
            try {
                state.pendingController.abort();
            } catch (error) {
                // Ignore abort races on already-settled requests.
            }
        }
        state.pendingController = null;
        state.pendingRequestId = 0;
    }

    function startPendingRequest(controller) {
        clearPendingRequest({ abort: true });
        requestSequence += 1;
        state.pendingRequestId = requestSequence;
        state.latestRequestId = requestSequence;
        state.pendingController = controller;
        return state.pendingRequestId;
    }

    function isLatestRequest(requestId) {
        return requestId === state.latestRequestId;
    }

    function renderActionLoadingState(action, screenSpec, options = {}) {
        const waitingCopy = options.waitingCopy || "正在读取业务数据...";
        els.main.innerHTML = `
            <section class="tui-entry-state">
                <div class="tui-view-status">加载中 / ${escapeHtml(action.label || "默认任务")}</div>
                <div class="tui-entry-copy">
                    <strong>${escapeHtml(waitingCopy)}</strong>
                    <p>${escapeHtml(screenSpec?.screen?.summary || "系统正在准备默认结果。")}</p>
                </div>
            </section>
        `;
        setStatus("读取数据");
    }

    function scheduleSlowActionState(requestId, action) {
        const slowTargets = new Set(runtimeConfig.host?.slowActionKeys || []);
        if (!slowTargets.has(action.key)) {
            return;
        }
        state.slowActionTimer = window.setTimeout(() => {
            if (state.pendingRequestId !== requestId) {
                return;
            }
            renderSlowActionState(action);
        }, slowActionTimeoutMs);
    }

    function renderSlowActionState(action) {
        const hostedAlternatives = (runtimeConfig.host?.slowActionScreens || [])
            .filter((item) => item?.key && item?.label)
            .map((item) => `<button type="button" data-slow-screen="${escapeHtml(item.key)}">${escapeHtml(item.label)}</button>`)
            .join("");
        els.main.innerHTML = `
            <section class="tui-entry-state">
                <div class="tui-view-status">响应较慢 / ${escapeHtml(action.label || "")}</div>
                <div class="tui-entry-copy">
                    <strong>当前响应较慢，可继续等待、重试或取消。</strong>
                    <p>当前请求仍在执行中，也可以切换到宿主提供的其他入口。</p>
                </div>
                <div class="tui-entry-actions">
                    <button type="button" data-slow-command="wait">继续等待</button>
                    <button type="button" data-slow-command="retry">重试</button>
                    ${hostedAlternatives}
                    <button type="button" data-slow-command="cancel">取消本次请求</button>
                </div>
            </section>
        `;
        els.main.querySelectorAll("[data-slow-command]").forEach((button) => {
            button.addEventListener("click", () => {
                const command = button.dataset.slowCommand;
                if (command === "wait") {
                    renderActionLoadingState(action, state.screen, { waitingCopy: "继续等待远端响应..." });
                    scheduleSlowActionState(state.pendingRequestId, action);
                } else if (command === "retry") {
                    clearPendingRequest({ abort: true });
                    runAction(action.key, null, { params: { ...state.lastParams } });
                } else if (command === "cancel") {
                    clearPendingRequest({ abort: true });
                    els.main.innerHTML = renderEmptyState("已取消当前请求。", ["你可以重试，或切换到其他入口继续。"]);
                    setStatus("已取消");
                }
            });
        });
        els.main.querySelectorAll("[data-slow-screen]").forEach((button) => {
            button.addEventListener("click", () => {
                clearPendingRequest({ abort: true });
                loadScreen(button.dataset.slowScreen);
            });
        });
        setStatus("响应较慢");
    }

    function focusActionForm(actionKey) {
        const action = currentAction(actionKey);
        if (!action) {
            setStatus("默认任务未找到");
            return;
        }
        const form = els.actions.querySelector(`[data-action-ui-key="${CSS.escape(actionUiKey(action))}"]`);
        form?.scrollIntoView({ block: "nearest" });
        form?.querySelector("input:not([type='hidden']),select,textarea,button")?.focus();
        setStatus(`已定位到 ${action.label}`);
    }
