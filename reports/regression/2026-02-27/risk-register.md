# Risk Register - 2026-02-27 Regression Test

## Active Risks

| ID | Risk | Severity | Likelihood | Impact | Mitigation | Owner |
|----|------|----------|------------|--------|------------|-------|
| R001 | SQLite lock failures may mask real issues | Low | Low | Low | Run critical tests on PostgreSQL | QA |
| R002 | Playwright login tests failing | Medium | Medium | Medium | Manual verification before release | Dev |
| R003 | Alpha provider fallback not tested | Low | Low | Low | Add to next sprint | Dev |
| R004 | Audit attribution tests incomplete | Low | Low | Low | Schedule fix | Dev |
| R005 | PostDeploy gate not validated | Medium | High | High | Run Docker validation before prod deploy | Ops |

## Closed Risks

| ID | Risk | Resolution | Closed Date |
|----|------|------------|-------------|
| - | - | - | - |

## Risk Mitigation Actions

### R002 - Playwright Login Tests
- **Action**: Manual login test on all supported browsers
- **Due**: Before RC deployment
- **Assignee**: QA Team

### R005 - PostDeploy Validation
- **Action**: Run full PostDeploy gate in Docker environment
- **Due**: Before production deployment
- **Assignee**: DevOps Team

## Risk Assessment Summary

- **Total Active Risks**: 5
- **High Severity**: 1 (R005)
- **Medium Severity**: 2 (R002, R005)
- **Low Severity**: 3 (R001, R003, R004)

**Overall Risk Level**: LOW

All identified risks have mitigation plans. No blocking risks for RC gate.
