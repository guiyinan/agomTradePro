    function userStorageKey(baseKey) {
        const userKey = String(els.app?.dataset.userKey || "anonymous")
            .trim()
            .replace(/[^a-zA-Z0-9_-]+/g, "_");
        return `${baseKey}:user:${userKey || "anonymous"}`;
    }

    function catalogExperience(catalog = state.catalog) {
        const experience = catalog?.experience;
        return experience && typeof experience === "object" ? experience : null;
    }

    function experienceModeDefinition(mode = state.experienceMode, catalog = state.catalog) {
        const experience = catalogExperience(catalog);
        if (!experience) {
            return null;
        }
        return (Array.isArray(experience.modes) ? experience.modes : [])
            .find((item) => String(item?.key || "") === String(mode || "")) || null;
    }

    function normalizeExperienceMode(mode, catalog = state.catalog) {
        const experience = catalogExperience(catalog);
        if (!experience) {
            return "professional";
        }
        const normalized = String(mode || "").trim();
        return experienceModeDefinition(normalized, catalog)
            ? normalized
            : String(experience.default_mode || "task") === "task" ? "task" : "professional";
    }

    function persistExperienceMode(mode) {
        safeStorageSet(
            "localStorage",
            userStorageKey(experienceModeStorageKey),
            normalizeExperienceMode(mode),
        );
    }

    function loadExperienceMode(catalog = state.catalog) {
        const experience = catalogExperience(catalog);
        state.experienceMode = experience
            ? normalizeExperienceMode(
                safeStorageGet("localStorage", userStorageKey(experienceModeStorageKey), ""),
                catalog,
            )
            : "professional";
        state.experienceModeInitialized = true;
        return state.experienceMode;
    }

    function experienceHomeScreenKey(catalog = state.catalog) {
        return String(catalogExperience(catalog)?.home_screen_key || "").trim();
    }

    function isExperienceHomeScreen(screenKey, catalog = state.catalog) {
        const homeKey = experienceHomeScreenKey(catalog);
        return Boolean(homeKey) && String(screenKey || "").trim() === homeKey;
    }

    function experienceEntries(mode = state.experienceMode, catalog = state.catalog) {
        const definition = experienceModeDefinition(mode, catalog);
        return Array.isArray(definition?.entries) ? definition.entries : [];
    }

    function experienceUtilities(catalog = state.catalog) {
        return Array.isArray(catalogExperience(catalog)?.utilities)
            ? catalogExperience(catalog).utilities
            : [];
    }

    function isExperienceNavigationEnabled(catalog = state.catalog) {
        return Boolean(catalogExperience(catalog));
    }

    function markExperienceHomeFresh(value) {
        state.experienceHomeFresh = Boolean(value);
    }

    function setRawDiagnosticAuthority(catalog = state.catalog) {
        const allowed = catalog?.diagnostics?.raw_response_allowed === true;
        if (state.rawResponseAllowed && !allowed) {
            state.lastRaw = null;
            state.rawResponseAvailable = false;
        }
        state.rawResponseAllowed = allowed;
        if (typeof updateRawDrawer === "function") {
            updateRawDrawer();
        }
        return state.rawResponseAllowed;
    }

    function rawResponseCanOpen() {
        return state.rawResponseAllowed && state.rawResponseAvailable && state.lastRaw !== null;
    }

    function isOperatorHomeScreen(screenKey) {
        if (catalogExperience()) {
            return isExperienceHomeScreen(screenKey);
        }
        if (typeof runtimeHooks.isOperatorHomeScreen === "function") {
            return Boolean(runtimeHooks.isOperatorHomeScreen(screenKey));
        }
        return false;
    }


    function experienceEntryScreen(entry) {
        return String(entry?.screen_key || "").trim();
    }

    function experienceTaskRailMarkup(catalog) {
        const entries = experienceEntries("task", catalog);
        const currentKey = String(state.screen?.screen?.key || "").trim();
        const currentInEntries = entries.some((entry) => experienceEntryScreen(entry) === currentKey);
        const currentScreen = currentKey && !currentInEntries && !isExperienceHomeScreen(currentKey, catalog)
            ? catalogScreen(currentKey, catalog)
            : null;
        const currentMarkup = currentScreen
            ? `
                <section class="tui-experience-current" aria-label="当前工作区">
                    <div class="tui-group-title">当前工作区</div>
                    <button class="tui-screen-button is-current" type="button" data-screen-key="${escapeHtml(currentScreen.key)}">
                        <span>${escapeHtml(currentScreen.label)}</span>
                        <small>已打开</small>
                    </button>
                </section>
            `
            : "";
        return `
            <section class="tui-experience-rail" aria-label="任务入口">
                <div class="tui-group-title">任务入口</div>
                ${entries.length ? entries.map((entry) => `
                    <button class="tui-experience-rail-entry" type="button" data-screen-key="${escapeHtml(experienceEntryScreen(entry))}">
                        <strong>${escapeHtml(entry.label)}</strong>
                        <small>${escapeHtml(entry.description)}</small>
                    </button>
                `).join("") : '<div class="tui-empty-state">当前没有可用任务。</div>'}
            </section>
            ${currentMarkup}
        `;
    }

    function catalogScreen(screenKey, catalog = state.catalog) {
        const normalizedKey = String(screenKey || "").trim();
        if (!normalizedKey) {
            return null;
        }
        for (const group of catalog?.groups || []) {
            for (const module of group.modules || []) {
                const screen = (module.screens || []).find((item) => item.key === normalizedKey);
                if (screen) {
                    return screen;
                }
            }
        }
        return null;
    }

    function renderExperienceControls() {
        const enabled = isExperienceNavigationEnabled();
        if (els.experienceControls) {
            els.experienceControls.hidden = !enabled;
        }
        els.experienceModeButtons.forEach((button) => {
            const active = enabled && button.dataset.experienceMode === state.experienceMode;
            button.hidden = !enabled;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-selected", active ? "true" : "false");
            button.setAttribute("tabindex", active ? "0" : "-1");
        });
        if (els.experienceHome) {
            const showHome = enabled && (!isExperienceHomeScreen(state.screen?.screen?.key) || !state.experienceHomeFresh);
            els.experienceHome.hidden = !showHome;
        }
        els.app?.toggleAttribute("data-experience-enabled", enabled);
        if (els.app) {
            els.app.dataset.activeExperienceMode = state.experienceMode;
        }
    }

    function selectExperienceMode(mode) {
        if (!isExperienceNavigationEnabled()) {
            return false;
        }
        const nextMode = normalizeExperienceMode(mode);
        if (nextMode === state.experienceMode) {
            renderExperienceControls();
            return false;
        }
        state.experienceMode = nextMode;
        persistExperienceMode(nextMode);
        renderExperienceControls();
        renderCatalog(state.catalog);
        refreshExperienceHomeCards();
        return true;
    }

    function bindExperienceHomeControls(root = els.main) {
        if (!root) {
            return;
        }
        root.querySelectorAll("[data-experience-entry]").forEach((button) => {
            button.addEventListener("click", () => {
                const target = String(button.dataset.experienceScreenKey || "").trim();
                if (!target) {
                    return;
                }
                loadScreen(target, { experienceEntry: true });
            });
        });
        root.querySelectorAll("[data-experience-utility]").forEach((button) => {
            button.addEventListener("click", () => {
                const kind = String(button.dataset.experienceKind || "").trim();
                const target = String(button.dataset.experienceScreenKey || "").trim();
                if (kind === "resume") {
                    resumeExperienceWorkspace();
                    return;
                }
                if (kind === "screen" && target) {
                    loadScreen(target, { experienceEntry: true });
                }
            });
        });
    }

    async function resumeExperienceWorkspace() {
        const target = String(state.lastNonHomeScreen || "").trim();
        if (!target) {
            setStatus("没有可恢复的最近工作区");
            return false;
        }
        const loaded = await loadScreen(target, { experienceEntry: true });
        if (loaded || !experienceHomeScreenKey()) {
            return Boolean(loaded);
        }
        const quietHome = state.experienceMode === "task";
        return Boolean(await loadScreen(experienceHomeScreenKey(), {
            replaceHistory: true,
            suppressHomeAutoLoad: quietHome,
        }));
    }

    function refreshExperienceHomeCards() {
        const home = els.main?.querySelector("[data-task-home]");
        if (!home) {
            return;
        }
        const replacement = document.createElement("template");
        replacement.innerHTML = renderHomeActionStrip();
        const nextHome = replacement.content.firstElementChild;
        if (nextHome) {
            home.replaceWith(nextHome);
            bindExperienceHomeControls(els.main);
        }
    }

    function syncExperienceHomeLocation(options = {}) {
        if (!window.history?.pushState) return;
        const url = new URL(window.location.href);
        if (!url.searchParams.has("screen") && !url.searchParams.has("action")) return;
        url.searchParams.delete("screen");
        url.searchParams.delete("action");
        const method = options.replace ? "replaceState" : "pushState";
        window.history[method]({ screenKey: experienceHomeScreenKey() }, "", url);
    }

    function loadRecoveryScreen(screenKey) {
        const quietHome = state.experienceMode === "task" && isExperienceHomeScreen(screenKey);
        return loadScreen(screenKey, { suppressHomeAutoLoad: quietHome });
    }
