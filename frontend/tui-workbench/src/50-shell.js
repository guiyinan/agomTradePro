    function showModal(title, bodyHtml, options = {}) {
        state.modalReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        els.modalTitle.textContent = title;
        els.modalBody.innerHTML = bodyHtml;
        els.modal.classList.remove("is-image-preview");
        const previousClass = els.modal.dataset.modalClass || "";
        if (previousClass) {
            els.modal.classList.remove(previousClass);
        }
        if (options.className) {
            els.modal.classList.add(options.className);
        }
        els.modal.dataset.modalClass = options.className || "";
        els.modal.hidden = false;
        els.modalClose.focus();
    }

    function modalFocusableElements() {
        if (!els.modal || els.modal.hidden) {
            return [];
        }
        return Array.from(els.modal.querySelectorAll(
            "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
        )).filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
    }

    function trapModalFocus(event) {
        if (event.key !== "Tab" || els.modal.hidden) {
            return false;
        }
        const focusable = modalFocusableElements();
        if (!focusable.length) {
            event.preventDefault();
            els.modalClose.focus();
            return true;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && (document.activeElement === first || !els.modal.contains(document.activeElement))) {
            event.preventDefault();
            last.focus();
            return true;
        }
        if (!event.shiftKey && (document.activeElement === last || !els.modal.contains(document.activeElement))) {
            event.preventDefault();
            first.focus();
            return true;
        }
        return false;
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
            const wasOpen = !els.modal.hidden;
            els.modal.hidden = true;
            els.modal.classList.remove("is-image-preview");
            els.modalBody.innerHTML = "";
            if (wasOpen && state.modalReturnFocus && document.contains(state.modalReturnFocus)) {
                state.modalReturnFocus.focus();
            }
            state.modalReturnFocus = null;
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
                <span>Alt+S/M/R/V/H</span><span>打开顶部对应菜单</span>
                <span>Alt+Shift+T</span><span>查看当前主题与三套风格</span>
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
        let text = String(value ?? "");
        if (/^[=+\-@]/.test(text)) {
            text = `'${text}`;
        }
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
        const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        const title = (state.currentViewModel.title || "tui-grid").toLowerCase().replace(/[^a-z0-9一-龥]+/g, "-").replace(/^-|-$/g, "") || "tui-grid";
        link.href = url;
        link.download = `${title}.csv`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        setStatus(`已导出 ${rows.length} 行`);
    }

    async function refreshCurrent() {
        const lastAction = state.lastAction ? currentAction(state.lastAction) : null;
        const isWriteAction = ["write", "admin"].includes(String(lastAction?.risk || "").toLowerCase());
        if (lastAction && !isWriteAction) {
            await runAction(state.lastAction, null, { params: { ...state.lastParams } });
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
            refreshRenderedActionPanel(state.screen.actions || [], state.screen.screen);
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
        if (state.menuSourceButton && state.menuSourceButton !== sourceButton) {
            state.menuSourceButton.setAttribute("aria-expanded", "false");
        }
        state.activeMenu = menuName;
        state.menuSourceButton = sourceButton;
        sourceButton.setAttribute("aria-expanded", "true");
        els.menuPopover.innerHTML = `
            <div class="tui-menu-title">${escapeHtml(menuName.toUpperCase())}</div>
            ${items.map(([command, label, key]) => `
                <button type="button" role="menuitem" data-menu-action="${escapeHtml(command)}">
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

    function closeMenu(options = {}) {
        const sourceButton = state.menuSourceButton;
        state.activeMenu = null;
        state.menuSourceButton = null;
        sourceButton?.setAttribute("aria-expanded", "false");
        if (els.menuPopover) {
            els.menuPopover.hidden = true;
            els.menuPopover.innerHTML = "";
        }
        if (options.restoreFocus && sourceButton && document.contains(sourceButton)) {
            sourceButton.focus();
        }
    }

    async function runCommand(command) {
        closeMenu();
        if (command === "refresh") {
            setLastRefresh();
            await refreshCurrent();
        } else if (command === "export") {
            exportGrid();
        } else if (command === "toggle-rail") {
            toggleRail();
        } else if (command === "focus-actions") {
            focusActions();
        } else if (command === "previous-workflow") {
            loadWorkflowStep(-1);
        } else if (command === "next-workflow") {
            loadWorkflowStep(1);
        } else if (command === "run-next-primary") {
            runNextPrimaryAction();
        } else if (command === "filter-actions") {
            focusActionFilter();
        } else if (command === "row-detail") {
            openSelectedRowDetail();
        } else if (command === "filter") {
            showFilterBar();
        } else if (command === "reset-progress") {
            resetCurrentScreenProgress();
        } else if (command === "toggle-inspector") {
            toggleInspector();
        } else if (command === "raw") {
            toggleRawDrawer();
        } else if (command === "help") {
            showHelp();
        }
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
            closeMenu({ restoreFocus: true });
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
        if (event.altKey && !event.ctrlKey && event.shiftKey && lowerKey === "t") {
            return "theme-status";
        }
        if (event.altKey && !event.ctrlKey && !event.shiftKey) {
            const menuKeys = { s: "file", m: "module", r: "action", v: "view", h: "help" };
            if (menuKeys[lowerKey]) {
                return `open-menu:${menuKeys[lowerKey]}`;
            }
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
        if (event.isComposing || event.metaKey || !els.modal.hidden) {
            return false;
        }
        const command = keyboardCommandForEvent(event);
        if (!command) {
            return false;
        }
        event.preventDefault();
        event.stopPropagation();
        if (command.startsWith("open-menu:")) {
            const menuName = command.slice("open-menu:".length);
            const button = document.querySelector(`[data-menu-command="${CSS.escape(menuName)}"]`);
            if (button) {
                openMenu(menuName, button);
            }
        } else if (command === "cycle-theme") {
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
            ? runtimeCore.debounce(() => applyFilter(true), actionFilterDebounceMs)
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
        els.menuPopover.addEventListener("keydown", (event) => {
            const items = Array.from(els.menuPopover.querySelectorAll("[role='menuitem']"));
            const currentIndex = items.indexOf(document.activeElement);
            let nextIndex = currentIndex;
            if (event.key === "ArrowDown") {
                nextIndex = (currentIndex + 1 + items.length) % items.length;
            } else if (event.key === "ArrowUp") {
                nextIndex = (currentIndex - 1 + items.length) % items.length;
            } else if (event.key === "Home") {
                nextIndex = 0;
            } else if (event.key === "End") {
                nextIndex = items.length - 1;
            } else if (event.key === "Escape") {
                event.preventDefault();
                closeMenu({ restoreFocus: true });
                return;
            } else if (event.key === "Tab") {
                closeMenu();
                return;
            } else {
                return;
            }
            if (items.length) {
                event.preventDefault();
                items[nextIndex]?.focus();
            }
        });
        document.addEventListener("click", (event) => {
            if (!els.menuPopover.hidden && !event.target.closest("[data-menu-popover]") && !event.target.closest("[data-menu-command]")) {
                closeMenu();
            }
        });
        document.addEventListener("keydown", (event) => {
            if (trapModalFocus(event)) {
                return;
            }
            if (handleGlobalShortcut(event)) {
                return;
            }
            if (event.key === "Escape") {
                if (closeTopLayer()) {
                    event.preventDefault();
                }
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
                if (state.lastPager) {
                    event.preventDefault();
                    pageDelta(1);
                }
            } else if (event.key === "PageUp" && !isEditableTarget(event.target)) {
                if (state.lastPager) {
                    event.preventDefault();
                    pageDelta(-1);
                }
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
            const deepLinkedScreen = screenKeyFromBrowserLocation();
            const deepLinkedAction = actionKeyFromBrowserLocation();
            const requestedScreen = deepLinkedScreen || (
                shouldResumeOnBoot() && state.lastNonHomeScreen
                    ? state.lastNonHomeScreen
                    : ""
            );
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
                        renderScreen(payload.screen, {
                            suppressAutoAction: Boolean(deepLinkedAction),
                        });
                        focusDeepLinkedAction(payload.screen, deepLinkedAction);
                        syncBrowserScreenLocation(payload.screen?.screen?.key, {
                            replace: true,
                            preserveAction: Boolean(deepLinkedAction),
                        });
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
            const isResumeAttempt = Boolean(!deepLinkedScreen && shouldResumeOnBoot() && state.lastNonHomeScreen);
            const initialScreen = deepLinkedScreen || (
                isResumeAttempt ? state.lastNonHomeScreen : catalog.default_screen
            );
            clearResumeOnBootFlag();
            const loaded = await loadScreen(initialScreen, {
                replaceHistory: true,
                preserveAction: Boolean(deepLinkedAction),
                deepLinkedActionKey: deepLinkedAction,
            });
            if (!loaded && (isResumeAttempt || deepLinkedScreen)) {
                setStatus(deepLinkedScreen
                    ? "链接中的工作区不可用，已返回首页"
                    : "上次工作区已不可用，已返回首页");
                await loadScreen(catalog.default_screen, { replaceHistory: true });
            }
            runtimeCore.mark?.("p0-ready");
            runtimeCore.measure?.("bootstrap-to-p0", "bootstrap-start", "p0-ready");
        } catch (error) {
            els.moduleTree.innerHTML = '<div class="tui-error">导航暂时不可用</div>';
            renderBoundedApplicationError(error);
        }
    }

    function requiredShellElementsAvailable() {
        const requiredKeys = [
            "app",
            "moduleTree",
            "screenTitle",
            "screenStatus",
            "actions",
            "mainTitle",
            "main",
            "inspector",
            "rawDrawer",
            "rawPanel",
            "rawToggle",
            "rawClose",
            "pager",
            "menuPopover",
            "filterBar",
            "filterInput",
            "filterClear",
            "modal",
            "modalTitle",
            "modalBody",
            "modalClose",
            "status",
        ];
        const missing = requiredKeys.filter((key) => !els[key]);
        if (!missing.length) {
            return true;
        }
        document.body.innerHTML = `
            <main class="tui-error" role="alert">
                工作台页面结构不完整，请刷新页面或联系系统管理员。
            </main>
        `;
        return false;
    }

    function initializeWorkbench() {
        if (!requiredShellElementsAvailable()) {
            return;
        }
        loadStoredProgress();
        loadStoredOperatorState();
        applyTheme(loadStoredTheme(), { silent: true });
        loadStoredInspectorWidth();
        bindControls();
        window.addEventListener("popstate", () => {
            const screenKey = screenKeyFromBrowserLocation();
            if (screenKey && screenKey !== state.screen?.screen?.key) {
                loadScreen(screenKey, {
                    suppressHistory: true,
                    preserveAction: true,
                    deepLinkedActionKey: actionKeyFromBrowserLocation(),
                });
            } else if (screenKey) {
                focusDeepLinkedAction(state.screen, actionKeyFromBrowserLocation());
            }
        });
        updateClock();
        window.setInterval(updateClock, 1000);
        bootstrap();
    }

    initializeWorkbench();
