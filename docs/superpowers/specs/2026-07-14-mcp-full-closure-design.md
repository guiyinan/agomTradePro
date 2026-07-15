# MCP Full Closure Design

> Approved design for completing the MCP consolidation closure, semantic-key
> governance, realtime alert and WebSocket delivery, controlled event replay,
> and the associated release-quality verification.

**Date:** 2026-07-14
**Status:** Approved for implementation
**Delivery branch:** `dev/feat-mcp-full-closure`

## 1. Goal

Finish the open work identified after the 2026-07-13 and 2026-07-14 MCP
consolidation changes. Completion means that the full Nightly pipeline passes,
semantic-key decisions are manually governable and auditable, realtime price
alerts and subscriptions have real canonical implementations, WebSocket clients
receive authenticated price updates, event replay uses explicit real targets and
reports partial failures, the three unsupported contracts are retired, and the
result is delivered as one reviewable pull request.

The implementation remains on the existing four-layer architecture. Domain code
stays standard-library only. Application code orchestrates Protocols and must not
import ORM models or infrastructure repositories. Infrastructure owns ORM,
Redis/Channels, external I/O, and persistence. Interface code owns DRF, ASGI,
serializers, permissions, and presentation.

## 2. Current State and Problems

The current MCP registry is core-only by default and its governance baseline is
machine-readable. The latest incremental push checks are green, but the most
recent full Nightly run stopped in the unit-test stage. The remaining reproduced
failures are:

1. The Backtest use case imports the Audit function under a local alias while its
   test patches the former symbol.
2. Production settings mutate the `MIDDLEWARE` list imported from base settings,
   causing import-order-dependent failures.
3. Realtime DRF views are registered in the page URL module instead of the API
   URL module.

`CapabilityCatalogModel.semantic_key` exists and routing uses it, but manual
overrides are not persistent across sync, no append-only correction audit exists,
and there is no batch preview/apply operator workflow.

Realtime currently has no ORM model for alerts or subscriptions, no canonical
alert/subscription API, no Channels integration, and no real WebSocket delivery.
The SDK methods intentionally fail fast.

Events currently exposes a replay route, but the route passes `target_handler=None`.
The replay loop catches and logs individual failures, returns only a success count,
and has no explicit target registry, preview, idempotency, or durable replay audit.

## 3. Delivery Structure

All work is delivered on one branch, but each mainline is an independent commit
group with its own tests and rollback point:

1. Nightly closure repairs.
2. Semantic-key governance.
3. Realtime alert CRUD and persistent subscription management.
4. Authenticated WebSocket price delivery and alert push.
5. Controlled event replay and governed MCP replacement.
6. Browser acceptance, complete regression, governance/docs closure, and PR.

No commit mixes unrelated feature implementation, deployment repair, governance
documentation, and broad test rewrites.

## 4. Nightly Closure Repairs

### 4.1 Backtest/Audit contract

The Backtest application module will expose and call one stable local symbol. The
unit test will patch that exact symbol and assert that the provided Backtest
repository is passed to the Audit application service. No ORM or Audit
infrastructure dependency is introduced into Backtest Application.

### 4.2 Production settings isolation

`core.settings.production` will create a new list from base `MIDDLEWARE` before
replacing `SecurityMiddleware` and inserting WhiteNoise. Re-importing production
settings must not mutate `core.settings.base.MIDDLEWARE`, and both supported secret
key tests must pass in any order and in the complete suite.

### 4.3 Realtime route separation

Realtime DRF endpoints move to `apps/realtime/interface/api_urls.py`. Page URLs
remain in `apps/realtime/interface/urls.py`. Canonical SDK requests use concrete
endpoints such as `/api/realtime/alerts/`; page routes cannot resolve to DRF
`APIView` classes.

## 5. Semantic-Key Governance

### 5.1 Persistence

Two Infrastructure models are added to `ai_capability`:

`CapabilitySemanticOverrideModel` stores the current operator decision:

- unique `capability_key`;
- normalized `semantic_key`;
- non-empty `reason`;
- `is_active`;
- `updated_by`;
- timezone-aware created/updated timestamps.

`CapabilitySemanticAuditModel` is append-only and stores:

- stable `batch_id` and `idempotency_key`;
- capability key;
- action (`set` or `remove`);
- old collected/effective value and new effective value;
- reason and operator;
- request fingerprint;
- timezone-aware creation timestamp.

The active override table is the source of truth for manual decisions. The audit
table is evidence and is never rewritten by catalog synchronization.

### 5.2 Domain and Application contracts

Domain values validate semantic keys without Django. A non-empty semantic key
must be lower-case dot notation, start with a letter, contain only letters,
digits, and underscores per segment, contain at least two segments, and be at
most 255 characters.

Application Protocols provide:

- list active overrides;
- inspect missing/conflicting/orphaned semantic groups;
- preview a correction batch;
- apply or remove a correction batch transactionally;
- list immutable audit entries.

The catalog sync flow is:

1. collect the source value;
2. look up an active override by capability key;
3. project the effective semantic key;
4. run routing de-duplication and winner selection.

Sync never silently deletes an override. An override for a missing capability is
reported as orphaned until an operator removes it.

### 5.3 Staff API and operator surface

The staff-only API is:

- `GET /api/ai-capabilities/semantic-governance/`;
- `POST /api/ai-capabilities/semantic-governance/preview/`;
- `POST /api/ai-capabilities/semantic-governance/apply/`;
- `GET /api/ai-capabilities/semantic-governance/audit/`.

A correction batch contains at most 100 unique capability keys, a non-empty
reason, an idempotency key, and ordered corrections. Preview performs no writes
and returns old/effective values plus the projected winner for Web, Terminal, and
Agent entrypoints. Apply repeats validation in the transaction. Reusing an
idempotency key with the same fingerprint returns the prior result; reusing it
with different input returns HTTP 409.

The existing Capability Gateway/MCP governance operator page gains missing,
conflict, orphan, preview/apply, and audit views. Ordinary users never see these
controls. Django Admin exposes the effective key and audit history but is not the
only governance workflow.

## 6. Realtime Price Alerts

### 6.1 Domain model and rules

The Domain layer adds frozen values for price alerts and subscriptions. Alert
conditions are `above`, `below`, `cross_up`, and `cross_down`. Alert statuses are
`active`, `triggered`, and `inactive`. Thresholds use `Decimal` and must be
strictly positive.

Trigger semantics are exact:

- `above`: new price is greater than or equal to the threshold;
- `below`: new price is less than or equal to the threshold;
- `cross_up`: old price is below and new price is at or above the threshold;
- `cross_down`: old price is above and new price is at or below the threshold.

An alert transitions atomically from active to triggered and records the trigger
price and timezone-aware timestamp. A triggered alert does not notify again unless
an explicit update reactivates it.

### 6.2 ORM and repository contracts

`PriceAlertModel` stores owner, canonical asset code, condition, threshold,
message, status, trigger price/time, and timestamps. All reads and mutations are
owner scoped. Staff does not implicitly cross owner scope through the ordinary
API.

`PriceSubscriptionModel` stores owner, canonical asset code, active status, and
timestamps. A database constraint keeps one row per owner/asset pair. The row is
the durable subscription truth; Channels groups are connection-state projections.

Application Protocols support owner-scoped list/get/create/update/delete and
atomic active-alert claiming. Infrastructure repositories implement those
Protocols with Django ORM.

### 6.3 Canonical REST and SDK

Canonical endpoints are:

- `GET/POST /api/realtime/alerts/`;
- `GET/PATCH/DELETE /api/realtime/alerts/{id}/`;
- `GET/POST /api/realtime/subscriptions/`;
- `DELETE /api/realtime/subscriptions/{asset_code}/`.

Serializers reject unknown fields, normalize asset codes, enforce length and
numeric bounds, and return stable JSON envelopes. Owner-scope misses return 404.

The SDK restores `list_alerts`, `create_alert`, `get_alert`, `delete_alert`,
`subscribe_price`, `unsubscribe_price`, and `get_subscriptions`, and adds
`update_alert`. SDK methods call only canonical APIs.

### 6.4 Price polling integration

The polling service receives alert repository and notification Protocols by
injection. It captures old cached prices before saving new prices, saves the new
snapshot, updates positions, evaluates alerts, atomically claims triggers, and
then publishes price and alert notifications.

Broadcast failures do not roll back saved prices or claimed alerts. They produce
structured logs and metrics. Alert evaluation failures are isolated per alert and
cannot abort the full price batch.

## 7. WebSocket Price Delivery

### 7.1 Runtime and dependencies

The project adds supported versions of `channels`, `channels-redis`, `daphne`,
and the SDK WebSocket client dependency to project and production dependency
files. `core.asgi` becomes a `ProtocolTypeRouter` with Django HTTP plus a
WebSocket router.

The channel layer uses Redis whenever `REDIS_URL` is present. Development and
tests may use `InMemoryChannelLayer`. Production with
`REALTIME_WEBSOCKET_ENABLED=true` requires Redis and fails readiness when Redis
is unavailable.

### 7.2 Authentication and connection security

The WebSocket path is `/ws/realtime/prices/`. `AllowedHostsOriginValidator`
protects browser origins. Session authentication is resolved through Channels'
auth stack. API-token authentication is resolved through an Account Application
identity service and accepts the same formal `Authorization` header used by the
REST API. Tokens are never accepted in query strings or logged.

Anonymous connections close with 4401. Disabled service closes with 1013. A
connection can only join its authenticated user control/alert group and asset
groups backed by that user's active subscriptions.

### 7.3 Client protocol

Client messages have a request ID and one of four actions:

- `subscribe` with at most 50 asset codes;
- `unsubscribe` with at most 50 asset codes;
- `list`;
- `ping`.

Each user may have at most 100 active assets. Commands are rate limited. Asset
codes are normalized and de-duplicated before persistence.

Server envelopes are:

- `connection.ready`;
- `subscription.updated`;
- `price.update`;
- `alert.triggered`;
- `error`;
- `pong`.

The response echoes the request ID when applicable. On connect, the consumer
loads active subscriptions, joins their groups, and returns them in
`connection.ready`. REST subscription changes publish a control message so live
connections resynchronize their groups. Reconnect always rebuilds state from the
database.

The SDK provides a real streaming iterator/context manager that authenticates
with an HTTP Authorization header, subscribes through the protocol, yields typed
server envelopes, sends heartbeats, and surfaces close/error codes.

## 8. Controlled Event Replay

### 8.1 Explicit target registry

Replay accepts only stable keys from an explicit Application registry. The
initial registry contains real existing handlers:

- Decision execution approved/rejected/executed/failed;
- Decision Rhythm main/quota/cooldown;
- Alpha Trigger main/invalidation/promotion.

Target factories are assembled in an Interface/composition-root module using
Application handlers and injected repositories. No request can provide an import
path, class name, or arbitrary callable.

Each registry entry declares supported event types and a human-readable side
effect description. An incompatible event type is rejected before preview.

### 8.2 Preview and execution

Requests contain `target_key`, explicit event type or a bounded time range,
`limit`, and, for commit, an idempotency key. Limits and time ranges are bounded.

Preview is staff-only, performs no handler calls and no writes, and returns:

- resolved target and supported event types;
- normalized filters;
- candidate and expected-skip counts;
- a bounded event sample;
- declared business side effects.

Commit is staff-only and produces a structured per-event result. The replay
engine no longer swallows failures. The response contains attempted, succeeded,
skipped, failed, and bounded failure details. Outcome is `completed`, `partial`,
or `failed`; partial and failed outcomes are never represented as unconditional
success.

`EventReplayRunModel` is the durable business audit and idempotency record. It
stores the requester, target, normalized request/fingerprint, idempotency key,
status, counts, bounded failures, and timezone-aware timestamps. Same key and
same fingerprint replays the stored result. Same key with different arguments
returns 409. A concurrent in-progress replay is not executed twice.

The canonical API supplies separate preview and commit endpoints. The SDK exposes
both. The governed MCP capability `events.replay.events` uses the common
preview/confirmation/idempotency/lifecycle-audit dispatcher and calls only the
formal SDK.

## 9. MCP and Legacy Closure

New governed capabilities are owner-sharded and use existing core tools. They do
not add top-level MCP tools. Capability families cover:

- reading, creating, updating, and deleting price alerts;
- reading, creating, and deleting persistent price subscriptions;
- controlled event replay.

Legacy `list_price_alerts`, `create_price_alert`, `delete_price_alert`, and
`replay_events` receive explicit replacement mappings. Subscription SDK methods
become canonical even though they had no raw MCP tools.

After API, SDK, registry, catalog, evidence, permissions, and regression tests
pass, remove these unsupported contracts:

- `realtime.delete.price_alert`;
- `realtime.price_subscription`;
- `events.replay`.

The machine governance baseline is regenerated from authoritative scripts. The
default top-level tool count remains seven, no raw `@server.tool()` is added, and
all manifest, tool-budget, read/write evidence, confirmation, preview, audit, and
catalog-dedup guards must pass.

## 10. User Surfaces

The existing Capability Gateway/MCP governance page is the semantic-key operator
surface. Realtime alert and subscription actions are exposed through the existing
Realtime TUI task surface, using row-backed selectors and user-facing labels.
Event Replay appears only to staff/operator users and always starts at preview.

Any TUI metadata changes preserve one primary task per screen, P0 visibility,
specialized presentation semantics, row-source compatibility, and no exposure of
HTTP paths or implementation details. Relevant schema, compiler/runtime metadata,
and tests are updated together.

## 11. Error Contract

- Invalid or unknown input: HTTP 400 or WebSocket `error` envelope.
- Unauthenticated REST: 401; unauthenticated WebSocket: 4401.
- Owner-scope miss or unknown permitted resource: 404.
- Staff-only action by ordinary user: 403.
- Idempotency conflict: 409.
- Channel layer unavailable for WebSocket service: 503/1013.
- Replay partial failure: HTTP success transport with explicit `partial` outcome,
  non-zero failed count, and persisted failure details; never a generic success.

No external credential, API token, internal path, stack trace, or unrestricted
event payload is emitted to ordinary users.

## 12. Migration, Operations, and Rollback

AI Capability, Realtime, and Events receive separate reversible migrations.
Historical migrations are not edited.

Feature flags:

- `REALTIME_WEBSOCKET_ENABLED` disables WebSocket connections and broadcasting;
- `EVENT_REPLAY_ENABLED` disables preview and commit replay.

Disabling WebSocket leaves polling, alert persistence, and REST management
available. Disabling replay never changes stored events. Removing a semantic
override restores the collected key on the next sync while preserving audit.

Production rollout order is:

1. install dependencies;
2. run migrations;
3. verify Redis readiness;
4. start an ASGI server using the documented command;
5. run authenticated WebSocket smoke tests;
6. enable replay only after its registry and audit checks pass.

No Docker files are created. Deployment and readiness documentation state that a
multi-process production WebSocket deployment requires Redis channel layers.

## 13. Test Strategy

Every behavior change follows red-green-refactor. Required evidence includes:

### Domain

- all four alert threshold boundaries and Decimal precision;
- no repeat trigger after atomic claim;
- semantic-key syntax and correction conflicts;
- replay completed/partial/failed classification.

### API and persistence

- response content type and status codes;
- strict unknown-field rejection;
- owner and staff scope;
- preview zero-write guarantees;
- idempotent replay and conflict;
- migration tests and database uniqueness/concurrency behavior.

### WebSocket

- anonymous rejection and session/token authentication;
- origin validation;
- subscription restore, add, remove, list, rate and size limits;
- cross-user group isolation;
- real `price.update` and single `alert.triggered` delivery;
- reconnect behavior;
- channel-layer failure handling.

Tests use Channels `WebsocketCommunicator` with an in-memory layer. A live Redis
smoke test validates the production adapter without making the ordinary unit
suite depend on external Redis.

### SDK and MCP

- canonical endpoint and payload contracts;
- real SDK WebSocket stream consumption;
- owner fallback and core-only capability calls;
- replacement, manifest, schema, preview, confirmation, idempotency, audit, and
  evidence guards;
- default tool-count and serialized-schema budgets.

### Regression and browser

- the exact previously failing Nightly tests;
- the fixed Terminal/TUI/MCP minimum regression package;
- Python 3.11 and 3.13 selected regressions;
- complete unit, API/migration, integration, app-local, and guardrail suites;
- Architecture audit and Playwright smoke suite;
- a browser journey covering semantic correction, realtime subscribe/push/alert,
  event replay preview/confirmation/result, and ordinary-user denial.

## 14. Acceptance Criteria

The work is complete only when all of the following are true:

1. The complete Nightly workflow reaches and passes every stage.
2. The three reproduced Nightly failure classes are fixed and regression tested.
3. Semantic corrections survive sync, support bounded preview/apply/remove, and
   produce immutable operator audit records.
4. Price Alert CRUD is owner scoped and all trigger rules behave exactly as
   specified.
5. Persistent subscriptions drive authenticated WebSocket group membership.
6. A real price-polling update reaches an authenticated WebSocket client.
7. Alert crossing produces exactly one user-scoped alert event.
8. Event replay requires a registered target, reports every outcome class, and
   cannot execute twice for the same idempotent request.
9. The three unsupported contracts are removed only after their replacements are
   proven.
10. Governance baseline and every relevant MCP guard pass.
11. Browser acceptance proves the user and operator primary tasks.
12. Documentation records completed, incomplete, verified, and unverified items;
    no required item remains unverified at merge time.
13. The branch contains focused commits, is pushed, and has one reviewable pull
    request with green required checks.

## 15. Explicit Non-Goals

- Building a general market-data vendor streaming gateway; the first real stream
  broadcasts the platform's canonical polling snapshots.
- Allowing arbitrary event handler imports or user-defined replay code.
- Treating Redis persistence or a subscription row alone as WebSocket delivery.
- Adding new raw top-level MCP tools.
- Creating or changing Docker deployment files.
