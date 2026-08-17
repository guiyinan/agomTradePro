# TUI Unified Operator Home Implementation

Date: 2026-07-07

## Scope

This change closes the TUI operator experience around a single unified `/tui/` home and a parallel governance workflow without upgrading the published TUI metadata schema.

## Implemented

- `command-center.overview` now acts as the unified operator home.
- Home panels are fixed to six sections:
  - decision queue
  - market context
  - account and signal summary
  - system exception summary
  - data and task summary
  - AI and config summary
- Added operator read APIs:
  - `GET /api/tui/operator/home/`
  - `GET /api/tui/operator/governance-queue/`
- Added a six-step governance workflow:
  1. `api-library.runtime`
  2. `api-library.data-center`
  3. `ai-ops.providers`
  4. `ai-ops.agent-runtime`
  5. `execution.account-settings`
  6. `api-library.config-center`
- `/terminal/` remains an independent parallel entry and is reachable from the TUI home and governance workflow strip.
- Added browser-local operator state:
  - `last_non_home_screen`
  - `pinned_screen_keys`
  - `preferred_home_lane`

## Frontend Behavior

- Home renders four fixed operator actions:
  - continue daily decision flow
  - enter governance flow
  - resume last workspace
  - open CLI
- Governance badges are shown in the module tree and on home cards.
- Clicking a screen row or badge with governance counts now drills into that screen's governance summary instead of only opening the workspace shell.
- Pinned screens are sorted to the front inside each module.
- Refresh from a non-home screen restores the last non-home workspace in the same browser session.
- Governance datagrid rows expose a direct drill-down action into the target handling screen.

## Backend Notes

- Aggregation stays in `apps.terminal.application.tui_operator_services`.
- Terminal app orchestration only calls application-layer services and facades.
- Governance summary actions now use hidden `domain` fields instead of query strings in action metadata so they remain compatible with the existing action runner contract.
- Runtime screen patch filtering now drops dashboard panels whose `target_screen` does not exist in the active payload, which keeps metadata validation stable for minimal test payloads.
- Operator-home performance now uses lighter summary paths than the detailed governance screens:
  - the home decision queue calls `TodayDecisionQueueQueryService(..., include_system_health=False)` so `/tui/` does not block on expensive Celery and Alpha consistency probes that already have dedicated治理面板
  - the canonical `GET /api/decision/workspace/today-queue/` fast path follows the same rule, so IA consolidation cannot accidentally reintroduce synchronous health probes into the P0 home panel
  - the home `config-center` governance card reads runtime config, active model, local qlib trade-date lag, and training-run presence directly instead of building the full Alpha/Qlib ops overview payloads
  - the home six-panel dashboard reads `GET /api/tui/operator/home/<section>/` directly for fixed summaries instead of routing those cards back through the generic action runner

## Verification

- `pytest tests/unit/test_tui_workbench.py -q`
- `pytest tests/unit/test_tui_operator_services.py -q`

## Production hardening (2026-08-17)

- TUI internal action admission now supports the six-panel decision dashboard without
  rejecting cold-start bursts: the default concurrency is six and saturated requests wait
  for a short bounded admission window before returning `tui_action_busy`.
- Global governance badges use a five-minute fresh cache and may reuse a fifteen-minute
  stale snapshot. Detailed domain drilldowns still rebuild their own domain-scoped payload,
  so navigation polling cannot repeatedly block ordinary task screens on the full governance
  aggregation.
- Alpha/Qlib cache fallback remains available to keep the UI inspectable, but Celery now
  publishes it as `outcome=partial` with one failed fresh operation and one stored fallback.
  A degraded forward-fill therefore no longer appears as a fully successful refresh.
