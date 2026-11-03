    const pressureScenarioLookupKey = "approved_portfolio_pressure_scenarios";
    const pressureScenarioLookupEndpoint =
        "/api/simulated-trading/accounts/<int:account_id>/portfolio-risk/scenarios/";

    function pressureScenarioLookupContext(form) {
        const actionContainer = els.actions;
        if (
            !form
            || form.isConnected === false
            || (
                actionContainer
                && typeof actionContainer.contains === "function"
                && !actionContainer.contains(form)
            )
        ) {
            return { action: null, field: null, select: null, accountElement: null, accountId: "" };
        }
        const action = currentAction(actionRefFromForm(form));
        const field = (action?.fields || []).find(
            (candidate) => candidate.options_lookup === pressureScenarioLookupKey,
        );
        const select = field ? formFieldElement(form, field.key) : null;
        const accountElement = formFieldElement(form, "account_id");
        const rawAccountId = String(accountElement?.value || "").trim();
        const accountId = /^[1-9][0-9]*$/.test(rawAccountId)
            && Number.isSafeInteger(Number(rawAccountId))
            ? rawAccountId
            : "";
        return { action, field, select, accountElement, accountId };
    }

    function bindPressureScenarioForm(form) {
        const context = pressureScenarioLookupContext(form);
        if (!context.field || !context.select) return;
        context.accountElement?.addEventListener("change", () => {
            void loadPressureScenarioOptions(form, {
                preserveSelection: false,
                forceRefresh: true,
            });
        });
        form.querySelector(
            `[data-options-lookup-retry="${context.field.key}"]`,
        )?.addEventListener("click", () => {
            void loadPressureScenarioOptions(form, {
                preserveSelection: true,
                forceRefresh: true,
            });
        });
        void loadPressureScenarioOptions(form, {
            preserveSelection: false,
            forceRefresh: true,
        });
    }

    function replacePressureScenarioOptions(select, options, placeholder, selectedValue = "") {
        const placeholderOption = document.createElement("option");
        placeholderOption.value = "";
        placeholderOption.textContent = placeholder;
        const optionElements = options.map((option) => {
            const element = document.createElement("option");
            element.value = option.value;
            element.textContent = option.label;
            return element;
        });
        select.replaceChildren(placeholderOption, ...optionElements);
        if (selectedValue && options.some((option) => option.value === selectedValue)) {
            select.value = selectedValue;
        } else {
            select.value = "";
        }
    }

    async function loadPressureScenarioOptions(
        form,
        { preserveSelection = false, forceRefresh = false } = {},
    ) {
        const context = pressureScenarioLookupContext(form);
        const { field, select, accountId } = context;
        if (!field || !select) return { status: "not_configured", accountId: "" };
        const actionKey = context.action?.key || "";
        const fieldKey = context.field.key;

        const previousAccountId = String(select.dataset.optionsLookupAccountId || "");
        const previousSelection = preserveSelection && previousAccountId === accountId
            ? select.value
            : "";
        const generation = Number(select.dataset.optionsLookupGeneration || 0) + 1;
        select.dataset.optionsLookupGeneration = String(generation);
        select.dataset.optionsLookupAccountId = "";
        select.dataset.optionsLookupStatus = "loading";
        select.disabled = true;
        const statusNode = form.querySelector(
            '[data-options-lookup-status="scenario_version_id"]',
        );
        const retryButton = form.querySelector(
            '[data-options-lookup-retry="scenario_version_id"]',
        );
        if (retryButton) retryButton.hidden = true;
        if (!accountId) {
            replacePressureScenarioOptions(select, [], "先选择模拟账户");
            select.dataset.optionsLookupStatus = "missing_scope";
            if (statusNode) statusNode.textContent = "先选择模拟账户，再读取可用的已审批情景。";
            return { status: "missing_scope", accountId: "" };
        }

        replacePressureScenarioOptions(select, [], "正在读取已审批情景…");
        if (statusNode) statusNode.textContent = "正在读取当前账户可用的已审批情景。";
        try {
            const endpoint = pressureScenarioLookupEndpoint.replace(
                "<int:account_id>",
                accountId,
            );
            const payload = await fetchJson(endpoint, {
                cache: forceRefresh ? "no-store" : "no-cache",
            });
            const current = pressureScenarioLookupContext(form);
            const stillCurrent = Number(select.dataset.optionsLookupGeneration) === generation
                && current.action?.key === actionKey
                && current.field?.key === fieldKey
                && current.accountId === accountId;
            if (!stillCurrent) return { status: "stale", accountId };
            if (
                !payload
                || payload.scope !== "simulation_only"
                || payload.read_only !== true
                || payload.account_id !== Number(accountId)
                || !Array.isArray(payload.options)
            ) {
                throw new Error("目录格式无效");
            }
            const seenValues = new Set();
            const options = payload.options.map((option) => {
                if (
                    !option
                    || Object.keys(option).sort().join(",") !== "label,value"
                    || typeof option.value !== "string"
                    || !option.value
                    || option.value.trim() !== option.value
                    || option.value.length > 160
                    || typeof option.label !== "string"
                    || !option.label.trim()
                    || option.label.trim() !== option.label
                    || seenValues.has(option.value)
                ) {
                    throw new Error("目录选项无效");
                }
                seenValues.add(option.value);
                return { value: option.value, label: option.label };
            });
            replacePressureScenarioOptions(
                select,
                options,
                options.length ? "请选择一个已审批情景" : "当前没有可用的已审批情景",
                previousSelection,
            );
            select.dataset.optionsLookupAccountId = accountId;
            select.dataset.optionsLookupStatus = options.length ? "ready" : "empty";
            select.disabled = options.length === 0;
            if (retryButton) retryButton.hidden = options.length > 0;
            if (statusNode) {
                statusNode.textContent = options.length
                    ? "选择情景名称和业务版本后，才会提交对应的已审批版本。"
                    : "当前账户暂无可运行的已审批情景；请联系负责人完成配置与审批后重试。";
            }
            return { status: options.length ? "ready" : "empty", accountId };
        } catch (_error) {
            const current = pressureScenarioLookupContext(form);
            const stillCurrent = Number(select.dataset.optionsLookupGeneration) === generation
                && current.action?.key === actionKey
                && current.field?.key === fieldKey
                && current.accountId === accountId;
            if (!stillCurrent) return { status: "stale", accountId };
            replacePressureScenarioOptions(select, [], "暂时无法读取已审批情景");
            select.dataset.optionsLookupStatus = "unavailable";
            if (retryButton) retryButton.hidden = false;
            if (statusNode) statusNode.textContent = "暂时无法读取已审批情景，请稍后重试。";
            return { status: "unavailable", accountId };
        }
    }

    async function ensurePressureScenarioSelection(form, action) {
        const context = pressureScenarioLookupContext(form);
        if (
            !context.field
            || !context.select
            || !context.accountId
            || context.action?.key !== action.key
        ) {
            setStatus("请先选择模拟账户，再选择已审批压力情景。");
            return null;
        }
        const selectedValue = String(context.select.value || "");
        const selectionWasLoaded = context.select.dataset.optionsLookupStatus === "ready"
            && context.select.dataset.optionsLookupAccountId === context.accountId
            && selectedValue !== ""
            && Array.from(context.select.options).some((option) => option.value === selectedValue);
        if (!selectionWasLoaded) {
            setStatus("请读取并选择一个当前可用的已审批压力情景后继续。");
            return null;
        }
        const result = await loadPressureScenarioOptions(form, {
            preserveSelection: true,
            forceRefresh: true,
        });
        const current = pressureScenarioLookupContext(form);
        const refreshedSelection = String(current.select?.value || "");
        const selectedOptionIsPublished = Boolean(
            current.select
            && Array.from(current.select.options).some(
                (option) => option.value === refreshedSelection && refreshedSelection !== "",
            ),
        );
        if (
            result.status !== "ready"
            || result.accountId !== context.accountId
            || current.action?.key !== action.key
            || current.field?.key !== context.field.key
            || current.accountId !== context.accountId
            || current.select?.dataset.optionsLookupAccountId !== context.accountId
            || refreshedSelection !== selectedValue
            || !selectedOptionIsPublished
        ) {
            setStatus("请读取并选择一个当前可用的已审批压力情景后继续。");
            return null;
        }
        return { accountId: context.accountId, revisionId: selectedValue };
    }

    async function preparePressureScenarioAction(action, form) {
        const requiresSelection = (action.fields || []).some(
            (field) => field.options_lookup === pressureScenarioLookupKey,
        );
        if (!requiresSelection) return null;
        const selection = await ensurePressureScenarioSelection(form, action);
        return selection || false;
    }
