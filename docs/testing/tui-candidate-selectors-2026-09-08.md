# Candidate account and count selectors — 2026-09-08

## Completed

- The Alpha candidate panel now exposes investment account and count controls above
  the results. Count defaults to 10 and accepts 1–500. An update stays in the panel,
  retains choices and shows the actual returned count, including zero.
- No account selects general research. The account selector contains only accounts
  owned by the signed-in user. An explicit account resolves its existing owned active
  portfolio, then queries portfolio candidates. Missing, inactive and foreign mappings
  fail explicitly; they never fall back to general research or create ledger mappings.
- Optional `filter_fields` is synchronized across IA, schema, metadata validation and
  browser runtime. Other panels retain their existing row limits and field labels.
- New panel requests supersede earlier requests; navigation still cancels panel reads.

## Validation

- Account service and HTTP contract tests: 8 passed, covering ownership, mappings,
  count/scope forwarding, JSON statuses and absence of fallback on failure.
- Combined Alpha views, TUI workbench, source consistency and IA regression: 426 passed,
  2 label regressions found. Labels were then limited to explicitly declared panel
  filters; both failures and related Alpha/account/projection tests passed in a focused
  rerun: 10 passed, 301 deselected. The full combined suite was not rerun after that fix.
- Invalid/unsafe filter metadata: 6 passed.
- Frontend suite: 48 passed. Final generated bundle selector test also passed after
  adding the zero-row count presentation.
- Incremental mypy for 6 production files: zero regressions; final catalog recheck:
  zero regressions. Full mypy debt ceiling: zero errors, baseline unchanged.
- Current-data guard: 53 surfaces. Template inventory, runtime build/check,
  Black/isort/Ruff and diff whitespace checks passed.

## Deployment and live browser acceptance

- Code-only hot update of 15 explicit files. Web restarted, health 200, nine containers
  running; release hashes and container/static markers verified.
- Backup: `/opt/agomtradepro/manual-file-backups/20260908105326`.
- Predeployment comparison matched all existing target files to the committed base.
  The new account selector service had no prior remote file. No migration was applied.
- Authenticated Playwright browser verified default 10 rows, changing to 20 rows,
  selecting an owned linked account, rejecting an unlinked account with a specific
  explanation, and returning to general research with 20 rows and preserved controls.
- Two owned account choices were available. The linked account currently returned zero
  portfolio candidates under the existing readiness rules. The unlinked account remains
  unlinked; this change does not create account/portfolio associations or relax gates.
- Viewports 390, 768 and 1440 px: no horizontal page overflow. No browser page errors.
- Raw acceptance summary: `tui-candidate-selectors-live-2026-09-08.json`.
  Local screenshot: `reports/quality/tui-candidate-selectors-live-2026-09-08.png`.
- The first browser probe used an overly strict label selector and failed to locate the
  account control. DOM inspection confirmed correct options; the completed probe uses
  the control's declared field name. No product change was needed for that probe issue.

## Remaining boundaries

Requested UI and selection behavior are complete and live. No sustained load test or
new account association was performed. The original source dates and decision
prohibitions still govern candidate availability.
