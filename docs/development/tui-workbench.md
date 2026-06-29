# TUI Workbench

> Last updated: 2026-06-29

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

Frontend runtime assets are synced from AgomTUI reference runtime. The current baseline is AgomTUI commit `781f75f` (`Improve responsive workbench layout`), with local AgomTradePro adaptations for dashboard panel routing, regime field aliases, table value coloring, and legacy `pagination_mode=limit_offset` compatibility.

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
- `chart`, `image`, `kpi_trend`, `table_chart`, `host_slot`, `custom`: richer renderer contracts supported by the AgomTUI runtime and gated by `config/tui/schema/tui_metadata.schema.v3.json` plus `validate_tui_metadata()`.
- `debug.raw_response`: raw payload for the Raw Response drawer only.

The browser renders a generic decision cue above every `datagrid`, `detail`, and `message` result when the screen has `business_context`. It shows the expected decision output, the current evidence shape (for example row count, detail field count, or message section count), reviewed operations available on the screen, and the next workflow step. This cue is derived from published metadata and actual result shape; it must not invent a trading recommendation.

The view model layer translates common field keys and enum-like values into operator language before the browser renders them. For example, `portfolio.total_assets`, `portfolio.total_return_pct`, `user.username`, and `regime.current=Recovery` should render as `组合 / 总资产`, `组合 / 总收益率`, `用户 / 用户名`, and `复苏`. The same shared vocabulary should also normalize nested collaboration/detail payloads such as public share snapshots (`分享链接 / 分享等级`, `快照 / 来源区间开始`, `绩效 / 年化收益`), research payloads such as `weights.policy`, `summary.investable`, `regime_fit_score`, and `total_score`, and field-specific enums such as `account_type=real`, `portfolio_type=simulated`, `rbac_role=owner`, and `risk_tolerance=moderate`. DataGrids must also prefer row-provided names such as `fund_name` over fallback asset-name lookup so fund rows do not display stock aliases. Add shared vocabulary in `TuiWorkbenchService` for reusable business terms; do not add per-endpoint label rewrites in JavaScript.

Parameterized action fields go through the same vocabulary layer. A path/query field such as `account_id` should render as `账户ID` with `请输入账户ID`, not `PK`, `Account Id`, or a raw placeholder copied from the endpoint. The same operator vocabulary also applies to action result titles and empty-state copy, so running an action must not fall back to raw compiler labels. Empty DataGrid responses should return a user-facing `empty_message` such as `暂无持仓明细数据。`; the browser distinguishes this from a local filter miss (`没有匹配的记录。`).

Published field defaults are execution defaults, not display-only hints. If a reviewed action ships with `default: "default"` or another non-empty default value, the TUI runner must inject that value into the actual request when the operator leaves the field blank. Otherwise the screen can pass local required-field validation but still fail the backend call with a missing query/path parameter.

Date fields in TUI actions must be published as `input_type: "date"` with `value_type: "date"` so the workbench renders the native date control. Read actions with keys such as `date`, `as_of_date`, `start_date`, `end_date`, and `trade_date` receive runtime date defaults from the action runner. Ranking/list actions that page over a bounded result set, such as `alpha.scores`, should expose hidden `limit`/`offset` query fields and an explicit offset pagination contract; the backend response must include `total`, `limit`, `offset`, `page`, and `page_size` when those pagination params are used so `PgUp/PgDn` and the visible Previous/Next buttons are enabled from pager metadata instead of local row counts.

Empty and blocked states must tell the operator what to do next. DataGrid view models include `empty_guidance` lines such as refresh, adjust parameters, press `F9` to enter the task area, or use the selected-row fill/action buttons. Missing required fields return a `message` view with a `需要补充参数` section listing each field and explaining how to fill it from the left task form or selected-row workflow. If a nominal `datagrid` response is really a short list of plain-language warning or summary lines, the renderer should promote it to a `message` result instead of showing a single `值` column. Avoid dead-end states that only say "暂无数据" or "需要参数".

Health/status payloads with scalar summary fields plus one named business list should stay as `detail` instead of collapsing into a one-column grid. For example, payloads such as `status/service + filters_available` should render summary fields plus a nested count like `可用滤波器`, while payloads that only expose internal endpoint directories (`module/endpoints`) must hide the `/api/...` list from the normal UI and show an operator summary with capability count and guidance instead.

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

Allowed panel kinds are `regime_quadrant`, `datagrid`, `detail`, `status`, and `placeholder`. `action_key` must reference an already published action, so the overview cannot bypass risk review or backend permission checks. The runtime derives desktop, tablet, and mobile dashboard grid areas from `dashboard_panels`, so adding or removing panels should be done in metadata instead of adding hardcoded CSS grid classes.

Every screen intended to replace a classic Django page should define `default_action_key`. The renderer auto-runs that action when it has no unresolved required fields, so users land on useful content instead of an empty task picker. Secondary actions stay in the left task panel.

Daily workflow screens should define `workflow`; all published screens should have `business_context`, either explicit or generated by the promotion tooling. The workflow strip gives the PC tools style previous/next navigation (`F3` / `F4`), while the Inspector explains why the screen exists in the investment process: objective, expected decision output, and the checks that should be completed before moving on. Desktop users can resize the Inspector; the width is persisted locally and remains bounded by the runtime layout. Keep this metadata in the published graph or generic contract layer, not in per-screen JavaScript, so the workbench stays reusable.

For `detail` and `message` results, the center panel is the single source of truth for the returned business object. The Inspector must not replay the same key/value payload a second time. It is reserved for flow state, business objective, evidence framing, and next-step actions. Desktop layout should also keep a readable CJK width for the Inspector instead of falling back to per-character wrapping.

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

- Account classic pages: `execution.accounts` for the current account list, current positions, account-level position queries, and account health/performance checks; `execution.trading-ledger` for trades, capital flows, and simulated-trading ledger checks; `execution.portfolio-performance` for portfolio performance and valuation; and `execution.account-settings` for execution parameters and permissions.
- `execution.account-settings` should default to a row-backed selector such as account categories, not an empty cost-config table, so operators can enter the screen and continue with selected-row workflows immediately.
- `execution.trading-ledger` should default to an account selector when direct position/trade tables are empty in local environments; that keeps `account_id`-based follow-up tasks operable from selected rows.
- Research classic pages: `research.asset-lab` for asset/equity research, `research.fund-sector` for fund and sector comparison, and `research.screening-sentiment` for filters and sentiment checks.
- Risk classic pages: `macro-regime.risk-controls` for decision rhythm, `macro-regime.beta-gate` for exposure gating, and `macro-regime.hedge` for hedge snapshots and alerts.
- `macro-regime.hedge` should default to a row-backed snapshot list when operators are expected to open snapshot detail records or continue into alert/snapshot follow-ups; latest-summary tables can stay as primary support actions instead of the default entrypoint.
- AI classic pages: `ai-ops.prompt-workbench` for prompt templates/chains/logs and `ai-ops.providers` for service providers, models, and usage logs.
- Data Center classic pages: `api-library.data-center` for data center status, selector catalogs, and conditional data queries; `api-library.market-thermometer` for market-temperature history and thresholds.

Promotion must prune empty legacy toolbox screens before publishing. A screen with no approved actions and no dashboard panels should not appear in the normal catalog.

Default screen entrypoints should prefer non-empty, operator-informative actions over empty slices. If the most obvious business list is often empty in local or early-stage environments, publish a selector, summary, or statistics action as the default instead of dropping users into a blank table.

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

Parameterized actions should be usable without copying internal IDs by hand whenever the current table already contains the needed identifiers. The browser provides a generic "从选中行填充" control on field-backed actions and never exposes the endpoint it will call. Selected-row context must survive same-screen drilldown from a `datagrid` into `detail` or `message`, so a user can open a record and still prefill a follow-up action such as a governed write on that same screen. The same fallback must not survive into a new `datagrid` that currently has zero visible rows: an empty query result means there is no current row to act on, so row-fill and row-backed actions must not silently reuse the previous table's identifier. If a workflow routinely needs a parameter that is not present in the default table, add that identifier to the API/view-model output or provide an explicit selector action instead of asking users to inspect raw JSON.

The same selected-row context should also survive a same-screen parameterized query that returns an empty server-side `datagrid`. Otherwise users lose the source row immediately after a valid but empty follow-up query and cannot continue with adjacent actions such as portfolio-scoped strategy checks. Local filter misses are different: when the operator's own text filter hides all rows, the browser should clear row context rather than silently filling from a hidden record.

When a displayed cell intentionally combines identifier and label text such as `511010 国债ETF` or `000001 华夏成长`, the row payload must still preserve the raw identifier for follow-up actions. Selected-row fill should prefer that raw value over the decorated display string.

Selected-row fill must also avoid inventing multi-field parameters from a single generic code. Example: on currency screens, a plain `code=CNY` row may fill `from_code`, but it must not also fill `to_code` unless the row exposes a distinct target/quote currency field.

When the current selected row has no usable field match for an action, the browser should disable that action's `从选中行填充` button instead of leaving a dead affordance that only fails after click.

Generic primary-key fill must also stay row-source compatible. A strategy list row may prefill strategy-scoped routes such as `/api/strategy/strategies/<pk>/...`, but it must not light up unrelated detail routes such as `/api/strategy/position-rules/<pk>/` or `/api/strategy/assignments/<pk>/` just because both payloads expose a plain `pk`. The browser now records the source action resource family on selected-row context and only allows generic `pk`/`id` fill when the row came from the same base resource family. This normalization must work across both generated route-shaped action keys (`param.api.get.api.backtest.backtests.pk`) and hand-authored workbench keys (`backtest.backtests`), otherwise same-resource detail flows regress.

When a DataGrid row is selected, the Inspector should surface the matching field-backed actions under `选中行可做`. This is generic: it matches action field keys such as `account_id`, `portfolio_id`, `asset_code`, `fund_code`, `task_id`, and similar aliases against the selected row. The listed actions are buttons, not passive hints: clicking one fills params from the selected row and calls the same action runner used by the left task panel, so write confirmations and backend permission checks still apply. The goal is a PC tools workflow where users select a business record first, then run the next usable task without reading endpoint contracts.

For `api-library.data-center`, the published screen should include same-screen selector reads for indicator catalog, provider list, and publisher catalog. Parameterized tasks such as macro series lookup or quote sync should be operable from those tables without requiring operators to inspect raw JSON for codes or IDs.

The task panel now uses delegated `submit` and `click` handling on the actions container instead of rebinding every rendered form node. This keeps support and advanced actions runnable across repeated task-panel rerenders and avoids browser/runtime combinations where a visible task button fails to reach the shared action runner even though the backend action itself is healthy.

The actions panel also reserves top scroll padding and action-level scroll margin so keyboard focus and browser auto-scroll do not pin the first available task under the panel chrome. This especially matters for same-screen support catalogs such as `api-library.data-center`.

Directory-like root APIs that return only internal `/api/...` links should still render as operator summaries, not empty detail pages. The workbench should convert those payloads into a small detail card with capability count and an operator hint, as with the share overview screen.

Published actions must also stay row-source compatible with the screen they live on. If an action needs a portfolio primary key, keep it on a screen that can render portfolio rows such as `execution.portfolio-performance`; do not leave it on `execution.accounts` or `execution.trading-ledger` where the default rows are accounts or positions. Likewise, list-style selector actions such as `decision.workspace.aggregated`, `decision-rhythm.quotas`, `decision-rhythm.cooldowns`, and `decision-rhythm.requests` must stay `datagrid` in published metadata, otherwise the TUI cannot produce selectable rows for follow-up detail actions.

Runtime metadata loading also applies a final operator-usability normalization step before screens are rendered. This runtime pass may prune duplicated detail routes when the same screen already exposes a row-backed business-key route for the same record, such as keeping `capability_key` detail and hiding the redundant `pk` detail on `ai-ops.capabilities`.

User-scoped detail actions must only appear when the current user has a reachable selector path in the same screen. For example, `ai-ops.providers` should hide `我的 AI 服务商详情(pk)` when the current user has no personal provider rows, and show it again after a personal provider exists.

The same operator-first rule also applies to shared business screens whose detail actions depend on local row availability. `macro-regime.risk-controls` hides cooldown/request detail queries until cooldown or request rows exist, `macro-regime.beta-gate` hides config/decision/universe detail routes until the corresponding tables have at least one row, and `research.alpha-triggers` hides trigger/candidate detail routes until those records exist. This keeps empty local environments from exposing dead-end ID forms.

The same runtime normalization layer may also patch view metadata when the published JSON is still too generic for operator use. Current example: `auto.api.get.api.system.list` is normalized to a `datagrid` with `items/total` paths so the runtime screen can render an empty-grid or task list instead of a vague detail card. Runtime normalization must be idempotent: the same published payload may be normalized once at publish time and again at load time, but `coverage_summary.runtime_*` counters must remain stable instead of accumulating on every reload.

Another runtime patch converts `auto.api.get.api.dashboard.alpha.history` into a `datagrid` backed by `data`, so the dashboard screen exposes real Alpha history rows and the follow-up `run_id` detail action can work through selected-row flow instead of acting like a blind ID form.

The runtime layer may also re-home published actions to a different user screen when the original screen has the wrong row source. Current example: account-level performance, valuation, and position actions are moved to `execution.accounts`, because account and position checks should share the account row source and account selector instead of being split across portfolio or ledger screens.

The same rule also applies in the opposite direction: portfolio-scoped strategy actions such as `策略绑定（按组合）` and `策略执行记录（按组合）` should live on `execution.portfolio-performance`, not on `macro-regime.strategy`, because a default strategy row must not prefill `portfolio_id` with a strategy primary key.

Some parameterized read actions should remain technical-only until a same-screen selector exists. When a screen has no operator-facing way to obtain a required business key such as `asset_code`, `snapshot_id`, `plan_id`, `indicator_code`, or `task_id`, the default user screen should hide that action rather than asking users to hand-type internal identifiers. The underlying action may still exist in published metadata for future technical surfacing after a compatible selector is added.

The same rule now also applies to condition/query actions that depend on same-screen business rows. Examples: dashboard Alpha history detail waits for visible history runs, risk-control quota/cooldown queries wait for quota or cooldown rows, task statistics wait for visible task rows, and config-center training-run detail waits for visible training runs.

Runtime normalization may also patch incorrect field contracts from generated metadata when the backend path type is authoritative. Current example: audit `log_id` and `request_id` detail actions use string/UUID path segments at runtime and must render text inputs, not numeric inputs.

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

   Default generation collects all available evidence and writes it to `config/tui/generated/tui_operation_evidence.generated.json`; the generated graph keeps only `source_evidence_ref` and `source_evidence_counts`. Use `--dry-run` to inspect counts without writing. Use the `--*-evidence-limit` flags only when a smaller sample is needed. Use `--include-safe-api-actions N` for direct safe GET API candidates and `--include-parameterized-api-actions N` for safe GET detail/query actions that need explicit field input. The compiler now also backfills inferred query fields into already-approved `GET` actions when the published baseline is used as input, so rebuilt graphs do not silently lose required date/query controls on previously promoted detail pages. Use `--inline-evidence` only for one-off debugging when a single large JSON is explicitly useful.

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

Normal runtime menus expose `read`, `ai`, and reviewed `write` actions. `write` actions are shown as `00 可执行操作`, validate required fields before confirmation, require a confirmation modal before execution, and still re-enter backend API permission checks. If required fields are missing, the action runner returns a business `message` view with `需要参数` and field labels instead of showing a confirmation prompt or raw JSON. `admin` actions may also be present in published metadata: they stay hidden from ordinary users, become visible only to admin users, and require confirmation whenever the admin action is not `GET`. `unsafe` actions remain hidden and blocked by `run_action`.

## Current Published Surface

The reviewed file and local DB baseline now contain 37 screens and 367 published actions. The current coverage summary tracks 354 smoke-covered `read`/`ai` actions, of which 215 open directly, 139 require field input, and 0 currently fail the local smoke gate. The graph also carries 15 reviewed operation/admin actions with explicit risk, field, and confirmation policy. Known HTMX fragments, POST-only proposal collections, and operation-like calculate/check routes are now filtered out before publication, so the current published graph carries `smoke_pruned_auto_actions = 0`. The latest local rerun on 2026-06-22 completed with the same `354 / 215 / 139 / 0` baseline and no runtime warning noise from expected Alpha, Celery, or task-monitor fallback paths. A same-day authenticated live UAT pass against a temporary local Django server also verified all 37 screen default actions, representative parameter-required actions, and representative confirmation-required write/admin actions. Follow-up UAT on 2026-06-22 then verified the previously broken account/simulated-trading `performance-report` and `valuation-snapshot` actions after adding the missing date fields, confirmed that strategy `ai_config` / `script_config` empty states now render as `暂无数据` instead of a hard error, removed the stale published GET action for `evaluate_position_management` because the backend route is POST-only, and replaced the stale share public `.../access/` GET publication with an explicit reviewed `share.public.access` POST access action. The observer-grant detail and positions APIs now also reject malformed UUID path input with a `400` validation response instead of bubbling into a `502`. In the TUI runtime path, same-process internal execution now forwards session state, so password-protected public-share reads no longer explode with `502`; they render the backend `401` challenge payload as a user-visible password challenge, append an operator hint that points users to the reviewed access action, and the reviewed access action can establish the same-session verification state needed for follow-up snapshot reads. Share access statuses such as `revoked` and `expired` are also localized in the TUI layer. The detail renderer now also hides wrapper flags such as `success=true` and prefers `detail` over accidental nested-list `datagrid` rendering when a response is clearly a single business object, which makes account详情、策略仓位规则、Prompt 模板/链条、公开分享快照等 screen 更接近用户预期。 The compiler also prunes stale promoted parameterized safe-read actions during rebuild. The unit contract suite now also enforces two global TUI guarantees on the published graph: all 143 actions with required fields must return the `需要参数` contract when invoked empty, and all 13 `write`/`admin` actions must either return `需要参数`, return `待确认`, or succeed immediately only when they are reviewed admin `GET` reads. Follow-up live UAT on 2026-06-23 then verified the current `user-task-52` asset pair against a fresh local Django host on `127.0.0.1:8036`: `api-library.data-center` now opens `指标目录` correctly, supports same-screen `indicator_code` row-fill into `Macro Serie`, and still opens `服务商列表` / `发布机构目录`; `execution.account-settings`, `execution.trading-ledger`, `execution.portfolio-performance`, `macro-regime.hedge`, `execution.share`, `research.fund-sector`, and `research.screening-sentiment` all completed representative `datagrid -> row-fill -> detail/query` loops; `macro-regime.beta-gate`, `research.alpha-triggers`, `api-library.market-thermometer`, and `ai-ops.providers` also completed representative main-flow screen transitions without browser console errors. These 2026-06-23 checks also validated the delegated actions-panel event handling and the actions-panel scroll padding/margin fix that prevents the first support task in long panels from being auto-scrolled into a non-clickable position. A same-day post-fix rerun against a fresh host on `127.0.0.1:8038` then confirmed that `execution.audit` no longer misrenders `审计 / 操作日志 / 详情` as an accidental datagrid: the same `log_id` path now renders a detail view with `Log / ID`、`Log / 请求ID` and other wrapped log fields. The regression suite also now locks two detail-inference cases that previously regressed into datagrids: wrapped audit-log objects and terminal-command detail payloads that include auxiliary lists such as `parameters` / `tags`. A follow-up UI fix on 2026-06-23 also moved action-form submission and row-fill onto explicit per-form bindings, marked runtime forms `novalidate`, and auto-prefills blank row-backed fields from the current selection, so browser-native validation and delegated-submit quirks no longer block terminal-screen flows such as `终端 / 指令 / 详情`. It keeps the hand-authored user workbench screens, promotes smoke-passing direct and parameterized tools into user-task screens, and keeps only low-frequency system/runtime tools in the system toolbox:

- Decision and workflow tools.
- Environment, strategy, rhythm, rotation, and hedge tools.
- Research, alpha, signal, factor, backtest, and asset-analysis tools.
- Account, portfolio, asset, and simulated-trading read tools.
- Execution, audit, events, realtime, share, and task-monitor tools.
- System, AI capability, terminal, agent-runtime, setup, data-center, and admin-only config-center tools.
- Parameterized detail/query tools are placed into the relevant user screen, with required fields instead of endpoint exposure.

The main business screens now include daily decision flow, dashboard checks, policy intake, tactical pulse, account and portfolio checks, strategy and position rules, rotation and allocation, rhythm/hedge controls, asset and market research, events/realtime monitoring, sharing/observer workflows, Prompt/model configuration, runtime health, data center status, and the admin-only Qlib config center. All 37 published screens now include explicit or generated `business_context`, so the Inspector shows the user's objective and expected decision output before they execute or inspect tasks. `audit.summary` is now modeled as a required-input read action instead of surfacing as a smoke-failing generic GET.

The compile-time scan currently sees 468 safe GET evidence records, 405 SDK methods, 346 MCP tools, and 127 classic templates with UX features. Of those safe GET records, 228 are direct safe-read candidates and 137 are parameterized safe-read candidates after filtering technical suffix routes, HTMX-only fragments, unstable collection routes, and operation-like GET routes. The current compact published graph exposes 367 runtime actions, 319 business-promoted actions, and 15 reviewed operation/admin actions. Deferred counts now stand at 37 path-parameter records, 30 write-like or heavy records, and 8 internal/debug/docs records.

Latest local runtime audit: the ordinary catalog still hides `api-library.config-center`, while admin users see that screen and can open `config_center.qlib_runtime` directly. Admin `POST` actions stay in the same workbench but require confirmation before execution. Focused regression tests now cover both visibility modes and the updated published metadata statistics.

Deferred candidates remain in generated evidence but are not normal-menu actions when they still lack safe field metadata, return HTML/HTMX fragments, expose debug/docs/TUI internals, or look like write/heavy operations despite using GET. Current deferred counts are 37 remaining path-parameter records, 30 write-like or heavy records, and 8 internal/debug/docs records. The current published graph no longer depends on post-smoke pruning to remove auto-promoted failures.

## Migration Rule

New UX work should prefer adding published metadata to the TUI workbench over creating another one-off Django page. Existing Django pages remain available as legacy/classic exits, but they are not wrapped inside a TUI shell.

Do not load `static/css/tui-theme.css` or `static/js/tui-mode.js` into classic pages. Those files are legacy rollback/reference assets. New TUI work belongs in `/tui/`, `tui-workbench.css`, and `tui-workbench.js`.
