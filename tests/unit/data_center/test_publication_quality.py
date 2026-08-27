"""RED contracts for Data Center publication-quality projection and recording."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.audit.application.data_quality_audit import DataQualityAuditObservation
from apps.data_center.application.publication_quality import (
    PublicationQualityProjection,
    PublicationQualityStatusCount,
    RecordPublicationQualityUseCase,
    project_publication_quality,
)
from apps.data_center.application.publication_utils import publication_hash
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationFactReference,
    PublicationMember,
    PublicationState,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _publication_and_members(
    statuses: tuple[str, ...] = ("valid", "estimated"),
) -> tuple[CanonicalPublication, tuple[PublicationMember, ...]]:
    """Build one complete persisted publication and its member snapshot."""

    publication_id = str(uuid4())
    dataset_key = "equity.daily"
    members = tuple(
        PublicationMember(
            member_id=str(uuid4()),
            publication_id=publication_id,
            dataset_key=dataset_key,
            natural_key=f"asset-{index}",
            source="provider-main",
            source_record_id=f"row-{index}",
            fact_table="data_center_price_bar",
            fact_pk=str(index),
            observed_at=NOW,
            quality_status=status,
        )
        for index, status in enumerate(statuses, start=1)
    )
    references = tuple(
        PublicationFactReference(
            natural_key=member.natural_key,
            source=member.source,
            source_record_id=member.source_record_id,
            fact_table=member.fact_table,
            fact_pk=member.fact_pk,
            observed_at=NOW,
            raw_payload_hash=member.raw_payload_hash,
            quality_status=member.quality_status,
            revision_number=member.revision_number,
        )
        for member in members
    )
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key=dataset_key,
        publication_key="current",
        policy_version="equity.daily.v1",
        state=PublicationState.PUBLISHED,
        selected_source="provider-main",
        publication_hash=publication_hash(references),
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=len(statuses),
            eligible_count=len(statuses),
            selected_count=len(statuses),
            generated_at=NOW,
        ),
        member_count=len(statuses),
        published_at=NOW,
        as_of=NOW,
        run_id="run-1",
    )
    return publication, members


@pytest.mark.parametrize(
    ("raw_status", "expected_state"),
    [
        ("accepted", "accepted"),
        ("valid", "accepted"),
        ("verified", "accepted"),
        ("estimated", "degraded"),
        ("error", "degraded"),
        ("missing", "degraded"),
        ("available_at_unverified", "degraded"),
    ],
)
def test_projection_explicitly_maps_member_quality(raw_status: str, expected_state: str) -> None:
    """Raw member statuses map only through the Data Center quality policy."""

    publication, members = _publication_and_members((raw_status,))
    projection = project_publication_quality(publication, members)

    assert isinstance(projection, PublicationQualityProjection)
    assert projection.quality_state == expected_state
    assert projection.member_count == 1
    assert projection.publication_id == publication.publication_id
    assert projection.dataset_key == publication.dataset_key
    assert projection.publication_hash == publication.publication_hash


@pytest.mark.parametrize("raw_status", ["stale", "unknown", "", " "])
def test_projection_rejects_forbidden_quality_status(raw_status: str) -> None:
    """Stale, unknown, and blank quality cannot be silently classified."""

    publication, members = _publication_and_members((raw_status,))
    with pytest.raises((TypeError, ValueError)):
        project_publication_quality(publication, members)


def test_projection_rejects_empty_members_and_recomputes_exact_identity() -> None:
    """A complete member snapshot verifies count, dataset, and hash."""

    publication, members = _publication_and_members()
    projection = project_publication_quality(publication, members)

    assert projection.member_count == len(members)
    assert projection.publication_id == publication.publication_id
    assert projection.dataset_key == publication.dataset_key
    assert projection.publication_hash == publication.publication_hash
    assert projection.quality_status_counts == (
        PublicationQualityStatusCount(status="accepted", count=1),
        PublicationQualityStatusCount(status="degraded", count=1),
    )
    with pytest.raises((TypeError, ValueError)):
        project_publication_quality(publication, ())


class _PublicationReader:
    """Reload seam proving recording uses persisted publication/member state."""

    def __init__(self, publication: CanonicalPublication, members: tuple[PublicationMember, ...]):
        self.publication = publication
        self.members = members
        self.calls: list[str] = []

    @property
    def unit_of_work_key(self) -> str:
        return "django:default"

    def get_by_id(self, publication_id: str) -> CanonicalPublication | None:
        self.calls.append(f"publication:{publication_id}")
        return self.publication if publication_id == self.publication.publication_id else None

    def list_members(self, publication_id: str) -> tuple[PublicationMember, ...]:
        self.calls.append(f"members:{publication_id}")
        return self.members


class _QualityWriter:
    """Typed writer fake for exact observation recording."""

    database_alias = "default"

    def __init__(self) -> None:
        self.observations: list[DataQualityAuditObservation] = []

    def write(self, observation: DataQualityAuditObservation) -> None:
        self.observations.append(observation)


class _Clock:
    """Deterministic application clock."""

    def now(self) -> datetime:
        return NOW


def test_record_reloads_members_and_writes_exact_quality_observation() -> None:
    """Recording preserves publication evidence and run identity."""

    publication, members = _publication_and_members(("verified",))
    reader = _PublicationReader(publication, members)
    writer = _QualityWriter()
    use_case = RecordPublicationQualityUseCase(
        publication_reader=reader,
        quality_writer=writer,
        clock=_Clock(),
    )
    observation = use_case.execute(
        publication_id=publication.publication_id,
        run_id="run-1",
        ingested_run_id="ingested-1",
        provider_key="provider-main",
    )

    assert isinstance(observation, DataQualityAuditObservation)
    assert observation.publication_id == publication.publication_id
    assert observation.publication_hash == publication.publication_hash
    assert observation.dataset_key == publication.dataset_key
    assert observation.run_id == "run-1"
    assert observation.ingested_run_id == "ingested-1"
    assert reader.calls == [
        f"publication:{publication.publication_id}",
        f"members:{publication.publication_id}",
    ]
    assert writer.observations == [observation]


def test_record_propagates_writer_failure_without_fallback() -> None:
    """Required quality-audit writer failures remain visible."""

    publication, members = _publication_and_members(("verified",))
    reader = _PublicationReader(publication, members)

    class _FailingWriter(_QualityWriter):
        def write(self, observation: DataQualityAuditObservation) -> None:
            del observation
            raise RuntimeError("quality writer backend failure")

    use_case = RecordPublicationQualityUseCase(
        publication_reader=reader,
        quality_writer=_FailingWriter(),
        clock=_Clock(),
    )
    with pytest.raises(RuntimeError, match="quality writer backend failure"):
        use_case.execute(
            publication_id=publication.publication_id,
            run_id="run-1",
            ingested_run_id="ingested-1",
            provider_key="provider-main",
        )
