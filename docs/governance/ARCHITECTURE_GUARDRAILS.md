# Architecture Guardrails

> Last updated: 2026-05-02

This document defines how repository-wide architecture checks are enforced.

## Checks

The project uses two complementary guardrails:

1. `scripts/check_architecture_delta.py`
   - Runs in `.github/workflows/architecture-layer-guard.yml`.
   - Scans changed lines in pull requests and pushes.
   - Fails immediately for new Domain/Application/Interface layer violations.

2. `scripts/check_governance_consistency.py`
   - Runs in `.github/workflows/consistency-check.yml`.
   - Scans the whole repository for governance drift.
   - Checks MCP tool counts, key documentation counters, `docs/INDEX.md` links, module shape scores, misplaced `AppConfig` definitions, singular `dto.py` files, and Application-layer pandas/numpy debt.

3. `scripts/verify_architecture.py --include-audit --fail-on-audit-violations`
   - Full-repository architecture audit gate.
   - Fails on both boundary violations and audit violations.
   - Current hard checks include:
     - Application-layer ORM manager access
     - Application-layer `transaction.atomic` / dynamic `get_model()` usage
     - Non-admin imports of app-root `models.py` shims

## Baseline

`governance/governance_baseline.json` records current accepted repository state.

The baseline is not an exemption for new code. It exists to keep historical debt visible while preventing regressions:

- If a module's four-layer shape score drops below its baseline, CI fails.
- If a new app module is added without a baseline entry, CI fails.
- If Application-layer pandas/numpy imports exceed the recorded baseline, CI fails.
- If MCP tool count changes without synchronized documentation and baseline updates, CI fails.

When debt is removed, update the baseline in the same change so future regressions remain blocked.

## Reports

CI writes machine-readable JSON reports to:

- `reports/architecture/architecture-audit.json`
- `reports/consistency/governance-consistency.json`

These reports are uploaded as GitHub Actions artifacts for review.
