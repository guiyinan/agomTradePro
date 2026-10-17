/*
 * TUX-08 task-entry and passive-read retry helpers.  Action identity, field
 * metadata, and continuation policy always come from the current server
 * screen; this segment contains no business action or screen keys.
 */

function continuationFieldsForAction(action) {
    if (typeof resultContinuations === "undefined"
        || typeof resultContinuations.continuationFields !== "function") {
        return new Set();
    }
    return resultContinuations.continuationFields(action, state.screen?.actions || []);
}

function passiveReadFieldSafe(field) {
    const inputType = String(field?.input_type || "").toLowerCase();
    const semantic = String(field?.presentation_semantic || "").toLowerCase();
    if (["password", "file", "hidden"].includes(inputType)
        || ["api_token", "endpoint_url", "secret", "copyable_secret"].includes(semantic)) {
        return false;
    }
    return typeof safeWorkspaceField !== "function" || safeWorkspaceField(field);
}

function passiveReadRequiredFields(action) {
    const requiredFields = (action?.fields || []).filter((field) => field.required);
    const continuationFields = continuationFieldsForAction(action);
    if (!requiredFields.length || requiredFields.some((field) => (
        !passiveReadFieldSafe(field) || continuationFields.has(field.key)
    ))) {
        return null;
    }
    return requiredFields;
}

function passiveReadRetryParams(action, params) {
    if (!action || !isPassiveRead(action)) {
        return null;
    }
    const requiredFields = passiveReadRequiredFields(action);
    if (!requiredFields || typeof safeActionParams !== "function") {
        return null;
    }
    const safeParams = safeActionParams(action, params || {});
    if (!requiredFields.every((field) => (
        Object.prototype.hasOwnProperty.call(safeParams, field.key)
        && safeParams[field.key] !== null
        && safeParams[field.key] !== undefined
        && !(typeof safeParams[field.key] === "string" && !safeParams[field.key].trim())
        && !(typeof safeParams[field.key] === "number" && !Number.isFinite(safeParams[field.key]))
    ))) {
        return null;
    }
    return safeParams;
}

function passiveReadEntryAction(action) {
    const screen = state.screen?.screen || {};
    const entryState = screen.entry_state || {};
    const defaultActionKey = String(screen.default_action_key || "").trim();
    if (entryState.mode !== "parameter_gate"
        || !defaultActionKey
        || !action
        || !(action.key === defaultActionKey || action.ui_key === defaultActionKey)
        || !isPassiveRead(action)
        || !passiveReadRequiredFields(action)) {
        return null;
    }
    return action;
}

function appendPassiveReadEntry(action, params = {}) {
    const entryAction = passiveReadEntryAction(action);
    if (!entryAction || !els.main || typeof renderActionForm !== "function") {
        return false;
    }
    const safeParams = typeof safeActionParams === "function"
        ? safeActionParams(entryAction, params || {})
        : {};
    let host = els.main.querySelector("[data-research-again-entry]");
    if (!host) {
        host = document.createElement("details");
        host.className = "tui-research-entry";
        host.dataset.researchAgainEntry = "true";
        host.innerHTML = `
            <summary class="tui-research-entry-title">研究其他标的</summary>
            ${renderActionForm(entryAction, { entry: true, idNamespace: "result" })}
        `;
        els.main.append(host);
        bindRenderedActionForms(host);
    }
    const form = host.querySelector(".tui-action-entry-form");
    (entryAction.fields || []).filter(passiveReadFieldSafe).forEach((field) => {
        if (!Object.prototype.hasOwnProperty.call(safeParams, field.key)) {
            return;
        }
        const input = formFieldElement(form, field.key);
        if (!input) {
            return;
        }
        if (field.input_type === "checkbox") {
            input.checked = safeParams[field.key] === true || safeParams[field.key] === "true";
        } else {
            input.value = safeParams[field.key];
        }
    });
    return true;
}
