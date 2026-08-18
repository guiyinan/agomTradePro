# VPS Web Liveness Stabilization — 2026-08-18

## Scope

This slice addresses the failure observed while deploying the current
`dev/next-development` candidate. Three concurrent Alpha/TUI requests held
the Web process for several minutes while the healthcheck ran in a shared PID
namespace. The verifier therefore observed an unhealthy Web service and the
release supervisor rolled back. This document is a code-stability plan, not a
production readiness attestation.

## Implemented locally

- Production settings disable synchronous Qlib inference in the Daphne/Web
  process. Development may opt in to the existing bounded fallback explicitly.
- The Qlib adapter reports `inline_inference_executed` truthfully and returns a
  degraded result when no worker is available instead of silently running an
  unbounded Web request.
- The Simple Alpha provider refuses oversized stock pools before its
  fundamental-data N+1 scan; the limit is configured by
  `ALPHA_SIMPLE_MAX_POOL_SIZE` (default `120`).
- The VPS compose default disables healthcheck-triggered Daphne termination.
  Docker still reports the service unhealthy, while recovery remains under the
  deployment supervisor instead of killing a process shared by Celery and Web.

## Evidence

- Alpha/Qlib infrastructure unit tests: `12 passed`.
- Alpha/Qlib integration tests: `29 passed`.
- Alpha runtime/contract/degradation regression: `34 passed`.
- Incremental mypy, architecture, governance, Black, isort and ruff checks
  passed locally for the changed files.

## Remaining gate

The fix must be deployed as a fresh immutable candidate and observed before
it can be called stable. The next deployment must record the candidate commit,
release/image binding, Web health/restart state, `/api/health/` latency,
Alpha request latency, absence of production inline-inference execution, and
rollback behavior. This does not provide role-based TUI UAT, write receipts,
14-day telemetry, backup/restore evidence, or AUD-01/EVID-01 authority and
publisher evidence; those gates remain unchanged.
