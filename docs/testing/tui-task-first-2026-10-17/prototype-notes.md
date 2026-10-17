# TUI task-first static interaction prototype

This is an archived synthetic interaction prototype for the TUX-06/TUX-07 review, initially built in `.tmp/`. It does not modify the production TUI, generated bundles, metadata, or business data. The parent independently checked desktop/mobile modes, evidence return, keyboard switching, page errors and zero external requests; see prototype-review.json. Screenshots illustrate structure, not the final production theme or business acceptance.

## Open it

Open [`prototype.html`](./prototype.html) directly in a browser. No package install, local server, database, browser extension, or network access is required.

The inline script is intentionally limited to local DOM state. It does not call `fetch`, XHR, an AI service, or a write endpoint.

## What to inspect

- **任务模式** is the default view. It has three clear cards, a resume path, and an explicit unavailable capability state.
- **专业模式** is an index over existing workspaces represented with 交互示例 labels. It is a second work mode, not a permission boundary.
- **证据层** opens as a reversible drawer from task cards and professional entries. Every value is marked as an interaction example, and the limitation box states when a data source or capability is unavailable.
- **工具与诊断** is a separate, locked entry. It is not a third work mode and does not expose raw responses in this prototype.
- `1` / `2` switch modes, `F2` folds the rail, `F6` opens the resume evidence layer, and `Esc` returns from the evidence layer.

## Minimal TUX-07 production contract

The prototype intentionally leaves production untouched. The smallest future contract should extend the server metadata projection rather than add a client business map.

### 1. Server projection

Add a top-level `experience_modes` block to the TUI metadata schema and normalized IA payload. It should contain only `task` and `professional` modes. Each entry should be typed and reference an existing canonical `screen_key`, with an optional existing `action_key`, user-facing label/summary, and the server-side audience/capability requirement. Add a separate `diagnostic_tools` collection for tools that require explicit authorization.

Candidate ownership:

- `config/tui/schema/tui_metadata.schema.v3.json`: schema for `experience_modes`, mode entries, and `diagnostic_tools`.
- `config/tui/ia/tui_information_architecture.v1.json`: canonical source entries and references.
- `apps/terminal/infrastructure/tui_information_architecture.py`: validate mode keys, canonical screen/action references, and diagnostic journey metadata.
- `apps/terminal/application/tui_metadata.py` and `tui_metadata_constants.py`: bounded allowed values and typed normalization.
- `apps/terminal/application/tui_workbench_catalog.py`: filter entries using the same visible screen/action policy as the catalog; never emit a target the caller cannot load.
- `apps/terminal/application/tui_workbench.py`: include the filtered projection in `get_catalog()` and bootstrap.

A small pure application helper is preferable to spreading policy across the shell:

```python
project_tui_experience(
    metadata: TuiMetadata,
    *,
    visible_screen_keys: frozenset[str],
    visible_action_keys: frozenset[str],
    diagnostic_authorized: bool,
) -> TuiExperienceProjection
```

The helper should return frozen typed records such as `TuiExperienceMode`, `TuiExperienceEntry`, and `TuiDiagnosticTool`; it should have no ORM, request, infrastructure, or frontend dependency. The caller supplies already-authorized sets from the existing catalog path. This prevents an Application module from importing `apps.terminal.infrastructure` and keeps authorization server-side.

### 2. Frontend behavior

Use the returned projection in:

- `frontend/tui-workbench/src/00-runtime.js` for a user-namespaced mode preference only.
- `10-navigation.js` for mode controls and entries.
- `50-shell.js` for bootstrap and return behavior.

Mode is layout/navigation state, not a URL route. Existing `screen`/`action` deep links, history, keyboard commands, confirmation, retry, and continuation remain authoritative. Switching mode must not call an action or rewrite the address.

The host adapter should stop supplying business-specific home mappings once the server contract exists. It may retain generic rendering hooks, but it must not reconstruct the mode entries from screen names.

### 3. Raw debug gate

The current execution path needs a server gate because the metadata path currently defaults `raw_debug` to true and the shell exposes a raw drawer globally. The minimum safe shape is:

```python
build_debug_envelope(
    action: TuiAction,
    *,
    diagnostic_authorized: bool,
    raw_response: JsonValue | None,
) -> TuiDebugEnvelope
```

`raw_response` must be omitted/null unless both the action explicitly allows raw debug and the server-authorized diagnostic capability is true. The unauthorized path should avoid serializing the payload, while still returning a typed `raw_available: false` state. The gate belongs in the server execution path, not only in the drawer visibility:

- `apps/terminal/application/tui_workbench_execution.py`: build the bounded envelope after authorization.
- `apps/terminal/application/tui_workbench.py` or the existing action runner: obtain the diagnostic capability and pass it explicitly.
- `apps/terminal/interface/api_views.py`: preserve the normal action authorization path; do not accept a client-provided debug flag.
- `frontend/tui-workbench/src/00-runtime.js`, `40-views.js`, and `50-shell.js`: render raw tools only when the server projection says they are authorized.

New or ordinary actions should default to no raw response. Legacy `raw_debug` metadata can remain a necessary condition, but it must never be sufficient on its own.

### 4. Smallest production evidence

- IA/schema validation: `tests/unit/terminal/test_tui_information_architecture.py` and the metadata compiler/revalidation tests.
- Permission-filtered catalog and bootstrap: `tests/unit/test_tui_workbench.py`.
- Pure projection and raw envelope: a focused unit test beside the existing TUI application tests.
- Browser mode/deep-link/history/no-auto-run cases: `frontend/tui-workbench/tests/workbench-browser.test.mjs`.
- Existing continuation/retry/confirmation suites remain required.
- Rebuild and validate the generated runtime/manifest only in the authorized implementation window.

## Limits of this artifact

This page does not prove server authorization, API deep links, data freshness, action confirmation, retries, or raw-debug redaction. It only makes the intended shell projection, evidence/limitations layering, unavailable capability state, return path, and keyboard feel reviewable without external requests or production writes.
