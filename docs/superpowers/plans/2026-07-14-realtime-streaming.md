# Realtime Alerts and Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver owner-scoped alert CRUD, durable subscriptions, authenticated price WebSockets, single-fire alert push, and working SDK clients.

**Architecture:** Domain defines immutable alert/subscription values and pure trigger rules. Application orchestrates injected persistence, polling, and notification Protocols. Infrastructure owns ORM and Channels publishing; Interface owns DRF, ASGI routing, authentication middleware, and the WebSocket consumer.

**Tech Stack:** Python 3.11+, Django 5.x, DRF, Channels, channels-redis, Daphne, Decimal, pytest, WebsocketCommunicator.

## Global Constraints

- Conditions are above, below, cross_up, cross_down; statuses are active, triggered, inactive.
- Thresholds use Decimal and are strictly positive.
- One durable subscription row exists per owner/asset; each user has at most 100 active assets.
- A command contains at most 50 asset codes and requires a request ID.
- WebSocket path is /ws/realtime/prices/; anonymous closes 4401 and disabled service closes 1013.
- Authorization headers are accepted; query-string tokens are rejected.
- REALTIME_WEBSOCKET_ENABLED disables connection and broadcasting without disabling REST or alert persistence.
- No raw top-level MCP tool and no Docker file is added.

---

### Task 1: Alert and subscription Domain

**Files:**
- Modify: apps/realtime/domain/entities.py
- Modify: apps/realtime/domain/rules.py
- Modify: apps/realtime/domain/protocols.py
- Test: tests/unit/realtime/test_alert_domain.py

**Interfaces:**
- Produces PriceAlert, PriceSubscription, AlertCondition, AlertStatus frozen values.
- Produces should_trigger_alert(condition, threshold, old_price, new_price) -> bool.
- Produces owner-scoped repository and notification Protocols.

- [ ] **Step 1: Write boundary tests**

Cover equality for above/below, both crossing directions, non-crossing equality starts, Decimal precision, positive threshold, canonical asset normalization, and triggered/inactive no-repeat behavior.

- [ ] **Step 2: Implement pure values and rules**

Use Enum and dataclass(frozen=True). Normalize asset codes with strip().upper(), reject empty or overlong codes, and compare Decimal inputs without float conversion.

- [ ] **Step 3: Run Domain tests**

Run:

~~~powershell
python -m pytest tests/unit/realtime/test_alert_domain.py -q
~~~

Expected: all pass.

### Task 2: ORM, migration, and owner-scoped repositories

**Files:**
- Modify: apps/realtime/infrastructure/models.py
- Modify: apps/realtime/infrastructure/repositories.py
- Create: apps/realtime/migrations/0001_alerts_subscriptions.py
- Test: tests/unit/realtime/test_realtime_repositories.py
- Test: tests/migrations/test_realtime_alert_subscription_migration.py

**Interfaces:**
- Produces PriceAlertModel and PriceSubscriptionModel.
- Produces DjangoPriceAlertRepository list/get/create/update/delete and claim_trigger.
- Produces DjangoPriceSubscriptionRepository list/subscribe/unsubscribe.

- [ ] **Step 1: Write persistence red tests**

Prove owner isolation, subscription uniqueness, reactivation of an existing inactive row, trigger claim updates active rows exactly once, inactive/triggered rows cannot be reclaimed, and migration reversibility.

- [ ] **Step 2: Add models and constraints**

Use settings.AUTH_USER_MODEL, DecimalField, timezone-aware DateTimeFields, status/condition choices, indexes on owner/status/asset, and UniqueConstraint(fields=("owner", "asset_code")) for subscriptions.

- [ ] **Step 3: Implement ORM repositories**

Use transaction.atomic and select_for_update for claim_trigger. Every ordinary read and mutation filters owner_id first. Return Domain values or explicit booleans rather than models.

- [ ] **Step 4: Run persistence tests**

Expected: all repository and migration tests pass.

### Task 3: REST use cases and API

**Files:**
- Modify: apps/realtime/application/dtos.py
- Modify: apps/realtime/application/use_cases.py
- Modify: apps/realtime/application/repository_provider.py
- Modify: apps/realtime/interface/serializers.py
- Modify: apps/realtime/interface/views.py
- Modify: apps/realtime/interface/api_urls.py
- Test: tests/api/test_realtime_alerts_api.py
- Test: tests/api/test_realtime_subscriptions_api.py

**Interfaces:**
- GET/POST /api/realtime/alerts/.
- GET/PATCH/DELETE /api/realtime/alerts/{id}/.
- GET/POST /api/realtime/subscriptions/.
- DELETE /api/realtime/subscriptions/{asset_code}/.

- [ ] **Step 1: Write strict API contracts**

Cover 401, owner 404, JSON content type, list/create/get/update/delete, all field bounds, unknown field rejection, duplicate subscribe idempotency, unsubscribe, 100-user limit, and staff not crossing owner scope.

- [ ] **Step 2: Implement Application use cases**

Use injected Protocols. Update permits message/status/threshold/condition changes; explicitly setting active clears trigger price/time. Delete returns false for an owner miss.

- [ ] **Step 3: Implement serializers and views**

Normalize codes before Application calls. Map validation to 400, owner misses to 404, limit conflicts to 409. On subscription changes call an injected control notifier after persistence.

- [ ] **Step 4: Run API tests**

Expected: all API contract tests pass.

### Task 4: Channels runtime and authentication

**Files:**
- Modify: pyproject.toml
- Modify: requirements-prod.txt
- Modify: core/settings/base.py
- Modify: core/settings/development.py
- Modify: core/settings/production.py
- Modify: core/asgi.py
- Create: apps/realtime/interface/routing.py
- Create: apps/realtime/interface/websocket_auth.py
- Create: apps/realtime/interface/consumers.py
- Test: tests/unit/realtime/test_websocket_auth.py
- Test: tests/integration/test_realtime_websocket.py

**Interfaces:**
- Produces application = ProtocolTypeRouter({"http": django_asgi_app, "websocket": origin/auth/router stack}).
- Produces AuthorizationHeaderAuthMiddleware resolving the formal Account identity facade.
- Produces RealtimePriceConsumer actions subscribe, unsubscribe, list, ping.

- [ ] **Step 1: Pin supported dependencies**

Add compatible bounded versions of channels, channels-redis, daphne, and websockets to both dependency sources, then refresh the existing lock artifact if the repository tracks one.

- [ ] **Step 2: Write communicator red tests**

Cover anonymous 4401, query token rejection, session and header authentication, disabled 1013, origin rejection, ready state restore, subscribe/unsubscribe/list/ping, 50-message and 100-user bounds, duplicate normalization, rate limit, cross-user isolation, reconnect restore, and request-id echo.

- [ ] **Step 3: Configure channel layers**

Use channels_redis.core.RedisChannelLayer when REDIS_URL is configured. Use channels.layers.InMemoryChannelLayer only in development/test. Add REALTIME_WEBSOCKET_ENABLED from environment and a production readiness check when enabled without reachable Redis.

- [ ] **Step 4: Implement auth middleware and consumer**

Never log Authorization or accept tokens from scope query_string. Join only user.{id}.control, user.{id}.alerts, and asset.{normalized_code} groups for database-backed subscriptions. Return connection.ready, subscription.updated, price.update, alert.triggered, error, and pong envelopes.

- [ ] **Step 5: Run WebSocket tests**

Expected: every communicator test passes with the in-memory layer.

### Task 5: Polling, broadcasting, and single-fire alerts

**Files:**
- Modify: apps/realtime/application/price_polling_service.py
- Modify: apps/realtime/application/tasks.py
- Create: apps/realtime/infrastructure/channel_notifier.py
- Modify: apps/realtime/infrastructure/providers.py
- Test: tests/unit/realtime/test_price_polling_alerts.py
- Test: tests/integration/test_realtime_price_delivery.py

**Interfaces:**
- PricePollingService receives alert_repository and notifier Protocols.
- ChannelPriceNotifier publishes price_update, alert_triggered, and subscriptions_changed.

- [ ] **Step 1: Write orchestration red tests**

Prove old prices are read before writes, prices persist before evaluation, each alert failure is isolated, claim occurs before notify, broadcast failure preserves saved prices and claims, and one crossing yields exactly one alert event.

- [ ] **Step 2: Implement polling sequence**

Capture old cached values, fetch and save snapshot, update positions, list relevant active alerts, evaluate pure rules, atomically claim, publish price updates and claimed alerts, and emit structured logs for isolated failures.

- [ ] **Step 3: Prove real delivery**

Connect an authenticated WebsocketCommunicator, persist a subscription and crossing alert, run the real polling service with a fake market provider but real repository/notifier, and assert one price.update plus one alert.triggered; a second poll must not emit another alert.

### Task 6: SDK, TUI, and MCP governed capabilities

**Files:**
- Modify: sdk/agomtradepro/client.py
- Create: sdk/agomtradepro/realtime_stream.py
- Modify: sdk/tests/test_sdk/test_client.py
- Create: sdk/tests/test_sdk/test_realtime_stream.py
- Modify: apps/terminal/application/tui_metadata.py
- Modify: config/tui/schema/tui_metadata.schema.v3.json
- Modify: apps/terminal/application/tui_runtime_metadata.py
- Modify: tests/unit/test_tui_workbench.py
- Modify: tests/unit/test_tui_metadata_compiler.py
- Modify: governance/mcp_tool_manifest.json
- Modify: governance/mcp_legacy_replacements.json
- Test: tests/unit/test_mcp_capability_registry.py

**Interfaces:**
- Restores SDK alert/subscription methods and adds update_alert.
- Produces RealtimeStream context manager/iterator with header auth and typed envelopes.
- Produces owner-sharded core capabilities for alert and subscription CRUD.

- [ ] **Step 1: Write SDK and governed-capability red tests**

Assert exact canonical paths/payloads, Authorization header WebSocket handshake, subscribe/heartbeat/yield/close handling, no direct API leakage in TUI copy, row-backed selectors, preview/confirmation/evidence guards, and unchanged seven-tool default.

- [ ] **Step 2: Implement SDK REST and stream**

REST methods use the existing request helper. RealtimeStream connects to /ws/realtime/prices/ with additional_headers={"Authorization": formal_header}, sends request IDs and heartbeats, yields typed envelopes, and raises a typed close exception containing the code.

- [ ] **Step 3: Add TUI and governed entries**

Expose alert/subscription primary tasks using user labels and row sources, update schema/compiler/runtime together, map legacy price-alert raw tools to canonical capability keys, and do not add @server.tool().

- [ ] **Step 4: Run module and fixed high-risk regressions**

Run:

~~~powershell
python -m pytest tests/unit/realtime sdk/tests/test_sdk/test_client.py sdk/tests/test_sdk/test_realtime_stream.py tests/unit/test_tui_workbench.py tests/unit/test_tui_metadata_compiler.py tests/unit/test_mcp_capability_registry.py -q
~~~

Expected: all pass.

- [ ] **Step 5: Commit in two focused groups**

Commit persistence/REST as feat: add realtime alert management, then Channels/polling/SDK/TUI/MCP as feat: add realtime price streaming.
