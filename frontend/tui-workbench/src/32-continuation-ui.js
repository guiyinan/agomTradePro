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
