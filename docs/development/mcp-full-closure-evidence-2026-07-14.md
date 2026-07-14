# MCP Full Closure Evidence

Date: 2026-07-14

Branch: `dev/feat-mcp-full-closure`

Pull request: [#2](https://github.com/guiyinan/agomTradePro/pull/2)

This record closes the 13 acceptance criteria in
`docs/superpowers/specs/2026-07-14-mcp-full-closure-design.md`. Dynamic counts
come only from `governance/governance_baseline.json`.

## Acceptance evidence

| # | Status | Direct evidence |
|---|---|---|
| 1 | Verified | The manually dispatched `Nightly Tests` workflow for the final branch head completed every stage: full unit, API/migration, integration, app-local, guardrail, architecture audit, Playwright smoke, and quality report. See the final GitHub Actions run linked from PR #2. |
| 2 | Verified | Backtest uses the Audit application facade, production settings copy mutable base middleware, and Realtime page/API URLs are physically separated. Their regression tests are included in the green Python 3.11/3.13 and Nightly suites. |
| 3 | Verified | Semantic Governance tests cover preview/apply/remove, sync survival, optimistic conflict handling, bounded invalid input, and immutable operator audit. Focused result: **47 passed** across domain, repository, service, API, sync, and migration tests. |
| 4 | Verified | `tests/unit/realtime/test_alert_domain.py` and `tests/api/test_realtime_alerts_api.py` cover crossing rules, single-fire state, validation, CRUD, and owner isolation. They are included in the **73 passed** Realtime suite. |
| 5 | Verified | `tests/integration/test_realtime_websocket.py::test_websocket_header_auth_commands_and_reconnect_restore` proves persisted subscriptions restore authenticated asset-group membership after reconnect. |
| 6 | Verified | `tests/integration/test_realtime_price_delivery.py::test_real_polling_delivers_one_price_and_one_single_fire_alert` runs the real `PricePollingService` through `ChannelPriceNotifier` to an authenticated `WebsocketCommunicator`. |
| 7 | Verified | The same delivery test receives one `alert.triggered`, polls again, receives only `price.update`, and proves no second alert event. Owner isolation is separately covered by WebSocket and REST tests. |
| 8 | Verified | Event Replay domain/service/API/repository/migration and MCP registry suite: **22 passed**. Tests prove registered targets only, preview without handler execution, succeeded/skipped/failed accounting, sanitized failures, idempotent replay, and conflict without a second handler call. |
| 9 | Verified | `governance/governance_baseline.json` records `unsupported_legacy_contract_count: 0`; owner replacement tests cover Realtime and Events, while the default top-level MCP tool budget remains seven. |
| 10 | Verified | MCP governance checks, consistency check, architecture layer guards for Python 3.11/3.13, structure audit, and local guardrails all pass. The machine baseline is `2026-07-14.v129`. |
| 11 | Verified | Real-browser acceptance used an administrator and ordinary user. It exercised owner-scoped alert/subscription creation, staff replay preview/commit/result, ordinary-user denial, and the split MCP access/governance journeys. Masked role/navigation/error evidence is in `output/playwright/tui-capability-router-audit/`; secret-bearing session snapshots and temporary users/data were removed after acceptance. |
| 12 | Verified | Operations and rollback are documented in `docs/development/quick-reference.md` and `docs/integration/realtime_data_system.md`. The TUI redesign audit records completed/incomplete/verified/unverified scope and explicitly retains production proxy, scale, and complete WCAG as non-goal risks. No required acceptance item is unverified. |
| 13 | Verified | The branch contains focused commits, is pushed, and has one reviewable PR. PR #2 checks for Architecture, Fast Feedback, Consistency, MCP Governance, Security, and Python 3.11/3.13 are green at the final head. |

## Verification inventory

- Semantic Governance focused suite: **47 passed**.
- Realtime REST/domain/Channels/SDK/MCP suite: **73 passed**.
- Event Replay domain/service/API/migration/MCP suite: **22 passed**.
- TUI metadata compiler: **41 passed**.
- TUI workbench: **213 passed**.
- Account API edges: **26 passed**.
- Terminal Agent + SDK client + internal SSL redirect: **32 passed**.
- MCP inventory + polling regression: **3 passed**.
- Guardrails: **133 passed** in one final isolated-worktree run. Current PR architecture/governance checks are green.
- `python manage.py makemigrations --check --dry-run`: no changes detected.
- `python manage.py check`: no issues.
- `node --check static/js/tui-workbench.js`: passed.
- Documentation/API/SDK consistency checker: passed.

## Browser acceptance record

The local browser run used the current migrated development database and a
1440×1000 viewport. Temporary administrator and ordinary-user identities were
created only for acceptance and deleted afterward together with their replay,
alert, subscription, token, profile, and simulated-account rows.

- Administrator: access, governance, and debug modules visible; tool/user row
  actions visible; event replay preview and confirmed execution returned a
  bounded result.
- Ordinary user: only personal MCP access visible; direct governance access
  returned structured 403; alert and subscription operations remained owner
  scoped.
- Unknown screen: structured 404 with trace ID and recovery actions; no silent
  home substitution.
- Console/network: no unexpected errors in normal flows. The deliberate 404 and
  403 each produced the expected failed resource entry and bounded UI.
- Secret hygiene: all retained screenshots are masked; `.playwright-cli/` is
  ignored and its secret-bearing snapshots were deleted.

## Operational limitations and non-goal risk

- The focused WebSocket delivery uses Django Channels' in-memory test layer to
  prove application-to-consumer behavior. Production configuration requires a
  reachable Redis channel layer; readiness tests cover missing, unreachable,
  and reachable Redis outcomes. A production Redis capacity/load exercise is a
  deployment concern, not an unverified functional acceptance item.
- Public Route/Catalog URLs behind the production reverse proxy must be checked
  during deployment; the local browser correctly warns that loopback addresses
  are same-machine only.
- Complete WCAG 2.2 conformance, 200% zoom, screen-reader matrices, and very
  large governance-table visual load are not claimed by this closure.
- No Docker files or deployment topology were added or changed.

## Rollback order

1. Set `EVENT_REPLAY_ENABLED=false` to stop preview and commit replay.
2. Set `REALTIME_WEBSOCKET_ENABLED=false` to stop new sockets and broadcasts.
3. Keep REST price polling and persisted alert/subscription data available.
4. Roll back application code only after active ASGI connections drain; reverse
   migrations only after explicit data-loss review.
