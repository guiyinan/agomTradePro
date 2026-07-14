# Semantic Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make semantic-key corrections persistent, previewable, idempotent, removable, and append-only audited.

**Architecture:** Pure Domain values validate correction syntax and batch invariants. Application use cases depend on repository and catalog projection Protocols. Infrastructure owns ORM and transactions; DRF and the existing Capability Gateway page call only Application services.

**Tech Stack:** Python 3.11+, Django 5.x ORM/migrations, Django REST Framework, pytest, existing Capability Gateway JavaScript/templates.

## Global Constraints

- A semantic key is lower-case dot notation, begins with a letter, has at least two segments, permits letters/digits/underscores per segment, and is at most 255 characters.
- A batch has at most 100 unique capability keys, a non-empty reason, an idempotency key, and ordered corrections.
- Preview is zero-write; apply revalidates inside one transaction.
- Reusing an idempotency key with a different fingerprint returns 409.
- Synchronization never deletes overrides; missing capabilities are reported as orphaned.
- Domain imports only the standard library; Interface imports no Infrastructure.

---

### Task 1: Domain values and batch rules

**Files:**
- Create: apps/ai_capability/domain/semantic_governance.py
- Test: tests/unit/ai_capability/test_semantic_governance_domain.py

**Interfaces:**
- Produces: normalize_semantic_key(value: str) -> str.
- Produces: SemanticCorrection(capability_key: str, semantic_key: str | None, action: Literal["set", "remove"]).
- Produces: SemanticCorrectionBatch(idempotency_key: str, reason: str, corrections: tuple[SemanticCorrection, ...]).
- Produces: canonical_batch_fingerprint(batch: SemanticCorrectionBatch) -> str.

- [ ] **Step 1: Write parameterized red tests**

Cover valid keys such as realtime.alert.create and invalid keys including empty segments, uppercase, leading digits, punctuation, one segment, and length 256. Cover duplicate capability keys, empty reason/idempotency key, and 101 corrections.

- [ ] **Step 2: Implement complete validation**

Use a compiled standard-library regular expression equivalent to:

~~~python
SEMANTIC_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
)
~~~

Define frozen dataclasses that normalize surrounding whitespace and raise ValueError with stable messages. Fingerprint sorted-key JSON encoded as UTF-8 with SHA-256 while retaining correction list order.

- [ ] **Step 3: Run Domain tests**

Run:

~~~powershell
python -m pytest tests/unit/ai_capability/test_semantic_governance_domain.py -q
~~~

Expected: all cases pass.

### Task 2: Persistence and repository

**Files:**
- Modify: apps/ai_capability/infrastructure/models.py
- Create: apps/ai_capability/infrastructure/semantic_governance_repository.py
- Create: apps/ai_capability/migrations/0005_semantic_governance.py
- Test: tests/unit/ai_capability/test_semantic_governance_repository.py
- Test: tests/migrations/test_ai_capability_semantic_governance_migration.py

**Interfaces:**
- Produces CapabilitySemanticOverrideModel with unique capability_key, semantic_key, reason, is_active, updated_by, created_at, updated_at.
- Produces CapabilitySemanticAuditModel with batch_id, idempotency_key, capability_key, action, old_collected_value, old_effective_value, new_effective_value, reason, operator, request_fingerprint, created_at.
- Produces DjangoSemanticGovernanceRepository methods list_active_overrides, list_audit, find_batch, apply_batch.

- [ ] **Step 1: Write repository and migration red tests**

Assert uniqueness, active filtering, append-only audit creation, reverse migration, atomic batch rollback, same-key/same-fingerprint lookup, and same-key/different-fingerprint conflict.

- [ ] **Step 2: Add models and reversible migration**

Use settings.AUTH_USER_MODEL for operator foreign keys with SET_NULL, db indexes on capability_key, batch_id, idempotency_key, and -created_at. Add a uniqueness constraint for (idempotency_key, capability_key) on audit rows.

- [ ] **Step 3: Implement repository transaction**

The repository accepts Domain corrections and collected/effective snapshots, locks existing overrides and prior audit rows with select_for_update, writes or deactivates overrides, appends audits, and returns immutable result dictionaries. It raises SemanticIdempotencyConflict for a fingerprint mismatch.

- [ ] **Step 4: Run persistence tests**

Run:

~~~powershell
python -m pytest tests/unit/ai_capability/test_semantic_governance_repository.py tests/migrations/test_ai_capability_semantic_governance_migration.py -q
~~~

Expected: all tests pass.

### Task 3: Application inspection, preview, and apply

**Files:**
- Create: apps/ai_capability/application/semantic_governance.py
- Modify: apps/ai_capability/application/governance_service.py
- Modify: apps/ai_capability/application/repository_provider.py
- Test: tests/unit/ai_capability/test_semantic_governance_service.py
- Test: tests/unit/ai_capability/test_capability_sync_semantic_overrides.py

**Interfaces:**
- Produces SemanticGovernanceService.inspect() -> SemanticGovernanceSnapshot.
- Produces preview(batch: SemanticCorrectionBatch) -> SemanticBatchResult.
- Produces apply(batch: SemanticCorrectionBatch, operator_id: int) -> SemanticBatchResult.
- Produces list_audit(limit: int, capability_key: str | None) -> list[SemanticAuditEntry].

- [ ] **Step 1: Write service red tests**

Use fakes to prove missing, conflicting, and orphaned groups; projected Web/Terminal/Agent winners; zero repository writes on preview; transactional apply; remove behavior; and both idempotency outcomes.

- [ ] **Step 2: Implement Protocols and service**

Define repository Protocols in the Application module without importing concrete repositories. Inject catalog readers, routing projector, and semantic repository. Return frozen DTOs with collected_key, effective_key, source, winner projections, conflicts, and orphan status.

- [ ] **Step 3: Project overrides during catalog sync**

Load active overrides once per synchronization, map by capability_key, and set the effective semantic_key before de-duplication/winner selection. Preserve the collected value separately for preview and audit.

- [ ] **Step 4: Run application tests**

Run both files from this task. Expected: all pass and architecture scans show no Application ORM access.

### Task 4: Staff API, Admin, and operator page

**Files:**
- Create: apps/ai_capability/interface/semantic_governance_serializers.py
- Create: apps/ai_capability/interface/semantic_governance_views.py
- Modify: apps/ai_capability/interface/api_urls.py
- Modify: apps/ai_capability/interface/admin.py
- Modify: apps/ai_capability/interface/views.py
- Modify: core/templates/settings/capability_gateway.html
- Modify: static/js/capability_gateway.js
- Test: tests/api/test_semantic_governance_api.py
- Test: tests/unit/ai_capability/test_capability_gateway_page.py

**Interfaces:**
- GET semantic-governance returns missing/conflicting/orphaned groups.
- POST semantic-governance/preview accepts idempotency_key, reason, corrections.
- POST semantic-governance/apply returns prior result for a matching replay and 409 for mismatch.
- GET semantic-governance/audit returns bounded immutable entries.

- [ ] **Step 1: Write API contract tests**

Assert JSON content type, 401/403, strict unknown-field rejection, 100/101 boundaries, preview zero writes, apply/remove, same-fingerprint replay, fingerprint conflict, and bounded audit pagination.

- [ ] **Step 2: Implement strict serializers and staff views**

Use serializers.Serializer with explicit fields and validate that incoming key sets equal declared writable fields. Views use IsAdminUser, call a provider-built Application service, and map ValueError to 400 and SemanticIdempotencyConflict to 409.

- [ ] **Step 3: Add operator workflow**

Render missing/conflict/orphan cards, an ordered correction editor, preview results including three entrypoint winners, an apply confirmation, and immutable audit rows. Hide all controls and data from non-staff.

- [ ] **Step 4: Run API and page tests**

Run:

~~~powershell
python -m pytest tests/api/test_semantic_governance_api.py tests/unit/ai_capability/test_capability_gateway_page.py -q
~~~

Expected: all pass.

- [ ] **Step 5: Commit**

Stage only ai_capability semantic governance code, migration, UI, and its tests. Commit:

~~~powershell
git commit -m "feat: add semantic key governance"
~~~
