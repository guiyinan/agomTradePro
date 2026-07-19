# Large-file risk remediation — equity batch 2026-07-19

## Completed

- Split `apps/equity/infrastructure/repositories.py` (2327 non-empty lines) into eight focused owner modules behind a bounded compatibility facade:
  - `stock_info_repository.py` — stock master info, display-name resolution, and universe listing (`StockInfoRepositoryMixin`).
  - `fundamentals_repository.py` — financial/valuation persistence, Data Center fact mappings, and aggregated context rows (`StockFundamentalsRepositoryMixin`).
  - `market_data_repository.py` — daily prices, technical bars, remote gateway fallbacks (`StockMarketDataRepositoryMixin`).
  - `intraday_repository.py` — intraday points with validated source failover (`StockIntradayRepositoryMixin`).
  - `stock_repository.py` — `DjangoStockRepository` composition of the four mixins plus shared code/normalization helpers.
  - `asset_repository.py` — `DjangoEquityAssetRepository` for the generic asset-analysis framework.
  - `config_repositories.py` — scoring-weight, valuation-repair-config, and bootstrap-config repositories.
  - `valuation_repair_repositories.py` — valuation-repair tracking, valuation data-quality snapshots, and the quality-flag/snapshot builders.
- Split `apps/equity/interface/views.py` (1309 non-empty lines) into six focused owner modules behind a bounded compatibility facade:
  - `page_views.py` — the five login-required HTML page entries.
  - `analysis_actions.py` — screening, valuation analysis, chart, DCF, and regime-correlation actions (`EquityAnalysisActionsMixin`).
  - `pool_actions.py` — current-pool query and Regime-driven pool refresh (`EquityPoolActionsMixin`).
  - `valuation_actions.py` — snapshot listing, financial-data sync (`EquityValuationActionsMixin`), module-level valuation-repair/valuation-data implementations, and the prebuilt `extend_schema` declarations applied by the facade.
  - `multidim_screen_views.py` — multi-dimensional screening API view.
  - `valuation_config_views.py` — valuation-repair config management viewset.
- Preserved every established import and monkeypatch path:
  - `apps.equity.infrastructure.repositories` re-exports all nine legacy public symbols plus `make_on_demand_data_center_service`; `DjangoStockRepository` remains a facade subclass so method patches stay global while the on-demand factory resolves from the facade namespace at call time.
  - `apps.equity.interface.views` re-exports the five page functions, `EquityViewSet`, `EquityMultiDimScreenAPIView`, `ValuationRepairConfigViewSet`, the two legacy repository factories, and the seven patch-surface use-case classes. The facade `EquityViewSet` composes the owner mixins and resolves the patched use-case classes from its own module namespace when dispatching to owner implementations.
- Added `tests/unit/test_equity_structure.py` structure contracts: export identity/subclassing, explicit facade `__all__` sets, the on-demand patch-surface behavior, per-module non-empty-line budgets, and one-way dependency checks (owners must not import their facades, including relative-import forms).
- No database schema, route, API payload, template key, or Celery task name changes. DRF router output (URL paths and route names) verified identical to the pre-split layout.

## Remaining

- The two remediated paths must be removed from `allowed_large_python_files` and `large_file_remediation` in `governance/governance_baseline.json`; the machine-baseline update is handled centrally by the main agent, not by this batch.
- The shared static test-function count baseline needs a +4 rebase for the new structure contract tests (also handled centrally).
- Equity P1/P2 hardening beyond file size (e.g. `DjangoStockRepository` N+1 query patterns in `get_all_stocks_with_fundamentals`) remains outside this large-file-only batch.

## Regression scope

- Structure contracts: `tests/unit/test_equity_structure.py`.
- Equity unit suites: adapters, config loader, market adapter, repository daily/data-center/intraday, scoring, sector dependency, the whole `tests/unit/equity/` package, and the in-app stock-context repository suite.
- Equity integration suites: `test_equity_integration.py`, `test_equity_asset_analysis.py`.
- Equity API edge and valuation-repair API suites exercising every legacy monkeypatch path (repository methods, on-demand factory, view factories, use-case classes).
- Cross-module consumer suites: `tests/unit/test_feature_providers.py` (Decision Rhythm feature providers importing the equity repository), architecture boundary/tooling and repository-governance guardrails.
- Migration-state check for the `equity` app and Ruff lint over `apps/equity`.

## Verified

- Structure contracts: `4 passed`.
- Equity focused unit regression: `177 passed`.
- Equity integration, API-edge, valuation-repair API, and feature-provider regression: `91 passed`.
- Architecture guardrails: `14 passed` (tooling) and `8 passed` (boundaries + repository governance contracts).
- `python manage.py makemigrations equity --check --dry-run` reported `No changes detected in app 'equity'`.
- `ruff check apps/equity tests/unit/test_equity_structure.py` passed.
- Facade sizes: repositories 42 non-empty lines, views 141 non-empty lines; every owner module is within its budget (largest owner: `fundamentals_repository.py` at 583 non-empty lines, budget 750).
- Manual runtime probes confirmed the facade subclass MRO, the factory/use-case monkeypatch surfaces, and the DRF route table.

## Risks and rollback

- The facade `DjangoStockRepository` is a subclass of the owner implementation (not the identical class object) so the legacy `make_on_demand_data_center_service` patch path keeps steering construction. The structure contract pins this as an explicit `issubclass` assertion; no `isinstance`/`type()` strict checks against the legacy class exist in the codebase.
- The dead defensive import of `StockInfoRepository` in `apps/factor/infrastructure/services.py` (wrapped in `try/except`) intentionally keeps failing exactly as before; the symbol was never defined by the legacy module and is not restored.
- `apps.equity.infrastructure.providers` (`from .repositories import *`) now re-exports only the explicit facade `__all__`; the sole consumer (`repository_provider.py`) imports exactly those names. Previously leaked incidental names (e.g. `timezone`, `requests`) are no longer re-exported.
- The full repository test suite, strict mypy, and the fixed minimum regression package (TUI/terminal/SDK/SSL) were not executed; this batch does not touch those chains.
- Governance CI will report the two remediated equity paths as stale large-file allowances and a static test-count mismatch until the main agent rebases the machine baseline; three additional stale allowances (`data_center` ×2, `decision_rhythm` ×1) pre-date this batch.
- Roll back by reverting the two facades and all fourteen owner modules together with `tests/unit/test_equity_structure.py`, then rerunning the equity focused regression sets listed above.
