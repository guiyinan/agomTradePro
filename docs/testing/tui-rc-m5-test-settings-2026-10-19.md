# M5 test settings isolation — 2026-10-19

The Fast Feedback run `39262270501` for `cbdccd361814a5d10039f837de46f3b18bbe230e`
failed on both Python versions: 277 passed, one failed and one skipped. The unchanged
runtime mock guard rejected the M5 synthetic-calendar installation in
`core/settings/playwright.py`. The other four ordinary workflows succeeded.

The installation now belongs to `tests.settings.m5_playwright`, which inherits the
existing browser settings. The core settings retain their SQLite NAME/TEST binding
and throttling. The RC journey environment, migration and managed server use the
same test settings module. Calendar/universe guards require that exact module;
Signal and M5 helpers preserve the original settings identity when calendar opt-in
is absent. Nightly smoke and the generic evidence recorder retain their existing
settings. No application mock guard, runtime request scope, CI/loopback/database
guard, health timeout, minimum test count, no-skip rule or UAT selection changed.

Actual checks on the nine applied paths:

- 42 tests passed, with no failures, errors or skips: calendar scope/sample,
  unchanged runtime mock guard and generic evidence-recorder contracts.
- Three separate settings-import probes passed: core settings remain inert even
  with the fixture flag; the new module is inert without opt-in and installs
  exactly the existing app/middleware with valid opt-in. All retain exact DB binding.
- Black, isort, Ruff, incremental mypy (zero regression/legacy errors), full
  production mypy debt (zero errors), module-map check and scoped diff check passed.
- Independent Luna static review found no blocking issue. Parent verified actual
  Git preimages separately from CRLF worktree hashes; the original candidate's
  raw-blob labels are corrected in the adoption receipt, without rewriting history.

Raw logs, JUnit, source bytes, candidate and adoption receipt are preserved in the
local-only archive
`C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/m5-test-settings-split-cbd-verified/`.
Its `index.json` SHA-256 is
`c67d2aff229b5be727175a784f1fbe0204ae24095c12d83cdf50c4742fba12b2`.
The original failed CI remains in the separate `cbd-ci-and-typed-core-member-r1`
archive, index SHA-256
`eec1d5ee3de904dc777036b27cbe90f070761b812829f0667b560c9a898c3983`.
Neither archive has been uploaded remotely.

These checks validate test configuration and isolation. Full M5 browser execution,
the final immutable candidate's RC/independent Publication PostgreSQL artifacts and
fresh S6 remain separate requirements. This change was not deployed and grants no
production data, activation or UAT qualification.
