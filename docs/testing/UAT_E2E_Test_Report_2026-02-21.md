# AgomSAAF UAT & E2E Test Report

**Test Date:** 2026-02-21
**Test Environment:** Windows 10, Python 3.13.5, Django 5.2.10
**Test Tool:** Playwright (Headless Browser) + Requests
**System Version:** AgomSAAF V3.4

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Smoke Test Cases | 28 |
| Smoke Passed | 28 |
| Smoke Failed | 0 |
| Smoke Pass Rate | 100% |

### Data Quality Notice

- Current report contains **statistical scope conflicts**:
  - Executive totals use `57` cases, while category totals sum to `87` (`28+10+28+21`).
  - Several `404 Missing route` findings are caused by **test path baseline mismatch** rather than confirmed missing URL patterns.
- Therefore, the previous global pass rate (`80.7%`) is **not accepted as final UAT conclusion**.
- This report is reclassified as: **Baseline Verification Pending**.

### Test Categories

| Category | Total | Passed | Failed | Pass Rate |
|----------|-------|--------|--------|-----------|
| Playwright Smoke Tests | 28 | 28 | 0 | 100% |
| API Endpoint Tests | 10 | 10 | 0 | 100% |
| E2E Page Tests (Auth) | 28 | 16 | 12 | 57% |
| API Module Tests | 21 | 13 | 8 | 62% |

---

## 1. Playwright Smoke Tests (100% Pass)

All 28 Playwright headless browser tests passed successfully.

### Test Results

```
tests/playwright/tests/smoke/test_critical_paths.py

TestCriticalPaths (16 tests)
├── test_login_page_loads                    PASSED
├── test_dashboard_requires_auth             PASSED
├── test_login_to_dashboard_path             PASSED
├── test_authenticated_dashboard_loads       PASSED
├── test_macro_data_page_loads               PASSED
├── test_regime_dashboard_loads              PASSED
├── test_signal_manage_loads                 PASSED
├── test_policy_manage_loads                 PASSED
├── test_equity_screen_loads                 PASSED
├── test_fund_dashboard_loads                PASSED
├── test_asset_analysis_screen_loads         PASSED
├── test_backtest_create_loads               PASSED
├── test_simulated_trading_dashboard_loads   PASSED
├── test_audit_reports_loads                 PASSED
├── test_filter_manage_loads                 PASSED
└── test_sector_analysis_loads               PASSED

TestAdminExposureSmoke (3 tests)
├── test_admin_index_accessible              PASSED
├── test_admin_exposes_modules               PASSED
└── test_user_pages_not_admin                PASSED

TestScreenshotBaseline (9 tests)
├── test_screenshot_login_page               PASSED
├── test_screenshot_dashboard                PASSED
├── test_screenshot_macro_data               PASSED
├── test_screenshot_regime_dashboard         PASSED
├── test_screenshot_signal_manage            PASSED
├── test_screenshot_equity_screen            PASSED
├── test_screenshot_fund_dashboard           PASSED
├── test_screenshot_backtest_create          PASSED
└── test_screenshot_simulated_trading        PASSED

Duration: 137.69s
Coverage: 19% (41836 statements, 33991 missed)
```

---

## 2. API Endpoint Tests (100% Pass)

Basic API accessibility tests all passed.

| Endpoint | Status | Result |
|----------|--------|--------|
| Health API | 200 | PASS |
| API Schema | 200 | PASS |
| Swagger UI | 200 | PASS |
| ReDoc | 200 | PASS |
| Admin Page | 302 | PASS |
| Login Page | 200 | PASS |
| Home Page | 200 | PASS |
| Regime Dashboard | 200 | PASS |
| Macro Data Page | 200 | PASS |
| Signal Manage Page | 200 | PASS |

---

## 3. E2E Page Tests (Authenticated)

### 3.1 Passed Pages (16)

| Module | Path | Status |
|--------|------|--------|
| Dashboard | /dashboard/ | 200 |
| Macro Data | /macro/data/ | 200 |
| Regime Dashboard | /regime/dashboard/ | 200 |
| Regime History | /regime/history/ | 200 |
| Signal Manage | /signal/manage/ | 200 |
| Policy Events | /policy/events/ | 200 |
| Equity Screen | /equity/screen/ | 200 |
| Fund Dashboard | /fund/dashboard/ | 200 |
| Asset Analysis Screen | /asset-analysis/screen/ | 200 |
| Backtest Create | /backtest/create/ | 200 |
| Simulated Trading Dashboard | /simulated-trading/dashboard/ | 200 |
| Audit Reports | /audit/reports/ | 200 |
| Factor Management | /factor/ | 200 |
| Rotation Analysis | /rotation/ | 200 |
| Hedge Strategy | /hedge/ | 200 |
| Admin Interface | /admin/ | 200 |

### 3.2 Failed Pages (12) - Baseline Mismatch / Need Investigation

| Module | Path | Status | Issue |
|--------|------|--------|-------|
| Macro Indicator | /macro/indicator/ | 404 | Path baseline mismatch (current page is `/macro/data/`) |
| Regime State | /regime/state/ | 404 | Path baseline mismatch (current page is `/regime/dashboard/`) |
| Signal List | /signal/list/ | 404 | Path baseline mismatch (current page is `/signal/manage/`) |
| Policy Manage | /policy/manage/ | 404 | Path baseline mismatch (current page is `/policy/events/`/`/policy/dashboard/`) |
| Backtest History | /backtest/history/ | 404 | Path baseline mismatch (current pages are `/backtest/`, `/backtest/create/`) |
| Simulated Trading Positions | /simulated-trading/positions/ | 404 | Path baseline mismatch (positions page requires account id path) |
| Filter Manage | /filter/manage/ | 404 | Path baseline mismatch (current page is `/filter/dashboard/`) |
| Sector Analysis | /sector/analysis/ | 404 | Path baseline mismatch (API-first module path under `/sector/`) |
| Strategy List | /strategy/list/ | 404 | Path baseline mismatch (current page is `/strategy/`) |
| Realtime Monitor | /realtime/monitor/ | 404 | Path baseline mismatch (current endpoint is `/realtime/prices/`) |
| Alpha Dashboard | /alpha/ | 404 | Path baseline mismatch (Alpha exposed by API and dashboard endpoints) |
| Sentiment Analysis | /sentiment/ | 500 | Server error |

---

## 4. API Module Tests

### 4.1 Passed APIs (13)

| API | Path | Status |
|-----|------|--------|
| Health | /api/health/ | 200 |
| Schema | /api/schema/ | 200 |
| Regime | /api/regime/ | 200 |
| Macro | /api/macro/ | 200 |
| Signal | /api/signal/ | 200 |
| Policy | /api/policy/ | 200 |
| Backtest | /api/backtest/ | 200 |
| Audit | /api/audit/ | 200 |
| Strategy | /api/strategy/ | 200 |
| Realtime | /api/realtime/ | 200 |
| Factor | /api/factor/ | 200 |
| Rotation | /api/rotation/ | 200 |
| Hedge | /api/hedge/ | 200 |

### 4.2 Failed APIs (8) - Baseline Mismatch / Need Investigation

| API | Path | Status | Issue |
|-----|------|--------|-------|
| Account | /api/account/ | 404 | Prefix is mounted; root path may not expose list endpoint |
| Equity | /api/equity/ | 404 | Prefix is mounted; endpoint path likely differs |
| Fund | /api/fund/ | 404 | Prefix is mounted; endpoint path likely differs |
| Asset Analysis | /api/asset-analysis/ | 404 | Prefix is mounted; endpoint path likely differs |
| Simulated Trading | /api/simulated-trading/ | 404 | Prefix is mounted; endpoint path likely differs |
| Sentiment | /api/sentiment/ | 500 | Server error |
| Alpha | /api/alpha/ | 404 | Prefix is mounted; endpoint path likely differs |
| System | /api/system/ | 404 | Prefix is mounted (task_monitor), endpoint path likely differs |

---

## 5. Test Environment

### Server Configuration
```
Platform: Windows 10 Pro 10.0.19045
Python: 3.13.5
Django: 5.2.10
Database: SQLite (development mode)
Server: manage.py runserver 8000
```

### Test Credentials
```
Username: admin
Password: Aa123456
```

### Browser Configuration (Playwright)
```
Browser: Chromium
Headless: True
Viewport: 1920x1080
Timeout: 30000ms
```

---

## 6. Recommendations

### 6.1 Critical Issues (P0)

1. **Sentiment Module Server Error (500)**
   - Location: `/sentiment/` and `/api/sentiment/`
   - Action: Capture traceback and response body, identify failing view/middleware, fix before release

### 6.2 Missing Routes (P1)

The following routes are referenced in test config and returned 404, but most are now identified as **baseline mismatch** instead of confirmed missing routes:

**Pages:**
- `/macro/indicator/`
- `/regime/state/`
- `/signal/list/`
- `/policy/manage/`
- `/backtest/history/`
- `/simulated-trading/positions/`
- `/filter/manage/`
- `/sector/analysis/`
- `/strategy/list/`
- `/realtime/monitor/`
- `/alpha/`

**APIs:**
- `/api/account/`
- `/api/equity/`
- `/api/fund/`
- `/api/asset-analysis/`
- `/api/simulated-trading/`
- `/api/alpha/`
- `/api/system/`

### 6.3 Test Coverage Improvement

Current coverage: 19%

Priority areas for improvement:
1. Domain layer services (business logic)
2. Application layer use cases
3. API views and serializers

### 6.4 Remediation Plan (新增)

1. **Route Baseline Rebuild** (Deadline: 2026-02-22)
   - Generate canonical page/API path list from `core/urls.py` + module `urls.py`.
   - Replace outdated paths in UAT config (e.g. `/strategy/list/` -> `/strategy/`).
   - Output file: `docs/testing/uat-route-baseline-2026-02-22.md`.
2. **Sentiment 500 Root Cause Fix** (Deadline: 2026-02-22)
   - Reproduce with authenticated browser flow and direct API call.
   - Collect traceback, request payload, and failing stack frame.
   - Add regression test for the exact failing scenario.
3. **UAT Statistics Normalization** (Deadline: 2026-02-23)
   - Define one counting rule: `unique test items only` (no category double-count).
   - Publish recalculated totals and pass rate.
   - Archive old conflicting metrics with superseded notice.
4. **Release Gate Update** (Deadline: 2026-02-23)
   - Set mandatory gate before release:
     - Smoke tests: 100% pass
     - P0 defects: 0 open
     - Baseline mismatch items: 0 unresolved
     - UAT report metrics internally consistent

### 6.5 Verification Checklist (新增)

- [ ] Route baseline regenerated from current code
- [ ] Sentiment 500 reproduced with evidence
- [ ] Sentiment fix merged and regression test added
- [ ] UAT rerun completed on corrected path set
- [ ] Final report metrics reconciled and signed off

---

## 7. Test Execution Log

### Server Startup
```
[OK] Python runtime ready: agomsaaf\Scripts\python.exe
[OK] Database ready (migrations applied)
[OK] Macro periodic tasks configured
[OK] Django server running on http://127.0.0.1:8000
```

### Playwright Test Summary
```
============================= test session starts =============================
platform win32 -- Python 3.13.5, pytest-9.0.2, pluggy-1.6.0
baseurl: http://127.0.0.1:8000
django: version: 5.2.10, settings: core.settings.development
plugins: anyio-4.12.0, base-url-2.1.0, cov-7.0.0, django-4.11.1, mock-3.15.1, playwright-0.7.2
collected 28 items

======================= 28 passed in 137.69s (0:02:17) ========================
```

---

## 8. Appendix

### A. Playwright Screenshots

Screenshots saved to: `tests/playwright/reports/screenshots/`

| Screenshot | Module | Path |
|------------|--------|------|
| login_page.png | Auth | /account/login/ |
| dashboard.png | Dashboard | /dashboard/ |
| macro_data.png | Macro | /macro/data/ |
| regime_dashboard.png | Regime | /regime/dashboard/ |
| signal_manage.png | Signal | /signal/manage/ |
| equity_screen.png | Equity | /equity/screen/ |
| fund_dashboard.png | Fund | /fund/dashboard/ |
| backtest_create.png | Backtest | /backtest/create/ |
| simulated_trading.png | Trading | /simulated-trading/dashboard/ |

### B. Coverage Report

HTML coverage report generated to: `htmlcov/`

Key metrics:
- Total statements: 41,836
- Missed statements: 33,991
- Coverage: 19%

### C. Test Commands

```bash
# Start server
python manage.py runserver 8000

# Run Playwright tests
pytest tests/playwright/tests/smoke/test_critical_paths.py -v --base-url=http://127.0.0.1:8000

# Run with coverage
pytest tests/playwright/tests/smoke/test_critical_paths.py -v --cov=apps --cov-report=html
```

---

**Report Generated:** 2026-02-21 09:05:00
**Generated By:** Claude Code Automated Testing
**Revision:** 2026-02-21 (route baseline and remediation plan updated)
