from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.data_center.application.publication_sync import PublishCapitalFlowBatchUseCase
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationFactReference
from apps.data_center.domain.entities import CapitalFlowFact
from apps.data_center.infrastructure.market_breadth_repositories import CapitalFlowRepository
from apps.data_center.infrastructure.models import CapitalFlowFactModel

PUBLISHED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


class _CandidateRepository:
    def __init__(self, references: list[PublicationFactReference]) -> None:
        self.references = references

    def list_publication_candidates(self, _facts):
        return list(self.references)


class _PolicyRepository:
    def get_active(self, _dataset_key: str):
        return PublicationPolicy(
            dataset=DatasetKey("market.capital_flow", "1.0", "1.0"),
            minimum_coverage_ratio=0.99,
            allow_partial=True,
            conflict_action="block",
            required_evidence=("source", "observed_at", "payload_hash"),
            retention_days=730,
        )


class _PublicationRepository:
    def __init__(self) -> None:
        self.current: CanonicalPublication | None = None
        self.published: list[tuple[CanonicalPublication, tuple[object, ...]]] = []

    def get_current(self, _dataset_key: str, _publication_key: str):
        return self.current

    def publish_with_members(self, publication, members):
        self.current = publication
        self.published.append((publication, members))
        return publication


def _fact(asset_code: str, flow_date: date) -> CapitalFlowFact:
    return CapitalFlowFact(
        asset_code=asset_code,
        flow_date=flow_date,
        main_net=10.0,
        retail_net=-2.0,
        source="provider-main",
        # Deliberately later than flow_date: this must not become observed_at.
        fetched_at=PUBLISHED_AT,
    )


def _reference(asset_code: str, flow_date: date, fact_pk: str) -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=f"{asset_code}:{flow_date.isoformat()}:provider-main",
        source="provider-main",
        source_record_id=f"{asset_code}:{flow_date.isoformat()}",
        fact_table="data_center_capital_flow_fact",
        fact_pk=fact_pk,
        observed_at=datetime.combine(flow_date, datetime.min.time(), tzinfo=UTC),
        raw_payload_hash="b" * 64,
    )


def test_capital_flow_publication_uses_flow_date_as_of_and_exact_members() -> None:
    facts = [_fact("000001.SZ", date(2026, 8, 3)), _fact("600000.SH", date(2026, 8, 3))]
    repository = _PublicationRepository()
    use_case = PublishCapitalFlowBatchUseCase(
        fact_repository=_CandidateRepository(
            [
                _reference("000001.SZ", date(2026, 8, 3), "101"),
                _reference("600000.SH", date(2026, 8, 3), "102"),
            ]
        ),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )

    publication = use_case.execute(
        facts,
        provider_name="provider-main",
        published_at=PUBLISHED_AT,
    )

    assert publication is not None
    assert publication.as_of == datetime(2026, 8, 3, tzinfo=UTC)
    assert publication.as_of != facts[0].fetched_at
    assert publication.coverage.selected_count == 2
    assert publication.coverage.missing_count == 0
    assert {member.fact_pk for member in repository.published[0][1]} == {"101", "102"}


def test_capital_flow_publication_is_idempotent_for_same_snapshot() -> None:
    facts = [_fact("000001.SZ", date(2026, 8, 3))]
    repository = _PublicationRepository()
    use_case = PublishCapitalFlowBatchUseCase(
        fact_repository=_CandidateRepository([_reference("000001.SZ", date(2026, 8, 3), "101")]),
        publication_repository=repository,
        policy_repository=_PolicyRepository(),
    )

    first = use_case.execute(facts, provider_name="provider-main", published_at=PUBLISHED_AT)
    second = use_case.execute(facts, provider_name="provider-main", published_at=PUBLISHED_AT)

    assert first is second
    assert len(repository.published) == 1


def test_capital_flow_publication_fails_closed_below_coverage_policy() -> None:
    facts = [_fact("000001.SZ", date(2026, 8, 3)), _fact("600000.SH", date(2026, 8, 3))]
    use_case = PublishCapitalFlowBatchUseCase(
        fact_repository=_CandidateRepository([_reference("000001.SZ", date(2026, 8, 3), "101")]),
        publication_repository=_PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )

    with pytest.raises(ValueError, match="coverage"):
        use_case.execute(facts, provider_name="provider-main", published_at=PUBLISHED_AT)


@pytest.mark.django_db
def test_capital_flow_repository_candidate_preserves_flow_date_observation() -> None:
    row = CapitalFlowFactModel.objects.create(
        asset_code="000001.SZ",
        flow_date=date(2026, 8, 3),
        main_net=10,
        retail_net=-2,
        source="provider-main",
        source_record_id="flow-1",
        raw_payload_hash="c" * 64,
        fetched_at=PUBLISHED_AT,
    )

    references = CapitalFlowRepository().list_publication_candidates(
        [_fact("000001.SZ", date(2026, 8, 3))]
    )

    assert len(references) == 1
    assert references[0].fact_pk == str(row.pk)
    assert references[0].source_record_id == "flow-1"
    assert references[0].raw_payload_hash == "c" * 64
    assert references[0].observed_at == datetime(2026, 8, 3, tzinfo=UTC)
    assert references[0].observed_at != row.fetched_at
