(function () {
    "use strict";

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
        pendingController: null,
        slowActionTimer: null,
        clientPage: 1,
        clientPageSize: 100,
        operatorHomePayload: null,
        operatorHomePromise: null,
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
            ["export", "导出当前表格", "F8"],
            ["toggle-inspector", "展开/收起说明栏", "F10"],
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
    const builtInFieldAliases = {
        "company.keyword": ["keyword", "name", "companyName", "company_name", "creditCode", "credit_code", "统一社会信用代码"],
        "company.id": ["id", "cid", "companyId", "company_id"],
        "company.credit_code": ["creditCode", "credit_code", "统一社会信用代码"],
        pk: ["pk", "id", "ID", "记录ID", "config_id", "decision_id", "snapshot_id"],
        id: ["id", "pk", "ID", "记录ID", "cid", "companyId", "company_id"],
        keyword: ["keyword", "name", "companyName", "company_name", "creditCode", "credit_code"],
        company_id: ["company_id", "companyId", "cid", "id", "pk"],
        company_name: ["company_name", "companyName", "name", "keyword"],
        credit_code: ["credit_code", "creditCode", "统一社会信用代码"],
        account_id: ["account_id", "account.id", "account", "账户ID", "id", "pk"],
        portfolio_id: ["portfolio_id", "portfolio.id", "portfolio", "组合ID", "id", "pk"],
        asset_class: ["asset_class", "code", "category", "name"],
        asset_code: ["asset_code", "asset.code", "code", "symbol", "标的代码", "代码"],
        asset_codes: ["asset_codes", "asset_code", "code", "symbol", "标的代码", "代码"],
        fund_code: ["fund_code", "code", "symbol", "基金代码", "代码"],
        indicator_code: ["indicator_code", "code", "指标代码", "代码"],
        capability_key: ["capability_key", "key", "id", "pk"],
        short_code: ["short_code", "code", "shortCode", "短码"],
        snapshot_id: ["snapshot_id", "valuation_snapshot_id", "snapshot.id", "id", "pk"],
        event_id: ["event_id", "event.id", "id", "pk"],
        decision_id: ["decision_id", "id", "pk"],
        report_id: ["report_id", "report.id"],
        run_id: ["run_id", "id", "pk"],
        validation_id: ["validation_id", "validation.id"],
        summary_id: ["summary_id", "summary.id"],
        log_id: ["log_id", "log.id", "id", "pk"],
        request_id: ["request_id", "request.id"],
        task_id: ["task_id", "task.id", "id", "pk"],
        provider_id: ["provider_id", "provider.id", "id", "pk"],
        from_code: ["from_code", "from_currency_code", "from_currency", "base_currency_code", "base_currency", "code"],
        strategy_id: ["strategy_id", "strategy.id", "strategy", "id", "pk"],
        sector_code: ["sector_code", "code", "symbol", "板块代码", "代码"],
        task_name: ["task_name", "name", "title"],
        to_code: ["to_code", "to_currency_code", "to_currency", "target_currency_code", "target_currency", "quote_currency_code", "quote_currency"],
        period: ["period", "period_type", "type", "name"],
    };

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
            try {
                window.localStorage?.setItem(themeStorageKey, resolvedThemeKey);
            } catch (error) {
                // Ignore storage failures; theme switching should still work for this session.
            }
        }
        return resolvedThemeKey;
    }

    function loadStoredTheme() {
        try {
            return normalizeThemeKey(window.localStorage?.getItem(themeStorageKey));
        } catch (error) {
            return "B";
        }
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
            const raw = window.sessionStorage?.getItem(progressStorageKey);
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
        state.lastNonHomeScreen = String(
            window.localStorage?.getItem(lastNonHomeScreenStorageKey) || ""
        ).trim();
        const storedLane = String(
            window.localStorage?.getItem(preferredHomeLaneStorageKey) || "decision"
        ).trim();
        state.preferredHomeLane = storedLane === "governance" ? "governance" : "decision";
        try {
            const rawPinned = window.localStorage?.getItem(pinnedScreensStorageKey);
            const parsed = rawPinned ? JSON.parse(rawPinned) : [];
            state.pinnedScreenKeys = new Set(
                Array.isArray(parsed)
                    ? parsed.map((value) => String(value || "").trim()).filter(Boolean)
                    : []
            );
        } catch (_error) {
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
            window.sessionStorage?.setItem(progressStorageKey, JSON.stringify(serializable));
        } catch (error) {
            // Session progress is a UI convenience; ignore storage failures.
        }
    }

    function persistLastNonHomeScreen(screenKey) {
        const normalizedKey = String(screenKey || "").trim();
        state.lastNonHomeScreen = normalizedKey;
        try {
            if (normalizedKey) {
                window.localStorage?.setItem(lastNonHomeScreenStorageKey, normalizedKey);
            } else {
                window.localStorage?.removeItem(lastNonHomeScreenStorageKey);
            }
        } catch (_error) {
            return;
        }
    }

    function persistPreferredHomeLane(lane) {
        state.preferredHomeLane = lane === "governance" ? "governance" : "decision";
        try {
            window.localStorage?.setItem(preferredHomeLaneStorageKey, state.preferredHomeLane);
        } catch (_error) {
            return;
        }
    }

    function persistPinnedScreens() {
        try {
            window.localStorage?.setItem(
                pinnedScreensStorageKey,
                JSON.stringify(Array.from(state.pinnedScreenKeys))
            );
        } catch (_error) {
            return;
        }
    }

    function shouldResumeOnBoot() {
        try {
            return window.sessionStorage?.getItem(resumeOnBootStorageKey) === "1";
        } catch (_error) {
            return false;
        }
    }

    function clearResumeOnBootFlag() {
        try {
            window.sessionStorage?.removeItem(resumeOnBootStorageKey);
        } catch (_error) {
            return;
        }
    }

    function markResumeOnBoot() {
        try {
            if (state.screen?.screen?.key && !isOperatorHomeScreen(state.screen.screen.key)) {
                window.sessionStorage?.setItem(resumeOnBootStorageKey, "1");
            } else {
                window.sessionStorage?.removeItem(resumeOnBootStorageKey);
            }
        } catch (_error) {
            return;
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
            renderCatalog(state.catalog);
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
        const queueUrl = governanceQueueUrl();
        if (!queueUrl) {
            return;
        }
        try {
            const payload = await fetchJson(queueUrl);
            state.screenBadges = badgeCountsByScreen(payload.items || []);
            state.screenBadgeDrilldowns = badgeDrilldownsByScreen(payload.items || []);
            if (state.catalog) {
                renderCatalog(state.catalog);
            }
            refreshVisibleHomePanelBadges();
        } catch (_error) {
            state.screenBadges = {};
            state.screenBadgeDrilldowns = {};
            if (state.catalog) {
                renderCatalog(state.catalog);
            }
        }
    }

    function inspectorGrid() {
        return els.inspectorShell?.closest?.(".tui-workspace-grid") || null;
    }

    function inspectorWidthBounds() {
        const grid = inspectorGrid();
        if (!grid || window.matchMedia?.("(max-width: 980px)")?.matches) {
            return null;
        }
        const gridWidth = grid.getBoundingClientRect().width || window.innerWidth;
        const max = Math.max(inspectorWidthMin, Math.min(inspectorWidthMax, Math.round(gridWidth * 0.56)));
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
            try {
                window.localStorage?.setItem(inspectorWidthStorageKey, String(nextWidth));
            } catch (error) {
                // Width persistence is a convenience; ignore storage failures.
            }
        }
        return nextWidth;
    }

    function loadStoredInspectorWidth() {
        try {
            const storedWidth = Number(window.localStorage?.getItem(inspectorWidthStorageKey));
            if (Number.isFinite(storedWidth)) {
                applyInspectorWidth(storedWidth);
            }
        } catch (error) {
            state.inspectorWidth = null;
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
        if (state.lastFormTriggerRef === actionRef && now - state.lastFormTriggerAt < 250) {
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

    function renderBoundedApplicationError(error) {
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
            const screenKey = String(state.screen?.screen?.key || state.catalog?.default_screen || "home");
            loadScreen(screenKey);
        });
        els.main.querySelectorAll("[data-panel-recovery-screen]").forEach((button) => {
            button.addEventListener("click", () => loadScreen(button.dataset.panelRecoveryScreen));
        });
        setStatus("请求未完成");
    }

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
        clearPendingRequest();
        state.pendingRequestId = Date.now();
        state.pendingController = controller;
        return state.pendingRequestId;
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
        }, 15000);
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

    function renderCatalog(catalog) {
        state.catalog = catalog;
        const groups = catalog.groups || [];
        let screenIndex = 0;
        els.moduleTree.innerHTML = groups.map((group) => `
            <section class="tui-group">
                <div class="tui-group-title">${escapeHtml(group.label)}</div>
                ${(group.modules || []).map((module) => `
                    <div class="tui-tree-module">
                        <div class="tui-tree-module-title">
                            <span>${escapeHtml(module.label)}</span>
                            <div class="tui-tree-module-meta">
                                ${badgeMarkup((module.screens || []).reduce((counts, screen) => {
                                    const badge = state.screenBadges[screen.key] || {};
                                    counts.blockedCount += Number(badge.blockedCount || 0);
                                    counts.warningCount += Number(badge.warningCount || 0);
                                    return counts;
                                }, { blockedCount: 0, warningCount: 0 }), { compact: true })}
                                <small>${escapeHtml(module.action_count || 0)}</small>
                            </div>
                        </div>
                        ${(module.screens || []).map((screen) => `
                            <div class="tui-screen-row">
                                <button class="tui-screen-button" type="button" data-screen-key="${escapeHtml(screen.key)}">
                                    <span>${++screenIndex} ${escapeHtml(screen.label)}</span>
                                    <small>${escapeHtml(viewLabel(screen.view_type))} / ${escapeHtml(screen.action_count)} 项</small>
                                </button>
                                <div class="tui-screen-tools">
                                    ${screenBadgeMarkup(screen.key)}
                                    <button
                                        class="tui-screen-pin${state.pinnedScreenKeys.has(screen.key) ? " is-active" : ""}"
                                        type="button"
                                        data-pin-screen-key="${escapeHtml(screen.key)}"
                                        aria-label="${escapeHtml(state.pinnedScreenKeys.has(screen.key) ? "取消收藏工作区" : "收藏工作区")}"
                                        title="${escapeHtml(state.pinnedScreenKeys.has(screen.key) ? "取消收藏工作区" : "收藏工作区")}"
                                    >${state.pinnedScreenKeys.has(screen.key) ? "★" : "☆"}</button>
                                </div>
                            </div>
                        `).join("")}
                    </div>
                `).join("")}
            </section>
        `).join("");
        els.moduleTree.querySelectorAll("[data-screen-key]").forEach((button) => {
            button.addEventListener("click", () => loadScreen(button.dataset.screenKey));
        });
        els.moduleTree.querySelectorAll("[data-badge-screen-key]").forEach((button) => {
            button.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                openScreenFromCatalog(button.dataset.badgeScreenKey);
            });
        });
        els.moduleTree.querySelectorAll("[data-pin-screen-key]").forEach((button) => {
            button.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const screenKey = String(button.dataset.pinScreenKey || "").trim();
                if (!screenKey) {
                    return;
                }
                if (state.pinnedScreenKeys.has(screenKey)) {
                    state.pinnedScreenKeys.delete(screenKey);
                } else {
                    state.pinnedScreenKeys.add(screenKey);
                }
                persistPinnedScreens();
                renderCatalog(state.catalog);
            });
        });
        if (state.screen?.screen?.key) {
            markActiveScreen(state.screen.screen.key);
        }
    }

    function markActiveScreen(screenKey) {
        let activeScreen = null;
        els.moduleTree.querySelectorAll("[data-screen-key]").forEach((button) => {
            const isActive = button.dataset.screenKey === screenKey;
            button.classList.toggle("is-active", isActive);
            if (isActive) {
                activeScreen = button;
            }
        });
        revealModuleScreen(activeScreen);
    }

    function revealModuleScreen(screenButton) {
        if (!screenButton || state.railCollapsed) {
            return;
        }
        window.requestAnimationFrame(() => {
            screenButton.scrollIntoView({ block: "nearest", inline: "nearest" });
        });
    }

    function renderField(action, field) {
        const id = `tui-${action.key}-${field.key}`;
        const value = field.default || "";
        const required = field.required ? "required" : "";
        if (field.input_type === "hidden") {
            return `<input id="${escapeHtml(id)}" name="${escapeHtml(field.key)}" type="hidden" value="${escapeHtml(value)}">`;
        }
        if (field.input_type === "select") {
            const options = field.options || [];
            return `
                <label class="tui-field" for="${escapeHtml(id)}">
                    <span>${escapeHtml(field.label)}</span>
                    <select id="${escapeHtml(id)}" name="${escapeHtml(field.key)}" ${required}>
                        ${options.map((option) => {
                            const optionValue = typeof option === "string" ? option : option.value;
                            const optionLabel = typeof option === "string" ? option : option.label;
                            return `<option value="${escapeHtml(optionValue)}" ${String(optionValue) === String(value) ? "selected" : ""}>${escapeHtml(optionLabel)}</option>`;
                        }).join("")}
                    </select>
                </label>
            `;
        }
        if (field.input_type === "checkbox") {
            const checked = value === true || String(value).toLowerCase() === "true" || String(value) === "1";
            return `
                <label class="tui-field tui-field-checkbox" for="${escapeHtml(id)}">
                    <input id="${escapeHtml(id)}" name="${escapeHtml(field.key)}" type="checkbox" value="true" ${checked ? "checked" : ""}>
                    <span>${escapeHtml(field.label)}</span>
                </label>
            `;
        }
        if (field.input_type === "textarea") {
            return `
                <label class="tui-field" for="${escapeHtml(id)}">
                    <span>${escapeHtml(field.label)}</span>
                    <textarea id="${escapeHtml(id)}" name="${escapeHtml(field.key)}" rows="3" ${required} placeholder="${escapeHtml(field.placeholder || "")}">${escapeHtml(value)}</textarea>
                </label>
            `;
        }
        if (field.input_type === "file") {
            return `
                <label class="tui-field tui-field-file" for="${escapeHtml(id)}">
                    <span>${escapeHtml(field.label)}</span>
                    <input id="${escapeHtml(id)}" name="${escapeHtml(field.key)}" type="file" ${required} accept="${escapeHtml(field.accept || "")}">
                </label>
            `;
        }
        return `
            <label class="tui-field" for="${escapeHtml(id)}">
                <span>${escapeHtml(field.label)}</span>
                <input id="${escapeHtml(id)}" name="${escapeHtml(field.key)}" type="${escapeHtml(field.input_type || "text")}" value="${escapeHtml(value)}" ${required} placeholder="${escapeHtml(field.placeholder || "")}">
            </label>
        `;
    }

    function coerceFieldValue(field, value, checked) {
        const valueType = String(field.value_type || field.input_type || "text").toLowerCase();
        if (field.input_type === "checkbox" || valueType === "boolean") {
            return Boolean(checked);
        }
        const text = String(value ?? "").trim();
        if (text === "") {
            return "";
        }
        if (valueType === "integer" || valueType === "int" || field.input_type === "number") {
            const parsed = Number(text);
            return Number.isFinite(parsed) ? parsed : text;
        }
        if (valueType === "float") {
            const parsed = Number.parseFloat(text);
            return Number.isFinite(parsed) ? parsed : text;
        }
        if (valueType === "list") {
            if (text.startsWith("[") && text.endsWith("]")) {
                try {
                    const parsed = JSON.parse(text);
                    return Array.isArray(parsed) ? parsed : text;
                } catch (error) {
                    return text.split(",").map((item) => item.trim()).filter(Boolean);
                }
            }
            return text.split(",").map((item) => item.trim()).filter(Boolean);
        }
        if (valueType === "json" || valueType === "object") {
            try {
                return JSON.parse(text);
            } catch (error) {
                return text;
            }
        }
        return text;
    }

    function resetGridState(options = {}) {
        const preserveRowContext = Boolean(options.preserveRowContext);
        state.currentViewModel = null;
        state.currentColumns = [];
        state.currentRows = [];
        state.visibleRows = [];
        state.selectedRowIndex = 0;
        if (!preserveRowContext) {
            state.selectedRowContext = null;
        }
        state.filterText = "";
        if (els.filterInput) {
            els.filterInput.value = "";
        }
        hideFilterBar();
    }

    function setWorkspaceViewKind(kind) {
        const grid = els.main.closest(".tui-workspace-grid");
        if (!grid) {
            return;
        }
        if (!kind) {
            delete grid.dataset.viewKind;
            return;
        }
        grid.dataset.viewKind = String(kind);
    }

    function renderScreen(screenSpec, options = {}) {
        state.screen = screenSpec;
        state.lastRaw = null;
        state.lastPager = null;
        state.homePanelBadges = {};
        resetGridState();
        const screen = screenSpec.screen;
        const inferredLane = inferLaneFromScreen(screen);
        if (inferredLane) {
            persistPreferredHomeLane(inferredLane);
        }
        if (!isOperatorHomeScreen(screen.key)) {
            persistLastNonHomeScreen(screen.key);
        }
        markResumeOnBoot();
        els.screenTitle.textContent = screen.label.toUpperCase();
        els.screenStatus.textContent = screen.status.toUpperCase();
        els.mainTitle.textContent = screen.label.toUpperCase();
        setCurrentLocation(null);
        markActiveScreen(screen.key);
        renderWorkflowStrip(screen.workflow || {});
        const dashboardScreen = hasDashboardPanels(screen) && (screen.entry_state?.mode !== "parameter_gate");
        const immersiveDashboard = isImmersiveDashboardScreen(screen);
        els.actions.closest(".tui-panel").hidden = immersiveDashboard;
        els.inspector.closest(".tui-panel").hidden = immersiveDashboard;
        els.main.closest(".tui-workspace-grid").classList.toggle("is-dashboard", dashboardScreen);
        setWorkspaceViewKind(dashboardScreen ? "dashboard" : "idle");
        state.showSupportTasks = false;
        state.showAdvancedQueries = false;
        state.actionFilterText = "";
        if (dashboardScreen && !immersiveDashboard) {
            renderActions(screenSpec.actions || [], screen);
        }
        if (dashboardScreen) {
            renderDashboardHome(screenSpec);
            updatePager(null);
            updateRawDrawer();
            setLastRefresh();
            setStatus(immersiveDashboard ? "系统首页" : "概览已加载");
            return;
        }
        renderActions(screenSpec.actions || [], screen);
        const actionSummary = summarizeActions(screenSpec.actions || []);
        const businessContext = screen.business_context || {};
        const experience = screenUserExperience(screen);
        renderInspector({
            title: screen.label,
            body: screenPrimaryBody(screen),
            rows: [
                ["主任务", experience.primaryTask],
                ["目标结果", experience.primaryOutcome],
                ["工作区", screenSpec.module.label],
                ["视图", viewLabel(screen.view_type)],
                ["主流程", actionSummary.primary],
                ["支撑检查", actionSummary.support],
                ["高级查询", actionSummary.advanced],
                ["可执行操作", actionSummary.operation],
                ["需确认", actionSummary.write],
                ["AI 交互", actionSummary.ai],
            ],
            sections: [
                ...userExperienceSections(screen),
                ...businessContextSections(businessContext),
                {
                    title: "操作提示",
                    body: [
                        actionSummary.operation
                            ? "本工作区包含提交或 AI 协助动作，已置顶显示；提交前会按策略要求确认。"
                            : "本工作区当前提供打开、查询和检查任务；结果按业务视图呈现，不展示内部接口。"
                    ],
                    rows: [],
                },
            ],
        });
        updatePager(null);
        updateRawDrawer();
        const entryState = screen.entry_state || {};
        const defaultAction = resolveDefaultAction(screenSpec);
        if (entryState.mode === "parameter_gate" && defaultAction) {
            renderEntryState(screenSpec, defaultAction, entryState);
            setStatus("等待选择");
        } else if (defaultAction && !options.suppressAutoAction) {
            const defaultForm = els.actions.querySelector(`[data-action-ui-key="${CSS.escape(actionUiKey(defaultAction))}"]`);
            renderActionLoadingState(defaultAction, screenSpec, { waitingCopy: entryState.empty_copy });
            runAction(defaultAction.key, defaultForm);
        } else {
            els.main.innerHTML = `<div class="tui-empty-state">${escapeHtml(entryState.empty_copy || screenEmptyStateHint(screen, screen.summary))}<br>请选择左侧任务或按 F6 执行下一主流程。</div>`;
            setStatus("工作区就绪");
        }
    }

    function resolveDefaultAction(screenSpec) {
        const actions = screenSpec.actions || [];
        if (!actions.length) {
            return null;
        }
        const screen = screenSpec.screen || {};
        const entryState = screen.entry_state || {};
        if (entryState.mode === "dashboard") {
            return null;
        }
        const preferred = actions.find((action) => action.key === screen.default_action_key);
        const candidate = preferred || actions[0];
        if (!candidate) {
            return null;
        }
        if (entryState.mode === "parameter_gate") {
            return candidate;
        }
        const requiredFields = unresolvedRequiredFields(candidate);
        if (requiredFields.length) {
            return null;
        }
        return candidate;
    }

    function unresolvedRequiredFields(action) {
        return (action?.fields || [])
            .filter((field) => field.required && field.input_type !== "hidden")
            .filter((field) => field.default === undefined || field.default === null || field.default === "");
    }

    function renderEntryState(screenSpec, action, entryState) {
        const fieldKey = String(entryState.field_key || "");
        const field = (action.fields || []).find((item) => item.key === fieldKey) || unresolvedRequiredFields(action)[0];
        if (!field) {
            els.main.innerHTML = renderEmptyState(
                entryState.empty_copy || screenEmptyStateHint(screenSpec.screen, screenSpec.screen.summary),
                entryState.help_steps || ["请选择左侧任务继续。"],
            );
            return;
        }
        const inputType = String(field.input_type || "").toLowerCase();
        if (inputType === "select" && Array.isArray(field.options) && field.options.length) {
            renderSelectorEntryState(screenSpec, action, entryState, field);
            return;
        }
        renderTaskStartEntryState(screenSpec, action, entryState, field);
    }

    function renderSelectorEntryState(screenSpec, action, entryState, field) {
        const options = (field.options || []).filter((option) => {
            if (option && typeof option === "object") {
                return String(option.value ?? "").trim() !== "";
            }
            return String(option ?? "").trim() !== "";
        });
        const cards = options.map((option, index) => {
            const optionValue = typeof option === "object" ? option.value : option;
            const optionLabel = typeof option === "object" ? option.label : option;
            const optionSummary = typeof option === "object"
                ? [option.account_name, option.account_type, option.summary].filter(Boolean).join(" / ")
                : "";
            return `
                <button type="button" class="tui-entry-card" data-entry-option-index="${index}" data-entry-option-value="${escapeHtml(optionValue)}">
                    <strong>${escapeHtml(optionLabel)}</strong>
                    <span>${escapeHtml(optionSummary || "选择后自动进入默认结果。")}</span>
                    <small>${escapeHtml(action.label)}</small>
                </button>
            `;
        }).join("");
        els.main.innerHTML = `
            <section class="tui-entry-state">
                <div class="tui-view-status">入口选择 / ${escapeHtml(screenSpec.screen.label)}</div>
                <div class="tui-entry-copy">
                    <strong>${escapeHtml(entryState.empty_copy || screenEmptyStateHint(screenSpec.screen, `先选择${field.label}`))}</strong>
                    ${(entryState.help_steps || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
                </div>
                <div class="tui-entry-grid">${cards}</div>
            </section>
        `;
        els.main.querySelectorAll("[data-entry-option-index]").forEach((button, index) => {
            button.addEventListener("click", () => {
                const option = options[index];
                const value = typeof option === "object" ? option.value : option;
                runAction(action.key, null, { params: { [field.key]: value } });
            });
        });
    }

    function renderTaskStartEntryState(screenSpec, action, entryState, field) {
        els.main.innerHTML = `
            <section class="tui-entry-state">
                <div class="tui-view-status">任务起步 / ${escapeHtml(screenSpec.screen.label)}</div>
                <div class="tui-entry-copy">
                    <strong>${escapeHtml(entryState.empty_copy || screenEmptyStateHint(screenSpec.screen, `先补充${field.label}`))}</strong>
                    ${(entryState.help_steps || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
                </div>
                <div class="tui-entry-actions">
                    <button type="button" data-focus-default-action>打开默认任务</button>
                </div>
            </section>
        `;
        els.main.querySelector("[data-focus-default-action]")?.addEventListener("click", () => {
            focusActionForm(action.key);
        });
    }

    function screenUserExperience(screen) {
        const experience = screen && typeof screen.user_experience === "object"
            ? screen.user_experience
            : {};
        return {
            journey: String(experience.journey || "").trim(),
            primaryTask: operatorText(experience.primary_task || screen?.summary || screen?.label || ""),
            primaryOutcome: operatorText(experience.primary_outcome || screen?.summary || screen?.label || ""),
            emptyStateHint: operatorText(
                experience.empty_state_hint || screen?.summary || "先运行本屏主任务，必要时补充参数。"
            ),
            nextStepHint: operatorText(
                experience.next_step_hint || "根据结果继续下一项主流程，或进入可执行操作。"
            ),
        };
    }

    function screenPrimaryBody(screen) {
        const experience = screenUserExperience(screen);
        return uniqueNonEmpty([
            experience.primaryTask,
            experience.primaryOutcome !== experience.primaryTask ? experience.primaryOutcome : "",
        ]).join("\n");
    }

    function screenEmptyStateHint(screen, fallback = "") {
        const experience = screenUserExperience(screen);
        return experience.emptyStateHint || operatorText(fallback || screen?.summary || "先运行本屏主任务。");
    }

    function userExperienceSections(screen) {
        const experience = screenUserExperience(screen);
        const rows = [
            ["主任务", experience.primaryTask],
            ["目标结果", experience.primaryOutcome],
        ];
        const body = uniqueNonEmpty([experience.emptyStateHint, experience.nextStepHint]);
        return [{
            title: "用户任务",
            rows,
            body,
        }];
    }

    function hasDashboardPanels(screen) {
        return Array.isArray(screen?.dashboard_panels) && screen.dashboard_panels.length > 0;
    }

    function isImmersiveDashboardScreen(screen) {
        return hasDashboardPanels(screen) && String(screen?.chrome_mode || "").toLowerCase() === "immersive";
    }

    function businessContextSections(context) {
        if (!context || (!context.objective && !context.decision_output && !(context.checkpoints || []).length)) {
            return [];
        }
        const rows = [];
        if (context.objective) {
            rows.push({ label: "目标", value: operatorText(context.objective) });
        }
        if (context.decision_output) {
            rows.push({ label: "产出", value: operatorText(context.decision_output) });
        }
        const body = (context.checkpoints || []).map((item, index) => `${index + 1}. ${operatorText(item)}`);
        return [
            {
                title: "业务目标",
                rows,
                body,
            },
        ];
    }

    function renderWorkflowStrip(workflow) {
        if (!els.workflowStrip) {
            return;
        }
        if (isOperatorHomeScreen(state.screen?.screen?.key)) {
            els.workflowStrip.hidden = true;
            els.workflowStrip.innerHTML = "";
            return;
        }
        const wf = workflow || {};
        if (!wf.name) {
            els.workflowStrip.hidden = true;
            els.workflowStrip.innerHTML = "";
            return;
        }
        const previous = wf.previous || {};
        const next = wf.next || {};
        const workflowActionKeys = runtimeConfig.host?.workflowActionKeys || [];
        const workflowActions = (
            typeof runtimeHooks.getHomeActions === "function"
                ? runtimeHooks.getHomeActions({
                    lastWorkspace: state.lastNonHomeScreen,
                    preferredLane: state.preferredHomeLane,
                })
                : []
        ).filter((action) => workflowActionKeys.includes(action.key));
        const workflowActionsLane = String(runtimeConfig.host?.workflowActionsLane || "");
        const showWorkflowActions = workflowActions.length
            && workflowActionsLane
            && inferLaneFromScreen({ workflow: wf }) === workflowActionsLane;
        const workflowTools = showWorkflowActions
            ? `
                <div class="tui-workflow-tools">
                    ${workflowActions.map((action) => `
                        <button type="button" data-home-action-key="${escapeHtml(action.key)}">${escapeHtml(action.label)}</button>
                    `).join("")}
                </div>
            `
            : "";
        els.workflowStrip.hidden = false;
        els.workflowStrip.innerHTML = `
            <div class="tui-workflow-main">
                <span>${escapeHtml(wf.name)}</span>
                <strong>${escapeHtml(String(wf.step || "-").padStart(2, "0"))}/${escapeHtml(wf.total || "-")}</strong>
                <span>${escapeHtml(wf.label || "")}</span>
            </div>
            <div class="tui-workflow-role">${escapeHtml(wf.role || "")}</div>
            <div class="tui-workflow-nav">
                ${previous.key ? `<button type="button" data-workflow-target="${escapeHtml(previous.key)}">&lt; ${escapeHtml(previous.label)}</button>` : "<span>起点</span>"}
                ${next.key ? `<button type="button" data-workflow-target="${escapeHtml(next.key)}">${escapeHtml(next.label)} &gt;</button>` : "<span>终点</span>"}
            </div>
            ${workflowTools}
        `;
        els.workflowStrip.querySelectorAll("[data-workflow-target]").forEach((button) => {
            button.addEventListener("click", () => loadScreen(button.dataset.workflowTarget));
        });
        els.workflowStrip.querySelectorAll("[data-home-action-key]").forEach((button) => {
            button.addEventListener("click", () => executeHomeAction(button.dataset.homeActionKey));
        });
    }

    function renderHomeActionStrip() {
        const actions = typeof runtimeHooks.getHomeActions === "function"
            ? runtimeHooks.getHomeActions({
                lastWorkspace: state.lastNonHomeScreen,
                preferredLane: state.preferredHomeLane,
            })
            : [];
        if (!Array.isArray(actions) || !actions.length) {
            return "";
        }
        return `
            <section class="tui-home-actions" aria-label="统一首页主动作">
                ${actions.map((action) => `
                    <button type="button" class="tui-home-action${action.active ? " is-active" : ""}" data-home-action-key="${escapeHtml(action.key)}">
                        <strong>${escapeHtml(action.label)}</strong>
                        <span>${escapeHtml(action.description || "")}</span>
                    </button>
                `).join("")}
            </section>
        `;
    }

    function renderDashboardHome(screenSpec) {
        const screen = screenSpec.screen;
        const panels = screen.dashboard_panels && screen.dashboard_panels.length
            ? screen.dashboard_panels
            : defaultDashboardPanels(screenSpec.actions || []);
        const immersiveDashboard = isImmersiveDashboardScreen(screen);
        const actionSummary = summarizeActions(screenSpec.actions || []);
        const businessContext = screen.business_context || {};
        const experience = screenUserExperience(screen);
        const layout = dashboardLayout(panels, screen);
        setWorkspaceViewKind("dashboard");
        els.mainTitle.textContent = immersiveDashboard ? "系统首页" : `${screen.label} 概览`;
        els.main.innerHTML = `
            ${isOperatorHomeScreen(screen.key) ? renderHomeActionStrip() : ""}
            <div class="tui-dashboard-grid${layout.contentFlow ? " is-content-flow" : ""}" style="${escapeHtml(layout.gridStyle)}">
                ${panels.map((panel, index) => `
                    <article class="tui-dash-panel" style="grid-area: ${escapeHtml(layout.areas[index])};" data-dashboard-panel="${escapeHtml(panel.key)}" data-panel-priority="${escapeHtml(panelPriority(panel))}" data-panel-semantic="${escapeHtml(panelPresentationSemantic(panel))}">
                        ${renderDashboardPanelShell(panel, '<div class="tui-loading">读取业务数据...</div>')}
                    </article>
                `).join("")}
            </div>
        `;
        renderInspector({
            title: screen.label,
            body: screenPrimaryBody(screen),
            rows: [
                ["主任务", experience.primaryTask],
                ["目标结果", experience.primaryOutcome],
                ["工作区", screenSpec.module.label],
                ["布局", immersiveDashboard ? "系统首页总控台" : "业务概览面板"],
                ["主流程", actionSummary.primary],
                ["支撑检查", actionSummary.support],
                ["任务", screen.action_count],
            ],
            sections: [
                ...userExperienceSections(screen),
                ...businessContextSections(businessContext),
                {
                    title: "操作提示",
                    body: [
                        immersiveDashboard
                            ? "总览面板来自已审核 action；点击面板可进入对应业务屏继续处理。"
                            : "概览面板用于先看全局摘要；左侧任务区可以继续打开明细或执行补充查询。",
                    ],
                    rows: [],
                },
            ],
        });
        bindDashboardPanelOpenControls(els.main);
        els.main.querySelectorAll("[data-home-action-key]").forEach((button) => {
            button.addEventListener("click", () => executeHomeAction(button.dataset.homeActionKey));
        });
        const primaryPanels = panels.filter((panel) => panelPriority(panel) === "p0");
        const deferredPanels = panels.filter((panel) => panelPriority(panel) !== "p0");
        primaryPanels.forEach((panel) => loadDashboardPanel(panel));
        const loadDeferredPanels = () => deferredPanels.forEach((panel) => loadDashboardPanel(panel));
        if (typeof window.requestIdleCallback === "function") {
            window.requestIdleCallback(loadDeferredPanels, { timeout: 250 });
        } else {
            window.setTimeout(loadDeferredPanels, 0);
        }
    }

    function dashboardTargetScreen(panel) {
        return String(panel.target_screen || panel.screen_key || "");
    }

    function activateDashboardPanel(targetScreen, actionKey) {
        const normalizedTarget = String(targetScreen || "").trim();
        const normalizedActionKey = String(actionKey || "").trim();
        const currentScreenKey = String(state.screen?.screen?.key || "").trim();
        if (normalizedTarget && normalizedTarget !== currentScreenKey) {
            loadScreen(normalizedTarget);
            return;
        }
        if (normalizedActionKey) {
            runAction(normalizedActionKey, null, { params: {} });
            return;
        }
    }

    function actionResultSemantics(actionRef) {
        const action = currentAction(actionRef);
        if (!action || !Array.isArray(action.result_semantics)) {
            return [];
        }
        return action.result_semantics
            .map((semantic) => String(semantic || "").trim())
            .filter(Boolean);
    }

    function panelPriority(panel) {
        return String(panel?.user_priority || "p2").trim().toLowerCase() || "p2";
    }

    function panelPresentationSemantic(panel) {
        const explicit = String(panel?.presentation_semantic || "").trim();
        if (explicit) {
            return explicit;
        }
        const semantics = actionResultSemantics(panel?.action_key);
        return semantics[0] || "";
    }

    function panelPriorityLabel(priority) {
        const normalized = String(priority || "").trim().toLowerCase();
        if (normalized === "p0") {
            return "P0";
        }
        if (normalized === "p1") {
            return "P1";
        }
        return "P2";
    }

    function panelSemanticLabel(semantic) {
        const labels = {
            primary_status: "状态",
            primary_list: "主任务",
            supporting_list: "支撑列表",
            copyable_secret: "凭证",
            endpoint_list: "地址",
            multiline_prompt: "提示词",
            next_step: "下一步",
            supporting_detail: "摘要",
            debug_only: "调试",
        };
        return labels[String(semantic || "").trim()] || "概览";
    }

    function hasSemantic(semantics, value) {
        return (semantics || []).includes(value);
    }

    function uniqueSemantics(values) {
        const seen = new Set();
        return (values || []).filter((value) => {
            const text = String(value || "").trim();
            if (!text || seen.has(text)) {
                return false;
            }
            seen.add(text);
            return true;
        });
    }

    function panelEffectiveSemantics(panel) {
        return uniqueSemantics([
            panelPresentationSemantic(panel),
            ...actionResultSemantics(panel?.action_key),
        ]);
    }

    function defaultDashboardPanels(actions) {
        return actions.slice(0, 5).map((action, index) => ({
            key: action.key || `panel-${index + 1}`,
            title: action.label || `面板 ${index + 1}`,
            kind: action.view_type === "datagrid" ? "datagrid" : "detail",
            action_key: action.key,
            max_rows: 8,
            columns: [],
        }));
    }

    function dashboardLayout(panels, screen) {
        const areas = uniqueDashboardAreas(panels);
        const desktopColumns = dashboardDesktopColumns(screen);
        const contentFlow = desktopColumns === 1 || isOperatorHomeScreen(screen?.key);
        const desktopRowSize = contentFlow ? "auto" : "minmax(190px, auto)";
        const tabletRowSize = contentFlow ? "auto" : "minmax(190px, 1fr)";
        return {
            areas,
            contentFlow,
            gridStyle: [
                `--tui-dashboard-areas-desktop: ${dashboardAreaTemplate(areas, desktopColumns, true)}`,
                `--tui-dashboard-areas-tablet: ${dashboardAreaTemplate(areas, 2)}`,
                `--tui-dashboard-areas-mobile: ${dashboardAreaTemplate(areas, 1)}`,
                `--tui-dashboard-rows-desktop: ${dashboardRows(areas, desktopColumns, desktopRowSize)}`,
                `--tui-dashboard-rows-tablet: ${dashboardRows(areas, 2, tabletRowSize)}`,
                `--tui-dashboard-rows-mobile: ${dashboardRows(areas, 1, "auto")}`,
            ].join("; "),
        };
    }

    function uniqueDashboardAreas(panels) {
        const counts = new Map();
        return panels.map((panel, index) => {
            const source = panel.layout_area || panel.key || `panel-${index + 1}`;
            const base = sanitizeDashboardArea(source) || `panel_${index + 1}`;
            const count = counts.get(base) || 0;
            counts.set(base, count + 1);
            return count ? `${base}_${count + 1}` : base;
        });
    }

    function sanitizeDashboardArea(value) {
        const normalized = String(value || "")
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9_-]+/g, "_")
            .replace(/^[-0-9]+/, "")
            .replace(/_+/g, "_")
            .replace(/^_+|_+$/g, "");
        return normalized && normalized !== "none" ? normalized : "";
    }

    function dashboardAreaTemplate(areas, columns, expandToTwelve = false) {
        const rows = chunkDashboardAreas(areas, columns);
        return rows
            .map((row) => `"${(expandToTwelve ? expandDashboardRow(row) : row).join(" ")}"`)
            .join(" ");
    }

    function dashboardRows(areas, columns, rowSize) {
        const rowCount = Math.max(1, chunkDashboardAreas(areas, columns).length);
        return Array.from({ length: rowCount }, () => rowSize).join(" ");
    }

    function chunkDashboardAreas(areas, columns) {
        const safeAreas = areas.length ? areas : ["panel_1"];
        const rows = [];
        for (let index = 0; index < safeAreas.length; index += columns) {
            rows.push(safeAreas.slice(index, index + columns));
        }
        return rows;
    }

    function expandDashboardRow(row) {
        const baseSpan = Math.floor(12 / row.length);
        let remainder = 12 - baseSpan * row.length;
        return row.flatMap((area) => {
            const span = baseSpan + (remainder > 0 ? 1 : 0);
            remainder -= 1;
            return Array.from({ length: span }, () => area);
        });
    }

    async function loadDashboardPanel(panel) {
        const container = els.main.querySelector(`[data-dashboard-panel="${CSS.escape(panel.key)}"]`);
        if (!container) {
            return;
        }
        if (!panel.action_key) {
            container.innerHTML = renderDashboardPanelShell(panel, renderPanelPlaceholder(panel, "等待发布数据源。"));
            bindDashboardPanelOpenControls(container);
            return;
        }
        try {
            let viewModel = null;
            let panelBadge = null;
            if (typeof runtimeHooks.loadDashboardPanel === "function") {
                const hosted = await runtimeHooks.loadDashboardPanel(panel, {
                    actionRunUrl,
                    fetchJson,
                    screen: state.screen,
                });
                if (hosted) {
                    viewModel = hosted.view_model || hosted;
                    panelBadge = hosted.badge || badgeCountsFromRows(viewModel.rows || []);
                }
            }
            const operatorSectionKey = isOperatorHomeScreen(state.screen?.screen?.key)
                ? operatorHomePanelSectionKey(panel)
                : "";
            if (viewModel) {
                // Host hook supplied a complete panel model.
            } else if (operatorSectionKey) {
                const homePayload = await loadOperatorHomeAggregate();
                const payload = homePayload?.[operatorSectionKey] || {};
                viewModel = operatorHomePanelViewModel(panel, payload);
                panelBadge = payload?.badge
                    ? {
                        blockedCount: Number(payload.badge.blocked_count || 0),
                        warningCount: Number(payload.badge.warning_count || 0),
                    }
                    : badgeCountsFromRows(viewModel.rows || []);
            } else {
                const result = await fetchJson(actionRunUrl(panel.action_key), {
                    method: "POST",
                    body: JSON.stringify({ params: {} }),
                });
                viewModel = result.view_model;
                panelBadge = badgeCountsFromRows(Array.isArray(viewModel?.rows) ? viewModel.rows : []);
            }
            if (isOperatorHomeScreen(state.screen?.screen?.key)) {
                state.homePanelBadges[panel.key] = panelBadge;
            }
            if (!renderDashboardRegisteredRenderer(panel, viewModel, container)) {
                container.innerHTML = renderDashboardPanelShell(panel, renderDashboardPanelBody(panel, viewModel));
                bindCopyButtons(container);
                bindDashboardRowActions(container, panel);
                bindDashboardPanelOpenControls(container);
                processHostSlot(container);
            }
            if (isOperatorHomeScreen(state.screen?.screen?.key)) {
                const badgeHost = container.querySelector("[data-panel-badge]");
                if (badgeHost) {
                    badgeHost.innerHTML = badgeMarkup(state.homePanelBadges[panel.key], { compact: true });
                }
            }
            setLastRefresh();
        } catch (error) {
            container.innerHTML = renderDashboardPanelShell(panel, renderDashboardPanelError(panel, error));
            bindDashboardPanelOpenControls(container);
            bindDashboardPanelRecovery(container, panel);
        }
    }

    function renderDashboardPanelShell(panel, body) {
        const content = `
            <h3>
                <span>${escapeHtml(panel.title)}</span>
                <span class="tui-panel-heading-tools">
                    <span class="tui-panel-priority">${escapeHtml(panelPriorityLabel(panelPriority(panel)))}</span>
                    <span class="tui-panel-semantic">${escapeHtml(panelSemanticLabel(panelPresentationSemantic(panel)))}</span>
                    <span data-panel-badge></span>
                    ${dashboardPanelOpenButton(panel)}
                </span>
            </h3>
            ${panel.note ? `<div class="tui-panel-caption">${escapeHtml(panel.note)}</div>` : ""}
            ${body}
        `;
        if (!dashboardPanelShouldCollapse(panel)) {
            return content;
        }
        return `
            <details class="tui-panel-disclosure">
                <summary>展开${escapeHtml(panel.title)}</summary>
                ${content}
            </details>
        `;
    }

    function dashboardPanelShouldCollapse(panel) {
        return panelPriority(panel) === "p2"
            && !isOperatorHomeScreen(state.screen?.screen?.key);
    }

    function dashboardPanelOpenButton(panel) {
        const target = dashboardTargetScreen(panel);
        const actionKey = String(panel?.action_key || "").trim();
        if (!target && !actionKey) {
            return "";
        }
        return `
            <button
                class="tui-dashboard-open"
                type="button"
                data-dashboard-open
                data-dashboard-target="${escapeHtml(target)}"
                data-dashboard-action="${escapeHtml(actionKey)}"
                aria-label="打开${escapeHtml(panel.title || "面板")}"
            >打开</button>
        `;
    }

    function bindDashboardPanelOpenControls(root) {
        root.querySelectorAll("[data-dashboard-open]").forEach((button) => {
            if (button.dataset.dashboardOpenBound === "true") {
                return;
            }
            button.dataset.dashboardOpenBound = "true";
            button.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                activateDashboardPanel(button.dataset.dashboardTarget, button.dataset.dashboardAction);
            });
        });
    }

    function renderDashboardRegisteredRenderer(panel, viewModel, container) {
        const rendererName = String(viewModel?.renderer || "").trim();
        if (!rendererName || builtInRendererNames.has(rendererName)) {
            return false;
        }
        const renderer = rendererRegistry.get(rendererName);
        if (!renderer) {
            return false;
        }
        container.innerHTML = renderDashboardPanelShell(
            panel,
            `<div class="tui-extension-host is-dashboard" data-renderer="${escapeHtml(rendererName)}"></div>`,
        );
        const host = container.querySelector(".tui-extension-host");
        try {
            renderer({
                viewModel,
                container: host,
                runtimeConfig,
                escapeHtml,
            });
        } catch (_error) {
            host.innerHTML = renderEmptyState("扩展视图暂时不可用。", ["请稍后重试，或改用默认任务查看数据。"]);
        }
        bindCopyButtons(container);
        bindDashboardPanelOpenControls(container);
        return true;
    }

    function renderDashboardPanelBody(panel, viewModel) {
        if (!viewModel) {
            return renderPanelPlaceholder(panel, "暂无可显示数据。");
        }
        if (requiresMissingRendererFallback(viewModel)) {
            return renderExtensionFallback(viewModel);
        }
        if (panel.kind === "regime_quadrant") {
            return renderRegimePanel(viewModel);
        }
        if (viewModel.kind === "chart") {
            return renderChartMarkup(viewModel, { compact: true });
        }
        if (viewModel.kind === "image") {
            return renderImageMarkup(viewModel, { compact: true });
        }
        if (viewModel.kind === "kpi_trend") {
            return renderKpiTrendMarkup(viewModel, { compact: true });
        }
        if (viewModel.kind === "table_chart") {
            return renderTableChartMarkup(viewModel, { compact: true });
        }
        if (viewModel.kind === "host_slot") {
            return renderHostSlotMarkup(viewModel, { compact: true });
        }
        if (viewModel.kind === "custom") {
            return renderExtensionFallback(viewModel);
        }
        if (viewModel.kind === "datagrid") {
            return renderPanelDataGrid(panel, viewModel);
        }
        if (viewModel.kind === "detail") {
            return renderPanelDetail(panel, viewModel);
        }
        return `<div class="tui-message">${escapeHtml(viewModel.message || viewModel.status || "正常")}</div>`;
    }

    function operatorHomePanelViewModel(panel, payload) {
        const rows = Array.isArray(payload?.rows) ? payload.rows : [];
        const columns = (Array.isArray(panel?.columns) ? panel.columns : [])
            .map((column) => ({
                key: String(column?.key || "").trim(),
                label: String(column?.label || column?.key || "").trim(),
            }))
            .filter((column) => column.key);
        return {
            kind: "datagrid",
            title: panel?.title || "",
            status: String(payload?.status || "ok"),
            columns,
            rows,
            total: Number(payload?.total || rows.length || 0),
            empty_message: "暂无数据",
            empty_guidance: [],
        };
    }

    function dashboardDesktopColumns(screen) {
        if (String(screen?.dashboard_layout || "adaptive_grid").trim() === "task_flow") {
            return 1;
        }
        const journey = screenUserExperience(screen).journey;
        if ((runtimeConfig.host?.singleColumnScreens || []).includes(screen?.key)) {
            return 1;
        }
        return ["self_service", "admin"].includes(journey) ? 2 : 3;
    }

    function renderRegimePanel(viewModel) {
        const fields = fieldsToMap(viewModel.fields || []);
        const regime = pickField(fields, ["current_regime", "dominant_regime", "regime", "regime_name", "state", "name"]) || "UNKNOWN";
        const confidence = pickField(fields, ["confidence", "regime_confidence", "confidence_pct"]) || "-";
        const trend = pickField(fields, ["trend", "movement", "transition_target", "status"]) || "-";
        const warning = pickField(fields, ["warning", "transition_warning", "risk", "alerts"]) || "-";
        return `
            <div class="tui-quadrant">
                <div class="q q-recovery">复苏<br><strong>RECOVERY</strong></div>
                <div class="q q-overheat">过热<br><strong>OVERHEAT</strong></div>
                <div class="q q-recession">衰退<br><strong>RECESSION</strong></div>
                <div class="q q-stagflation">滞胀<br><strong>STAGFLATION</strong></div>
                <div class="q-axis-x"></div>
                <div class="q-axis-y"></div>
                <div class="q-marker">◆</div>
            </div>
            <div class="tui-dash-lines">
                <div>当前判断: <strong class="tui-green">${escapeHtml(regime)}</strong></div>
                <div>置信度: <strong>${escapeHtml(confidence)}</strong>　趋势: <strong class="tui-green">${escapeHtml(trend)}</strong></div>
                <div>拐点预警: ${escapeHtml(warning)}</div>
            </div>
        `;
    }

    function renderPanelDataGrid(panel, viewModel) {
        const rows = (viewModel.rows || []).slice(0, Number(panel.max_rows || 8));
        const panelColumns = Array.isArray(panel.columns) ? panel.columns : [];
        const preferredColumns = panelColumns.filter((column) => rows.some((row) => Object.prototype.hasOwnProperty.call(row, column.key)));
        const sourceColumns = preferredColumns.length ? preferredColumns : (viewModel.columns || []);
        const columns = sourceColumns.filter((column) => rows.some((row) => Object.prototype.hasOwnProperty.call(row, column.key))).slice(0, 6);
        if (!rows.length || !columns.length) {
            return renderPanelPlaceholder(panel, "暂无表格数据。");
        }
        const rowActions = Array.isArray(panel.row_actions) ? panel.row_actions : [];
        const headers = columns.map((column) => column.label || column.key);
        if (rowActions.length) {
            headers.push("操作");
        }
        return `
            <table class="tui-mini-table">
                <thead><tr>${headers.map((header, index) => `<th class="${rowActions.length && index === headers.length - 1 ? "tui-row-actions-header" : ""}">${escapeHtml(header)}</th>`).join("")}</tr></thead>
                <tbody>
                    ${rows.map((row) => `
                        <tr>
                            ${columns.map((column) => `<td class="${cellClass(row[column.key], column.label || column.key)}">${escapeHtml(row[column.key] ?? "-")}</td>`).join("")}
                            ${rowActions.length ? `<td class="tui-row-actions-cell">${renderDashboardRowActions(panel, row)}</td>` : ""}
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;
    }

    function renderDashboardRowActions(panel, row) {
        const descriptors = Array.isArray(panel?.row_actions) ? panel.row_actions : [];
        return `<div class="tui-row-actions">${descriptors.map((descriptor) => {
            const action = currentAction(descriptor.action_key);
            const params = Object.fromEntries(
                Object.entries(descriptor.param_map || {}).map(([paramKey, rowKey]) => [paramKey, row?.[rowKey]]),
            );
            const label = interpolateRowActionLabel(descriptor.label_template, row);
            return `
                <button
                    class="tui-row-action"
                    type="button"
                    data-dashboard-row-action
                    data-row-action-key="${escapeHtml(descriptor.action_key)}"
                    data-row-action-params="${escapeHtml(JSON.stringify(params))}"
                    aria-label="${escapeHtml(label)}"
                    title="${escapeHtml(label)}"
                >${escapeHtml(action?.label || "操作")}</button>
            `;
        }).join("")}</div>`;
    }

    function interpolateRowActionLabel(template, row) {
        return String(template || "操作").replace(/\{([^{}]+)\}/g, (_match, key) => String(row?.[key] ?? "-"));
    }

    function bindDashboardRowActions(root, panel) {
        root.querySelectorAll("[data-dashboard-row-action]").forEach((button) => {
            if (button.dataset.rowActionBound === "true") {
                return;
            }
            button.dataset.rowActionBound = "true";
            button.addEventListener("click", async (event) => {
                event.preventDefault();
                event.stopPropagation();
                let params = {};
                try {
                    params = JSON.parse(button.dataset.rowActionParams || "{}");
                } catch (_error) {
                    setStatus("行操作参数不可用");
                    return;
                }
                button.disabled = true;
                try {
                    const action = currentAction(button.dataset.rowActionKey);
                    const method = String(action?.method || "GET").trim().toUpperCase();
                    const refreshesDashboard = !["GET", "HEAD", "OPTIONS"].includes(method);
                    await runAction(
                        button.dataset.rowActionKey,
                        null,
                        refreshesDashboard
                            ? { params, dashboardPanelKey: panel.key }
                            : { params },
                    );
                } finally {
                    button.disabled = false;
                }
            });
        });
    }

    function renderPanelDetail(panel, viewModel) {
        const semantics = panelEffectiveSemantics(panel);
        if (semantics.length) {
            return renderSemanticDetailView(viewModel, semantics, { compact: true, panel });
        }
        const fields = (viewModel.fields || []).slice(0, Number(panel.max_rows || 8));
        if (!fields.length) {
            const nested = (viewModel.nested || []).slice(0, Number(panel.max_rows || 8));
            if (nested.length) {
                return renderMiniTable(["项目", "数量"], nested.map((item) => [item.label, item.count]));
            }
            return renderPanelPlaceholder(panel, "暂无摘要数据。");
        }
        return `
            ${renderMiniTable(["项目", "值"], fields.map((field) => [field.label, field.value]))}
            ${panel.note ? `<div class="tui-panel-note">${escapeHtml(panel.note)}</div>` : ""}
        `;
    }

    function currentActionSemantics() {
        return actionResultSemantics(state.lastAction);
    }

    function renderSemanticDetailView(viewModel, semantics, options = {}) {
        const fields = (viewModel.fields || []).slice(0, Number(options.panel?.max_rows || 12));
        const nested = (viewModel.nested || []).slice(0, Number(options.panel?.max_rows || 12));
        const classes = [
            "tui-semantic-detail",
            options.compact ? "is-compact" : "",
            hasSemantic(semantics, "primary_status") ? "is-primary-status" : "",
            hasSemantic(semantics, "copyable_secret") ? "is-copyable-secret" : "",
            hasSemantic(semantics, "endpoint_list") ? "is-endpoint-list" : "",
            hasSemantic(semantics, "multiline_prompt") ? "is-multiline-prompt" : "",
        ].filter(Boolean).join(" ");
        const statusHero = hasSemantic(semantics, "primary_status")
            ? `
                <div class="tui-status-hero">
                    <strong>${escapeHtml(viewModel.title || "状态")}</strong>
                    <span class="tui-status-pill">${escapeHtml(viewModel.status || "正常")}</span>
                </div>
            `
            : "";
        const secretFields = fields.filter((field) => fieldPresentation(field) === "secret");
        const copyFields = fields.filter((field) => fieldPresentation(field) === "copyable");
        const multilineFields = fields.filter((field) => fieldPresentation(field) === "multiline");
        const metaFields = fields.filter((field) => fieldPresentation(field) === "metadata");
        const fieldMarkup = [
            secretFields.length ? renderSemanticSecretFields(secretFields) : "",
            copyFields.length ? renderSemanticCopyFields(copyFields) : "",
            metaFields.length ? renderSemanticGridFields(metaFields) : "",
            multilineFields.length ? renderSemanticMultilineFields(multilineFields) : "",
        ].filter(Boolean).join("");
        const nestedMarkup = nested.length
            ? `<div class="tui-nested-list">${nested.map((item) => `<span>${escapeHtml(item.label)}: ${escapeHtml(item.count)} 行</span>`).join("")}</div>`
            : "";
        return `
            <section class="${classes}">
                ${statusHero}
                ${fieldMarkup || renderPanelPlaceholder(options.panel || {}, "暂无摘要数据。")}
                ${nestedMarkup}
            </section>
        `;
    }

    function renderSemanticGridFields(fields) {
        if (!fields.length) {
            return "";
        }
        return `
            <dl class="tui-detail-grid">
                ${fields.map((field) => `
                    <dt>${escapeHtml(field.label)}</dt>
                    <dd>${escapeHtml(field.value)}</dd>
                `).join("")}
            </dl>
        `;
    }

    function fieldPresentation(field) {
        const presentation = String(field?.presentation || "metadata").trim().toLowerCase();
        return ["secret", "copyable", "multiline", "metadata"].includes(presentation)
            ? presentation
            : "metadata";
    }

    function renderSemanticSecretFields(fields) {
        return `
            <div class="tui-copy-stack">
                ${fields.map((field) => `
                    <div class="tui-copy-row is-secret">
                        <div class="tui-copy-head">
                            <span>${escapeHtml(field.label)}</span>
                            <span class="tui-copy-controls">
                                <button
                                    class="tui-copy-action"
                                    type="button"
                                    data-secret-toggle
                                    data-secret-visible="true"
                                    aria-label="隐藏${escapeHtml(field.label)}"
                                >隐藏</button>
                                <button
                                    class="tui-copy-action"
                                    type="button"
                                    data-copy-value="${escapeHtml(field.value)}"
                                    data-copy-label="${escapeHtml(field.label)}"
                                >复制</button>
                            </span>
                        </div>
                        <code data-secret-value="${escapeHtml(field.value)}">${escapeHtml(field.value)}</code>
                    </div>
                `).join("")}
            </div>
        `;
    }

    function renderSemanticCopyFields(fields) {
        if (!fields.length) {
            return "";
        }
        return `
            <div class="tui-copy-stack">
                ${fields.map((field) => `
                    <div class="tui-copy-row">
                        <div class="tui-copy-head">
                            <span>${escapeHtml(field.label)}</span>
                            <button
                                class="tui-copy-action"
                                type="button"
                                data-copy-value="${escapeHtml(field.value)}"
                                data-copy-label="${escapeHtml(field.label)}"
                            >复制</button>
                        </div>
                        <code>${escapeHtml(field.value)}</code>
                    </div>
                `).join("")}
            </div>
        `;
    }

    function renderSemanticMultilineFields(fields) {
        if (!fields.length) {
            return "";
        }
        return `
            <div class="tui-copy-stack">
                ${fields.map((field) => {
                    const accessPackage = String(field?.key || "") === "access_package";
                    return `
                    <section class="tui-copy-block-card${accessPackage ? " is-dominant" : ""}">
                        <div class="tui-copy-head">
                            <strong>${escapeHtml(field.label)}</strong>
                            <button
                                class="tui-copy-action"
                                type="button"
                                data-copy-value="${escapeHtml(field.value)}"
                                data-copy-label="${escapeHtml(field.label)}"
                            >${accessPackage ? "复制完整接入包" : "复制"}</button>
                        </div>
                        <pre class="tui-copy-block">${escapeHtml(field.value)}</pre>
                    </section>
                `;
                }).join("")}
            </div>
        `;
    }

    async function writeClipboardText(value) {
        const text = String(value ?? "");
        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
            await navigator.clipboard.writeText(text);
            return;
        }
        const helper = document.createElement("textarea");
        helper.value = text;
        helper.setAttribute("readonly", "readonly");
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        helper.style.pointerEvents = "none";
        document.body.appendChild(helper);
        helper.select();
        document.execCommand("copy");
        document.body.removeChild(helper);
    }

    function bindCopyButtons(root = document) {
        root.querySelectorAll("[data-secret-toggle]").forEach((button) => {
            if (button.dataset.secretBound === "true") {
                return;
            }
            button.dataset.secretBound = "true";
            button.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const code = button.closest(".tui-copy-row")?.querySelector("[data-secret-value]");
                if (!code) {
                    return;
                }
                const visible = button.dataset.secretVisible === "true";
                button.dataset.secretVisible = visible ? "false" : "true";
                button.textContent = visible ? "显示" : "隐藏";
                button.setAttribute("aria-label", visible ? "显示接入令牌" : "隐藏接入令牌");
                code.textContent = visible ? "••••••••••••" : code.dataset.secretValue;
            });
        });
        root.querySelectorAll("[data-copy-value]").forEach((button) => {
            if (button.dataset.copyBound === "true") {
                return;
            }
            button.dataset.copyBound = "true";
            button.addEventListener("click", async (event) => {
                event.preventDefault();
                event.stopPropagation();
                const label = String(button.dataset.copyLabel || "内容").trim();
                const originalText = button.textContent;
                try {
                    await writeClipboardText(button.dataset.copyValue || "");
                    button.textContent = "已复制";
                    setStatus(`${label}已复制`);
                } catch (_error) {
                    button.textContent = "复制失败";
                    setStatus(`${label}复制失败`);
                }
                window.setTimeout(() => {
                    button.textContent = originalText;
                }, 1200);
            });
        });
    }

    function fieldsToMap(fields) {
        return fields.reduce((result, field) => {
            result[String(field.key || field.label || "").toLowerCase()] = field.value;
            result[String(field.label || "").toLowerCase()] = field.value;
            return result;
        }, {});
    }

    function pickField(fields, keys) {
        for (const key of keys) {
            const value = fields[String(key).toLowerCase()];
            if (value !== undefined && value !== null && value !== "") {
                return value;
            }
        }
        return "";
    }

    function renderPanelPlaceholder(panel, message) {
        return `
            <div class="tui-panel-placeholder">
                <div>${escapeHtml(message)}</div>
                ${panel.note ? `<small>${escapeHtml(panel.note)}</small>` : ""}
            </div>
        `;
    }

    function renderMiniTable(headers, rows, selectedIndex) {
        return `
            <table class="tui-mini-table">
                <thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>
                <tbody>
                    ${rows.map((row, index) => `
                        <tr class="${index === selectedIndex ? "is-hot" : ""}">
                            ${row.map((cell, cellIndex) => `<td class="${cellClass(cell, headers[cellIndex])}">${escapeHtml(cell)}</td>`).join("")}
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;
    }

    function cellClass(value, header = "") {
        const text = String(value);
        const headerText = String(header || "");
        if (["标的", "代码", "名称", "股票", "资产", "证券"].some((item) => headerText.includes(item))) {
            return "";
        }
        if (/^-\d+(?:\.\d+)?%?$/.test(text.trim()) || text.includes("暂停") || text.includes("触发")) {
            return "is-red";
        }
        if (text.includes("观察") || /(进行中|运行中|处理中|同步中|排队中)/.test(text)) {
            return "is-yellow";
        }
        if (text.includes("正常") || text.includes("运行") || text.includes("成功") || text.includes("%")) {
            return "is-green";
        }
        return "";
    }

    function actionTier(action) {
        const tier = String(action.task_tier || "").toLowerCase();
        if (["primary", "support", "advanced", "operation"].includes(tier)) {
            return tier;
        }
        if (isAdvancedAction(action)) {
            return "advanced";
        }
        const risk = String(action.risk || "").toLowerCase();
        if (risk === "write" || risk === "ai") {
            return "operation";
        }
        const group = String(action.task_group || "");
        return group.startsWith("01 ") || group.startsWith("02 ") || group.startsWith("03 ")
            ? "primary"
            : "support";
    }

    function summarizeActions(actions) {
        return actions.reduce((summary, action) => {
            const tier = actionTier(action);
            if (tier === "advanced") {
                summary.advanced += 1;
            } else if (tier === "support") {
                summary.support += 1;
            } else if (tier === "operation") {
                summary.operation += 1;
            } else {
                summary.primary += 1;
            }
            const risk = String(action.risk || "").toLowerCase();
            if (risk === "write") {
                summary.write += 1;
            }
            if (risk === "ai") {
                summary.ai += 1;
            }
            return summary;
        }, { primary: 0, support: 0, advanced: 0, operation: 0, write: 0, ai: 0 });
    }

    function isAdvancedAction(action) {
        const group = String(action.task_group || "");
        const key = String(action.key || "");
        return group.includes("条件查询") || key.startsWith("param.");
    }

    function renderActions(actions, screen) {
        if (!actions.length) {
            els.actions.innerHTML = '<div class="tui-empty-state">当前工作区暂无可执行任务。</div>';
            return;
        }
        const primaryActions = actions.filter((action) => actionTier(action) === "primary");
        const supportActions = actions.filter((action) => actionTier(action) === "support");
        const operationActions = actions.filter((action) => actionTier(action) === "operation");
        const advancedActions = actions.filter((action) => actionTier(action) === "advanced");
        const hasPrimary = primaryActions.length > 0;
        const filterNeedle = state.actionFilterText.trim().toLowerCase();
        const visibleActions = filterNeedle
            ? actions.filter((action) => actionMatchesFilter(action, filterNeedle))
            : hasPrimary
            ? operationActions
                .concat(primaryActions)
                .concat(state.showSupportTasks ? supportActions : [])
                .concat(state.showAdvancedQueries ? advancedActions : [])
            : operationActions.concat(supportActions).concat(advancedActions);
        const summary = summarizeActions(actions);
        const progress = screenProgress(actions);
        const groups = groupActions(visibleActions);
        els.actions.innerHTML = `
            <div class="tui-action-brief">
                <div>
                    <strong>${escapeHtml((screen && screen.label) || "当前工作区")}</strong>
                    <span>主流程 ${progress.completed}/${progress.total} / 操作 ${summary.operation} / 支撑 ${summary.support} / 高级 ${summary.advanced}${filterNeedle ? ` / 匹配 ${visibleActions.length}` : ""}</span>
                </div>
                <label class="tui-action-filter">
                    <span>任务</span>
                    <input type="search" value="${escapeHtml(state.actionFilterText)}" placeholder="输入业务词" data-action-filter>
                    ${state.actionFilterText ? '<button type="button" data-clear-action-filter>清</button>' : ""}
                </label>
                ${supportActions.length ? `
                    <button class="tui-action-toggle" type="button" data-toggle-support>
                        ${state.showSupportTasks || !hasPrimary ? "隐藏支撑" : "显示支撑"}
                    </button>
                ` : ""}
                ${advancedActions.length ? `
                    <button class="tui-action-toggle" type="button" data-toggle-advanced>
                        ${state.showAdvancedQueries || !hasPrimary ? "隐藏高级" : "显示高级"}
                    </button>
                ` : ""}
            </div>
            ${groups.length ? groups.map((group) => `
                <section class="tui-action-group tui-action-group-${escapeHtml(group.tier)}">
                    <div class="tui-action-group-title">${escapeHtml(group.label)}</div>
                    ${group.actions.map((action) => renderActionForm(action)).join("")}
                </section>
            `).join("") : `<div class="tui-empty-state">没有匹配任务。清空筛选后查看全部。</div>`}
        `;
        const actionFilter = els.actions.querySelector("[data-action-filter]");
        actionFilter?.addEventListener("input", () => {
            state.actionFilterText = actionFilter.value;
            renderActions(actions, screen);
            const nextFilter = els.actions.querySelector("[data-action-filter]");
            if (nextFilter) {
                nextFilter.focus();
                nextFilter.setSelectionRange(nextFilter.value.length, nextFilter.value.length);
            }
        });
        els.actions.querySelector("[data-clear-action-filter]")?.addEventListener("click", () => {
            state.actionFilterText = "";
            renderActions(actions, screen);
            setStatus("任务筛选已清除");
        });
        els.actions.querySelector("[data-toggle-support]")?.addEventListener("click", () => {
            state.showSupportTasks = !state.showSupportTasks;
            renderActions(actions, screen);
            setStatus(state.showSupportTasks ? "支撑检查已显示" : "支撑检查已隐藏");
        });
        els.actions.querySelector("[data-toggle-advanced]")?.addEventListener("click", () => {
            state.showAdvancedQueries = !state.showAdvancedQueries;
            renderActions(actions, screen);
            setStatus(state.showAdvancedQueries ? "高级查询已显示" : "高级查询已隐藏");
        });
        bindRenderedActionForms();
        refreshRowFillButtons();
    }

    function bindRenderedActionForms() {
        els.actions.querySelectorAll("[data-action-ui-key]").forEach((form) => {
            form.addEventListener("submit", (event) => {
                event.preventDefault();
                event.stopPropagation();
                triggerActionForm(form);
            });
            const actionButton = form.querySelector(".tui-action-button");
            actionButton?.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                triggerActionForm(form);
            });
            const fillButton = form.querySelector("[data-fill-from-row]");
            fillButton?.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                fillActionFromSelectedRow(form);
            });
        });
    }

    function actionMatchesFilter(action, needle) {
        const haystack = [
            action.label,
            action.description,
            action.task_group,
            actionRoleLabel(action),
            actionVerbLabel(action),
            ...(action.fields || []).map((field) => `${field.label} ${field.key}`),
        ].join(" ").toLowerCase();
        return haystack.includes(needle);
    }

    function groupActions(actions) {
        const groups = [];
        const byLabel = new Map();
        actions.forEach((action) => {
            const tier = actionTier(action);
            const label = tier === "operation" ? "00 可执行操作" : (action.task_group || "核心任务");
            if (!byLabel.has(label)) {
                const group = {
                    label,
                    tier,
                    actions: [],
                    sequence: tier === "operation" ? -100 : Number(action.sequence || 999),
                };
                byLabel.set(label, group);
                groups.push(group);
            }
            const group = byLabel.get(label);
            group.sequence = Math.min(
                group.sequence,
                tier === "operation" ? -100 : Number(action.sequence || 999)
            );
            group.actions.push(action);
        });
        groups.sort((left, right) => left.sequence - right.sequence);
        groups.forEach((group) => {
            group.actions.sort((left, right) => Number(left.sequence || 999) - Number(right.sequence || 999));
        });
        return groups;
    }

    function renderActionForm(action) {
        const hasVisibleFields = (action.fields || []).some((field) => field.input_type !== "hidden");
        const completed = isActionCompleted(action.key);
        const description = operatorText(action.description || "");
        const submitLabel = actionSubmitLabel(action);
        return `
            <form class="tui-action-form tui-action-risk-${escapeHtml(action.risk || "read")} ${completed ? "is-completed" : ""}" data-action-ui-key="${escapeHtml(actionUiKey(action))}" novalidate>
                <button class="tui-action-button" type="button">
                    <span>
                        ${escapeHtml(action.label)}
                        <span class="tui-action-meta">${escapeHtml(actionMetaLabel(action, completed))}</span>
                    </span>
                </button>
                ${hasVisibleFields ? '<button class="tui-row-fill-button" type="button" data-fill-from-row>从选中行填充</button>' : ""}
                ${action.confirmation_required ? '<div class="tui-action-confirm">提交前会要求确认</div>' : ""}
                ${description ? `<div class="tui-action-desc">${escapeHtml(description)}</div>` : ""}
                ${(action.fields || []).map((field) => renderField(action, field)).join("")}
                <button class="tui-action-submit" type="submit">${escapeHtml(submitLabel)}</button>
            </form>
        `;
    }

    function actionSubmitLabel(action) {
        const text = `${action.label || ""} ${action.intent || ""} ${action.key || ""}`.toLowerCase();
        if (action.risk === "write" || action.risk === "admin" || /save|submit|update|create|delete|保存|提交|变更|更新|创建|删除/.test(text)) {
            return "提交变更";
        }
        if (/check|validate|verify|inspect|检查|校验|验证|诊断/.test(text)) {
            return "运行检查";
        }
        if (/query|search|list|find|lookup|查询|搜索|检索|列表/.test(text)) {
            return "按条件查询";
        }
        return "执行";
    }

    function actionResourceBase(actionKey) {
        let segments = String(actionKey || "")
            .split(".")
            .filter(Boolean);
        const dynamicSegments = new Set(["pk", "id", "int", "str", "uuid", "slug", "path", "bool", "float", "decimal", "date", "datetime"]);
        const collected = [];
        if (segments[0] === "auto" || segments[0] === "param") {
            segments = segments.slice(1);
        }
        if (segments[0] === "api" && segments[2] === "api") {
            segments = segments.slice(3);
        }
        for (const segment of segments) {
            if (dynamicSegments.has(segment)) {
                break;
            }
            collected.push(segment);
        }
        return collected.join(".");
    }

    function rowContextWithSource(row) {
        if (!row) {
            return null;
        }
        const sourceAction = currentAction(state.lastAction);
        return {
            ...row,
            __tui_source_action_key: sourceAction ? sourceAction.key : "",
            __tui_source_resource_base: actionResourceBase(sourceAction ? sourceAction.key : ""),
        };
    }

    function actionCompatibleWithRowSource(action, row, fieldKey) {
        const key = String(fieldKey || "");
        if (!["pk", "id"].includes(key)) {
            return true;
        }
        const rowResourceBase = String(row && row.__tui_source_resource_base ? row.__tui_source_resource_base : "");
        const targetResourceBase = actionResourceBase(action && action.key);
        if (!rowResourceBase || !targetResourceBase) {
            return true;
        }
        return rowResourceBase === targetResourceBase;
    }

    function actionCanFillFromRow(action, row) {
        if (!action || !row) {
            return false;
        }
        const fields = (action.fields || []).filter((field) => field.input_type !== "hidden");
        if (!fields.length) {
            return false;
        }
        return fields.some((field) => rowValueForField(row, field.key, action) !== undefined);
    }

    async function collectParams(form, action) {
        const params = {};
        if (!form) {
            return params;
        }
        const fields = (action && action.fields) || [];
        for (const field of fields) {
            const element = formFieldElement(form, field.key);
            if (!element) {
                continue;
            }
            if (field.input_type === "file") {
                if (element.files && element.files.length) {
                    params[field.key] = await readTextFile(element.files[0]);
                }
                continue;
            }
            const value = coerceFieldValue(field, element.value, element.checked);
            if (field.input_type === "checkbox" || value !== "") {
                params[field.key] = value;
            }
        }
        return params;
    }

    function readTextFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.addEventListener("load", () => resolve(String(reader.result || "")));
            reader.addEventListener("error", () => reject(reader.error || new Error("文件读取失败")));
            reader.readAsText(file, "utf-8");
        });
    }

    function applySelectedRowToActionForm(form, options = {}) {
        const { onlyIfEmpty = false, silent = false, focus = false } = options;
        if (!form) {
            if (!silent) {
                setStatus("没有可填充的任务");
            }
            return false;
        }
        const row = selectedRowForActions();
        if (!row) {
            if (!silent) {
                setStatus("先在表格中选择一行");
            }
            return false;
        }
        const action = currentAction(actionRefFromForm(form));
        if (!action) {
            if (!silent) {
                setStatus("任务未找到");
            }
            return false;
        }
        const params = paramsFromRowForAction(row, action);
        const fields = (action.fields || []);
        let filled = 0;
        fields.forEach((field) => {
            if (field.input_type === "hidden") {
                return;
            }
            const element = formFieldElement(form, field.key);
            if (!element) {
                return;
            }
            if (onlyIfEmpty) {
                if (element.type === "checkbox" && element.checked) {
                    return;
                }
                if (element.type !== "checkbox" && String(element.value || "").trim() !== "") {
                    return;
                }
            }
            const value = params[field.key];
            if (value === undefined || value === null || value === "") {
                return;
            }
            if (element.type === "checkbox") {
                element.checked = Boolean(value);
            } else {
                element.value = String(value);
            }
            filled += 1;
        });
        if (filled) {
            if (!silent) {
                setStatus(`已从选中行填充 ${filled} 项`);
            }
            if (focus) {
                form.querySelector("input:not([type='hidden']),select,textarea")?.focus();
            }
            return true;
        }
        if (!silent) {
            setStatus("选中行没有可匹配字段");
        }
        return false;
    }

    function fillActionFromSelectedRow(form) {
        return applySelectedRowToActionForm(form, { focus: true });
    }

    function rowValueForField(row, fieldOrKey, action) {
        const fieldKey = typeof fieldOrKey === "object" && fieldOrKey ? fieldOrKey.key : fieldOrKey;
        if (!actionCompatibleWithRowSource(action, row, fieldKey)) {
            return undefined;
        }
        for (const key of rowFieldCandidates(fieldOrKey, action)) {
            const rawKey = `__raw_${key}`;
            if (Object.prototype.hasOwnProperty.call(row, rawKey) && row[rawKey] !== undefined && row[rawKey] !== null && row[rawKey] !== "") {
                return row[rawKey];
            }
            if (Object.prototype.hasOwnProperty.call(row, key) && row[key] !== undefined && row[key] !== null && row[key] !== "") {
                return row[key];
            }
        }
        return undefined;
    }

    function formFieldElement(form, fieldKey) {
        if (!form || !form.elements) {
            return null;
        }
        const byName = typeof form.elements.namedItem === "function"
            ? form.elements.namedItem(fieldKey)
            : null;
        if (byName) {
            if (typeof byName.length === "number" && !byName.tagName) {
                return byName[0] || null;
            }
            return byName;
        }
        return form.querySelector(`[name="${CSS.escape(fieldKey)}"]`);
    }

    function selectedRowForActions() {
        const row = rowContextWithSource(state.visibleRows[state.selectedRowIndex]);
        if (row) {
            return row;
        }
        if (state.currentViewModel && state.currentViewModel.kind === "datagrid") {
            return null;
        }
        return state.selectedRowContext;
    }

    function refreshRowFillButtons() {
        const row = selectedRowForActions();
        els.actions.querySelectorAll("[data-action-ui-key]").forEach((form) => {
            const button = form.querySelector("[data-fill-from-row]");
            if (!button) {
                return;
            }
            const action = currentAction(actionRefFromForm(form));
            const enabled = actionCanFillFromRow(action, row);
            button.disabled = !enabled;
            button.title = enabled ? "从当前选中行填充可匹配参数" : "当前选中行没有可匹配字段";
            if (enabled) {
                applySelectedRowToActionForm(form, { onlyIfEmpty: true, silent: true, focus: false });
            }
        });
    }

    function rowFieldCandidates(fieldOrKey, action) {
        const field = typeof fieldOrKey === "object" && fieldOrKey
            ? fieldOrKey
            : ((action && action.fields) || []).find((candidate) => candidate.key === fieldOrKey) || { key: fieldOrKey };
        const key = String(field.key || "");
        const semantic = String(field.semantic || "").trim();
        const candidates = [];
        candidates.push(key);
        if (semantic) {
            candidates.push(semantic);
            candidates.push(...aliasesForSemantic(semantic));
        }
        if (Array.isArray(field.aliases)) {
            candidates.push(...field.aliases);
        }
        candidates.push(...aliasesForSemantic(key));
        return uniqueNonEmpty(candidates);
    }

    function aliasesForSemantic(name) {
        const key = String(name || "");
        const registry = {
            ...builtInFieldAliases,
            ...fieldAliasRegistry(),
        };
        return Array.isArray(registry[key]) ? registry[key] : [];
    }

    function fieldAliasRegistry() {
        return {
            ...(runtimeConfig.field_aliases || runtimeConfig.fieldAliases || {}),
            ...((state.catalog && state.catalog.field_aliases) || {}),
            ...((state.screen && state.screen.field_aliases) || {}),
        };
    }

    function uniqueNonEmpty(values) {
        return values.filter((value, index, array) => {
            const text = String(value || "").trim();
            return text && array.indexOf(value) === index;
        });
    }

    async function loadScreen(screenKey, options = {}) {
        try {
            clearPendingRequest({ abort: true });
            closeMenu();
            closeModal();
            els.main.innerHTML = '<div class="tui-loading">正在加载工作区...</div>';
            setStatus("加载工作区");
            const screenSpec = await fetchJson(screenUrl(screenKey));
            if (isOperatorHomeScreen(screenSpec?.screen?.key)) {
                state.operatorHomePayload = null;
                state.operatorHomePromise = null;
            }
            renderScreen(screenSpec, options);
            refreshGovernanceBadges();
            return screenSpec;
        } catch (error) {
            resetLocationInput();
            renderBoundedApplicationError(error);
            return null;
        }
    }

    async function runAction(actionKey, form, options = {}) {
        const action = currentAction(actionKey);
        if (!action) {
            setStatus("任务未找到");
            return;
        }
        const actualActionKey = action.key;
        if (isHomeClientAction(actualActionKey)) {
            executeHomeAction(actualActionKey);
            return;
        }
        try {
            const params = options.params ? { ...options.params } : (form ? await collectParams(form, action) : { ...state.lastParams });
            state.lastAction = actualActionKey;
            state.lastParams = params;
            state.selectedRowIndex = 0;
            setCurrentLocation(action);
            closeMenu();
            closeModal();
            const controller = new AbortController();
            const requestId = startPendingRequest(controller);
            if (!options.dashboardPanelKey) {
                renderActionLoadingState(action, state.screen);
                scheduleSlowActionState(requestId, action);
            }
            const requestBody = { params, confirmed: Boolean(options.confirmed) };
            if (options.confirmation) {
                requestBody.confirmation = options.confirmation;
            }
            if (options.reauth) {
                requestBody.reauth = options.reauth;
            }
            const result = await fetchJson(actionRunUrl(actualActionKey), {
                method: "POST",
                body: JSON.stringify(requestBody),
                signal: controller.signal,
            });
            clearPendingRequest();
            if (Array.isArray(result.missing_fields) && result.missing_fields.length) {
                state.lastRaw = null;
                if (!options.dashboardPanelKey) {
                    renderViewModel(result.view_model);
                }
                showMissingFieldsPrompt(result, actualActionKey, params, options);
                updateRawDrawer();
                setStatus("等待补填");
                return;
            }
            if (result.confirmation_required) {
                state.lastRaw = null;
                if (!options.dashboardPanelKey) {
                    renderViewModel(result.view_model);
                }
                showActionConfirmation(result, actualActionKey, params, options);
                updateRawDrawer();
                setStatus("等待确认");
                return;
            }
            if (result.password_challenge_required) {
                state.lastRaw = null;
                if (!options.dashboardPanelKey) {
                    renderViewModel(result.view_model);
                }
                showPasswordChallenge(result, actualActionKey, params, options);
                updateRawDrawer();
                setStatus("等待验密");
                return;
            }
            markActionCompleted(action);
            state.lastRaw = result.debug?.raw_response ?? null;
            if (options.dashboardPanelKey) {
                updateRawDrawer();
                await refreshCurrentDashboardPanels();
                setStatus("操作完成，列表已刷新");
                refreshGovernanceBadges();
                return;
            }
            if (!isImmersiveDashboardScreen(state.screen?.screen)) {
                renderActions(state.screen.actions || [], state.screen.screen);
            }
            renderViewModel(result.view_model);
            renderResultInspector(result, result.view_model);
            updateRawDrawer();
            setStatus("读取完成");
            refreshGovernanceBadges();
        } catch (error) {
            if (error?.name === "AbortError") {
                setStatus("请求已取消");
                return;
            }
            clearPendingRequest();
            if (options.dashboardPanelKey) {
                const panels = Array.isArray(state.screen?.screen?.dashboard_panels)
                    ? state.screen.screen.dashboard_panels
                    : [];
                const panel = panels.find((item) => item.key === options.dashboardPanelKey);
                const container = panel
                    ? els.main.querySelector(`[data-dashboard-panel="${CSS.escape(panel.key)}"]`)
                    : null;
                if (panel && container) {
                    container.innerHTML = renderDashboardPanelShell(
                        panel,
                        renderDashboardPanelError(panel, error),
                    );
                    bindDashboardPanelOpenControls(container);
                    bindDashboardPanelRecovery(container, panel);
                } else {
                    renderBoundedApplicationError(error);
                }
            } else {
                renderBoundedApplicationError(error);
            }
        }
    }

    async function refreshCurrentDashboardPanels() {
        const panels = Array.isArray(state.screen?.screen?.dashboard_panels)
            ? state.screen.screen.dashboard_panels
            : [];
        await Promise.all(panels.map((panel) => loadDashboardPanel(panel)));
    }

    function renderViewModel(viewModel) {
        if (!viewModel) {
            renderError("没有返回可渲染的业务视图。");
            return;
        }
        state.currentViewModel = viewModel;
        setWorkspaceViewKind(viewModel.kind || "message");
        els.mainTitle.textContent = (viewModel.title || "视图").toUpperCase();
        if (renderRegisteredRenderer(viewModel, els.main)) {
            resetGridState({ preserveRowContext: true });
        } else if (requiresMissingRendererFallback(viewModel)) {
            resetGridState({ preserveRowContext: true });
            renderCustomFallback(viewModel);
        } else if (viewModel.kind === "datagrid") {
            renderDataGrid(viewModel);
        } else if (viewModel.kind === "detail") {
            resetGridState({ preserveRowContext: true });
            renderDetail(viewModel);
        } else if (viewModel.kind === "chart") {
            resetGridState({ preserveRowContext: true });
            renderChart(viewModel);
        } else if (viewModel.kind === "image") {
            resetGridState({ preserveRowContext: true });
            renderImage(viewModel);
        } else if (viewModel.kind === "kpi_trend") {
            resetGridState({ preserveRowContext: true });
            renderKpiTrend(viewModel);
        } else if (viewModel.kind === "table_chart") {
            resetGridState({ preserveRowContext: true });
            renderTableChart(viewModel);
        } else if (viewModel.kind === "host_slot") {
            resetGridState({ preserveRowContext: true });
            renderHostSlot(viewModel);
        } else if (viewModel.kind === "custom") {
            resetGridState({ preserveRowContext: true });
            renderCustomFallback(viewModel);
        } else {
            resetGridState({ preserveRowContext: true });
            renderMessage(viewModel);
        }
        bindDecisionCueActions();
        bindCopyButtons(els.main);
        updatePager(viewModel.pager || null);
        refreshRowFillButtons();
    }

    function renderRegisteredRenderer(viewModel, container) {
        const rendererName = String(viewModel.renderer || "").trim();
        if (!rendererName || builtInRendererNames.has(rendererName)) {
            return false;
        }
        const renderer = rendererRegistry.get(rendererName);
        if (!renderer) {
            return false;
        }
        container.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || rendererName)}</div>
            ${renderDecisionCue(viewModel)}
            <div class="tui-extension-host" data-renderer="${escapeHtml(rendererName)}"></div>
        `;
        const host = container.querySelector(".tui-extension-host");
        try {
            renderer({
                viewModel,
                container: host,
                runtimeConfig,
                escapeHtml,
            });
        } catch (_error) {
            host.innerHTML = renderEmptyState("扩展视图暂时不可用。", ["请稍后重试，或改用默认任务查看数据。"]);
        }
        return true;
    }

    function requiresMissingRendererFallback(viewModel) {
        const rendererName = String(viewModel.renderer || "").trim();
        if (!rendererName || builtInRendererNames.has(rendererName)) {
            return false;
        }
        return ["chart", "kpi_trend", "table_chart", "host_slot", "custom"].includes(viewModel.kind);
    }

    function renderDataGrid(viewModel) {
        state.currentViewModel = viewModel;
        state.currentColumns = viewModel.columns || [];
        state.currentRows = viewModel.rows || [];
        applyFilter(false);
    }

    function rowMatchesFilter(row) {
        const needle = state.filterText.trim().toLowerCase();
        if (!needle) {
            return true;
        }
        return Object.values(row || {}).some((value) => String(value ?? "").toLowerCase().includes(needle));
    }

    function applyFilter(announce) {
        if (!state.currentViewModel || state.currentViewModel.kind !== "datagrid") {
            if (announce) {
                setStatus("当前视图不可筛选");
            }
            return;
        }
        if (announce) {
            state.clientPage = 1;
        }
        state.visibleRows = state.currentRows.filter(rowMatchesFilter);
        state.selectedRowIndex = Math.min(state.selectedRowIndex, Math.max(0, state.visibleRows.length - 1));
        drawDataGrid();
        if (announce) {
            setStatus(state.filterText ? `筛选 ${state.visibleRows.length}/${state.currentRows.length}` : "筛选已清除");
        }
    }

    function drawDataGrid() {
        const viewModel = state.currentViewModel;
        const columns = state.currentColumns;
        const allRows = state.visibleRows;
        const localPage = !viewModel.pager && typeof runtimeCore.clientPage === "function"
            ? runtimeCore.clientPage(allRows, state.clientPage, state.clientPageSize)
            : { rows: allRows, pager: null };
        const rows = localPage.rows;
        const activePager = viewModel.pager || localPage.pager;
        state.lastPager = activePager;
        const filterSuffix = state.filterText ? ` / 筛选: ${state.filterText} (${allRows.length}/${state.currentRows.length})` : "";
        const emptyMessage = state.filterText
            ? "没有匹配的记录。"
            : (viewModel.empty_message || "暂无可显示数据。");
        const gridBody = rows.length && columns.length
            ? `
                <table>
                    <thead>
                        <tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr>
                    </thead>
                    <tbody>
                        ${rows.map((row, rowIndex) => `
                            <tr data-row-index="${rowIndex}" class="${rowIndex === state.selectedRowIndex ? "is-selected" : ""}">
                                ${columns.map((column) => `<td title="${escapeHtml(row[column.key])}">${escapeHtml(row[column.key])}</td>`).join("")}
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            `
            : renderEmptyState(
                emptyMessage,
                state.filterText ? ["清空筛选后查看全部记录。"] : viewModel.empty_guidance,
                state.filterText ? [] : viewModel.next_steps,
            );
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status)} / ${escapeHtml(viewModel.title)}${escapeHtml(filterSuffix)}</div>
            ${renderDecisionCue(viewModel)}
            <div class="tui-datagrid" role="grid" tabindex="0" aria-label="${escapeHtml(viewModel.title)}">
                ${gridBody}
            </div>
            ${renderDataGridPager(activePager)}
        `;
        els.main.querySelectorAll("[data-row-index]").forEach((row) => {
            row.addEventListener("click", () => selectRow(Number(row.dataset.rowIndex || 0)));
            row.addEventListener("dblclick", () => openSelectedRowDetail());
        });
        els.main.querySelectorAll("[data-page-delta]").forEach((button) => {
            button.addEventListener("click", () => pageDelta(Number(button.dataset.pageDelta || 0)));
        });
        bindNextStepButtons(els.main, viewModel.next_steps);
        if (rows.length) {
            state.selectedRowContext = rowContextWithSource(rows[state.selectedRowIndex]);
        } else {
            state.selectedRowContext = null;
        }
        renderSelectedRowInspector();
        refreshRowFillButtons();
    }

    function renderDataGridPager(pager) {
        if (!pager) {
            return "";
        }
        const page = pager.page ?? "-";
        const totalPages = pager.total_pages ?? "-";
        const totalRows = pager.total_rows ?? 0;
        return `
            <div class="tui-datagrid-pager" aria-label="分页">
                <button type="button" data-page-delta="-1" ${pager.has_previous ? "" : "disabled"}>上一页</button>
                <span>第 ${escapeHtml(page)} / ${escapeHtml(totalPages)} 页</span>
                <span>共 ${escapeHtml(totalRows)} 行</span>
                <button type="button" data-page-delta="1" ${pager.has_next ? "" : "disabled"}>下一页</button>
            </div>
        `;
    }

    function renderEmptyState(message, guidance, nextSteps = []) {
        const lines = (guidance || []).filter(Boolean);
        const steps = Array.isArray(nextSteps) ? nextSteps : [];
        return `
            <div class="tui-empty-state tui-empty-guidance">
                <strong>${escapeHtml(message)}</strong>
                ${lines.length ? `
                    <ul>
                        ${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}
                    </ul>
                ` : ""}
                ${steps.length ? `
                    <div class="tui-entry-actions">
                        ${steps.map((step, index) => `
                            <button type="button" data-next-step-index="${index}">
                                ${escapeHtml(step.label || "继续")}
                            </button>
                        `).join("")}
                    </div>
                ` : ""}
            </div>
        `;
    }

    function bindNextStepButtons(container, nextSteps) {
        container.querySelectorAll("[data-next-step-index]").forEach((button) => {
            button.addEventListener("click", () => {
                const index = Number(button.dataset.nextStepIndex || 0);
                executeNextStep((nextSteps || [])[index]);
            });
        });
    }

    function executeNextStep(step) {
        if (!step) {
            return;
        }
        if (step.action_key) {
            const params = step.params && typeof step.params === "object" ? step.params : { ...state.lastParams };
            runAction(step.action_key, null, { params });
            return;
        }
        if (step.screen_key) {
            loadScreen(step.screen_key);
            return;
        }
        setStatus(step.hint || "已记录下一步");
    }

    function renderChart(viewModel) {
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || "图表")}</div>
            ${renderDecisionCue(viewModel)}
            ${renderChartMarkup(viewModel)}
        `;
    }

    function renderImage(viewModel) {
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || "图片")}</div>
            ${renderDecisionCue(viewModel)}
            ${renderImageMarkup(viewModel)}
        `;
    }

    function renderKpiTrend(viewModel) {
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || "指标趋势")}</div>
            ${renderDecisionCue(viewModel)}
            ${renderKpiTrendMarkup(viewModel)}
        `;
    }

    function renderTableChart(viewModel) {
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || "表格图表")}</div>
            ${renderDecisionCue(viewModel)}
            ${renderTableChartMarkup(viewModel)}
        `;
    }

    function renderHostSlot(viewModel) {
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || "宿主插槽")}</div>
            ${renderDecisionCue(viewModel)}
            ${renderHostSlotMarkup(viewModel)}
        `;
        processHostSlot(els.main);
    }

    function renderCustomFallback(viewModel) {
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || "自定义视图")}</div>
            ${renderDecisionCue(viewModel)}
            ${renderExtensionFallback(viewModel)}
        `;
    }

    function renderChartMarkup(viewModel, options = {}) {
        const compact = Boolean(options.compact);
        const chartType = String(viewModel.chart_type || viewModel.renderer || "line").toLowerCase();
        const points = chartPoints(viewModel);
        if (!points.length) {
            return renderEmptyState(viewModel.empty_message || "暂无图表数据。", []);
        }
        const svg = chartType === "pie"
            ? renderPieSvg(points)
            : chartType === "bar"
                ? renderBarSvg(points)
                : renderLineSvg(points);
        return `
            <section class="tui-rich-view tui-chart-view ${compact ? "is-compact" : ""}">
                <div class="tui-rich-header">
                    <strong>${escapeHtml(viewModel.title || "Chart")}</strong>
                    <span>${escapeHtml(chartType.toUpperCase())}</span>
                </div>
                ${svg}
                <div class="tui-chart-legend">
                    ${points.slice(0, compact ? 4 : 8).map((point) => `
                        <span><i></i>${escapeHtml(point.label)} ${escapeHtml(formatNumber(point.value))}</span>
                    `).join("")}
                </div>
            </section>
        `;
    }

    function renderImageMarkup(viewModel, options = {}) {
        const source = imageSourceFromViewModel(viewModel);
        if (!source) {
            return renderEmptyState(viewModel.empty_message || "暂无图片链接。", []);
        }
        const alt = String(viewModel.alt || viewModel.caption || viewModel.title || "Image");
        const caption = String(viewModel.caption || "");
        const title = String(viewModel.title || "Image");
        return `
            <figure class="tui-rich-view tui-image-view ${options.compact ? "is-compact" : ""}">
                <div class="tui-rich-header">
                    <strong>${escapeHtml(title)}</strong>
                    <span>IMAGE</span>
                </div>
                <button class="tui-image-frame" type="button"
                        data-image-preview
                        data-image-src="${escapeHtml(source)}"
                        data-image-alt="${escapeHtml(alt)}"
                        data-image-caption="${escapeHtml(caption)}"
                        data-image-title="${escapeHtml(title)}">
                    <img src="${escapeHtml(source)}" alt="${escapeHtml(alt)}" loading="lazy" decoding="async">
                </button>
                ${caption ? `<figcaption>${escapeHtml(caption)}</figcaption>` : ""}
            </figure>
        `;
    }

    function imageSourceFromViewModel(viewModel) {
        const candidates = [
            viewModel.url,
            viewModel.src,
            viewModel.image_url,
            viewModel.imageUrl,
            viewModel.href,
        ];
        for (const candidate of candidates) {
            const source = normalizeImageSource(candidate);
            if (source) {
                return source;
            }
        }
        return "";
    }

    function normalizeImageSource(value) {
        const raw = String(value || "").trim();
        if (!raw) {
            return "";
        }
        try {
            const url = new URL(raw, window.location.href);
            if (url.protocol === "http:" || url.protocol === "https:") {
                return raw;
            }
            if (url.protocol === "data:" && /^data:image\/(?:apng|avif|gif|jpe?g|png|webp);/i.test(raw)) {
                return raw;
            }
            if (url.protocol === "data:" && allowSvgDataImages && /^data:image\/svg\+xml(?:[;,]|$)/i.test(raw)) {
                return raw;
            }
        } catch (_error) {
            return "";
        }
        return "";
    }

    function renderKpiTrendMarkup(viewModel, options = {}) {
        const points = (viewModel.trend || []).map(normalizePoint).filter(Boolean);
        const values = points.map((point) => point.value);
        const first = values[0] || 0;
        const last = values.length ? values[values.length - 1] : Number.parseFloat(viewModel.value) || 0;
        const delta = last - first;
        const directionClass = delta >= 0 ? "is-up" : "is-down";
        return `
            <section class="tui-rich-view tui-kpi-view ${options.compact ? "is-compact" : ""}">
                <div class="tui-kpi-main">
                    <span>${escapeHtml(viewModel.label || viewModel.title || "KPI")}</span>
                    <strong>${escapeHtml(viewModel.value || formatNumber(last))}</strong>
                    <em class="${directionClass}">${delta >= 0 ? "+" : ""}${escapeHtml(formatNumber(delta))}</em>
                </div>
                ${points.length ? `<div class="tui-kpi-spark">${renderLineSvg(points, { spark: true })}</div>` : ""}
            </section>
        `;
    }

    function renderTableChartMarkup(viewModel, options = {}) {
        const chart = viewModel.chart || {};
        const table = viewModel.table || {};
        return `
            <section class="tui-rich-view tui-table-chart-view ${options.compact ? "is-compact" : ""}">
                ${renderChartMarkup({ ...chart, title: chart.title || viewModel.title }, { compact: options.compact })}
                <div class="tui-table-chart-grid">
                    ${renderPanelDataGrid({ max_rows: options.compact ? 4 : 10, columns: table.columns || [] }, table)}
                </div>
            </section>
        `;
    }

    function renderHostSlotMarkup(viewModel, options = {}) {
        const allowHostHtml = Boolean(runtimeConfig.allowHostHtmlSlots);
        const html = String(viewModel.partial_html || "");
        const message = viewModel.fallback_message || "宿主插槽内容由宿主应用控制。";
        if (!allowHostHtml || !html) {
            return `
                <section class="tui-rich-view tui-host-slot ${options.compact ? "is-compact" : ""}">
                    <div class="tui-rich-header">
                        <strong>${escapeHtml(viewModel.slot_key || viewModel.title || "host-slot")}</strong>
                        <span>HOST SLOT</span>
                    </div>
                    ${renderEmptyState(message, allowHostHtml ? [] : ["当前 runtime 未开启 allowHostHtmlSlots。"])}
                </section>
            `;
        }
        return `
            <section class="tui-rich-view tui-host-slot ${options.compact ? "is-compact" : ""}" data-host-slot="${escapeHtml(viewModel.slot_key || "")}">
                ${html}
            </section>
        `;
    }

    function processHostSlot(container) {
        if (runtimeConfig.allowHostHtmlSlots && window.htmx && typeof window.htmx.process === "function") {
            container.querySelectorAll(".tui-host-slot").forEach((slot) => window.htmx.process(slot));
        }
    }

    function renderExtensionFallback(viewModel) {
        const rendererName = String(viewModel.renderer || "").trim() || "custom";
        return renderEmptyState(
            viewModel.fallback_message || `没有注册 renderer: ${rendererName}`,
            ["宿主可以通过 window.AgomTUIRenderers.register(name, rendererFn) 注册扩展。"],
        );
    }

    function chartPoints(viewModel) {
        const series = Array.isArray(viewModel.series) ? viewModel.series : [];
        const firstSeries = series.find((item) => Array.isArray(item?.points));
        const points = firstSeries ? firstSeries.points : (Array.isArray(viewModel.points) ? viewModel.points : []);
        return points.map(normalizePoint).filter(Boolean);
    }

    function normalizePoint(point, index = 0) {
        if (point === null || point === undefined) {
            return null;
        }
        if (typeof point === "number") {
            return { label: String(index + 1), value: point };
        }
        const value = Number.parseFloat(point.value ?? point.y ?? point.count ?? point.total);
        if (!Number.isFinite(value)) {
            return null;
        }
        return {
            label: String(point.label ?? point.x ?? point.name ?? index + 1),
            value,
        };
    }

    function chartScale(points, width, height, padding) {
        const values = points.map((point) => point.value);
        const min = Math.min(0, ...values);
        const max = Math.max(1, ...values);
        const span = max - min || 1;
        return {
            x(index) {
                if (points.length <= 1) {
                    return width / 2;
                }
                return padding + (index / (points.length - 1)) * (width - padding * 2);
            },
            y(value) {
                return height - padding - ((value - min) / span) * (height - padding * 2);
            },
        };
    }

    function renderLineSvg(points, options = {}) {
        const width = options.spark ? 240 : 640;
        const height = options.spark ? 72 : 220;
        const padding = options.spark ? 8 : 28;
        const scale = chartScale(points, width, height, padding);
        const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${scale.x(index).toFixed(1)} ${scale.y(point.value).toFixed(1)}`).join(" ");
        return `
            <svg class="tui-chart-svg ${options.spark ? "is-spark" : ""}" viewBox="0 0 ${width} ${height}" role="img">
                <path class="tui-chart-gridline" d="M${padding} ${height - padding}H${width - padding}"></path>
                <path class="tui-chart-line" d="${escapeHtml(path)}"></path>
                ${points.map((point, index) => `<circle class="tui-chart-point" cx="${scale.x(index).toFixed(1)}" cy="${scale.y(point.value).toFixed(1)}" r="${options.spark ? 2 : 3}"></circle>`).join("")}
            </svg>
        `;
    }

    function renderBarSvg(points) {
        const width = 640;
        const height = 220;
        const padding = 28;
        const max = Math.max(1, ...points.map((point) => point.value));
        const barGap = 8;
        const barWidth = Math.max(8, (width - padding * 2 - barGap * (points.length - 1)) / points.length);
        return `
            <svg class="tui-chart-svg" viewBox="0 0 ${width} ${height}" role="img">
                <path class="tui-chart-gridline" d="M${padding} ${height - padding}H${width - padding}"></path>
                ${points.map((point, index) => {
                    const x = padding + index * (barWidth + barGap);
                    const barHeight = Math.max(2, (point.value / max) * (height - padding * 2));
                    const y = height - padding - barHeight;
                    return `<rect class="tui-chart-bar" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}"></rect>`;
                }).join("")}
            </svg>
        `;
    }

    function renderPieSvg(points) {
        const total = points.reduce((sum, point) => sum + Math.max(0, point.value), 0) || 1;
        let offset = 0;
        const slices = points.map((point, index) => {
            const value = Math.max(0, point.value);
            const dash = (value / total) * 100;
            const slice = `<circle class="tui-chart-pie-slice slice-${index % 6}" r="70" cx="100" cy="100" pathLength="100" stroke-dasharray="${dash} ${100 - dash}" stroke-dashoffset="${-offset}"></circle>`;
            offset += dash;
            return slice;
        }).join("");
        return `
            <svg class="tui-chart-svg tui-chart-pie" viewBox="0 0 200 200" role="img">
                ${slices}
                <circle class="tui-chart-pie-hole" r="38" cx="100" cy="100"></circle>
            </svg>
        `;
    }

    function formatNumber(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) {
            return String(value ?? "-");
        }
        return Math.abs(number) >= 100 ? number.toFixed(0) : number.toFixed(2).replace(/\.00$/, "");
    }

    function renderDetail(viewModel) {
        const semantics = currentActionSemantics();
        const detailBody = semantics.length
            ? renderSemanticDetailView(viewModel, semantics)
            : renderSemanticGridFields(viewModel.fields || []);
        const nested = semantics.length ? [] : (viewModel.nested || []);
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status)} / ${escapeHtml(viewModel.title)}</div>
            ${renderDecisionCue(viewModel)}
            ${detailBody || renderEmptyState("暂无摘要数据。", [])}
            ${nested.length ? `
                <div class="tui-nested-list">
                    ${nested.map((item) => `<span>${escapeHtml(item.label)}: ${escapeHtml(item.count)} 行</span>`).join("")}
                </div>
            ` : ""}
            ${Array.isArray(viewModel.next_steps) && viewModel.next_steps.length ? renderEmptyState("建议下一步", [], viewModel.next_steps) : ""}
        `;
        bindNextStepButtons(els.main, viewModel.next_steps);
    }

    function renderMessage(viewModel) {
        const sections = Array.isArray(viewModel.sections) ? viewModel.sections : [];
        const body = sections.length
            ? sections.map((section) => `
                <section class="tui-message-section">
                    <h4>${escapeHtml(section.title || "摘要")}</h4>
                    ${(section.body || []).map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
                    ${(section.rows || []).length ? `
                        <dl class="tui-message-fields">
                            ${section.rows.map((row) => `
                                <dt>${escapeHtml(row.label)}</dt>
                                <dd>${escapeHtml(row.value)}</dd>
                            `).join("")}
                        </dl>
                    ` : ""}
                </section>
            `).join("")
            : `<div class="tui-message">${escapeHtml(viewModel.message || "")}</div>`;
        els.main.innerHTML = `
            <div class="tui-view-status">${escapeHtml(viewModel.status || "正常")} / ${escapeHtml(viewModel.title || "消息")}</div>
            ${renderDecisionCue(viewModel)}
            <div class="tui-message-list">${body}</div>
            ${Array.isArray(viewModel.next_steps) && viewModel.next_steps.length ? renderEmptyState("建议下一步", [], viewModel.next_steps) : ""}
        `;
        bindNextStepButtons(els.main, viewModel.next_steps);
    }

    function renderDecisionCue(viewModel) {
        const screen = state.screen?.screen || {};
        const context = screen.business_context || {};
        if (!context.decision_output && !context.objective && !viewModel?.business_summary) {
            return "";
        }
        const workflow = screen.workflow || {};
        const next = workflow.next || {};
        const actions = (state.screen && state.screen.actions) || [];
        const summary = summarizeActions(actions);
        const evidence = resultEvidenceLabel(viewModel);
        const businessSummary = String(viewModel?.business_summary || "").trim();
        const rows = [
            ["判断产出", businessSummary || context.decision_output || context.objective],
            ["当前证据", evidence],
        ];
        if (viewModel?.blocking_reason) {
            rows.push(["当前阻断", viewModel.blocking_reason]);
        }
        const cueActions = [];
        if (summary.operation) {
            rows.push(["可执行操作", `${summary.operation} 项，提交前确认`]);
        }
        const progress = screenProgress(actions);
        if (progress.total) {
            rows.push(["本屏进度", `${progress.completed}/${progress.total}`]);
        }
        const nextPrimary = nextPrimaryAction();
        if (nextPrimary) {
            rows.push(["本屏下一项", nextPrimary.label]);
            cueActions.push({
                command: "next-primary",
                label: nextPrimary.label,
                key: "F6",
                title: "运行下一主流程",
            });
        }
        if (next.label) {
            rows.push(["下一步", next.label]);
            cueActions.push({
                command: "workflow-next",
                label: next.label,
                key: "F4",
                title: "进入流程下一屏",
            });
        }
        return `
            <section class="tui-decision-cue">
                ${rows.map(([label, value]) => `
                    <div>
                        <span>${escapeHtml(label)}</span>
                        <strong>${escapeHtml(value)}</strong>
                    </div>
                `).join("")}
                ${cueActions.length ? `
                    <div class="tui-decision-actions">
                        <span>继续</span>
                        <strong>
                            ${cueActions.map((action) => `
                                <button type="button" data-decision-action="${escapeHtml(action.command)}">
                                    ${escapeHtml(action.title)}: ${escapeHtml(action.label)}
                                    <kbd>${escapeHtml(action.key)}</kbd>
                                </button>
                            `).join("")}
                        </strong>
                    </div>
                ` : ""}
            </section>
        `;
    }

    function bindDecisionCueActions() {
        els.main.querySelectorAll("[data-decision-action]").forEach((button) => {
            button.addEventListener("click", () => {
                const command = button.dataset.decisionAction;
                if (command === "next-primary") {
                    runNextPrimaryAction();
                } else if (command === "workflow-next") {
                    loadWorkflowStep(1);
                }
            });
        });
    }

    function resultEvidenceLabel(viewModel) {
        if (!viewModel) {
            return "尚未返回业务视图";
        }
        if (viewModel.kind === "datagrid") {
            const total = viewModel.pager?.total_rows ?? state.currentRows.length;
            if (state.filterText) {
                return `筛选后 ${state.visibleRows.length}/${state.currentRows.length} 行`;
            }
            return `表格 ${state.currentRows.length}/${total} 行`;
        }
        if (viewModel.kind === "detail") {
            const fields = (viewModel.fields || []).length;
            const nested = (viewModel.nested || []).reduce((count, item) => count + Number(item.count || 0), 0);
            return nested ? `详情 ${fields} 项，关联 ${nested} 行` : `详情 ${fields} 项`;
        }
        if (viewModel.kind === "chart") {
            const points = chartPoints(viewModel).length;
            return `图表 ${points} 点`;
        }
        if (viewModel.kind === "kpi_trend") {
            const points = (viewModel.trend || []).length;
            return points ? `指标趋势 ${points} 点` : "指标趋势";
        }
        if (viewModel.kind === "table_chart") {
            const rows = viewModel.table?.rows?.length || 0;
            return `图表表格 ${rows} 行`;
        }
        if (viewModel.kind === "host_slot") {
            return "宿主插槽";
        }
        if (viewModel.kind === "custom") {
            return `自定义 ${viewModel.renderer || "renderer"}`;
        }
        const sections = (viewModel.sections || []).length;
        return sections ? `消息 ${sections} 段` : "消息结果";
    }

    function renderInspector(info) {
        const sections = Array.isArray(info.sections) ? info.sections : [];
        const rows = normalizeInspectorRows(info.rows || []);
        const bodyLines = operatorText(info.body || "").split(/\n+/).map((line) => line.trim()).filter(Boolean);
        const rowsTitle = operatorText(info.rowsTitle || "流程状态");
        els.inspector.innerHTML = `
            <section class="tui-inspector-card tui-inspector-summary">
                <div class="tui-inspector-title">${escapeHtml(info.title || "说明")}</div>
                ${bodyLines.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
            </section>
            ${rows.length ? `
                <section class="tui-inspector-card">
                    <div class="tui-inspector-title">${escapeHtml(rowsTitle)}</div>
                    <dl class="tui-inspector-grid">
                        ${rows.map((row) => `
                            <dt>${escapeHtml(row.label)}</dt>
                            <dd>${escapeHtml(row.value)}</dd>
                        `).join("")}
                    </dl>
                </section>
            ` : ""}
            ${sections.length ? `
                <div class="tui-inspector-sections">
                    ${sections.map((section) => `
                        <section class="tui-message-section">
                            <h4>${escapeHtml(operatorText(section.title || "摘要"))}</h4>
                            ${(section.body || []).map((line) => `<p>${escapeHtml(operatorText(line))}</p>`).join("")}
                            ${(section.actions || []).length ? `
                                <div class="tui-inspector-actions">
                                    ${section.actions.map((action) => `
                                        <button type="button" data-inspector-action="${escapeHtml(action.ui_key)}">
                                            <span>${escapeHtml(action.label)}</span>
                                            <kbd>${escapeHtml(action.verb)}</kbd>
                                        </button>
                                    `).join("")}
                                </div>
                            ` : ""}
                            ${(section.rows || []).length ? `
                                <dl class="tui-message-fields">
                                    ${normalizeInspectorRows(section.rows).map((row) => `
                                        <dt>${escapeHtml(row.label)}</dt>
                                        <dd>${escapeHtml(row.value)}</dd>
                                    `).join("")}
                                </dl>
                            ` : ""}
                        </section>
                    `).join("")}
                </div>
            ` : ""}
        `;
        els.inspector.querySelectorAll("[data-inspector-action]").forEach((button) => {
            button.addEventListener("click", () => runInspectorAction(button.dataset.inspectorAction));
        });
    }

    function normalizeInspectorRows(rows) {
        return (rows || []).map((row) => {
            if (Array.isArray(row)) {
                return { label: row[0], value: row[1] };
            }
            return { label: row.label, value: row.value };
        }).filter((row) => row.label !== undefined && row.value !== undefined)
            .map((row) => ({
                label: operatorText(row.label),
                value: operatorText(row.value),
            }));
    }

    function inspectorFlowRows(result) {
        const progress = screenProgress();
        const nextAction = nextPrimaryAction();
        const operationCount = ((state.screen && state.screen.actions) || [])
            .filter((action) => actionTier(action) === "operation")
            .length;
        const rows = [
            ["操作方式", actionVerbLabel(result.action)],
            ["本屏进度", `${progress.completed}/${progress.total}`],
        ];
        if (nextAction && nextAction.key !== result.action.key) {
            rows.push(["下一项", nextAction.label]);
        }
        if (operationCount) {
            rows.push(["可执行操作", `${operationCount} 项`]);
        }
        if (result.action.confirmation_required) {
            rows.push(["确认策略", "提交前会要求确认"]);
        }
        return rows;
    }

    function renderResultInspector(result, viewModel) {
        const businessContext = state.screen?.screen?.business_context || {};
        const contextSections = businessContextSections(businessContext);
        const operationActions = ((state.screen && state.screen.actions) || [])
            .filter((action) => actionTier(action) === "operation")
            .slice(0, 5)
            .map((action) => `${action.label} / ${actionVerbLabel(action)}`);
        const actionRows = inspectorFlowRows(result);
        const sections = [
            ...contextSections,
            ...(operationActions.length ? [{
                title: "后续动作",
                body: operationActions,
                rows: [],
            }] : []),
        ];
        if (!viewModel) {
            renderInspector({
                title: result.action.label,
                body: result.action.description || "",
                rows: actionRows,
                sections,
            });
            return;
        }
        if (viewModel.kind === "detail") {
            renderInspector({
                title: "操作说明",
                body: result.action.description || "中间主面板显示完整业务明细，右栏只保留流程、证据与后续动作。",
                rowsTitle: "流程状态",
                rows: actionRows,
                sections: [
                    {
                        title: "阅读提示",
                        body: ["完整业务明细已在中间主面板显示。右栏不再重复渲染同一对象。"],
                        rows: [],
                    },
                    ...sections,
                ],
            });
            return;
        }
        if (viewModel.kind === "message") {
            renderInspector({
                title: "操作说明",
                body: result.action.description || "中间主面板显示当前结果说明，右栏保留导航与后续动作。",
                rowsTitle: "流程状态",
                rows: actionRows,
                sections: [
                    {
                        title: "阅读提示",
                        body: ["结果说明已在中间主面板显示。右栏保留流程导航、业务目标与后续动作。"],
                        rows: [],
                    },
                    ...sections,
                ],
            });
            return;
        }
        renderSelectedRowInspector([
            ...actionRows,
            ...operationActions.slice(0, 3).map((label, index) => [`可执行动作 ${index + 1}`, label]),
        ]);
    }

    function renderError(message) {
        els.main.innerHTML = `<div class="tui-error">${escapeHtml(message)}</div>`;
        updatePager(null);
        setStatus("错误");
    }

    function updatePager(pager) {
        state.lastPager = pager;
        if (!pager) {
            els.pager.textContent = "页 -/- | 0 行";
            return;
        }
        els.pager.textContent = `页 ${pager.page}/${pager.total_pages} | ${pager.total_rows} 行 | ${pager.has_previous ? "PgUp" : "--"} / ${pager.has_next ? "PgDn" : "--"}`;
    }

    function updateRawDrawer() {
        els.rawPanel.textContent = state.lastRaw === null ? "尚未加载原始响应。" : JSON.stringify(state.lastRaw, null, 2);
    }

    function toggleRawDrawer(show) {
        els.rawDrawer.hidden = typeof show === "boolean" ? !show : !els.rawDrawer.hidden;
        setStatus(els.rawDrawer.hidden ? "原始响应关闭" : "原始响应打开");
    }

    function selectRow(index) {
        state.selectedRowIndex = index;
        els.main.querySelectorAll("[data-row-index]").forEach((row) => {
            row.classList.toggle("is-selected", Number(row.dataset.rowIndex || 0) === index);
        });
        const row = state.visibleRows[index];
        state.selectedRowContext = rowContextWithSource(row);
        if (row) {
            setStatus(`行 ${index + 1}/${state.visibleRows.length}`);
            renderSelectedRowInspector();
        }
        refreshRowFillButtons();
    }

    function renderSelectedRowInspector(prefixRows = []) {
        if (!state.currentViewModel || state.currentViewModel.kind !== "datagrid") {
            return;
        }
        const row = state.visibleRows[state.selectedRowIndex];
        const rows = row
            ? rowDisplayRows(row, 14)
            : [["状态", state.filterText ? "没有匹配记录" : "暂无记录"]];
        const rowContext = rowContextWithSource(row);
        const rowActions = rowContext ? actionsAvailableForRow(rowContext) : [];
        const sections = [];
        if (rowActions.length) {
            sections.push({
                title: "选中行可做",
                body: ["直接使用选中记录填入参数。"],
                actions: rowActions.map((action) => ({
                    ui_key: actionUiKey(action),
                    label: action.label,
                    verb: actionVerbLabel(action),
                })),
                rows: [],
            });
        }
        sections.push({
            title: "键盘操作",
            body: ["方向键移动，Enter 打开详情，F7 筛选，F9 进入任务区，F8 导出。"],
            rows: [],
        });
        renderInspector({
            title: row ? `选中记录 ${state.selectedRowIndex + 1}/${state.visibleRows.length}` : "表格状态",
            body: state.currentViewModel.title || "",
            rows: [...prefixRows, ...rows],
            sections,
        });
    }

    function actionsAvailableForRow(row) {
        const actions = (state.screen && state.screen.actions) || [];
        return actions
            .filter((action) => {
                const fields = (action.fields || []).filter((field) => field.input_type !== "hidden");
                if (!fields.length) {
                    return false;
                }
                return fields.some((field) => rowValueForField(row, field.key, action) !== undefined);
            })
            .sort((left, right) => {
                const tierRank = { operation: 0, advanced: 1, primary: 2, support: 3 };
                return (tierRank[actionTier(left)] ?? 9) - (tierRank[actionTier(right)] ?? 9)
                    || Number(left.sequence || 999) - Number(right.sequence || 999);
            })
            .slice(0, 5);
    }

    function paramsFromRowForAction(row, action) {
        const params = {};
        const fields = (action && action.fields) || [];
        fields.forEach((field) => {
            if (field.input_type === "hidden") {
                return;
            }
            const value = rowValueForField(row, field.key, action);
            if (value !== undefined && value !== null && value !== "") {
                params[field.key] = value;
            }
        });
        return params;
    }

    function runInspectorAction(actionRef) {
        const row = rowContextWithSource(state.visibleRows[state.selectedRowIndex]);
        const action = currentAction(actionRef);
        if (!row || !action) {
            setStatus("没有可执行的选中行任务");
            return;
        }
        const params = paramsFromRowForAction(row, action);
        const missing = (action.fields || [])
            .filter((field) => field.required && !field.default && field.input_type !== "hidden")
            .filter((field) => params[field.key] === undefined || params[field.key] === null || String(params[field.key]).trim() === "");
        if (missing.length) {
            setStatus(`选中行缺少参数: ${missing.map((field) => field.label).join(", ")}`);
            return;
        }
        runAction(action.key, null, { params });
    }

    function moveRow(delta) {
        const rows = els.main.querySelectorAll("[data-row-index]");
        if (!rows.length) {
            return;
        }
        const next = Math.max(0, Math.min(rows.length - 1, state.selectedRowIndex + delta));
        selectRow(next);
        rows[next].scrollIntoView({ block: "nearest" });
    }

    async function pageDelta(delta) {
        if (state.lastPager?.client_side) {
            if (delta < 0 && !state.lastPager.has_previous) {
                setStatus("已经是第一页");
                return;
            }
            if (delta > 0 && !state.lastPager.has_next) {
                setStatus("已经是最后一页");
                return;
            }
            state.clientPage = Math.max(1, state.clientPage + delta);
            state.selectedRowIndex = 0;
            drawDataGrid();
            setStatus(`第 ${state.clientPage} 页`);
            return;
        }
        if (!state.lastAction || !state.lastPager) {
            setStatus("当前视图不可翻页");
            return;
        }
        const action = currentAction(state.lastAction);
        if (!action) {
            setStatus("任务未找到");
            return;
        }
        if (delta < 0 && !state.lastPager.has_previous) {
            setStatus("已经是第一页");
            return;
        }
        if (delta > 0 && !state.lastPager.has_next) {
            setStatus("已经是最后一页");
            return;
        }
        const patch = paginationParamPatch(action, state.lastPager, state.lastParams, delta);
        if (!patch) {
            setStatus("当前分页参数不可推断");
            return;
        }
        state.lastParams = { ...state.lastParams, ...patch };
        await runAction(state.lastAction, null);
    }

    function paginationParamPatch(action, pager, params, delta) {
        const pagination = action.pagination || {};
        const pagerMode = String(pager.pagination_mode || pager.mode || "");
        const mode = pagination.mode || (pagerMode === "limit_offset" ? "offset" : pagerMode) || inferPaginationMode(action);
        if (mode === "cursor") {
            const cursorParam = pagination.cursor_param || firstFieldKey(action, ["cursor", "nextCursor", "next_cursor"]);
            const cursor = delta > 0
                ? valueAtPath(pager, pagination.next_cursor_path || "next_cursor")
                : valueAtPath(pager, pagination.previous_cursor_path || "previous_cursor");
            return cursorParam && cursor ? { [cursorParam]: cursor } : null;
        }
        if (mode === "offset") {
            const offsetParam = pagination.offset_param || firstFieldKey(action, ["offset", "start"]);
            const limitParam = pagination.limit_param || firstFieldKey(action, ["limit", "pageSize", "page_size"]);
            const limit = Number(params[limitParam] || pager.page_size || pager.limit || 10);
            const current = Number(params[offsetParam] || pager.offset || 0);
            if (!offsetParam || !Number.isFinite(limit) || !Number.isFinite(current)) {
                return null;
            }
            const nextOffset = Math.max(0, current + (delta * limit));
            return limitParam ? { [offsetParam]: nextOffset, [limitParam]: limit } : { [offsetParam]: nextOffset };
        }
        const pageParam = pagination.page_param || firstFieldKey(action, ["page", "pageNum", "page_num", "pageNo", "page_no"]);
        const pageSizeParam = pagination.page_size_param || firstFieldKey(action, ["page_size", "pageSize", "page_size", "limit", "size"]);
        const current = Number(params[pageParam] || pager.page || 1);
        if (!pageParam || !Number.isFinite(current)) {
            return null;
        }
        const next = Math.max(1, current + delta);
        const patch = { [pageParam]: next };
        const pageSize = Number(params[pageSizeParam] || pager.page_size || pager.pageSize || 0);
        if (pageSizeParam && Number.isFinite(pageSize) && pageSize > 0) {
            patch[pageSizeParam] = pageSize;
        }
        return patch;
    }

    function inferPaginationMode(action) {
        const fields = (action.fields || []).map((field) => String(field.key || ""));
        if (fields.some((key) => ["cursor", "nextCursor", "next_cursor"].includes(key))) {
            return "cursor";
        }
        if (fields.some((key) => ["offset", "start"].includes(key))) {
            return "offset";
        }
        return "page";
    }

    function firstFieldKey(action, candidates) {
        const fields = (action.fields || []).map((field) => String(field.key || ""));
        return candidates.find((candidate) => fields.includes(candidate)) || candidates[0] || "";
    }

    function valueAtPath(value, path) {
        if (!path) {
            return undefined;
        }
        return String(path).split(".").reduce((current, key) => {
            if (current && Object.prototype.hasOwnProperty.call(current, key)) {
                return current[key];
            }
            return undefined;
        }, value);
    }

    function showModal(title, bodyHtml, options = {}) {
        els.modalTitle.textContent = title;
        els.modalBody.innerHTML = bodyHtml;
        els.modal.classList.remove("is-image-preview");
        if (options.className) {
            els.modal.classList.add(options.className);
        }
        els.modal.hidden = false;
        els.modalClose.focus();
    }

    function showImagePreview(trigger) {
        const source = normalizeImageSource(trigger.dataset.imageSrc || "");
        if (!source) {
            setStatus("图片链接不可用");
            return;
        }
        const title = trigger.dataset.imageTitle || "图片预览";
        const alt = trigger.dataset.imageAlt || title;
        const caption = trigger.dataset.imageCaption || "";
        showModal(title, `
            <figure class="tui-image-lightbox">
                <div class="tui-image-lightbox-frame">
                    <img src="${escapeHtml(source)}" alt="${escapeHtml(alt)}" loading="eager" decoding="async">
                </div>
                <figcaption>
                    ${caption ? `<span>${escapeHtml(caption)}</span>` : ""}
                    <a href="${escapeHtml(source)}" target="_blank" rel="noopener noreferrer">打开原图</a>
                </figcaption>
            </figure>
        `, { className: "is-image-preview" });
        setStatus("图片预览");
    }

    function showMissingFieldsPrompt(result, actionKey, params, options = {}) {
        const fields = result.missing_fields || [];
        const promptAction = result.action || currentAction(actionKey) || { key: actionKey || "missing-fields" };
        showModal("补填参数", `
            <form class="tui-confirmation tui-missing-fields" data-missing-fields-form>
                <p>${escapeHtml(result.view_model?.message || "补齐参数后继续执行。")}</p>
                <div class="tui-missing-fields-list">
                    ${fields.map((field) => renderField(promptAction, {
                        ...field,
                        default: params[field.key] ?? field.default ?? "",
                    })).join("")}
                </div>
                <div class="tui-confirmation-actions">
                    <button class="tui-confirm-button" type="submit">继续</button>
                    <button class="tui-confirm-button" type="button" data-cancel-action>取消</button>
                </div>
            </form>
        `);
        const form = els.modalBody.querySelector("[data-missing-fields-form]");
        const cancelButton = els.modalBody.querySelector("[data-cancel-action]");
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const completed = { ...params };
            fields.forEach((field) => {
                const input = form.querySelector(`[name="${CSS.escape(field.key)}"]`);
                if (input) {
                    completed[field.key] = coerceFieldValue(field, input.value, input.checked);
                }
            });
            closeModal();
            runAction(actionKey, null, { ...options, params: completed });
        });
        cancelButton.addEventListener("click", () => {
            closeModal();
            setStatus("已取消");
        });
        form.querySelector("select, input, textarea")?.focus();
    }

    function showActionConfirmation(result, actionKey, params, options = {}) {
        const confirmation = result.confirmation || {};
        showModal(confirmation.title || "确认操作", `
            <div class="tui-confirmation">
                <p>${escapeHtml(confirmation.message || "确认后执行此操作。")}</p>
                <div class="tui-confirmation-actions">
                    <button class="tui-confirm-button" type="button" data-confirm-action>${escapeHtml(confirmation.confirm_label || "确认执行")}</button>
                    <button class="tui-confirm-button" type="button" data-cancel-action>${escapeHtml(confirmation.cancel_label || "取消")}</button>
                </div>
            </div>
        `);
        const confirmButton = els.modalBody.querySelector("[data-confirm-action]");
        const cancelButton = els.modalBody.querySelector("[data-cancel-action]");
        confirmButton.addEventListener("click", () => {
            closeModal();
            runAction(actionKey, null, {
                ...options,
                confirmed: true,
                params,
                confirmation: {
                    confirmed: true,
                    confirmed_at: new Date().toISOString(),
                    message: confirmation.message || "",
                },
            });
        });
        cancelButton.addEventListener("click", () => {
            closeModal();
            setStatus("已取消");
        });
        confirmButton.focus();
    }

    function showPasswordChallenge(result, actionKey, params, options = {}) {
        const challenge = result.password_challenge || {};
        showModal("重新验证身份", `
            <form class="tui-confirmation" data-password-challenge-form>
                <p>${escapeHtml(challenge.message || "该操作需要重新验证身份。")}</p>
                <label class="tui-field">
                    <span>密码</span>
                    <input name="password" type="password" autocomplete="current-password" required>
                </label>
                <div class="tui-confirmation-actions">
                    <button class="tui-confirm-button" type="submit">验证并继续</button>
                    <button class="tui-confirm-button" type="button" data-cancel-action>取消</button>
                </div>
            </form>
        `);
        const form = els.modalBody.querySelector("[data-password-challenge-form]");
        const cancelButton = els.modalBody.querySelector("[data-cancel-action]");
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const password = form.querySelector("[name='password']")?.value || "";
            closeModal();
            runAction(actionKey, null, {
                ...options,
                params,
                reauth: {
                    method: "password",
                    credential: password,
                    challenge_id: challenge.challenge_id || "",
                    submitted_at: new Date().toISOString(),
                },
            });
        });
        cancelButton.addEventListener("click", () => {
            closeModal();
            setStatus("已取消");
        });
        form.querySelector("input")?.focus();
    }

    function closeModal() {
        if (els.modal) {
            els.modal.hidden = true;
            els.modal.classList.remove("is-image-preview");
        }
    }

    function openSelectedRowDetail() {
        const row = state.visibleRows[state.selectedRowIndex];
        if (!row) {
            setStatus("未选择行");
            return;
        }
        const rows = rowDisplayRows(row).map(([key, value]) => `
            <dt>${escapeHtml(key)}</dt>
            <dd>${escapeHtml(value)}</dd>
        `).join("");
        const targetScreen = String(row?.target_screen || "").trim();
        const targetActionKey = String(row?.target_action_key || "").trim();
        const canDrillDown = Boolean(targetScreen || targetActionKey);
        showModal(
            `第 ${state.selectedRowIndex + 1} 行`,
            `
                <dl class="tui-detail-grid">${rows}</dl>
                ${canDrillDown ? `
                    <div class="tui-modal-actions">
                        <button type="button" data-row-target-screen="${escapeHtml(targetScreen)}" data-row-target-action="${escapeHtml(targetActionKey)}">进入处理屏</button>
                    </div>
                ` : ""}
            `,
        );
        els.modalBody?.querySelector("[data-row-target-screen], [data-row-target-action]")?.addEventListener("click", async () => {
            closeModal();
            const nextScreen = targetScreen || state.screen?.screen?.key || "";
            if (!nextScreen) {
                return;
            }
            await loadScreen(nextScreen);
            if (targetActionKey && currentAction(targetActionKey)) {
                runAction(targetActionKey, null, { params: {} });
            }
        });
        setStatus("行详情");
    }

    function showHelp() {
        showModal("帮助", `
            <div class="tui-help-grid">
                <span>F1</span><span>打开帮助</span>
                <span>F2</span><span>展开或收起模块导航</span>
                <span>F3</span><span>进入流程上一屏</span>
                <span>F4</span><span>进入流程下一屏</span>
                <span>F5</span><span>刷新当前工作区或任务</span>
                <span>F6</span><span>执行本屏下一主流程任务</span>
                <span>F7</span><span>筛选当前表格</span>
                <span>F8</span><span>导出当前表格 CSV</span>
                <span>F9</span><span>定位任务区</span>
                <span>F10</span><span>展开或收起说明栏</span>
                <span>Alt+T</span><span>循环切换主题 A / B / C</span>
                <span>Ctrl+T</span><span>查看当前主题与三套风格</span>
                <span>方向键</span><span>移动表格选中行</span>
                <span>Enter</span><span>打开选中行详情</span>
                <span>PgUp/PgDn</span><span>存在分页时翻页</span>
                <span>Esc</span><span>关闭菜单、筛选、调试抽屉或弹窗</span>
            </div>
        `);
        setStatus("帮助");
    }

    function showThemeStatus() {
        showModal("主题", `
            <div class="tui-help-grid">
                <span>当前</span><span>STYLE: ${escapeHtml(state.themeKey)}</span>
                <span>A</span><span>Norton PCTOOLS 蓝底黄字风格</span>
                <span>B</span><span>中性金融专业终端风格</span>
                <span>C</span><span>风控 / 控制台风格</span>
                <span>Alt+T</span><span>循环切换，不刷新页面，不丢失当前状态</span>
            </div>
        `);
        setStatus(`当前主题: ${state.themeKey}`);
    }

    function showFilterBar() {
        if (!state.currentViewModel || state.currentViewModel.kind !== "datagrid") {
            setStatus("当前视图不可筛选");
            return;
        }
        els.filterBar.hidden = false;
        els.filterInput.value = state.filterText;
        els.filterInput.focus();
        els.filterInput.select();
        setStatus("筛选就绪");
    }

    function hideFilterBar() {
        if (els.filterBar) {
            els.filterBar.hidden = true;
        }
    }

    function clearFilter() {
        state.filterText = "";
        if (els.filterInput) {
            els.filterInput.value = "";
        }
        applyFilter(true);
    }

    function csvEscape(value) {
        const text = String(value ?? "");
        return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    }

    function exportGrid() {
        if (!state.currentViewModel || state.currentViewModel.kind !== "datagrid") {
            setStatus("当前视图不可导出");
            return;
        }
        const columns = state.currentColumns;
        const rows = state.visibleRows;
        const csv = [
            columns.map((column) => csvEscape(column.label)).join(","),
            ...rows.map((row) => columns.map((column) => csvEscape(row[column.key])).join(",")),
        ].join("\r\n");
        const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        const title = (state.currentViewModel.title || "tui-grid").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "tui-grid";
        link.href = url;
        link.download = `${title}.csv`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        setStatus(`已导出 ${rows.length} 行`);
    }

    async function refreshCurrent() {
        if (state.lastAction) {
            await runAction(state.lastAction, null);
        } else if (state.screen?.screen?.key) {
            await loadScreen(state.screen.screen.key);
        } else {
            await bootstrap();
        }
    }

    function focusModules() {
        setRailCollapsed(false);
        const active = els.moduleTree.querySelector(".tui-screen-button.is-active") || els.moduleTree.querySelector(".tui-screen-button");
        if (active) {
            revealModuleScreen(active);
            active.focus();
            setStatus("模块导航");
        }
    }

    function focusActions() {
        const grid = els.main.closest(".tui-workspace-grid");
        if (grid?.classList.contains("is-dashboard")) {
            grid.classList.remove("is-dashboard");
            setWorkspaceViewKind("idle");
        }
        const actionFilter = els.actions.querySelector("[data-action-filter]");
        if (actionFilter) {
            actionFilter.focus();
            actionFilter.select();
            setStatus("任务区");
            return;
        }
        const firstAction = els.actions.querySelector(".tui-action-button");
        if (firstAction) {
            firstAction.focus();
            setStatus("任务区");
        }
    }

    function focusInspector() {
        setInspectorCollapsed(false);
        const target = els.inspector.querySelector("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])") || els.inspectorShell;
        if (target) {
            target.focus();
            setStatus("说明栏");
        }
    }

    function setRailCollapsed(collapsed) {
        state.railCollapsed = Boolean(collapsed);
        els.app?.classList.toggle("is-rail-collapsed", state.railCollapsed);
        if (els.moduleTree) {
            els.moduleTree.hidden = state.railCollapsed;
            els.moduleTree.inert = state.railCollapsed;
            els.moduleTree.setAttribute("aria-hidden", String(state.railCollapsed));
        }
        if (els.railToggle) {
            els.railToggle.setAttribute("aria-expanded", String(!state.railCollapsed));
            els.railToggle.setAttribute("aria-label", state.railCollapsed ? "展开模块导航" : "收起模块导航");
            els.railToggle.textContent = state.railCollapsed ? "►" : "◄";
        }
        if (state.railCollapsed && els.railPanel?.contains(document.activeElement)) {
            els.main.querySelector(".tui-datagrid")?.focus();
        }
    }

    function toggleRail() {
        setRailCollapsed(!state.railCollapsed);
        if (!state.railCollapsed) {
            focusModules();
        } else {
            setStatus("模块导航已收起");
        }
    }

    function setInspectorCollapsed(collapsed) {
        state.inspectorCollapsed = Boolean(collapsed);
        els.app?.classList.toggle("is-inspector-collapsed", state.inspectorCollapsed);
        if (els.inspectorToggle) {
            els.inspectorToggle.setAttribute("aria-expanded", String(!state.inspectorCollapsed));
            els.inspectorToggle.setAttribute("aria-label", state.inspectorCollapsed ? "展开说明栏" : "收起说明栏");
            els.inspectorToggle.textContent = state.inspectorCollapsed ? "◄" : "►";
        }
        if (state.inspectorCollapsed && els.inspectorShell?.contains(document.activeElement)) {
            els.main.querySelector(".tui-datagrid")?.focus();
        }
    }

    function toggleInspector() {
        setInspectorCollapsed(!state.inspectorCollapsed);
        if (!state.inspectorCollapsed) {
            focusInspector();
        } else {
            setStatus("说明栏已收起");
        }
    }

    function widthFromInspectorResizePointer(event) {
        const grid = inspectorGrid();
        if (!grid) {
            return null;
        }
        const rect = grid.getBoundingClientRect();
        return rect.right - event.clientX;
    }

    function beginInspectorResize(event) {
        if (state.inspectorCollapsed || event.button !== 0 || !inspectorWidthBounds()) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        els.app?.classList.add("is-inspector-resizing");
        els.inspectorResizeHandle?.setPointerCapture?.(event.pointerId);
        applyInspectorWidth(widthFromInspectorResizePointer(event));

        const onPointerMove = (moveEvent) => {
            moveEvent.preventDefault();
            applyInspectorWidth(widthFromInspectorResizePointer(moveEvent));
        };
        const onPointerUp = (upEvent) => {
            upEvent.preventDefault();
            els.app?.classList.remove("is-inspector-resizing");
            els.inspectorResizeHandle?.releasePointerCapture?.(event.pointerId);
            els.inspectorResizeHandle?.removeEventListener("pointermove", onPointerMove);
            els.inspectorResizeHandle?.removeEventListener("pointerup", onPointerUp);
            els.inspectorResizeHandle?.removeEventListener("pointercancel", onPointerUp);
            applyInspectorWidth(state.inspectorWidth, { persist: true });
            setStatus(`说明栏宽度 ${state.inspectorWidth}px`);
        };

        els.inspectorResizeHandle?.addEventListener("pointermove", onPointerMove);
        els.inspectorResizeHandle?.addEventListener("pointerup", onPointerUp);
        els.inspectorResizeHandle?.addEventListener("pointercancel", onPointerUp);
    }

    function resizeInspectorByKeyboard(event) {
        if (state.inspectorCollapsed) {
            return;
        }
        const bounds = inspectorWidthBounds();
        if (!bounds) {
            return;
        }
        const currentWidth = state.inspectorWidth || els.inspectorShell?.getBoundingClientRect().width || bounds.min;
        let nextWidth = null;
        if (event.key === "ArrowLeft") {
            nextWidth = currentWidth + (event.shiftKey ? 48 : 16);
        } else if (event.key === "ArrowRight") {
            nextWidth = currentWidth - (event.shiftKey ? 48 : 16);
        } else if (event.key === "Home") {
            nextWidth = bounds.min;
        } else if (event.key === "End") {
            nextWidth = bounds.max;
        }
        if (nextWidth === null) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        const appliedWidth = applyInspectorWidth(nextWidth, { persist: true });
        if (appliedWidth) {
            setStatus(`说明栏宽度 ${appliedWidth}px`);
        }
    }

    function focusActionFilter() {
        const input = els.actions.querySelector("[data-action-filter]");
        if (input) {
            input.focus();
            input.select();
            setStatus("筛选当前任务");
        }
    }

    function loadAdjacentScreen(delta) {
        const buttons = Array.from(els.moduleTree.querySelectorAll("[data-screen-key]"));
        if (!buttons.length) {
            return;
        }
        const currentIndex = Math.max(0, buttons.findIndex((button) => button.classList.contains("is-active")));
        const nextIndex = (currentIndex + delta + buttons.length) % buttons.length;
        loadScreen(buttons[nextIndex].dataset.screenKey);
    }

    function loadWorkflowStep(direction) {
        if (isOperatorHomeScreen(state.screen?.screen?.key)) {
            const actionKey = runtimeConfig.host?.laneActionKeys?.[state.preferredHomeLane];
            if (actionKey) {
                executeHomeAction(actionKey);
            }
            return;
        }
        const workflow = state.screen?.screen?.workflow || {};
        const target = direction < 0 ? workflow.previous : workflow.next;
        if (target && target.key) {
            loadScreen(target.key);
            return;
        }
        loadAdjacentScreen(direction);
    }

    function runFirstAction() {
        const firstAction = els.actions.querySelector("[data-action-ui-key]");
        if (firstAction) {
            runAction(actionRefFromForm(firstAction), firstAction);
        } else {
            setStatus("没有可执行任务");
        }
    }

    function primaryTaskActions() {
        const actions = (state.screen && state.screen.actions) || [];
        return actions
            .map((action, index) => ({ action, index }))
            .filter((item) => actionTier(item.action) === "primary")
            .sort((left, right) => {
                const sequenceDelta = Number(left.action.sequence || 999) - Number(right.action.sequence || 999);
                return sequenceDelta || left.index - right.index;
            })
            .map((item) => item.action);
    }

    function nextPrimaryAction() {
        const primaryActions = primaryTaskActions();
        if (!primaryActions.length) {
            return null;
        }
        return primaryActions.find((action) => !isActionCompleted(action.key)) || null;
    }

    function screenCompletedSet(screenKey = state.screen?.screen?.key) {
        const key = screenKey || "";
        if (!key) {
            return new Set();
        }
        if (!state.completedActionsByScreen[key]) {
            state.completedActionsByScreen[key] = new Set();
        }
        return state.completedActionsByScreen[key];
    }

    function isActionCompleted(actionKey) {
        return screenCompletedSet().has(actionKey);
    }

    function markActionCompleted(action) {
        if (!action || actionTier(action) !== "primary") {
            return;
        }
        screenCompletedSet(action.screen_key).add(action.key);
        persistProgress();
    }

    function screenProgress(actions = (state.screen && state.screen.actions) || []) {
        const primaryActions = actions.filter((action) => actionTier(action) === "primary");
        const completed = primaryActions.filter((action) => isActionCompleted(action.key)).length;
        return { completed, total: primaryActions.length };
    }

    function resetCurrentScreenProgress() {
        const screenKey = state.screen?.screen?.key;
        if (!screenKey) {
            setStatus("没有可重置的工作区");
            return;
        }
        state.completedActionsByScreen[screenKey] = new Set();
        persistProgress();
        if (!isImmersiveDashboardScreen(state.screen?.screen)) {
            renderActions(state.screen.actions || [], state.screen.screen);
        }
        if (state.currentViewModel) {
            renderViewModel(state.currentViewModel);
        }
        setStatus("本屏进度已重置");
    }

    function runNextPrimaryAction() {
        if (isOperatorHomeScreen(state.screen?.screen?.key)) {
            const actionKey = runtimeConfig.host?.laneActionKeys?.[state.preferredHomeLane];
            if (actionKey) {
                executeHomeAction(actionKey);
            }
            return;
        }
        const action = nextPrimaryAction();
        if (!action) {
            setStatus("本屏主流程已完成");
            return;
        }
        const form = els.actions.querySelector(`[data-action-ui-key="${CSS.escape(actionUiKey(action))}"]`);
        const requiredFields = (action.fields || []).filter((field) => field.required && !field.default);
        if (requiredFields.length && form) {
            fillActionFromSelectedRow(form);
            const missing = requiredFields.filter((field) => {
                const element = formFieldElement(form, field.key);
                return !element || (!element.checked && String(element.value || "").trim() === "");
            });
            if (missing.length) {
                form.scrollIntoView({ block: "nearest" });
                form.querySelector("input:not([type='hidden']),select,textarea")?.focus();
                setStatus(`下一项需要参数: ${missing.map((field) => field.label).join(", ")}`);
                return;
            }
        }
        runAction(action.key, form);
    }

    function openMenu(menuName, sourceButton) {
        const items = menuItems[menuName] || [];
        state.activeMenu = menuName;
        els.menuPopover.innerHTML = `
            <div class="tui-menu-title">${escapeHtml(menuName.toUpperCase())}</div>
            ${items.map(([command, label, key]) => `
                <button type="button" data-menu-action="${escapeHtml(command)}">
                    <span>${escapeHtml(label)}</span>
                    <kbd>${escapeHtml(key)}</kbd>
                </button>
            `).join("")}
        `;
        const rect = sourceButton.getBoundingClientRect();
        els.menuPopover.style.left = `${Math.max(4, rect.left)}px`;
        els.menuPopover.style.top = `${rect.bottom + 2}px`;
        els.menuPopover.hidden = false;
        const first = els.menuPopover.querySelector("button");
        if (first) {
            first.focus();
        }
    }

    function closeMenu() {
        state.activeMenu = null;
        if (els.menuPopover) {
            els.menuPopover.hidden = true;
            els.menuPopover.innerHTML = "";
        }
    }

    async function runCommand(command) {
        closeMenu();
        if (command === "refresh") {
            setLastRefresh();
            await refreshCurrent();
        } else if (command === "export") {
            exportGrid();
        } else if (command === "report") {
            setStatus("报表生成已加入队列");
        } else if (command === "layout") {
            loadAdjacentScreen(1);
        } else if (command === "toggle-rail") {
            toggleRail();
        } else if (command === "focus-modules") {
            focusModules();
        } else if (command === "focus-actions") {
            focusActions();
        } else if (command === "previous-workflow") {
            loadWorkflowStep(-1);
        } else if (command === "next-workflow") {
            loadWorkflowStep(1);
        } else if (command === "next-screen") {
            loadAdjacentScreen(1);
        } else if (command === "run-first-action") {
            runFirstAction();
        } else if (command === "run-next-primary") {
            runNextPrimaryAction();
        } else if (command === "filter-actions") {
            focusActionFilter();
        } else if (command === "row-detail") {
            openSelectedRowDetail();
        } else if (command === "filter") {
            showFilterBar();
        } else if (command === "fill-from-row") {
            fillFocusedOrFirstActionFromRow();
        } else if (command === "reset-progress") {
            resetCurrentScreenProgress();
        } else if (command === "toggle-support") {
            state.showSupportTasks = !state.showSupportTasks;
            if (!isImmersiveDashboardScreen(state.screen?.screen)) {
                renderActions(state.screen.actions || [], state.screen.screen);
            }
            setStatus(state.showSupportTasks ? "支撑检查已显示" : "支撑检查已隐藏");
        } else if (command === "toggle-advanced") {
            state.showAdvancedQueries = !state.showAdvancedQueries;
            if (!isImmersiveDashboardScreen(state.screen?.screen)) {
                renderActions(state.screen.actions || [], state.screen.screen);
            }
            setStatus(state.showAdvancedQueries ? "高级查询已显示" : "高级查询已隐藏");
        } else if (command === "toggle-inspector") {
            toggleInspector();
        } else if (command === "raw") {
            toggleRawDrawer();
        } else if (command === "help") {
            showHelp();
        }
    }

    function fillFocusedOrFirstActionFromRow() {
        const focusedForm = document.activeElement?.closest?.("[data-action-ui-key]");
        if (focusedForm && fillActionFromSelectedRow(focusedForm)) {
            return;
        }
        const firstVisibleFieldForm = Array.from(els.actions.querySelectorAll("[data-action-ui-key]"))
            .find((form) => form.querySelector("input:not([type='hidden']),select,textarea"));
        fillActionFromSelectedRow(firstVisibleFieldForm);
    }

    function isEditableTarget(target) {
        return Boolean(target?.closest?.("input, textarea, select, [contenteditable='true']"));
    }

    function isInteractiveTarget(target) {
        return Boolean(target?.closest?.("button, a, input, textarea, select, summary, [role='button'], [role='separator'], [contenteditable='true']"));
    }

    function closeTopLayer() {
        if (!els.modal.hidden) {
            closeModal();
            return true;
        }
        if (!els.filterBar.hidden) {
            hideFilterBar();
            return true;
        }
        if (!els.menuPopover.hidden) {
            closeMenu();
            return true;
        }
        if (!els.rawDrawer.hidden) {
            toggleRawDrawer(false);
            return true;
        }
        return false;
    }

    function keyboardCommandForEvent(event) {
        const key = String(event.key || "");
        const lowerKey = key.toLowerCase();
        if (event.altKey && !event.ctrlKey && !event.shiftKey && lowerKey === "t") {
            return "cycle-theme";
        }
        if (event.ctrlKey && !event.altKey && !event.shiftKey && lowerKey === "t") {
            return "theme-status";
        }
        if (!event.altKey && !event.ctrlKey && !event.metaKey && HOTKEY_COMMANDS[key]) {
            return HOTKEY_COMMANDS[key];
        }
        if (event.ctrlKey && !event.altKey && !event.metaKey && key === "Enter") {
            return "run-next-primary";
        }
        return "";
    }

    function handleGlobalShortcut(event) {
        if (event.isComposing || event.metaKey) {
            return false;
        }
        const command = keyboardCommandForEvent(event);
        if (!command) {
            return false;
        }
        event.preventDefault();
        event.stopPropagation();
        if (command === "cycle-theme") {
            cycleTheme();
        } else if (command === "theme-status") {
            showThemeStatus();
        } else {
            runCommand(command);
        }
        return true;
    }

    function bindControls() {
        const applyFilterDebounced = typeof runtimeCore.debounce === "function"
            ? runtimeCore.debounce(() => applyFilter(true), 120)
            : () => applyFilter(true);
        els.actions?.addEventListener("submit", (event) => {
            const form = event.target?.closest?.("[data-action-ui-key]");
            if (!form) {
                return;
            }
            event.preventDefault();
            triggerActionForm(form);
        });
        els.actions?.addEventListener("click", (event) => {
            const fillButton = event.target?.closest?.("[data-fill-from-row]");
            if (fillButton) {
                event.preventDefault();
                fillActionFromSelectedRow(fillButton.closest("[data-action-ui-key]"));
                return;
            }
            const actionButton = event.target?.closest?.(".tui-action-button");
            if (!actionButton) {
                return;
            }
            const form = actionButton.closest("[data-action-ui-key]");
            if (!form) {
                return;
            }
            event.preventDefault();
            triggerActionForm(form);
        });
        els.main?.addEventListener("click", (event) => {
            const imagePreview = event.target?.closest?.("[data-image-preview]");
            if (!imagePreview) {
                return;
            }
            event.preventDefault();
            showImagePreview(imagePreview);
        });
        els.currentLocation?.addEventListener("focus", () => {
            els.currentLocation.select();
        });
        els.currentLocation?.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                submitLocationInput();
            } else if (event.key === "Escape") {
                event.preventDefault();
                resetLocationInput();
                els.currentLocation.blur();
            }
        });
        els.rawToggle.addEventListener("click", () => toggleRawDrawer());
        els.rawClose.addEventListener("click", () => toggleRawDrawer(false));
        els.modalClose.addEventListener("click", closeModal);
        els.filterInput.addEventListener("input", () => {
            state.filterText = els.filterInput.value;
            applyFilterDebounced();
        });
        els.filterInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                hideFilterBar();
                els.main.querySelector(".tui-datagrid")?.focus();
            }
        });
        els.filterClear.addEventListener("click", clearFilter);
        els.railToggle?.addEventListener("click", toggleRail);
        els.inspectorToggle?.addEventListener("click", toggleInspector);
        els.inspectorResizeHandle?.addEventListener("pointerdown", beginInspectorResize);
        els.inspectorResizeHandle?.addEventListener("keydown", resizeInspectorByKeyboard);
        document.querySelectorAll("[data-menu-command]").forEach((button) => {
            button.addEventListener("click", (event) => {
                event.stopPropagation();
                const name = button.dataset.menuCommand;
                if (state.activeMenu === name && !els.menuPopover.hidden) {
                    closeMenu();
                } else {
                    openMenu(name, button);
                }
            });
        });
        els.menuPopover.addEventListener("click", (event) => {
            const action = event.target.closest("[data-menu-action]");
            if (action) {
                runCommand(action.dataset.menuAction);
            }
        });
        document.addEventListener("click", (event) => {
            if (!els.menuPopover.hidden && !event.target.closest("[data-menu-popover]") && !event.target.closest("[data-menu-command]")) {
                closeMenu();
            }
        });
        document.addEventListener("keydown", (event) => {
            if (handleGlobalShortcut(event)) {
                return;
            }
            if (event.key === "Escape") {
                event.preventDefault();
                closeTopLayer();
            } else if (event.key === "Enter" && !isInteractiveTarget(event.target)) {
                event.preventDefault();
                openSelectedRowDetail();
            } else if (event.key === "ArrowDown" && !isEditableTarget(event.target) && !isInteractiveTarget(event.target)) {
                event.preventDefault();
                moveRow(1);
            } else if (event.key === "ArrowUp" && !isEditableTarget(event.target) && !isInteractiveTarget(event.target)) {
                event.preventDefault();
                moveRow(-1);
            } else if (event.key === "PageDown" && !isEditableTarget(event.target)) {
                event.preventDefault();
                pageDelta(1);
            } else if (event.key === "PageUp" && !isEditableTarget(event.target)) {
                event.preventDefault();
                pageDelta(-1);
            }
        }, { capture: true });
    }

    function updateClock() {
        if (!els.clock) {
            return;
        }
        els.clock.textContent = currentDateTime();
    }

    async function bootstrap() {
        runtimeCore.mark?.("bootstrap-start");
        try {
            els.moduleTree.innerHTML = '<div class="tui-loading">正在加载目录...</div>';
            setStatus("启动中");
            const requestedScreen = shouldResumeOnBoot() && state.lastNonHomeScreen
                ? state.lastNonHomeScreen
                : "";
            const optimizedUrl = bootstrapUrl(requestedScreen);
            if (optimizedUrl) {
                try {
                    const payload = await fetchJson(optimizedUrl);
                    if (payload?.contract === "tui-bootstrap.v1" && payload.catalog && payload.screen) {
                        renderCatalog(payload.catalog);
                        clearResumeOnBootFlag();
                        if (isOperatorHomeScreen(payload.screen?.screen?.key)) {
                            state.operatorHomePayload = null;
                            state.operatorHomePromise = null;
                        }
                        renderScreen(payload.screen);
                        refreshGovernanceBadges();
                        if (requestedScreen && payload.resolved_screen !== requestedScreen) {
                            setStatus("上次工作区已不可用，已返回首页");
                        }
                        runtimeCore.mark?.("p0-ready");
                        runtimeCore.measure?.("bootstrap-to-p0", "bootstrap-start", "p0-ready");
                        return;
                    }
                } catch (optimizedError) {
                    if (![0, 404, 405].includes(Number(optimizedError?.status || 0))) {
                        throw optimizedError;
                    }
                }
            }
            const catalog = await fetchJson(catalogUrl());
            renderCatalog(catalog);
            const isResumeAttempt = Boolean(shouldResumeOnBoot() && state.lastNonHomeScreen);
            const initialScreen = isResumeAttempt
                ? state.lastNonHomeScreen
                : catalog.default_screen;
            clearResumeOnBootFlag();
            const loaded = await loadScreen(initialScreen);
            if (!loaded && isResumeAttempt) {
                setStatus("上次工作区已不可用，已返回首页");
                await loadScreen(catalog.default_screen);
            }
            runtimeCore.mark?.("p0-ready");
            runtimeCore.measure?.("bootstrap-to-p0", "bootstrap-start", "p0-ready");
        } catch (error) {
            els.moduleTree.innerHTML = '<div class="tui-error">导航暂时不可用</div>';
            renderBoundedApplicationError(error);
        }
    }

    loadStoredProgress();
    loadStoredOperatorState();
    applyTheme(loadStoredTheme(), { silent: true });
    loadStoredInspectorWidth();
    bindControls();
    updateClock();
    window.setInterval(updateClock, 1000);
    bootstrap();
})();
