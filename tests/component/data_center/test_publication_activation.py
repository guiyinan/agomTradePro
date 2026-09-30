"""Candidate/member/current-pointer activation contracts on the real ORM."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import connection, transaction

from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef
from apps.audit.infrastructure.publication_activation_audit_writer import (
    DjangoPublicationActivationAuditWriter,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.publication_activation import (
    PublicationActivationError,
    PublicationActivationRequest,
)
from apps.data_center.application.publication_utils import (
    member_reference,
    publication_hash,
    publication_member_from_reference,
)
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit, ValuationFact
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    PublicationMemberModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.publication_activation_repository import (
    DjangoPublicationActivationRepository,
)
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository
from core.integration.data_center_audit import (
    DataPublicationAuditObservation,
    SystemAuditEventOutboxCommit,
)
from tests.component.data_center.test_current_publication_evidence_gate import _published_snapshot

pytestmark = pytest.mark.django_db(transaction=True)


class _AuditWriter(DjangoPublicationActivationAuditWriter):
    """Required event/outbox seam used without production composition."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail
        self.coordinator = DjangoSystemAuditEventOutboxCoordinator()
        super().__init__(self.coordinator)

    def append_required(self, *, request, publication, members, observation):
        assert connection.in_atomic_block
        if self.fail:
            raise RuntimeError("required audit/outbox failure")
        assert len(members) == publication.member_count
        assert observation.recorded_at <= datetime.now(UTC)
        commit = super().append_required(
            request=request,
            publication=publication,
            members=members,
            observation=observation,
        )
        assert isinstance(commit, SystemAuditEventOutboxCommit)
        self.calls.append((request.activation_id, publication.publication_id))
        return commit


class _AuthorityFence:
    """Feature-off fence seam that owns the real outer transaction in tests."""

    @contextmanager
    def fence_complete(self, proof):
        assert proof == "proof"
        with transaction.atomic():
            checked_at = datetime.now(UTC)
            yield _FenceResult(
                checked_at=checked_at,
                valid_until=checked_at + timedelta(hours=1),
            )


@dataclass(frozen=True)
class _FenceFingerprint:
    complete_graph_hash: str = "f" * 64


@dataclass(frozen=True)
class _FenceResult:
    database_alias: str = "default"
    tenant_id: str = "tenant-1"
    owner_id: str = "owner-1"
    generation: int = 1
    fingerprint: _FenceFingerprint = _FenceFingerprint()
    checked_at: datetime = datetime.now(UTC)
    valid_until: datetime = datetime.now(UTC) + timedelta(hours=1)
    scope: str = "account_authority_complete_graph"


def _successor_candidate(
    publication_id: str,
    *,
    source_fact: ValuationFact,
    policy_version: str,
    run_id: str,
) -> tuple[CanonicalPublication, object]:
    reference = ValuationFactRepository().list_publication_candidates([source_fact])[0]
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=publication_id,
        dataset_key="equity.valuation.fact",
    )
    generated_at = datetime.now(UTC)
    candidate = CanonicalPublication(
        publication_id=publication_id,
        dataset_key="equity.valuation.fact",
        publication_key="current",
        policy_version=policy_version,
        state=PublicationState.CANDIDATE,
        selected_source=source_fact.source,
        publication_hash=publication_hash(
            [member_reference(member)],
            policy_identity=policy_version if policy_version.startswith("p2:") else None,
        ),
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            missing_count=0,
            conflict_count=0,
            generated_at=generated_at,
        ),
        member_count=1,
        as_of=reference.observed_at,
        created_by="test.activation",
        run_id=run_id,
    )
    return candidate, member


def _stage_successor(
    old_publication,
    *,
    stage: bool = True,
) -> tuple[CanonicalPublication, object, object, RawAudit]:
    current_member = CanonicalPublicationRepository().list_members(old_publication.publication_id)[
        0
    ]
    old_model = ValuationFactModel.objects.get(pk=current_member.fact_pk)
    successor = ValuationFact(
        asset_code=old_model.asset_code,
        val_date=old_model.val_date,
        pe_ttm=99.0,
        pb=9.0,
        dv_ratio=0.99,
        source=old_model.source,
        observed_at=old_model.observed_at,
        available_at=old_model.available_at,
        fetched_at=old_model.fetched_at + timedelta(seconds=1),
        extra=old_model.extra or {},
        source_record_id="activation-successor-" + uuid4().hex,
        raw_payload_hash="c" * 64,
    )
    assert ValuationFactRepository().bulk_upsert([successor]) == 1
    raw = RawAuditRepository().log(
        RawAudit(
            provider_name=old_model.source,
            capability="valuation",
            request_params={"asset_code": old_model.asset_code},
            status="ok",
            row_count=1,
            fetched_at=successor.fetched_at,
            run_id=str(uuid4()),
            ingested_run_id=str(uuid4()),
            response_payload_hash="d" * 64,
            schema_fingerprint="e" * 64,
            parser_version="test",
        )
    )
    candidate, member = _successor_candidate(
        str(uuid4()),
        source_fact=successor,
        policy_version=old_publication.policy_version,
        run_id=raw.run_id,
    )
    if stage:
        DjangoPublicationActivationRepository().stage_candidate_with_members(candidate, (member,))
    return candidate, member, old_model, raw


def _activation_request(
    candidate,
    raw: RawAudit,
    *,
    activation_id: str = "activation-1",
):
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=candidate.dataset_key,
        publication_key=candidate.publication_key,
    )
    return PublicationActivationRequest(
        dataset_key=candidate.dataset_key,
        publication_key=candidate.publication_key,
        candidate_publication_id=candidate.publication_id,
        candidate_publication_hash=candidate.publication_hash,
        activation_id=activation_id,
        audit_observation=_audit_observation(candidate, raw),
        expected_current_publication_id=str(pointer.publication_id),
        expected_current_publication_hash=pointer.publication_hash,
    )


def _audit_observation(
    candidate: CanonicalPublication,
    raw: RawAudit,
) -> DataPublicationAuditObservation:
    raw_reference = raw.exact_reference()
    return DataPublicationAuditObservation(
        dataset_key=candidate.dataset_key,
        publication_key=candidate.publication_key,
        publication_id=candidate.publication_id,
        publication_version=candidate.policy_version,
        publication_hash=candidate.publication_hash,
        provider_key=candidate.selected_source,
        run_id=raw.run_id,
        ingested_run_id=raw.ingested_run_id,
        member_count=candidate.member_count,
        coverage_requested_count=candidate.coverage.requested_count,
        coverage_eligible_count=candidate.coverage.eligible_count,
        coverage_selected_count=candidate.coverage.selected_count,
        outcome=AuditOutcome.PUBLISHED,
        raw_audit_id=raw_reference.raw_audit_id,
        raw_audit_version=raw_reference.version,
        raw_audit_content_hash=raw_reference.content_hash,
        occurred_at=candidate.as_of,
        recorded_at=raw.fetched_at,
        scope=AuditScopeRef(tenant_id="tenant-1", owner_id="owner-1"),
    )


def _activate(request: PublicationActivationRequest, writer: _AuditWriter):
    return DjangoPublicationActivationRepository().activate_candidate(
        request,
        audit_writer=writer,
        authority_fence=_AuthorityFence(),
        authority_proof="proof",
    )


def test_activation_switches_pointer_and_retry_is_idempotent() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, member, _old_model, raw = _stage_successor(old_publication)
    request = _activation_request(candidate, raw)
    writer = _AuditWriter()

    activated = _activate(request, writer)
    assert activated.publication_id == candidate.publication_id
    assert (
        CanonicalPublicationRepository().get_current(candidate.dataset_key, "current") == activated
    )
    assert writer.calls == [(request.activation_id, candidate.publication_id)]
    assert (
        CanonicalPublicationModel.objects.get(publication_id=old_publication.publication_id).state
        == PublicationState.SUPERSEDED.value
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=candidate.dataset_key,
        publication_key="current",
    )
    assert str(pointer.publication_id) == candidate.publication_id
    assert pointer.publication_hash == candidate.publication_hash
    assert pointer.activation_id == request.activation_id
    assert CanonicalPublicationRepository().list_members(candidate.publication_id) == [member]

    retried = _activate(request, writer)
    assert retried.publication_id == candidate.publication_id
    assert len(writer.calls) == 2


def test_activation_rolls_back_pointer_and_publication_when_required_audit_fails() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, _member, _old_model, raw = _stage_successor(old_publication)
    request = _activation_request(candidate, raw)

    with pytest.raises(RuntimeError, match="required audit/outbox failure"):
        _activate(request, _AuditWriter(fail=True))

    current = CanonicalPublicationRepository().get_current(old_publication.dataset_key, "current")
    assert current is not None
    assert current.publication_id == old_publication.publication_id
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=old_publication.dataset_key,
        publication_key="current",
    )
    assert str(pointer.publication_id) == old_publication.publication_id


def test_candidate_stage_rolls_back_publication_members_and_pointer_on_bulk_failure(
    monkeypatch,
) -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, member, _old_model, _raw = _stage_successor(old_publication, stage=False)
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=old_publication.dataset_key,
        publication_key="current",
    )

    def _fail_bulk_create(*_args, **_kwargs):
        raise RuntimeError("member staging failure")

    monkeypatch.setattr(
        PublicationMemberModel._default_manager,
        "bulk_create",
        _fail_bulk_create,
    )
    with pytest.raises(RuntimeError, match="member staging failure"):
        DjangoPublicationActivationRepository().stage_candidate_with_members(
            candidate,
            (member,),
        )

    assert not CanonicalPublicationModel.objects.filter(
        publication_id=candidate.publication_id
    ).exists()
    assert not PublicationMemberModel.objects.filter(
        publication_id=candidate.publication_id
    ).exists()
    pointer.refresh_from_db()
    assert str(pointer.publication_id) == old_publication.publication_id


def test_legacy_publish_does_not_advance_activation_owned_pointer() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, member, _old_model, _raw = _stage_successor(old_publication, stage=False)
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key=old_publication.dataset_key,
        publication_key="current",
    )
    original_activation_id = pointer.activation_id
    legacy_publication = replace(
        candidate,
        state=PublicationState.PUBLISHED,
        published_at=datetime.now(UTC),
    )

    published = CanonicalPublicationRepository().publish_with_members(
        legacy_publication,
        (member,),
    )

    assert published.publication_id == candidate.publication_id
    pointer.refresh_from_db()
    assert str(pointer.publication_id) == old_publication.publication_id
    assert pointer.activation_id == original_activation_id
    assert (
        CanonicalPublicationRepository().get_current(
            candidate.dataset_key,
            candidate.publication_key,
        )
        is None
    )


def test_activation_rolls_back_when_audit_event_append_fails(monkeypatch) -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, _member, _old_model, raw = _stage_successor(old_publication)
    request = _activation_request(candidate, raw)
    writer = _AuditWriter()

    def _fail_event_append(*_args, **_kwargs):
        raise RuntimeError("event append failure")

    monkeypatch.setattr(
        type(writer.coordinator._event_repository),
        "append_targeted",
        _fail_event_append,
    )
    with pytest.raises(RuntimeError, match="event append failure"):
        _activate(request, writer)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )


def test_activation_rolls_back_when_audit_outbox_enqueue_fails(monkeypatch) -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, _member, _old_model, raw = _stage_successor(old_publication)
    request = _activation_request(candidate, raw)
    writer = _AuditWriter()

    def _fail_outbox_enqueue(*_args, **_kwargs):
        raise RuntimeError("outbox enqueue failure")

    monkeypatch.setattr(
        type(writer.coordinator._outbox_repository),
        "enqueue_targeted",
        _fail_outbox_enqueue,
    )
    with pytest.raises(RuntimeError, match="outbox enqueue failure"):
        _activate(request, writer)
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )


def test_activation_rolls_back_when_pointer_write_fails(monkeypatch) -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, _member, _old_model, raw = _stage_successor(old_publication)
    request = _activation_request(candidate, raw)

    def _fail_pointer_save(*_args, **_kwargs):
        raise RuntimeError("pointer write failure")

    monkeypatch.setattr(CanonicalPublicationPointerModel, "save", _fail_pointer_save)
    with pytest.raises(RuntimeError, match="pointer write failure"):
        _activate(request, _AuditWriter())
    assert (
        CanonicalPublicationRepository()
        .get_current(old_publication.dataset_key, "current")
        .publication_id
        == old_publication.publication_id
    )
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )


def test_activation_fails_closed_on_fact_drift_without_pointer_write() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, member, old_model, raw = _stage_successor(old_publication)
    ValuationFactModel.objects.filter(pk=member.fact_pk).update(pe_ttm=101.0)
    request = _activation_request(candidate, raw)

    with pytest.raises(PublicationActivationError, match="fact content hash drifted"):
        _activate(request, _AuditWriter())

    assert (
        CanonicalPublicationRepository()
        .get_current(old_publication.dataset_key, "current")
        .publication_id
        == old_publication.publication_id
    )
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )
    assert old_model.pe_ttm == 12.5


def test_activation_fails_closed_on_candidate_hash_drift_without_pointer_write() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, _member, _old_model, raw = _stage_successor(old_publication)
    CanonicalPublicationModel.objects.filter(publication_id=candidate.publication_id).update(
        publication_hash="f" * 64
    )
    request = _activation_request(candidate, raw)

    with pytest.raises(PublicationActivationError, match="candidate publication identity drifted"):
        _activate(request, _AuditWriter())

    assert (
        CanonicalPublicationRepository()
        .get_current(old_publication.dataset_key, "current")
        .publication_id
        == old_publication.publication_id
    )
    assert (
        CanonicalPublicationModel.objects.get(publication_id=candidate.publication_id).state
        == PublicationState.CANDIDATE.value
    )


def test_activation_fails_closed_when_candidate_run_identity_is_missing() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, _member, _old_model, raw = _stage_successor(old_publication)
    CanonicalPublicationModel.objects.filter(publication_id=candidate.publication_id).update(
        run_id=None
    )
    request = _activation_request(candidate, raw)

    with pytest.raises(PublicationActivationError, match="timing or run evidence differs"):
        _activate(request, _AuditWriter())

    assert (
        CanonicalPublicationRepository()
        .get_current(old_publication.dataset_key, "current")
        .publication_id
        == old_publication.publication_id
    )


def test_activation_fails_closed_on_member_manifest_drift_without_pointer_write() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, member, _old_model, raw = _stage_successor(old_publication)
    PublicationMemberModel.objects.filter(member_id=member.member_id).update(
        fact_content_hash="e" * 64
    )
    request = _activation_request(candidate, raw)

    with pytest.raises(PublicationActivationError, match="member manifest drifted"):
        _activate(request, _AuditWriter())

    assert (
        CanonicalPublicationRepository()
        .get_current(old_publication.dataset_key, "current")
        .publication_id
        == old_publication.publication_id
    )


def test_sealed_candidate_rejects_concurrent_member_append() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, member, _old_model, _raw = _stage_successor(old_publication)

    with pytest.raises(ValueError, match="member set is sealed"):
        CanonicalPublicationRepository().add_member(member)


def test_activation_fails_closed_when_scope_pointer_is_missing() -> None:
    _policy, old_publication, _member = _published_snapshot()
    candidate, _member, _old_model, raw = _stage_successor(old_publication)
    CanonicalPublicationPointerModel.objects.filter(
        dataset_key=old_publication.dataset_key,
        publication_key="current",
    ).delete()
    request = PublicationActivationRequest(
        dataset_key=candidate.dataset_key,
        publication_key="current",
        candidate_publication_id=candidate.publication_id,
        candidate_publication_hash=candidate.publication_hash,
        activation_id="activation-no-pointer",
        audit_observation=_audit_observation(candidate, raw),
    )

    with pytest.raises(PublicationActivationError, match="pointer is missing"):
        _activate(request, _AuditWriter())
    assert (
        CanonicalPublicationRepository().get_current(old_publication.dataset_key, "current") is None
    )
