"""Full-universe current-publication rebuild contracts."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.data_center.application.current_publication_rebuild import (
    CoreCurrentPublicationRebuildUseCase,
    CurrentPublicationDataset,
    CurrentPublicationPreview,
    CurrentPublicationRebuildUseCase,
    CurrentPublicationScopeExclusion,
)
from apps.data_center.application.publication_utils import (
    current_publication_id_for_hash,
    publication_hash,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationFactReference,
    PublicationState,
)
from apps.data_center.domain.market_time import cn_market_date_from_observation

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
        self.date_probe_calls: list[tuple[tuple[str, ...], date]] = []

    def list_current_publication_candidates(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[PublicationFactReference]:
        self.calls.append(asset_codes)
        requested = set(asset_codes)
        return [
            reference
            for reference in self.references
            if reference.natural_key.split(":", 1)[0] in requested
        ]

    def list_asset_codes_with_observation_on_date(
        self,
        asset_codes: tuple[str, ...],
        observation_date: date,
    ) -> tuple[str, ...]:
        self.date_probe_calls.append((asset_codes, observation_date))
        requested = set(asset_codes)
        return tuple(
            sorted(
                {
                    reference.natural_key.split(":", 1)[0]
                    for reference in self.references
                    if reference.natural_key.split(":", 1)[0] in requested
                    and cn_market_date_from_observation(reference.observed_at) == observation_date
                }
            )
        )


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


class _PartialPolicyRepository:
    def __init__(
        self,
        *,
        minimum_coverage_ratio: float = 0.99,
        allow_partial: bool = True,
    ) -> None:
        self.minimum_coverage_ratio = minimum_coverage_ratio
        self.allow_partial = allow_partial

    def get_active(self, dataset_key: str) -> PublicationPolicy:
        return PublicationPolicy(
            dataset=DatasetKey(dataset_key, "1.0", "1.0"),
            minimum_coverage_ratio=self.minimum_coverage_ratio,
            allow_partial=self.allow_partial,
            conflict_action="block",
            required_evidence=("source", "observed_at", "payload_hash"),
            retention_days=3650,
            policy_version="scope-partial-v1",
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
    observed_at: datetime | None = None,
    suffix: str = "latest",
) -> PublicationFactReference:
    if observed_at is None:
        observed_at = (
            datetime(2026, 8, 28, 7, 0, tzinfo=UTC)
            if dataset.dataset_key == "equity.quote.snapshot"
            else NOW - timedelta(hours=1)
        )
    natural_key_suffix = suffix
    if dataset.dataset_key == "equity.valuation.fact" and suffix == "latest":
        natural_key_suffix = NOW.date().isoformat()
    return PublicationFactReference(
        natural_key=f"{asset_code}:{natural_key_suffix}:source-main",
        source="source-main",
        source_record_id=f"record-{fact_pk}",
        fact_table=dataset.fact_table,
        fact_pk=fact_pk,
        observed_at=observed_at,
        raw_payload_hash="a" * 64,
        available_at=observed_at,
        fetched_at=observed_at,
        source_published_at=observed_at,
        raw_payload_scope="record",
        fact_content_hash="b" * 64,
    )


def _use_case(
    dataset: CurrentPublicationDataset,
    references: list[PublicationFactReference],
    publications: _PublicationRepository | None = None,
    policy_repository: object | None = None,
) -> CurrentPublicationRebuildUseCase:
    return CurrentPublicationRebuildUseCase(
        dataset=dataset,
        candidate_repository=_CandidateRepository(references),
        publication_repository=publications or _PublicationRepository(),
        policy_repository=policy_repository or _PolicyRepository(),
    )


def test_candidate_preparation_and_legacy_execute_share_identical_snapshot_content() -> None:
    """Fence-external preparation and legacy publication use one candidate builder."""

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

    candidate = use_case.prepare_candidate(
        asset_codes=("000001.SZ", "600000.SH"),
        published_at=NOW,
        run_id="candidate-run",
    )
    published = use_case.execute(
        asset_codes=("000001.SZ", "600000.SH"),
        published_at=NOW,
        run_id="candidate-run",
    )

    assert candidate.publication.state is PublicationState.CANDIDATE
    assert candidate.publication.published_at is None
    assert (
        replace(
            candidate.publication,
            state=PublicationState.PUBLISHED,
            published_at=NOW,
        )
        == published
    )
    assert tuple(repository.members[published.publication_id]) == candidate.members


def test_candidate_preparation_does_not_read_current_and_keeps_eight_quote_suspensions() -> None:
    """A complete evidenced suspension partition stages without a current pointer read."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.quote.snapshot",
        fact_table="data_center_quote_snapshot",
        created_by="ops.current_publication_rebuild",
    )
    asset_codes = tuple(f"{index:06d}.SZ" for index in range(1, 11))
    suspended_codes = asset_codes[2:]
    references = [
        _reference(code, str(index), dataset=dataset)
        for index, code in enumerate(asset_codes[:2], start=1)
    ]

    class _NoCurrentReadRepository(_PublicationRepository):
        def get_current(
            self, dataset_key: str, publication_key: str
        ) -> CanonicalPublication | None:
            raise AssertionError("candidate preparation must not read the current pointer")

    use_case = _use_case(
        dataset,
        references,
        _NoCurrentReadRepository(),
        policy_repository=_PartialPolicyRepository(
            minimum_coverage_ratio=1.0,
            allow_partial=False,
        ),
    )
    exclusions = tuple(
        CurrentPublicationScopeExclusion(
            asset_code=code,
            reason_code="quote_full_day_suspension",
            target_trade_date=date(2026, 8, 28),
            evidence_source="tushare.suspend_d",
        )
        for code in suspended_codes
    )

    candidate = use_case.prepare_candidate(
        asset_codes=asset_codes,
        published_at=NOW,
        run_id="quote-stage-run",
        scope_exclusions=exclusions,
    )

    assert candidate.publication.state is PublicationState.CANDIDATE
    assert candidate.publication.coverage.requested_count == 10
    assert candidate.publication.coverage.eligible_count == 2
    assert candidate.publication.coverage.selected_count == 2
    assert candidate.publication.coverage.missing_count == 8
    assert (
        tuple(block.asset_code for block in candidate.publication.scope_blocks) == suspended_codes
    )


def test_candidate_preparation_uses_partial_valuation_policy_and_block_evidence() -> None:
    """A policy-valid partial valuation remains a candidate with explicit missing scope."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.valuation.fact",
        fact_table="data_center_valuation_fact",
        created_by="ops.current_publication_rebuild",
    )
    asset_codes = tuple(f"{index:06d}.SZ" for index in range(1, 11))
    use_case = _use_case(
        dataset,
        [
            _reference(code, str(index), dataset=dataset)
            for index, code in enumerate(asset_codes[:9])
        ],
        policy_repository=_PartialPolicyRepository(
            minimum_coverage_ratio=0.9,
            allow_partial=True,
        ),
    )

    candidate = use_case.prepare_candidate(
        asset_codes=asset_codes,
        published_at=NOW,
        run_id="valuation-stage-run",
    )

    assert candidate.publication.state is PublicationState.CANDIDATE
    assert candidate.publication.coverage.coverage_ratio == 0.9
    assert candidate.publication.coverage.missing_count == 1
    assert candidate.publication.scope_blocks[0].asset_code == asset_codes[-1]
    assert candidate.publication.scope_blocks[0].reason_code == "valuation_source_data_unavailable"


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


def test_rebuild_publishes_policy_allowed_partial_valuation_with_scope_block() -> None:
    dataset = CurrentPublicationDataset(
        dataset_key="equity.valuation.fact",
        fact_table="data_center_valuation_fact",
        created_by="ops.current_publication_rebuild",
    )
    codes = [f"{index:06d}.SZ" for index in range(100)]
    references = [
        _reference(code, str(index), dataset=dataset)
        for index, code in enumerate(codes[:-1], start=1)
    ]
    repository = _PublicationRepository()
    use_case = _use_case(
        dataset,
        references,
        repository,
        policy_repository=_PartialPolicyRepository(),
    )
    publication = use_case.execute(
        asset_codes=codes,
        published_at=NOW,
        run_id="partial-run-20260830",
    )
    replay = use_case.execute(
        asset_codes=codes,
        published_at=NOW + timedelta(seconds=1),
        run_id="partial-run-20260830",
    )

    assert publication.coverage.requested_count == 100
    assert publication.coverage.selected_count == 99
    assert publication.coverage.missing_count == 1
    assert publication.member_count == 99
    assert publication.scope_blocks[0].asset_code == codes[-1]
    assert publication.scope_blocks[0].reason_code == "valuation_source_data_unavailable"
    block = publication.scope_blocks[0]
    assert block.target_trade_date == NOW.date()
    assert block.source == publication.selected_source == "source-main"
    assert block.publication_run_id == publication.run_id == "partial-run-20260830"
    assert block.policy_version == publication.policy_version
    assert block.publication_id == publication.publication_id
    assert replay is publication
    assert repository.published == [publication]
    assert (
        publication_hash(
            references,
            policy_identity=publication.policy_version,
            scope_blocks=publication.scope_blocks,
        )
        == publication.publication_hash
    )
    assert publication.publication_id == current_publication_id_for_hash(
        publication.dataset_key,
        publication.publication_key,
        publication.publication_hash,
    )


def test_required_observation_date_excludes_stale_valuation_candidate() -> None:
    """A prior-session latest row remains a gap in the requested session."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.valuation.fact",
        fact_table="data_center_valuation_fact",
        created_by="ops.current_publication_rebuild",
    )
    codes = [f"{index:06d}.SZ" for index in range(100)]
    target_date = cn_market_date_from_observation(NOW - timedelta(hours=1))
    references = [
        _reference(code, str(index), dataset=dataset)
        for index, code in enumerate(codes[:-1], start=1)
    ]
    references.append(
        _reference(
            codes[-1],
            "stale",
            dataset=dataset,
            observed_at=NOW - timedelta(days=1),
            suffix=(target_date - timedelta(days=1)).isoformat(),
        )
    )
    repository = _PublicationRepository()
    use_case = _use_case(
        dataset,
        references,
        repository,
        policy_repository=_PartialPolicyRepository(),
    )

    preview = use_case.preview(
        asset_codes=codes,
        published_at=NOW,
        required_observation_date=target_date,
    )
    publication = use_case.execute(
        asset_codes=codes,
        published_at=NOW,
        run_id="target-date-run-20260830",
        required_observation_date=target_date,
    )

    assert preview.ready is False
    assert preview.covered_asset_count == 99
    assert preview.member_count == 99
    assert preview.missing_asset_codes == (codes[-1],)
    assert publication.coverage.requested_count == 100
    assert publication.coverage.selected_count == 99
    assert publication.member_count == 99
    assert publication.scope_blocks[0].asset_code == codes[-1]
    assert publication.scope_blocks[0].reason_code == "valuation_source_data_unavailable"
    assert publication.scope_blocks[0].target_trade_date == target_date
    assert all(
        member.fact_pk != "stale" for member in repository.members[publication.publication_id]
    )


def test_required_observation_date_fails_closed_below_valuation_policy_threshold() -> None:
    """A stale candidate cannot satisfy a policy that requires complete coverage."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.valuation.fact",
        fact_table="data_center_valuation_fact",
        created_by="ops.current_publication_rebuild",
    )
    repository = _PublicationRepository()
    use_case = _use_case(
        dataset,
        [
            _reference("000001.SZ", "current", dataset=dataset),
            _reference(
                "600000.SH",
                "stale",
                dataset=dataset,
                observed_at=NOW - timedelta(days=1),
                suffix=(NOW.date() - timedelta(days=1)).isoformat(),
            ),
        ],
        repository,
        policy_repository=_PartialPolicyRepository(minimum_coverage_ratio=1.0),
    )

    with pytest.raises(ValueError, match="missing active assets"):
        use_case.execute(
            asset_codes=["000001.SZ", "600000.SH"],
            published_at=NOW,
            run_id="blocked-target-date-run",
            required_observation_date=cn_market_date_from_observation(NOW - timedelta(hours=1)),
        )

    assert repository.published == []


def test_required_observation_date_rejects_valuation_identity_date_mismatch() -> None:
    """The valuation natural-key date and source observation date must agree."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.valuation.fact",
        fact_table="data_center_valuation_fact",
        created_by="ops.current_publication_rebuild",
    )
    use_case = _use_case(
        dataset,
        [
            _reference(
                "000001.SZ",
                "mismatched",
                dataset=dataset,
                observed_at=NOW - timedelta(days=1),
                suffix=NOW.date().isoformat(),
            )
        ],
    )

    with pytest.raises(ValueError, match="trade date differs from its observation date"):
        use_case.preview(
            asset_codes=["000001.SZ"],
            published_at=NOW,
            required_observation_date=NOW.date(),
        )


@pytest.mark.parametrize(
    ("minimum_coverage_ratio", "allow_partial"),
    [(1.0, True), (0.5, False)],
    ids=["below-policy-threshold", "partial-disabled"],
)
def test_rebuild_blocks_partial_valuation_when_policy_does_not_allow_it(
    minimum_coverage_ratio: float,
    allow_partial: bool,
) -> None:
    """Both threshold failure and explicit partial prohibition leave no publication."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.valuation.fact",
        fact_table="data_center_valuation_fact",
        created_by="ops.current_publication_rebuild",
    )
    codes = ["000001.SZ", "600000.SH"]
    repository = _PublicationRepository()
    use_case = _use_case(
        dataset,
        [_reference(codes[0], "1", dataset=dataset)],
        repository,
        policy_repository=_PartialPolicyRepository(
            minimum_coverage_ratio=minimum_coverage_ratio,
            allow_partial=allow_partial,
        ),
    )

    with pytest.raises(ValueError, match="missing active assets"):
        use_case.execute(
            asset_codes=codes,
            published_at=NOW,
            run_id="blocked-partial-run",
        )

    assert repository.published == []


def test_partial_policy_does_not_relax_quote_publication_scope() -> None:
    dataset = CurrentPublicationDataset(
        dataset_key="equity.quote.snapshot",
        fact_table="data_center_quote_snapshot",
        created_by="ops.current_publication_rebuild",
    )
    use_case = _use_case(
        dataset,
        [_reference("000001.SZ", "1", dataset=dataset)],
        policy_repository=_PartialPolicyRepository(),
    )

    with pytest.raises(ValueError, match="missing active assets"):
        use_case.execute(
            asset_codes=["000001.SZ", "600000.SH"],
            published_at=NOW,
        )


@pytest.mark.parametrize(
    "published_at",
    (
        datetime(2026, 8, 28, 7, 5, tzinfo=UTC),
        datetime(2026, 8, 28, 9, 5, tzinfo=UTC),
    ),
    ids=["15-05-china-time", "17-05-china-time"],
)
def test_rebuild_rejects_pre_close_quote_observations_after_publication_time(
    published_at: datetime,
) -> None:
    """A later publication clock cannot turn a 14:55 quote into a closing quote."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.quote.snapshot",
        fact_table="data_center_quote_snapshot",
        created_by="ops.current_publication_rebuild",
    )
    publications = _PublicationRepository()
    use_case = _use_case(
        dataset,
        [
            _reference(
                "000001.SZ",
                "pre-close",
                dataset=dataset,
                observed_at=datetime(2026, 8, 28, 6, 55, tzinfo=UTC),
            )
        ],
        publications,
    )

    with pytest.raises(ValueError, match="before the official China-market close"):
        use_case.preview(asset_codes=("000001.SZ",), published_at=published_at)
    with pytest.raises(ValueError, match="before the official China-market close"):
        use_case.execute(asset_codes=("000001.SZ",), published_at=published_at)

    assert publications.published == []


def test_rebuild_accepts_quote_observation_at_official_close_boundary() -> None:
    """An observation exactly at 15:00 China time is eligible for current rebuild."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.quote.snapshot",
        fact_table="data_center_quote_snapshot",
        created_by="ops.current_publication_rebuild",
    )
    close_at = datetime(2026, 8, 28, 7, 0, tzinfo=UTC)
    use_case = _use_case(
        dataset,
        [_reference("000001.SZ", "at-close", dataset=dataset, observed_at=close_at)],
    )

    publication = use_case.execute(
        asset_codes=("000001.SZ",),
        published_at=datetime(2026, 8, 28, 7, 5, tzinfo=UTC),
    )

    assert publication.as_of == close_at
    assert publication.coverage.selected_count == 1


def test_rebuild_publishes_verified_target_session_suspension_scope() -> None:
    """A strict policy may exclude only a fully evidenced target-day suspension."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.quote.snapshot",
        fact_table="data_center_quote_snapshot",
        created_by="ops.current_publication_rebuild",
    )
    codes = ["000001.SZ", "000016.SZ"]
    repository = _PublicationRepository()
    use_case = _use_case(
        dataset,
        [
            _reference(
                codes[0],
                "1",
                dataset=dataset,
                observed_at=datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
            )
        ],
        repository,
        policy_repository=_PartialPolicyRepository(
            minimum_coverage_ratio=1.0,
            allow_partial=False,
        ),
    )

    publication = use_case.execute(
        asset_codes=codes,
        published_at=NOW,
        run_id="suspension-run-20260828",
        scope_exclusions=(
            CurrentPublicationScopeExclusion(
                asset_code=codes[1],
                reason_code="quote_full_day_suspension",
                target_trade_date=date(2026, 8, 28),
                evidence_source="tushare.suspend_d",
            ),
        ),
    )

    assert publication.coverage.requested_count == 2
    assert publication.coverage.eligible_count == 1
    assert publication.coverage.selected_count == 1
    assert publication.coverage.missing_count == 1
    assert publication.member_count == 1
    assert publication.policy_version.startswith("p2:")
    assert publication.scope_blocks[0].to_dict() == {
        "asset_code": codes[1],
        "reason_code": "quote_full_day_suspension",
        "target_trade_date": "2026-08-28",
        "evidence_source": "tushare.suspend_d",
        "source": publication.selected_source,
        "publication_run_id": "suspension-run-20260828",
        "policy_version": publication.policy_version,
        "publication_id": publication.publication_id,
    }
    assert repository.published == [publication]


def test_preview_and_execute_exclude_stale_suspended_quote_candidate() -> None:
    """Preview and publish must select the same target-session eligible quote scope."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.quote.snapshot",
        fact_table="data_center_quote_snapshot",
        created_by="ops.current_publication_rebuild",
    )
    active_code = "000001.SZ"
    suspended_code = "000016.SZ"
    candidate_repository = _CandidateRepository(
        [
            _reference(
                active_code,
                "1",
                dataset=dataset,
                observed_at=datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
            ),
            _reference(
                suspended_code,
                "2",
                dataset=dataset,
                observed_at=datetime(2026, 8, 27, 7, 0, tzinfo=UTC),
            ),
        ]
    )
    publication_repository = _PublicationRepository()
    use_case = CurrentPublicationRebuildUseCase(
        dataset=dataset,
        candidate_repository=candidate_repository,
        publication_repository=publication_repository,
        policy_repository=_PartialPolicyRepository(
            minimum_coverage_ratio=1.0,
            allow_partial=False,
        ),
    )
    exclusions = (
        CurrentPublicationScopeExclusion(
            asset_code=suspended_code,
            reason_code="quote_full_day_suspension",
            target_trade_date=date(2026, 8, 28),
            evidence_source="tushare.suspend_d",
        ),
    )

    preview = use_case.preview(
        asset_codes=(active_code, suspended_code),
        published_at=NOW,
        scope_exclusions=exclusions,
    )
    publication = use_case.execute(
        asset_codes=(active_code, suspended_code),
        published_at=NOW,
        run_id="suspension-run-20260828",
        scope_exclusions=exclusions,
    )

    assert candidate_repository.calls == [(active_code,), (active_code,)]
    assert candidate_repository.date_probe_calls == [
        ((suspended_code,), date(2026, 8, 28)),
        ((suspended_code,), date(2026, 8, 28)),
    ]
    assert preview.requested_asset_count == 2
    assert preview.covered_asset_count == 1
    assert preview.missing_asset_codes == (suspended_code,)
    assert preview.oldest_observed_at == datetime(2026, 8, 28, 7, 0, tzinfo=UTC)
    assert preview.newest_observed_at == datetime(2026, 8, 28, 7, 0, tzinfo=UTC)
    assert publication.coverage.requested_count == 2
    assert publication.coverage.eligible_count == 1
    assert publication.coverage.missing_count == 1
    assert publication.member_count == 1
    assert publication.scope_blocks[0].asset_code == suspended_code


@pytest.mark.parametrize(
    "observed_at",
    (
        datetime(2026, 8, 28, 6, 55, tzinfo=UTC),
        datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
    ),
)
def test_suspension_exclusion_rejects_target_session_quote_observation(
    observed_at: datetime,
) -> None:
    """A target-day quote contradicts a claimed full-day suspension, even before close."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.quote.snapshot",
        fact_table="data_center_quote_snapshot",
        created_by="ops.current_publication_rebuild",
    )
    active_code = "000001.SZ"
    falsely_excluded_code = "000016.SZ"
    use_case = _use_case(
        dataset,
        [
            _reference(
                active_code,
                "1",
                dataset=dataset,
                observed_at=datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
            ),
            _reference(
                falsely_excluded_code,
                "2",
                dataset=dataset,
                observed_at=observed_at,
            ),
            _reference(
                falsely_excluded_code,
                "3",
                dataset=dataset,
                observed_at=datetime(2026, 8, 29, 7, 0, tzinfo=UTC),
            ),
        ],
        policy_repository=_PartialPolicyRepository(
            minimum_coverage_ratio=1.0,
            allow_partial=False,
        ),
    )
    exclusions = (
        CurrentPublicationScopeExclusion(
            asset_code=falsely_excluded_code,
            reason_code="quote_full_day_suspension",
            target_trade_date=date(2026, 8, 28),
            evidence_source="tushare.suspend_d",
        ),
    )

    with pytest.raises(ValueError, match="conflicts with a target-session quote"):
        use_case.preview(
            asset_codes=(active_code, falsely_excluded_code),
            published_at=NOW,
            scope_exclusions=exclusions,
        )
    with pytest.raises(ValueError, match="conflicts with a target-session quote"):
        use_case.execute(
            asset_codes=(active_code, falsely_excluded_code),
            published_at=NOW,
            run_id="suspension-run-20260828",
            scope_exclusions=exclusions,
        )


def test_suspension_exclusion_does_not_hide_an_eligible_quote_gap() -> None:
    """A real eligible gap remains blocking beside independently excluded suspensions."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.quote.snapshot",
        fact_table="data_center_quote_snapshot",
        created_by="ops.current_publication_rebuild",
    )
    active_code = "000001.SZ"
    missing_eligible_code = "000002.SZ"
    suspended_code = "000016.SZ"
    use_case = _use_case(
        dataset,
        [
            _reference(
                active_code,
                "1",
                dataset=dataset,
                observed_at=datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
            ),
            _reference(
                suspended_code,
                "2",
                dataset=dataset,
                observed_at=datetime(2026, 8, 27, 7, 0, tzinfo=UTC),
            ),
        ],
        policy_repository=_PartialPolicyRepository(
            minimum_coverage_ratio=1.0,
            allow_partial=False,
        ),
    )
    exclusions = (
        CurrentPublicationScopeExclusion(
            asset_code=suspended_code,
            reason_code="quote_full_day_suspension",
            target_trade_date=date(2026, 8, 28),
            evidence_source="tushare.suspend_d",
        ),
    )

    preview = use_case.preview(
        asset_codes=(active_code, missing_eligible_code, suspended_code),
        published_at=NOW,
        scope_exclusions=exclusions,
    )

    assert preview.covered_asset_count == 1
    assert preview.missing_asset_codes == (missing_eligible_code, suspended_code)
    with pytest.raises(ValueError, match="match publication gaps"):
        use_case.execute(
            asset_codes=(active_code, missing_eligible_code, suspended_code),
            published_at=NOW,
            run_id="suspension-run-20260828",
            scope_exclusions=exclusions,
        )


def test_suspension_exclusion_is_not_contradicted_by_next_session_quote() -> None:
    """A later-session quote does not disprove an evidenced prior-day suspension."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.quote.snapshot",
        fact_table="data_center_quote_snapshot",
        created_by="ops.current_publication_rebuild",
    )
    active_code = "000001.SZ"
    suspended_code = "000016.SZ"
    use_case = _use_case(
        dataset,
        [
            _reference(
                active_code,
                "1",
                dataset=dataset,
                observed_at=datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
            ),
            _reference(
                suspended_code,
                "2",
                dataset=dataset,
                observed_at=datetime(2026, 8, 29, 7, 0, tzinfo=UTC),
            ),
        ],
        policy_repository=_PartialPolicyRepository(
            minimum_coverage_ratio=1.0,
            allow_partial=False,
        ),
    )
    exclusions = (
        CurrentPublicationScopeExclusion(
            asset_code=suspended_code,
            reason_code="quote_full_day_suspension",
            target_trade_date=date(2026, 8, 28),
            evidence_source="tushare.suspend_d",
        ),
    )

    publication = use_case.execute(
        asset_codes=(active_code, suspended_code),
        published_at=NOW,
        run_id="suspension-run-20260828",
        scope_exclusions=exclusions,
    )

    assert publication.member_count == 1
    assert publication.scope_blocks[0].asset_code == suspended_code


@pytest.mark.parametrize(
    ("scope_exclusions", "message"),
    [
        ((), "missing active assets"),
        (
            (
                CurrentPublicationScopeExclusion(
                    asset_code="000002.SZ",
                    reason_code="quote_full_day_suspension",
                    target_trade_date=date(2026, 8, 30),
                    evidence_source="tushare.suspend_d",
                ),
            ),
            "match publication gaps",
        ),
        (
            (
                CurrentPublicationScopeExclusion(
                    asset_code="000016.SZ",
                    reason_code="provider_missing",
                    target_trade_date=date(2026, 8, 30),
                    evidence_source="tushare.suspend_d",
                ),
            ),
            "unsupported scope exclusion",
        ),
        (
            (
                CurrentPublicationScopeExclusion(
                    asset_code="000016.SZ",
                    reason_code="quote_full_day_suspension",
                    target_trade_date=date(2026, 8, 29),
                    evidence_source="tushare.suspend_d",
                ),
            ),
            "target trade date",
        ),
    ],
)
def test_rebuild_rejects_unverified_or_misaligned_market_scope_exclusion(
    scope_exclusions: tuple[CurrentPublicationScopeExclusion, ...],
    message: str,
) -> None:
    """Missing rows remain globally blocked without exact target-session evidence."""

    dataset = CurrentPublicationDataset(
        dataset_key="equity.quote.snapshot",
        fact_table="data_center_quote_snapshot",
        created_by="ops.current_publication_rebuild",
    )
    repository = _PublicationRepository()
    use_case = _use_case(
        dataset,
        [_reference("000001.SZ", "1", dataset=dataset)],
        repository,
        policy_repository=_PartialPolicyRepository(
            minimum_coverage_ratio=1.0,
            allow_partial=False,
        ),
    )

    with pytest.raises(ValueError, match=message):
        use_case.execute(
            asset_codes=["000001.SZ", "000016.SZ"],
            published_at=NOW,
            run_id="suspension-run-20260830",
            scope_exclusions=scope_exclusions,
        )

    assert repository.published == []


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
        authority_preflight=lambda as_of: transaction_entries.append(
            f"authority:{as_of.isoformat()}"
        ),
    )

    result = coordinator.execute(asset_codes=["000001.SZ"], published_at=NOW)

    assert transaction_entries == [f"authority:{NOW.isoformat()}", "enter", "exit"]
    assert result.published_count == 3
    assert set(result.publication_ids) == {item.publication_id for item in publications.published}
    assert all(item["covered_asset_count"] == 1 for item in result.to_dict()["datasets"])
    assert all(
        str(item["policy_identity"]).startswith("1.0:1.0") for item in result.to_dict()["datasets"]
    )


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
        authority_preflight=lambda as_of: (_ for _ in ()).throw(
            AssertionError("preview must not resolve write authority")
        ),
    )

    payload = coordinator.preview(asset_codes=["000001.SZ"], published_at=NOW)

    assert payload.ready is True
    assert payload.member_count == 1
    assert publications.published == []


def test_core_preview_rejects_unknown_exclusion_dataset() -> None:
    """Preview rejects exclusion mappings that execute could not consume."""

    dataset = CurrentPublicationDataset(
        "equity.quote.snapshot",
        "data_center_quote_snapshot",
        "ops.current_publication_rebuild",
    )
    coordinator = CoreCurrentPublicationRebuildUseCase(
        rebuilders=(
            _use_case(
                dataset,
                [_reference("000001.SZ", "1", dataset=dataset)],
            ),
        ),
        transaction=nullcontext,
        authority_preflight=lambda _as_of: None,
    )

    with pytest.raises(ValueError, match="unknown datasets"):
        coordinator.preview(
            asset_codes=["000001.SZ"],
            published_at=NOW,
            scope_exclusions_by_dataset={"equity.unknown": ()},
        )


def test_core_preview_applies_required_observation_date_per_dataset() -> None:
    """Session binding applies only to the explicitly mapped current datasets."""

    valuation = CurrentPublicationDataset(
        "equity.valuation.fact",
        "data_center_valuation_fact",
        "ops.current_publication_rebuild",
    )
    price_bar = CurrentPublicationDataset(
        "equity.price.bar",
        "data_center_price_bar",
        "ops.current_publication_rebuild",
    )
    stale_observation = NOW - timedelta(days=1)
    coordinator = CoreCurrentPublicationRebuildUseCase(
        rebuilders=(
            _use_case(
                valuation,
                [
                    _reference(
                        "000001.SZ",
                        "valuation-stale",
                        dataset=valuation,
                        observed_at=stale_observation,
                        suffix=cn_market_date_from_observation(stale_observation).isoformat(),
                    )
                ],
            ),
            _use_case(
                price_bar,
                [
                    _reference(
                        "000001.SZ",
                        "price-stale",
                        dataset=price_bar,
                        observed_at=stale_observation,
                    )
                ],
            ),
        ),
        transaction=nullcontext,
        authority_preflight=lambda _as_of: None,
    )

    result = coordinator.preview(
        asset_codes=["000001.SZ"],
        published_at=NOW,
        required_observation_dates={"equity.valuation.fact": cn_market_date_from_observation(NOW)},
    )
    by_dataset = {item.dataset_key: item for item in result.datasets}

    assert by_dataset["equity.valuation.fact"].covered_asset_count == 0
    assert by_dataset["equity.valuation.fact"].missing_asset_codes == ("000001.SZ",)
    assert by_dataset["equity.price.bar"].ready is True


def test_core_preview_rejects_unknown_required_observation_date_dataset() -> None:
    """An unknown session binding fails before any coordinated read."""

    dataset = CurrentPublicationDataset(
        "equity.valuation.fact",
        "data_center_valuation_fact",
        "ops.current_publication_rebuild",
    )
    coordinator = CoreCurrentPublicationRebuildUseCase(
        rebuilders=(
            _use_case(
                dataset,
                [_reference("000001.SZ", "1", dataset=dataset)],
            ),
        ),
        transaction=nullcontext,
        authority_preflight=lambda _as_of: None,
    )

    with pytest.raises(ValueError, match="required observation dates.*unknown datasets"):
        coordinator.preview(
            asset_codes=["000001.SZ"],
            published_at=NOW,
            required_observation_dates={"equity.unknown": NOW.date()},
        )


def test_core_rebuild_denied_authority_never_enters_transaction() -> None:
    dataset = CurrentPublicationDataset(
        "equity.price.bar",
        "data_center_price_bar",
        "ops.current_publication_rebuild",
    )
    transaction_entries: list[str] = []

    def deny_authority(as_of: datetime) -> None:
        assert as_of == NOW
        raise RuntimeError("current audit authority unavailable")

    coordinator = CoreCurrentPublicationRebuildUseCase(
        rebuilders=(
            _use_case(
                dataset,
                [_reference("000001.SZ", "1", dataset=dataset)],
            ),
        ),
        transaction=lambda: transaction_entries.append("enter") or nullcontext(),
        authority_preflight=deny_authority,
    )

    with pytest.raises(RuntimeError, match="authority unavailable"):
        coordinator.execute(asset_codes=["000001.SZ"], published_at=NOW)

    assert transaction_entries == []
