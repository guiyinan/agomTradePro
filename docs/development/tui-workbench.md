# TUI Workbench

> Last updated: 2026-06-21

`/tui/` is the standalone task-oriented interaction shell for AgomTradePro. It is not a CSS presentation mode for existing Django pages, and it is not an API catalog UI.

## Contract

- Page: `GET /tui/`
- Catalog: `GET /api/tui/catalog/`
- Screen: `GET /api/tui/screens/<screen_key>/`
- Action runner: `POST /api/tui/actions/<action_key>/run/`
- Compatibility registry: `GET /api/tui/registry/`
- Compatibility module snapshot: `GET /api/tui/modules/<module_key>/snapshot/`

The V2 catalog is read from published TUI metadata:

- Runtime primary source: `terminal_tui_metadata_registry` rows with `status=published`.
- Runtime fallback source: `config/tui/published/tui_operation_graph.published.json`.
- Candidate graph: `config/tui/generated/tui_operation_graph.generated.json`.
- Candidate evidence: `config/tui/generated/tui_operation_evidence.generated.json`.
- Compile-time helper skill: `tui-metadata-compiler/`.
- Promotion guide: `docs/development/tui-metadata-promotion-guide.md`.

Runtime `/tui/` does not parse classic templates, SDK modules, MCP tools, or source code. Those sources are evidence for the compile-time skill only. The skill generates candidate JSON, validates it, and publishes it to the database only after explicit approval.

## Governance Principles

TUI metadata is now a schema-first release artifact, not an AI-shaped UI draft:

- Schema exists before AI generation. `schema_version`, field keys, value types, widgets, action risks, panel kinds, and source prefixes are fixed by `config/tui/schema/tui_metadata.schema.v3.json` and `validate_tui_metadata()`. New types require an intentional schema upgrade.
- AI reads code, not retellings. Field metadata must come from Django models, DRF serializers/OpenAPI, DDD aggregate roots, SDK signatures, or MCP typed contracts. Human or AI review may improve labels, grouping, descriptions, and task order, but must not invent fields or widgets.
- Validate before publish. Generated metadata must pass JSON Schema validation, domain validation, smoke checks, and manual diff review before it can be written to `terminal_tui_metadata_registry`.
- Review cannot be skipped for high-risk fields. Write actions cannot use GET. Amount, quantity, price, cash, share, quote, weight, count, and portfolio-list fields must declare value types and remain behind confirmation plus backend permission checks.
- The renderer is a dumb client. Business-specific visibility, editability, confirmation, and response-shape decisions belong in metadata and backend view models; JavaScript only renders the published contract and calls the action runner.
- Every publish leaves a trail. Registry rows record schema version, generation source (`ai` / `manual` / `mixed`), backend version, payload hash, source evidence hash, changed fields, review status, approver, review note, and publish time.

The metadata files use a compact storage form. Common action defaults such as `method: GET`, `risk: read`, `raw_debug: true`, empty `fields`, empty `view_model`, and action `module_key` values that can be inferred from `screen_key` may be omitted from disk and DB payloads. `validate_tui_metadata()` restores those defaults before the TUI service uses the graph.

The screen contract returns:

- `layout.regions`: PC tools shell regions (`module_tree`, `workspace`, `inspector`, `status_bar`, `raw_drawer`).
- `screen.dashboard_panels`: optional home/dashboard panels that compose already-approved actions into an operator-first overview.
- `screen.default_action_key`: the primary task to run automatically when a non-home workspace opens.
- `screen.workflow`: optional daily workflow navigation metadata (`previous`, `next`, `step`, and `role`).
- `screen.business_context`: operator guidance with the screen objective, expected decision output, and ordered checkpoints. Explicit metadata wins; the compiler and backend derive a generic fallback when a screen is not hand-annotated.
- `actions`: action schemas that generate forms and buttons.
- `actions[].ui_key`: a non-technical browser identifier for DOM bindings. It must not reveal endpoint-shaped metadata keys such as `auto.api...`.
- `actions[].fields`: input fields used for query params or JSON bodies.
- `actions[].risk`: read/AI/write-style risk labels.

Operator-facing navigation is organized by user work areas and tasks. Ordinary screen/action payloads do not include HTTP methods, endpoints, metadata source labels, raw debug flags, or response-mapping internals. Technical endpoint details belong in compatibility endpoints, metadata files, review tooling, tests, or explicit debug tools.

The browser must not translate the internal `risk=read` policy into visible labels such as "read-only" or "只读". Read actions are still real operator actions: open a list, inspect a status, run a check, filter a query, or generate a view. Confirmed write and AI actions remain visually separate, but the normal UI should describe what the operator can do, not which HTTP safety bucket the metadata used.

The ordinary DOM uses `actions[].ui_key` for action form bindings. Real metadata action keys remain inside the loaded screen contract so the runner can call `/api/tui/actions/<action_key>/run/`, but they should not be copied into visible HTML attributes or labels. This keeps endpoint-shaped keys out of the operator surface while preserving a stable backend execution contract.

Published labels must also be operator-facing. Do not publish labels that are only cleaned-up route names, such as `Dashboard Alpha Ic Trends`, `System List`, `Password Strength`, `Validate`, or `Assignment`. Add exact labels or shared vocabulary rules in `promote_tui_business_screens.py` so generated actions become user jobs such as `Alpha IC 趋势`, `系统任务列表`, `初始化密码强度`, or `策略绑定`.

Action execution returns a business-first `view_model`:

- `datagrid`: tabular list with pager metadata.
- `detail`: key/value fields and nested row counts.
- `message`: plain operation message.
- `debug.raw_response`: raw payload for the Raw Response drawer only.

The browser renders a generic decision cue above every `datagrid`, `detail`, and `message` result when the screen has `business_context`. It shows the expected decision output, the current evidence shape (for example row count, detail field count, or message section count), reviewed operations available on the screen, and the next workflow step. This cue is derived from published metadata and actual result shape; it must not invent a trading recommendation.

The view model layer translates common field keys and enum-like values into operator language before the browser renders them. For example, `portfolio.total_assets`, `portfolio.total_return_pct`, `user.username`, and `regime.current=Recovery` should render as `组合 / 总资产`, `组合 / 总收益率`, `用户 / 用户名`, and `复苏`. Add shared vocabulary in `TuiWorkbenchService` for reusable business terms; do not add per-endpoint label rewrites in JavaScript.

Parameterized action fields go through the same vocabulary layer. A path/query field such as `account_id` should render as `账户ID` with `请输入账户ID`, not `PK`, `Account Id`, or a raw placeholder copied from the endpoint. Empty DataGrid responses should return a user-facing `empty_message` such as `暂无持仓明细数据。`; the browser distinguishes this from a local filter miss (`没有匹配的记录。`).

Empty and blocked states must tell the operator what to do next. DataGrid view models include `empty_guidance` lines such as refresh, adjust parameters, press `F9` to enter the task area, or use the selected-row fill/action buttons. Missing required fields return a `message` view with a `需要补充参数` section listing each field and explaining how to fill it from the left task form or selected-row workflow. Avoid dead-end states that only say "暂无数据" or "需要参数".

Screen labels, action labels, task groups, descriptions, and field labels all pass through the operator vocabulary. Backend/framework words such as `Provider`, `Prompt`, `Chat`, `Runtime`, `Source`, `Keyword`, `Config`, and `Model` should render as user-facing terms such as `服务商`, `提示词`, `对话`, `运行时`, `来源`, `关键词`, `配置`, and `模型`. Domain acronyms that are part of the product language, such as AI, RSS, Alpha, Pulse, and Qlib, may remain when they are clearer than a forced translation.

Current DataGrid vocabulary audit reduced technical column labels across visible primary/support tables from 145 occurrences to 34, with the remaining common cases being acceptable short identifiers such as `ID` and `Top N`. Add future reusable terms to the shared vocabulary before adding screen-specific label rewrites.

The renderer is a reusable TUI framework. It must not know business response names such as `stocks`, `logs`, or `backtests`. If an API needs a specific list or pager path, put it in action metadata; the mapping is used server-side and is not sent to the ordinary screen payload:

```json
{
  "view_model": {
    "kind": "datagrid",
    "rows_path": "data.records",
    "total_path": "meta.total",
    "page_path": "meta.page",
    "page_size_path": "meta.page_size"
  }
}
```

When no mapping exists, the framework may use structure-based detection to choose a table-like list. That fallback is for compatibility only; reviewed published actions should prefer explicit metadata.
Use `view_model.kind: "detail"` for status payloads that contain nested lists but should remain a summary panel.

Home/dashboard screens should use `dashboard_panels` instead of hardcoding business rows in JavaScript:

```json
{
  "dashboard_panels": [
    {
      "key": "alpha-ranking",
      "title": "四、Alpha 排行",
      "kind": "datagrid",
      "action_key": "alpha.scores",
      "max_rows": 10,
      "layout_area": "alpha",
      "columns": [
        {"key": "code", "label": "标的"},
        {"key": "score", "label": "Alpha"}
      ]
    }
  ]
}
```

Allowed panel kinds are `regime_quadrant`, `datagrid`, `detail`, `status`, and `placeholder`. `action_key` must reference an already published action, so the overview cannot bypass risk review or backend permission checks.

Every screen intended to replace a classic Django page should define `default_action_key`. The renderer auto-runs that action when it has no unresolved required fields, so users land on useful content instead of an empty task picker. Secondary actions stay in the left task panel.

Daily workflow screens should define `workflow`; all published screens should have `business_context`, either explicit or generated by the promotion tooling. The workflow strip gives the PC tools style previous/next navigation (`F3` / `F4`), while the Inspector explains why the screen exists in the investment process: objective, expected decision output, and the checks that should be completed before moving on. Keep this metadata in the published graph or generic contract layer, not in per-screen JavaScript, so the workbench stays reusable.

Detail view models flatten one level of nested objects into readable fields. For example, `portfolio.total_assets` renders as `Portfolio / Total Assets`, which keeps summary APIs usable without writing a per-endpoint parser. Absolute or relative internal API paths are not operator-visible detail values. Nested technical fields such as `endpoints` are also hidden from normal detail and Inspector views; raw paths belong only in debug output.

## Classic Replacement Checklist

Use this checklist before calling a `/tui/` screen a replacement for a classic Django page:

- The screen is named and grouped by the user's job, not by backend module or endpoint.
- Screen, action, and dashboard panel labels are user-language labels, not endpoint-derived English fragments.
- `default_action_key` is present when the screen has a natural first view.
- Replacement screens include `business_context` so the user sees the screen goal and expected decision output, not just a list of APIs.
- Opening the screen shows useful content without requiring the user to understand API contracts.
- Results render as `datagrid`, `detail`, `status`, or `message`; normal UI payloads do not expose endpoint, method, source metadata, response mappings, or raw JSON.
- Result views show a business decision cue (`判断产出`, `当前证据`, and `下一步`) when the screen has `business_context`.
- Any required field is represented as a control with an operator-facing label, not as a JSON body editor.
- Pagination uses DataGrid status and keyboard flow (`PgUp`, `PgDn`, row focus), not web-card paging.
- Overview pages use `dashboard_panels` that reference already-approved actions.
- Browser validation confirms no empty "task picker only" page, no default `NO MATCHING ROWS`, and no console warning/error.
- Runtime validation confirms every visible non-home screen has a default action and that each default action returns a renderable business `view_model`.
- When changing `tui-workbench.js` or `tui-workbench.css`, bump the static asset version in `core/templates/terminal/tui_workbench.html`.

Current promotion keeps the navigation business-first instead of toolbox-first. Broad classic areas are split into focused replacement screens:

- Account classic pages: `execution.accounts` for account/portfolio overview, `execution.trading-ledger` for positions and trades, `execution.portfolio-performance` for performance and valuation, and `execution.account-settings` for execution parameters and permissions.
- Research classic pages: `research.asset-lab` for asset/equity research, `research.fund-sector` for fund and sector comparison, and `research.screening-sentiment` for filters and sentiment checks.
- Risk classic pages: `macro-regime.risk-controls` for decision rhythm, `macro-regime.beta-gate` for exposure gating, and `macro-regime.hedge` for hedge snapshots and alerts.
- AI classic pages: `ai-ops.prompt-workbench` for prompt templates/chains/logs and `ai-ops.providers` for service providers, models, and usage logs.
- Data Center classic pages: `api-library.data-center` for data center status/news and `api-library.market-thermometer` for market-temperature history and thresholds.

Promotion must prune empty legacy toolbox screens before publishing. A screen with no approved actions and no dashboard panels should not appear in the normal catalog.

## Interaction Model

The workbench uses one DOS/PCTOOLS-style operation model across user work areas:

- `File`, `Module`, `Action`, `View`, and `Help` open terminal-style menu panels instead of navigating to separate Django pages.
- `F1` opens keyboard help.
- `F2` expands or collapses the module tree; expanding it focuses the active screen.
- `F3` moves to the previous published workflow screen, falling back to the previous visible screen when workflow metadata is absent.
- `F4` moves to the next published workflow screen, falling back to the next visible screen when workflow metadata is absent.
- `F5` refreshes the current action result, or the current screen when no action has run.
- `F6` executes the next primary task in the current screen. It uses the published action order and never chooses confirmed write operations as the next primary step.
- `F7` opens a command-line filter for the visible DataGrid.
- `F8` exports the visible DataGrid rows to CSV.
- `F9` focuses the task area. The task filter searches operator-facing action labels, descriptions, groups, verbs, and field labels across primary, support, advanced, and operation actions, then restores the normal grouped view when cleared.
- `F10` expands or collapses the Inspector / explanation panel.
- Arrow keys move the selected DataGrid row.
- `Enter` opens the selected row as a detail dialog.
- `PgUp` and `PgDn` call the action runner with adjacent page params only when pager metadata allows it.
- `Esc` closes modal layers in order: detail/help, filter strip, menu, raw drawer.

The visible hotkey bar should only advertise workbench-owned commands. Do not expose or globally bind browser/navigation combinations such as `Alt+Left`, `Alt+Right`, `Alt+letter`, or `Ctrl+PgDn` as TUI commands; they read as browser controls and break the DOS application mental model.

The workbench uses the operating-system cursor. Do not hide it or replace it with a simulated block cursor. Left module navigation and the right Inspector are first-class keyboard targets and must remain collapsible through `F2` and `F10` plus their titlebar buttons. Scrollable regions should use square DOS-style scrollbar tracks, thumbs, buttons, and corners without gradients or rounded shapes.

The TUI shell now exposes a runtime theme system with three reviewed modes: `A` (Norton PCTOOLS-style blue/cyan/yellow shell), `B` (neutral professional terminal, default), and `C` (risk-control console). Theme state is runtime-only UI state: switching must not reload the page, reset the current screen, move the selected row, clear filters, or rerun tasks. `Alt+T` cycles themes, the footer shows a low-key status item (`T:A/B/C`), and the current mode is also visible in the system strip as `STYLE: A/B/C`.

All renderer colors must resolve from one shared theme token set: `background`, `panelBackground`, `primaryText`, `secondaryText`, `border`, `highlight`, `accent`, `success`, `warning`, `error`, and `grid`. Do not hardcode new per-component colors in `tui-workbench.css` or invent per-screen color logic in JavaScript. Runtime theme switching is implemented by replacing root CSS variables only; the renderer remains a dumb client.

JSON remains hidden by default. Operators use DataGrid, detail fields, modal row details, filters, paging status, and CSV export as the primary interface. The Raw Response drawer is a debug view only.

DataGrid row details and the selected-row Inspector must reuse `columns[].label` from the business view model. They must not display raw row keys such as `portfolio_value` or `return_pct` when the table already has labels such as `组合值` or `收益率`.

Parameterized actions should be usable without copying internal IDs by hand whenever the current table already contains the needed identifiers. The browser provides a generic "从选中行填充" control on field-backed actions and never exposes the endpoint it will call. If a workflow routinely needs a parameter that is not present in the default table, add that identifier to the API/view-model output or provide an explicit selector action instead of asking users to inspect raw JSON.

When a DataGrid row is selected, the Inspector should surface the matching field-backed actions under `选中行可做`. This is generic: it matches action field keys such as `account_id`, `portfolio_id`, `asset_code`, `fund_code`, `task_id`, and similar aliases against the selected row. The listed actions are buttons, not passive hints: clicking one fills params from the selected row and calls the same action runner used by the left task panel, so write confirmations and backend permission checks still apply. The goal is a PC tools workflow where users select a business record first, then run the next usable task without reading endpoint contracts.

Primary tasks are treated as an ordered work queue inside each screen. The decision cue shows `本屏下一项`, and `F6` runs that task so users can step through the published workflow without scanning endpoint-like task names. The cue also renders `运行下一主流程` and `进入流程下一屏` buttons when applicable; these call the same generic runner and workflow navigation as the keyboard shortcuts. Task cards use role labels such as `主流程`, `支撑检查`, `条件查询`, and `可执行操作`; write/AI operations remain visible but separate under `00 可执行操作`, and result inspectors repeat the available confirmed operations in user-language labels instead of endpoint/method details.

The Inspector is a formatted operator panel, not a raw key/value dump. It should group the current task, operation, result shape, progress, business objective, and follow-up actions. It may reuse generic rows from the view model, but labels and values must pass through the shared operator vocabulary and internal-path filter before rendering.

When a primary task returns successfully, the workbench marks it complete in the current browser session. The action panel shows `主流程 completed/total`, completed tasks get a green marker, and the decision cue shows `本屏进度`. This progress is persisted in browser `sessionStorage` only as UI convenience state and can be reset from the task area; the source of truth for business records remains the backend APIs and audit logs.

## Metadata Promotion

Use this flow when adding or changing TUI screens:

1. Use `tui-metadata-compiler/` to inspect API contracts, SDK modules, MCP tools, and classic templates.
2. Generate a candidate:

   ```powershell
   agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\generate_tui_metadata.py
   ```

   Default generation collects all available evidence and writes it to `config/tui/generated/tui_operation_evidence.generated.json`; the generated graph keeps only `source_evidence_ref` and `source_evidence_counts`. Use `--dry-run` to inspect counts without writing. Use the `--*-evidence-limit` flags only when a smaller sample is needed. Use `--include-safe-api-actions N` for direct safe GET API candidates and `--include-parameterized-api-actions N` for safe GET detail/query actions that need explicit field input. Use `--inline-evidence` only for one-off debugging when a single large JSON is explicitly useful.

   To rebuild the broad safe-read coverage baseline, use:

   ```powershell
   agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\generate_tui_metadata.py --include-safe-api-actions 9999 --include-parameterized-api-actions 9999
   agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\generate_tui_metadata.py --include-safe-api-actions 9999 --include-parameterized-api-actions 9999 --publish-ready --output config\tui\published\tui_operation_graph.published.json
   agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\smoke_tui_actions.py --metadata-path config\tui\published\tui_operation_graph.published.json --json-output tmp_tui_smoke.json --prune-output config\tui\published\tui_operation_graph.published.json
   agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\promote_tui_business_screens.py config\tui\published\tui_operation_graph.published.json
   agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\smoke_tui_actions.py --metadata-path config\tui\published\tui_operation_graph.published.json --json-output tmp_tui_smoke.json --fail-on-error
   ```

   `--publish-ready` writes a compact runtime graph without source evidence arrays; evidence remains in the generated evidence file.
   The smoke step executes the published actions through the same service used by `/tui/`; actions with required fields are counted as `needs_input`, and failed auto-discovered candidates are removed from the ordinary published graph.

3. Edit `config/tui/generated/*.json` only when AI/human review needs better labels, grouping, descriptions, task order, or view-model paths. Do not invent fields, value types, widgets, visibility rules, editability rules, confirmation policy, or action risk in the generated graph. If the existing schema cannot express the needed UI, upgrade `config/tui/schema/tui_metadata.schema.v3.json` and `validate_tui_metadata()` first.
4. Validate:

   ```powershell
   agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\validate_tui_metadata.py config\tui\generated\tui_operation_graph.generated.json
   ```

5. Review the generated diff. Do not publish hidden admin/debug/unsafe routes to the normal TUI surface.
6. Publish to DB only with explicit approval:

   ```powershell
   agomtradepro\Scripts\python.exe tui-metadata-compiler\scripts\publish_tui_metadata.py config\tui\generated\tui_operation_graph.generated.json --approve --generation-source mixed --backend-version "local-dev" --source-evidence-path config\tui\generated\tui_operation_evidence.generated.json --review-note "Reviewed TUI metadata"
   ```

Normal runtime menus expose `read`, `ai`, and reviewed `write` actions. `write` actions are shown as `00 可执行操作`, validate required fields before confirmation, require a confirmation modal before execution, and still re-enter backend API permission checks. If required fields are missing, the action runner returns a business `message` view with `需要参数` and field labels instead of showing a confirmation prompt or raw JSON. `unsafe` and `admin` actions may be present in metadata for future admin toolboxes, but they are hidden from the ordinary catalog and blocked by `run_action`.

## Current Published Surface

The reviewed file and local DB baseline now contain 34 screens and 319 published actions: 311 read actions, 6 confirmed write actions, and 2 AI interaction actions. Of the read coverage, 203 can open directly and 109 are safe parameterized read tools that require field input before execution. It keeps the hand-authored user workbench screens, promotes smoke-passing direct and parameterized tools into user-task screens, and keeps only low-frequency system/runtime tools in the system toolbox:

- Decision and workflow tools.
- Environment, strategy, rhythm, rotation, and hedge tools.
- Research, alpha, signal, factor, backtest, and asset-analysis tools.
- Account, portfolio, asset, and simulated-trading read tools.
- Execution, audit, events, realtime, share, and task-monitor tools.
- System, AI capability, terminal, agent-runtime, setup, and data-center tools.
- Parameterized detail/query tools are placed into the relevant user screen, with required fields instead of endpoint exposure.

The main business screens now include daily decision flow, dashboard checks, policy intake, tactical pulse, account and portfolio checks, strategy and position rules, rotation and allocation, rhythm/hedge controls, asset and market research, events/realtime monitoring, sharing/observer workflows, Prompt/model configuration, runtime health, and data center status. All 34 published screens now include explicit or generated `business_context`, so the Inspector shows the user's objective and expected decision output before they execute or inspect tasks.

The compile-time scan currently sees 468 safe GET evidence records, 405 SDK methods, 346 MCP tools, and 127 classic templates with UX features. Of those safe GET records, 259 are direct safe-read candidates and 109 are parameterized safe-read candidates after filtering technical suffix routes and operation-like GET routes. The current compact published graph exposes 319 runtime actions: 312 scanned/smoked candidates plus 7 reviewed operation actions. It keeps 43 non-smokeable auto candidates pruned and has 277 smoke-passing or field-backed actions promoted into user-task screens.

Latest local runtime audit: the catalog exposes 26 non-empty screens. The home screen is intentionally dashboard-composed; the other 25 visible screens all have a default action and all 25 default actions return a renderable business view model through `/api/tui/actions/<action_key>/run/`. The visible primary/support queue currently has 202 no-input actions, and all 202 return renderable business view models. The reviewed operation set currently has 8 actions: 4 write actions correctly stop at confirmation, 2 write actions correctly return `需要参数`, and 2 AI actions return business view models.

Deferred candidates remain in generated evidence but are not normal-menu actions when they still lack safe field metadata, return HTML/HTMX fragments, expose debug/docs/TUI internals, look like write/heavy operations despite using GET, or fail the same-process smoke gate. Current deferred counts are 65 remaining path-parameter records, 30 write-like or heavy records, 8 internal/debug/docs records, and 43 smoke-pruned auto candidates.

## Migration Rule

New UX work should prefer adding published metadata to the TUI workbench over creating another one-off Django page. Existing Django pages remain available as legacy/classic exits, but they are not wrapped inside a TUI shell.

Do not load `static/css/tui-theme.css` or `static/js/tui-mode.js` into classic pages. Those files are legacy rollback/reference assets. New TUI work belongs in `/tui/`, `tui-workbench.css`, and `tui-workbench.js`.
