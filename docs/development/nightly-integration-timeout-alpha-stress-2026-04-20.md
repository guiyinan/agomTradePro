## Nightly Integration Timeout: Alpha Stress Tests

Date: 2026-04-20

### Symptom

`Nightly Tests` run `24647473264` timed out in `Run Integration Tests (core)` after 30 minutes.

The last completed integration log lines were:

- `tests/integration/test_config_center_api.py::test_config_center_snapshot_treats_data_center_provider_config_as_configured`
- `tests/integration/test_alpha_stress.py::TestHighLoadScenarios::test_concurrent_requests`

`test_rapid_sequential_requests` from the same module never completed.

### Root Cause

`tests/integration/test_alpha_stress.py::TestHighLoadScenarios` exercised `AlphaService.get_stock_scores("csi300")` against the full automatic provider fallback chain.

That made the test runtime sensitive to:

- current provider registration state
- cache/valuation coverage growth
- repeated provider health checks
- repeated database work in fallback providers

In nightly, the sequential stress case issued 100 service calls with no provider pinning, which was no longer bounded enough for the 30 minute integration budget.

### Fix

Keep the stress intent, but make the path deterministic:

- seed a local available cache record
- force `provider_filter="cache"` in `test_concurrent_requests`
- force `provider_filter="cache"` in `test_rapid_sequential_requests`
- run `test_concurrent_requests` with `transaction=True` so worker threads can read the seeded cache row from independent database connections
- reset `AlphaService` singleton around the class

This preserves the assertion that repeated and concurrent requests do not crash, while removing accidental dependence on the live fallback chain.
