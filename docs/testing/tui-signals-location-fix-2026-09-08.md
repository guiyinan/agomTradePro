# TUI selection and location repair — 2026-09-08

## Completed

- Restored the shared shell's `TUI屏幕地址` input for ordinary users and administrators,
  retaining selection/copy, Enter navigation, and Escape restoration.
- Changed `dashboard.alpha-ranking` to default to the existing general research scope.
  The production portfolio scope returned zero visible rows because its scoped Alpha
  result was not ready; the existing general scope returned ten research rows.
- Published eight result columns: combined security code/name, Alpha score, scoring
  date, decision prohibition, gate status, suggested position, inclusion reason, and
  no-action reason. The compact panel preserves the date and prohibition within its
  first six columns; the full task shows all eight.
- Kept the portfolio choice and owner-service readiness checks intact. No source
  timestamp, score, execution gate, or stock-pool membership was changed.

## Validation

- `pytest tests/unit/test_tui_workbench.py tests/unit/test_tui_actionability_contract.py tests/unit/test_tui_metadata_source_consistency.py tests/unit/terminal/test_tui_information_architecture.py -q --no-cov --nomigrations --basetemp=pytest-tmp-tui-final`: **382 passed**.
- The new research-default regression first failed on the previous `portfolio` default.
- Two authenticated shell rendering tests also passed with normal test migrations.
- Production-template browser test: **1 passed**, covering 1440, 768, and 390 px widths,
  visible address input, Enter navigation, and Escape restoration.
- Incremental mypy: zero regressions; full mypy debt ceiling: zero errors.
- Black, isort, Ruff, `npm run check:tui`, and template migration inventory passed.

## Deployment and live verification

- Mode: `hot-update code-only`; only Web restarted.
- Backup: `/opt/agomtradepro/manual-file-backups/20260908100333`.
- Files: `core/templates/terminal/tui_workbench.html`,
  `apps/terminal/infrastructure/tui_metadata_runtime_injection_dashboard_alpha.py`,
  `config/tui/ia/tui_information_architecture.v1.json`, and
  `config/tui/agomtui-runtime.manifest.json`.
- Predeployment comparison confirmed that these changes did not overwrite unrelated
  production source changes. Release checksums matched local files; container markers
  were verified; HTTPS health returned 200 and all listed containers were running.
- Authenticated production template: 200, location input present.
- Production screen metadata: `alpha_scope` defaults to `general`.
- Actual default TUI action: 200, **10 rows**, all names present, all scoring dates
  `2026-09-04`, and every row explicitly prohibited from decision use.

## Remaining limitations

- This repairs research visibility; it does not complete portfolio-specific inference
  or refresh the historical scoring date. Research results remain decision-blocked.
- Browser interaction was verified against the actual repository template with test
  responses; live verification used authenticated HTTP, not a signed-in browser UAT.
- This Web restart is a new operational event. Earlier uninterrupted observation
  windows must not be treated as continuing through it; this repair does not attest
  M5 retained-window or release-governance closure.
- Rollback point is the four backed-up files above; restoring them requires a Web
  restart. No database restore is part of this patch.
