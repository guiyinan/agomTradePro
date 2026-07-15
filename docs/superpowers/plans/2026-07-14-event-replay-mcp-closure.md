# Controlled Event Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace unsafe/inert replay with a registered, staff-only, preview-first, idempotent replay workflow and its governed MCP capability.

**Architecture:** Domain classifies outcomes and normalized replay requests. Application owns the target registry and replay orchestration over injected event/audit repositories. Interface composition builds only approved existing handlers; Infrastructure persists idempotent run audit.

**Tech Stack:** Python 3.11+, Django 5.x, DRF, existing events/decision handler applications, pytest, SDK/MCP governance.

## Global Constraints

- Registry keys, never imports/class names/callables, are accepted from requests.
- Initial real targets cover Decision execution approved/rejected/executed/failed, Decision Rhythm main/quota/cooldown, and Alpha Trigger main/invalidation/promotion.
- Preview performs no handler call and no write.
- Commit reports attempted/succeeded/skipped/failed and bounded failure details.
- Same idempotency key plus same fingerprint returns stored result; different fingerprint returns 409; in-progress work cannot execute twice.
- EVENT_REPLAY_ENABLED gates preview and commit.
- Replay is staff-only and the governed write starts with preview/confirmation.

---

### Task 1: Replay Domain request and outcome

**Files:**
- Create: apps/events/domain/replay.py
- Test: tests/unit/events/test_replay_domain.py

**Interfaces:**
- Produces ReplayFilter(event_type, start_at, end_at, limit).
- Produces ReplayEventResult(event_id, status, error_code, message).
- Produces ReplaySummary with outcome completed, partial, or failed.
- Produces replay_fingerprint(target_key, normalized_filter) -> str.

- [ ] **Step 1: Write red tests**

Cover timezone awareness, start/end order, bounded time range and limit, explicit event type, stable fingerprint, and classification: zero failures completed, mixed partial, no success with failures failed.

- [ ] **Step 2: Implement frozen values**

Use datetime and timezone from the standard library, stable JSON plus SHA-256, and bounded sanitized error messages. Do not carry unrestricted event payloads in public results.

- [ ] **Step 3: Run Domain tests**

Expected: all pass.

### Task 2: Explicit target registry and composition

**Files:**
- Create: apps/events/application/replay_registry.py
- Create: apps/events/interface/replay_composition.py
- Test: tests/unit/events/test_replay_registry.py

**Interfaces:**
- Produces ReplayTarget(key, supported_event_types, side_effect_description, factory).
- Produces ReplayTargetRegistry.resolve(key: str) -> ReplayTarget.
- Produces build_replay_target_registry() with exactly the ten approved handler target families from the design.

- [ ] **Step 1: Write registry red tests**

Assert stable keys, supported types, non-empty side-effect descriptions, unknown-key rejection, type mismatch rejection, and no import path/callable accepted from input.

- [ ] **Step 2: Implement Application registry**

Keep factories opaque behind a Protocol. Registry resolution returns metadata and a factory known at composition time.

- [ ] **Step 3: Compose existing handlers**

Build factories for apps.events.application.decision_execution_handlers, apps.decision_rhythm.application.handlers, and apps.alpha_trigger.application.handlers using their existing repository providers. Interface is the composition root; Application imports no Infrastructure.

- [ ] **Step 4: Run registry tests**

Expected: all targets resolve and architecture checks pass.

### Task 3: Durable replay run audit

**Files:**
- Modify: apps/events/infrastructure/models.py
- Modify: apps/events/infrastructure/repositories.py
- Create: apps/events/migrations/0004_event_replay_run.py
- Test: tests/unit/events/test_replay_run_repository.py
- Test: tests/migrations/test_event_replay_run_migration.py

**Interfaces:**
- Produces EventReplayRunModel with requester, target_key, normalized_request, request_fingerprint, idempotency_key, status, counts, failures, created_at, started_at, finished_at.
- Produces DjangoReplayRunRepository.reserve, complete, fail, get_by_idempotency.

- [ ] **Step 1: Write repository red tests**

Cover uniqueness, reserve concurrency, same-fingerprint replay, mismatch conflict, in-progress non-execution, bounded failures, timezone-aware timestamps, and reverse migration.

- [ ] **Step 2: Implement model and transaction**

Use a unique constraint on requester plus idempotency_key, JSON fields for normalized request and bounded failures, select_for_update during reserve, and explicit pending/running/completed/partial/failed statuses.

- [ ] **Step 3: Run persistence tests**

Expected: all pass.

### Task 4: Preview and commit use cases

**Files:**
- Modify: apps/events/application/dtos.py
- Create: apps/events/application/replay_service.py
- Modify: apps/events/application/use_cases.py
- Modify: apps/events/application/repository_provider.py
- Test: tests/unit/events/test_replay_service.py

**Interfaces:**
- Produces preview(request, requester_id) -> ReplayPreview.
- Produces commit(request, requester_id) -> ReplaySummary.
- EventReplayHandler returns per-event results instead of swallowing failures.

- [ ] **Step 1: Write service red tests**

Prove preview resolves target and counts candidates/skips without factory invocation or writes; commit records each handled/skipped/failed event; handler exceptions become sanitized failure entries; and idempotent/concurrent paths do not call handlers twice.

- [ ] **Step 2: Implement bounded preview**

Validate feature flag, target/type compatibility, time window, and limit. Query candidate event metadata only and return a bounded sample plus declared side effects.

- [ ] **Step 3: Implement explicit commit outcomes**

Reserve the run, resolve the target factory, iterate ordered events, call can_handle then handle, append a result for every candidate, persist summary, and re-raise only infrastructure-fatal errors after marking the run failed.

- [ ] **Step 4: Run service tests**

Expected: all pass with completed, partial, and failed assertions.

### Task 5: Staff API and SDK

**Files:**
- Modify: apps/events/interface/serializers.py
- Modify: apps/events/interface/views.py
- Modify: apps/events/interface/api_urls.py
- Modify: sdk/agomtradepro/client.py
- Test: tests/api/test_event_replay_api.py
- Modify: sdk/tests/test_sdk/test_client.py

**Interfaces:**
- POST /api/events/replay/preview/.
- POST /api/events/replay/commit/.
- SDK preview_event_replay and commit_event_replay.

- [ ] **Step 1: Write API/SDK contract red tests**

Cover 401/403, flag-disabled 503, strict fields, unknown target/type 400, preview zero writes, success/partial/failed envelopes, same-key replay, 409 mismatch, and exact SDK paths/payloads.

- [ ] **Step 2: Implement staff endpoints**

Use IsAdminUser, separate preview/commit serializers, bounded fields, and provider-built services. Transport remains 200 for a partial business outcome with non-zero failed and persisted details.

- [ ] **Step 3: Restore formal SDK methods**

Keep compatibility replay_events as a wrapper that requires target_key and delegates to preview or commit; expose explicit preview_event_replay and commit_event_replay.

### Task 6: Governed MCP replacement and unsupported-contract retirement

**Files:**
- Modify: apps/agent_runtime/application/mcp_capability_registry.py
- Modify: apps/agent_runtime/application/mcp_dispatcher.py
- Modify: governance/mcp_tool_manifest.json
- Modify: governance/mcp_legacy_replacements.json
- Modify: governance/unsupported_sdk_contracts.json
- Modify: tests/unit/test_mcp_capability_registry.py
- Modify: tests/unit/test_mcp_governance_guards.py

**Interfaces:**
- Produces events.replay.events governed capability using the formal SDK.
- Uses common preview, confirmation, idempotency, and lifecycle audit dispatcher behavior.
- Removes unsupported contracts realtime.delete.price_alert, realtime.price_subscription, and events.replay only after replacement tests pass.

- [ ] **Step 1: Write governed capability red tests**

Assert owner shard, permissions, preview-required confirmation, idempotency, lifecycle audit, SDK-only dispatch, legacy replay_events mapping, no raw tool registration, and unchanged seven-tool default.

- [ ] **Step 2: Add registry and manifest entries**

Map controlled replay to the existing core dispatcher and declare read/write evidence. Add explicit legacy replacement keys for list/create/delete price alerts and replay_events.

- [ ] **Step 3: Prove replacements before deleting unsupported markers**

Run SDK, API, capability, manifest, permission, preview, confirmation, idempotency, audit, catalog-dedup, and tool-budget tests. Only then delete the three entries from unsupported_sdk_contracts.json.

- [ ] **Step 4: Commit**

Stage only Events replay, its migration/tests, SDK replay, and MCP replacement files. Commit:

~~~powershell
git commit -m "feat: add controlled event replay"
~~~
