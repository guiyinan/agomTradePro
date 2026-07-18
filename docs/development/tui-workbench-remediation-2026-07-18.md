# TUI Workbench Remediation Plan (2026-07-18)

## Current stage objective

Close the remaining TUI interaction defects identified in the July review, replace string-only confidence with behavior-level regression coverage, and split the monolithic workbench source into responsibility-owned source segments while preserving the published browser bundle contract.

## Completed

- Preserved client-side pager state and global row indexes across pages.
- Added monotonic request ordering and guarded both success and error rendering paths.
- Removed implicit reuse of parameters for unrelated actions and next steps.
- Prevented action filtering, support toggles, advanced toggles, and action completion updates from rebuilding form DOM.
- Added modal focus return, sensitive-body cleanup, and keyboard focus trapping.
- Made the Regime quadrant marker data-driven and hidden for unknown regimes.
- Changed governance badge refreshes to update badge hosts without rebuilding the module tree.
- Prevented automatic dashboard panel execution for required-field, write, admin, or non-read actions.
- Removed automatic selected-row form filling; row filling now requires an explicit user action.
- Added CSV formula protection and a 2 MB client text-file limit.
- Split the maintained browser source into six responsibility-owned segments and made `static/js/tui-workbench.js` a generated compatibility bundle.
- Added Node contract tests plus real Chromium interaction coverage for pagination, form preservation, stale requests, next-step parameters, dashboard safety, and modal focus.
- Moved field aliases, task tiers, submit labels, and workflow lanes into the backend metadata contract instead of inferring them from Chinese labels in the browser.
- Centralized optional browser persistence behind safe storage helpers and named the remaining interaction timing/layout constants.
- Removed the unused legacy `static/js/tui-mode.js` runtime to eliminate conflicting shortcuts and global fetch patching risk.
- Regenerated the runtime manifest and verified the generated bundle drift gate.

## Remaining

- None for the July review scope.

## Regression scope

- `npm run check:tui`
- `npm run test:tui-js`
- `node --check static/js/tui-workbench.js`
- `pytest tests/unit/test_tui_workbench.py -q`
- `pytest tests/unit/test_tui_ui_mode.py -q`
- `pytest tests/unit/test_terminal_agent_service.py -q`
- `pytest sdk/tests/test_sdk/test_client.py -q`
- Focused Playwright TUI interaction tests

## Verified results

- `npm run check:tui` — passed.
- `npm run test:tui-js` — 15 passed, including six real Chromium workbench scenarios.
- `node --check static/js/tui-workbench.js` and JSON parsing for schema/generated/published metadata — passed.
- `pytest tests/unit/test_tui_workbench.py -q` — 218 passed.
- `pytest tests/unit/test_tui_ui_mode.py -q` — 6 passed.
- `pytest tests/unit/test_terminal_agent_service.py -q` — 11 passed.
- `pytest sdk/tests/test_sdk/test_client.py -q` — 22 passed.

## Risks and rollback points

- Source segmentation must preserve declaration order because the compatibility bundle retains one shared closure.
- The generated bundle and manifest must be updated together; `npm run check:tui` is the authoritative drift gate.
- Metadata producers must continue publishing explicit `task_tier`, `submit_label`, field-alias, and workflow-lane values; validator defaults preserve legacy payload compatibility.
- No production deployment or VPS mutation is part of this stage.
