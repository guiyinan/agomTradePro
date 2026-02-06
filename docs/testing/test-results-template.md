# Test Results Summary

**Test Date**: YYYY-MM-DD
**Tester**: [Your Name]
**Test Environment**: SQLite / Docker / PostgreSQL
**Total Duration**: [XX minutes]

---

## Executive Summary

| Metric | Count |
|--------|-------|
| Total Tests | XX |
| Passed | XX |
| Failed | XX |
| Skipped | XX |
| Pass Rate | XX% |

**Overall Status**: PASSED / FAILED / PARTIAL

---

## Test Execution Details

### Phase 1: Environment Preparation

| Test | Status | Notes |
|------|--------|-------|
| Virtual environment exists | [PASS/FAIL] | |
| Dependencies installed | [PASS/FAIL] | |
| Environment variables configured | [PASS/FAIL] | |
| Superuser created | [PASS/FAIL] | |

---

### Phase 2: Service Startup

| Service | Status | Notes |
|---------|--------|-------|
| Docker services (PostgreSQL/Redis) | [PASS/FAIL] | |
| Database migrations | [PASS/FAIL] | |
| Celery Worker | [PASS/FAIL] | |
| Celery Beat | [PASS/FAIL] | |
| Django server | [PASS/FAIL] | |

**Service URLs Verified**:
- [ ] http://127.0.0.1:8000/ (Home)
- [ ] http://127.0.0.1:8000/admin/ (Admin)
- [ ] http://127.0.0.1:8000/api/ (API)
- [ ] http://127.0.0.1:8000/api/docs/ (API Docs)

---

### Phase 3: SDK Tests

| Test Module | Test | Status | Notes |
|-------------|------|--------|-------|
| SDK Import | Import SDK successfully | [PASS/FAIL] | |
| SDK Client | Create client instance | [PASS/FAIL] | |
| Regime Module | Get current regime | [PASS/FAIL] | |
| Regime Module | Get regime history | [PASS/FAIL] | |
| Policy Module | Get policy status | [PASS/FAIL] | |
| Macro Module | List indicators | [PASS/FAIL] | |
| Signal Module | List signals | [PASS/FAIL] | |
| Signal Module | Check eligibility | [PASS/FAIL] | |
| Signal Module | Create signal | [PASS/FAIL] | |
| Backtest Module | List backtests | [PASS/FAIL] | |
| Account Module | Get portfolios | [PASS/FAIL] | |

**SDK Test Summary**: X/Y tests passed

---

### Phase 4: MCP Tests

| Test Category | Test | Status | Notes |
|---------------|------|--------|-------|
| MCP Server | Import MCP module | [PASS/FAIL] | |
| MCP Server | Create server instance | [PASS/FAIL] | |
| MCP Tools | List available tools | [PASS/FAIL] | |
| MCP Resources | List resources | [PASS/FAIL] | |
| MCP Resources | Read regime resource | [PASS/FAIL] | |
| MCP Resources | Read policy resource | [PASS/FAIL] | |
| MCP Prompts | List prompts | [PASS/FAIL] | |
| MCP Prompts | Get prompt content | [PASS/FAIL] | |
| MCP Integration | Tool imports | [PASS/FAIL] | |
| MCP Integration | SDK client from MCP | [PASS/FAIL] | |

**MCP Test Summary**: X/Y tests passed

---

### Phase 5: Integration Tests

| Scenario | Test | Status | Notes |
|----------|------|--------|-------|
| Investment Flow | Initialize client | [PASS/FAIL] | |
| Investment Flow | Get regime | [PASS/FAIL] | |
| Investment Flow | Get policy | [PASS/FAIL] | |
| Investment Flow | Check eligibility | [PASS/FAIL] | |
| Investment Flow | Create signal | [PASS/FAIL] | |
| Investment Flow | Verify signal | [PASS/FAIL] | |
| Backtest Flow | List backtests | [PASS/FAIL] | |
| Backtest Flow | Get details | [PASS/FAIL] | |
| Backtest Flow | Get results | [PASS/FAIL] | |
| Backtest Flow | Get net value curve | [PASS/FAIL] | |
| Realtime Flow | Get single price | [PASS/FAIL] | |
| Realtime Flow | Get batch prices | [PASS/FAIL] | |
| Realtime Flow | Get market overview | [PASS/FAIL] | |
| Realtime Flow | Get top gainers | [PASS/FAIL] | |
| Realtime Flow | Get top losers | [PASS/FAIL] | |

**Integration Test Summary**: X/Y tests passed

---

## Bugs Found

### Critical Bugs
1. [Bug #1] - [Brief description]
   - Impact: [What functionality is broken?]
   - Workaround: [Is there a workaround?]

### High Priority Bugs
1. [Bug #2] - [Brief description]
   - Impact: [What functionality is broken?]
   - Workaround: [Is there a workaround?]

### Medium Priority Bugs
1. [Bug #3] - [Brief description]

### Low Priority Bugs
1. [Bug #4] - [Brief description]

---

## User Experience Issues

### Usability Concerns
1. [Issue description]

### Documentation Issues
1. [Issue description]

### Performance Observations
1. [Issue description]

---

## Recommendations

### Must Fix (Blocking Release)
1. [Recommendation]

### Should Fix (Important)
1. [Recommendation]

### Nice to Have (Enhancements)
1. [Recommendation]

---

## Test Artifacts

- **Log Directory**: `./test-results/`
- **Screenshots**: [Link to folder]
- **Coverage Report**: [Link to HTML report]

---

## Sign-off

**Tested By**: [Name]
**Date**: YYYY-MM-DD
**Status**: APPROVED / NOT APPROVED / NEEDS REVIEW

---

## Next Steps

- [ ] Fix critical bugs
- [ ] Address high-priority issues
- [ ] Update documentation based on findings
- [ ] Schedule follow-up testing
