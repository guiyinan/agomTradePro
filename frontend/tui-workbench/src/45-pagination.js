    function renderDataGridPager(pager) {
        if (!pager) {
            return "";
        }
        const page = pager.page ?? "-";
        const totalPages = pager.total_pages ?? "-";
        const totalRows = pager.total_rows;
        const cursor = String(pager.pagination_mode || pager.mode || '') === 'cursor';
        const size = Number(pager.page_size || state.clientPageSize);
        const start = totalRows === 0 ? 0 : (Number(page) - 1) * size + 1;
        const end = Number.isFinite(Number(totalRows)) && totalRows !== null
            ? Math.min(Number(totalRows), start + size - 1) : start + state.visibleRows.length - 1;
        const range = cursor || !Number.isFinite(start) ? `本批 ${state.visibleRows.length} 条`
            : `第 ${start}–${end} 条`;
        const sizeControl = pager.client_side || Boolean(currentAction(state.lastAction)?.pagination?.page_size_param
            || currentAction(state.lastAction)?.pagination?.limit_param
            || (currentAction(state.lastAction)?.fields || []).some(field => ['page_size','pageSize','limit','size'].includes(field.key)));
        return `
            <div class="tui-datagrid-pager" aria-label="分页">
                ${sizeControl ? `<label>每页 <select data-page-size aria-label="每页条数">${[...new Set([20,50,100,size])].sort((a,b)=>a-b).map(value=>`<option value="${value}" ${value === size ? 'selected' : ''}>${value}</option>`).join('')}</select> 条</label>` : ''}
                <button type="button" data-page-delta="-1" ${pager.has_previous ? "" : "disabled"}>上一页</button>
                ${!cursor && Number(totalPages) > 0 ? `<label>第 <input data-page-number aria-label="跳转页码" type="number" min="1" max="${escapeHtml(totalPages)}" value="${escapeHtml(page)}"> / ${escapeHtml(totalPages)} 页</label>` : '<span>按批次浏览</span>'}
                <span>${escapeHtml(range)}${totalRows != null ? `，共 ${escapeHtml(totalRows)} 行` : '，总量未知'}</span>
                <button type="button" data-page-delta="1" ${pager.has_next ? "" : "disabled"}>下一页</button>
            </div>
        `;
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
            state.selectedRowIndex = (state.clientPage - 1) * state.clientPageSize;
            drawDataGrid();
            setStatus(`第 ${state.clientPage} 页`);
            return;
        }
        if (state.pendingController) {
            setStatus("翻页中，请稍候");
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
        await runGridQuery({ ...state.lastParams, ...patch });
    }

    function bindGridPagination() {
        els.main.querySelector('[data-page-size]')?.addEventListener('change', event => {
            const size = Number(event.target.value);
            if (state.lastPager?.client_side || !state.currentViewModel?.pager) {
                state.clientPageSize = size;
                state.clientPage = 1;
                state.selectedRowIndex = 0;
                drawDataGrid();
                return;
            }
            const action = currentAction(state.lastAction);
            const metadata = action.pagination || {};
            const key = metadata.page_size_param || metadata.limit_param || firstFieldKey(action, ['page_size','pageSize','limit','size']);
            const patch = paginationParamPatch(action, state.lastPager, state.lastParams, 1 - Number(state.lastPager.page || 1));
            if (patch) runGridQuery({ ...state.lastParams, ...patch, [key]: size });
        });
        els.main.querySelector('[data-page-number]')?.addEventListener('keydown', event => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            const target = Number(event.target.value);
            if (!event.target.reportValidity() || !Number.isInteger(target)) return;
            pageDelta(target - Number(state.lastPager.page));
        });
    }

    function bindPanelPagination(container, panel, viewModel) {
        const redraw = () => {
            container.innerHTML = renderDashboardPanelShell(panel, renderPanelDataGrid(panel, viewModel));
            bindDashboardFilters(container);
            bindDashboardPanelOpenControls(container);
            bindDashboardRowActions(container, panel);
            bindPanelPagination(container, panel, viewModel);
        };
        container.querySelectorAll('[data-panel-page-delta]').forEach(button => button.addEventListener('click', () => {
            panelPages[panel.key].page += Number(button.dataset.panelPageDelta);
            redraw();
            container.querySelector('.tui-table-scroll')?.focus();
        }));
        container.querySelector('[data-panel-page-size]')?.addEventListener('change', event => {
            panelPages[panel.key] = { page: 1, size: Number(event.target.value) };
            redraw();
        });
        container.querySelector('[data-panel-full-list]')?.addEventListener('click', () => {
            captureWorkspace();
            state.lastAction = panel.action_key;
            state.lastParams = { ...state.dashboardFilters[panel.key] };
            renderViewModel(viewModel);
            els.main.insertAdjacentHTML('afterbegin', '<button type="button" data-return-dashboard>返回概览</button>');
            els.main.querySelector('[data-return-dashboard]').addEventListener('click', () => loadScreen(state.screen.screen.key, { skipCapture: true, skipRestoreAction: true }));
        });
    }

    async function runGridQuery(params) {
        const action = currentAction(state.lastAction);
        if (!isPassiveRead(action) || state.pendingController) return;
        await runAction(action.key, null, { params, preserveGrid: true });
    }

    function setGridUpdating(updating) {
        els.main.setAttribute('aria-busy', String(updating));
        els.main.querySelectorAll('.tui-datagrid-pager button, .tui-datagrid-pager input, .tui-datagrid-pager select')
            .forEach(control => {
                if (updating) { control.dataset.wasDisabled = String(control.disabled); control.disabled = true; }
                else { control.disabled = control.dataset.wasDisabled === 'true'; }
            });
        els.main.querySelector('[data-grid-update]')?.remove();
        if (updating) els.main.insertAdjacentHTML('afterbegin', '<div data-grid-update role="status">正在更新列表，当前仍显示上一页…</div>');
    }

    function renderGridFailure(params) {
        setGridUpdating(false);
        els.main.querySelector('[data-grid-error]')?.remove();
        els.main.insertAdjacentHTML('afterbegin', '<div data-grid-error role="status">本次更新未完成，已保留原页。<button type="button" data-grid-retry>重试更新</button></div>');
        els.main.querySelector('[data-grid-retry]').addEventListener('click', () => runGridQuery(params));
        setStatus('更新失败，仍显示原页');
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
        const pageSizeParam = pagination.page_size_param || firstFieldKey(action, ["page_size", "pageSize", "limit", "size"]);
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
