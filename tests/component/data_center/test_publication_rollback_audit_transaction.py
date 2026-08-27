"""SQLite proof that publication rollback and required audit are atomic."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.audit.application.data_publication_rollback_audit import (
    AppendDataPublicationRollbackAuditObservationUseCase,
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
from apps.data_center.application.control_plane import (
    RollbackCanonicalPublicationUseCase,
    publication_rollback_evidence_content_hash,
)
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationState,
)
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncUnitOfWork,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
    PublicationRollbackModel,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime.now(UTC)
SCOPE = AuditScopeRef("tenant:research", "owner:test")
SCHEMA_MODELS = (
    CanonicalPublicationModel,
    PublicationMemberModel,
    CoverageSnapshotModel,
    PublicationRollbackModel,
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


def _publication(
    *, publication_id: str, published_at: datetime
) -> tuple[CanonicalPublication, tuple[PublicationMember, ...]]:
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key="equity.price.bar",
        publication_key="current",
        policy_version="price.v1",
        state=PublicationState.PUBLISHED,
        selected_source="fixture",
        publication_hash=hashlib.sha256(publication_id.encode("utf-8")).hexdigest(),
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            generated_at=published_at,
        ),
        member_count=1,
        as_of=published_at,
        published_at=published_at,
        run_id=str(uuid4()),
    )
    member = PublicationMember(
        member_id=str(uuid4()),
        publication_id=publication_id,
        dataset_key=publication.dataset_key,
        natural_key=f"asset:{publication_id}",
        source="fixture",
        source_record_id=publication_id,
        fact_table="data_center_price_bar",
        fact_pk=publication_id,
        observed_at=published_at,
        raw_payload_hash=hashlib.sha256(f"raw:{publication_id}".encode("utf-8")).hexdigest(),
    )
    return publication, (member,)


def _setup() -> tuple[
    RollbackCanonicalPublicationUseCase,
    CanonicalPublicationRepository,
    CanonicalPublication,
    CanonicalPublication,
]:
    repository = CanonicalPublicationRepository()
    target, target_members = _publication(
        publication_id=str(uuid4()),
        published_at=NOW - timedelta(hours=2),
    )
    current, current_members = _publication(
        publication_id=str(uuid4()),
        published_at=NOW - timedelta(hours=1),
    )
    repository.publish_with_members(target, target_members)
    repository.publish_with_members(current, current_members)
    audit_writer = AppendDataPublicationRollbackAuditObservationUseCase(
        DjangoSystemAuditEventOutboxCoordinator(),
        _ScopeProvider(),
    )
    use_case = RollbackCanonicalPublicationUseCase(
        repository,
        audit_writer=audit_writer,
        unit_of_work=DjangoDataCenterSyncUnitOfWork(
            (repository,),
            audit_writer,
        ),
        clock=_Clock(),
    )
    return use_case, repository, target, current


def test_rollback_event_binds_exact_evidence_and_exact_retry_is_idempotent() -> None:
    use_case, repository, target, current = _setup()
    rollback_id = str(uuid4())
    arguments = {
        "target_publication_id": target.publication_id,
        "reason": "restore verified prior snapshot",
        "operator": "operator-1",
        "observed_at": NOW,
        "rollback_id": rollback_id,
    }

    first = use_case.execute(**arguments)
    replay = use_case.execute(**arguments)

    evidence = repository.get_rollback_by_id(rollback_id)
    assert evidence is not None
    event = SystemAuditEventModel._default_manager.get(event_type="data.publication.rolled_back")
    outbox = SystemAuditOutboxModel._default_manager.get(event_id=event.event_id)
    assert first == replay
    assert first.publication_id == target.publication_id
    assert event.write_policy == "required"
    assert event.outcome == "rolled_back"
    assert event.correlations["run_id"] == target.run_id
    assert event.correlations["publication_id"] == target.publication_id
    assert event.correlations["evidence_ref"] == rollback_id
    assert [reference["artifact_id"] for reference in event.evidence_refs] == [
        target.publication_id,
        rollback_id,
        current.publication_id,
    ]
    assert event.evidence_refs[0]["content_hash"] == target.publication_hash
    assert event.evidence_refs[1]["content_hash"] == (
        publication_rollback_evidence_content_hash(evidence)
    )
    assert event.evidence_refs[2]["content_hash"] == current.publication_hash
    assert event.scope_tenant_id == SCOPE.tenant_id
    assert event.scope_owner_id == SCOPE.owner_id
    assert outbox.payload_hash == event.content_hash
    assert PublicationRollbackModel._default_manager.count() == 1
    assert SystemAuditEventModel._default_manager.count() == 1
    assert SystemAuditOutboxModel._default_manager.count() == 1


def test_outbox_failure_rolls_back_publications_and_rollback_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_case, _repository, target, current = _setup()

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
        use_case.execute(
            target_publication_id=target.publication_id,
            reason="restore verified prior snapshot",
            operator="operator-1",
            observed_at=NOW,
            rollback_id=str(uuid4()),
        )

    target_row = CanonicalPublicationModel._default_manager.get(
        publication_id=target.publication_id
    )
    current_row = CanonicalPublicationModel._default_manager.get(
        publication_id=current.publication_id
    )
    assert target_row.state == PublicationState.SUPERSEDED.value
    assert target_row.reinstated_at is None
    assert current_row.state == PublicationState.PUBLISHED.value
    assert PublicationRollbackModel._default_manager.count() == 0
    assert SystemAuditEventModel._default_manager.count() == 0
    assert SystemAuditOutboxModel._default_manager.count() == 0
