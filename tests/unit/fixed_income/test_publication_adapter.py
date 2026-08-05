"""Unit coverage for the Data Center publication adapter."""

from datetime import UTC, datetime

from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationState,
)
from apps.fixed_income.domain.entities import InputRole
from apps.fixed_income.infrastructure.publication_adapter import (
    DataCenterPublishedInputAdapter,
    PublishedDatasetRequest,
)


class _PublicationRepository:
    def __init__(
        self,
        publication: CanonicalPublication | None,
        observed_at: datetime | None,
    ) -> None:
        self.publication = publication
        self.observed_at = observed_at

    def get_as_of(
        self,
        dataset_key: str,
        publication_key: str,
        as_of: datetime,
    ) -> CanonicalPublication | None:
        del dataset_key, publication_key, as_of
        return self.publication

    def get_oldest_member_observed_at(self, publication_id: str) -> datetime | None:
        del publication_id
        return self.observed_at


class _FreshnessReader:
    def __init__(self, seconds: int | None) -> None:
        self.seconds = seconds

    def get_freshness_seconds(self, dataset_key: str) -> int | None:
        del dataset_key
        return self.seconds


def _publication() -> CanonicalPublication:
    published_at = datetime(2024, 1, 1, 8, tzinfo=UTC)
    return CanonicalPublication(
        publication_id="curve-publication-v1",
        dataset_key="r5_government_curve",
        publication_key="research",
        policy_version="policy-v1",
        state=PublicationState.PUBLISHED,
        selected_source="gold-provider",
        publication_hash="e" * 64,
        coverage=CoverageSnapshot(
            coverage_id="coverage-v1",
            publication_id="curve-publication-v1",
            requested_count=2,
            eligible_count=2,
            selected_count=2,
            missing_count=0,
            conflict_count=0,
            generated_at=published_at,
        ),
        member_count=2,
        conflict_count=0,
        as_of=published_at,
        published_at=published_at,
        superseded_at=None,
        reinstated_at=None,
        must_not_use_for_decision=False,
        blocked_reason="",
        created_by="test",
        run_id="run-v1",
    )


def test_adapter_resolves_fresh_pit_visible_publication() -> None:
    observed_at = datetime(2024, 1, 1, 7, tzinfo=UTC)
    repository = _PublicationRepository(_publication(), observed_at)
    adapter = DataCenterPublishedInputAdapter(repository, _FreshnessReader(86400))

    resolution = adapter.resolve(
        PublishedDatasetRequest(
            role=InputRole.GOVERNMENT_CURVE,
            dataset_key="r5_government_curve",
            publication_key="research",
        ),
        as_of=datetime(2024, 1, 1, 9, tzinfo=UTC),
    )

    assert resolution.blocked_reason is None
    assert resolution.reference is not None
    assert resolution.reference.publication_id == "curve-publication-v1"
    assert resolution.reference.observed_at == observed_at


def test_adapter_fails_closed_for_stale_publication() -> None:
    repository = _PublicationRepository(
        _publication(),
        datetime(2024, 1, 1, 7, tzinfo=UTC),
    )
    adapter = DataCenterPublishedInputAdapter(repository, _FreshnessReader(3600))

    resolution = adapter.resolve(
        PublishedDatasetRequest(
            role=InputRole.GOVERNMENT_CURVE,
            dataset_key="r5_government_curve",
            publication_key="research",
        ),
        as_of=datetime(2024, 1, 1, 9, tzinfo=UTC),
    )

    assert resolution.reference is None
    assert resolution.blocked_reason == "canonical_publication_stale"
