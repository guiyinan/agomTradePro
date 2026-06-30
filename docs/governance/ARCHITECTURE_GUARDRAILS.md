# Architecture Guardrails

> Last updated: 2026-06-30

This document defines how repository-wide architecture and governance checks are enforced.

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
   - Also selects changed domain modules for the incremental Domain coverage gate.

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

- `allowed_bidirectional_pairs` and `allowed_cycle_components` are currently empty.
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
