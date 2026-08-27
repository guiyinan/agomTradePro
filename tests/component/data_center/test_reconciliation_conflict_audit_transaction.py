"""SQLite proof for atomic reconciliation evidence and conflict events."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.audit.application.data_conflict_audit import (
    AppendDataConflictAuditObservationUseCase,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
)
from apps.data_center.application.reconciliation import (
    RecordReconciliationEvidenceUseCase,
    reconciliation_evidence_content_hash,
)
from apps.data_center.domain.reconciliation import (
    ReconciliationClassification,
    ReconciliationDifference,
    ReconciliationReport,
)
from apps.data_center.infrastructure.reconciliation_evidence_repositories import (
    DjangoReconciliationEvidenceUnitOfWork,
    ReconciliationEvidenceRepository,
)
from apps.data_center.infrastructure.reconciliation_models import (
    ReconciliationEvidenceModel,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime.now(UTC)
SCOPE = AuditScopeRef("tenant:research", "owner:test")
SCHEMA_MODELS = (
    ReconciliationEvidenceModel,
    SystemAuditEventModel,
    SystemAuditOutboxModel,
)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Isolate only the tables participating in this transaction proof."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(SCHEMA_MODELS):
            yield


class _ScopeProvider:
    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        assert as_of == NOW
        return SCOPE


class _Clock:
    def now(self) -> datetime:
        return NOW


def _report(*, conflict: bool) -> ReconciliationReport:
    classification = (
        ReconciliationClassification.SEMANTIC_CONFLICT
        if conflict
        else ReconciliationClassification.SAME
    )
    return ReconciliationReport(
        dataset_key="equity.price.bar",
        rows=(
            ReconciliationDifference(
                natural_key="000001.SZ|2026-08-01",
                classification=classification,
                legacy_value={"close": 10.0},
                canonical_value={"close": 11.0 if conflict else 10.0},
            ),
        ),
    )


def _recorder() -> RecordReconciliationEvidenceUseCase:
    repository = ReconciliationEvidenceRepository()
    audit_writer = AppendDataConflictAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )
    return RecordReconciliationEvidenceUseCase(
        repository,
        audit_writer=audit_writer,
        unit_of_work=DjangoReconciliationEvidenceUnitOfWork(
            repository,
            audit_writer,
        ),
        clock=_Clock(),
    )


def test_detected_then_resolved_persists_exact_evidence_and_predecessor_chain() -> None:
    recorder = _recorder()
    detected_evidence = recorder.execute(
        _report(conflict=True),
        evidence_id=str(uuid4()),
        legacy_snapshot_hash="legacy-conflict",
        canonical_snapshot_hash="canonical-conflict",
        observed_at=NOW - timedelta(days=2),
    )
    resolved_evidence = recorder.execute(
        _report(conflict=False),
        evidence_id=str(uuid4()),
        legacy_snapshot_hash="legacy-clean",
        canonical_snapshot_hash="canonical-clean",
        observed_at=NOW - timedelta(days=1),
    )

    detected = SystemAuditEventModel._default_manager.get(event_type="data.conflict.detected")
    resolved = SystemAuditEventModel._default_manager.get(event_type="data.conflict.resolved")
    detected_outbox = SystemAuditOutboxModel._default_manager.get(event_id=detected.event_id)
    resolved_outbox = SystemAuditOutboxModel._default_manager.get(event_id=resolved.event_id)

    assert ReconciliationEvidenceModel._default_manager.count() == 2
    assert detected.sequence_no == 1
    assert detected.predecessor_hash is None
    assert resolved.sequence_no == 2
    assert resolved.predecessor_hash == detected.content_hash
    assert detected.scope_tenant_id == resolved.scope_tenant_id == SCOPE.tenant_id
    assert detected.scope_owner_id == resolved.scope_owner_id == SCOPE.owner_id
    assert detected.evidence_refs[0]["artifact_id"] == detected_evidence.evidence_id
    assert detected.evidence_refs[0]["content_hash"] == (
        reconciliation_evidence_content_hash(detected_evidence)
    )
    assert [reference["artifact_id"] for reference in resolved.evidence_refs] == [
        resolved_evidence.evidence_id,
        detected_evidence.evidence_id,
    ]
    assert resolved.evidence_refs[0]["content_hash"] == (
        reconciliation_evidence_content_hash(resolved_evidence)
    )
    assert resolved.evidence_refs[1]["content_hash"] == (
        reconciliation_evidence_content_hash(detected_evidence)
    )
    assert detected_outbox.payload_hash == detected.content_hash
    assert resolved_outbox.payload_hash == resolved.content_hash
    assert SystemAuditEventModel._default_manager.count() == 2
    assert SystemAuditOutboxModel._default_manager.count() == 2


def test_outbox_failure_rolls_back_reconciliation_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_enqueue(
        _repository: DjangoSystemAuditOutboxRepository,
        _event: object,
        *,
        available_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> object:
        del available_at, created_at
        raise RuntimeError("simulated outbox failure")

    monkeypatch.setattr(DjangoSystemAuditOutboxRepository, "enqueue", fail_enqueue)

    with pytest.raises(RuntimeError, match="simulated outbox failure"):
        _recorder().execute(
            _report(conflict=True),
            evidence_id=str(uuid4()),
            legacy_snapshot_hash="legacy-conflict",
            canonical_snapshot_hash="canonical-conflict",
            observed_at=NOW - timedelta(days=2),
        )

    assert ReconciliationEvidenceModel._default_manager.count() == 0
    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0
