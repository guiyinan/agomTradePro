# 2026-02-17 Static/API Cleanup Memo

## Scope
- Removed static path conflicts that caused `collectstatic` duplicate warnings and inconsistent asset loading.
- Fixed multiple frontend hard-coded API URLs that did not match Django routes.
- Added defensive compatibility for strategy-related payload shapes used by templates.

## Code Changes
- `core/settings/base.py`
  - Removed `core/static` from `STATICFILES_DIRS`.
  - Keep only project-level `static/`; app-level static files are discovered via `AppDirectoriesFinder`.

- `static/css/main.css` (deleted)
- `static/js/echarts.min.js` (deleted)
  - Removed duplicate copies; canonical files remain under `core/static`.

- API URL fixes in templates:
  - `core/templates/strategy/list.html`
  - `core/templates/strategy/create.html`
  - `core/templates/strategy/edit.html`
  - `core/templates/strategy/detail.html`
  - `core/templates/strategy/components/script_editor.html`
  - `core/templates/simulated_trading/my_accounts.html`
  - `core/templates/backtest/create.html`
  - `core/templates/backtest/list.html`
  - `core/templates/fund/dashboard.html`
  - `core/templates/filter/dashboard.html`
  - `core/templates/macro/data.html`
  - `core/templates/decision/workspace.html`

- `apps/fund/interface/views.py`
  - Added `active_signals_count` into dashboard context.
  - Frontend now uses server context instead of requesting a non-existent signal endpoint.

## Validation Results
- `python manage.py check`
  - Passed (`System check identified no issues`).

- Template URL resolve scan (literal `fetch('/...')`):
  - Checked: 24
  - Unresolved: 0

- Static conflict scan across `*/static/*` sources:
  - Duplicate relative paths: 0

- `python manage.py collectstatic --noinput --clear`
  - Remaining duplicate warnings only from `django.contrib.admin` vs `jazzmin` built-in files:
    - `admin/js/cancel.js`
    - `admin/js/popup_response.js`
  - This pair is expected with Jazzmin and not from project static files.

- `pytest apps/strategy apps/fund apps/backtest apps/simulated_trading apps/decision_rhythm -q`
  - Completed but collected 0 tests in these directories (current repository test distribution issue).

- Lightweight URL smoke via Django test client:
  - `/`, `/dashboard/`, `/strategy/`, `/strategy/create/`, `/simulated-trading/my-accounts/`, `/decision/workspace/` -> 302 (login redirect expected)
  - `/regime/dashboard/`, `/fund/dashboard/`, `/filter/dashboard/`, `/macro/data/`, `/backtest/` -> 200

## Follow-up Recommendation
- If you want zero `collectstatic` duplicate warnings, add a static post-processing filter or settings-level exclusion for Jazzmin's duplicated admin JS, while keeping one canonical source.
