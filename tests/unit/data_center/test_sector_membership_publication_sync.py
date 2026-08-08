from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.data_center.application.publication_sync import PublishSectorMembershipBatchUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import SectorMembershipFact
from apps.data_center.infrastructure.market_breadth_repositories import SectorMembershipRepository
from apps.data_center.infrastructure.models import SectorMembershipFactModel

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
EFFECTIVE = date(2026, 8, 3)


class _Candidates:
    def __init__(self, refs):
        self.refs = refs

    def list_publication_candidates(self, _facts):
        return list(self.refs)


class _Policies:
    def get_active(self, _key):
        return PublicationPolicy(
            dataset=DatasetKey("sector.membership", "1.0", "1.0"),
            minimum_coverage_ratio=0.99,
            allow_partial=True,
            conflict_action="block",
            required_evidence=("source", "observed_at", "payload_hash"),
            retention_days=1825,
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


def _fact(asset_code: str) -> SectorMembershipFact:
    return SectorMembershipFact(
        asset_code=asset_code,
        sector_code="399300.SZ",
        sector_name="CSI 300",
        effective_date=EFFECTIVE,
        source="provider-main",
        fetched_at=NOW,
    )


def _ref(asset_code: str, fact_pk: str) -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=f"{asset_code}:399300.SZ:{EFFECTIVE.isoformat()}",
        source="provider-main",
        source_record_id=f"membership-{asset_code}",
        fact_table="data_center_sector_membership",
        fact_pk=fact_pk,
        observed_at=datetime(2026, 8, 3, tzinfo=UTC),
        raw_payload_hash="a" * 64,
    )


def test_sector_publication_uses_effective_date_as_of_and_exact_members() -> None:
    repository = _Publications()
    use_case = PublishSectorMembershipBatchUseCase(
        fact_repository=_Candidates([_ref("000001.SZ", "401")]),
        publication_repository=repository,
        policy_repository=_Policies(),
    )

    publication = use_case.execute(
        [_fact("000001.SZ")], provider_name="provider-main", published_at=NOW
    )

    assert publication is not None
    assert publication.as_of == datetime(2026, 8, 3, tzinfo=UTC)
    assert publication.as_of != _fact("000001.SZ").fetched_at
    assert repository.writes[0][1][0].fact_pk == "401"


def test_sector_publication_is_idempotent_for_same_snapshot() -> None:
    repository = _Publications()
    use_case = PublishSectorMembershipBatchUseCase(
        fact_repository=_Candidates([_ref("000001.SZ", "401")]),
        publication_repository=repository,
        policy_repository=_Policies(),
    )
    first = use_case.execute([_fact("000001.SZ")], provider_name="provider-main", published_at=NOW)
    second = use_case.execute([_fact("000001.SZ")], provider_name="provider-main", published_at=NOW)

    assert first is second
    assert len(repository.writes) == 1


@pytest.mark.django_db
def test_sector_repository_candidate_preserves_effective_date_observation() -> None:
    row = SectorMembershipFactModel.objects.create(
        asset_code="000001.SZ",
        sector_code="399300.SZ",
        sector_name="CSI 300",
        effective_date=EFFECTIVE,
        source="provider-main",
        source_record_id="membership-1",
        raw_payload_hash="b" * 64,
        fetched_at=NOW,
    )
    refs = SectorMembershipRepository().list_publication_candidates([_fact("000001.SZ")])

    assert refs[0].fact_pk == str(row.pk)
    assert refs[0].observed_at == datetime(2026, 8, 2, 16, tzinfo=UTC)
    assert refs[0].observed_at != row.fetched_at
    assert refs[0].raw_payload_hash == "b" * 64
