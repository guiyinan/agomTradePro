    function renderDashboardRowActions(panel, row) {
        const descriptors = Array.isArray(panel?.row_actions) ? panel.row_actions : [];
        const buttons = descriptors.filter((descriptor) => {
            const rule = descriptor.visible_when;
            if (!rule) return true;
            const value = row?.[`__raw_${rule.field}`] ?? row?.[rule.field];
            const matches = rule.values.some(item => String(item) === String(value));
            return rule.negate ? !matches : matches;
        }).map((descriptor) => {
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
                    data-row-action-row="${escapeHtml(JSON.stringify(row))}"
                    aria-label="${escapeHtml(label)}"
                    title="${escapeHtml(label)}"
                >${escapeHtml(action?.label || "操作")}</button>
            `;
        });
        return `<div class="tui-row-actions">${buttons[0] || ""}${buttons.length > 1
            ? `<details class="tui-row-action-menu"><summary aria-label="更多行操作">更多</summary><div>${buttons.slice(1).join("")}</div></details>`
            : ""}</div>`;
    }

    function interpolateRowActionLabel(template, row) {
        return String(template || "操作").replace(/\{([^{}]+)\}/g, (_match, key) => String(row?.[key] ?? "-"));
    }

    function dashboardRowActionNeedsForm(action) {
        // Public action metadata omits HTTP methods; visible body inputs are
        // the user-facing contract for opening an editor before execution.
        // Path/query identity fields are already supplied by the row action.
        // Only an explicit visible body field means the user has extra input
        // to review or change before the mutation is sent.
        return (action?.fields || []).some(
            (field) =>
                field.input_type !== "hidden" &&
                String(field.binding || "body").trim().toLowerCase() === "body",
        );
    }

    function fillDashboardRowActionForm(form, action, row, params) {
        let filled = 0;
        (action?.fields || []).forEach((field) => {
            const element = formFieldElement(form, field.key);
            if (!element || field.input_type === "password") {
                return;
            }
            const previousValue = element.type === "checkbox"
                ? Boolean(element.checked)
                : String(element.value ?? "");
            let value = Object.prototype.hasOwnProperty.call(params, field.key)
                ? params[field.key]
                : rowValueForField(row, field, action);
            if (value === undefined || value === null) {
                return;
            }
            if (typeof value === "object") {
                value = JSON.stringify(value, null, 2);
            }
            if (element.type === "checkbox") {
                element.checked = Boolean(value);
            } else {
                element.value = String(value);
            }
            const currentValue = element.type === "checkbox"
                ? Boolean(element.checked)
                : String(element.value ?? "");
            if (previousValue !== currentValue) {
                element.dispatchEvent(new Event("input", { bubbles: true }));
                element.dispatchEvent(new Event("change", { bubbles: true }));
            }
            filled += 1;
        });
        return filled;
    }

    function dashboardRowActionNeedsPersistentLookupForm(action) {
        const fields = Array.isArray(action?.fields) ? action.fields : [];
        const hasLiveOptions = fields.some(
            (field) => typeof field.options_lookup === "string" && field.options_lookup.trim(),
        );
        const hasRequiredPathScope = fields.some(
            (field) => field.required === true
                && String(field.binding || "body").trim().toLowerCase() === "path",
        );
        return hasLiveOptions && hasRequiredPathScope;
    }

    function openDashboardRowActionForm(action, panel, descriptor, row, params) {
        let form;
        if (
            hasDashboardPanels(state.screen?.screen)
            && !dashboardRowActionNeedsPersistentLookupForm(action)
        ) {
            showModal(action.label || "编辑配置", renderActionForm(action));
            bindRenderedActionForms(els.modalBody);
            form = els.modalBody.querySelector("form[data-action-ui-key]");
        } else {
            form = revealActionFormInPanel(action);
        }
        if (!form) {
            setStatus(`请先打开“${action?.label || "编辑任务"}”表单`);
            return true;
        }
        state.selectedRowContext = rowContextWithSource(row);
        form.dataset.dashboardPanelKey = panel.key || "";
        form.dataset.dashboardResultPanelKey = descriptor.result_panel_key || "";
        form.dataset.dashboardRefreshPanelKey = descriptor.refresh_panel_key || "";
        form.hidden = false;
        form.closest("details")?.setAttribute("open", "");
        form.closest(".tui-action-group")?.removeAttribute("hidden");
        const filled = fillDashboardRowActionForm(form, action, row, params);
        form.scrollIntoView({ block: "nearest" });
        form.querySelector("input:not([type='hidden']),select,textarea")?.focus();
        setStatus(
            filled
                ? `已从当前行填充 ${filled} 项，请修改后提交`
                : `请填写“${action?.label || "编辑任务"}”后提交`,
        );
        return true;
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
                try {
                    const action = currentAction(button.dataset.rowActionKey);
                    const descriptor = (panel.row_actions || []).find(
                        (item) => item.action_key === button.dataset.rowActionKey,
                    ) || {};
                    if (isDashboardSelectorPanel(panel)) {
                        const panelContainer = button.closest("[data-dashboard-panel]");
                        const signatureParams = typeof dashboardTargetParams === "function"
                            ? dashboardTargetParams(action, params)
                            : params;
                        const signature = selectionParamsSignature(signatureParams);
                        if (panelContainer?.dataset.selectedScopeSignature
                            && panelContainer.dataset.selectedScopeSignature !== signature) {
                            clearDashboardTargetResults(panel);
                        }
                        if (panelContainer) {
                            panelContainer.dataset.selectedScopeSignature = signature;
                        }
                    }
                    if (!els.main.querySelector('[data-dashboard-panel]')) {
                        await loadScreen(state.screen.screen.key, { skipCapture: true, skipRestoreAction: true, suppressAutoAction: true });
                    }
                    if (dashboardRowActionNeedsForm(action)) {
                        const row = JSON.parse(button.dataset.rowActionRow || "{}");
                        openDashboardRowActionForm(action, panel, descriptor, row, params);
                        return;
                    }
                    button.disabled = true;
                    const method = String(action?.method || "GET").trim().toUpperCase();
                    const refreshesDashboard = !["GET", "HEAD", "OPTIONS"].includes(method);
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
