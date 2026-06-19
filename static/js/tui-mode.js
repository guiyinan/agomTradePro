(function () {
    "use strict";

    var COOKIE_NAME = "agom_ui_mode";
    var STORAGE_KEY = "agom:ui-mode";
    var SCAN_STORAGE_KEY = "agom:tui-scan-enabled";
    var VALID_MODES = { classic: true, tui: true };
    var SCAN_DURATION_MS = 980;
    var scanEnabledMemory = true;

    function normalizeMode(value) {
        return VALID_MODES[value] ? value : "classic";
    }

    function readCookie(name) {
        var prefix = name + "=";
        return document.cookie.split(";").map(function (item) {
            return item.trim();
        }).filter(function (item) {
            return item.indexOf(prefix) === 0;
        }).map(function (item) {
            return decodeURIComponent(item.slice(prefix.length));
        })[0] || "";
    }

    function writeCookie(mode) {
        var maxAge = 60 * 60 * 24 * 365;
        document.cookie = COOKIE_NAME + "=" + encodeURIComponent(mode) + "; path=/; max-age=" + maxAge + "; SameSite=Lax";
    }

    function readStoredMode() {
        try {
            return normalizeMode(window.localStorage.getItem(STORAGE_KEY) || "");
        } catch (error) {
            return normalizeMode(readCookie(COOKIE_NAME));
        }
    }

    function writeStoredMode(mode) {
        try {
            window.localStorage.setItem(STORAGE_KEY, mode);
        } catch (error) {
            // Cookie persistence is enough when storage is unavailable.
        }
        writeCookie(mode);
    }

    function readScanEnabled() {
        try {
            var storedValue = window.localStorage.getItem(SCAN_STORAGE_KEY);
            if (storedValue === "false") {
                scanEnabledMemory = false;
                return false;
            }
            if (storedValue === "true") {
                scanEnabledMemory = true;
                return true;
            }
        } catch (error) {
            // Use the in-memory value when storage is unavailable.
        }
        return scanEnabledMemory;
    }

    function writeScanEnabled(enabled) {
        scanEnabledMemory = !!enabled;
        try {
            window.localStorage.setItem(SCAN_STORAGE_KEY, scanEnabledMemory ? "true" : "false");
        } catch (error) {
            // The in-memory checkbox state still applies for the current page.
        }
    }

    function getCurrentMode() {
        return normalizeMode(document.body.getAttribute("data-ui-mode") || readCookie(COOKIE_NAME));
    }

    function setPanelOpen(control, open) {
        if (!control) {
            return;
        }
        var panel = control.querySelector("[data-ui-mode-panel]");
        var button = control.querySelector("[data-ui-mode-panel-toggle]");
        if (!panel || !button) {
            return;
        }
        panel.hidden = !open;
        button.setAttribute("aria-expanded", open ? "true" : "false");
    }

    function closePanels(exceptControl) {
        document.querySelectorAll("[data-ui-mode-control]").forEach(function (control) {
            if (control !== exceptControl) {
                setPanelOpen(control, false);
            }
        });
    }

    function updatePanelControls(mode) {
        var isScanEnabled = readScanEnabled();
        document.body.setAttribute("data-tui-scan-enabled", isScanEnabled ? "true" : "false");

        document.querySelectorAll("[data-ui-mode-choice]").forEach(function (button) {
            var isActive = button.getAttribute("data-ui-mode-choice") === mode;
            button.setAttribute("aria-pressed", isActive ? "true" : "false");
        });

        document.querySelectorAll("[data-ui-mode-exit]").forEach(function (button) {
            button.setAttribute("aria-pressed", mode === "classic" ? "true" : "false");
        });

        document.querySelectorAll("[data-tui-scan-toggle]").forEach(function (input) {
            input.checked = isScanEnabled;
        });

        document.querySelectorAll("[data-ui-mode-panel-status]").forEach(function (status) {
            status.textContent = "MODE: " + mode.toUpperCase() + " / SCAN: " + (isScanEnabled ? "ON" : "OFF");
        });
    }

    function updateToggle(mode) {
        var isTui = mode === "tui";
        document.querySelectorAll("[data-ui-mode-toggle]").forEach(function (button) {
            var label = button.querySelector("[data-ui-mode-toggle-label]");
            button.setAttribute("aria-pressed", isTui ? "true" : "false");
            button.setAttribute("title", isTui ? "已在 TUI，打开控制面板" : "进入 TUI 界面");
            if (label) {
                label.textContent = isTui ? "TUI" : "Classic";
            }
        });
        document.querySelectorAll(".tui-status-strip").forEach(function (strip) {
            strip.setAttribute("data-active-ui-mode", mode);
        });
        updatePanelControls(mode);
    }

    function applyMode(mode, options) {
        var normalized = normalizeMode(mode);
        var shouldPersist = !options || options.persist !== false;
        document.body.setAttribute("data-ui-mode", normalized);
        document.documentElement.setAttribute("data-ui-mode", normalized);
        updateToggle(normalized);
        if (shouldPersist) {
            writeStoredMode(normalized);
        }
        if (normalized === "tui" && (!options || options.scan !== false)) {
            triggerScan(document.getElementById("mainContent"));
        }
    }

    function findScanTarget(node) {
        if (!node || node === document || node === window) {
            return document.getElementById("mainContent") || document.body;
        }
        if (node.classList && (node.classList.contains("tui-scan-target") || node.hasAttribute("data-tui-scan-target"))) {
            return node;
        }
        if (node.closest) {
            return node.closest(".tui-scan-target, [data-tui-scan-target]") || document.getElementById("mainContent") || document.body;
        }
        return document.getElementById("mainContent") || document.body;
    }

    function triggerScan(node, options) {
        if (getCurrentMode() !== "tui") {
            return;
        }
        if ((!options || options.force !== true) && !readScanEnabled()) {
            return;
        }
        var target = findScanTarget(node);
        if (!target || !target.classList) {
            return;
        }
        target.classList.remove("is-crt-refreshing");
        // Force a reflow so repeated refreshes restart the scan animation.
        void target.offsetWidth;
        target.classList.add("is-crt-refreshing");
        window.setTimeout(function () {
            target.classList.remove("is-crt-refreshing");
        }, SCAN_DURATION_MS);
    }

    function resetUiPreferences(control) {
        writeScanEnabled(true);
        applyMode(getCurrentMode(), { persist: true, scan: false });
        if (getCurrentMode() === "tui") {
            triggerScan(document.getElementById("mainContent"), { force: true });
        }
        setPanelOpen(control, true);
    }

    function exitTuiMode(control) {
        writeScanEnabled(true);
        applyMode("classic", { persist: true, scan: false });
        closePanels(control);
    }

    function bindToggles() {
        document.querySelectorAll("[data-ui-mode-toggle]").forEach(function (button) {
            button.addEventListener("click", function (event) {
                event.stopPropagation();
                if (getCurrentMode() === "tui") {
                    var control = button.closest("[data-ui-mode-control]");
                    closePanels(control);
                    setPanelOpen(control, true);
                    return;
                }
                applyMode("tui", { persist: true, scan: true });
            });
        });

        document.addEventListener("keydown", function (event) {
            var tagName = document.activeElement ? document.activeElement.tagName : "";
            var isTyping = tagName === "INPUT" || tagName === "TEXTAREA" || tagName === "SELECT";
            if (isTyping) {
                return;
            }
            if (event.ctrlKey && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "u") {
                event.preventDefault();
                if (getCurrentMode() === "tui") {
                    var firstControl = document.querySelector("[data-ui-mode-control]");
                    closePanels(firstControl);
                    setPanelOpen(firstControl, true);
                    return;
                }
                applyMode("tui", { persist: true, scan: true });
            }
            if (event.key === "F9" && getCurrentMode() === "tui") {
                event.preventDefault();
                resetUiPreferences(document.querySelector("[data-ui-mode-control]"));
            }
        });
    }

    function bindControlPanels() {
        document.querySelectorAll("[data-ui-mode-panel-toggle]").forEach(function (button) {
            button.addEventListener("click", function (event) {
                event.stopPropagation();
                var control = button.closest("[data-ui-mode-control]");
                var panel = control ? control.querySelector("[data-ui-mode-panel]") : null;
                var shouldOpen = !panel || panel.hidden;
                closePanels(control);
                setPanelOpen(control, shouldOpen);
            });
        });

        document.querySelectorAll("[data-ui-mode-panel]").forEach(function (panel) {
            panel.addEventListener("click", function (event) {
                event.stopPropagation();
            });
        });

        document.querySelectorAll("[data-ui-mode-choice]").forEach(function (button) {
            button.addEventListener("click", function () {
                applyMode(button.getAttribute("data-ui-mode-choice"), { persist: true, scan: true });
            });
        });

        document.querySelectorAll("[data-ui-mode-exit]").forEach(function (button) {
            button.addEventListener("click", function () {
                exitTuiMode(button.closest("[data-ui-mode-control]"));
            });
        });

        document.querySelectorAll("[data-tui-scan-toggle]").forEach(function (input) {
            input.addEventListener("change", function () {
                writeScanEnabled(!!input.checked);
                updatePanelControls(getCurrentMode());
            });
        });

        document.querySelectorAll("[data-tui-manual-scan]").forEach(function (button) {
            button.addEventListener("click", function () {
                if (getCurrentMode() !== "tui") {
                    applyMode("tui", { persist: true, scan: false });
                }
                triggerScan(document.getElementById("mainContent"), { force: true });
            });
        });

        document.querySelectorAll("[data-ui-mode-reset]").forEach(function (button) {
            button.addEventListener("click", function () {
                resetUiPreferences(button.closest("[data-ui-mode-control]"));
            });
        });

        document.addEventListener("click", function () {
            closePanels();
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                closePanels();
            }
        });
    }

    function bindRefreshHooks() {
        document.body.addEventListener("htmx:afterSwap", function (event) {
            triggerScan(event.detail && event.detail.target ? event.detail.target : document.getElementById("mainContent"));
        });

        document.addEventListener("click", function (event) {
            var refreshControl = event.target.closest(".refresh-btn, .mini-refresh-btn, [data-tui-refresh], [hx-get], [hx-post]");
            if (refreshControl) {
                window.setTimeout(function () {
                    triggerScan(refreshControl);
                }, 40);
            }
        });

        if (typeof window.fetch === "function" && !window.fetch.__agomTuiWrapped) {
            var nativeFetch = window.fetch.bind(window);
            var wrappedFetch = function () {
                return nativeFetch.apply(null, arguments).finally(function () {
                    window.setTimeout(function () {
                        triggerScan(document.getElementById("mainContent"));
                    }, 60);
                });
            };
            wrappedFetch.__agomTuiWrapped = true;
            window.fetch = wrappedFetch;
        }
    }

    function initialize() {
        var serverMode = normalizeMode(document.body.getAttribute("data-ui-mode") || "");
        var cookieMode = normalizeMode(readCookie(COOKIE_NAME));
        var storedMode = readStoredMode();
        var mode = storedMode !== "classic" ? storedMode : (cookieMode !== "classic" ? cookieMode : serverMode);
        applyMode(mode, { persist: mode !== serverMode, scan: false });
        bindToggles();
        bindControlPanels();
        bindRefreshHooks();
        window.AgomTuiMode = {
            applyMode: applyMode,
            triggerScan: triggerScan,
            getCurrentMode: getCurrentMode,
            isScanEnabled: readScanEnabled,
            setScanEnabled: function (enabled) {
                writeScanEnabled(!!enabled);
                updatePanelControls(getCurrentMode());
            }
        };
        window.requestAnimationFrame(function () {
            triggerScan(document.getElementById("mainContent"));
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
