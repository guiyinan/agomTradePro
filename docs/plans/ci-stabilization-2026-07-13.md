# CI Stabilization - 2026-07-13

## Scope

This closure is limited to failures observed in the `Logic Guardrails` push run
and the recurring `main` nightly run. It does not change the SDK route-contract
work already in progress in the working tree.

## Completed

- Align default MCP registration tests with the governed seven-core-tool surface.
- Keep legacy task and proposal tool execution tests isolated from default registration.
- Make the terminal MCP Python entrypoint assertion portable across Windows and Linux.
- Prevent explicit `.OF` fund codes from falling through to equity remote hydration.
- Prefer configured rotation names for ETF display-name stability.
- Restore cache-first then hydrate-on-miss behavior in equity valuation analysis.
- Validate the staff-only policy RSS fetch payload with a staff test client.

## Regression scope

Verified locally with Python 3.13:

- `tests/unit/test_asset_name_resolver.py`: 11 passed.
- Agent Runtime M2/M3/M4, core naming, and terminal agent service: 97 passed.
- Policy API edges, equity use cases, and dashboard alpha queries: 45 passed.
- `tests/unit/test_tui_workbench.py`: 188 passed.
- `sdk/tests/test_sdk/test_client.py`: 19 passed.
- `tests/unit/test_internal_ssl_redirect.py`: 2 passed.
- Focused six-test regression for the exact CI failures: 6 passed.
- Ruff checks for the focused changed-file set passed before preserving the
  pre-existing formatting style of the M4 regression file.
- `git diff --check` passed.

Not verified locally:

- Python 3.11, because no complete Python 3.11 project environment is installed.
- The full 3,100+ test Logic Guardrails matrix.
- The complete nightly pipeline after the unit-test stage.

## Risks and rollback

- Asset-name precedence changes only for explicit `.OF` identifiers and configured
  rotation assets; revert the resolver ordering block if a conflicting canonical
  naming rule is established.
- Legacy MCP tools remain available only through their explicit compatibility path;
  the default server registration remains core-only.
- Full nightly and the complete Logic Guardrails matrix remain required before merge.
