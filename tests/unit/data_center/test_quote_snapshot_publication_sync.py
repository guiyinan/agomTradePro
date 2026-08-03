from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.data_center.application.publication_sync import PublishQuoteSnapshotBatchUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import QuoteSnapshot
from apps.data_center.infrastructure.market_data_repositories import QuoteSnapshotRepository
from apps.data_center.infrastructure.models import QuoteSnapshotModel

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
SNAPSHOT = datetime(2026, 8, 4, 11, 59, tzinfo=UTC)


class _Candidates:
    def __init__(self, refs):
        self.refs = refs

    def list_publication_candidates(self, _quotes):
        return list(self.refs)


class _Policies:
    def get_active(self, _key):
        return PublicationPolicy(
            dataset=DatasetKey("equity.quote.snapshot", "1.0", "1.0"),
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=("source", "observed_at", "fetched_at", "payload_hash"),
            retention_days=90,
        )


class _Publications:
    def __init__(self):
        self.current = None
        self.writes = []

    def get_current(self, *_args):
        return self.current

    def publish_with_members(self, publication, members):
        self.current = publication
        self.writes.append((publication, members))
        return publication


def _quote(asset_code: str = "000001.SZ") -> QuoteSnapshot:
    return QuoteSnapshot(
        asset_code=asset_code,
        snapshot_at=SNAPSHOT,
        fetched_at=NOW,
        current_price=10.2,
        source="provider-main",
    )


def _ref(asset_code: str = "000001.SZ", fact_pk: str = "301") -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=f"{asset_code}:{SNAPSHOT.isoformat()}:provider-main",
        source="provider-main",
        source_record_id=f"quote-{asset_code}",
        fact_table="data_center_quote_snapshot",
        fact_pk=fact_pk,
        observed_at=SNAPSHOT,
        raw_payload_hash="f" * 64,
    )


def test_quote_publication_preserves_snapshot_observation_and_member_pk() -> None:
    repository = _Publications()
    use_case = PublishQuoteSnapshotBatchUseCase(
        fact_repository=_Candidates([_ref()]),
        publication_repository=repository,
        policy_repository=_Policies(),
    )

    publication = use_case.execute([_quote()], provider_name="provider-main", published_at=NOW)

    assert publication is not None
    assert publication.as_of == SNAPSHOT
    assert publication.as_of != NOW
    assert repository.writes[0][1][0].fact_pk == "301"


def test_quote_publication_is_idempotent_for_same_snapshot() -> None:
    repository = _Publications()
    use_case = PublishQuoteSnapshotBatchUseCase(
        fact_repository=_Candidates([_ref()]),
        publication_repository=repository,
        policy_repository=_Policies(),
    )
    first = use_case.execute([_quote()], provider_name="provider-main", published_at=NOW)
    second = use_case.execute([_quote()], provider_name="provider-main", published_at=NOW)

    assert first is second
    assert len(repository.writes) == 1


@pytest.mark.django_db
def test_quote_repository_candidate_keeps_snapshot_at_not_fetched_at() -> None:
    row = QuoteSnapshotModel.objects.create(
        asset_code="000001.SZ",
        snapshot_at=SNAPSHOT,
        fetched_at=NOW,
        current_price=10.2,
        source="provider-main",
        source_record_id="quote-1",
        raw_payload_hash="a" * 64,
    )
    refs = QuoteSnapshotRepository().list_publication_candidates([_quote()])

    assert refs[0].fact_pk == str(row.pk)
    assert refs[0].observed_at == SNAPSHOT
    assert refs[0].observed_at != row.fetched_at
    assert refs[0].raw_payload_hash == "a" * 64
