# Large-file remediation — Data Center repositories and market thermometer — 2026-07-19

This stage applies behavior-preserving refactoring to the two remaining Data Center large-file allowances: the Infrastructure repository monolith and the Application market-thermometer monolith. The machine-readable source for allowances, ownership, and targets remains `governance/governance_baseline.json`; baseline edits for these two paths are closed out by the coordinating batch, not here.

## Completed

- Split `apps/data_center/infrastructure/repositories.py` (1529 non-empty lines) into eight focused Infrastructure owners grouped by persistence responsibility, behind a 69-non-empty-line compatibility facade that re-exports all 21 public repository classes plus the test-referenced private helper `_build_asset_code_candidates` through an explicit `__all__`:
  - `_repository_helpers.py` (101 non-empty) — private asset-code candidate resolution and small normalization helpers shared by owners.
  - `provider_state_repositories.py` (135) — `ProviderConfigRepository`, `DataProviderSettingsRepository`, `ProductionCoverageUniverseConfigRepository`, `RawAuditRepository`.
  - `market_thermometer_repositories.py` (90) — thermometer config, user-override, and snapshot persistence.
  - `catalog_repositories.py` (247) — `AssetRepository`, `PublisherCatalogRepository`, `IndicatorCatalogRepository`, `IndicatorUnitRuleRepository`.
  - `macro_fact_repositories.py` (435) — `MacroFactRepository`, `MacroGovernanceRepository`.
  - `market_data_repositories.py` (133) — `PriceBarRepository`, `QuoteSnapshotRepository`.
  - `fundamental_fact_repositories.py` (179) — `FundNavRepository`, `FinancialFactRepository`, `ValuationFactRepository`.
  - `market_breadth_repositories.py` (239) — `SectorMembershipRepository`, `NewsRepository`, `CapitalFlowRepository`.
- Split `apps/data_center/application/market_thermometer.py` (1434 non-empty lines) into six focused Application owners behind a 59-non-empty-line compatibility facade:
  - `market_thermometer_specs.py` (63) — shared component specs, source-type defaults, timeout knobs, and consensus constants.
  - `_market_thermometer_runtime.py` (41) — private bridge between owners and the legacy facade patch surface.
  - `market_thermometer_config_use_cases.py` (103) — config and per-user override management plus the override payload builder.
  - `market_thermometer_import_use_cases.py` (86) — investor-account CSV import.
  - `market_thermometer_sync.py` (654) — thermometer input synchronization with provider timeout, failover, and multi-source consensus.
  - `market_thermometer_calculate.py` (571) — snapshot calculation, display fallback, and component scoring.
- Preserved the legacy monkeypatch surfaces. Repository class-attribute patch paths (`...repositories.MacroGovernanceRepository.build_snapshot`, `...repositories.ValuationFactRepository`, and similar) keep working because facade exports are identical objects. The market-thermometer facade registers itself with `_market_thermometer_runtime`, so the historically patched module attributes (`MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS`, `MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES`, `resolve_market_thermometer_as_of_date`) are resolved through the facade at call time while owners never import the facade; without a registered facade the owners fall back to the canonical constants and helpers.
- Added `tests/unit/test_data_center_repositories_structure.py` with export-identity, non-empty-line budget, and one-way dependency contracts for both splits.
- Fixed one pre-existing ruff I001 (an extra blank line after the import block) in `apps/data_center/migrations/0030_seed_market_thermometer_inputs.py` so the mandated `ruff check apps/data_center` gate passes; the change is whitespace-only and does not touch migration operations.

### Macro fact projection repository read/write evaluation

The provider-convergence plan asked whether the canonical macro fact projection repository should be split further by read/write responsibility. Conclusion: **not split in this batch**. `MacroFactRepository` is 46 non-empty lines with two read methods (`get_series`, `get_latest`) and one write method (`bulk_upsert`) that share a single `_from_model` mapping and one table. A read/write split would produce two ~30-line classes plus a shared mapping holder, adding indirection without reducing complexity, and it would not touch the actual size driver in this area (`MacroGovernanceRepository`, which is already a separate audit/repair class). The projection repository stays intact inside `macro_fact_repositories.py`; revisit only if it grows new read or write families.

## Remaining

- Removing the two remediated paths from `allowed_large_python_files` / `large_file_remediation` in `governance/governance_baseline.json` is handled by the coordinating batch, not this work package.
- The known order-sensitive shared-state pollution inside `tests/unit/data_center` remains separate test debt; behavior suites and structure contracts were executed in dedicated invocations here.
- The full repository test suite and a strict mypy run were not executed in this batch.

## Regression scope

- New structure contracts covering export identity, owner size budgets, and one-way dependencies for both facades and all owner modules.
- Data Center unit behavior suite (`tests/unit/data_center`), which includes the market thermometer use-case, timeout-monkeypatch, governance-console patch-path, and repository persistence tests.
- Reverse-dependency, architecture-guard, and use-case structure contracts.
- Legacy patch-surface spot checks outside the Data Center suite: price-code resolution helper import and decision-rhythm feature-provider patching of `ValuationFactRepository`.
- Market thermometer API integration tests exercising `interface_services` through the compatibility facade.
- Migration drift check for the `data_center` app and Ruff over the whole app.

## Verified

- New structure contract file alone: `4 passed`.
- `pytest tests/unit/data_center -q`: `266 passed`.
- `pytest tests/unit/test_data_center_reverse_dependencies.py tests/unit/test_data_center_architecture_guard.py tests/unit/test_data_center_use_cases_structure.py -q`: `5 passed`.
- `pytest tests/unit/test_data_center_price_code_resolution.py tests/unit/test_feature_providers.py -q`: `35 passed`.
- `pytest tests/integration/data_center/test_market_thermometer_api.py -q`: `7 passed`.
- `python manage.py makemigrations data_center --check --dry-run` (`core.settings.development_sqlite`): no changes detected.
- `ruff check apps/data_center`: all checks passed.
- Import smoke: 22 repository exports and 20 thermometer exports resolve to identical owner objects, and facade monkeypatch propagation through `_market_thermometer_runtime` was verified programmatically.

## Risks and rollback

- Runtime imports and compatibility exports are the main risk because tests and adjacent modules patch legacy paths; both original modules remain the stable import and patch surface, and owner modules are forbidden from importing their facade by structure contract.
- The thermometer patch bridge holds a module-level facade reference after import; it introduces no request-time state and falls back to canonical constants when the facade was never imported.
- No database schema, route, API payload, template key, or Celery task name changes are part of this batch.
- Roll back by restoring the two facade modules and removing the new owner modules and the structure contract file together; no migration or settings change needs reverting.
