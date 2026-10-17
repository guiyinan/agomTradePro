(function (root) {
    "use strict";

    const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
    const isRecord = value => value !== null && typeof value === "object" && !Array.isArray(value);
    const sameKeys = (value, keys) => isRecord(value)
        && Object.keys(value).sort().join("\u0000") === [...keys].sort().join("\u0000");

    function descriptorFor(action, actions) {
        if (!isRecord(action) || !hasOwn(action, "result_continuation")) {
            return { status: "none" };
        }
        const descriptor = action.result_continuation;
        if (!sameKeys(descriptor, ["target_action_key", "field_map"])) {
            return { status: "invalid" };
        }
        const targetActionKey = descriptor.target_action_key;
        const fieldMap = descriptor.field_map;
        if (typeof targetActionKey !== "string" || !targetActionKey.trim()
            || !isRecord(fieldMap) || !Object.keys(fieldMap).length) {
            return { status: "invalid" };
        }
        const target = actions.find(item => item?.key === targetActionKey);
        if (!target || target.screen_key !== action.screen_key || target.key === action.key
            || String(target.method || "GET").toUpperCase() === "GET"
            || target.session_auth_required !== true || target.confirmation_required !== true) {
            return { status: "invalid" };
        }
        const destinations = new Set();
        const targetFields = new Map((target.fields || []).map(field => [field.key, field]));
        for (const [inputKey, fieldKey] of Object.entries(fieldMap)) {
            const field = targetFields.get(fieldKey);
            if (typeof inputKey !== "string" || !inputKey.trim()
                || typeof fieldKey !== "string" || !fieldKey.trim()
                || destinations.has(fieldKey)
                || !field || field.input_type !== "hidden" || field.value_type !== "string"
                || field.required !== true || field.binding !== "body"
                || field.presentation_semantic !== "api_token"
                || (field.default !== undefined && field.default !== null && field.default !== "")) {
                return { status: "invalid" };
            }
            destinations.add(fieldKey);
        }
        return {
            status: "ready",
            sourceActionKey: action.key,
            targetActionKey,
            fieldMap: { ...fieldMap },
        };
    }

    function incomingForTarget(actions, targetActionKey) {
        const sources = [];
        for (const action of actions || []) {
            if (!hasOwn(action || {}, "result_continuation")) continue;
            const descriptor = descriptorFor(action, actions || []);
            if (descriptor.status === "invalid"
                && action.result_continuation?.target_action_key === targetActionKey) {
                return { status: "invalid" };
            }
            if (descriptor.status === "ready" && descriptor.targetActionKey === targetActionKey) {
                sources.push({ action, descriptor });
            }
        }
        if (sources.length > 1) return { status: "invalid" };
        if (!sources.length) return { status: "none" };
        return {
            status: "ready",
            sourceActionKey: sources[0].action.key,
            targetActionKey,
            fieldMap: sources[0].descriptor.fieldMap,
        };
    }

    function parseUtcExpiry(value) {
        if (typeof value !== "string" || !/(?:Z|\+00:00)$/.test(value)) return NaN;
        const parsed = Date.parse(value);
        return Number.isFinite(parsed) ? parsed : NaN;
    }

    function containsValue(value, expectedValues) {
        if (typeof value === "string") return expectedValues.has(value);
        if (Array.isArray(value)) return value.some(item => containsValue(item, expectedValues));
        if (isRecord(value)) return Object.values(value).some(item => containsValue(item, expectedValues));
        return false;
    }

    function createController() {
        const pending = new Map();
        const targetRequests = new Map();
        const sourceRequests = new Map();
        let sourceRequestSequence = 0;
        const storeKey = (screenKey, targetActionKey) => `${screenKey}\u0000${targetActionKey}`;

        function retainActionContext(action, actions) {
            if (!isRecord(action) || typeof action.screen_key !== "string" || !action.screen_key) {
                return false;
            }
            const availableActions = Array.isArray(actions) ? actions : [];
            const source = descriptorFor(action, availableActions);
            const incoming = incomingForTarget(availableActions, action.key);
            let retainedTargetActionKey = null;
            if (source.status === "ready" && incoming.status === "none") {
                retainedTargetActionKey = source.targetActionKey;
            } else if (source.status === "none" && incoming.status === "ready") {
                retainedTargetActionKey = action.key;
            }

            const prefix = `${action.screen_key}\u0000`;
            const retainedKey = retainedTargetActionKey
                ? storeKey(action.screen_key, retainedTargetActionKey)
                : null;
            for (const entries of [pending, sourceRequests, targetRequests]) {
                for (const key of entries.keys()) {
                    if (key.startsWith(prefix) && key !== retainedKey) entries.delete(key);
                }
            }
            return retainedTargetActionKey !== null;
        }

        function startSource(action, actions) {
            const descriptor = descriptorFor(action, actions || []);
            if (descriptor.status === "ready") {
                const key = storeKey(action.screen_key, descriptor.targetActionKey);
                pending.delete(key);
                targetRequests.delete(key);
                sourceRequestSequence += 1;
                sourceRequests.set(key, sourceRequestSequence);
                return { ...descriptor, requestToken: sourceRequestSequence };
            }
            return descriptor;
        }

        function acceptResult(action, actions, result, nowMs = Date.now(), requestToken) {
            const descriptor = descriptorFor(action, actions || []);
            const hasContinuation = isRecord(result) && hasOwn(result, "continuation");
            if (descriptor.status === "invalid") return { status: "invalid" };
            if (descriptor.status === "none") {
                return hasContinuation ? { status: "unexpected" } : { status: "none" };
            }
            const sourceKey = storeKey(action.screen_key, descriptor.targetActionKey);
            if (requestToken !== undefined) {
                if (sourceRequests.get(sourceKey) !== requestToken) return { status: "stale" };
                sourceRequests.delete(sourceKey);
            }
            if (!hasContinuation) {
                if (result?.confirmation_required || result?.password_challenge_required
                    || (Array.isArray(result?.missing_fields) && result.missing_fields.length)) {
                    return { status: "none" };
                }
                if (result?.outcome === "success"
                    && Number(result?.response?.status_code ?? 200) < 400) {
                    return { status: "missing" };
                }
                return { status: "none" };
            }

            const continuation = result.continuation;
            if (result?.outcome !== "success"
                || Number(result?.response?.status_code ?? 200) >= 400
                || result?.confirmation_required
                || !sameKeys(continuation, ["action_key", "input", "expires_at"])
                || continuation.action_key !== descriptor.targetActionKey
                || !isRecord(continuation.input)
                || !sameKeys(continuation.input, Object.keys(descriptor.fieldMap))) {
                return { status: "invalid" };
            }

            const expiresAtMs = parseUtcExpiry(continuation.expires_at);
            if (!Number.isFinite(expiresAtMs)) return { status: "invalid" };
            if (expiresAtMs <= nowMs) return { status: "expired" };
            const params = {};
            for (const [inputKey, fieldKey] of Object.entries(descriptor.fieldMap)) {
                const value = continuation.input[inputKey];
                if (typeof value !== "string" || !value) return { status: "invalid" };
                params[fieldKey] = value;
            }
            if (containsValue(result.view_model, new Set(Object.values(continuation.input)))
                || containsValue(result.debug, new Set(Object.values(continuation.input)))) {
                return { status: "leaked" };
            }

            pending.set(storeKey(action.screen_key, descriptor.targetActionKey), {
                sourceActionKey: action.key,
                targetActionKey: descriptor.targetActionKey,
                sourceRequestToken: requestToken,
                expiresAtMs,
                expiresAt: continuation.expires_at,
                params,
            });
            return {
                status: "stored",
                sourceActionKey: action.key,
                targetActionKey: descriptor.targetActionKey,
                expiresAt: continuation.expires_at,
            };
        }

        function cancelSource(action, actions, requestToken) {
            const descriptor = descriptorFor(action, actions || []);
            if (descriptor.status !== "ready") return false;
            const key = storeKey(action.screen_key, descriptor.targetActionKey);
            if (requestToken !== undefined && sourceRequests.get(key) !== requestToken) return false;
            sourceRequests.delete(key);
            pending.delete(key);
            targetRequests.delete(key);
            return true;
        }

        function sourceCancelHandler(action, actions) {
            const descriptor = descriptorFor(action, actions || []);
            if (descriptor.status !== "ready") return null;
            const key = storeKey(action.screen_key, descriptor.targetActionKey);
            const requestToken = sourceRequests.get(key);
            if (requestToken === undefined) return null;
            return () => cancelSource(action, actions, requestToken);
        }

        function targetParams(action, actions, baseParams = {}, nowMs = Date.now()) {
            const incoming = incomingForTarget(actions || [], action?.key);
            if (incoming.status !== "ready") return incoming;
            const key = storeKey(action.screen_key, action.key);
            const entry = pending.get(key);
            if (!entry) {
                return { status: "missing", sourceActionKey: incoming.sourceActionKey };
            }
            if (entry.expiresAtMs <= nowMs) {
                pending.delete(key);
                targetRequests.delete(key);
                return { status: "expired", sourceActionKey: entry.sourceActionKey };
            }
            return {
                status: "ready",
                sourceActionKey: entry.sourceActionKey,
                targetActionKey: entry.targetActionKey,
                sourceRequestToken: entry.sourceRequestToken,
                expiresAt: entry.expiresAt,
                params: { ...baseParams, ...entry.params },
            };
        }

        function consumeTarget(action, actions, baseParams = {}, nowMs = Date.now()) {
            const prepared = targetParams(action, actions, baseParams, nowMs);
            if (prepared.status === "ready") {
                const key = storeKey(action.screen_key, action.key);
                pending.delete(key);
                targetRequests.delete(key);
            }
            return prepared;
        }

        function rememberTargetRequest(action, actions, request, nowMs = Date.now()) {
            const incoming = incomingForTarget(actions || [], action?.key);
            if (incoming.status !== "ready" || !isRecord(request) || !isRecord(request.params)
                || typeof request.idempotencyKey !== "string" || !request.idempotencyKey
                || typeof request.confirmed !== "boolean") {
                return { status: "invalid" };
            }
            const expiresAtMs = parseUtcExpiry(request.expiresAt);
            if (!Number.isFinite(expiresAtMs)) return { status: "invalid" };
            if (expiresAtMs <= nowMs) return { status: "expired" };
            const continuationFields = Object.values(incoming.fieldMap);
            if (continuationFields.some(fieldKey =>
                typeof request.params[fieldKey] !== "string" || !request.params[fieldKey])) {
                return { status: "invalid" };
            }
            if (request.confirmed && (!isRecord(request.confirmation)
                || request.confirmation.confirmed !== true
                || typeof request.confirmation.confirmed_at !== "string"
                || typeof request.confirmation.message !== "string")) {
                return { status: "invalid" };
            }
            targetRequests.set(storeKey(action.screen_key, action.key), {
                sourceActionKey: incoming.sourceActionKey,
                targetActionKey: action.key,
                expiresAtMs,
                expiresAt: request.expiresAt,
                params: { ...request.params },
                idempotencyKey: request.idempotencyKey,
                confirmed: request.confirmed,
                confirmation: request.confirmation ? { ...request.confirmation } : null,
            });
            return { status: "stored" };
        }

        function targetRequestForRetry(action, actions, nowMs = Date.now()) {
            const incoming = incomingForTarget(actions || [], action?.key);
            if (incoming.status !== "ready") return incoming;
            const key = storeKey(action.screen_key, action.key);
            const entry = targetRequests.get(key);
            if (!entry) return { status: "missing", sourceActionKey: incoming.sourceActionKey };
            if (entry.expiresAtMs <= nowMs) {
                targetRequests.delete(key);
                return { status: "expired", sourceActionKey: entry.sourceActionKey };
            }
            return {
                status: "ready",
                sourceActionKey: entry.sourceActionKey,
                targetActionKey: entry.targetActionKey,
                expiresAt: entry.expiresAt,
                params: { ...entry.params },
                idempotencyKey: entry.idempotencyKey,
                confirmed: entry.confirmed,
                confirmation: entry.confirmation ? { ...entry.confirmation } : null,
            };
        }

        function clearTargetRequest(action) {
            if (!isRecord(action) || typeof action.screen_key !== "string"
                || typeof action.key !== "string") return false;
            return targetRequests.delete(storeKey(action.screen_key, action.key));
        }

        function cancelTargetConfirmation(action, actions, params = {}, nowMs = Date.now()) {
            const incoming = incomingForTarget(actions || [], action?.key);
            if (incoming.status !== "ready") return incoming;
            const key = storeKey(action.screen_key, action.key);
            const entry = pending.get(key);
            if (!entry) {
                return { status: "missing", sourceActionKey: incoming.sourceActionKey };
            }
            if (entry.expiresAtMs <= nowMs) {
                pending.delete(key);
                targetRequests.delete(key);
                return { status: "expired", sourceActionKey: entry.sourceActionKey };
            }
            const continuationFields = Object.values(incoming.fieldMap);
            if (continuationFields.some(fieldKey => params?.[fieldKey] !== entry.params[fieldKey])) {
                return { status: "stale", sourceActionKey: entry.sourceActionKey };
            }
            pending.delete(key);
            targetRequests.delete(key);
            if (entry.sourceRequestToken !== undefined
                && sourceRequests.get(key) === entry.sourceRequestToken) {
                sourceRequests.delete(key);
            }
            return { status: "cancelled", sourceActionKey: entry.sourceActionKey };
        }

        function continuationFields(action, actions) {
            const incoming = incomingForTarget(actions || [], action?.key);
            return incoming.status === "ready" ? new Set(Object.values(incoming.fieldMap)) : new Set();
        }

        function safeUiParams(action, params, actions) {
            const continuationKeys = continuationFields(action, actions);
            const hiddenKeys = new Set((action?.fields || [])
                .filter(field => field?.input_type === "hidden")
                .map(field => field.key));
            return Object.fromEntries(Object.entries(params || {})
                .filter(([key]) => !continuationKeys.has(key) && !hiddenKeys.has(key)));
        }

        function clearScreen(screenKey) {
            for (const [key] of pending) {
                if (key.startsWith(`${screenKey}\u0000`)) pending.delete(key);
            }
            for (const [key] of sourceRequests) {
                if (key.startsWith(`${screenKey}\u0000`)) sourceRequests.delete(key);
            }
            for (const [key] of targetRequests) {
                if (key.startsWith(`${screenKey}\u0000`)) targetRequests.delete(key);
            }
        }

        return Object.freeze({
            acceptResult,
            cancelSource,
            cancelTargetConfirmation,
            clearScreen,
            consumeTarget,
            continuationFields,
            clearTargetRequest,
            incomingForTarget: (actions, targetActionKey) => incomingForTarget(actions, targetActionKey),
            retainActionContext,
            safeUiParams,
            startSource,
            sourceCancelHandler,
            rememberTargetRequest,
            targetRequestForRetry,
            targetParams,
        });
    }

    root.AgomTUIResultContinuations = Object.freeze({ createController });
})(typeof globalThis !== "undefined" ? globalThis : window);
