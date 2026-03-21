# AgomTradePro SDK & MCP Testing Guide

## Quick Start

### Prerequisites

1. **Virtual Environment** (already exists)
   ```powershell
   # Verify it exists
   Test-Path agomtradepro\Scripts\python.exe
   ```

2. **Dependencies Installed**
   ```powershell
   # If not installed
   pip install -r requirements.txt
   cd sdk
   pip install -e .
   cd ..
   ```
   MCP acceptance tests also require:
   ```powershell
   pip install "mcp>=1.20,<2"
   ```

3. **Environment Configuration**
   ```powershell
   # Copy .env.example to .env if not exists
   if (-not (Test-Path .env)) {
       Copy-Item .env.example .env
   }
   ```

---

## Running Tests

### Option 1: Run All Tests (Recommended)

```powershell
# Start the server first (in one terminal)
.\scripts\start-dev.ps1 -Mode sqlite

# In another terminal, run all tests
.\run_all_tests.ps1 -TestMode quick
```

### Option 2: Run Individual Test Scripts

```powershell
# Start the server first
.\scripts\start-dev.ps1 -Mode sqlite

# In another terminal:
pytest -q tests/acceptance/test_sdk_connection.py
pytest -q tests/acceptance/test_mcp_server.py
```

Note:
- `test_sdk_connection.py` will `skip` endpoint checks when the current backend does not expose those SDK routes (returns 404).
- `test_mcp_server.py` validates MCP registration against `mcp>=1.20,<2`.

### Option 3: Run Integration Tests

```powershell
# Start the server first
.\scripts\start-dev.ps1 -Mode sqlite

# In another terminal:
python tests/integration/test_complete_investment_flow.py
python tests/integration/test_backtesting_flow.py
set AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1
python tests/integration/test_realtime_monitoring_flow.py
```

Note:
- `test_realtime_monitoring_flow.py` depends on a live local server and real-time market data.
- It is skipped by default unless `AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1` is set.

---

## Test Scripts Overview

| Script | Purpose | Location |
|--------|---------|----------|
| `test_sdk_connection.py` | Tests SDK basic connection | `tests/acceptance/` |
| `test_mcp_server.py` | Tests MCP server functionality | `tests/acceptance/` |
| `run_all_tests.ps1` | Orchestrates all tests | Project root |
| `test_complete_investment_flow.py` | Integration test: investment flow | `tests/integration/` |
| `test_backtesting_flow.py` | Integration test: backtesting | `tests/integration/` |
| `test_realtime_monitoring_flow.py` | Integration test: realtime monitoring (live data, opt-in) | `tests/integration/` |

---

## Test Directory Structure

```
tests/
├── acceptance/          # 验收测试（端到端）
│   ├── test_sdk_connection.py
│   └── test_mcp_server.py
├── integration/        # 集成测试
│   ├── test_complete_investment_flow.py
│   ├── test_backtesting_flow.py
│   └── test_realtime_monitoring_flow.py
├── unit/              # 单元测试
│   ├── test_sdk/      # SDK 单元测试
│   └── test_mcp/      # MCP 单元测试
├── performance/       # 性能测试（待创建）
├── fixtures/          # 测试数据
├── factories/         # 测试工厂类
└── README.md          # 本文档
```

---

## Test Modes

### Quick Mode
```powershell
.\run_all_tests.ps1 -TestMode quick
```
Runs: SDK connection + MCP server tests
Duration: ~2-3 minutes

### Full Mode
```powershell
.\run_all_tests.ps1 -TestMode full
```
Runs: All tests including integration and pytest
Duration: ~5-10 minutes

### SDK Only
```powershell
.\run_all_tests.ps1 -TestMode sdk-only
```
Runs: SDK tests only

### MCP Only
```powershell
.\run_all_tests.ps1 -TestMode mcp-only
```
Runs: MCP tests only

---

## Test Results

Results are saved in the `test-results/` directory:

```
test-results/
├── sdk_connection.log
├── mcp_server.log
├── test_complete_investment_flow.py.log
├── test_backtesting_flow.py.log
├── test_realtime_monitoring_flow.py.log
└── pytest.log
```

---

## Troubleshooting

### Server Not Running
```powershell
# Check if server is accessible
Invoke-WebRequest -Uri "http://localhost:8000/api/" -UseBasicParsing

# Start the server
.\scripts\start-dev.ps1 -Mode sqlite
```

### Virtual Environment Issues
```powershell
# Recreate virtual environment
Remove-Item -Recurse -Force agomtradepro
python -m venv agomtradepro
agomtradepro\Scripts\Activate.ps1
pip install -r requirements.txt
cd sdk
pip install -e .
cd ..
```

### Import Errors
```powershell
# Reinstall SDK in development mode
cd sdk
pip install -e .
cd ..
```

---

## Next Steps

1. Run the quick test suite to verify everything works
2. Check test results in `test-results/`
3. If tests pass, try the full test suite
4. Report any bugs using the template in `docs/testing/bug-report-template.md`

---

## Additional Resources

- **Full Test Plan**: `docs/testing/sdk-mcp-integration-test-plan.md`
- **Bug Report Template**: `docs/testing/bug-report-template.md`
- **Test Results Template**: `docs/testing/test-results-template.md`
- **SDK Documentation**: `docs/sdk/`

