# TUI User-Facing Design Standard

> Last updated: 2026-10-17

This standard defines the user-facing contract for AgomTradePro `/tui/`. It exists to stop TUI screens from degenerating into route browsers, endpoint lists, or raw JSON shells.

## Core Rule

The account inspection preview offers an explicit reference-price choice. Its
default market mode keeps the existing behavior. Published-close mode displays
the verified daily-close basis, market date and source observation time alongside
the read-only plan. Request and response basis must agree; incomplete provenance
must never appear as a verified actionable row. The close remains a preview
reference and cannot authorize orders or automatic proposal creation. Publication
hashes, run identifiers and internal publication keys remain outside ordinary
user-facing copy.

Every published TUI screen must optimize for user completion, not interface exposure.

The decision-data row in ordinary market context and its admin governance summary
retain the owner's aggregate restriction and per-security observation/fetch clocks.
Check time is labelled separately and is not refreshed when a cached result is read.
Thermometer observation, reference date and snapshot date keep their own labels;
none supplies a missing quote clock or a synthetic aggregate observation time.
Stable owner reason codes remain evidence, while visible restrictions use readable
copy. Restricted facts remain diagnostic facts rather than zero values. These two
consumers do not calculate freshness or introduce fallback decisions. Development
counterexamples use synthetic source-bearing inputs; they do not establish live
provider or ordinary-user browser acceptance.

- One screen serves one primary user task.
- P0 information is visible on the first screenful.
- Copyable artifacts such as token, endpoint, and prompt are shown with dedicated semantics, not buried in generic detail dumps.
- Raw endpoint, method, schema, and compiler details are implementation metadata. They do not belong in ordinary user-facing copy.
- Literal connection addresses may appear inside an explicitly copyable access artifact; their labels, help text, errors, and surrounding workflow must remain user-facing and must not expose route/compiler jargon.

## Required Metadata Contract

Mutation transport uses a per-submission `Idempotency-Key`, separate from business fields.
The workbench retains it across confirmation, reauthentication and an explicit retry of the
same submission. A new form submission receives a new key. The action-run endpoint and internal
executor forward only this named header; they do not accept arbitrary caller-supplied headers.
Network failures and server failures offer “重试本次提交” without showing the technical key.
This transport identity does not replace user confirmation, authentication or business authority.

Actions that require a real browser session declare `session_auth_required: true`.
This server-owned optional boolean defaults to `false`; the schema and metadata
validator reject other types. The action-run endpoint resolves the validated,
visible action and requires the exact DRF `SessionAuthentication`, an authenticated
user and a nonempty database-backed session key before constructing its executor.
Failure returns HTTP 403 with `tui_session_auth_required`. Audience, risk, client
parameters and a token-authenticated staff user cannot satisfy this contract.
The action-run request may omit `confirmed` (equivalent to `false`). If present,
it must be a JSON boolean; strings, numbers, null, arrays and objects return
HTTP 400 with `tui_confirmation_invalid` before metadata/audit/executor setup.
Query parameters cannot supply confirmation. A true value remains a UI
acknowledgement and never replaces the owner's business authorization.

An action may declare `result_continuation` with an exact `target_action_key` and
`field_map` for one confirmed, session-protected mutation on the same screen.
The owner returns `continuation` separately from display data. The server validates
its exact shape, target, nonempty hidden values and original UTC expiry before
rendering; it excludes the handoff from debug and audit results. The current tab
keeps those values only in a private controller. They never become form defaults,
URL parameters, persistent browser state or an automatic mutation.
The target still requires its own explicit confirmation and live owner authority.
Network/server retry uses the original unexpired token, confirmation and submission
key; reauthentication credentials are entered again rather than retained for retry.
Cancellation, expiry, a new preview, another action pair or screen exit clears the
corresponding pending/retry context. Source generations prevent late responses from
replacing a newer preview. Backend expiry, CAS and authority remain decisive.

A continuation may opt into `reuse_source_idempotency_key: true` and name a
`readback_action_key`. The readback must be an authenticated, same-screen read-only
GET with the exact mapped target path fields. The source key survives both the
target's confirmation prompt and its confirmed submission; hidden values must
remain identical to the original owner handoff. A confirmation prompt keeps the
pending handoff, while cancellation clears it. The server validates the exact
endpoint path scope. The public catalog retains hidden scope fields without
converting them into account selectors; the browser uses these validated fields
and does not require private endpoint metadata.

Readback path fields identify the public account/entity scope. They remain bound
hidden inputs, but their values may also occur in ordinary result data (for
example, a trade ID matching a security code). Leakage checks protect the other
mapped handoff values, including opaque confirmation tokens; they must not reject
a legitimate result merely because it equals a public scope identifier.

For this opt-in flow, an unknown target outcome retains only the original key and
validated readback scope. The user explicitly queries the original request; the
workbench does not repeat the mutation or generate a replacement key. Partial or
failed reads remain unresolved, including after the confirmation token expires.
Only an explicitly confirmed, dispatched write can enter this unknown state;
failure while requesting the confirmation prompt remains retryable. Switching
context during a dispatched confirmation or receiving an undecodable response
preserves its readback identity. Late responses can update only their original
request key and cannot automatically resolve an already unknown operation.
Only a successful read with the matching request identity resolves it. The owner
readback must report success only after finding the original request's matching
receipt; the generic workbench trusts that outcome contract. A new source
submission on that screen is blocked until recovery succeeds. Screen exit clears
secret handoffs but retains unresolved readback identity in the current tab, so
returning cannot bypass recovery. This context is not durable across a full page
reload or tab closure. This readback capability does not change the owner's
receipt, expiry or authority checks, and does not turn a missing receipt into
proof that no write occurred.

Fee-correction previews also display the existing public material UUID as a
copyable recovery reference. After a reload or tab closure, the owner can enter
that reference with the account and trade in the dedicated read-only recovery
action. The owner API resolves the immutable binding to the original request
key and validates the matching event and material; it never returns the key or
confirmation token. The reference grants no authority. A missing receipt remains
unresolved, including after policy or confirmation expiry, and recovery never
resubmits a write. This manual recovery does not persist browser handoffs or
automatically discover and block unresolved requests across page reloads.

The internal request factory disables CSRF checks, so the actual outer browser
request must pass SessionAuthentication's CSRF enforcement. Owner APIs must still
recheck their own live permissions and transaction-bound session authority.

Original-material uploads may declare paired `file_name_field` and `max_bytes`
on a string/body file field. The filename destination must be a unique, required,
hidden string/body field on the same action. The browser derives both values from
the selected File: its exact name and strictly decoded UTF-8 bytes, preserving
BOM and line endings. Invalid encoding, empty material and excess byte size are
rejected before submission. Missing files cannot reuse an old filename or file
content. A subsequent hidden input cannot overwrite the derived name. The
declared limit must be positive and no larger than the workbench's existing
2 MiB limit; the fee-correction owner uses 1 MiB. Undeclared legacy file fields
retain their existing behavior. The owner still validates and hashes the stored
original bytes; this input contract does not confer source authenticity.
Canonical TUI audit masks file bodies and their declared filename destinations;
the owner's evidence store retains the original material. Ordinary action
parameters and outcomes remain in the audit record.

The executable contract lives in:

- `config/tui/schema/tui_metadata.schema.v3.json`
- `apps/terminal/application/tui_metadata.py`

New user-facing semantics:

- `screen.user_experience`
- `screen.action_density`
- `screen.dashboard_layout`
- `dashboard_panels[].user_priority`
- `dashboard_panels[].presentation_semantic`
- `actions[].result_semantics`
- `actions[].fields[].presentation_semantic`
- `actions[].view_model.field_presentations`
- `actions[].view_model.columns`
- `dashboard_panels[].row_actions`
- `dashboard_panels[].row_actions[].result_panel_key`
- `dashboard_panels[].row_actions[].refresh_panel_key`

## Information Architecture Source Of Truth

The versioned registry `config/tui/ia/tui_information_architecture.v1.json` is the only source of truth for TUI groups, modules, canonical screens, legacy aliases, the daily workflow, audiences, panels, and action-density budgets. Compiler promotion, database normalization, runtime injection, and deep-link resolution must load this registry; they must not maintain parallel screen-routing dictionaries.

The current contract has three groups (`daily`, `research`, `system`) and an eight-step daily workflow. The canonical screen inventories are the registry's `published_screens` and `runtime_screens` arrays; contract tests derive the expected keys from those inventories and explicitly cover role visibility and ownership. Adding, merging, or retiring a screen starts with this registry and its contract tests.

The `research` group is explicitly divided into four user-task modules: `investment-research`, `ai-workspace`, `personal-services`, and `personal-settings`. Do not recreate a generic research-tools catch-all or place account settings, personal service access, and asset research in one undifferentiated module.

The navigation renderer must collapse a redundant module heading when a group contains exactly one module with the same user-facing label. Multi-module groups retain both levels so their hierarchy remains explicit.

## Canonical User Vocabulary

- Use `宏观象限` for the four-quadrant market regime and `市场环境` for a broader market context. Do not expose `Regime` in user-facing metadata.
- Use `提示词` and `提示词模板与执行链`. Internal identifiers may retain `prompt`, but runtime labels, help text, and descriptions must not mix in `Prompt`.
- Use `观测时间` for `observed_at`. Use `数据基准日` when a date is an explicit calculation cut-off; do not alternate between `数据日期` and `观测日期` for the same concept.
- Distinguish personal and administrative entries in the label itself: `我的 AI 服务商` / `系统 AI 服务商治理`, `我的 MCP 接入` / `MCP 工具治理` / `MCP 用户与令牌`, and `账户与持仓` / `个人资料与交易设置`.
- Distinguish interaction modes as `AI 任务助手` and `命令行任务台`; neither label may silently stand in for the other.

## Screen Rules

Each screen must publish `user_experience`:

- `journey`: `dashboard | workspace | self_service | admin | toolbox | debug`
- `primary_task`: what the user is here to finish
- `primary_outcome`: what decision or artifact the user should leave with
- `empty_state_hint`: what to do when the screen opens empty or blocked
- `next_step_hint`: the immediate follow-up step

Hard rules:

- `dashboard` screens must publish `dashboard_panels`.
- Non-dashboard screens must publish `default_action_key`.
- User-facing copy must not leak `/api/`, `auto.api`, `param.api`, `GET`, `POST`, or path placeholders.
- Every screen must publish an explicit `audience`: `authenticated` for an ordinary signed-in user or `admin` for staff governance/debugging.
- Catalog filtering and direct screen loading must enforce the same audience rule.
- An explicit request for an unknown or forbidden screen must return a bounded 404/403 result. It must not silently substitute the home screen or another published screen.
- Access, governance, and debugging are independent journeys. Do not use shared step counters across roles.
- Runtime-owned journey screens/actions replace stale database-published entries by key. Deployment must not leave an obsolete self-service contract active merely because it was published earlier.
- Legacy screen keys resolve only through the registry alias map. Unknown keys retain the normal bounded 404 behavior.
- `action_density.primary_operation_limit` and `task_group_limit` control the visible action budget. The renderer may collapse overflow, but it must not hardcode per-screen business keys or limits.
- Published and runtime-owned IA screens derive those limits from the same registry defaults and per-screen overrides. Runtime injection must publish the budget before catalog/rendering, and normalization plus the density guard must cover both inventories. Protect default and P0 panel actions; retain all overflow action identities and execution policy through the existing support/advanced tiers. A selected-row read may be a contextual support action without becoming a global primary step; its required row parameters and result-panel binding remain mandatory.
- A newly rendered result-entry form represents a fresh explicit read. The duplicate-trigger guard must not discard that interaction merely because the preceding read completed within its guard interval. The exemption applies only to a distinct result-entry form and the existing passive-read classification; repeated events on the same form, mutations, confirmation-bound actions, and unresolved action references retain duplicate protection. Do not add sleeps or increase response timeouts to conceal a discarded submission.

## Task Deep-Link Rules

The shared shell exposes a selectable `TUI屏幕地址` location input to all signed-in
users. It displays `screen:<canonical-key>`, follows navigation and browser history,
accepts a screen address with Enter, and restores the current address with Escape.
This is a user-requested navigation control; keep it outside business result panels.

`research.signals` opens Alpha ranking in the general research scope. Research rows
must retain their scoring date and decision prohibition alongside the no-action
reason. Users can explicitly select portfolio scope; its readiness gate still
controls which portfolio candidates are returned. Never fabricate candidate rows
from stock-pool size or relax the owner service's decision gate to fill the table.

Classic compatibility pages and cross-screen task links use
`/tui/?screen=<screen-key>&action=<action-key>`. Additional query parameters
may prefill fields declared by that action.

- `screen` and `action` are reserved routing parameters and must never be sent
  to the owner API as business fields.
- A permitted safe read runs automatically only when all required fields are
  present. A write, admin, AI, confirmation-bound, or incomplete read is
  revealed and focused but never auto-submitted.
- `password` and `file` fields must never be prefilled from the URL.
- The action must pass the same audience filtering as the screen. A hidden or
  forbidden action produces a bounded unavailable status and must not fall
  through to a similarly named task.
- Normal in-app navigation removes a stale `action` parameter. Browser
  back/forward restores both the screen and task intent.
- Action overflow and support/advanced groups are expanded as needed so the
  requested permitted task is visible.

## Panel Rules

Panels express information hierarchy:

- `p0`: first thing the user must see
- `p1`: needed follow-up context
- `p2`: supporting or reference material

`presentation_semantic` defines how the panel should behave:

- `primary_status`
- `primary_list`
- `supporting_list`
- `copyable_secret`
- `endpoint_list`
- `multiline_prompt`
- `next_step`
- `supporting_detail`
- `debug_only`

Hard rules:

- Any screen with panels must expose at least one `p0` panel.
- `copyable_secret`, `endpoint_list`, and `multiline_prompt` panels must use `kind: detail`.
- A `p0` panel must point to an action or a target screen.
- Automatic panel loading is limited to passive reads. Admin reads may auto-load only when both the screen and action are admin-owned and the action belongs to the current screen; write/AI actions always require an explicit user action.

## Action And Field Rules

`actions[].result_semantics` marks result payloads that need non-generic treatment:

- `copyable_secret`
- `endpoint_list`
- `multiline_prompt`
- `primary_status`

Hard rules:

- Actions with `copyable_secret`, `endpoint_list`, or `multiline_prompt` must render as `detail`.
- Structured detail results must declare each field presentation explicitly as `secret`, `copyable`, `multiline`, or `metadata`.
- Copy and reveal controls are driven only by the declared field presentation. Labels and field names must not be used to guess whether a value is secret or copyable.
- `metadata` fields and token-history rows must never expose or copy a plaintext token.
- `actions[].view_model.columns` fixes the user-facing projection and order for important datagrid fields. It is required when generic inference could omit routing state, terminal state, or another task-critical value.

`actions[].fields[].presentation_semantic` marks user input intent:

- `identifier`
- `primary_selector`
- `api_token`
- `endpoint_url`
- `prompt_text`
- `debug_only`

Hard rules:

- `prompt_text` must use `textarea`.
- `endpoint_url` must use text input.
- `api_token`, `endpoint_url`, and `prompt_text` must use `value_type: string`.

## Self-Service Pattern

For self-service screens such as `screen:capability-router.self-service`, the first screen must expose:

- current usable credential state
- copyable connection endpoint set
- copyable onboarding prompt
- immediate next-step guidance
- in-place panel expansion for same-screen self-service cards; clicking a summary card must not hard-refresh the current screen

Do not require users to assemble these pieces from multiple generic detail actions.

The canonical MCP access package is one server-produced artifact containing:

- exactly one recommended active token, or a clear no-token/unavailable state
- route endpoint
- capability catalog endpoint
- minimal agent prompt
- environment statement, including a same-machine warning for loopback addresses

The screen must expose exactly one dominant “copy complete access package” control. Individual token and endpoint copy controls may remain secondary. Verification must be read-only: it may check token ownership/activity, routing readiness, and catalog readability, but it must not create, rotate, or revoke a token and must not call an AI model.

The primary credential state is one of four outcomes:

- access not enabled: explain who can enable it and the next step
- access enabled without a token: offer a default read-only token
- usable token: select one recommended token and expose show/copy/rotate controls
- unavailable or undecryptable token: explain why the old value cannot be recovered and offer rotation

Token history is supporting information. It shows only name, preview, level, creation/last-use state, and revocation state; it never returns a full plaintext token.

## Governance Table Pattern

Actionable governance rows publish validated `row_actions` metadata. Each descriptor must reference an action on the same screen, map every required action parameter from a published row column, and use an accessible row-specific label.

CRUD-style governance screens use a master-list workbench: the P0 table remains visible, while row reads and mutation receipts render into a declared same-screen result panel. `result_panel_key` identifies that result panel; `refresh_panel_key` identifies the data panel that must be reloaded after a mutation. A result-only panel may omit `action_key` and publish `empty_message` to guide the initial selection.

Hard rules:

- Row actions render as native buttons in a dedicated action column.
- Backend authorization, risk confirmation, and reauthentication remain authoritative; row actions do not bypass them.
- A successful mutation row action refreshes the affected panel so the operator can verify the new state.
- A read-only row action renders its returned detail/list result; it must not discard the result and only refresh the source panel.
- Row actions with `result_panel_key` must keep navigation, filters, and the source table in place; they must not replace the entire work area.
- Mutation actions should declare both `result_panel_key` and `refresh_panel_key`; the receipt remains visible while only the affected data panel refreshes.
- Tool governance tables with several action controls use a full-width panel at desktop size; do not compress the actionable table beside a summary panel.
- The operation column stays visible while a wide table scrolls horizontally.

## Portable Chart Pattern

Published chart actions use schema-owned projections rather than action-name checks in the
runtime. The production convention is:

```json
{
  "view_model": {
    "kind": "chart",
    "rows_path": "data",
    "columns": [
      {"key": "observed_at", "label": "日期"},
      {"key": "composite_score", "label": "综合脉搏"},
      {"key": "growth_score", "label": "增长"}
    ]
  }
}
```

The first column is the x-axis. Every remaining column is one numeric series, in published
legend order. The host projection produces `series[].points[]` with `{label, value}` pairs;
the common runtime renders those pairs without knowing screen keys, action keys, or business
field names.

Hard rules:

- Time axes use ISO 8601 values. Use timezone-aware datetimes when time-of-day matters;
  date-only business observations may use `YYYY-MM-DD`.
- Labels include the unit when it is not already unambiguous. Renderers do not infer scaling
  or convert percent/fraction semantics.
- Dashboard detail `field_rules` may declare `percentage_unit="fraction"` or
  `"percent"` only with `format="percentage"`. New percentage fields must declare
  the owner unit explicitly: fractions scale by 100, percentage points do not.
  Legacy fields without a unit retain compatibility behavior.
- The regime quadrant result declares `confidence_unit="percent"`; values below 1 retain
  their percentage meaning. Its four `quadrant_distribution` rows carry explicitly named
  `probability_percent` values and appear only when the owner permits current use. Show the
  actual observation date separately from the query cutoff, and keep stale/blocked reasons
  visible. Never reconstruct probabilities from a current marker or a missing observation.
- Non-numeric and non-finite values are omitted from the affected series, not coerced to zero.
- The generic host projection caps a chart at 240 source rows by deterministic even sampling,
  preserves the first and last observations, and publishes `source_row_count` plus `sampled`.
- Line charts may contain multiple series. Portable bar and pie charts use one series until a
  grouped/stacked contract is separately approved.
- Every chart exposes a visible textual series summary and legend. SVG geometry is decorative
  and must not be the only source of meaning.
- Empty and failed responses keep the chart panel bounded and show user-facing
  `empty_message`/error recovery text; raw exceptions stay in diagnostics.
- A production chart panel declares `empty_message`, `error_message`, and `stale_message`.
  Dashboard siblings remain visible if that panel fails.

`kpi_trend` result models use `label`, `value`, and `trend[]` points in the same
`{label, value}` shape. `table_chart` result models contain a `chart` object following the
chart result contract and a `table` object following the datagrid contract. These two kinds
currently require an explicit server/host projection; publishing only `rows_path` and
`columns` does not synthesize them.

The canonical production sample is the `pulse.history` action on
`macro-regime.overview`. It is the compatibility gate for later B-class chart migrations.

## Error And Recovery Contract

Screen and panel failures use a bounded user-facing shape:

```json
{
  "error_code": "stable_machine_code",
  "title": "short user-facing title",
  "detail": "safe explanation without raw exception text",
  "recovery_actions": [],
  "trace_id": "request correlation identifier"
}
```

Hard rules:

- Ordinary UI must not render raw exception messages, database column names, migration SQL, paths, methods, or stack traces.
- Page-level 404/403 failures preserve the requested context and offer a safe recovery destination.
- Panel-level failures keep successful sibling panels visible and provide retry or contextual recovery controls.
- Expected 404/403 responses may appear as failed network resources during acceptance; they are not unexpected console failures when the bounded UI renders correctly.
- Database readiness failures return bounded `503`; downstream execution failures return bounded `502`; neither surface may expose a raw exception.

## Layout And Interaction

- Self-service and admin dashboards use at most two columns at a 1440px desktop viewport; actionable MCP tool governance uses one full-width column.
- Screens whose P0 artifact has variable multiline height use `dashboard_layout: task_flow`; panels then follow one content-driven column and the main work area owns vertical scrolling. Use `adaptive_grid` for bounded summary cards.
- P2 supporting panels are collapsed initially.
- New controls use native interactive elements, visible `:focus-visible` treatment, and practical pointer/keyboard hit targets.
- Status meaning uses text in addition to color.
- Avoid nested panel scrolling when the main work area can own scrolling.
- These rules improve accessibility but do not, by themselves, establish complete WCAG conformance.

## Do / Don't

Do:

- publish `我的 MCP 接入` with P0 panels for token, endpoint, and prompt
- describe actions as `读取我的接入 Endpoint` instead of route names
- place revocation under support/operation, not ahead of the onboarding artifact

Don't:

- make the user open a raw token list before they can see the token they need to copy
- hide the Route API or Prompt behind debug drawers
- publish labels such as `route endpoint`, `catalog api`, `config detail`, `validate`

## Review Checklist

- Does the screen expose one clear primary task?
- Is the P0 information visible without drilling into unrelated support actions?
- Are token, endpoint, and prompt rendered with dedicated semantics when present?
- Does empty state tell the user what to do next?
- Does copy avoid endpoint/method/schema leakage?
- Does metadata pass schema + validator without relying on prose-only conventions?
- Does every new screen schema property have an explicit server projection policy?
- Does the runtime replace stale published access/governance metadata by key?
- Does an ordinary user see only the self-service journey and receive a bounded 403 on direct admin access?
- Are task-critical datagrid states and native row actions visible at 1440 × 1000?
- Does the happy-path browser flow complete with zero unexpected console errors or warnings?
- Do task-flow panels pass the three-viewport browser geometry guard with no overlap or horizontal overflow?

## Candidate selection controls

Passive primary-list panels may opt into `filter_fields`, an ordered list of the
action's `primary_selector` fields. Supporting-detail chart panels may also opt in
for passive range selection when their action is a GET read with no confirmation and
the selector is not hidden or sensitive. Schema and metadata validation reject
unknown, duplicate or unsafe selectors; write actions and secret controls remain
ineligible. These controls stay above the panel; submitting updates that panel and
retains the selection. For primary lists, every returned row remains accessible with
an actual loaded count. Candidate count defines the research set; page size only
controls browsing. The common panel renderer pages the loaded set at 20/50/100 rows
without rerunning the candidate query for each local page.
Other summary panels retain their `max_rows` limit.

`research.signals` exposes investment account and candidate count (1–500, default 10).
The account list is limited to the signed-in user. No account means general research;
an explicit account resolves to its owned active portfolio before querying candidates.
Missing mappings and foreign accounts fail explicitly, never falling back to general
research. Source dates and decision gates remain unchanged.

## Pagination, refresh and workspace continuity

- Summary tables identify the displayed prefix and offer a full-list entry when
  additional loaded rows or a following server page exist.
- Full lists expose page range, supported page-size controls and page navigation.
  Cursor lists do not invent a total count or random page access.
- F7 names its scope: current server page or loaded collection. It is not a
  replacement for server-side search over the entire dataset.
- Unpaged owner collections retain their returned rows and use client pagination;
  the host must not slice to the first 20 rows and fabricate server page access.
- Server page changes retain the old table while loading and on failure, clearly
  label the retained page, and offer a local retry. Pure page reads do not reload
  navigation badges.
- F5 only repeats passive reads or observes an existing queued run. AI/write
  submissions require their explicit action control.
- Session-local workspace restoration retains safe form fields and list controls,
  revalidates screen access and rereads business data. Passwords, secrets and file
  inputs are excluded; business result payloads are not persisted in browser storage.
- Primary progress is an operation checklist, not business approval or decision
  readiness. Its copy must say so and it must not count queued, failed, blocked or
  partial results as a completed operation.
- `shell-ready` and `p0-ready` are separate timing marks. Primary data loading must
  settle before auxiliary work is scheduled; failed panels retain bounded recovery.


## 2026-09-09 巡检修复契约

- 导航、恢复和刷新仅自动执行无确认、无未填必填参数的 GET/HEAD/OPTIONS 读取任务；AI、写操作与要求确认的读取任务展示表单。
- 面板按 `user_priority` 稳定排序；宽表独占一行，P2 折叠仅占标题高度，回执返回时自动展开。行操作保留首项，其余使用可键盘操作的原生 disclosure。
- 显式 `view_model.columns` 支持最多 16 列，schema 与运行时一致；通用推断维持紧凑列数，不得截断显式审核字段。完整列表保留筛选与行操作。
- 行操作可声明 `visible_when: {field, values, negate?}`；field 必须属于面板列，values 为非空标量列表。前端比较保留的原始状态值，服务端仍负责权限与状态校验。
- `presentation=secret` 对独立凭证和含凭证的完整接入包同样生效，且不依赖 action 是否声明结果语义；正文默认隐藏，复制保留完整内容。
- HTTP 成功只表示数据已读取；业务阻断、待审积压与超时必须分别呈现。详情展示嵌套标量与阻断原因，剩余详情按需展开。
- 验证依据见 `docs/reviews/vps-tui-page-design-audit-2026-09-08.md` 及其中修复验收记录。

## Alpha 更新异常呈现（2026-09-19）

Alpha 清单将最近一次相关推理的业务失败投影到现有 `business_summary` / `blocking_reason` 契约，包含真实评分日、目标日及尝试时间。dashboard 面板同样展示阻断原因，不能因空表或旧缓存而隐藏。任务异常只映射为安全用户文案，不呈现原始 traceback、凭据或其他组合的信息；新的成功评分清除旧失败。测试见 `tests/unit/dashboard/test_alpha_refresh_notice.py` 及浏览器 `dashboard displays blocking evidence` 用例。

2026-09-20：Dashboard 概览投影与数值格式化拆入 `TuiDashboardResultMixin`，由原 specialized mixin 继承，保持结果协议与现有调用入口不变。


## Task and professional presentation modes

The optional metadata root `experience` is owned by the IA registry. It declares
`home_screen_key`, `default_mode: task`, task/professional mode labels, passive screen
entries and local resume utilities. Entry destinations must be canonical, present
screen keys, and the experience home must match the metadata default screen;
duplicate entries, unknown modes and executable navigation payloads
are rejected. Compiler promotion projects this map onto its published screens;
runtime normalization overlays the complete IA map after injecting runtime screens.
The catalog then filters against the actual authorized visible screen inventory,
without modifying cached metadata. Metadata without this contract retains the
legacy professional navigation.

Mode preference is presentation state scoped to the signed-in user. A mode toggle
must not execute tasks, reload the current screen, rewrite routing/history, submit
forms or alter confirmation, continuation, credentials or retry identity. An explicit
screen/action deep link takes priority over a saved preference or local resume.
Unknown and forbidden explicit bootstrap destinations return bounded 404/403;
only a stale local resume may recover by opening the default entry.

Diagnostics are a separate server capability, never a third mode. Catalog
`diagnostics.raw_response_allowed` requires an authenticated, active principal
with a nonempty database identity and the existing administrator/RBAC policy.
An executed action also needs its own `raw_debug` policy to return raw data.
Ordinary and unidentified actors receive `debug.raw_available: false` and
`debug.raw_response: null`; hiding a drawer alone is insufficient. Existing result
continuation exclusion and output redaction remain mandatory. Business outcomes,
including partial/blocked/failed and nullable counts, retain owner semantics in
all modes. This repository contract does not establish production/user acceptance.

The experience validator is included in the repository cache contract fingerprint.
The runtime manifest also binds experience projection, workbench execution,
interface recovery and compiler promotion sources, so a changed server contract
cannot be represented by an unchanged frontend-only artifact identity.


IA panels may declare compiler-only `runtime_only: true` when their effective
contract belongs to runtime injection even though a stale published action key
still exists. Static promotion defers those panels, and references to known
runtime-only screens, rather than emitting invalid static references. Runtime
projection restores the complete IA panels and strips the compiler marker.
Unknown destinations still fail validation; selector and action-kind guards are
unchanged. Regression compares the complete effective owner endpoint, method,
risk, field, confirmation, session, continuation and raw-policy maps before and
after compilation. The standalone CLI must work without Django initialization.
