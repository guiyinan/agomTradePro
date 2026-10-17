/* TUX-09 shared task-focus helpers.  These helpers reuse the existing action, dashboard, pagination, and screen seams; they do not introduce a second transport or navigation state machine. */

    function isDashboardSelectorPanel(panel) {
        return panelPresentationSemantic(panel) === "primary_list";
    }

    function dashboardPanelStatus(error) {
        const status = Number(error?.status || 0);
        return Number.isInteger(status) ? status : 0;
    }

    function isRetryableDashboardPanelError(error) {
        const status = dashboardPanelStatus(error);
        return status === 0 || status >= 500 || error instanceof TypeError;
    }

    function isDashboardAuthorizationError(error) {
        const status = dashboardPanelStatus(error);
        return status === 401 || status === 403;
    }

    function dashboardResultErrorCode(value) {
        const records = [
            value,
            value?.payload,
            value?.response,
            value?.view_model,
            value?.payload?.response,
            value?.payload?.view_model,
        ];
        for (const record of records) {
            const code = String(record?.user_error_code || record?.error_code || "").trim();
            if (code) return code;
        }
        return "";
    }

    function isDashboardScopeInvalid(value) {
        return dashboardResultErrorCode(value) === "TUI_TASK_SCOPE_INVALID";
    }

    function dashboardTargetCanRenderViewModel(status, result) {
        return !isDashboardAuthorizationError({ status })
            && !isDashboardScopeInvalid({ status, payload: result });
    }

    function dashboardTargetNeedsClear(status, result) {
        return Number(status) === 401 || Number(status) === 403 || isDashboardScopeInvalid(result);
    }

    function isDashboardReadAction(action) {
        return Boolean(action && isPassiveRead(action)
            && (!action.effect || action.effect === "read"));
    }

    function dashboardResultStatus(result) {
        const nested = Number(result?.response?.status_code ?? result?.status_code ?? 0);
        if (Number.isInteger(nested) && nested >= 400) {
            return nested;
        }
        const outcome = String(result?.outcome || "").trim().toLowerCase();
        return outcome === "failed" ? 502 : outcome === "blocked" ? 400 : 0;
    }

    function dashboardResultError(result, status) {
        const error = new Error("业务清单读取未完成");
        error.status = status;
        error.payload = result;
        return error;
    }

    function setDashboardPanelPending(container, panel, params, previousPage) {
        container.dataset.dashboardPanelPending = "true";
        container.setAttribute("aria-busy", "true");
        container.querySelector("[data-panel-pending]")?.remove();
        const action = currentAction(panel?.action_key || "");
        const pageKey = action?.pagination?.page_param
            || (action && typeof firstFieldKey === "function"
                ? firstFieldKey(action, ["page", "pageNum", "page_num", "pageNo", "page_no"])
                : "")
            || "page";
        const requestedPage = Number(params?.[pageKey] || params?.page || params?.page_num || params?.pageNo || 1);
        const currentPage = Number(previousPage?.page || 1);
        container.insertAdjacentHTML(
            "afterbegin",
            `<div class="tui-panel-caption" data-panel-pending role="status">正在读取第 ${Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1} 页，当前仍显示第 ${currentPage} 页。</div>`,
        );
        container.querySelectorAll("[data-panel-page-delta], [data-panel-page-size]").forEach((control) => {
            control.dataset.panelPreviousDisabled = String(control.disabled);
            control.disabled = true;
        });
    }

    function clearDashboardPanelPending(container) {
        container.dataset.dashboardPanelPending = "false";
        container.removeAttribute("aria-busy");
        container.querySelector("[data-panel-pending]")?.remove();
        container.querySelectorAll("[data-panel-page-delta], [data-panel-page-size]").forEach((control) => {
            if (control.dataset.panelPreviousDisabled !== undefined) {
                control.disabled = control.dataset.panelPreviousDisabled === "true";
                delete control.dataset.panelPreviousDisabled;
            }
        });
    }

    function renderDashboardPanelPageRetry(container, panel, params, error, previousPage) {
        clearDashboardPanelPending(container);
        container.querySelector("[data-panel-page-retry]")?.remove();
        const action = currentAction(panel?.action_key || "");
        const pageKey = action?.pagination?.page_param
            || (action && typeof firstFieldKey === "function"
                ? firstFieldKey(action, ["page", "pageNum", "page_num", "pageNo", "page_no"])
                : "")
            || "page";
        const requestedPage = Number(params?.[pageKey] || params?.page || params?.page_num || params?.pageNo || 1);
        const retryPage = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
        const status = dashboardPanelStatus(error);
        const message = status >= 500 || status === 0
            ? "本页读取暂时未完成，当前仍保留上一页。"
            : "本页读取未完成，当前仍保留上一页。";
        container.insertAdjacentHTML(
            "afterbegin",
            `<div class="tui-panel-error" data-panel-page-retry role="status"><p>${escapeHtml(message)}</p><button type="button" data-panel-page-retry-button>重试第 ${retryPage} 页</button></div>`,
        );
        container.querySelector("[data-panel-page-retry-button]")?.addEventListener("click", () => {
            loadDashboardPanel(panel, {
                paramsOverride: { ...params },
                preservePrevious: true,
                previousPage,
            });
        });
    }

    function dashboardTargetPanelKeys(panel) {
        return [...new Set((panel?.row_actions || [])
            .flatMap((descriptor) => [descriptor?.result_panel_key, descriptor?.refresh_panel_key])
            .map((key) => String(key || "").trim())
            .filter(Boolean))];
    }

    function clearDashboardTargetResults(panel) {
        clearDashboardPassiveRequestForPanel(panel);
        dashboardTargetPanelKeys(panel).forEach((panelKey) => {
            const targetPanel = currentDashboardPanel(panelKey);
            const targetContainer = targetPanel
                ? els.main.querySelector(`[data-dashboard-panel="${CSS.escape(targetPanel.key)}"]`)
                : null;
            if (!targetPanel) return;
            if (targetContainer?.panelRequestController
                && targetContainer.panelRequestPassiveRead === true) {
                targetContainer.panelRequestController.abort();
            }
            if (state.dashboardFilters) delete state.dashboardFilters[targetPanel.key];
            delete panelPages[targetPanel.key];
            if (!targetContainer) return;
            targetContainer.panelViewModel = null;
            delete targetContainer.dashboardResultRetry;
            delete targetContainer.dashboardResultActionKey;
            delete targetContainer.dashboardResultParams;
            targetContainer.innerHTML = renderDashboardPanelShell(
                targetPanel,
                renderPanelPlaceholder(targetPanel, "已更换选择，请重新读取。"),
            );
            bindDashboardPanelOpenControls(targetContainer);
            bindDashboardFilters(targetContainer);
        });
    }

    function clearDashboardPassiveRequestForPanel(panel) {
        const actionKey = String(state.lastAction || "").trim();
        const relatedActionKeys = new Set(
            (panel?.row_actions || [])
                .map((descriptor) => String(descriptor?.action_key || "").trim())
                .filter(Boolean),
        );
        const activeAction = currentAction(actionKey);
        if (!state.pendingController
            || !actionKey
            || !relatedActionKeys.has(actionKey)
            || typeof isPassiveRead !== "function"
            || !isPassiveRead(activeAction)) {
            return false;
        }
        clearPendingRequest({ abort: true });
        state.latestRequestId = 0;
        return true;
    }

    function clearDashboardSelectorState(panel) {
        state.selectedRowContext = null;
        state.selectedRowIndex = 0;
        const selectorContainer = els.main.querySelector(
            `[data-dashboard-panel="${CSS.escape(panel.key)}"]`,
        );
        if (selectorContainer) {
            delete selectorContainer.dataset.selectedScopeSignature;
            selectorContainer.panelViewModel = null;
            selectorContainer.innerHTML = renderDashboardPanelShell(
                panel,
                renderPanelPlaceholder(panel, "当前选择已失效，请重新选择。"),
            );
            bindDashboardPanelOpenControls(selectorContainer);
            bindDashboardFilters(selectorContainer);
        }
        delete state.dashboardFilters[panel.key];
        delete panelPages[panel.key];
        dashboardTargetPanelKeys(panel).forEach((panelKey) => {
            const targetPanel = currentDashboardPanel(panelKey);
            const targetContainer = targetPanel
                ? els.main.querySelector(`[data-dashboard-panel="${CSS.escape(targetPanel.key)}"]`)
                : null;
            if (targetPanel && targetContainer?.panelRequestController
                && targetContainer.panelRequestPassiveRead === true) {
                targetContainer.panelRequestController.abort();
            }
            if (targetContainer) {
                targetContainer.panelViewModel = null;
                delete targetContainer.dashboardResultRetry;
                delete targetContainer.dashboardResultActionKey;
                delete targetContainer.dashboardResultParams;
                targetContainer.innerHTML = renderDashboardPanelShell(
                    targetPanel,
                    renderPanelPlaceholder(targetPanel, "当前选择已失效，请重新选择。"),
                );
                bindDashboardPanelOpenControls(targetContainer);
                bindDashboardFilters(targetContainer);
            }
            delete panelPages[panelKey];
            delete state.dashboardFilters[panelKey];
        });
        const relatedActions = new Set((panel.row_actions || [])
            .map((descriptor) => String(descriptor?.action_key || "").trim())
            .filter(Boolean));
        if ((relatedActions.has(String(state.lastAction || "")) || state.lastAction === panel.action_key)
            && isPassiveRead(currentAction(state.lastAction))) {
            const activeAction = currentAction(state.lastAction);
            if (state.pendingController && activeAction && isPassiveRead(activeAction)) {
                clearPendingRequest({ abort: true });
                // Existing request generations are positive. Invalidate the
                // completed authentication context before any late read can
                // repopulate facts that were just removed.
                state.latestRequestId = 0;
            }
            state.currentViewModel = null;
            state.lastAction = "";
            state.lastParams = {};
            state.lastPager = null;
            if (activeAction && isDashboardReadAction(activeAction)) {
                state.lastRaw = null;
                state.rawResponseAvailable = false;
                if (typeof updateRawDrawer === "function") updateRawDrawer();
            }
            if (typeof updatePager === "function") {
                updatePager(null);
            }
        }
    }

    function selectionParamsSignature(params) {
        return JSON.stringify(Object.keys(params || {})
            .sort()
            .map((key) => [key, params[key]]));
    }

    function dashboardTargetParams(action, params, actions = state.screen?.actions || []) {
        if (!action) {
            return {};
        }
        const continuationFields = typeof resultContinuations?.continuationFields === "function"
            ? resultContinuations.continuationFields(action, actions)
            : new Set();
        const allowed = new Set((action.fields || [])
            .filter((field) => typeof safeWorkspaceField === "function"
                && safeWorkspaceField(field)
                && field?.secret !== true && field?.sensitive !== true
                && String(field?.sensitive_level || "none") === "none")
            .map((field) => String(field.key || "").trim())
            .filter((key) => key && !continuationFields.has(key)));
        const pagination = action.pagination || {};
        const declaredFieldKeys = new Set((action.fields || [])
            .map((field) => String(field?.key || "").trim())
            .filter(Boolean));
        ["page", "page_size", "limit", "offset", "cursor"]
            .filter((key) => declaredFieldKeys.has(key))
            .concat([
                pagination.page_param,
                pagination.page_size_param,
                pagination.limit_param,
                pagination.offset_param,
                pagination.cursor_param,
            ])
            .map((key) => String(key || "").trim())
            .filter(Boolean)
            .forEach((key) => allowed.add(key));
        return Object.fromEntries(Object.entries(params || {}).filter(([key, value]) => (
            allowed.has(key)
            && (value === null || ["string", "number", "boolean"].includes(typeof value))
            && !(typeof value === "number" && !Number.isFinite(value))
        )));
    }

    function clearDashboardSelectorForTarget(panelKeys) {
        if (typeof clearDashboardSelectorState !== "function"
            || typeof dashboardTargetPanelKeys !== "function") {
            return;
        }
        const targetKeys = new Set((panelKeys || [])
            .map((key) => String(key || "").trim())
            .filter(Boolean));
        if (!targetKeys.size) {
            return;
        }
        const selectorPanel = (state.screen?.screen?.dashboard_panels || []).find((candidate) => (
            dashboardTargetPanelKeys(candidate).some((key) => targetKeys.has(key))
        ));
        if (selectorPanel) {
            clearDashboardSelectorState(selectorPanel);
        }
    }

    function clearFullScreenReadState(action, error) {
        if (!action
            || typeof isPassiveRead !== "function"
            || !isPassiveRead(action)
            || (!isDashboardAuthorizationError(error) && !isDashboardScopeInvalid(error))) {
            return false;
        }
        const actionKey = String(action.key || "").trim();
        if (state.lastAction && String(state.lastAction).trim() !== actionKey) return false;
        const actionScreen = String(action.screen_key || "").trim();
        const currentScreen = String(state.screen?.screen?.key || "").trim();
        if (actionScreen && currentScreen && actionScreen !== currentScreen) return false;
        if (state.pendingController) clearPendingRequest({ abort: true });
        state.latestRequestId = 0;
        state.currentViewModel = null;
        state.currentRows = [];
        state.currentColumns = [];
        state.visibleRows = [];
        state.lastAction = "";
        state.lastParams = {};
        state.lastPager = null;
        state.selectedRowContext = null;
        state.selectedRowIndex = 0;
        state.lastRaw = null;
        state.rawResponseAvailable = false;
        if (typeof updatePager === "function") updatePager(null);
        if (typeof updateRawDrawer === "function") updateRawDrawer();
        return true;
    }

    function renderFullScreenRestrictedResult(action, hasDashboardPanel, status, result) {
        if (hasDashboardPanel || !clearFullScreenReadState(action, { status, payload: result })) {
            return false;
        }
        renderBoundedApplicationError({ status, payload: result });
        return true;
    }

    function isTaskDashboardScreen() {
        const screen = state.screen?.screen;
        return screen?.entry_state?.mode === "dashboard"
            && typeof experienceEntries === "function"
            && experienceEntries("task").some(entry => experienceEntryScreen(entry) === screen.key);
    }

    function renderTaskDashboardSummary(viewModel) {
        if (!isTaskDashboardScreen() || (!viewModel?.business_summary && !viewModel?.blocking_reason)) return "";
        return `<section class="tui-decision-cue" data-task-result-summary role="status">
            <div><span>当前结果</span><strong>${escapeHtml(viewModel.title || "当前任务")} · ${escapeHtml(viewModel.status || "未提供")}</strong></div>
            <div><span>事实与限制</span><strong>${escapeHtml(viewModel.business_summary)}</strong></div>
            ${viewModel.blocking_reason ? `<div><span>当前阻断</span><strong>${escapeHtml(viewModel.blocking_reason)}</strong></div>` : ""}
        </section>`;
    }

    function targetedReadRetryDescriptor(action, params, panelKey) {
        if (!action || !isPassiveRead(action) || typeof passiveReadRetryParams !== "function") {
            return null;
        }
        const retryParams = passiveReadRetryParams(action, params || {});
        if (!retryParams) {
            return null;
        }
        return {
            actionKey: action.key,
            panelKey,
            params: dashboardTargetParams(action, retryParams),
        };
    }

    function targetedReadRetryableError(error) {
        const status = Number(error?.status || 0);
        return status === 0 || status >= 500 || error instanceof TypeError;
    }

    function bindTargetedPanelRetry(container, descriptor) {
        const button = container.querySelector("[data-panel-retry]");
        if (!button) {
            return;
        }
        if (!descriptor) {
            button.remove();
            return;
        }
        button.dataset.targetedReadRetry = "true";
        button.textContent = "重新读取";
        button.addEventListener("click", () => {
            button.disabled = true;
            runAction(descriptor.actionKey, null, {
                params: { ...descriptor.params },
                dashboardResultPanelKey: descriptor.panelKey,
                targetedReadRetry: true,
            });
        });
    }

    function appendTargetedPanelRetry(container, descriptor) {
        if (!descriptor || container.querySelector("[data-targeted-read-retry]")) {
            return;
        }
        container.insertAdjacentHTML(
            "beforeend",
            `<div class="tui-panel-error-actions" data-targeted-read-retry><button type="button" data-panel-retry>重新读取</button></div>`,
        );
        bindTargetedPanelRetry(container, descriptor);
    }

    function renderTargetedDashboardEnvelope(action, result, params, dashboardResultPanelKey, dashboardRefreshPanelKey) {
        const targetParams = params || {};
        const targetStatus = Number(result.response?.status_code ?? result.status_code ?? 0);
        const targetOutcome = String(result.outcome || "").trim().toLowerCase();
        const targetFailure = (Number.isFinite(targetStatus) && targetStatus >= 400)
            || ["failed", "blocked"].includes(targetOutcome);
        const targetRetryable = (Number.isFinite(targetStatus) && targetStatus >= 500)
            || (targetStatus < 400 && targetOutcome === "failed");
        if (dashboardTargetNeedsClear(targetStatus, result)) {
            clearDashboardSelectorForTarget([dashboardResultPanelKey, dashboardRefreshPanelKey]);
        }
        if (!dashboardTargetCanRenderViewModel(targetStatus, result)
            || (targetFailure && !result.view_model)) {
            const ownerError = new Error("目标数据未能读取");
            ownerError.status = isDashboardScopeInvalid(result) ? 400
                : Number.isFinite(targetStatus) && targetStatus >= 400 ? targetStatus : 502;
            ownerError.payload = result;
            renderDashboardActionError(
                dashboardResultPanelKey,
                ownerError,
                action,
                targetParams,
            );
        } else {
            renderDashboardActionResult(dashboardResultPanelKey, result.view_model, action, {
                params: targetParams,
                retryable: targetRetryable,
            });
        }
    }

    function renderDashboardActionResult(panelKey, viewModel, action, context = {}) {
        const panel = currentDashboardPanel(panelKey);
        const container = panel
            ? els.main.querySelector(`[data-dashboard-panel="${CSS.escape(panel.key)}"]`)
            : null;
        if (!panel || !container) {
            return;
        }
        const targetParams = context.params || {};
        const retryDescriptor = targetedReadRetryDescriptor(action, targetParams, panelKey);
        container.dashboardResultRetry = retryDescriptor;
        container.dashboardResultActionKey = action.key;
        container.dashboardResultParams = { ...targetParams };
        const actionSemantics = actionResultSemantics(action.key);
        const resultPanel = {
            ...panel,
            action_key: action.key,
            presentation_semantic: actionSemantics[0] || panel.presentation_semantic,
        };
        container.panelViewModel = viewModel || null;
        container.innerHTML = renderDashboardPanelShell(
            panel,
            renderDashboardPanelBody(resultPanel, viewModel, {
                targetAction: action,
                targetParams,
                targetPanelKey: panelKey,
            }),
        );
        container.querySelector('.tui-panel-disclosure')?.setAttribute('open', '');
        container.scrollIntoView({ block: 'nearest' });
        bindCopyButtons(container);
        bindDashboardPanelOpenControls(container);
        bindDashboardRowActions(container, resultPanel);
        bindNextStepButtons(container, viewModel?.next_steps);
        if (typeof bindResultPagerControls === "function") {
            bindResultPagerControls(container, action, viewModel?.pager, targetParams, panelKey);
        }
        if (context.retryable) {
            appendTargetedPanelRetry(container, retryDescriptor);
        }
        processHostSlot(container);
    }

    function renderDashboardActionError(panelKey, error, action = null, params = {}) {
        const panel = currentDashboardPanel(panelKey);
        const container = panel
            ? els.main.querySelector(`[data-dashboard-panel="${CSS.escape(panel.key)}"]`)
            : null;
        if (!panel || !container) {
            renderBoundedApplicationError(error);
            return;
        }
        const errorStatus = Number(error?.status || 0);
        if (errorStatus === 401 || errorStatus === 403 || isDashboardScopeInvalid(error)) {
            clearDashboardSelectorForTarget([panelKey]);
        }
        const retryDescriptor = targetedReadRetryableError(error)
            ? targetedReadRetryDescriptor(action, params, panelKey)
            : null;
        container.dashboardResultRetry = retryDescriptor;
        container.dashboardResultActionKey = action?.key || "";
        container.dashboardResultParams = { ...(params || {}) };
        container.panelViewModel = null;
        container.innerHTML = renderDashboardPanelShell(panel, renderDashboardPanelError(panel, error));
        container.querySelector('.tui-panel-disclosure')?.setAttribute('open', '');
        container.scrollIntoView({ block: 'nearest' });
        bindDashboardPanelOpenControls(container);
        bindTargetedPanelRetry(container, retryDescriptor);
        container.querySelectorAll('[data-panel-recovery-screen]').forEach(button => {
            button.addEventListener('click', () => loadRecoveryScreen(button.dataset.panelRecoveryScreen));
        });
    }

    function renderDetailSectionMarkup(section) {
        const title = section?.title || section?.label || "详情";
        const body = Array.isArray(section?.body)
            ? section.body
            : (section?.body ? [section.body] : []);
        const limitation = section?.restriction_message
            || section?.limitation
            || section?.blocking_reason
            || "";
        const columns = Array.isArray(section?.columns)
            ? section.columns
                .map((column) => ({
                    key: String(column?.key || "").trim(),
                    label: String(column?.label || column?.key || "").trim(),
                }))
                .filter((column) => column.key && column.label)
            : [];
        const rawRows = Array.isArray(section?.rows) ? section.rows : [];
        const rawFields = Array.isArray(section?.fields) ? section.fields : [];
        const rowFields = (row) => {
            if (Array.isArray(row?.fields)) {
                return row.fields
                    .map((field) => ({
                        key: String(field?.key || "").trim(),
                        label: String(field?.label || field?.key || "").trim(),
                        value: field?.value,
                    }))
                    .filter((field) => field.key || field.label);
            }
            if (Array.isArray(row)) {
                return [{ key: String(row[0] || ""), label: String(row[0] || ""), value: row[1] }];
            }
            if (row && typeof row === "object") {
                return [{
                    key: String(row.key || row.label || ""),
                    label: String(row.label || row.key || ""),
                    value: row.value,
                }];
            }
            return [];
        };
        const tabularRows = columns.length
            ? rawRows.map((row) => {
                const values = new Map(rowFields(row).map((field) => [field.key || field.label, field.value]));
                return columns.map((column) => values.get(column.key));
            })
            : [];
        const simpleRows = [
            ...rawFields.map((field) => ({
                label: field?.label || field?.key,
                value: field?.value,
            })),
            ...rawRows.flatMap((row) => rowFields(row)),
        ].filter((row) => row.label !== undefined && row.label !== "");
        const tableMarkup = tabularRows.length
            ? `
                <div class="tui-table-scroll" tabindex="0" aria-label="${escapeHtml(title)}">
                    <table class="tui-mini-table">
                        <thead><tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr></thead>
                        <tbody>${tabularRows.map((row) => `<tr>${row.map((value) => `<td>${escapeHtml(displayValue(value))}</td>`).join("")}</tr>`).join("")}</tbody>
                    </table>
                </div>
            `
            : "";
        return `
            <details class="tui-detail-section" data-detail-section>
                <summary>${escapeHtml(title)}</summary>
                ${body.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
                ${limitation ? `<p class="tui-panel-note">${escapeHtml(limitation)}</p>` : ""}
                ${tableMarkup}
                ${!tableMarkup && simpleRows.length
                    ? `<dl class="tui-message-fields">${simpleRows.map((row) => `<dt>${escapeHtml(row.label)}</dt><dd>${escapeHtml(displayValue(row.value))}</dd>`).join("")}</dl>`
                    : ""}
            </details>
        `;
    }

    function renderDashboardWorkspaceReturnMarkup() {
        const screen = state.screen?.screen;
        if (!Array.isArray(screen?.dashboard_panels) || !screen.dashboard_panels.length) {
            return "";
        }
        const label = String(screen.label || "当前工作区").trim();
        return `<button type="button" data-return-dashboard-workspace>返回${escapeHtml(label)}</button>`;
    }

    function bindDashboardWorkspaceReturnControl(root) {
        root.querySelector("[data-return-dashboard-workspace]")?.addEventListener("click", () => {
            const screenKey = String(state.screen?.screen?.key || "").trim();
            if (screenKey) {
                loadScreen(screenKey, { skipCapture: true, skipRestoreAction: true });
            }
        });
    }

    function renderResultPagerMarkup(pager) {
        if (!pager || pager.client_side === true) {
            return "";
        }
        const page = Number(pager.page || 1);
        const totalPages = Number(pager.total_pages || 0);
        const normalizedPage = Number.isInteger(page) && page > 0 ? page : 1;
        const pageLabel = Number.isInteger(totalPages) && totalPages > 0
            ? `第 ${normalizedPage} / ${totalPages} 页`
            : `第 ${normalizedPage} 页`;
        return `
            <div class="tui-datagrid-pager" data-result-pager aria-label="详情分页">
                <button type="button" data-result-page-delta="-1" ${pager.has_previous ? "" : "disabled"}>上一页</button>
                <span>${escapeHtml(pageLabel)}${pager.total_rows != null ? ` / 共 ${escapeHtml(pager.total_rows)} 条` : ""}</span>
                <button type="button" data-result-page-delta="1" ${pager.has_next ? "" : "disabled"}>下一页</button>
            </div>
        `;
    }

    function bindResultPagerControls(container, action, pager, params, targetPanelKey = "") {
        if (!container || !pager || pager.client_side === true || !action || !isPassiveRead(action)) {
            return;
        }
        container.querySelectorAll("[data-result-page-delta]").forEach((button) => {
            if (button.dataset.resultPagerBound === "true") {
                return;
            }
            button.dataset.resultPagerBound = "true";
            button.addEventListener("click", async () => {
                const delta = Number(button.dataset.resultPageDelta || 0);
                const patch = paginationParamPatch(action, pager, params || {}, delta);
                if (!patch) {
                    setStatus("当前分页参数不可用");
                    return;
                }
                const requestParams = { ...(params || {}), ...patch };
                const options = { params: requestParams };
                if (targetPanelKey) {
                    options.dashboardResultPanelKey = targetPanelKey;
                }
                await runAction(action.key, null, options);
            });
        });
    }
