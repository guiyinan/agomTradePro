    // Session-local presentation state; no business results or credentials are persisted.
    const workspaceStates = new Map();
    const panelPages = {};
    const operationContexts = new Map();

    function invalidateOperationContext(action, params) {
        if (actionTier(action) !== 'primary') return;
        const key = `${action.screen_key}:${action.key}`;
        const safe = safeActionParams(action, params);
        const signature = JSON.stringify(Object.keys(safe).sort().map(key => [key, safe[key]]));
        if (operationContexts.has(key) && operationContexts.get(key) !== signature) {
            screenCompletedSet(action.screen_key).clear();
            persistProgress();
        }
        operationContexts.set(key, signature);
    }

    function isPassiveRead(action) {
        return Boolean(action && ['GET','HEAD','OPTIONS'].includes(String(action.method || 'GET').toUpperCase())
            && String(action.risk || 'read').toLowerCase() === 'read' && !action.confirmation_required);
    }

    function safeWorkspaceField(field) {
        return !['password','file','hidden'].includes(field.input_type)
            && !['api_token','endpoint_url','secret','copyable_secret'].includes(field.presentation_semantic);
    }

    function safeActionParams(action, params) {
        const allowed = new Set((action?.fields || []).filter(safeWorkspaceField).map(field => field.key));
        const pagination = action?.pagination || {};
        ['page','page_size','limit','offset','cursor'].forEach(key => allowed.add(key));
        ['page_param','page_size_param','limit_param','offset_param','cursor_param'].forEach(key => {
            if (pagination[key]) allowed.add(pagination[key]);
        });
        return Object.fromEntries(Object.entries(params || {}).filter(([key, value]) => allowed.has(key)
            && (value == null || ['string','number','boolean'].includes(typeof value))));
    }

    function captureWorkspace() {
        const key = state.screen?.screen?.key;
        if (!key) return;
        const drafts = {};
        for (const action of state.screen.actions || []) {
            const form = els.actions.querySelector(`[data-action-ui-key="${CSS.escape(actionUiKey(action))}"]`);
            if (!form) continue;
            drafts[action.key] = {};
            for (const field of (action.fields || []).filter(safeWorkspaceField)) {
                const input = formFieldElement(form, field.key);
                if (input) drafts[action.key][field.key] = field.input_type === 'checkbox' ? input.checked : input.value;
            }
        }
        const action = currentAction(state.lastAction);
        workspaceStates.set(key, {
            drafts, filters: { ...state.dashboardFilters }, panelPages: { ...panelPages },
            filterText: state.filterText, clientPage: state.clientPage, clientPageSize: state.clientPageSize,
            selectedRowIndex: state.selectedRowIndex, scrollTop: els.main.scrollTop,
            actionKey: isPassiveRead(action) && state.currentViewModel ? action.key : '',
            params: isPassiveRead(action) ? safeActionParams(action, state.lastParams) : {},
            queued: state.currentViewModel?.queued_run ? queuedObservationModel(state.currentViewModel) : null,
        });
        if (workspaceStates.size > 24) workspaceStates.delete(workspaceStates.keys().next().value);
    }

    function restoreWorkspaceForms(snapshot) {
        if (!snapshot) return;
        for (const action of state.screen.actions || []) {
            const form = els.actions.querySelector(`[data-action-ui-key="${CSS.escape(actionUiKey(action))}"]`);
            if (!form) continue;
            for (const field of (action.fields || []).filter(safeWorkspaceField)) {
                const value = snapshot.drafts[action.key]?.[field.key];
                const input = formFieldElement(form, field.key);
                if (!input || value === undefined) continue;
                if (field.input_type === 'checkbox') input.checked = Boolean(value);
                else input.value = value;
            }
        }
    }

    function queuedObservationModel(model) {
        return { kind: 'detail', title: '任务运行状态', status: model.status,
            fields: [{ key: 'run_id', label: '运行编号', value: model.queued_run.run_id },
                { key: 'run_status', label: '状态', value: model.queued_run.status }],
            queued_run: { ...model.queued_run } };
    }

    async function refreshQueuedObservation(model) {
        const controller = new AbortController();
        const requestId = startPendingRequest(controller);
        try { await consumeQueuedRun(model, requestId); }
        finally { if (isLatestRequest(requestId)) clearPendingRequest(); }
    }

    function revealTaskWithParams(action, params) {
        focusActions();
        const form = revealActionFormInPanel(action);
        if (!form) return;
        for (const field of (action.fields || []).filter(safeWorkspaceField)) {
            if (!Object.prototype.hasOwnProperty.call(params, field.key)) continue;
            const input = formFieldElement(form, field.key);
            if (!input) continue;
            if (field.input_type === 'checkbox') input.checked = params[field.key] === true || params[field.key] === 'true';
            else input.value = params[field.key];
        }
        focusActionFormInPanel(form);
        setStatus(`已定位“${action.label}”，请核对对象后继续`);
    }

    function markDataReady() {
        runtimeCore.mark?.('p0-ready');
        runtimeCore.measure?.('bootstrap-to-p0', 'bootstrap-start', 'p0-ready');
    }
