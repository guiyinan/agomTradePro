# TUI User-Facing Design Standard

> Last updated: 2026-07-14

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
- `screen.dashboard_layout`
- `dashboard_panels[].user_priority`
- `dashboard_panels[].presentation_semantic`
- `actions[].result_semantics`
- `actions[].fields[].presentation_semantic`
- `actions[].view_model.field_presentations`
- `actions[].view_model.columns`
- `dashboard_panels[].row_actions`

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

Hard rules:

- Row actions render as native buttons in a dedicated action column.
- Backend authorization, risk confirmation, and reauthentication remain authoritative; row actions do not bypass them.
- A successful mutation row action refreshes the affected panel so the operator can verify the new state.
- A read-only row action renders its returned detail/list result; it must not discard the result and only refresh the source panel.
- Tool governance tables with several action controls use a full-width panel at desktop size; do not compress the actionable table beside a summary panel.
- The operation column stays visible while a wide table scrolls horizontally.

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
- Does the runtime replace stale published access/governance metadata by key?
- Does an ordinary user see only the self-service journey and receive a bounded 403 on direct admin access?
- Are task-critical datagrid states and native row actions visible at 1440 × 1000?
- Does the happy-path browser flow complete with zero unexpected console errors or warnings?
