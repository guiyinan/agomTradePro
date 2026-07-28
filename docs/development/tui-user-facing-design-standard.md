# TUI User-Facing Design Standard

> Last updated: 2026-07-21

This standard defines the user-facing contract for AgomTradePro `/tui/`. It exists to stop TUI screens from degenerating into route browsers, endpoint lists, or raw JSON shells.

## Core Rule

Every published TUI screen must optimize for user completion, not interface exposure.

- One screen serves one primary user task.
- P0 information is visible on the first screenful.
- Copyable artifacts such as token, endpoint, and prompt are shown with dedicated semantics, not buried in generic detail dumps.
- Raw endpoint, method, schema, and compiler details are implementation metadata. They do not belong in ordinary user-facing copy.
- Literal connection addresses may appear inside an explicitly copyable access artifact; their labels, help text, errors, and surrounding workflow must remain user-facing and must not expose route/compiler jargon.

## Required Metadata Contract

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

The current contract has three groups (`daily`, `research`, `system`), 12 published screens, 11 runtime screens, and an eight-step daily workflow. The registry separates published inputs from runtime inputs so both inventories are mechanically testable. Adding, merging, or retiring a screen starts with this registry and its contract tests.

The navigation renderer must collapse a redundant module heading when a group contains exactly one module with the same user-facing label. Multi-module groups retain both levels so their hierarchy remains explicit.

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

## Task Deep-Link Rules

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
