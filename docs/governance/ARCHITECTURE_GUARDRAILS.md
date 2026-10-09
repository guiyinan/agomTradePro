# Architecture Guardrails

> Last updated: 2026-10-09
> Dynamic governance machine source of truth: `governance/governance_baseline.json`

This document defines how repository-wide architecture and governance checks are enforced.
It documents rules and verification entrypoints only; it must not maintain copies of
current governance counts.

## Evidence levels and RC composition

`rc-gate.yml` calls the same six reusable workflows used by daily CI and Nightly at
the candidate commit, then adds mandatory browser journeys. RC does not maintain a
second copy of lint rules, coverage floors, database tests or security policies.
`scripts/rc_gate_report.py` defines the required job set and aggregates actual
same-run `needs.*.result` values. Regression tests verify workflow wiring against
that set. Failure, cancellation, skipped jobs, absent results and unknown candidate
identity all block RC. Reports and available journey evidence are retained on failure.

| Gate | Evidence level and blocking policy | What passing proves | What passing does not prove |
|---|---|---|---|
| Local pre-commit | Local formatting; effective only if installed | Selected files passed the installed hooks | Remote CI success, tests, production acceptance |
| Architecture Layer Guard | Blocking static checks | Registered layer boundaries, dependency budgets and module-map projection pass | Business behavior or runtime correctness |
| Consistency Check | Blocking static/contract checks | Registered source markers, inventories, API/documentation projections and ownership rules agree | That every registered test ran, or real providers/production satisfy the contract |
| CI Fast Feedback | Blocking incremental checks and selected tests | Selected changed files pass lint/type checks; production mypy debt ceiling and selected test/Domain gates pass | Full regression, full-repository style cleanliness or production acceptance |
| Security Scan | Blocking at configured severity/exception policy | Bandit HIGH, declared dependency vulnerabilities, gitleaks and npm high-severity gates pass | Absence of all vulnerabilities; Bandit MEDIUM remains a warning and explicit advisory exceptions remain visible in the workflow |
| Nightly Tests | Blocking regression/coverage and isolated PostgreSQL jobs | Configured suites, scope/Domain coverage ratchets, migrations, backup restore and reliability checks pass in CI | Live/optional/diagnostic suites excluded by markers, real production recovery or deployment approval |
| Nightly full lint | Observe-only (`continue-on-error`) | Reports whole-repository style findings separately | A blocking lint approval; the report uses step `outcome`, so a tolerated failure is still reported as failed |
| Publication PostgreSQL contracts | Blocking isolated PostgreSQL tests | Registered lock, authority, publication, role and reconciliation tests execute successfully; missing/skipped required evidence is rejected | Production data completeness, live credentials or current production authority |
| RC browser journeys | Blocking browser tests against an isolated CI server | At least 20 selected cases, no skips, no errors/failures | Real-user production UAT, external AI tests marked `live_required`, or acceptance of every possible journey |
| RC Gate Summary | Blocking aggregate of all required jobs | This candidate passes the configured repository verification package | Zero P0/P1 defects, production readiness, release authorization or permission to deploy |
| S6 release rehearsal | Separate candidate/configuration-bound rehearsal evidence | Required reports validate for the exact candidate, frozen policy/provider/universe and rehearsal environment | A live deployment, continued validity after configuration drift or production acceptance |
| Production acceptance / runtime decision gate | Separate target-environment evidence and runtime checks | Only the properties actually evidenced for that candidate/environment/window | Cannot be inferred from CI green, HTTP health, Celery SUCCESS or the newest database row |

Incremental scope remains event-dependent: PRs compare the target branch, pushes
use the event base with the existing rewritten-history fallback, and manual RC
may supply an ancestor `base_ref` for cumulative Fast Feedback. With no explicit
base, manual/tag fallback may cover only the last commit. RC therefore always
runs the complete Nightly and PostgreSQL workflows regardless of that selection.
Incremental evidence must never be described as whole-release lint coverage.

Coverage thresholds come from `governance/testing_quality_baseline.json`;
`run_incremental_domain_coverage.py` reads its Domain floor, and a local override
may only strengthen it. Nightly uses the same baseline for scope and per-Domain
line/branch floors. See [coverage governance](../development/ci/coverage-governance.md).

Quality reports distinguish coverage availability from actual test outcomes.
An XML coverage file can exist after test failure and cannot set a suite to passed.
Nightly reports consume `steps.*.outcome`; absent execution evidence is `unverified`.
RC reports always publish `production_acceptance=unverified`,
`deployment_authorized=false` and `defect_inventory=unverified`, even when all CI
jobs pass. The former TODO/FIXME scan and fabricated P0/P1 counts are removed.
An actual defect inventory or production acceptance requires separate evidence.

GitHub branch protection is remote administrative state, not proven by these YAML
files. Configure required checks for the protected branch in GitHub; the repository
must not claim that merge enforcement was verified merely because workflows exist.
This change does not alter S6 required reports or any production authorization.

## Checks

The project uses complementary guardrails:

1. `scripts/check_architecture_delta.py`
   - Runs in `.github/workflows/architecture-layer-guard.yml`.
   - Scans changed lines in pull requests and pushes.
   - Fails immediately for new Domain/Application/Interface layer violations.
   - Also hard-fails new audit-rule regressions because CI enables `--include-audit --fail-on-audit-violations`.

2. `scripts/verify_architecture.py --rules-file governance/architecture_rules.json --format text --include-audit --fail-on-audit-violations`
   - Runs as a full-repository architecture audit gate.
   - Fails on both boundary violations and audit violations.
   - Current hard checks include Application ORM access, transaction ownership, Interface infrastructure imports, Domain runtime imports, naive datetime usage, retired shared compatibility imports, and app-root model shim misuse.
   - The shared model resolver is forbidden in Domain/Application/Interface. Its literal fallback modules and app labels are recorded as dependencies, including imported aliases and keyword arguments. Unknown resolver arguments still fail closed through the resolver dependency. Incremental checks consider the complete multiline import/call span, so changing only a fallback target cannot evade the guard.

3. `scripts/check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json --fail-on-cycles`
   - Locks app-level cycles to zero.
   - Blocks new bidirectional pairs and strong cycle components.
   - Locks total app import edges, global inbound/outbound fan-in/fan-out, and per-app `max_outbound_modules_by_app` / `max_inbound_modules_by_app`.
   - Fails on stale baselines when dependency debt decreases without tightening `governance/module_cycle_allowlist.json`.

4. `scripts/check_governance_consistency.py --baseline governance/governance_baseline.json --format text`
   - Runs in `.github/workflows/consistency-check.yml`.
   - Scans the whole repository for governance drift.
   - Current report sections:
     - `governance_baseline`
     - `docs_consistency`
     - `docs_links`
     - `governance_docs`
     - `module_shape`
     - `misplaced_app_config`
     - `singular_dto_files`
     - `architecture_ruleset`
     - `module_dependency_baseline`
     - `ci_governance_wiring`
     - `application_third_party_imports`
     - `core_integration_debt`
     - `core_management_command_debt`
     - `large_python_files`

5. `scripts/select_quality_targets.py`
   - Runs in `.github/workflows/ci-fast-feedback.yml`.
   - Selects changed Python files for incremental `ruff` / `black` / `isort` / `mypy`.
   - Also selects changed domain modules for the incremental Domain coverage gate; the runner includes app-owned tests plus unit tests that directly import the selected Domain package.

6. `scripts/check_business_configuration_hardcodes.py --mode full`
   - Runs in `.github/workflows/consistency-check.yml`; its mutation-style self-tests run in `.github/workflows/ci-fast-feedback.yml`.
   - Reads `governance/business_configuration_contracts.json` and scans the configured production Python roots with the AST.
   - Rejects static historical-scenario catalogs, 4x4 allocation policies, Policy multipliers, recommendation thresholds, arbitrary stress-test principals, and repository-to-static-configuration fallbacks.
   - Treats the full-repository result as authoritative. A changed-line or delta view may help locate a regression, but it cannot authorize the gate.
   - Allows a migration exception only when owner, reason, replacement plan, expiry date, exact path, symbol, rule, and AST fingerprint all match. Expired, edited, or stale exceptions fail closed.

## Guard Responsibility Boundaries

`AGENTS.md` defines the development policy; the machine rules below implement a
bounded static check, not complete Python dependency analysis. Application's
cross-app infrastructure ban is layer-scoped. Infrastructure has targeted bans
(including Data Center) and graph budgets, but no blanket machine ban on every
other app's ORM. Existing single-direction infrastructure ORM dependencies are
therefore visible in the module map without necessarily failing a registered
rule. Passing the scan does not authorize copying those dependencies into new
code. Prefer the owner's Application read port and preserve ownership filters.

Architecture CI already runs a blocking full audit on pushes, pull requests and
manual runs. Repeating the same audit more often cannot expose an unrecognized
loader; extend its dependency extraction and add counterexample tests first.
Arbitrary wrappers, computed imports and runtime monkey-patching still require
review; this scanner does not claim whole-program analysis.

| Responsibility | Machine source and entrypoint | What it proves | What it does not prove |
|---|---|---|---|
| Architecture compliance | `governance/architecture_rules.json`; `check_architecture_delta.py` and `verify_architecture.py` | Dependency direction, layer imports, ORM/transaction ownership, and other structural rules | That a structurally valid Python literal is suitable as live business configuration |
| Runtime configuration coverage | `governance/runtime_config_contracts.json`; `check_runtime_config_coverage.py` | Environment and registered System Settings reads have an explicit runtime classification | That dates, weights, probabilities, estimates, or decision thresholds are versioned business policy |
| Business configuration governance | `governance/business_configuration_contracts.json`; `check_business_configuration_hardcodes.py --mode full` | Mutable catalogs and decision parameters have a canonical owner and are not reintroduced as production literals or static fallbacks | General dependency correctness or environment-variable coverage |

Enum identities, protocol/schema discriminators, dimensional unit conversions, and mathematical normalization rules remain valid constants when their invariant rationale is declared. Values that change with markets, research conclusions, strategy judgment, or operations are mutable business configuration and must use the owned, versioned read port named in the manifest.

## Baselines

`governance/governance_baseline.json` records current accepted repository state.

The baseline is not an exemption for new code. It exists to keep historical debt visible while preventing regressions:

- If a module's four-layer shape score drops below its baseline, CI fails.
- If a new app module is added without a baseline entry, CI fails.
- If Application-layer pandas/numpy imports exceed the recorded baseline, CI fails.
- If production Python files exceed the large-file baseline or historical large files grow, CI fails.
- If `core/integration` app infrastructure imports or ORM access lines increase, CI fails.
- If `core/integration` debt decreases, CI fails with stale baseline until `governance_baseline.json` is tightened.
- If `core/management/commands` app infrastructure imports or ORM access lines increase, CI fails.
- If `core/management/commands` debt decreases, CI fails with stale baseline until `governance_baseline.json` is tightened.
- If MCP tool count, business module count, static test function count, or current documentation counters drift, CI fails.

`governance/module_cycle_allowlist.json` records the app dependency graph budget.

- `allowed_bidirectional_pairs` and `allowed_cycle_components` record only unresolved historical debt. Every resolved edge must be removed immediately; the completed zero-cycle burn-down record is `docs/archive/plans/architecture-cycle-remediation-2026-07-15.md`.
- `max_app_import_edges`, `max_outbound_modules_per_app`, and `max_inbound_modules_per_app` must match the current dependency graph.
- `max_outbound_modules_by_app` and `max_inbound_modules_by_app` must cover every app module.

## Governance Self-Checks

The governance system also checks its own configuration:

- `governance_baseline` validates `governance_baseline.json` version format, required keys, count fields, module baselines, application third-party import baselines, and large-file baselines.
- `architecture_ruleset` validates `architecture_rules.json` version format, rule ID uniqueness, metadata, source selectors, and forbidden matchers.
- `module_dependency_baseline` validates `module_cycle_allowlist.json` version format, description, per-app budget coverage, global budget consistency, and allowlist module references.
- `ci_governance_wiring` validates that CI workflows still run the architecture, module-cycle, and governance consistency gates.
- `governance_docs` validates this document keeps the current command and report-section vocabulary.

## Reports

CI writes machine-readable JSON reports to:

- `reports/architecture/architecture-audit.json`
- `reports/architecture/module-cycles.json`
- `reports/consistency/governance-consistency.json`

These reports are uploaded as GitHub Actions artifacts for review.
