# TUI UI Mode

> Last updated: 2026-06-19

AgomTradePro supports two browser-local UI modes:

- `classic`: default existing interface.
- `tui`: PC Tools / DOS-style presentation overlay.

The TUI mode is a presentation layer only. It does not add routes, database state, or account-level preferences.

## Persistence Contract

- Cookie: `agom_ui_mode=classic|tui`, path `/`.
- Local storage: `agom:ui-mode=classic|tui`.
- Template context: `ui_mode`, `is_tui_mode`.
- CRT scan local storage: `agom:tui-scan-enabled=true|false`.

Invalid or missing UI mode values fall back to `classic`.

## Control Interface

The global shell renders a UI control next to the top navigation actions on both `base.html` and `base_auth.html`.

Controls:

- Main `UI` button enters TUI from Classic. In TUI it opens the control panel instead of returning to Classic.
- Dropdown panel exposes Classic/TUI mode buttons.
- `CRT 扫描刷新` toggles automatic content scan animation.
- `扫描刷新` forces one content-area CRT scan and enters TUI if needed.
- `重置扫描` re-enables CRT scanning and keeps the current UI mode.
- `退出 TUI` is the only built-in control that intentionally returns from TUI to Classic.

Keyboard:

- `Ctrl+U`: enter TUI from Classic; open the control panel when already in TUI.
- `F9`: reset CRT scan settings when currently in TUI mode, without leaving TUI.

## Frontend API

`static/js/tui-mode.js` exposes:

```javascript
window.AgomTuiMode = {
  applyMode,
  triggerScan,
  getCurrentMode,
  isScanEnabled,
  setScanEnabled
};
```

Automatic scan hooks are wired to initial render, HTMX `afterSwap`, refresh controls, and same-origin fetch completion. The scan effect is scoped to `.tui-scan-target` / `[data-tui-scan-target]`, normally `#mainContent`.
