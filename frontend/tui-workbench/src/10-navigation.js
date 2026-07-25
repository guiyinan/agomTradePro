    function renderCatalog(catalog) {
        state.catalog = catalog;
        const groups = catalog.groups || [];
        let screenIndex = 0;
        const previousFocusKey = document.activeElement?.closest?.("[data-screen-key]")?.dataset?.screenKey || "";
        const previousScrollTop = els.moduleTree.scrollTop;
        els.moduleTree.innerHTML = groups.map((group) => `
            <section class="tui-group">
                <div class="tui-group-title">${escapeHtml(group.label)}</div>
                ${(group.modules || []).map((module) => `
                    <div class="tui-tree-module">
                        ${isRedundantModuleTitle(group, module) ? "" : `
                            <div class="tui-tree-module-title">
                                <span>${escapeHtml(module.label)}</span>
                                <div class="tui-tree-module-meta">
                                    <span data-module-badge-screens="${escapeHtml((module.screens || []).map((screen) => screen.key).join(","))}">${badgeMarkup(badgeCountsForScreenKeys((module.screens || []).map((screen) => screen.key)), { compact: true })}</span>
                                    <small>${escapeHtml(module.action_count || 0)}</small>
                                </div>
                            </div>
                        `}
                        ${(module.screens || []).map((screen) => `
                            <div class="tui-screen-row">
                                <button class="tui-screen-button" type="button" data-screen-key="${escapeHtml(screen.key)}">
                                    <span>${++screenIndex} ${escapeHtml(screen.label)}</span>
                                    <small>${escapeHtml(viewLabel(screen.view_type))} / ${escapeHtml(screen.action_count)} 项</small>
                                </button>
                                <div class="tui-screen-tools">
                                    <span data-screen-badge-host="${escapeHtml(screen.key)}">${screenBadgeMarkup(screen.key)}</span>
                                    <button
                                        class="tui-screen-pin${state.pinnedScreenKeys.has(screen.key) ? " is-active" : ""}"
                                        type="button"
                                        data-pin-screen-key="${escapeHtml(screen.key)}"
                                        aria-label="${escapeHtml(`${state.pinnedScreenKeys.has(screen.key) ? "取消收藏工作区" : "收藏工作区"}：${screen.label}`)}"
                                        title="${escapeHtml(`${state.pinnedScreenKeys.has(screen.key) ? "取消收藏工作区" : "收藏工作区"}：${screen.label}`)}"
                                        aria-pressed="${state.pinnedScreenKeys.has(screen.key) ? "true" : "false"}"
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
        bindCatalogBadgeButtons();
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
        els.moduleTree.scrollTop = previousScrollTop;
        if (previousFocusKey) {
            els.moduleTree.querySelector(`[data-screen-key="${CSS.escape(previousFocusKey)}"]`)?.focus();
        }
        if (state.screen?.screen?.key) {
            markActiveScreen(state.screen.screen.key);
        }
    }

    function isRedundantModuleTitle(group, module) {
        const modules = Array.isArray(group?.modules) ? group.modules : [];
        const groupLabel = String(group?.label || "").trim().toLocaleLowerCase();
        const moduleLabel = String(module?.label || "").trim().toLocaleLowerCase();
        return modules.length === 1 && groupLabel !== "" && groupLabel === moduleLabel;
    }

    function bindCatalogBadgeButtons() {
        els.moduleTree.querySelectorAll("[data-badge-screen-key]").forEach((button) => {
            if (button.dataset.badgeBound === "true") {
                return;
            }
            button.dataset.badgeBound = "true";
            button.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                openScreenFromCatalog(button.dataset.badgeScreenKey);
            });
        });
    }

    function refreshCatalogBadges() {
        if (!state.catalog || !els.moduleTree) {
            return;
        }
        els.moduleTree.querySelectorAll("[data-screen-badge-host]").forEach((host) => {
            host.innerHTML = screenBadgeMarkup(host.dataset.screenBadgeHost);
        });
        els.moduleTree.querySelectorAll("[data-module-badge-screens]").forEach((host) => {
            const counts = badgeCountsForScreenKeys(
                String(host.dataset.moduleBadgeScreens || "").split(",").filter(Boolean)
            );
            host.innerHTML = badgeMarkup(counts, { compact: true });
        });
        bindCatalogBadgeButtons();
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
            const containerRect = els.moduleTree.getBoundingClientRect();
            const rect = screenButton.getBoundingClientRect();
            const alreadyVisible = rect.top >= containerRect.top && rect.bottom <= containerRect.bottom;
            if (!alreadyVisible) {
                screenButton.scrollIntoView({ block: "nearest", inline: "nearest" });
            }
        });
    }

    function renderField(action, field) {
        const id = `tui-${action.key}-${field.key}`;
        const rawValue = field.default ?? "";
        const valueType = String(field.value_type || "").toLowerCase();
        const isStructuredValue = ["json", "object", "list"].includes(valueType)
            || (rawValue !== null && typeof rawValue === "object");
        const value = isStructuredValue
            ? (typeof rawValue === "string" ? rawValue : JSON.stringify(rawValue, null, 2))
            : rawValue;
        const required = field.required ? "required" : "";
        if (field.input_type === "hidden") {
            return `<input id="${escapeHtml(id)}" name="${escapeHtml(field.key)}" type="hidden" value="${escapeHtml(value)}">`;
        }
        if (field.input_type === "select") {
            const options = field.options || [];
            const emptyOption = !field.required && value === ""
                ? '<option value=""></option>'
                : "";
            return `
                <label class="tui-field" for="${escapeHtml(id)}">
                    <span>${escapeHtml(field.label)}</span>
                    <select id="${escapeHtml(id)}" name="${escapeHtml(field.key)}" ${required}>
                        ${emptyOption}${options.map((option) => {
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
        if (field.input_type === "textarea" || isStructuredValue) {
            return `
                <label class="tui-field" for="${escapeHtml(id)}">
                    <span>${escapeHtml(field.label)}</span>
                    <textarea id="${escapeHtml(id)}" name="${escapeHtml(field.key)}" rows="${isStructuredValue ? "5" : "3"}" ${required} placeholder="${escapeHtml(field.placeholder || "")}">${escapeHtml(value)}</textarea>
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
        state.lastPager = null;
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
                availableActionKeys: new Set(
                    (state.screen?.actions || []).map((action) => String(action.key || ""))
                ),
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
