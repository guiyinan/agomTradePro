# Large-file risk remediation — 2026-07-14

## Stage objective

This stage applies behavior-preserving refactoring to the four highest-risk large-file allowances. The machine-readable source for current allowances, ownership, priorities, targets, and review dates remains `governance/governance_baseline.json`; this document intentionally does not copy live line counts.

## Completed scope

- Terminal identity/access runtime metadata now uses MCP, current-user AI provider, system AI provider, and quota owner shards. The original module is a compatibility aggregator.
- Dashboard Alpha homepage behavior is divided into exit-watch, runtime/readiness, candidate mapping, and history collaborators while `AlphaHomepageQuery` remains the public entry point.
- Dashboard HTTP views retain page orchestration and compatibility exports; Regime/Pulse, Alpha, and navigation/empty-state context helpers live in focused modules.
- Alpha Qlib Celery task definitions and aliases remain in Application. Initialization, prediction/cache, and artifact/training runtime work is delegated through the Application provider factory to Infrastructure modules.
- The four remediated paths were removed from both the allowance and remediation maps. Every remaining allowance has an owner, rationale, priority, target, review date, and this plan path.

## Remaining scope

The remaining allowances are not refactored in this stage. Their authoritative backlog is `large_file_remediation` in the governance baseline:

- P1 items must be reviewed by 2026-09-30.
- P2 items must be reviewed by 2026-12-31.
- A reached review date fails governance CI until the file is remediated or its metadata is deliberately revised through review.
- Targets cannot exceed the repository-wide large-file threshold.

## Regression coverage

- Terminal metadata composition, TUI workbench, terminal service, SDK, and SSL redirect checks.
- Dashboard API edges, market thermometer, regression guardrails, Alpha end-to-end, and Regime/Pulse integration.
- Qlib prediction, cache fallback, training, integration, and Celery registration aliases.
- Architecture rules, module cycles, governance consistency, formatting, import sorting, and test collection.

## Risks and rollback points

- Runtime imports and compatibility exports are the main risk because tests and adjacent interface modules patch legacy paths. Each original module therefore retains thin exports or aggregators.
- Celery task registration is kept in the original module; Infrastructure modules contain implementation only.
- Each responsibility split is independently revertible. If a regression is found, revert the corresponding split together with its baseline removal so governance remains internally consistent.
- No database schema, route, API payload, template key, TUI key, or Celery task name changes are part of this stage.
