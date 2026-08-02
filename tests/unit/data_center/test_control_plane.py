"""Contract and persistence tests for the Data Center control plane."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

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
