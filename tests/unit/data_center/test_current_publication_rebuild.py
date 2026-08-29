"""Full-universe current-publication rebuild contracts."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.application.current_publication_rebuild import (
    CoreCurrentPublicationRebuildUseCase,
    CurrentPublicationDataset,
    CurrentPublicationPreview,
    CurrentPublicationRebuildUseCase,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationFactReference,
)

NOW = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)


def test_preview_serialization_bounds_asset_code_evidence() -> None:
    missing = tuple(f"{index:06d}.SZ" for index in range(25))
    unexpected = tuple(f"{index:06d}.SH" for index in range(30))
    payload = CurrentPublicationPreview(
        dataset_key="equity.financial.fact",
        requested_asset_count=25,
        covered_asset_count=0,
        member_count=0,
        missing_asset_codes=missing,
        unexpected_asset_codes=unexpected,
        oldest_observed_at=None,
        newest_observed_at=None,
    ).to_dict()

    assert payload["missing_asset_count"] == 25
    assert payload["missing_asset_codes"] == list(missing[:20])
    assert payload["missing_asset_codes_truncated"] is True
    assert payload["unexpected_asset_count"] == 30
    assert payload["unexpected_asset_codes"] == list(unexpected[:20])
    assert payload["unexpected_asset_codes_truncated"] is True


class _CandidateRepository:
    def __init__(self, references: list[PublicationFactReference]) -> None:
        self.references = references
        self.calls: list[tuple[str, ...]] = []

    def list_current_publication_candidates(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[PublicationFactReference]:
        self.calls.append(asset_codes)
        return list(self.references)


class _PolicyRepository:
    def get_active(self, dataset_key: str) -> PublicationPolicy:
        return PublicationPolicy(
            dataset=DatasetKey(dataset_key, "1.0", "1.0"),
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=("source", "observed_at", "payload_hash"),
            retention_days=3650,
        )


class _PublicationRepository:
    def __init__(self) -> None:
        self.current: dict[tuple[str, str], CanonicalPublication] = {}
        self.members: dict[str, tuple[object, ...]] = {}
        self.published: list[CanonicalPublication] = []

    def get_current(
        self,
        dataset_key: str,
        publication_key: str,
    ) -> CanonicalPublication | None:
        return self.current.get((dataset_key, publication_key))

    def list_members(self, publication_id: str) -> list[object]:
        return list(self.members.get(publication_id, ()))

    def publish_with_members(self, publication, members):
        self.current[(publication.dataset_key, publication.publication_key)] = publication
        self.members[publication.publication_id] = tuple(members)
        self.published.append(publication)
        return publication


def _reference(
    asset_code: str,
    fact_pk: str,
    *,
    dataset: CurrentPublicationDataset,
    observed_at: datetime = NOW - timedelta(hours=1),
    suffix: str = "latest",
) -> PublicationFactReference:
    return PublicationFactReference(
        natural_key=f"{asset_code}:{suffix}:source-main",
        source="source-main",
        source_record_id=f"record-{fact_pk}",
        fact_table=dataset.fact_table,
        fact_pk=fact_pk,
        observed_at=observed_at,
        raw_payload_hash="a" * 64,
    )


def _use_case(
    dataset: CurrentPublicationDataset,
    references: list[PublicationFactReference],
    publications: _PublicationRepository | None = None,
) -> CurrentPublicationRebuildUseCase:
    return CurrentPublicationRebuildUseCase(
        dataset=dataset,
        candidate_repository=_CandidateRepository(references),
        publication_repository=publications or _PublicationRepository(),
        policy_repository=_PolicyRepository(),
    )


def test_rebuild_publishes_exact_full_universe_and_is_idempotent() -> None:
    dataset = CurrentPublicationDataset(
        dataset_key="equity.price.bar",
        fact_table="data_center_price_bar",
        created_by="ops.current_publication_rebuild",
    )
    repository = _PublicationRepository()
    use_case = _use_case(
        dataset,
        [
            _reference("000001.SZ", "1", dataset=dataset),
            _reference("600000.SH", "2", dataset=dataset),
        ],
        repository,
    )

    first = use_case.execute(
        asset_codes=["600000.sh", "000001.SZ", "000001.sz"],
        published_at=NOW,
        run_id="",
    )
    second = use_case.execute(
        asset_codes=["000001.SZ", "600000.SH"],
        published_at=NOW + timedelta(seconds=1),
        run_id="",
    )

    assert first is second
    assert first.member_count == 2
    assert first.coverage.requested_count == 2
    assert first.coverage.missing_count == 0
    assert first.as_of == NOW - timedelta(hours=1)
    assert len(repository.published) == 1


def test_rebuild_preview_reports_missing_asset_and_execute_fails_closed() -> None:
    dataset = CurrentPublicationDataset(
        dataset_key="equity.valuation.fact",
        fact_table="data_center_valuation_fact",
        created_by="ops.current_publication_rebuild",
    )
    use_case = _use_case(
        dataset,
        [_reference("000001.SZ", "1", dataset=dataset)],
    )

    preview = use_case.preview(
        asset_codes=["000001.SZ", "600000.SH"],
        published_at=NOW,
    )

    assert preview.ready is False
    assert preview.covered_asset_count == 1
    assert preview.missing_asset_codes == ("600000.SH",)
    with pytest.raises(ValueError, match="missing active assets"):
        use_case.execute(
            asset_codes=["000001.SZ", "600000.SH"],
            published_at=NOW,
        )


def test_rebuild_rejects_wrong_fact_table_and_future_observation() -> None:
    dataset = CurrentPublicationDataset(
        dataset_key="equity.financial.fact",
        fact_table="data_center_financial_fact",
        created_by="ops.current_publication_rebuild",
    )
    wrong_table = PublicationFactReference(
        natural_key="000001.SZ:latest:source-main",
        source="source-main",
        source_record_id="record-1",
        fact_table="data_center_price_bar",
        fact_pk="1",
        observed_at=NOW - timedelta(hours=1),
        raw_payload_hash="a" * 64,
    )
    with pytest.raises(ValueError, match="fact table mismatch"):
        _use_case(dataset, [wrong_table]).preview(
            asset_codes=["000001.SZ"],
            published_at=NOW,
        )

    future = _reference(
        "000001.SZ",
        "2",
        dataset=dataset,
        observed_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="future observation"):
        _use_case(dataset, [future]).preview(
            asset_codes=["000001.SZ"],
            published_at=NOW,
        )


def test_financial_rebuild_allows_multiple_latest_metrics_per_asset() -> None:
    dataset = CurrentPublicationDataset(
        dataset_key="equity.financial.fact",
        fact_table="data_center_financial_fact",
        created_by="ops.current_publication_rebuild",
    )
    use_case = _use_case(
        dataset,
        [
            _reference("000001.SZ", "1", dataset=dataset, suffix="revenue"),
            _reference("000001.SZ", "2", dataset=dataset, suffix="net_profit"),
            _reference("600000.SH", "3", dataset=dataset, suffix="revenue"),
        ],
    )

    publication = use_case.execute(
        asset_codes=["000001.SZ", "600000.SH"],
        published_at=NOW,
    )

    assert publication.member_count == 3
    assert publication.coverage.requested_count == 3
    assert publication.coverage.selected_count == 3


def test_core_rebuild_wraps_all_three_publications_in_one_transaction() -> None:
    datasets = (
        CurrentPublicationDataset(
            "equity.price.bar",
            "data_center_price_bar",
            "ops.current_publication_rebuild",
        ),
        CurrentPublicationDataset(
            "equity.valuation.fact",
            "data_center_valuation_fact",
            "ops.current_publication_rebuild",
        ),
        CurrentPublicationDataset(
            "equity.financial.fact",
            "data_center_financial_fact",
            "ops.current_publication_rebuild",
        ),
    )
    publications = _PublicationRepository()
    rebuilders = tuple(
        _use_case(dataset, [_reference("000001.SZ", str(index), dataset=dataset)], publications)
        for index, dataset in enumerate(datasets, start=1)
    )
    transaction_entries: list[str] = []

    class _Transaction:
        def __enter__(self) -> None:
            transaction_entries.append("enter")

        def __exit__(self, *_args: object) -> None:
            transaction_entries.append("exit")

    coordinator = CoreCurrentPublicationRebuildUseCase(
        rebuilders=rebuilders,
        transaction=lambda: _Transaction(),
    )

    result = coordinator.execute(asset_codes=["000001.SZ"], published_at=NOW)

    assert transaction_entries == ["enter", "exit"]
    assert result.published_count == 3
    assert set(result.publication_ids) == {item.publication_id for item in publications.published}


def test_core_preview_is_read_only() -> None:
    dataset = CurrentPublicationDataset(
        "equity.price.bar",
        "data_center_price_bar",
        "ops.current_publication_rebuild",
    )
    publications = _PublicationRepository()
    coordinator = CoreCurrentPublicationRebuildUseCase(
        rebuilders=(
            _use_case(
                dataset,
                [_reference("000001.SZ", "1", dataset=dataset)],
                publications,
            ),
        ),
        transaction=nullcontext,
    )

    payload = coordinator.preview(asset_codes=["000001.SZ"], published_at=NOW)

    assert payload.ready is True
    assert payload.member_count == 1
    assert publications.published == []
