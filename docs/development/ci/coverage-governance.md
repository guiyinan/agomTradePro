# Coverage governance

## Source of truth

Coverage configuration is owned by `.coveragerc`. Thresholds and completion targets are owned by
`governance/testing_quality_baseline.json`. Workflows must not duplicate those values.

Python coverage is collected once and then projected into independent reports:

| Scope | Included source | Report |
|---|---|---|
| `apps` | `apps/` | `reports/quality/coverage-apps.xml` |
| `core` | `core/` | `reports/quality/coverage-core.xml` |
| `shared` | `shared/` | `reports/quality/coverage-shared.xml` |
| `sdk` | `sdk/agomtradepro/`, `sdk/agomtradepro_mcp/` | `reports/quality/coverage-sdk.xml` |
| combined/final | all configured Python sources | `reports/quality/coverage-final.xml` |

`scripts/generate_coverage_reports.py` is the only report projection command. It also writes
`coverage-manifest.json` with the commit SHA, UTC generation time, configuration digest and report
digests. `git_dirty` must be `false` for release evidence.

`coverage-final-details.json` preserves coverage.py's executable/missing line and branch-arc data.
`coverage-inventory.json` aggregates the same evidence by source scope, app module, architecture
layer, and file so prioritization does not depend on manually reading XML.

`scripts/generate_quality_report.py` reads those four scope reports and publishes their line and
branch values independently. Its `overall_coverage` is the `apps` repository value, not an average
of cumulative Unit/Integration/Guardrail reports.

## Branch measurement

Branch measurement is enabled globally. A report with `branches-valid=0` is rejected for every
required scope, even when its temporary branch threshold is zero. This prevents an old line-only
report from satisfying the gate.

The ratchet evaluates:

- `apps` repository line and branch coverage;
- per-App line coverage;
- optional per-App overrides from `coverage.module_minimums`, used to lock completed remediation
  modules above the shared core/default floor;
- Domain line and branch coverage, with `domain_module_minimums` and
  `domain_branch_minimums` providing explicit per-Domain floors while the shared defaults remain
  unchanged;
- independent line and branch totals for `apps/core/shared/sdk`;
- missing required reports.

New scopes begin with an observed baseline after a complete merged run. A temporary zero threshold
means “baseline collection is not complete”; it is not an accepted completion state. After T0
evidence is generated, each value must be replaced with the rounded-down reproducible result and
may only increase.

When independently developed branches change a scope's executable-branch denominator before they
are integrated, the integration branch must run the complete collection again and record a fresh
merged baseline. This is a denominator reconciliation, not permission to lower a threshold for an
unchanged code tree. The 2026-07-29 consolidation rebuilt the Domain branch baselines after 64
Domain files changed by 4,710 insertions and 2,178 deletions; subsequent changes ratchet from that
merged result.

The 2026-09-05 reconciliation is bound to commit
`d5f5e86963029e7c1dc353d2d2b7db2ef7c31d83`, Nightly run `33938041618`, coverage artifact
`9962383584`, and manifest SHA-256
`ec5a0dee1344f0bf7e38e00911e9af7c5198b1fbd703258f2b21d797a379088e`. The manifest reports
`git_dirty=false`; every report digest was reverified after download. All four source scopes passed
their existing line and branch floors, while 44 current Domains were remeasured after denominator
growth since the previous green Nightly. Four line floors use explicit per-Domain overrides instead
of weakening the shared 90% default, and every Domain branch floor is the complete run's
one-decimal rounded-down result. Restoring those four line exceptions to 90% and the ten decreased
branch floors to their pre-reconciliation values remains P2 test debt; the reconciliation itself is
not evidence that missing behavior has become tested.

## Local evidence workflow

Each pytest layer appends to the same coverage data:

```powershell
python -m coverage erase
python -m pytest tests/unit/ -q --cov --cov-config=.coveragerc
python -m pytest tests/component/ -q --cov --cov-config=.coveragerc --cov-append
python -m pytest tests/api/ tests/migrations/ -q `
  --cov --cov-config=.coveragerc --cov-append
python -m pytest tests/integration/ `
  -m "not live_required and not optional_runtime and not diagnostic" `
  -q --cov --cov-config=.coveragerc --cov-append
python -m pytest apps/ sdk/tests/ tests/e2e/ tests/guardrails/ -q `
  --cov --cov-config=.coveragerc --cov-append
python scripts/generate_coverage_reports.py --check
```

Do not run a second non-append pytest-cov command while a merged collection is in progress; it can
erase the shared `.coverage` file.

## Browser and frontend evidence

Browser coverage and Python import coverage are different evidence:

- `npm run test:tui-js:ci` writes `reports/quality/frontend-node-tests.xml`;
- Playwright writes JUnit, logs, screenshots, video or trace for user journeys;
- Playwright does not publish Python line coverage;
- Node and Playwright results are never merged into Python XML.

This keeps “Django modules were imported while a browser test ran” from being presented as proof
that frontend behavior or server branches were exercised.

## Failure handling

A complete baseline records every suite exit code. A failed layer does not authorize lowering a
threshold, increasing `omit`, or adding a skip. Fix the failure or record the suite as an explicit
unverified risk. Live network and optional runtime suites remain separately reported.
