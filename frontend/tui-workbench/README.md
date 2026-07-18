# TUI Workbench browser source

The browser workbench is maintained in responsibility-owned source segments under `src/` and compiled by `npm run build:tui` into the compatibility bundle at `static/js/tui-workbench.js`.

Source ownership:

- `00-runtime.js`: shared state, persistence, request coordination, errors, and runtime integration.
- `10-navigation.js`: catalog, screen entry, user-experience metadata, and workflow navigation.
- `20-dashboard.js`: dashboard layout, panels, semantic detail rendering, and panel actions.
- `30-actions.js`: action grouping, forms, row parameter mapping, action execution, and dashboard result coordination.
- `40-views.js`: view-model rendering, grids, charts, inspectors, pagination, and export-ready data handling.
- `50-shell.js`: modal flows, shell commands, focus/resize behavior, keyboard controls, and bootstrap.

Do not edit the generated static bundle directly. Update the owning source segment, run the focused tests, then run `npm run build:tui` and `npm run check:tui`.

The segments intentionally share one generated closure to preserve the existing browser contract while keeping each maintained source file bounded. Declaration order is therefore part of the build contract and is defined in `scripts/build-tui-runtime.mjs`.

Business presentation rules are supplied by validated backend metadata. In particular, source segments must not infer task tiers, submit labels, field aliases, or workflow lanes from translated labels or key prefixes.
