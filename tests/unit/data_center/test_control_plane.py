"""Contract and persistence tests for the Data Center control plane."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.data_center.application.control_plane import PublishCanonicalDatasetUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
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
