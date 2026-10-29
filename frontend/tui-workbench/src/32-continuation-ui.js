function showContinuationRecovery(action, sourceActionKey, message) {
    const sourceAction = currentAction(sourceActionKey);
    els.main.innerHTML = `
        <section class="tui-entry-state" role="alert">
            <div class="tui-view-status">需要重新准备</div>
            <div class="tui-entry-copy">
                <strong>${escapeHtml(message)}</strong>
                <p>后续操作需要当前标签页中仍有效的预览结果。</p>
            </div>
            ${sourceAction ? `
                <div class="tui-entry-actions">
                    <button type="button" data-continuation-source>${escapeHtml(sourceAction.label)}</button>
                </div>
            ` : ""}
        </section>
    `;
    els.main.querySelector("[data-continuation-source]")?.addEventListener("click", () => {
        runAction(sourceAction.key, actionFormElement(sourceAction));
    });
    setStatus("等待重新准备");
}

function renderContinuationFailure(action, code) {
    state.lastRaw = null;
    state.rawResponseAvailable = false;
    state.lastAction = action.key;
    state.lastParams = {};
    renderViewModel({
        kind: "message",
        title: action.label || "当前任务",
        status: "未完成",
        message: "当前结果未能安全交接，尚未继续后续操作。请重新运行准备步骤。",
        user_error_code: code,
    });
    setStatus("交接未完成");
    updateRawDrawer();
}

function appendContinuationNextAction(targetActionKey) {
    const targetAction = currentAction(targetActionKey);
    if (!targetAction) {
        return;
    }
    const section = document.createElement("section");
    section.className = "tui-entry-actions";
    section.dataset.resultContinuation = "true";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `继续：${targetAction.label}`;
    button.addEventListener("click", () => {
        runAction(targetAction.key, actionFormElement(targetAction));
    });
    section.appendChild(button);
    els.main.appendChild(section);
}

function slowActionRetryOptions(action) {
    const incomingContinuation = resultContinuations.incomingForTarget(
        state.screen?.actions || [],
        action.key,
    );
    if (incomingContinuation.status === "ready") {
        return { continuationRetry: true };
    }
    return {
        params: { ...state.lastParams },
        idempotencyKey: state.lastIdempotencyKey,
    };
}

function offerActionRetry(actionKey, params, options = {}) {
    const action = currentAction(actionKey);
    const retryParams = passiveReadRetryParams(action, params);
    if (action) {
        appendPassiveReadEntry(action, params || {});
    }
    if (retryParams) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "tui-action-submit";
        button.dataset.actionReadRetry = "true";
        button.textContent = "重新读取";
        button.addEventListener("click", () => {
            button.disabled = true;
            runAction(actionKey, null, { params: { ...retryParams }, readRetry: true });
        });
        els.main.appendChild(button);
        return;
    }
    if (!options.idempotencyKey || !params) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tui-action-submit";
    button.dataset.actionSubmissionRetry = "true";
    button.textContent = "重试本次提交";
    button.addEventListener("click", () => {
        button.disabled = true;
        runAction(actionKey, null, { ...options, params: { ...params } });
    });
    els.main.appendChild(button);
}

function offerContinuationRetry(actionKey) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tui-action-submit";
    button.dataset.actionSubmissionRetry = "true";
    button.textContent = "重试本次提交";
    button.addEventListener("click", () => {
        button.disabled = true;
        runAction(actionKey, null, { continuationRetry: true });
    });
    els.main.appendChild(button);
}

function offerContinuationReadback(actionKey) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tui-action-submit";
    button.dataset.continuationReadback = "true";
    button.textContent = "查询原请求结果";
    button.addEventListener("click", () => {
        button.disabled = true;
        runAction(actionKey, null, { continuationReadback: true });
    });
    els.main.appendChild(button);
}

function showUnknownContinuation(action, targetActionKey) {
    const actions = Array.isArray(state.screen?.actions) ? state.screen.actions : [];
    const sourceDescriptor = resultContinuations.incomingForTarget(actions, targetActionKey);
    const readbackAction = currentAction(
        sourceDescriptor.status === "ready" ? sourceDescriptor.readbackActionKey : "",
    );
    els.main.innerHTML = `
        <section class="tui-entry-state" role="alert">
            <div class="tui-view-status">原请求结果待确认</div>
            <div class="tui-entry-copy">
                <strong>上一笔更正请求结果尚未确认。请先查询原请求。</strong>
                <p>查询会沿用原请求身份；没有匹配回执时仍保持待确认。</p>
            </div>
            <div class="tui-entry-actions">
                ${readbackAction ? '<button type="button" data-continuation-readback>查询原请求结果</button>' : ''}
            </div>
        </section>
    `;
    els.main.querySelector("[data-continuation-readback]")?.addEventListener("click", () => {
        runAction(readbackAction.key, null, { continuationReadback: true });
    });
    setStatus("原请求结果待确认");
}

function continuationFailureState({
    target,
    confirmed,
    reuseSourceKey,
    readbackActionKey,
    error,
    fetchStarted,
    fetchReturned,
}) {
    if (!target) return { retryable: false, unknown: false };
    const status = Number(error?.status);
    const explicitClientRejection = status >= 400 && status < 500;
    const retryable = !explicitClientRejection
        && (status >= 500 || (fetchStarted && !fetchReturned));
    return {
        retryable,
        unknown: Boolean(confirmed && reuseSourceKey && readbackActionKey && retryable),
    };
}

function clearContinuationSourceTriggerGuard(sourceActionKey, completed) {
    if (!completed) return false;
    const lastTriggeredAction = currentAction(state.lastFormTriggerRef);
    if (lastTriggeredAction?.key !== sourceActionKey) return false;
    state.lastFormTriggerRef = "";
    state.lastFormTriggerForm = null;
    state.lastFormTriggerAt = 0;
    return true;
}

function handleFeeScopeChange(form, event) {
    if (!["account_id", "trade_id"].includes(event.target?.name)) return;
    const action = currentAction(actionRefFromForm(form));
    if (!String(action?.key || "").startsWith("simulated-trading.fee-correction-")) return;
    const scope = Object.fromEntries(["account_id", "trade_id"].map(key =>
        [key, formFieldElement(form, key)?.value || ""]));
    if (!resultContinuations.setActiveScope(action, state.screen?.actions || [], scope)) return;
    // Invalidate the old request generation before clearing its visible facts.
    startPendingRequest(new AbortController());
    clearPendingRequest();
    closeModal();
    state.currentViewModel = null;
    state.currentRows = [];
    state.visibleRows = [];
    state.selectedRowContext = null;
    state.lastParams = {};
    state.lastAction = null;
    state.lastRaw = null;
    state.rawResponseAvailable = false;
    renderError("账户或成交已变化，请重新读取费用材料；原未决结果并未因此撤销。");
    renderInspector({ title: "请重新读取费用材料", rows: [], body: "切换范围不代表原请求未发生。" });
    updateRawDrawer();
}

function isOwnerOrderMutationAction(actionKey) {
    return [
        'simulated-trading.order-decision-apply',
        'simulated-trading.order-cancel',
    ].includes(String(actionKey || ''));
}

function beginOwnerOrderMutationRequest(action, requestId, options, form) {
    state.pendingOrderMutation = null;
    if (!isOwnerOrderMutationAction(action?.key)) return false;
    const params = options.params && typeof options.params === 'object'
        ? { ...options.params }
        : {};
    if (form && Array.isArray(action.fields)) {
        action.fields.filter(field => field.binding === 'path').forEach(field => {
            const control = formFieldElement(form, field.key);
            if (control) params[field.key] = control.value;
        });
    }
    state.pendingOrderMutation = {
        requestId,
        actionKey: String(action.key),
        confirmed: Boolean(options.confirmed),
        fetchStarted: false,
        params,
    };
    return true;
}

function rememberOwnerOrderMutationParams(requestId, params) {
    if (state.pendingOrderMutation?.requestId === requestId) {
        state.pendingOrderMutation.params = { ...params };
    }
}

function markOwnerOrderMutationDispatched(requestId, confirmed) {
    if (state.pendingOrderMutation?.requestId === requestId) {
        state.pendingOrderMutation.fetchStarted = true;
        state.pendingOrderMutation.confirmed = confirmed;
    }
}

function clearOwnerOrderMutationRequest(requestId) {
    if (state.pendingOrderMutation?.requestId === requestId) {
        state.pendingOrderMutation = null;
    }
}

function handleOwnerOrderMutationFailure(actionKey, requestId, request) {
    clearOwnerOrderMutationRequest(requestId);
    return handleUnknownOwnerOrderMutationOutcome(actionKey, request);
}

function handleUnknownOwnerOrderMutationOutcome(actionKey, request) {
    if (!isOwnerOrderMutationAction(actionKey)
        || !request.confirmed
        || !request.fetchStarted
        || !(request.error?.name === 'AbortError'
            || Number(request.error?.status || 0) >= 500
            || !request.fetchReturned)) {
        return false;
    }
    clearPendingRequest();
    renderUnknownOrderMutationOutcome(actionKey, request.params || {});
    return true;
}

function renderUnknownOrderMutationOutcome(actionKey, params) {
    const publicId = (value) => {
        if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) {
            return String(value);
        }
        if (typeof value === 'string' && /^[1-9][0-9]*$/.test(value)) {
            return value;
        }
        return null;
    };
    const accountId = publicId(params?.account_id);
    const orderId = publicId(params?.order_id);
    const decisionId = publicId(params?.decision_id);
    const isApply = actionKey === 'simulated-trading.order-decision-apply';
    const nextSteps = accountId && orderId ? [
        ...(isApply && decisionId ? [{
            label: `读取原账户 ${accountId}、订单 ${orderId} 的撮合决定列表（含决定 ${decisionId}）`,
            action_key: 'simulated-trading.order-decisions',
            params: { account_id: accountId, order_id: orderId, limit: 5 },
        }] : !isApply ? [{
            label: `重新读取原账户 ${accountId} 的订单列表（定位订单 ${orderId}）`,
            action_key: 'simulated-trading.orders',
            params: { account_id: accountId, limit: 5 },
        }] : []),
        {
            label: `查看原账户 ${accountId}、订单 ${orderId} 的成交回执`,
            action_key: 'simulated-trading.order-fills',
            params: { account_id: accountId, order_id: orderId, limit: 5 },
        },
    ] : [];
    const title = isApply ? '原撮合决定入账状态暂不能确认' : '原订单撤销状态暂不能确认';
    const status = isApply ? '入账结果尚未确认' : '撤销结果尚未确认';
    const summary = isApply
        ? (nextSteps.length
            ? `账户 ${accountId}、订单 ${orderId}、决定 ${decisionId} 的请求结果暂不能确认。请先读取原决定列表和成交回执；如仍无法确认，可从原决定页对同一决定显式重试，已有入账会按原结果核对，不要重新撮合。`
            : '请求结果暂不能确认，且原订单范围无法核对。请先重新选择本人账户并读取订单记录。')
        : (nextSteps.length
            ? `账户 ${accountId}、订单 ${orderId} 的撤销结果暂不能确认。请先读取原订单状态和成交回执，再决定是否从原订单页重试。`
            : '撤销结果暂不能确认，且原订单范围无法核对。请先重新选择本人账户并读取订单记录。');
    state.currentViewModel = null;
    state.currentRows = [];
    state.visibleRows = [];
    state.selectedRowContext = null;
    state.lastParams = {};
    state.lastAction = null;
    state.lastPager = null;
    state.lastIdempotencyKey = null;
    state.lastRaw = null;
    state.rawResponseAvailable = false;
    renderViewModel({
        kind: 'detail',
        title,
        status,
        outcome: 'blocked',
        business_summary: summary,
        fields: [],
        nested: [],
        sections: [],
        next_steps: nextSteps,
    });
    setStatus(title);
}

function ownerOrderConfirmationContextIsCurrent(context) {
    if (!isOwnerOrderMutationAction(context.actionKey)) return true;
    const currentScreenKey = String(state.screen?.screen?.key || state.screen?.key || '');
    if (state.latestRequestId !== context.requestId
        || currentScreenKey !== context.screenKey
        || state.lastAction !== context.lastAction) {
        return false;
    }
    const currentActions = Array.isArray(state.screen?.actions) ? state.screen.actions : [];
    if (context.screenKey && !currentActions.some(item => item?.key === context.actionKey)) {
        return false;
    }
    if (context.lastAction !== context.actionKey) return true;
    const currentParams = state.lastParams && typeof state.lastParams === 'object'
        ? state.lastParams
        : {};
    const pathScope = Object.fromEntries(
        (Array.isArray(context.action?.fields) ? context.action.fields : [])
            .filter(field => field?.binding === 'path' && typeof field.key === 'string')
            .filter(field => Object.prototype.hasOwnProperty.call(context.params || {}, field.key))
            .map(field => [field.key, String(context.params[field.key] ?? '')]),
    );
    return Object.entries(pathScope).every(([key, value]) =>
        String(currentParams[key] ?? '') === value);
}

function handleOrderOperationScopeChange(form, event) {
    if (!['input', 'change'].includes(event?.type)) return;
    const action = currentAction(actionRefFromForm(form));
    const actionKey = String(action?.key || '');
    if (!isOwnerOrderMutationAction(actionKey)) return;
    const pathFields = Array.isArray(action?.fields)
        ? action.fields.filter(field => field?.binding === 'path' && typeof field.key === 'string')
        : [];
    if (!pathFields.some(field => field.key === event.target?.name)) return;

    const pending = state.pendingOrderMutation?.actionKey === actionKey
        ? state.pendingOrderMutation
        : null;
    const baseline = pending?.params
        || (state.lastAction === actionKey ? state.lastParams : null);
    if (!baseline) return;
    const hasScopeChange = pathFields.some(field => {
        const control = formFieldElement(form, field.key);
        const currentValue = String(control?.value ?? '');
        return currentValue !== String(baseline[field.key] ?? '');
    });
    if (!hasScopeChange) return;

    const originalParams = { ...baseline };
    const uncertain = Boolean(pending?.confirmed && pending.fetchStarted);
    const confirmationWasOpen = Boolean(els.modal && !els.modal.hidden);
    state.pendingOrderMutation = null;
    startPendingRequest(new AbortController());
    clearPendingRequest();
    closeModal();
    state.currentViewModel = null;
    state.currentRows = [];
    state.visibleRows = [];
    state.selectedRowContext = null;
    state.selectedRowIndex = 0;
    state.lastAction = null;
    state.lastParams = {};
    state.lastPager = null;
    state.lastIdempotencyKey = null;
    state.lastRaw = null;
    state.rawResponseAvailable = false;
    if (uncertain) {
        renderUnknownOrderMutationOutcome(actionKey, originalParams);
        renderInspector({
            title: '原订单操作结果暂不能确认',
            rows: [],
            body: '已清除旧范围结果；下面的回读入口仍固定指向原账户和订单。',
        });
    } else {
        const accountId = String(originalParams.account_id ?? '');
        const orderId = String(originalParams.order_id ?? '');
        const decisionText = actionKey === 'simulated-trading.order-decision-apply'
            ? `、决定 ${String(originalParams.decision_id ?? '')}`
            : '';
        const message = confirmationWasOpen
            ? `账户 ${accountId}、订单 ${orderId}${decisionText} 的确认已因表单目标变化关闭。请重新读取原范围后再确认。`
            : `账户 ${accountId}、订单 ${orderId}${decisionText} 的旧结果已清除。请按当前表单范围重新读取。`;
        renderError(message);
        renderInspector({ title: '订单操作范围已变化', rows: [], body: message });
    }
    updateRawDrawer();
}

function offerFeeFencedResolution(action, actions, result) {
    if (action.key !== "simulated-trading.fee-correction-discover") return;
    const offered = resultContinuations.offerFencedResolution(action, actions, result);
    if (offered.status !== "ready") return;
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.feeEndFenced = "true";
    button.textContent = "结束这份旧材料的确认，继续核对或准备新材料";
    button.addEventListener("click", () => {
        showModal("结束旧材料确认", `
            <p>材料 ${escapeHtml(offered.proof.source_locator)} 的旧确认已受较新账户策略隔离。</p>
            <p>本操作仅结束这份旧材料在当前页面的确认流程；历史是否入账仍须核对回执。
            不会删除账务事件、修改策略或自动准备新材料。</p>
            <button type="button" data-fee-ack-fenced>明确结束旧确认</button>`);
        els.modalBody.querySelector("[data-fee-ack-fenced]")?.addEventListener("click", () => {
            const ended = resultContinuations.endFencedConfirmation(action, actions, { confirmed: true });
            closeModal();
            if (ended.status !== "ended") {
                setStatus("材料范围已变化，请重新读取原材料状态");
                return;
            }
            const scope = { account_id: ended.proof.account_id, trade_id: ended.proof.trade_id };
            renderViewModel({ kind: "message", title: "旧材料确认已结束", status: "历史入账状态仍待核对",
                outcome: "noop", business_summary: "仅结束旧确认；不能据此认定历史未入账。",
                message: "没有自动发起新材料或入账操作。请核对原回执，或重新准备并确认新材料。",
                blocking_reason: "新材料仍由账户全部材料状态和当前策略核对决定。",
                next_steps: [
                    { label: "核对原材料回执", action_key: "simulated-trading.fee-correction-recover",
                        params: { ...scope, source_locator: ended.proof.source_locator } },
                    { label: "准备新的材料预览", action_key: "simulated-trading.fee-correction-preview", params: scope },
                ] });
            renderInspector({ title: "旧确认已结束，历史仍待核对", rows: [],
                body: "较新策略使旧确认失效，不代表历史从未入账。" });
        });
    });
    els.main.appendChild(button);
}
