"""Contract and persistence tests for the Data Center control plane."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.data_center.application.control_plane import (
    PublishCanonicalDatasetUseCase,
    RollbackCanonicalPublicationUseCase,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationRollback,
    PublicationState,
    QuarantineRecord,
    QuarantineResolution,
    SyncBatch,
    SyncCheckpoint,
    SyncItemState,
    SyncRun,
    SyncRunStatus,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
    QuarantineRepository,
    SyncBatchRepository,
    SyncCheckpointRepository,
    SyncRunRepository,
)
from apps.data_center.infrastructure.models import (
    CanonicalPublicationModel,
    PublicationMemberModel,
    PublicationRollbackModel,
)

NOW = datetime(2026, 8, 2, 5, 0, tzinfo=UTC)


def _ids() -> tuple[str, str, str]:
    return str(uuid4()), str(uuid4()), str(uuid4())


def test_sync_run_rejects_success_without_business_output() -> None:
    run_id, _, _ = _ids()
    with pytest.raises(ValueError, match="store or publish"):
        SyncRun(
            run_id=run_id,
            dataset_key="equity.daily",
            trigger="test",
            status=SyncRunStatus.PUBLISHED,
            outcome="success",
            requested=1,
            started_at=NOW,
            finished_at=NOW,
        )


def test_quarantine_requires_resolution_timestamp() -> None:
    quarantine_id, _, _ = _ids()
    with pytest.raises(ValueError, match="resolved_at"):
        QuarantineRecord(
            quarantine_id=quarantine_id,
            dataset_key="macro.china.cpi",
            provider_name="tushare",
            natural_key="20260701",
            reason_code="schema_mismatch",
            reason="missing required field",
            payload_hash="sha256:payload",
            schema_fingerprint="sha256:schema",
            payload={"period": "20260701"},
            resolution=QuarantineResolution.ACCEPTED,
            quarantined_at=NOW,
        )


def test_publication_coverage_ratio_fails_closed_for_empty_scope() -> None:
    coverage = CoverageSnapshot(
        coverage_id=str(uuid4()),
        publication_id=str(uuid4()),
        requested_count=0,
        eligible_count=0,
        selected_count=0,
        generated_at=NOW,
    )
    assert coverage.coverage_ratio == 0.0


@pytest.mark.django_db
def test_control_plane_repositories_are_idempotent_and_current_is_published_only() -> None:
    run_id, batch_id, checkpoint_id = _ids()
    run = SyncRun(
        run_id=run_id,
        dataset_key="equity.daily",
        trigger="pytest",
        status=SyncRunStatus.STORED,
        outcome="success",
        requested=1,
        succeeded=1,
        stored=1,
        started_at=NOW,
        finished_at=NOW,
    )
    assert SyncRunRepository().save(run).run_id == run_id

    batch = SyncBatch(
        batch_id=batch_id,
        run_id=run_id,
        dataset_key="equity.daily",
        provider_name="tushare",
        idempotency_key="equity.daily:tushare:20260802",
        state=SyncItemState.SUCCEEDED,
        requested=1,
        succeeded=1,
        stored=1,
        started_at=NOW,
        finished_at=NOW,
    )
    saved_batch = SyncBatchRepository().save(batch)
    assert SyncBatchRepository().get_by_idempotency_key(batch.idempotency_key) == saved_batch

    checkpoint = SyncCheckpoint(
        checkpoint_id=checkpoint_id,
        run_id=run_id,
        batch_id=batch_id,
        cursor_name="trade_date",
        cursor_value="20260802",
        recorded_at=NOW,
    )
    assert SyncCheckpointRepository().save(checkpoint).cursor_value == "20260802"

    publication_id = str(uuid4())
    coverage = CoverageSnapshot(
        coverage_id=str(uuid4()),
        publication_id=publication_id,
        requested_count=1,
        eligible_count=1,
        selected_count=1,
        generated_at=NOW,
    )
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key="equity.daily",
        publication_key="20260802",
        policy_version="equity.daily.v1",
        state=PublicationState.PUBLISHED,
        selected_source="tushare",
        publication_hash="sha256:publication",
        coverage=coverage,
        member_count=1,
        published_at=NOW,
        as_of=NOW,
    )
    member = PublicationMember(
        member_id=str(uuid4()),
        publication_id=publication_id,
        dataset_key="equity.daily",
        natural_key="000001.SZ|20260802",
        source="tushare",
        source_record_id="row-1",
        fact_table="data_center_price_bar",
        fact_pk="1",
        observed_at=NOW,
    )
    repository = CanonicalPublicationRepository()
    repository.add_member(member)
    repository.publish(publication)
    current = repository.get_current("equity.daily", "20260802")
    assert current is not None
    assert current.publication_id == publication_id
    assert repository.get_oldest_member_observed_at(publication_id) == NOW

    blocked = CanonicalPublication(
        publication_id=str(uuid4()),
        dataset_key="equity.daily",
        publication_key="blocked",
        policy_version="equity.daily.v1",
        state=PublicationState.BLOCKED,
        selected_source="",
        publication_hash="sha256:blocked",
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=str(uuid4()),
            requested_count=1,
            eligible_count=0,
            selected_count=0,
            generated_at=NOW,
        ),
        blocked_reason="coverage below threshold",
    )
    repository.save(blocked)
    assert repository.get_current("equity.daily", "blocked") is None


@pytest.mark.django_db
def test_control_plane_repositories_reject_identity_reuse() -> None:
    """Retries may update state, but stable control-plane keys cannot change owner."""

    run_id, batch_id, checkpoint_id = _ids()
    run = SyncRun(
        run_id=run_id,
        dataset_key="equity.daily",
        trigger="pytest",
        status=SyncRunStatus.STORED,
        outcome="success",
        requested=1,
        succeeded=1,
        stored=1,
        started_at=NOW,
        finished_at=NOW,
    )
    SyncRunRepository().save(run)
    with pytest.raises(ValueError, match="sync run identity conflict for dataset_key"):
        SyncRunRepository().save(replace(run, dataset_key="macro.cpi"))

    batch = SyncBatch(
        batch_id=batch_id,
        run_id=run_id,
        dataset_key="equity.daily",
        provider_name="tushare",
        idempotency_key="equity.daily:tushare:identity-guard",
        state=SyncItemState.SUCCEEDED,
        requested=1,
        succeeded=1,
        stored=1,
        started_at=NOW,
        finished_at=NOW,
    )
    SyncBatchRepository().save(batch)
    with pytest.raises(ValueError, match="sync batch identity conflict for batch_id"):
        SyncBatchRepository().save(replace(batch, batch_id=str(uuid4())))

    checkpoint = SyncCheckpoint(
        checkpoint_id=checkpoint_id,
        run_id=run_id,
        batch_id=batch_id,
        cursor_name="trade_date",
        cursor_value="20260802",
        recorded_at=NOW,
    )
    SyncCheckpointRepository().save(checkpoint)
    with pytest.raises(ValueError, match="sync checkpoint identity conflict for checkpoint_id"):
        SyncCheckpointRepository().save(replace(checkpoint, checkpoint_id=str(uuid4())))


@pytest.mark.django_db
def test_quarantine_repository_keeps_open_record_out_of_publication() -> None:
    record = QuarantineRecord(
        quarantine_id=str(uuid4()),
        dataset_key="macro.china.cpi",
        provider_name="tushare",
        natural_key="20260701",
        reason_code="stale",
        reason="source observation is outside contract window",
        payload_hash="sha256:payload",
        schema_fingerprint="sha256:schema",
        payload={"period": "20260701"},
        quarantined_at=NOW,
    )
    saved = QuarantineRepository().add(record)
    assert saved.resolution is QuarantineResolution.OPEN
    assert len(QuarantineRepository().list_open(dataset_key="macro.china.cpi")) == 1


@pytest.mark.django_db
def test_publication_as_of_never_returns_a_future_selection() -> None:
    repository = CanonicalPublicationRepository()
    first_id = str(uuid4())
    first_time = NOW.replace(day=1)
    first = CanonicalPublication(
        publication_id=first_id,
        dataset_key="equity.price.bar",
        publication_key="current",
        policy_version="price.v1",
        state=PublicationState.PUBLISHED,
        selected_source="fixture-a",
        publication_hash="sha256:first",
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=first_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            generated_at=first_time,
        ),
        member_count=1,
        published_at=first_time,
        as_of=first_time,
    )
    repository.add_member(
        PublicationMember(
            member_id=str(uuid4()),
            publication_id=first_id,
            dataset_key=first.dataset_key,
            natural_key="000001.SZ|20260801",
            source="fixture-a",
            source_record_id="a-1",
            fact_table="data_center_price_bar",
            fact_pk="1",
            observed_at=first_time,
        )
    )
    repository.publish(first)

    second_id = str(uuid4())
    second_time = NOW
    second = CanonicalPublication(
        publication_id=second_id,
        dataset_key=first.dataset_key,
        publication_key="current",
        policy_version="price.v1",
        state=PublicationState.PUBLISHED,
        selected_source="fixture-b",
        publication_hash="sha256:second",
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=second_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            generated_at=second_time,
        ),
        member_count=1,
        published_at=second_time,
        as_of=second_time,
    )
    repository.add_member(
        PublicationMember(
            member_id=str(uuid4()),
            publication_id=second_id,
            dataset_key=second.dataset_key,
            natural_key="000001.SZ|20260802",
            source="fixture-b",
            source_record_id="b-1",
            fact_table="data_center_price_bar",
            fact_pk="2",
            observed_at=second_time,
        )
    )
    repository.publish(second)

    historical = repository.get_as_of(
        first.dataset_key,
        "current",
        NOW.replace(day=1, hour=12),
    )
    assert historical is not None
    assert historical.publication_id == first_id


def _publication_with_members(
    *,
    publication_id: str,
    member_count: int,
    as_of: datetime = NOW,
) -> tuple[CanonicalPublication, tuple[PublicationMember, ...]]:
    """Build a valid publication snapshot fixture for writer contract tests."""

    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key="equity.daily",
        publication_key="current",
        policy_version="equity.daily.v1",
        state=PublicationState.PUBLISHED,
        selected_source="fixture",
        publication_hash=f"sha256:{publication_id}",
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=member_count,
            eligible_count=member_count,
            selected_count=member_count,
            generated_at=NOW,
        ),
        member_count=member_count,
        as_of=as_of,
        published_at=as_of,
    )
    members = tuple(
        PublicationMember(
            member_id=str(uuid4()),
            publication_id=publication_id,
            dataset_key=publication.dataset_key,
            natural_key=f"asset-{index}",
            source="fixture",
            source_record_id=f"row-{index}",
            fact_table="data_center_price_bar",
            fact_pk=str(index + 1),
            observed_at=as_of,
        )
        for index in range(member_count)
    )
    return publication, members


def test_publish_use_case_rejects_duplicate_member_snapshot() -> None:
    """The application port must reject duplicate natural/fact selections."""

    publication, members = _publication_with_members(
        publication_id=str(uuid4()),
        member_count=2,
    )
    duplicate = PublicationMember(
        member_id=members[1].member_id,
        publication_id=members[0].publication_id,
        dataset_key=members[0].dataset_key,
        natural_key=members[0].natural_key,
        source=members[0].source,
        source_record_id=members[0].source_record_id,
        fact_table=members[0].fact_table,
        fact_pk=members[0].fact_pk,
        observed_at=members[0].observed_at,
    )

    class _Repository:
        def publish_with_members(self, *_args):
            pytest.fail("invalid publication must be rejected before persistence")

    policy = PublicationPolicy(
        dataset=DatasetKey("equity.daily", "v1", "v1"),
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("raw_payload_hash",),
        retention_days=7,
    )
    with pytest.raises(ValueError, match="unique natural_key"):
        PublishCanonicalDatasetUseCase(_Repository()).execute(
            publication,
            policy=policy,
            members=(members[0], duplicate),
        )


@pytest.mark.django_db
def test_publish_with_members_rolls_back_candidate_and_members_on_failure(monkeypatch) -> None:
    """A member write failure must not leave a half-visible publication."""

    publication, members = _publication_with_members(
        publication_id=str(uuid4()),
        member_count=2,
    )
    repository = CanonicalPublicationRepository()
    original_add_member = repository.add_member
    calls = 0

    def _fail_on_second(member: PublicationMember) -> PublicationMember:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated member write failure")
        return original_add_member(member)

    monkeypatch.setattr(repository, "add_member", _fail_on_second)
    with pytest.raises(RuntimeError, match="simulated member write failure"):
        repository.publish_with_members(publication, members)

    assert not CanonicalPublicationModel._default_manager.filter(
        publication_id=publication.publication_id
    ).exists()
    assert not PublicationMemberModel._default_manager.filter(
        publication_id=publication.publication_id
    ).exists()


@pytest.mark.django_db
def test_explicit_publication_rollback_preserves_history_until_observed_boundary() -> None:
    """Rollback must be explicit and must not rewrite historical as-of reads."""

    repository = CanonicalPublicationRepository()
    first_time = NOW.replace(hour=1)
    second_time = NOW.replace(hour=2)
    first, first_members = _publication_with_members(
        publication_id=str(uuid4()),
        member_count=1,
        as_of=first_time,
    )
    second, second_members = _publication_with_members(
        publication_id=str(uuid4()),
        member_count=1,
        as_of=second_time,
    )
    repository.publish_with_members(first, first_members)
    repository.publish_with_members(second, second_members)

    current = repository.get_current(first.dataset_key, first.publication_key)
    assert current is not None
    assert current.publication_id == second.publication_id
    before_rollback = repository.get_as_of(
        first.dataset_key,
        first.publication_key,
        second_time.replace(minute=30),
    )
    assert before_rollback is not None
    assert before_rollback.publication_id == second.publication_id

    rollback_at = NOW
    restored = RollbackCanonicalPublicationUseCase(repository).execute(
        target_publication_id=first.publication_id,
        reason="restore verified prior snapshot",
        operator="operator-1",
        observed_at=rollback_at,
    )
    assert restored.publication_id == first.publication_id
    assert restored.reinstated_at == rollback_at
    current_after = repository.get_current(first.dataset_key, first.publication_key)
    assert current_after is not None
    assert current_after.publication_id == first.publication_id

    historical = repository.get_as_of(
        first.dataset_key,
        first.publication_key,
        second_time.replace(minute=30),
    )
    assert historical is not None
    assert historical.publication_id == second.publication_id
    after_rollback = repository.get_as_of(
        first.dataset_key,
        first.publication_key,
        rollback_at.replace(minute=1),
    )
    assert after_rollback is not None
    assert after_rollback.publication_id == first.publication_id

    evidence = PublicationRollbackModel._default_manager.get(
        target_publication_id=first.publication_id,
    )
    assert evidence.reason == "restore verified prior snapshot"
    assert evidence.operator == "operator-1"
    assert evidence.observed_at == rollback_at
    assert str(evidence.previous_publication_id) == second.publication_id


@pytest.mark.django_db
def test_publication_rollback_rejects_non_published_missing_evidence_and_bad_time() -> None:
    """Rollback refuses invalid targets, incomplete members and inconsistent time."""

    repository = CanonicalPublicationRepository()
    first_time = NOW.replace(hour=1)
    second_time = NOW.replace(hour=2)
    first, first_members = _publication_with_members(
        publication_id=str(uuid4()),
        member_count=1,
        as_of=first_time,
    )
    second, second_members = _publication_with_members(
        publication_id=str(uuid4()),
        member_count=1,
        as_of=second_time,
    )
    repository.publish_with_members(first, first_members)
    repository.publish_with_members(second, second_members)

    candidate_id = str(uuid4())
    candidate, _ = _publication_with_members(
        publication_id=candidate_id,
        member_count=1,
        as_of=first_time,
    )
    repository.save(replace(candidate, state=PublicationState.CANDIDATE))
    with pytest.raises(ValueError, match="superseded published"):
        repository.rollback(
            PublicationRollback(
                target_publication_id=candidate_id,
                reason="invalid target",
                operator="operator-1",
                observed_at=NOW,
            )
        )

    incomplete_id = str(uuid4())
    incomplete = CanonicalPublication(
        publication_id=incomplete_id,
        dataset_key=first.dataset_key,
        publication_key=first.publication_key,
        policy_version=first.policy_version,
        state=PublicationState.SUPERSEDED,
        selected_source="fixture",
        publication_hash=f"sha256:{incomplete_id}",
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=incomplete_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            generated_at=first_time,
        ),
        member_count=1,
        as_of=first_time,
        published_at=first_time,
        superseded_at=second_time,
    )
    repository.save(incomplete)
    with pytest.raises(ValueError, match="member evidence"):
        repository.rollback(
            PublicationRollback(
                target_publication_id=incomplete_id,
                reason="missing member evidence",
                operator="operator-1",
                observed_at=NOW,
            )
        )

    with pytest.raises(ValueError, match="later than current"):
        repository.rollback(
            PublicationRollback(
                target_publication_id=first.publication_id,
                reason="time mismatch",
                operator="operator-1",
                observed_at=second_time,
            )
        )


@pytest.mark.django_db
def test_publish_with_members_rejects_out_of_order_snapshot() -> None:
    """A late provider response must not rewind the current publication."""

    repository = CanonicalPublicationRepository()
    current_id = str(uuid4())
    current, current_members = _publication_with_members(
        publication_id=current_id,
        member_count=1,
    )
    repository.publish_with_members(current, current_members)

    late_time = NOW.replace(hour=4, minute=59)
    late_id = str(uuid4())
    late, late_members = _publication_with_members(
        publication_id=late_id,
        member_count=1,
        as_of=late_time,
    )
    with pytest.raises(ValueError, match="later than current"):
        repository.publish_with_members(late, late_members)

    active = repository.get_current("equity.daily", "current")
    assert active is not None
    assert active.publication_id == current_id
    assert not CanonicalPublicationModel._default_manager.filter(publication_id=late_id).exists()
