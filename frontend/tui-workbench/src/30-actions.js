    function actionTier(action) {
        const tier = String(action.task_tier || "").toLowerCase();
        if (["primary", "support", "advanced", "operation"].includes(tier)) {
            return tier;
        }
        return "support";
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

    function renderActions(actions, screen) {
        if (!actions.length) {
            els.actions.innerHTML = '<div class="tui-empty-state">当前工作区暂无可执行任务。</div>';
            return;
        }
        const primaryActions = actions.filter((action) => actionTier(action) === "primary");
        const supportActions = actions.filter((action) => actionTier(action) === "support");
        const advancedActions = actions.filter((action) => actionTier(action) === "advanced");
        const hasPrimary = primaryActions.length > 0;
        const summary = summarizeActions(actions);
        const progress = screenProgress(actions);
        const groups = groupActions(actions);
        const density = screenActionDensity(screen);
        const visibilityBudget = { remaining: density.primaryOperationLimit };
        els.actions.innerHTML = `
            <div class="tui-action-brief">
                <div>
                    <strong>${escapeHtml((screen && screen.label) || "当前工作区")}</strong>
                    <span data-action-summary>主流程 ${progress.completed}/${progress.total} / 操作 ${summary.operation} / 支撑 ${summary.support} / 高级 ${summary.advanced}</span>
                </div>
                <label class="tui-action-filter">
                    <span>任务</span>
                    <input type="search" value="${escapeHtml(state.actionFilterText)}" placeholder="输入业务词" data-action-filter>
                    <button type="button" data-clear-action-filter ${state.actionFilterText ? "" : "hidden"}>清</button>
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
            ${groups.map((group) => renderActionGroup(group, density, visibilityBudget)).join("")}
            <div class="tui-empty-state" data-action-filter-empty hidden>没有匹配任务。清空筛选后查看全部。</div>
        `;
        els.actions.dataset.renderedScreenKey = (screen && screen.key) || "";
        const actionFilter = els.actions.querySelector("[data-action-filter]");
        const applyActionFilterInput = () => {
            state.actionFilterText = actionFilter ? actionFilter.value : state.actionFilterText;
            refreshRenderedActionPanel(actions, screen);
        };
        actionFilter?.addEventListener("input", (event) => {
            if (event.isComposing) {
                return;
            }
            applyActionFilterInput();
        });
        actionFilter?.addEventListener("compositionend", applyActionFilterInput);
        els.actions.querySelector("[data-clear-action-filter]")?.addEventListener("click", () => {
            state.actionFilterText = "";
            actionFilter.value = "";
            refreshRenderedActionPanel(actions, screen);
            actionFilter.focus();
            setStatus("任务筛选已清除");
        });
        els.actions.querySelector("[data-toggle-support]")?.addEventListener("click", () => {
            state.showSupportTasks = !state.showSupportTasks;
            refreshRenderedActionPanel(actions, screen);
            setStatus(state.showSupportTasks ? "支撑检查已显示" : "支撑检查已隐藏");
        });
        els.actions.querySelector("[data-toggle-advanced]")?.addEventListener("click", () => {
            state.showAdvancedQueries = !state.showAdvancedQueries;
            refreshRenderedActionPanel(actions, screen);
            setStatus(state.showAdvancedQueries ? "高级查询已显示" : "高级查询已隐藏");
        });
        bindRenderedActionForms();
        refreshRenderedActionPanel(actions, screen);
        refreshRowFillButtons();
    }

    function actionVisibleInPanel(action, hasPrimary, filterNeedle) {
        if (filterNeedle) {
            return actionMatchesFilter(action, filterNeedle);
        }
        if (!hasPrimary) {
            return true;
        }
        const tier = actionTier(action);
        if (tier === "operation" || tier === "primary") {
            return true;
        }
        if (tier === "support") {
            return state.showSupportTasks;
        }
        if (tier === "advanced") {
            return state.showAdvancedQueries;
        }
        return false;
    }

    function refreshRenderedActionPanel(actions, screen) {
        const hasPrimary = actions.some((action) => actionTier(action) === "primary");
        const filterNeedle = state.actionFilterText.trim().toLowerCase();
        let visibleCount = 0;
        els.actions.querySelectorAll("[data-action-ui-key]").forEach((form) => {
            const action = currentAction(actionRefFromForm(form));
            const visible = Boolean(action && actionVisibleInPanel(action, hasPrimary, filterNeedle));
            form.hidden = !visible;
            if (visible) {
                visibleCount += 1;
            }
            if (action) {
                const completed = isActionCompleted(action.key);
                form.classList.toggle("is-completed", completed);
                const meta = form.querySelector("[data-action-meta]");
                if (meta) {
                    meta.textContent = actionMetaLabel(action, completed);
                }
            }
        });
        els.actions.querySelectorAll(".tui-action-group").forEach((group) => {
            group.hidden = !group.querySelector("[data-action-ui-key]:not([hidden])");
        });
        const summary = summarizeActions(actions);
        const progress = screenProgress(actions);
        const summaryHost = els.actions.querySelector("[data-action-summary]");
        if (summaryHost) {
            summaryHost.textContent = `主流程 ${progress.completed}/${progress.total} / 操作 ${summary.operation} / 支撑 ${summary.support} / 高级 ${summary.advanced}${filterNeedle ? ` / 匹配 ${visibleCount}` : ""}`;
        }
        const empty = els.actions.querySelector("[data-action-filter-empty]");
        if (empty) {
            empty.hidden = visibleCount > 0;
        }
        const clearButton = els.actions.querySelector("[data-clear-action-filter]");
        if (clearButton) {
            clearButton.hidden = !filterNeedle;
        }
        const supportToggle = els.actions.querySelector("[data-toggle-support]");
        if (supportToggle) {
            supportToggle.textContent = state.showSupportTasks || !hasPrimary ? "隐藏支撑" : "显示支撑";
        }
        const advancedToggle = els.actions.querySelector("[data-toggle-advanced]");
        if (advancedToggle) {
            advancedToggle.textContent = state.showAdvancedQueries || !hasPrimary ? "隐藏高级" : "显示高级";
        }
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

    function screenActionDensity(screen) {
        const density = screen?.action_density || {};
        const primaryOperationLimit = Number(density.primary_operation_limit);
        const taskGroupLimit = Number(density.task_group_limit);
        return {
            primaryOperationLimit: Number.isFinite(primaryOperationLimit) && primaryOperationLimit > 0
                ? primaryOperationLimit
                : Number.POSITIVE_INFINITY,
            taskGroupLimit: Number.isFinite(taskGroupLimit) && taskGroupLimit > 0
                ? taskGroupLimit
                : Number.POSITIVE_INFINITY,
        };
    }

    function renderActionGroup(group, density, visibilityBudget) {
        const direct = [];
        const overflow = [];
        let groupPrimaryOperationCount = 0;
        group.actions.forEach((action) => {
            const tier = actionTier(action);
            const budgeted = tier === "primary" || tier === "operation";
            const withinGroup = groupPrimaryOperationCount < density.taskGroupLimit;
            const withinScreen = visibilityBudget.remaining > 0;
            if (!budgeted || (withinGroup && withinScreen)) {
                direct.push(action);
                if (budgeted) {
                    groupPrimaryOperationCount += 1;
                    visibilityBudget.remaining -= 1;
                }
                return;
            }
            overflow.push(action);
        });
        return `
            <section class="tui-action-group tui-action-group-${escapeHtml(group.tier)}">
                <div class="tui-action-group-title">${escapeHtml(group.label)}</div>
                ${direct.map((action) => renderActionForm(action)).join("")}
                ${overflow.length ? `
                    <details class="tui-action-overflow">
                        <summary>更多任务（${overflow.length}）</summary>
                        ${overflow.map((action) => renderActionForm(action)).join("")}
                    </details>
                ` : ""}
            </section>
        `;
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
                        <span class="tui-action-meta" data-action-meta>${escapeHtml(actionMetaLabel(action, completed))}</span>
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
        return String(action.submit_label || "执行");
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
        return fields.some((field) => rowValueForField(row, field, action) !== undefined);
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
            if (file && Number(file.size) > maxTextFileBytes) {
                reject(new Error("文件超过 2MB，请改用更小的文本文件"));
                return;
            }
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
        const field = typeof fieldOrKey === "object" && fieldOrKey
            ? fieldOrKey
            : ((action && action.fields) || []).find((candidate) => candidate.key === fieldOrKey) || { key: fieldOrKey };
        const fieldKey = field.key;
        const presentation = String(field.presentation_semantic || field.semantic || "").toLowerCase();
        if (field.input_type === "password" || ["api_token", "copyable_secret", "secret"].includes(presentation)) {
            return undefined;
        }
        if (!actionCompatibleWithRowSource(action, row, fieldKey)) {
            return undefined;
        }
        for (const key of rowFieldCandidates(field, action)) {
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

    function focusDeepLinkedAction(screenSpec, actionKey) {
        const normalizedKey = String(actionKey || "").trim();
        if (!normalizedKey) {
            return;
        }
        const action = (screenSpec?.actions || []).find((item) => item.key === normalizedKey);
        if (!action) {
            setStatus("链接中的任务在当前账号下不可用");
            return;
        }
        const dashboardPanel = (screenSpec?.screen?.dashboard_panels || [])
            .find((panel) => panel.action_key === normalizedKey);
        if (dashboardPanel && isImmersiveDashboardScreen(screenSpec?.screen)) {
            const panel = els.main.querySelector(
                `[data-dashboard-panel="${CSS.escape(dashboardPanel.key)}"]`,
            );
            if (!panel) {
                setStatus("链接中的任务暂时无法定位");
                return;
            }
            panel.scrollIntoView({ block: "nearest" });
            (panel.querySelector("button, a, input, select, textarea") || panel).focus?.();
            setStatus(`已定位到 ${action.label}`);
            return;
        }
        const tier = actionTier(action);
        if (tier === "support") {
            state.showSupportTasks = true;
        }
        if (tier === "advanced") {
            state.showAdvancedQueries = true;
        }
        state.actionFilterText = "";
        refreshRenderedActionPanel(screenSpec.actions || [], screenSpec.screen || {});
        const form = els.actions.querySelector(
            `[data-action-ui-key="${CSS.escape(actionUiKey(action))}"]`,
        );
        if (!form) {
            setStatus("链接中的任务暂时无法定位");
            return;
        }
        form.closest("details")?.setAttribute("open", "");
        const deepLinkedParams = actionParamsFromBrowserLocation();
        const runnableParams = {};
        (action.fields || []).forEach((field) => {
            if (!(field.key in deepLinkedParams)) {
                return;
            }
            const element = formFieldElement(form, field.key);
            if (!element || ["file", "password"].includes(field.input_type)) {
                return;
            }
            if (field.input_type === "checkbox") {
                element.checked = ["1", "true", "yes", "on"].includes(
                    String(deepLinkedParams[field.key]).toLowerCase(),
                );
                runnableParams[field.key] = element.checked;
                return;
            }
            element.value = deepLinkedParams[field.key];
            runnableParams[field.key] = deepLinkedParams[field.key];
        });
        const requiredFieldsArePresent = (action.fields || [])
            .filter((field) => field.required)
            .every((field) => Object.prototype.hasOwnProperty.call(runnableParams, field.key));
        const safeRead = ["read", "admin"].includes(
            String(action.risk || "read").toLowerCase(),
        )
            && String(action.method || "GET").toUpperCase() === "GET"
            && !action.confirmation_required;
        if (safeRead && requiredFieldsArePresent) {
            runAction(normalizedKey, null, { params: runnableParams });
            return;
        }
        focusActionFormInPanel(form);
        setStatus(`已定位到 ${action.label}`);
    }

    function focusActionFormInPanel(form) {
        if (!form) {
            return;
        }
        const focus = () => {
            form.scrollIntoView({ block: "nearest", inline: "nearest" });
            const primaryInput = form.querySelector(
                "textarea, input:not([type='hidden']), select",
            );
            (primaryInput || form.querySelector("button"))?.focus({ preventScroll: true });
        };
        focus();
        const schedule = () => {
            focus();
            window.setTimeout(() => {
                form.scrollIntoView({ block: "nearest", inline: "nearest" });
            }, 0);
        };
        if (typeof window.requestAnimationFrame === "function") {
            window.requestAnimationFrame(schedule);
        } else {
            window.setTimeout(schedule, 0);
        }
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
        const registry = fieldAliasRegistry();
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
        const controller = new AbortController();
        const requestId = startPendingRequest(controller);
        try {
            closeMenu();
            closeModal();
            els.main.innerHTML = '<div class="tui-loading">正在加载工作区...</div>';
            setStatus("加载工作区");
            const screenSpec = await fetchJson(screenUrl(screenKey), { signal: controller.signal });
            if (!isLatestRequest(requestId)) {
                return null;
            }
            clearPendingRequest();
            if (isOperatorHomeScreen(screenSpec?.screen?.key)) {
                state.operatorHomePayload = null;
                state.operatorHomePromise = null;
            }
            renderScreen(screenSpec, {
                ...options,
                suppressAutoAction: Boolean(options.deepLinkedActionKey) || options.suppressAutoAction,
            });
            focusDeepLinkedAction(screenSpec, options.deepLinkedActionKey || "");
            if (!options.suppressHistory) {
                syncBrowserScreenLocation(screenSpec?.screen?.key || screenKey, {
                    replace: Boolean(options.replaceHistory),
                    preserveAction: Boolean(options.preserveAction),
                });
            }
            refreshGovernanceBadges();
            return screenSpec;
        } catch (error) {
            if (!isLatestRequest(requestId)) {
                return null;
            }
            if (error?.name === "AbortError") {
                return null;
            }
            clearPendingRequest();
            resetLocationInput();
            renderBoundedApplicationError(error, { retryScreenKey: screenKey });
            return null;
        }
    }

    const QUEUED_TERMINAL_STATUSES = new Set([
        "cancelled",
        "completed",
        "failed",
        "timed_out",
        "orphaned",
    ]);

    function queuedStatusLabel(status) {
        return {
            accepted: "已接受",
            queued: "已排队",
            claimed: "已接收",
            running: "执行中",
            waiting_approval: "等待审批",
            cancel_requested: "正在取消",
            cancelled: "已取消",
            completed: "已完成",
            failed: "执行失败",
            timed_out: "执行超时",
            orphaned: "执行记录待恢复",
        }[String(status || "").trim()] || "状态待确认";
    }

    function queuedViewModelWithSnapshot(viewModel, queuedRun, status, events) {
        const eventTypes = events
            .map((event) => String(event?.event_type || "").trim())
            .filter(Boolean);
        const fields = Array.isArray(viewModel.fields)
            ? viewModel.fields.map((field) => ({ ...field }))
            : [];
        const values = new Map([
            ["run_status", queuedStatusLabel(status)],
            [
                "event_summary",
                eventTypes.length
                    ? eventTypes.slice(-8).join(" → ")
                    : "等待服务器端 Worker 返回进度",
            ],
        ]);
        values.forEach((value, key) => {
            const field = fields.find((item) => String(item?.key || "") === key);
            if (field) {
                field.value = value;
            }
        });
        return {
            ...viewModel,
            status: queuedStatusLabel(status),
            fields,
            queued_run: {
                ...queuedRun,
                status,
                event_cursor: events.reduce(
                    (cursor, event) => Math.max(cursor, Number(event?.sequence || 0)),
                    Number(queuedRun.event_cursor || 0),
                ),
                events: events.slice(-20),
            },
            business_summary: `服务器端任务 ${queuedRun.run_id}：${queuedStatusLabel(status)}。`,
        };
    }

    async function consumeQueuedRun(viewModel, requestId) {
        const initial = viewModel?.queued_run;
        if (!initial || !initial.status_url || !initial.events_url) {
            return;
        }
        let queuedRun = { ...initial };
        let events = Array.isArray(initial.events) ? [...initial.events] : [];
        let status = String(initial.status || "queued");
        const maxPolls = 20;
        for (let poll = 0; poll < maxPolls; poll += 1) {
            if (!isLatestRequest(requestId)) {
                return;
            }
            try {
                const cursor = Number(queuedRun.event_cursor || 0);
                const separator = String(queuedRun.events_url).includes("?") ? "&" : "?";
                const eventPage = await fetchJson(
                    `${queuedRun.events_url}${separator}after=${encodeURIComponent(cursor)}`,
                );
                const pageEvents = Array.isArray(eventPage?.events)
                    ? eventPage.events.filter((event) => event && typeof event === "object")
                    : [];
                if (pageEvents.length) {
                    events = [...events, ...pageEvents];
                }
            } catch (_error) {
                // A status snapshot remains useful when event replay is temporarily unavailable.
            }
            try {
                const snapshot = await fetchJson(queuedRun.status_url);
                if (snapshot && typeof snapshot === "object") {
                    if (snapshot.run_id && snapshot.run_id !== queuedRun.run_id) {
                        throw new Error("queued run identity changed");
                    }
                    status = String(snapshot.status || status);
                    queuedRun = {
                        ...queuedRun,
                        status_url: snapshot.status_url || queuedRun.status_url,
                        events_url: snapshot.events_url || queuedRun.events_url,
                        cancel_url: snapshot.cancel_url || queuedRun.cancel_url,
                    };
                }
            } catch (_error) {
                setStatus("服务器端任务状态暂时不可用");
                return;
            }
            const nextViewModel = queuedViewModelWithSnapshot(viewModel, queuedRun, status, events);
            state.currentViewModel = nextViewModel;
            renderViewModel(nextViewModel);
            if (QUEUED_TERMINAL_STATUSES.has(status)) {
                setStatus(`服务器端任务${queuedStatusLabel(status)}`);
                return;
            }
            setStatus(`服务器端任务${queuedStatusLabel(status)}`);
            if (poll < maxPolls - 1) {
                await new Promise((resolve) => setTimeout(resolve, 1000));
            }
        }
        setStatus("服务器端任务仍在运行，可稍后刷新状态");
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
        const controller = new AbortController();
        const requestId = startPendingRequest(controller);
        try {
            const dashboardResultPanelKey = String(options.dashboardResultPanelKey || "").trim();
            const dashboardRefreshPanelKey = String(options.dashboardRefreshPanelKey || "").trim();
            const hasDashboardResultTarget = Boolean(dashboardResultPanelKey);
            const hasDashboardRefreshTarget = Boolean(dashboardRefreshPanelKey);
            const isTargetedDashboardAction = hasDashboardResultTarget || hasDashboardRefreshTarget;
            const params = options.params ? { ...options.params } : (form ? await collectParams(form, action) : {});
            if (!isLatestRequest(requestId)) {
                return;
            }
            if (actualActionKey === "cli.agent_queue" && !params.client_request_id) {
                const suffix = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
                    ? crypto.randomUUID()
                    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
                params.client_request_id = `request-tui-${suffix}`;
            }
            state.lastAction = actualActionKey;
            state.lastParams = params;
            state.selectedRowIndex = 0;
            setCurrentLocation(action);
            closeMenu();
            closeModal();
            if (hasDashboardResultTarget) {
                if (!Object.prototype.hasOwnProperty.call(options, "dashboardResultPanelMarkup")) {
                    options.dashboardResultPanelMarkup = dashboardPanelMarkup(dashboardResultPanelKey);
                }
                renderDashboardActionLoading(dashboardResultPanelKey, action);
            } else if (!options.dashboardPanelKey && !isTargetedDashboardAction) {
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
            if (!isLatestRequest(requestId)) {
                return;
            }
            clearPendingRequest();
            if (Array.isArray(result.missing_fields) && result.missing_fields.length) {
                state.lastRaw = null;
                if (!options.dashboardPanelKey && !isTargetedDashboardAction) {
                    renderViewModel(result.view_model);
                }
                restoreDashboardActionPanel(options);
                showMissingFieldsPrompt(result, actualActionKey, params, options);
                updateRawDrawer();
                setStatus("等待补填");
                return;
            }
            if (result.confirmation_required) {
                state.lastRaw = null;
                if (!options.dashboardPanelKey && !isTargetedDashboardAction) {
                    renderViewModel(result.view_model);
                }
                restoreDashboardActionPanel(options);
                showActionConfirmation(result, actualActionKey, params, options);
                updateRawDrawer();
                setStatus("等待确认");
                return;
            }
            if (result.password_challenge_required) {
                state.lastRaw = null;
                if (!options.dashboardPanelKey && !isTargetedDashboardAction) {
                    renderViewModel(result.view_model);
                }
                restoreDashboardActionPanel(options);
                showPasswordChallenge(result, actualActionKey, params, options);
                updateRawDrawer();
                setStatus("等待验密");
                return;
            }
            markActionCompleted(action);
            state.lastRaw = result.debug?.raw_response ?? null;
            if (isTargetedDashboardAction) {
                if (hasDashboardResultTarget) {
                    renderDashboardActionResult(dashboardResultPanelKey, result.view_model, action);
                }
                if (hasDashboardRefreshTarget && dashboardRefreshPanelKey !== dashboardResultPanelKey) {
                    await refreshDashboardPanel(dashboardRefreshPanelKey);
                }
                updateRawDrawer();
                setStatus(hasDashboardRefreshTarget ? "操作完成，治理工作区已更新" : "详情已在当前页面打开");
                refreshGovernanceBadges();
                return;
            }
            if (options.dashboardPanelKey) {
                updateRawDrawer();
                await refreshCurrentDashboardPanels();
                setStatus("操作完成，列表已刷新");
                refreshGovernanceBadges();
                return;
            }
            if (!isImmersiveDashboardScreen(state.screen?.screen)) {
                refreshRenderedActionPanel(state.screen.actions || [], state.screen.screen);
            }
            renderViewModel(result.view_model);
            renderResultInspector(result, result.view_model);
            const hasQueuedRun = Boolean(result.view_model?.queued_run);
            if (hasQueuedRun) {
                await consumeQueuedRun(result.view_model, requestId);
            }
            updateRawDrawer();
            if (!hasQueuedRun) {
                setStatus("读取完成");
            }
            refreshGovernanceBadges();
        } catch (error) {
            if (!isLatestRequest(requestId)) {
                return;
            }
            if (error?.name === "AbortError") {
                setStatus("请求已取消");
                return;
            }
            clearPendingRequest();
            const dashboardResultPanelKey = String(options.dashboardResultPanelKey || "").trim();
            if (dashboardResultPanelKey) {
                renderDashboardActionError(dashboardResultPanelKey, error);
                return;
            }
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

    function currentDashboardPanel(panelKey) {
        const panels = Array.isArray(state.screen?.screen?.dashboard_panels)
            ? state.screen.screen.dashboard_panels
            : [];
        return panels.find((panel) => panel.key === panelKey) || null;
    }

    async function refreshDashboardPanel(panelKey) {
        const panel = currentDashboardPanel(panelKey);
        if (panel) {
            await loadDashboardPanel(panel);
        }
    }

    function dashboardPanelMarkup(panelKey) {
        const panel = currentDashboardPanel(panelKey);
        const container = panel
            ? els.main.querySelector(`[data-dashboard-panel="${CSS.escape(panel.key)}"]`)
            : null;
        return container?.innerHTML || "";
    }

    function restoreDashboardActionPanel(options = {}) {
        const panelKey = String(options.dashboardResultPanelKey || "").trim();
        if (!panelKey || !Object.prototype.hasOwnProperty.call(options, "dashboardResultPanelMarkup")) {
            return;
        }
        const panel = currentDashboardPanel(panelKey);
        const container = panel
            ? els.main.querySelector(`[data-dashboard-panel="${CSS.escape(panel.key)}"]`)
            : null;
        if (!panel || !container) {
            return;
        }
        container.innerHTML = options.dashboardResultPanelMarkup;
        bindCopyButtons(container);
        bindDashboardRowActions(container, panel);
        bindDashboardPanelOpenControls(container);
        processHostSlot(container);
    }

    function renderDashboardActionLoading(panelKey, action) {
        const panel = currentDashboardPanel(panelKey);
        const container = panel
            ? els.main.querySelector(`[data-dashboard-panel="${CSS.escape(panel.key)}"]`)
            : null;
        if (!panel || !container) {
            return;
        }
        container.innerHTML = renderDashboardPanelShell(
            panel,
            `<div class="tui-loading">正在执行${escapeHtml(action.label || "当前操作")}...</div>`,
        );
    }

    function renderDashboardActionResult(panelKey, viewModel, action) {
        const panel = currentDashboardPanel(panelKey);
        const container = panel
            ? els.main.querySelector(`[data-dashboard-panel="${CSS.escape(panel.key)}"]`)
            : null;
        if (!panel || !container) {
            return;
        }
        const actionSemantics = actionResultSemantics(action.key);
        const resultPanel = {
            ...panel,
            action_key: action.key,
            presentation_semantic: actionSemantics[0] || panel.presentation_semantic,
        };
        container.innerHTML = renderDashboardPanelShell(
            panel,
            renderDashboardPanelBody(resultPanel, viewModel),
        );
        bindCopyButtons(container);
        bindDashboardPanelOpenControls(container);
        bindDashboardRowActions(container, resultPanel);
        processHostSlot(container);
    }

    function renderDashboardActionError(panelKey, error) {
        const panel = currentDashboardPanel(panelKey);
        const container = panel
            ? els.main.querySelector(`[data-dashboard-panel="${CSS.escape(panel.key)}"]`)
            : null;
        if (!panel || !container) {
            renderBoundedApplicationError(error);
            return;
        }
        container.innerHTML = renderDashboardPanelShell(panel, renderDashboardPanelError(panel, error));
        bindDashboardPanelOpenControls(container);
        bindDashboardPanelRecovery(container, panel);
    }
