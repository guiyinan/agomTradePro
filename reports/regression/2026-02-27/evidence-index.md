# Evidence Index - 2026-02-27 Regression Test

## 1. Test Execution Evidence

### 1.1 System Health Check
- **Command**: `python manage.py check`
- **Result**: System check identified no issues (0 silenced)
- **Migration Status**: No planned migration operations

### 1.2 Guardrails Tests
- **File**: `tests/guardrails/`
- **Result**: 26 passed, 0 failed
- **Duration**: 55.58s
- **Coverage**: Decision rhythm API, logic guardrails, security hardening, 501 checks

### 1.3 Unit Tests
- **File**: `tests/unit/`
- **Result**: 1,349 passed, 18 failed, 19 skipped
- **Duration**: ~48s
- **Pass Rate**: 97.3%

### 1.4 Integration Tests
- **File**: `tests/integration/`
- **Result**: 421 passed, 0 failed, 2 skipped
- **Duration**: 155.70s (2:35)

### 1.5 UAT API Contract Tests
- **Files**:
  - `tests/uat/test_api_naming_compliance.py`
  - `tests/uat/test_route_baseline_consistency.py`
- **Result**: 12 passed, 0 failed
- **Duration**: 17.42s

### 1.6 Playwright Smoke Tests
- **File**: `tests/playwright/tests/smoke/test_critical_paths.py`
- **Result**: 27 passed, 1 failed
- **Duration**: 138.36s (2:18)
- **Failed**: `test_login_to_dashboard_path[chromium]`

### 1.7 Playwright UAT Tests
- **File**: `tests/playwright/tests/uat/test_user_journeys.py`
- **Result**: 30 passed, 1 failed
- **Duration**: 114.20s (1:54)
- **Failed**: `test_A1_login_redirects_to_dashboard[chromium]`

### 1.8 SDK Module Tests
- **Files**:
  - `sdk/tests/test_sdk/test_extended_modules.py`
  - `sdk/tests/test_sdk/test_extended_module_endpoints.py`
- **Result**: 108 passed, 0 failed
- **Duration**: 2.23s
- **Modules**: ai_provider, prompt, audit, events, decision_rhythm, beta_gate, alpha_trigger, dashboard, asset_analysis, sentiment, task_monitor, filter

### 1.9 MCP Tool Tests
- **Files**:
  - `sdk/tests/test_mcp/test_tool_registration.py`
  - `sdk/tests/test_mcp/test_tool_execution.py`
  - `sdk/tests/test_mcp/test_rbac.py`
- **Result**: 98 passed, 0 failed
- **Duration**: 5.43s
- **Coverage**: Tool registration, execution, RBAC

## 2. Coverage Report

- **Total Coverage**: 44% (baseline)
- **Files Skipped (Complete Coverage)**: 240 files
- **HTML Report**: `htmlcov/index.html`

## 3. Defect Evidence

See `defects.csv` for detailed defect tracking.

## 4. Environment Information

- **Python**: 3.13.5
- **Django**: 5.2.10
- **Database**: SQLite (development)
- **Platform**: Windows 10 Pro
- **Branch**: main
- **Commit**: c55293e
