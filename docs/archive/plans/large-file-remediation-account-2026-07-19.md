# Large-file risk remediation — account batch 2026-07-19

## Completed

- Split `apps/account/infrastructure/models.py` (1389 non-empty lines) into five focused owner modules behind a bounded compatibility facade:
  - `identity_models.py` — user account profile (RBAC, approval, volatility targeting), MCP/SDK access tokens with the `_build_app_fernet` encryption helper, and portfolio observer grants.
  - `classification_models.py` — asset metadata, the tree-structured asset category model, currencies, and exchange rates.
  - `portfolio_models.py` — portfolios, positions, transactions, broker trade import batches, position signal logs, daily portfolio snapshots, and capital flows.
  - `trading_config_models.py` — investment advice rules, per-portfolio trading cost config, market-level transaction cost config, stop-loss/take-profit configs, stop-loss trigger records, and the macro sizing config.
  - `documentation_models.py` — the Markdown documentation content model.
- Replaced the legacy module with a 60-non-empty-line compatibility facade that re-exports all 22 account ORM model classes plus the `SystemSettingsModel` cross-app re-export via an explicit `__all__`.
- Preserved every established import surface: all 24 names imported anywhere in the repo from `apps.account.infrastructure.models` (enumerated by AST scan over the full workspace) resolve to the identical class objects; `apps.account.models` keeps its `from ... import *` behavior and now re-exports exactly the facade `__all__`. No `mock.patch`/`monkeypatch` paths target the legacy module namespace.
- Added `tests/unit/test_account_models_structure.py` structure contracts: export identity plus `apps.get_model("account", ...)` registration identity for every owner export, stable cross-app re-export registration for `SystemSettingsModel`, per-module non-empty-line budgets, and one-way dependency checks (owner modules must not import the facade, in absolute or relative-import form).
- No database schema, `db_table`, field, `Meta`, route, API payload, or migration changes. Owner-to-owner dependencies are one-way: `trading_config_models` → `portfolio_models` → `classification_models`; `identity_models` and `documentation_models` are standalone.

## Remaining

- The remediated path must be removed from `allowed_large_python_files` / `large_file_remediation` in `governance/governance_baseline.json`; the machine-baseline update is handled centrally by the main agent, not by this batch.
- The shared static test-function count baseline needs a rebase for the new structure contract tests (also handled centrally).
- Account P1/P2 hardening beyond file size (e.g. the 2500+ non-empty-line `apps/account/infrastructure/repositories.py` and other account modules still above threshold) remains outside this large-file-only batch.

## Regression scope

- Structure contracts: `tests/unit/test_account_models_structure.py`.
- Account unit suites: the whole `tests/unit/account/` package plus every top-level `tests/unit/test_account_*` / account-adjacent guardrail file (business reverse dependencies, macro sizing, performance domain, position helpers, decision-workspace binding, personal-account readiness, unified frontend bindings, admin user management).
- Cross-module consumer suites: `tests/unit/core/test_account_ledger.py`, `tests/unit/core/test_encryption_readiness_command.py`, `tests/unit/strategy/test_order_intent_repository.py`, observer-grant unit suites, dashboard regression guardrails, and the simulated-trading unit package (its `account_portfolio_repository.py` imports account models).
- Account integration suites: the whole `tests/integration/account/` package plus `tests/integration/test_account_performance_api.py` and `tests/integration/test_unified_account_api.py`; account API edge suites under `tests/api/`; simulated-trading integration suites.
- Migration-state check for the `account` app and Ruff lint over `apps/account`.

## Verified

- Structure contracts: `3 passed`.
- Account focused unit regression (unit/account package + account-adjacent unit files + simulated-trading unit package): `301 passed`.
- Account integration + API edge + simulated-trading integration regression: `253 passed`.
- `python manage.py makemigrations account --check --dry-run` reported `No changes detected in app 'account'`.
- `ruff check apps/account` passed (`All checks passed!`).
- Facade size: 60 non-empty lines (budget 100, requirement ≤150). Owner sizes: `identity_models.py` 360, `classification_models.py` 238, `portfolio_models.py` 395, `trading_config_models.py` 417, `documentation_models.py` 42 non-empty lines — all within their budgets (largest budget 550).
- `apps.get_model("account", ...)` returns the identical class object for all 22 account models; `apps.get_model("config_center", "SystemSettingsModel")` stays identical through the facade re-export (pinned by the structure contracts).

## Risks and rollback

- `apps/account/models.py` uses `from apps.account.infrastructure.models import *`; the legacy module had no `__all__`, so incidental public names (e.g. `User`, `Decimal`, `models`, `Sum`, `ROLE_CHOICES`) previously leaked through the star import. The facade's explicit `__all__` ends that leak; a full-repo AST scan confirms the only `apps.account.models` consumers (`core/integration/account_ledger.py`) import exactly the model classes covered by `__all__`.
- The `_build_app_fernet` encryption helper moved to `identity_models.py` alongside its sole consumer (`UserAccessTokenModel`); no external references exist, so token encryption/decryption behavior is unchanged.
- `PositionModel` choice lists still reference `AssetMetadataModel.*_CHOICES` at class-definition time and stop-loss/trading-cost models still reference `PortfolioModel`/`PositionModel` class objects directly — now via owner-to-owner imports; Django resolves these at import time exactly as before because the facade import order matches the dependency direction.
- The full test suite, strict mypy, and the fixed minimum regression package (TUI/terminal/SDK/SSL) were not executed; this batch does not touch those chains. (`tests/unit/test_tui_workbench.py` imports `SystemSettingsModel` through the facade and is covered by the structure contracts only.)
- Governance CI will report the remediated account path as a stale large-file allowance and a static test-count mismatch until the main agent rebases the machine baseline.
- Roll back by restoring the legacy `apps/account/infrastructure/models.py` and deleting the five owner modules together with `tests/unit/test_account_models_structure.py`, then rerunning the regression sets listed above.
