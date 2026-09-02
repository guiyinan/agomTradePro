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

## Candidate observation

Candidate `56f2f8d4acb4e4510015ee10f6578fb9edc1c698` was deployed code-only as
release `20260818185114` with image
`sha256:e62c0347848245773dbaa11d47a2bf397f99c6be3a203582fc4ab76fdc999906`.
The PostgreSQL/Redis data volumes were preserved and the pre-deploy PostgreSQL
backup is recorded at
`/opt/agomtradepro/backups/database/postgres-20260818-125148.dump`.

The first standard verifier returned a fail-closed 30-second remote healthcheck
timeout even though its preceding HTTPS and container checks were healthy. A
second read-only verifier run with a 120-second remote command window passed
all checks: HTTPS health/TLS, migrations/schema, TUI registry, Qlib identity,
Celery worker/beat, source/image/release binding and backup presence. The
running release is `source-20260818185114`, Web restart count is `0`, and the
Web container is `healthy`; the previous release remains available at
`source-20260818154306` for rollback.

Eight HTTPS `/api/health/` probes all returned `200` during the sample window
with observed latency between roughly `1.09s` and `1.85s`. Inside the Web
container `ALPHA_ALLOW_INLINE_INFERENCE=false` and
`ALPHA_SIMPLE_MAX_POOL_SIZE=120`; no inline-inference or long Alpha request
appeared in the last ten minutes of Web logs.

The deploy verifier follow-up now uses a `120s` default/one-click remote
command window, preventing the observed false negative on a freshly restarted
stack. This is deploy-tooling hardening; it does not change the running image.

## Remaining gate

This is a short, read-only stabilization sample, not a production closure
claim. Continue observing the candidate for the planned window and record
Alpha latency/restart/error telemetry before calling it stable. This does not
provide role-based TUI UAT, write receipts, 14-day telemetry, backup/restore
drill evidence, or AUD-01/EVID-01 authority and publisher evidence; those gates
remain unchanged.

## 2026-09-02: bounded host recovery contract

The 2026-09-02 candidate-bound read-only probe found a real recovery gap: Web
was `running/unhealthy` with `restart=0`, Daphne was still alive, and Caddy
returned `502` because `web:8000` timed out. The compose healthcheck only
reported the failure (`WEB_HEALTH_SELF_TERMINATE_AFTER_FAILURES=0`), while the
shared `runtime_ns` PID namespace makes healthcheck-triggered process kills an
unsafe recovery mechanism. No systemd/monit/supervisor watcher was present on
the VPS.

The repository now provides an optional server-side watchdog at
`scripts/vps-web-watchdog.sh`, plus systemd service/timer templates. It is
deliberately not invoked by application deployment. Each timer tick reads the
Docker health state, counts three consecutive `unhealthy` samples, enforces a
15-minute cooldown and two-restarts-per-hour budget, then issues only
`docker compose ... restart web` and waits up to 120 seconds for health to
recover. It never kills a shared-PID process, restarts `runtime_ns`/Celery, or
touches database/configuration state. Healthy Web liveness—including an
application-level decision gate that is correctly blocked—clears the counter.

The contract is covered by five local shell-behavior tests and `sh -n`; it has
not been installed on or exercised against the VPS. Installing the timer is a
single explicit operations action, not a reason to redeploy the application or
reset the TUI-02 candidate window. Production installation, recovery and
post-restart evidence remain pending authorization and observation.
