# TUI User-Facing Design Standard

> Last updated: 2026-07-09

This standard defines the user-facing contract for AgomTradePro `/tui/`. It exists to stop TUI screens from degenerating into route browsers, endpoint lists, or raw JSON shells.

## Core Rule

Every published TUI screen must optimize for user completion, not interface exposure.

- One screen serves one primary user task.
- P0 information is visible on the first screenful.
- Copyable artifacts such as token, endpoint, and prompt are shown with dedicated semantics, not buried in generic detail dumps.
- Raw endpoint, method, schema, and compiler details are implementation metadata. They do not belong in ordinary user-facing copy.

## Required Metadata Contract

The executable contract lives in:

- `config/tui/schema/tui_metadata.schema.v3.json`
- `apps/terminal/application/tui_metadata.py`

New user-facing semantics:

- `screen.user_experience`
- `dashboard_panels[].user_priority`
- `dashboard_panels[].presentation_semantic`
- `actions[].result_semantics`
- `actions[].fields[].presentation_semantic`

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

Do not require users to assemble these pieces from multiple generic detail actions.

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
