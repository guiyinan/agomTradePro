# Research R1 forecast promotion decision coverage plan

## Purpose

This bounded slice closes reachable Domain validation branches in
`apps/research/domain/r1_forecast_promotion_decision.py`. It is a test and
evidence exercise only. The production Domain file is unchanged, and this
slice does not change Research policy, provider behavior, persistence, or
production acceptance.

## Controlled scope

The baseline and final runs use the same five existing R1 unit scopes. The
final run adds only
`tests/unit/research/test_r1_forecast_promotion_decision_missing_boundaries.py`.
The tests construct the existing Equity trial through `_eligible_result`,
`_ineligible_result`, `_policy`, and `_decision`, then exercise the public
frozen dataclass constructors and `dataclasses.replace`. No `object.__new__`,
provider, database, PostgreSQL, VPS, or network path is involved.

The candidate test covers malformed authority tokens, hashes, clocks, Decimal
intervals, policy gates, policy identity, forecast identity, metric and
invalidation evidence, trial-seal completeness, and decision-window and
research-only guards. Each case asserts the corresponding fail-closed error.

## Measured completion

The controlled baseline ran 48 tests. The final run ran 55 tests and exited 0.
For the target file, branch coverage moved from 89/134 (66.4%) to 129/134
(96.3%), closing 40 baseline missing arcs. Statement coverage moved from
346/394 (87.8%) to 389/394 (98.7%). The final missing-arc set has no members
outside the baseline set (`new_missing_arcs=[]`). The exact commands, JUnit,
coverage JSON/XML, stdout/stderr, copied `.coverage`, and SHA-256 references
are sealed in
`docs/testing/research-r1-forecast-promotion-controlled-branch-increment-2026-09-14.json`.

The current whole-Research measurement remains a separate 1,035-test result.
This R1 slice must not be added to that global measurement or presented as a
whole-Research 90% result.

## Explicit remaining boundaries

Five arcs remain uncovered and are recorded in the seal:

- Empty forecasts and cross-semantic forecasts cannot be supplied by the
  current valid Equity artifact/result constructors, which require exact
  forecast periods and one artifact scope.
- A cross-scope actual manifest is rejected by the valid Equity trial's
  manifest/member binding before R1 projection.
- `R1PromotionScope` itself enforces the `research/r1/valuation` authority,
  so a valid nested scope cannot substitute another authority.
- `ForecastBaselineTrialResult.__post_init__` rejects non-research flags
  before the R1 factory receives such a result.

These are documented residual upstream-invariant paths; the tests do not
forge objects to claim them as covered.

## Acceptance and rollback

Acceptance for this slice is the final same-scope exit-0 run, zero new missing
arcs, stable target source raw/canonical-LF SHA and Git blob OID, and complete
artifact references in the public seal and sidecar. The test commit is
independent of any production commit and can be reverted without changing
runtime behavior. No production deployment or governance promotion is
claimed by this plan.
