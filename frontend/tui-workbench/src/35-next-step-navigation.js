/*
 * This helper owns only a one-hop, tab-local handoff from a result next step
 * to another server-published screen/action.  It deliberately knows nothing
 * about business screen or action keys.  The host supplies the existing
 * loadScreen, currentAction, revealTaskWithParams, and runAction functions.
 */
function createNextStepNavigation(deps = {}) {
    let returnContext = null;
    let generation = 0;
    let pending = null;

    const reservedParamKeys = new Set([
        "confirmation",
        "reauth",
        "idempotency_key",
        "retry_id",
        "retry_token",
        "continuation",
        "continuation_id",
        "continuation_token",
        "run_id",
        "request_id",
        "screen",
        "action",
        "owner_result",
        "result",
        "credential",
        "credentials",
        "password",
        "secret",
        "api_token",
        "endpoint_url",
    ]);

    function text(value) {
        return String(value || "").trim();
    }

    function isSafeWorkspaceField(field) {
        const inputType = text(field?.input_type).toLowerCase();
        const semantic = text(field?.presentation_semantic).toLowerCase();
        return !["password", "file", "hidden"].includes(inputType)
            && !["api_token", "endpoint_url", "secret", "copyable_secret"].includes(semantic);
    }

    function actionForScreen(screenSpec, actionRef) {
        const normalizedRef = text(actionRef);
        if (!normalizedRef) {
            return null;
        }
        const screenKey = text(screenSpec?.screen?.key);
        if (!screenKey) {
            return null;
        }
        return (screenSpec?.actions || []).find((action) => (
            (action.key === normalizedRef || action.ui_key === normalizedRef)
            && (!text(action.screen_key) || text(action.screen_key) === screenKey)
        )) || null;
    }

    function continuationKeys(action, screenSpec) {
        if (typeof deps.continuationFields !== "function") {
            return new Set();
        }
        const supplied = deps.continuationFields(action, screenSpec?.actions || []);
        return supplied instanceof Set ? supplied : new Set(supplied || []);
    }

    function safeScalarParams(action, params, screenSpec) {
        if (!action || !params || typeof params !== "object" || Array.isArray(params)) {
            return {};
        }
        const allowed = new Set(
            (action.fields || [])
                .filter(isSafeWorkspaceField)
                .map((field) => text(field.key))
                .filter(Boolean),
        );
        const continuation = continuationKeys(action, screenSpec);
        return Object.fromEntries(Object.entries(params).filter(([key, value]) => (
            allowed.has(key)
            && !continuation.has(key)
            && !reservedParamKeys.has(text(key).toLowerCase())
            && (
                value === null
                || ["string", "boolean"].includes(typeof value)
                || (typeof value === "number" && Number.isFinite(value))
            )
        )));
    }

    function state() {
        return typeof deps.getState === "function" ? deps.getState() || {} : {};
    }

    function currentScreenKey() {
        const supplied = typeof deps.getCurrentScreenKey === "function"
            ? deps.getCurrentScreenKey()
            : state().screen?.screen?.key;
        return text(supplied);
    }

    function sourceContext() {
        const currentState = state();
        const screenSpec = currentState.screen || {};
        const screenKey = currentScreenKey();
        const actionRef = text(currentState.lastAction);
        const action = typeof deps.currentAction === "function"
            ? deps.currentAction(actionRef)
            : actionForScreen(screenSpec, actionRef);
        const passive = Boolean(action && typeof deps.isPassiveRead === "function" && deps.isPassiveRead(action));
        const actionKey = text(action?.key || actionRef);
        return {
            screenKey,
            screenLabel: text(
                typeof deps.screenLabel === "function"
                    ? deps.screenLabel(screenKey)
                    : screenSpec.screen?.label,
            ),
            actionKey,
            passive,
            params: passive ? safeScalarParams(action, currentState.lastParams, screenSpec) : {},
        };
    }

    function setStatus(message) {
        if (typeof deps.setStatus === "function") {
            deps.setStatus(message);
        }
    }

    function clearReturnControl() {
        if (typeof deps.clearReturnControl === "function") {
            deps.clearReturnControl();
        }
    }

    function invalidate() {
        generation += 1;
        pending = null;
        returnContext = null;
        clearReturnControl();
    }

    function navigationOptions(origin) {
        return {
            suppressAutoAction: true,
            skipRestoreAction: true,
            suppressHistory: true,
            navigationOrigin: origin,
        };
    }

    function actionForLoadedScreen(screenSpec, actionRef, expectedScreenKey) {
        const loadedScreenKey = text(screenSpec?.screen?.key);
        if (!loadedScreenKey || (expectedScreenKey && loadedScreenKey !== expectedScreenKey)) {
            return null;
        }
        return actionForScreen(screenSpec, actionRef);
    }

    function syncLocation(screenKey, actionKey, options = {}) {
        if (typeof deps.syncLocation === "function") {
            deps.syncLocation(screenKey, actionKey, options);
        }
    }

    function sourceRecoveryContext(source, targetScreenKey, targetActionKey, targetParams = {}) {
        return {
            sourceScreenKey: source.screenKey,
            sourceScreenLabel: source.screenLabel,
            sourceActionKey: source.actionKey,
            sourcePassiveRead: source.passive,
            sourceParams: source.params,
            targetScreenKey,
            targetActionKey,
            targetParams,
        };
    }

    function retainRecovery(context, message, status = "error") {
        returnContext = context.sourceScreenKey ? context : null;
        if (returnContext && typeof deps.renderReturnControl === "function") {
            deps.renderReturnControl(returnContext, returnToSource);
        }
        setStatus(message);
        return { status, context: returnContext };
    }

    function requiredSafeFieldsPresent(action, params) {
        return (action?.fields || [])
            .filter((field) => field.required)
            .every((field) => (
                isSafeWorkspaceField(field)
                && Object.prototype.hasOwnProperty.call(params, field.key)
                && params[field.key] !== null
                && params[field.key] !== undefined
                && !(typeof params[field.key] === "string" && !params[field.key].trim())
                && !(typeof params[field.key] === "number" && !Number.isFinite(params[field.key]))
            ));
    }

    async function open(step) {
        const targetScreenKey = text(step?.screen_key);
        const targetActionRef = text(step?.action_key);
        if (!targetScreenKey || !targetActionRef) {
            setStatus("下一步信息不完整，尚未跳转");
            return { status: "invalid" };
        }
        if (returnContext || pending) {
            setStatus("请先返回原任务，再进入下一项任务");
            return { status: "blocked" };
        }

        const source = sourceContext();
        const params = step.params && typeof step.params === "object" && !Array.isArray(step.params)
            ? step.params
            : {};
        const recovery = sourceRecoveryContext(source, targetScreenKey, targetActionRef);
        const token = ++generation;
        pending = { token, targetScreenKey };
        clearReturnControl();
        try {
            const screenSpec = await deps.loadScreen(targetScreenKey, navigationOptions("next-step"));
            if (token !== generation) {
                return { status: "stale" };
            }
            if (!screenSpec) {
                return retainRecovery(recovery, "下一步工作区暂不可用，可返回原任务");
            }
            const loadedKey = text(screenSpec.screen?.key);
            if (!loadedKey) {
                return retainRecovery(recovery, "下一步工作区缺少有效位置，可返回原任务");
            }
            if (loadedKey !== targetScreenKey) {
                setStatus("下一步工作区已变更，尚未继续");
                return { status: "stale" };
            }
            const targetAction = actionForLoadedScreen(screenSpec, targetActionRef, targetScreenKey);
            if (!targetAction) {
                return retainRecovery(recovery, "下一步任务当前不可用，可返回原任务", "forbidden");
            }
            const safeParams = safeScalarParams(targetAction, params, screenSpec);
            const context = sourceRecoveryContext(
                source,
                targetScreenKey,
                text(targetAction.key || targetActionRef),
                safeParams,
            );
            if (!requiredSafeFieldsPresent(targetAction, safeParams)) {
                return retainRecovery(context, "目标任务需要当前页面未提供的安全输入，可返回原任务", "unavailable");
            }
            const revealResult = typeof deps.revealTaskWithParams === "function"
                ? deps.revealTaskWithParams(targetAction, safeParams, { origin: "next-step" })
                : false;
            if (revealResult !== true) {
                return retainRecovery(context, "目标任务暂不可用，可返回原任务", "unavailable");
            }
            returnContext = context.sourceScreenKey ? context : null;
            syncLocation(targetScreenKey, context.targetActionKey, { origin: "next-step" });
            if (typeof deps.renderReturnControl === "function" && returnContext) {
                deps.renderReturnControl(returnContext, returnToSource);
            }
            return { status: "opened", context: returnContext, action: targetAction };
        } catch (error) {
            if (token === generation) {
                return retainRecovery(recovery, "下一步工作区暂不可用，可返回原任务");
            }
            return { status: token === generation ? "error" : "stale", error };
        } finally {
            if (pending?.token === token) {
                pending = null;
            }
        }
    }

    async function returnToSource() {
        const context = returnContext;
        if (!context) {
            setStatus("当前没有可返回的原任务");
            return { status: "none" };
        }
        // Keep the context until the source has actually loaded and either
        // refreshed or revealed successfully.  A failed source load must
        // leave the user a retryable path back to the original task.
        clearReturnControl();
        const token = ++generation;
        pending = { token, targetScreenKey: context.sourceScreenKey };
        if (!context.sourceScreenKey) {
            setStatus("原任务位置不可用");
            pending = null;
            return { status: "invalid" };
        }
        try {
            const screenSpec = await deps.loadScreen(
                context.sourceScreenKey,
                navigationOptions("next-step-return"),
            );
            if (token !== generation) {
                return { status: "stale" };
            }
            if (!screenSpec) {
                return retainRecovery(context, "原任务工作区暂不可用，可重试返回", "error");
            }
            const loadedKey = text(screenSpec.screen?.key);
            if (!loadedKey) {
                return retainRecovery(context, "原任务工作区缺少有效位置，可重试返回", "error");
            }
            if (loadedKey !== context.sourceScreenKey) {
                return retainRecovery(context, "原任务工作区已变更，可重试返回", "stale");
            }
            const sourceAction = context.sourceActionKey
                ? actionForLoadedScreen(screenSpec, context.sourceActionKey, context.sourceScreenKey)
                : null;
            if (!sourceAction) {
                syncLocation(context.sourceScreenKey, "", { origin: "next-step-return" });
                returnContext = null;
                clearReturnControl();
                setStatus("已返回原工作区；原任务当前不可用");
                return { status: "forbidden" };
            }
            const safeParams = safeScalarParams(sourceAction, context.sourceParams, screenSpec);
            const requiredSafeFields = requiredSafeFieldsPresent(sourceAction, safeParams);
            // Missing or sensitive inputs require a fresh form, never a replay.
            const canRefresh = context.sourcePassiveRead
                && typeof deps.isPassiveRead === "function"
                && deps.isPassiveRead(sourceAction)
                && requiredSafeFields
                && typeof deps.runAction === "function";
            if (canRefresh) {
                syncLocation(context.sourceScreenKey, text(sourceAction.key), { origin: "next-step-return" });
                deps.runAction(sourceAction.key, null, {
                    params: safeParams,
                    origin: "next-step-return",
                });
            } else {
                const revealResult = typeof deps.revealTaskWithParams === "function"
                    ? deps.revealTaskWithParams(sourceAction, safeParams, { origin: "next-step-return" })
                    : false;
                if (revealResult !== true) {
                    return retainRecovery(context, "原任务暂不可用，可重试返回", "unavailable");
                }
                syncLocation(context.sourceScreenKey, text(sourceAction.key), { origin: "next-step-return" });
            }
            returnContext = null;
            clearReturnControl();
            return { status: "returned", action: sourceAction, refreshed: canRefresh };
        } catch (error) {
            if (token === generation) {
                return retainRecovery(context, "原任务工作区暂不可用，可重试返回", "error");
            }
            return { status: token === generation ? "error" : "stale", error };
        } finally {
            if (pending?.token === token) {
                pending = null;
            }
        }
    }

    return {
        open,
        returnToSource,
        invalidate,
        safeScalarParams,
        currentContext: () => returnContext ? {
            ...returnContext,
            sourceParams: { ...returnContext.sourceParams },
            targetParams: { ...returnContext.targetParams },
        } : null,
    };
}
