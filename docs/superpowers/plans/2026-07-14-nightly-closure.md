# Nightly Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the three reproduced Nightly failure classes without changing unrelated behavior.

**Architecture:** Keep fixes at their owning boundaries: Backtest calls the Audit application facade through one stable module symbol, production settings copy mutable base settings, and Realtime page/API routing is physically separated. Each repair has a focused regression before the combined Nightly test slice.

**Tech Stack:** Python 3.11+, Django 5.x, Django REST Framework, pytest.

## Global Constraints

- Domain remains standard-library only; Application and Interface must not import Infrastructure.
- API routes live in api_urls.py and page routes live in urls.py.
- Use timezone-aware datetimes.
- Follow red-green-refactor and create one focused commit for this repair group.
- Do not create or modify Docker files.

---

### Task 1: Stabilize the Backtest-to-Audit facade symbol

**Files:**
- Modify: apps/backtest/application/use_cases.py
- Test: tests/unit/test_backtest_use_cases.py

**Interfaces:**
- Consumes: apps.audit.application.interface_services.generate_attribution_report_for_backtest(backtest_id: int, *, backtest_repository: object)
- Produces: apps.backtest.application.use_cases.generate_attribution_report_for_backtest, the stable patch and call symbol.

- [ ] **Step 1: Confirm the regression is red**

Run:

~~~powershell
python -m pytest tests/unit/test_backtest_use_cases.py::test_run_backtest_uses_audit_interface_service -q
~~~

Expected: FAIL because the test patches generate_attribution_report_for_backtest while execute calls the renamed alias.

- [ ] **Step 2: Use one stable imported symbol**

Replace the aliased import with:

~~~python
from apps.audit.application.interface_services import (
    generate_attribution_report_for_backtest,
)
~~~

Call that exact symbol inside RunBacktestUseCase.execute:

~~~python
audit_response = generate_attribution_report_for_backtest(
    backtest_id=backtest_id,
    backtest_repository=self.repository,
)
~~~

- [ ] **Step 3: Prove the facade contract**

Run the test from Step 1. Expected: 1 passed and audit_calls equals [(42, repository)].

### Task 2: Isolate production MIDDLEWARE

**Files:**
- Modify: core/settings/production.py
- Test: tests/unit/test_production_settings.py

**Interfaces:**
- Consumes: core.settings.base.MIDDLEWARE.
- Produces: a production-local list containing SelectiveSSLRedirectSecurityMiddleware followed by WhiteNoiseMiddleware.

- [ ] **Step 1: Add an import-order regression**

Add a test that imports base, snapshots tuple(base.MIDDLEWARE), imports/reloads production with a valid secret, and asserts base.MIDDLEWARE is unchanged while production.MIDDLEWARE has both production entries exactly once.

- [ ] **Step 2: Run both production tests together**

Run:

~~~powershell
python -m pytest tests/unit/test_production_settings.py -q
~~~

Expected before the fix: at least one order-dependent failure or mutation assertion failure.

- [ ] **Step 3: Copy before mutation**

Immediately after importing base settings, add:

~~~python
MIDDLEWARE = list(MIDDLEWARE)
~~~

Keep replacement and insertion logic operating only on this new list.

- [ ] **Step 4: Prove order independence**

Run the file twice, once normally and once with pytest-randomly disabled if installed. Expected: every test passes both times.

### Task 3: Separate Realtime page and API routes

**Files:**
- Modify: apps/realtime/interface/urls.py
- Modify: apps/realtime/interface/api_urls.py
- Test: tests/unit/test_route_compatibility.py

**Interfaces:**
- Produces page module urls.py with no DRF APIView route.
- Produces canonical API module api_urls.py for prices, sector-performance, top-movers, market-summary, poll, and health.

- [ ] **Step 1: Add route-boundary assertions**

Add assertions that /realtime/sector-performance/ and /realtime/top-movers/ do not resolve to SectorPerformanceView or TopMoversView, while /api/realtime/sector-performance/ and /api/realtime/top-movers/ do.

- [ ] **Step 2: Confirm the current route failure**

Run:

~~~powershell
python -m pytest tests/unit/test_route_compatibility.py -q
~~~

Expected before the fix: page-path assertions fail.

- [ ] **Step 3: Move API urlpatterns**

Define app_name = "realtime" and all DRF path entries directly in api_urls.py. Reduce urls.py to actual page routes only; if Realtime has no page view yet, keep an empty urlpatterns list rather than a JSON API home.

- [ ] **Step 4: Run focused and combined regressions**

Run:

~~~powershell
python -m pytest tests/unit/test_backtest_use_cases.py tests/unit/test_production_settings.py tests/unit/test_route_compatibility.py -q
~~~

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

~~~powershell
git add apps/backtest/application/use_cases.py core/settings/production.py apps/realtime/interface/urls.py apps/realtime/interface/api_urls.py tests/unit/test_backtest_use_cases.py tests/unit/test_production_settings.py tests/unit/test_route_compatibility.py
git commit -m "fix: close nightly regressions"
~~~
