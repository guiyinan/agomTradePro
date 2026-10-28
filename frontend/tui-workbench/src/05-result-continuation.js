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
        const allowedDescriptorKeys = [
            "target_action_key",
            "field_map",
            "reuse_source_idempotency_key",
            "readback_action_key",
            "readback_scope_map",
        ];
        if (!isRecord(descriptor)
            || !["target_action_key", "field_map"].every(key => hasOwn(descriptor, key))
            || Object.keys(descriptor).some(key => !allowedDescriptorKeys.includes(key))) {
            return { status: "invalid" };
        }
        const reuseSourceIdempotencyKey = descriptor.reuse_source_idempotency_key === true;
        if ((hasOwn(descriptor, "reuse_source_idempotency_key")
            && descriptor.reuse_source_idempotency_key !== true)
            || (hasOwn(descriptor, "readback_action_key")
                && (typeof descriptor.readback_action_key !== "string"
                    || !descriptor.readback_action_key.trim()))
            || (hasOwn(descriptor, "readback_action_key") && !reuseSourceIdempotencyKey)) {
            return { status: "invalid" };
        }
        const targetActionKey = descriptor.target_action_key;
        const fieldMap = descriptor.field_map;
        const scopeMap = descriptor.readback_scope_map || {};
        if (hasOwn(descriptor, "readback_scope_map") && (
            action.key !== "simulated-trading.fee-correction-preview"
            || !hasOwn(descriptor, "readback_action_key")
            || !sameKeys(scopeMap, ["source_locator"])
            || scopeMap.source_locator !== "preview.source_locator")) return { status: "invalid" };
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
        let readbackAction = null;
        let readbackPathFields = [];
        if (hasOwn(descriptor, "readback_action_key")) {
            readbackAction = actions.find(item => item?.key === descriptor.readback_action_key);
            const readbackFieldList = readbackAction?.fields || [];
            readbackPathFields = readbackFieldList
                .filter(isRecord)
                .map(field => field.key);
            const readbackFields = new Map(readbackFieldList
                .filter(isRecord)
                .map(field => [field.key, field]));
            if (!reuseSourceIdempotencyKey
                || String(action.method || "GET").toUpperCase() !== "POST"
                || !readbackAction
                || readbackAction.key === action.key
                || readbackAction.key === target.key
                || readbackAction.screen_key !== action.screen_key
                || String(readbackAction.method || "GET").toUpperCase() !== "GET"
                || readbackAction.risk !== "read"
                || (readbackAction.effect || "read") !== "read"
                || readbackAction.session_auth_required !== true
                || readbackAction.confirmation_required === true
                || String(readbackAction.audience || "authenticated")
                    !== String(action.audience || "authenticated")
                || !readbackPathFields.length
                || new Set(readbackPathFields).size !== readbackPathFields.length
                || readbackPathFields.some(fieldKey => !Object.values(fieldMap).includes(fieldKey)
                    && !Object.keys(scopeMap).includes(fieldKey))
                || Object.keys(scopeMap).some(fieldKey => !readbackPathFields.includes(fieldKey)
                    || Object.values(fieldMap).includes(fieldKey))
                || readbackFields.size !== readbackFieldList.length
                || readbackPathFields.some(fieldKey => {
                    const field = readbackFields.get(fieldKey);
                    return !field || field.input_type !== "hidden" || field.value_type !== "string"
                        || field.required !== true || field.binding !== "body"
                        || field.presentation_semantic !== "api_token"
                        || (field.default !== undefined && field.default !== null && field.default !== "");
                })) {
                return { status: "invalid" };
            }
        }
        const destinations = new Set();
        const targetFields = new Map((target.fields || []).map(field => [field.key, field]));
        const optionalBrokerPreviewContext = action.key === "audit.manual-trade-import-preview"
            && targetActionKey === "audit.manual-trade-import"
            && sameKeys(fieldMap, [
                "expected_fact_set_fingerprint",
                "expected_balance_fingerprint",
            ])
            && fieldMap.expected_fact_set_fingerprint === "expected_fact_set_fingerprint"
            && fieldMap.expected_balance_fingerprint === "expected_balance_fingerprint";
        for (const [inputKey, fieldKey] of Object.entries(fieldMap)) {
            const field = targetFields.get(fieldKey);
            if (typeof inputKey !== "string" || !inputKey.trim()
                || typeof fieldKey !== "string" || !fieldKey.trim()
                || destinations.has(fieldKey)
                || !field || field.input_type !== "hidden" || field.value_type !== "string"
                || field.required !== !optionalBrokerPreviewContext || field.binding !== "body"
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
            reuseSourceIdempotencyKey,
            readbackActionKey: readbackAction?.key || null,
            readbackPathFields,
            readbackScopeFields: Object.keys(scopeMap),
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
            reuseSourceIdempotencyKey: sources[0].descriptor.reuseSourceIdempotencyKey,
            readbackActionKey: sources[0].descriptor.readbackActionKey,
            readbackPathFields: sources[0].descriptor.readbackPathFields,
            readbackScopeFields: sources[0].descriptor.readbackScopeFields,
        };
    }

    function incomingForReadback(actions, readbackActionKey) {
        const sources = [];
        for (const action of actions || []) {
            if (!hasOwn(action || {}, "result_continuation")) continue;
            const descriptor = descriptorFor(action, actions || []);
            if (descriptor.status === "invalid"
                && action.result_continuation?.readback_action_key === readbackActionKey) {
                return { status: "invalid" };
            }
            if (descriptor.status === "ready"
                && descriptor.readbackActionKey === readbackActionKey) {
                sources.push({ action, descriptor });
            }
        }
        if (sources.length > 1) return { status: "invalid" };
        if (!sources.length) return { status: "none" };
        return {
            status: "ready",
            sourceActionKey: sources[0].action.key,
            targetActionKey: sources[0].descriptor.targetActionKey,
            readbackActionKey,
            readbackPathFields: [...sources[0].descriptor.readbackPathFields],
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
        const activeScopes = new Map();
        const fencedAcknowledgements = new Map();

        function offerFencedResolution(action, actions, result) {
            const prefix = `${action?.screen_key}\u0000`;
            for (const key of fencedAcknowledgements.keys()) {
                if (key.startsWith(prefix)) fencedAcknowledgements.delete(key);
            }
            if (action?.key !== "simulated-trading.fee-correction-discover"
                || action.method !== "GET" || action.risk !== "read"
                || action.session_auth_required !== true || result?.outcome !== "success"
                || Number(result?.response?.status_code) !== 200
                || !Array.isArray(result.fee_recovery) || result.fee_recovery.length > 100) {
                return { status: "missing" };
            }
            const active = activeScopes.get(action.screen_key);
            if (!active) return { status: "missing" };
            for (const source of actions || []) {
                const descriptor = descriptorFor(source, actions || []);
                if (source.screen_key !== action.screen_key
                    || !descriptor.readbackScopeFields?.includes("source_locator")) continue;
                const key = storeKey(action.screen_key, descriptor.targetActionKey);
                const entry = targetRequests.get(key);
                if (!entry?.unknown || entry.confirmationEnded === true) continue;
                const candidates = result.fee_recovery.filter(proof => isRecord(proof)
                    && proof.state === "fenced"
                    && proof.reason_code === "FEE_CORRECTION_RECOVERY_POLICY_SUPERSEDED"
                    && Number.isSafeInteger(proof.binding_policy_version) && proof.binding_policy_version > 0
                    && Number.isSafeInteger(proof.current_policy_version)
                    && proof.current_policy_version > proof.binding_policy_version
                    && proof.source_locator === entry.readbackParams?.source_locator
                    && ["account_id", "trade_id"].every((field, index) => (
                        typeof proof[field] === "string" && /^[1-9][0-9]*$/.test(proof[field])
                        && proof[field] === entry.readbackParams?.[field] && proof[field] === active[index]
                    )));
                if (candidates.length !== 1) continue;
                const proof = { ...candidates[0] };
                fencedAcknowledgements.set(key, { entry, proof });
                return { status: "ready", proof: { ...proof } };
            }
            return { status: "missing" };
        }

        function endFencedConfirmation(action, actions, options = {}) {
            if (action?.key !== "simulated-trading.fee-correction-discover") return { status: "missing" };
            const active = activeScopes.get(action.screen_key);
            for (const [key, acknowledged] of fencedAcknowledgements) {
                if (!key.startsWith(`${action.screen_key}\u0000`)) continue;
                const { entry, proof } = acknowledged;
                if (!active || targetRequests.get(key) !== entry || entry.unknown !== true
                    || ["account_id", "trade_id"].some((field, index) => proof[field] !== active[index])) {
                    fencedAcknowledgements.delete(key);
                    return { status: "missing" };
                }
                if (options.confirmed !== true) return { status: "confirmation_required" };
                fencedAcknowledgements.delete(key);
                entry.confirmationEnded = true;
                pending.delete(key);
                sourceRequests.delete(key);
                return { status: "ended", proof: { ...proof }, receiptState: "unknown" };
            }
            return { status: "missing" };
        }

        function setActiveScope(action, actions, params) {
            const source = (actions || []).find(candidate => candidate?.screen_key === action?.screen_key
                && descriptorFor(candidate, actions || []).readbackScopeFields?.length);
            if (!source || !isRecord(params)) return false;
            const scope = ["account_id", "trade_id"].map(key => String(params[key] ?? ""));
            const previous = activeScopes.get(action.screen_key);
            activeScopes.set(action.screen_key, scope);
            if (!previous || previous.every((value, index) => value === scope[index])) return false;
            clearScreen(action.screen_key);
            return true;
        }
        let sourceRequestSequence = 0;
        const storeKey = (screenKey, targetActionKey) => `${screenKey}\u0000${targetActionKey}`;

        function retainUnknownTargetRequest(key, request) {
            if (!request || request.unknown === true || request.confirmed !== true
                || request.dispatched !== true || request.reuseSourceIdempotencyKey !== true
                || !request.readbackActionKey || !isRecord(request.readbackParams)
                || !Object.keys(request.readbackParams).length) {
                return false;
            }
            request.unknown = true;
            request.params = { ...request.readbackParams };
            request.confirmation = null;
            request.confirmed = false;
            request.dispatched = false;
            pending.delete(key);
            targetRequests.set(key, request);
            return true;
        }

        function preserveDispatchedTargetRequests(screenKey) {
            if (typeof screenKey !== "string" || !screenKey) return false;
            const prefix = `${screenKey}\u0000`;
            let preserved = false;
            for (const [key, request] of targetRequests) {
                if (key.startsWith(prefix)) {
                    preserved = retainUnknownTargetRequest(key, request) || preserved;
                }
            }
            return preserved;
        }

        function retainActionContext(action, actions) {
            if (!isRecord(action) || typeof action.screen_key !== "string" || !action.screen_key) {
                return false;
            }
            const availableActions = Array.isArray(actions) ? actions : [];
            const source = descriptorFor(action, availableActions);
            const incoming = incomingForTarget(availableActions, action.key);
            const readback = incomingForReadback(availableActions, action.key);
            let retainedTargetActionKey = null;
            if (source.status === "ready" && incoming.status === "none") {
                retainedTargetActionKey = source.targetActionKey;
            } else if (source.status === "none" && incoming.status === "ready") {
                retainedTargetActionKey = action.key;
            } else if (source.status === "none" && readback.status === "ready") {
                retainedTargetActionKey = readback.targetActionKey;
            }

            const prefix = `${action.screen_key}\u0000`;
            preserveDispatchedTargetRequests(action.screen_key);
            const retainedKey = retainedTargetActionKey
                ? storeKey(action.screen_key, retainedTargetActionKey)
                : null;
            for (const entries of [pending, sourceRequests, targetRequests]) {
                for (const key of entries.keys()) {
                    if (!key.startsWith(prefix) || key === retainedKey) continue;
                    if (entries === targetRequests && entries.get(key)?.unknown === true) continue;
                    entries.delete(key);
                }
            }
            return retainedTargetActionKey !== null;
        }

        function startSource(action, actions) {
            const descriptor = descriptorFor(action, actions || []);
            if (descriptor.status === "ready") {
                preserveDispatchedTargetRequests(action.screen_key);
                const screenPrefix = `${action.screen_key}\u0000`;
                const unresolvedEntry = [...targetRequests.entries()].find(([key, request]) =>
                    key.startsWith(screenPrefix) && request?.unknown === true
                    && request.confirmationEnded !== true);
                if (unresolvedEntry) {
                    const priorRequest = unresolvedEntry[1];
                    return {
                        status: "readback_pending",
                        sourceActionKey: priorRequest.sourceActionKey,
                        targetActionKey: priorRequest.targetActionKey,
                        readbackActionKey: priorRequest.readbackActionKey,
                    };
                }
                const key = storeKey(action.screen_key, descriptor.targetActionKey);
                pending.delete(key);
                if (targetRequests.get(key)?.confirmationEnded !== true) targetRequests.delete(key);
                sourceRequestSequence += 1;
                sourceRequests.set(key, sourceRequestSequence);
                return { ...descriptor, requestToken: sourceRequestSequence };
            }
            return descriptor;
        }

        function acceptResult(
            action,
            actions,
            result,
            nowMs = Date.now(),
            requestToken,
            sourceIdempotencyKey,
        ) {
            const descriptor = descriptorFor(action, actions || []);
            const hasContinuation = isRecord(result) && hasOwn(result, "continuation");
            if (descriptor.status === "invalid") return { status: "invalid" };
            if (descriptor.status === "none") {
                return hasContinuation ? { status: "unexpected" } : { status: "none" };
            }
            if (descriptor.reuseSourceIdempotencyKey
                && (typeof sourceIdempotencyKey !== "string" || !sourceIdempotencyKey)) {
                return { status: "invalid" };
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
                    if (action.key === "audit.manual-trade-import-preview") {
                        return { status: "optional_missing" };
                    }
                    return { status: "missing" };
                }
                return { status: "none" };
            }

            const continuation = result.continuation;
            const scopeFields = descriptor.readbackScopeFields;
            const envelopeKeys = ["action_key", "input", "expires_at"];
            if (scopeFields.length) envelopeKeys.push("readback_scope");
            if (result?.outcome !== "success"
                || Number(result?.response?.status_code ?? 200) >= 400
                || result?.confirmation_required
                || !sameKeys(continuation, envelopeKeys)
                || continuation.action_key !== descriptor.targetActionKey
                || !isRecord(continuation.input)
                || !sameKeys(continuation.input, Object.keys(descriptor.fieldMap))) {
                return { status: "invalid" };
            }

            const expiresAtMs = parseUtcExpiry(continuation.expires_at);
            const publicScope = scopeFields.length ? continuation.readback_scope : {};
            if (!sameKeys(publicScope, scopeFields)
                || scopeFields.some(key => typeof publicScope[key] !== "string"
                    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(publicScope[key]))) {
                return { status: "invalid" };
            }
            if (!Number.isFinite(expiresAtMs)) return { status: "invalid" };
            if (expiresAtMs <= nowMs) return { status: "expired" };
            const params = {};
            for (const [inputKey, fieldKey] of Object.entries(descriptor.fieldMap)) {
                const value = continuation.input[inputKey];
                if (typeof value !== "string" || !value) return { status: "invalid" };
                params[fieldKey] = value;
            }
            const protectedValues = new Set(Object.entries(continuation.input)
                .filter(([inputKey]) => !descriptor.readbackPathFields.includes(descriptor.fieldMap[inputKey]))
                .map(([, value]) => value));
            if (containsValue(result.view_model, protectedValues)
                || containsValue(result.debug, protectedValues)) {
                return { status: "leaked" };
            }

            pending.set(storeKey(action.screen_key, descriptor.targetActionKey), {
                sourceActionKey: action.key,
                targetActionKey: descriptor.targetActionKey,
                sourceRequestToken: requestToken,
                expiresAtMs,
                expiresAt: continuation.expires_at,
                params,
                sourceIdempotencyKey: descriptor.reuseSourceIdempotencyKey
                    ? sourceIdempotencyKey
                    : null,
                reuseSourceIdempotencyKey: descriptor.reuseSourceIdempotencyKey,
                readbackActionKey: descriptor.readbackActionKey,
                readbackPathFields: [...descriptor.readbackPathFields],
                readbackScope: { ...publicScope },
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
                const priorRequest = targetRequests.get(key);
                if (priorRequest?.unknown !== true) targetRequests.delete(key);
                return { status: "expired", sourceActionKey: entry.sourceActionKey };
            }
            return {
                status: "ready",
                sourceActionKey: entry.sourceActionKey,
                targetActionKey: entry.targetActionKey,
                sourceRequestToken: entry.sourceRequestToken,
                expiresAt: entry.expiresAt,
                params: { ...baseParams, ...entry.params },
                idempotencyKey: entry.reuseSourceIdempotencyKey
                    ? entry.sourceIdempotencyKey
                    : null,
                reuseSourceIdempotencyKey: entry.reuseSourceIdempotencyKey,
                readbackActionKey: entry.readbackActionKey,
            };
        }

        function consumeTarget(action, actions, baseParams = {}, nowMs = Date.now()) {
            const prepared = targetParams(action, actions, baseParams, nowMs);
            if (prepared.status === "ready") {
                const key = storeKey(action.screen_key, action.key);
                const incoming = incomingForTarget(actions || [], action?.key);
                if (!incoming.reuseSourceIdempotencyKey) {
                    pending.delete(key);
                    targetRequests.delete(key);
                }
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
            const pendingEntry = pending.get(storeKey(action.screen_key, action.key));
            if (incoming.reuseSourceIdempotencyKey
                && (!pendingEntry
                    || request.idempotencyKey !== pendingEntry.sourceIdempotencyKey
                    || !request.idempotencyKey
                    || continuationFields.some(fieldKey =>
                        request.params[fieldKey] !== pendingEntry.params[fieldKey]))) {
                return { status: "invalid" };
            }
            const readbackParams = {};
            for (const fieldKey of incoming.readbackPathFields || []) {
                const value = incoming.readbackScopeFields.includes(fieldKey)
                    ? pendingEntry?.readbackScope?.[fieldKey]
                    : request.params[fieldKey];
                if (typeof value !== "string" || !value) return { status: "invalid" };
                readbackParams[fieldKey] = value;
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
                reuseSourceIdempotencyKey: incoming.reuseSourceIdempotencyKey,
                readbackActionKey: incoming.readbackActionKey,
                readbackParams,
                dispatched: false,
                unknown: false,
            });
            return { status: "stored" };
        }

        function markTargetRequestDispatched(action, actions, idempotencyKey) {
            const incoming = incomingForTarget(actions || [], action?.key);
            if (incoming.status !== "ready" || typeof idempotencyKey !== "string" || !idempotencyKey) {
                return false;
            }
            const entry = targetRequests.get(storeKey(action.screen_key, action.key));
            if (!entry || entry.unknown === true || entry.idempotencyKey !== idempotencyKey) return false;
            entry.dispatched = true;
            return true;
        }

        function markTargetRequestResponseReceived(action, actions, idempotencyKey) {
            const incoming = incomingForTarget(actions || [], action?.key);
            if (incoming.status !== "ready" || typeof idempotencyKey !== "string" || !idempotencyKey) {
                return false;
            }
            const entry = targetRequests.get(storeKey(action.screen_key, action.key));
            if (!entry || entry.idempotencyKey !== idempotencyKey) return false;
            entry.dispatched = false;
            return true;
        }

        function targetRequestForRetry(action, actions, nowMs = Date.now()) {
            const incoming = incomingForTarget(actions || [], action?.key);
            if (incoming.status !== "ready") return incoming;
            preserveDispatchedTargetRequests(action.screen_key);
            const key = storeKey(action.screen_key, action.key);
            const entry = targetRequests.get(key);
            if (!entry) return { status: "missing", sourceActionKey: incoming.sourceActionKey };
            if (entry.unknown === true) {
                return {
                    status: "unknown",
                    sourceActionKey: entry.sourceActionKey,
                    readbackActionKey: entry.readbackActionKey,
                };
            }
            if (entry.expiresAtMs <= nowMs) {
                targetRequests.delete(key);
                pending.delete(key);
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

        function markTargetUnknown(action, actions) {
            const incoming = incomingForTarget(actions || [], action?.key);
            if (incoming.status !== "ready" || !incoming.reuseSourceIdempotencyKey
                || !incoming.readbackActionKey) return false;
            const key = storeKey(action.screen_key, action.key);
            const entry = targetRequests.get(key);
            if (!entry || entry.confirmed !== true || entry.idempotencyKey === ""
                || entry.unknown === true) return false;
            const readbackParams = {};
            for (const fieldKey of incoming.readbackPathFields || []) {
                const value = entry.readbackParams?.[fieldKey] ?? entry.params[fieldKey];
                if (typeof value !== "string" || !value) return false;
                readbackParams[fieldKey] = value;
            }
            entry.unknown = true;
            entry.params = { ...readbackParams };
            entry.readbackParams = readbackParams;
            entry.confirmation = null;
            entry.confirmed = false;
            entry.dispatched = false;
            pending.delete(key);
            targetRequests.set(key, entry);
            return true;
        }

        function readbackRequestForAction(action, actions, nowMs = Date.now()) {
            const incoming = incomingForReadback(actions || [], action?.key);
            if (incoming.status !== "ready") return incoming;
            const entry = targetRequests.get(storeKey(action.screen_key, incoming.targetActionKey));
            if (!entry || entry.unknown !== true
                || entry.readbackActionKey !== action.key
                || !entry.reuseSourceIdempotencyKey
                || typeof entry.idempotencyKey !== "string"
                || !entry.idempotencyKey) {
                return { status: "missing", sourceActionKey: incoming.sourceActionKey };
            }
            const active = activeScopes.get(action.screen_key);
            if (active && ["account_id", "trade_id"].some((key, index) =>
                entry.readbackParams?.[key] !== active[index])) return { status: "scope_mismatch" };
            const params = {};
            for (const fieldKey of incoming.readbackPathFields) {
                const value = entry.readbackParams?.[fieldKey];
                if (typeof value !== "string" || !value) return { status: "invalid" };
                params[fieldKey] = value;
            }
            return {
                status: "ready",
                sourceActionKey: entry.sourceActionKey,
                targetActionKey: entry.targetActionKey,
                readbackActionKey: action.key,
                params,
                idempotencyKey: entry.idempotencyKey,
                expiresAt: entry.expiresAt,
                expired: entry.expiresAtMs <= nowMs,
            };
        }

        function resolveReadback(action, actions, result, idempotencyKey) {
            const incoming = incomingForReadback(actions || [], action?.key);
            if (incoming.status !== "ready" || result?.outcome !== "success"
                || Number(result?.response?.status_code ?? result?.status_code ?? 0) >= 400
                || result?.confirmation_required
                || result?.password_challenge_required
                || (Array.isArray(result?.missing_fields) && result.missing_fields.length)) {
                return false;
            }
            const key = storeKey(action.screen_key, incoming.targetActionKey);
            const entry = targetRequests.get(key);
            if (readbackRequestForAction(action, actions).status !== "ready") return false;
            if (!entry || entry.unknown !== true || entry.readbackActionKey !== action.key
                || typeof idempotencyKey !== "string"
                || idempotencyKey !== entry.idempotencyKey) {
                return false;
            }
            targetRequests.delete(key);
            if (pending.get(key)?.sourceIdempotencyKey === entry.idempotencyKey) {
                pending.delete(key);
                sourceRequests.delete(key);
            }
            return true;
        }

        function clearTargetRequest(action, { preservePending = false } = {}) {
            if (!isRecord(action) || typeof action.screen_key !== "string"
                || typeof action.key !== "string") return false;
            const key = storeKey(action.screen_key, action.key);
            const targetRequestCleared = targetRequests.delete(key);
            const pendingCleared = preservePending ? false : pending.delete(key);
            return targetRequestCleared || pendingCleared;
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
            preserveDispatchedTargetRequests(screenKey);
            for (const key of fencedAcknowledgements.keys()) {
                if (key.startsWith(`${screenKey}\u0000`)) fencedAcknowledgements.delete(key);
            }
            for (const [key] of pending) {
                if (key.startsWith(`${screenKey}\u0000`)) pending.delete(key);
            }
            for (const [key] of sourceRequests) {
                if (key.startsWith(`${screenKey}\u0000`)) sourceRequests.delete(key);
            }
            for (const [key] of targetRequests) {
                const request = targetRequests.get(key);
                if (key.startsWith(`${screenKey}\u0000`) && request?.unknown !== true) {
                    targetRequests.delete(key);
                }
            }
        }

        return Object.freeze({
            acceptResult,
            setActiveScope,
            offerFencedResolution,
            endFencedConfirmation,
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
            incomingForReadback: (actions, readbackActionKey) =>
                incomingForReadback(actions, readbackActionKey),
            markTargetUnknown,
            markTargetRequestDispatched,
            markTargetRequestResponseReceived,
            preserveDispatchedTargetRequests,
            readbackRequestForAction,
            resolveReadback,
        });
    }

    root.AgomTUIResultContinuations = Object.freeze({ createController });
})(typeof globalThis !== "undefined" ? globalThis : window);
