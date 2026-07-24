    function renderDashboardHome(screenSpec) {
        const screen = screenSpec.screen;
        const panels = screen.dashboard_panels || [];
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
            window.requestIdleCallback(loadDeferredPanels, { timeout: dashboardIdleTimeoutMs });
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
            const action = currentAction(normalizedActionKey);
            if (action && String(action.effect || "read") !== "read") {
                focusActions();
                const form = actionFormElement(action);
                form?.scrollIntoView({ block: "nearest" });
                const primaryInput = form?.querySelector(
                    "textarea, input:not([type='hidden']), select",
                );
                (primaryInput || form?.querySelector("button"))?.focus();
                setStatus(`请填写“${action.label}”后继续`);
                return;
            }
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
            .map((row) => {
                const completedRow = expandToTwelve
                    ? expandDashboardRow(row)
                    : completeDashboardRow(row, columns);
                return `"${completedRow.join(" ")}"`;
            })
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

    function completeDashboardRow(row, columns) {
        const completed = [...row];
        const fallback = completed.at(-1) || "panel_1";
        while (completed.length < columns) {
            completed.push(fallback);
        }
        return completed;
    }

    function dashboardActionCanAutoRun(action) {
        if (!action) {
            return false;
        }
        const method = String(action.method || "GET").trim().toUpperCase();
        const risk = String(action.risk || "read").trim().toLowerCase();
        const screen = state.screen?.screen || {};
        const sameAdminScreen = String(screen.audience || "") === "admin"
            && String(action.screen_key || "") === String(screen.key || "");
        return ["GET", "HEAD", "OPTIONS"].includes(method)
            && (risk === "read" || (risk === "admin" && sameAdminScreen))
            && unresolvedRequiredFields(action).length === 0;
    }

    async function loadDashboardPanel(panel) {
        const container = els.main.querySelector(`[data-dashboard-panel="${CSS.escape(panel.key)}"]`);
        if (!container) {
            return;
        }
        if (!panel.action_key) {
            container.innerHTML = renderDashboardPanelShell(
                panel,
                renderPanelPlaceholder(panel, panel.empty_message || "等待发布数据源。"),
            );
            bindDashboardPanelOpenControls(container);
            return;
        }
        const operatorSectionKey = isOperatorHomeScreen(state.screen?.screen?.key)
            ? operatorHomePanelSectionKey(panel)
            : "";
        const panelAction = currentAction(panel.action_key);
        if (!operatorSectionKey && !dashboardActionCanAutoRun(panelAction)) {
            container.innerHTML = renderDashboardPanelShell(
                panel,
                renderDashboardActionPrompt(panel, panelAction),
            );
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

    function renderDashboardActionPrompt(panel, action) {
        if (!action) {
            return renderPanelPlaceholder(panel, panel.empty_message || "当前任务暂不可用。");
        }
        const label = String(action.submit_label || action.label || "继续").trim();
        return `
            <div class="tui-dashboard-action-prompt">
                <p>${escapeHtml(panel.note || action.description || "填写必要信息后继续。")}</p>
                <button
                    type="button"
                    class="tui-entry-action"
                    data-dashboard-open
                    data-dashboard-target="${escapeHtml(dashboardTargetScreen(panel))}"
                    data-dashboard-action="${escapeHtml(action.key)}"
                >${escapeHtml(label)}</button>
            </div>
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
            return renderPanelPlaceholder(panel, panel.empty_message || "暂无可显示数据。");
        }
        if (viewModel.stale && panel.stale_message) {
            return renderPanelPlaceholder(panel, panel.stale_message);
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
        if (typeof runtimeCore.dashboardDesktopColumns === "function") {
            return runtimeCore.dashboardDesktopColumns(screen, runtimeConfig.host || {});
        }
        throw new Error("AgomTUI Runtime core is missing dashboardDesktopColumns");
    }

    function regimeMarkerSpec(regime) {
        const normalized = String(regime || "").trim().toLowerCase();
        const positions = [
            { aliases: ["recovery", "复苏"], left: "25%", top: "25%", label: "复苏象限" },
            { aliases: ["overheat", "过热"], left: "75%", top: "25%", label: "过热象限" },
            { aliases: ["deflation", "recession", "通缩", "衰退"], left: "25%", top: "75%", label: "通缩象限" },
            { aliases: ["stagflation", "滞胀"], left: "75%", top: "75%", label: "滞胀象限" },
        ];
        return positions.find((item) => item.aliases.some((alias) => normalized.includes(alias))) || null;
    }

    function renderRegimePanel(viewModel) {
        const fields = fieldsToMap(viewModel.fields || []);
        const regime = pickField(fields, ["current_regime", "dominant_regime", "regime", "regime_name", "state", "name"]) || "UNKNOWN";
        const confidence = formatConfidence(
            pickField(fields, ["confidence", "regime_confidence", "confidence_pct"]),
        );
        const trend = pickField(fields, ["trend", "movement", "transition_target", "status"]) || "-";
        const warning = pickField(fields, ["warning", "transition_warning", "risk", "alerts"]) || "-";
        const marker = regimeMarkerSpec(regime);
        return `
            <div class="tui-quadrant">
                <div class="q q-recovery">复苏<br><strong>RECOVERY</strong></div>
                <div class="q q-overheat">过热<br><strong>OVERHEAT</strong></div>
                <div class="q q-recession">衰退<br><strong>RECESSION</strong></div>
                <div class="q q-stagflation">滞胀<br><strong>STAGFLATION</strong></div>
                <div class="q-axis-x"></div>
                <div class="q-axis-y"></div>
                ${marker ? `<div class="q-marker" style="left:${marker.left};top:${marker.top}" role="img" aria-label="${escapeHtml(marker.label)}">◆</div>` : ""}
            </div>
            <div class="tui-dash-lines">
                <div>当前判断: <strong class="tui-green">${escapeHtml(regime)}</strong></div>
                <div>置信度: <strong>${escapeHtml(confidence)}</strong>　趋势: <strong class="tui-green">${escapeHtml(trend)}</strong></div>
                <div>拐点预警: ${escapeHtml(warning)}</div>
            </div>
        `;
    }

    function formatConfidence(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) {
            return displayValue(value);
        }
        const percentage = Math.abs(number) <= 1 ? number * 100 : number;
        return `${percentage.toFixed(1).replace(/\.0$/, "")}%`;
    }

    function renderPanelDataGrid(panel, viewModel) {
        const rows = (viewModel.rows || []).slice(0, Number(panel.max_rows || 8));
        const panelColumns = Array.isArray(panel.columns) ? panel.columns : [];
        const preferredColumns = panelColumns.filter((column) => rows.some((row) => Object.prototype.hasOwnProperty.call(row, column.key)));
        const sourceColumns = preferredColumns.length ? preferredColumns : (viewModel.columns || []);
        const columns = sourceColumns.filter((column) => rows.some((row) => Object.prototype.hasOwnProperty.call(row, column.key))).slice(0, 6);
        if (!rows.length || !columns.length) {
            return renderPanelPlaceholder(panel, panel.empty_message || "暂无表格数据。");
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
                            ${columns.map((column) => {
                                const value = displayValue(row[column.key]);
                                return `<td class="${cellClass(value, column.label || column.key)}">${escapeHtml(value)}</td>`;
                            }).join("")}
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
                    const descriptor = (panel.row_actions || []).find(
                        (item) => item.action_key === button.dataset.rowActionKey,
                    ) || {};
                    const resultPanelKey = String(descriptor.result_panel_key || "").trim();
                    const refreshPanelKey = String(descriptor.refresh_panel_key || "").trim();
                    if (resultPanelKey || refreshPanelKey) {
                        await runAction(button.dataset.rowActionKey, null, {
                            params,
                            dashboardResultPanelKey: resultPanelKey,
                            dashboardRefreshPanelKey: refreshPanelKey,
                        });
                        return;
                    }
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
        const fields = applyPanelFieldRules(viewModel.fields || [], panel)
            .slice(0, Number(panel.max_rows || 8));
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
        const fields = applyPanelFieldRules(viewModel.fields || [], options.panel)
            .slice(0, Number(options.panel?.max_rows || 12));
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
        const secretFields = fields.filter(
            (field) => fieldPresentation(field) === "secret" && hasDisplayValue(field.value),
        );
        const copyFields = fields.filter(
            (field) => fieldPresentation(field) === "copyable" && hasDisplayValue(field.value),
        );
        const multilineFields = fields.filter(
            (field) => fieldPresentation(field) === "multiline" && hasDisplayValue(field.value),
        );
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

    function hasDisplayValue(value) {
        return value !== null
            && value !== undefined
            && String(value).trim() !== ""
            && String(value).trim() !== "-";
    }

    function applyPanelFieldRules(fields, panel) {
        const rules = Array.isArray(panel?.field_rules) ? panel.field_rules : [];
        const byLabel = new Map(
            rules.map((rule) => [String(rule?.label || "").trim(), rule]),
        );
        return (fields || []).flatMap((field) => {
            const rule = byLabel.get(String(field?.label || "").trim());
            if (rule?.visible === false) {
                return [];
            }
            return [{
                ...field,
                value: formatPanelFieldValue(field?.value, rule?.format),
            }];
        });
    }

    function formatPanelFieldValue(value, format) {
        const normalizedFormat = String(format || "text").trim();
        if (normalizedFormat === "money") {
            const number = Number(value);
            return Number.isFinite(number)
                ? `${number.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 元`
                : displayValue(value);
        }
        if (normalizedFormat === "percentage") {
            return formatConfidence(value);
        }
        if (normalizedFormat === "datetime") {
            const timestamp = Date.parse(String(value || ""));
            return Number.isFinite(timestamp)
                ? new Date(timestamp).toLocaleString("zh-CN", { hour12: false })
                : displayValue(value);
        }
        return displayValue(value);
    }

    function renderSemanticGridFields(fields) {
        if (!fields.length) {
            return "";
        }
        return `
            <dl class="tui-detail-grid">
                ${fields.map((field) => `
                    <dt>${escapeHtml(field.label)}</dt>
                    <dd>${escapeHtml(displayValue(field.value))}</dd>
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
                                    data-secret-visible="false"
                                    data-secret-label="${escapeHtml(field.label)}"
                                    aria-label="显示${escapeHtml(field.label)}"
                                >显示</button>
                                <button
                                    class="tui-copy-action"
                                    type="button"
                                    data-copy-value="${escapeHtml(field.value)}"
                                    data-copy-label="${escapeHtml(field.label)}"
                                >复制</button>
                            </span>
                        </div>
                        <code data-secret-value="${escapeHtml(field.value)}">••••••••••••</code>
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
                const label = String(button.dataset.secretLabel || "凭证");
                button.dataset.secretVisible = visible ? "false" : "true";
                button.textContent = visible ? "显示" : "隐藏";
                button.setAttribute("aria-label", `${visible ? "显示" : "隐藏"}${label}`);
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
        if (/^-\d+(?:\.\d+)?%?$/.test(text.trim()) || text.includes("暂停") || text.includes("触发") || text.includes("失败") || text.includes("未运行")) {
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
