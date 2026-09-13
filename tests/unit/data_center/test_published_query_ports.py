"""Publication-only query port contracts for D7-D9."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.data_center.application import query_services
from apps.data_center.application.publication_utils import member_reference, publication_hash
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.entities import (
    CapitalFlowFact,
    NewsFact,
    SectorMembershipFact,
)

pytestmark = pytest.mark.django_db


_DEFAULT_OLDEST = object()
_RAISE_OLDEST = object()
_DATASET_FACT_TABLES: dict[str, str] = {
    "macro.fact": "data_center_macro_fact",
    "fund.nav": "data_center_fund_nav_fact",
    "equity.price.bar": "data_center_price_bar",
    "equity.quote.snapshot": "data_center_quote_snapshot",
    "equity.financial.fact": "data_center_financial_fact",
    "equity.valuation.fact": "data_center_valuation_fact",
    "sector.membership": "data_center_sector_membership",
    "market.news": "data_center_news_fact",
    "market.capital_flow": "data_center_capital_flow_fact",
}
_POLICY_CONFIG: dict[str, tuple[float, bool, str, tuple[str, ...], int]] = {
    "macro.fact": (
        1.0,
        False,
        "block",
        ("source", "observed_at", "published_at", "payload_hash"),
        3650,
    ),
    "fund.nav": (0.99, True, "block", ("source", "observed_at", "payload_hash"), 1825),
    "equity.price.bar": (0.99, True, "quarantine", ("source", "observed_at", "payload_hash"), 3650),
    "equity.quote.snapshot": (
        1.0,
        False,
        "block",
        ("source", "observed_at", "fetched_at", "payload_hash"),
        90,
    ),
    "equity.financial.fact": (
        1.0,
        True,
        "quarantine",
        ("source", "observed_at", "available_at", "payload_hash"),
        3650,
    ),
    "equity.valuation.fact": (
        0.99,
        True,
        "quarantine",
        ("source", "observed_at", "payload_hash"),
        3650,
    ),
    "sector.membership": (0.99, True, "block", ("source", "observed_at", "payload_hash"), 1825),
    "market.news": (0.95, True, "quarantine", ("source", "observed_at", "payload_hash"), 730),
    "market.capital_flow": (0.99, True, "block", ("source", "observed_at", "payload_hash"), 730),
}


class _PublicationPolicyRepository:
    """Return the reviewed legacy policy for each mocked dataset scope."""

    def get_active(self, dataset_key: str) -> PublicationPolicy:
        """Return a typed policy whose identity matches the test publication."""

        minimum, allow_partial, conflict_action, evidence, retention = _POLICY_CONFIG[dataset_key]
        return PublicationPolicy(
            dataset=DatasetKey(dataset_key, "1.0", "1.0"),
            minimum_coverage_ratio=minimum,
            allow_partial=allow_partial,
            conflict_action=conflict_action,
            required_evidence=evidence,
            retention_days=retention,
        )


class _DatasetContractRepository:
    """Provide a long enough freshness window for the synthetic publication."""

    def get_active(self, _dataset_key: str) -> SimpleNamespace:
        """Return the minimal contract field consumed by the current gate."""

        return SimpleNamespace(freshness_seconds=3650 * 86_400)


def _member(
    *,
    publication_id: str,
    dataset_key: str,
    fact_pk: str = "1",
    observed_at: datetime = datetime(2026, 8, 1, 12, tzinfo=UTC),
) -> PublicationMember:
    """Build a complete typed member for the current-publication gate."""

    return PublicationMember(
        member_id=f"member-{publication_id}-{fact_pk}",
        publication_id=publication_id,
        dataset_key=dataset_key,
        natural_key=f"test:{dataset_key}:{fact_pk}",
        source="test",
        source_record_id=f"record-{publication_id}-{fact_pk}",
        fact_table=_DATASET_FACT_TABLES[dataset_key],
        fact_pk=fact_pk,
        observed_at=observed_at,
        raw_payload_hash="a" * 64,
        quality_status="accepted",
        revision_number=1,
        available_at=observed_at,
        fetched_at=observed_at,
        source_published_at=observed_at,
        fact_content_hash="b" * 64,
    )


def _publication(
    *,
    dataset_key: str = "equity.financial.fact",
    publication_id: str = "pub-2026-08-02",
    publication_key: str = "current",
    as_of: datetime = datetime(2026, 8, 1, 12, tzinfo=UTC),
    published_at: datetime = datetime(2026, 8, 2, tzinfo=UTC),
    fact_pk: str = "1",
) -> CanonicalPublication:
    """Build a complete typed publication and matching immutable member."""

    policy = _PublicationPolicyRepository().get_active(dataset_key)
    member = _member(
        publication_id=publication_id,
        dataset_key=dataset_key,
        fact_pk=fact_pk,
        observed_at=as_of,
    )
    return CanonicalPublication(
        publication_id=publication_id,
        dataset_key=dataset_key,
        publication_key=publication_key,
        policy_version=policy.identity,
        state=PublicationState.PUBLISHED,
        selected_source="test",
        publication_hash=publication_hash((member_reference(member),)),
        coverage=CoverageSnapshot(
            coverage_id=publication_id,
            publication_id=publication_id,
            requested_count=1,
            eligible_count=1,
            selected_count=1,
            generated_at=published_at,
        ),
        member_count=1,
        conflict_count=0,
        as_of=as_of,
        published_at=published_at,
        created_by="test",
    )


class _PublicationRepository:
    """Provide typed publication, member and independent fact-hash snapshots."""

    def __init__(
        self,
        *,
        missing: set[str] | None = None,
        oldest_observed_at: object = _DEFAULT_OLDEST,
        fixed_publication: CanonicalPublication | None = None,
        fixed_fact_pk: str = "1",
        fact_pks: dict[str, str] | None = None,
        publication_id: str = "pub-2026-08-02",
        missing_members: bool = False,
    ) -> None:
        self.missing = missing or set()
        self.oldest_observed_at = oldest_observed_at
        self.fixed_publication = fixed_publication
        self.fixed_fact_pk = fixed_fact_pk
        self.fact_pks = fact_pks or {}
        self.publication_id = publication_id
        self.missing_members = missing_members
        self._members: dict[str, tuple[PublicationMember, ...]] = {}
        self._fact_hashes: dict[tuple[str, str], str] = {}

    def get_current(self, dataset_key: str, publication_key: str) -> CanonicalPublication | None:
        """Return and register one typed publication for the requested scope."""

        if publication_key in self.missing:
            return None
        publication = self.fixed_publication or _publication(
            dataset_key=dataset_key,
            publication_id=self.publication_id,
            publication_key=publication_key,
            fact_pk=self.fact_pks.get(dataset_key, self.fixed_fact_pk),
        )
        fact_pk = self.fact_pks.get(publication.dataset_key, self.fixed_fact_pk)
        member = _member(
            publication_id=publication.publication_id,
            dataset_key=publication.dataset_key,
            fact_pk=fact_pk,
            observed_at=publication.as_of or publication.published_at or datetime.now(UTC),
        )
        members = () if self.missing_members else (member,)
        self._members[publication.publication_id] = members
        for selected in members:
            self._fact_hashes[(selected.fact_table, selected.fact_pk)] = selected.fact_content_hash
        return publication

    def list_members(self, publication_id: str) -> list[PublicationMember]:
        """Return the member rows captured for the current publication."""

        return list(self._members.get(publication_id, ()))

    def get_fact_content_hashes(
        self, members: tuple[PublicationMember, ...]
    ) -> dict[tuple[str, str], str]:
        """Return a separately stored row-content hash for each selected member."""

        return {
            (member.fact_table, member.fact_pk): self._fact_hashes[
                (member.fact_table, member.fact_pk)
            ]
            for member in members
        }

    def get_oldest_member_observed_at(self, publication_id: str) -> datetime | None:
        """Return the configured freshness probe for the selected publication."""

        if self.oldest_observed_at is _RAISE_OLDEST:
            raise AssertionError("member lookup must not run when contract is missing")
        if self.oldest_observed_at is not _DEFAULT_OLDEST:
            if isinstance(self.oldest_observed_at, datetime):
                return self.oldest_observed_at
            return None
        members = self._members.get(publication_id, ())
        return min(
            (member.observed_at for member in members if member.observed_at is not None),
            default=None,
        )


@pytest.fixture(autouse=True)
def _governed_query_dependencies(monkeypatch) -> None:
    """Supply the typed policy and contract used by every current-read gate."""

    monkeypatch.setattr(
        query_services,
        "get_publication_policy_repository",
        lambda: _PublicationPolicyRepository(),
    )
    monkeypatch.setattr(
        query_services,
        "get_dataset_contract_repository",
        lambda: _DatasetContractRepository(),
    )


def test_latest_published_macro_values_are_catalog_bounded_and_fail_closed(monkeypatch) -> None:
    """Current macro summaries must discard unpublished or empty indicators."""

    monkeypatch.setattr(
        query_services,
        "get_indicator_catalog_repository",
        lambda: SimpleNamespace(
            list_active=lambda: [
                SimpleNamespace(code="CN_CPI"),
                SimpleNamespace(code="CN_PMI"),
            ]
        ),
    )

    def _published(code: str, *, limit: int) -> dict[str, object]:
        assert limit == 1
        if code == "CN_CPI":
            return {
                "rows": [
                    {
                        "indicator_code": code,
                        "value": 1.2,
                        "reporting_period": "2026-07-31",
                    }
                ],
                "publication_id": "pub-cpi",
                "freshness_status": "fresh",
                "must_not_use_for_decision": False,
            }
        return {
            "rows": [],
            "publication_id": "pub-pmi",
            "freshness_status": "stale",
            "must_not_use_for_decision": True,
        }

    monkeypatch.setattr(query_services, "query_published_macro_fact_series", _published)

    result = query_services.list_latest_published_macro_indicator_payloads(limit=10)

    assert result == [
        {
            "indicator_code": "CN_CPI",
            "value": 1.2,
            "reporting_period": "2026-07-31",
            "publication_id": "pub-cpi",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
        }
    ]


def test_latest_macro_indicator_value_cannot_bypass_publication_gate(monkeypatch) -> None:
    """The compatibility scalar port must not read an unpublished fact directly."""

    monkeypatch.setattr(
        query_services,
        "query_published_macro_fact_series",
        lambda *_args, **_kwargs: {
            "rows": [{"value": 51.2}],
            "must_not_use_for_decision": True,
        },
    )
    monkeypatch.setattr(
        query_services,
        "get_macro_fact_repository",
        lambda: (_ for _ in ()).throw(AssertionError("raw macro repository must not be read")),
    )

    assert query_services.get_latest_macro_indicator_value("CN_PMI") is None


def test_published_sector_memberships_fail_closed_without_publication(monkeypatch) -> None:
    """Canonical rows must not leak when the current sector publication is absent."""

    publication_repo = SimpleNamespace(get_current=lambda *_args: None)
    repository = SimpleNamespace(
        get_members=lambda *_args: [
            SectorMembershipFact(
                asset_code="600000.SH",
                sector_code="SW1_BANK",
                sector_name="银行",
                effective_date=date(2026, 1, 1),
                expiry_date=None,
                source="test",
            )
        ]
    )
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(query_services, "get_sector_membership_repository", lambda: repository)

    result = query_services.query_published_sector_memberships("SW1_BANK")

    assert result["rows"] == []
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "canonical_publication_missing"


def test_published_news_and_capital_flow_preserve_publication_evidence(monkeypatch) -> None:
    """D8/D9 ports return canonical rows together with the selected publication."""

    publication_repo = _PublicationRepository()
    news = NewsFact(
        asset_code="",
        title="Market",
        summary="Summary",
        url="https://example.test/news",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        source="test",
        external_id="news-1",
    )
    flow = CapitalFlowFact(
        asset_code="600000.SH",
        flow_date=date(2026, 8, 1),
        main_net=1.0,
        source="test",
    )
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(
        query_services,
        "get_news_repository",
        lambda: SimpleNamespace(list_market_news_for_date=lambda *_args, **_kwargs: [news]),
    )
    monkeypatch.setattr(
        query_services,
        "get_capital_flow_repository",
        lambda: SimpleNamespace(get_series=lambda *_args, **_kwargs: [flow]),
    )

    news_result = query_services.query_published_market_news(target_date=date(2026, 8, 1))
    flow_result = query_services.query_published_capital_flow_series("600000.SH", limit=20)

    assert len(news_result["rows"]) == 1
    assert len(flow_result["rows"]) == 1
    assert news_result["publication_id"] == "pub-2026-08-02"
    assert flow_result["must_not_use_for_decision"] is False


def test_published_capital_flow_blocks_before_querying_repository(monkeypatch) -> None:
    """A blocked D9 read must not spend a query on the canonical fact table."""

    publication_repo = SimpleNamespace(get_current=lambda *_args: None)
    repository = SimpleNamespace(
        get_series=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError)
    )
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(query_services, "get_capital_flow_repository", lambda: repository)

    result = query_services.query_published_capital_flow_series("600000.SH")

    assert result["rows"] == []
    assert result["blocked_reason"] == "canonical_publication_missing"


def test_published_financial_and_valuation_facts_preserve_gate_evidence(monkeypatch) -> None:
    """D4/D5 public ports return rows only after their own publications exist."""

    publication_repo = _PublicationRepository()
    financial = SimpleNamespace(to_dict=lambda: {"metric_code": "revenue", "value": 10.0})
    valuation = SimpleNamespace(to_dict=lambda: {"pe_ttm": 12.0})
    monkeypatch.setattr(
        query_services,
        "get_canonical_publication_repository",
        lambda: publication_repo,
    )
    monkeypatch.setattr(
        query_services,
        "get_financial_fact_repository",
        lambda: SimpleNamespace(get_facts=lambda *_args, **_kwargs: [financial]),
    )
    monkeypatch.setattr(
        query_services,
        "get_valuation_fact_repository",
        lambda: SimpleNamespace(get_series=lambda *_args, **_kwargs: [valuation]),
    )

    financial_result = query_services.query_published_financial_facts("600000.SH")
    valuation_result = query_services.query_published_valuation_facts("600000.SH")

    assert financial_result["rows"] == [{"metric_code": "revenue", "value": 10.0}]
    assert valuation_result["rows"] == [{"pe_ttm": 12.0}]
    assert financial_result["publication_id"] == "pub-2026-08-02"
    assert valuation_result["must_not_use_for_decision"] is False


def test_published_macro_facts_block_old_member_observation(monkeypatch) -> None:
    """Macro publication metadata cannot wash an old source observation into current reads."""

    publication_repo = _PublicationRepository(
        oldest_observed_at=datetime(2025, 7, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(
        query_services,
        "get_canonical_publication_repository",
        lambda: publication_repo,
    )
    monkeypatch.setattr(
        query_services,
        "get_dataset_contract_repository",
        lambda: SimpleNamespace(
            get_active=lambda *_args: SimpleNamespace(freshness_seconds=86_400)
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_macro_fact_repository",
        lambda: (_ for _ in ()).throw(AssertionError("stale macro facts must not be read")),
    )

    result = query_services.query_published_macro_fact_series("CN_PMI")

    assert result["rows"] == []
    assert result["publication_id"] == "pub-2026-08-02"
    assert result["freshness_status"] == "stale"
    assert result["blocked_reason"] == "canonical_publication_stale"


def test_published_macro_facts_use_only_publication_members(monkeypatch) -> None:
    """A current macro read must pass selected fact primary keys to the repository."""

    publication = _publication(
        dataset_key="macro.fact",
        publication_id="pub-macro-members",
        publication_key="CN_PMI",
        fact_pk="41",
    )
    publication_repo = _PublicationRepository(
        fixed_publication=publication,
        fixed_fact_pk="41",
    )
    seen: dict[str, object] = {}
    macro_repo = SimpleNamespace(
        get_series=lambda *_args, **kwargs: (
            seen.update(kwargs),
            [SimpleNamespace(to_dict=lambda: {"reporting_period": "2026-08-01"})],
        )[1]
    )
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(query_services, "get_macro_fact_repository", lambda: macro_repo)

    result = query_services.query_published_macro_fact_series("CN_PMI")

    assert result["rows"] == [{"reporting_period": "2026-08-01"}]
    assert seen["fact_pks"] == ["41"]


def test_published_fund_nav_uses_only_publication_members(monkeypatch) -> None:
    """The fund NAV publication port must not query unselected canonical rows."""

    publication = _publication(
        dataset_key="fund.nav",
        publication_id="pub-fund-members",
        fact_pk="73",
    )
    publication_repo = _PublicationRepository(
        fixed_publication=publication,
        fixed_fact_pk="73",
    )
    seen: dict[str, object] = {}
    fund_repo = SimpleNamespace(
        get_series=lambda *_args, **kwargs: (
            seen.update(kwargs),
            [SimpleNamespace(to_dict=lambda: {"nav_date": "2026-08-01"})],
        )[1]
    )
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(query_services, "get_fund_nav_repository", lambda: fund_repo)

    result = query_services.query_published_fund_nav_series("110011.OF")

    assert result["rows"] == [{"nav_date": "2026-08-01"}]
    assert seen["fact_pks"] == ["73"]


def test_published_financial_facts_fail_closed_before_repository_query(monkeypatch) -> None:
    """Missing D4 publication blocks before a financial repository call."""

    monkeypatch.setattr(
        query_services,
        "get_canonical_publication_repository",
        lambda: SimpleNamespace(get_current=lambda *_args: None),
    )
    monkeypatch.setattr(
        query_services,
        "get_financial_fact_repository",
        lambda: (_ for _ in ()).throw(AssertionError("financial repository must not be read")),
    )

    result = query_services.query_published_financial_facts("600000.SH")

    assert result["rows"] == []
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "canonical_publication_missing"


def test_published_gate_blocks_old_member_observation_even_when_publication_is_new(
    monkeypatch,
) -> None:
    """A newly-created publication cannot wash an old source observation into current data."""

    publication_repo = _PublicationRepository(
        publication_id="pub-new",
        oldest_observed_at=datetime(2025, 7, 1, tzinfo=UTC),
    )
    contract_repo = SimpleNamespace(
        get_active=lambda *_args: SimpleNamespace(freshness_seconds=86_400),
    )
    monkeypatch.setattr(
        query_services,
        "get_canonical_publication_repository",
        lambda: publication_repo,
    )
    monkeypatch.setattr(query_services, "get_dataset_contract_repository", lambda: contract_repo)
    monkeypatch.setattr(
        query_services,
        "get_financial_fact_repository",
        lambda: (_ for _ in ()).throw(AssertionError("stale facts must not be read")),
    )

    result = query_services.query_published_financial_facts("600000.SH")

    assert result["rows"] == []
    assert result["publication_id"] == "pub-new"
    assert result["freshness_status"] == "stale"
    assert result["blocked_reason"] == "canonical_publication_stale"


def test_published_gate_blocks_old_publication_as_of_even_when_member_was_reindexed(
    monkeypatch,
) -> None:
    """A refreshed member index must not hide an old publication knowledge boundary."""

    publication = _publication(
        publication_id="pub-reindexed",
        as_of=datetime(2025, 7, 1, tzinfo=UTC),
    )
    publication_repo = _PublicationRepository(
        fixed_publication=publication,
        oldest_observed_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(
        query_services,
        "get_dataset_contract_repository",
        lambda: SimpleNamespace(
            get_active=lambda *_args: SimpleNamespace(freshness_seconds=86_400)
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_financial_fact_repository",
        lambda: (_ for _ in ()).throw(AssertionError("old publication must not be read")),
    )

    result = query_services.query_published_financial_facts("600000.SH")

    assert result["rows"] == []
    assert result["publication_id"] == "pub-reindexed"
    assert result["freshness_status"] == "stale"
    assert result["blocked_reason"] == "canonical_publication_stale"


def test_published_gate_blocks_when_member_freshness_policy_is_missing(monkeypatch) -> None:
    """A real publication repository must not bypass an absent freshness contract."""

    publication_repo = _PublicationRepository(
        oldest_observed_at=_RAISE_OLDEST,
    )
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(
        query_services,
        "get_dataset_contract_repository",
        lambda: SimpleNamespace(get_active=lambda *_args: None),
    )

    result = query_services.query_published_financial_facts("600000.SH")

    assert result["rows"] == []
    assert result["freshness_status"] == "unverified"
    assert result["blocked_reason"] == "publication_freshness_policy_missing"


def test_published_gate_blocks_missing_member_observation(monkeypatch) -> None:
    """A publication with no source observation cannot be treated as current."""

    publication_repo = _PublicationRepository(oldest_observed_at=None)
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(
        query_services,
        "get_dataset_contract_repository",
        lambda: SimpleNamespace(
            get_active=lambda *_args: SimpleNamespace(freshness_seconds=86_400)
        ),
    )

    result = query_services.query_published_financial_facts("600000.SH")

    assert result["rows"] == []
    assert result["freshness_status"] == "missing"
    assert result["blocked_reason"] == "publication_observation_missing"


def test_published_gate_blocks_naive_member_observation(monkeypatch) -> None:
    """A naive source timestamp must not enter a timezone-aware decision read."""

    publication_repo = _PublicationRepository(oldest_observed_at=datetime(2025, 7, 1))
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publication_repo
    )
    monkeypatch.setattr(
        query_services,
        "get_dataset_contract_repository",
        lambda: SimpleNamespace(
            get_active=lambda *_args: SimpleNamespace(freshness_seconds=86_400)
        ),
    )

    result = query_services.query_published_financial_facts("600000.SH")

    assert result["rows"] == []
    assert result["freshness_status"] == "invalid"
    assert result["blocked_reason"] == "publication_observation_naive"


def test_published_rows_are_bounded_by_publication_as_of(monkeypatch) -> None:
    """A current publication must not expose facts observed after its knowledge boundary."""

    publication_repo = _PublicationRepository(publication_id="pub-as-of")
    monkeypatch.setattr(
        query_services,
        "get_canonical_publication_repository",
        lambda: publication_repo,
    )

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        query_services,
        "get_price_bar_repository",
        lambda: SimpleNamespace(
            get_bars=lambda asset_code, start=None, end=None, limit=500, **kwargs: captured.update(
                price_end=end
            )
            or []
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_financial_fact_repository",
        lambda: SimpleNamespace(
            get_facts=lambda asset_code, period_type=None, limit=20, end=None, **kwargs: captured.update(
                financial_end=end
            )
            or []
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_valuation_fact_repository",
        lambda: SimpleNamespace(
            get_series=lambda asset_code, start=None, end=None, **kwargs: captured.update(
                valuation_end=end
            )
            or []
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_capital_flow_repository",
        lambda: SimpleNamespace(
            get_series=lambda asset_code, start=None, end=None, limit=None, **kwargs: captured.update(
                capital_flow_end=end
            )
            or []
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_news_repository",
        lambda: SimpleNamespace(
            get_recent=lambda asset_code=None, limit=50, end=None, **kwargs: captured.update(
                news_end=end
            )
            or []
        ),
    )

    query_services.query_published_price_bar_series("600000.SH")
    query_services.query_published_financial_facts("600000.SH")
    query_services.query_published_valuation_facts("600000.SH")
    query_services.query_published_capital_flow_series("600000.SH")
    query_services.query_published_market_news(asset_code="600000.SH")

    expected_end = date(2026, 8, 1)
    assert captured == {
        "price_end": expected_end,
        "financial_end": expected_end,
        "valuation_end": expected_end,
        "capital_flow_end": expected_end,
        "news_end": expected_end,
    }


def test_publication_as_of_date_uses_china_market_calendar_across_utc_midnight() -> None:
    """UTC evening must not truncate the following China-market fact date."""

    assert query_services._publication_as_of_date(
        {"as_of": datetime(2026, 8, 8, 16, 30, tzinfo=UTC).isoformat()}
    ) == date(2026, 8, 9)


def test_published_quotes_reject_snapshots_after_publication_as_of(monkeypatch) -> None:
    """A quote newer than the selected publication cannot leak into its current read."""

    publication_repo = _PublicationRepository(
        fixed_publication=_publication(
            dataset_key="equity.quote.snapshot",
            publication_id="pub-quote-as-of",
            as_of=datetime(2026, 8, 1, 12, tzinfo=UTC),
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_canonical_publication_repository",
        lambda: publication_repo,
    )
    monkeypatch.setattr(
        query_services,
        "get_quote_snapshot_repository",
        lambda: SimpleNamespace(
            get_latest=lambda _asset_code, **_kwargs: SimpleNamespace(
                snapshot_at=datetime(2026, 8, 2, tzinfo=UTC),
                to_dict=lambda: {"snapshot_at": "2026-08-02T00:00:00+00:00"},
            )
        ),
    )

    result = query_services.query_published_quote_payloads(["600000.SH"])

    assert result["rows"] == []
    assert result["as_of"] == "2026-08-01T12:00:00+00:00"


def test_published_core_queries_are_bound_to_publication_member_fact_pks(monkeypatch) -> None:
    """Published core reads must query only fact rows selected by that publication."""

    tables = {
        "equity.price.bar": "data_center_price_bar",
        "equity.quote.snapshot": "data_center_quote_snapshot",
        "equity.financial.fact": "data_center_financial_fact",
        "equity.valuation.fact": "data_center_valuation_fact",
    }
    member_pks = {dataset_key: f"{index + 1}" for index, dataset_key in enumerate(tables)}

    publication_repo = _PublicationRepository(
        fact_pks=member_pks,
    )

    monkeypatch.setattr(
        query_services,
        "get_canonical_publication_repository",
        lambda: publication_repo,
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        query_services,
        "get_price_bar_repository",
        lambda: SimpleNamespace(
            get_bars=lambda *args, **kwargs: captured.update(price_pks=kwargs["fact_pks"]) or []
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_quote_snapshot_repository",
        lambda: SimpleNamespace(
            get_latest=lambda *args, **kwargs: captured.update(quote_pks=kwargs["fact_pks"])
            or None,
            get_series=lambda *args, **kwargs: captured.update(quote_series_pks=kwargs["fact_pks"])
            or [],
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_financial_fact_repository",
        lambda: SimpleNamespace(
            get_facts=lambda *args, **kwargs: captured.update(financial_pks=kwargs["fact_pks"])
            or []
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_valuation_fact_repository",
        lambda: SimpleNamespace(
            get_series=lambda *args, **kwargs: captured.update(valuation_pks=kwargs["fact_pks"])
            or []
        ),
    )

    query_services.query_published_price_bar_series("600000.SH")
    query_services.query_published_quote_payloads(["600000.SH"])
    query_services.query_published_quote_series("600000.SH")
    query_services.query_published_financial_facts("600000.SH")
    query_services.query_published_valuation_facts("600000.SH")

    assert captured == {
        "price_pks": [member_pks["equity.price.bar"]],
        "quote_pks": [member_pks["equity.quote.snapshot"]],
        "quote_series_pks": [member_pks["equity.quote.snapshot"]],
        "financial_pks": [member_pks["equity.financial.fact"]],
        "valuation_pks": [member_pks["equity.valuation.fact"]],
    }


def test_published_query_blocks_when_publication_members_are_missing(monkeypatch) -> None:
    """A current publication without selected members must never fall back to full tables."""

    publication_repo = _PublicationRepository(
        publication_id="pub-empty",
        missing_members=True,
    )

    monkeypatch.setattr(
        query_services,
        "get_canonical_publication_repository",
        lambda: publication_repo,
    )
    monkeypatch.setattr(
        query_services,
        "get_financial_fact_repository",
        lambda: (_ for _ in ()).throw(
            AssertionError("memberless publication must not query facts")
        ),
    )

    result = query_services.query_published_financial_facts("600000.SH")

    assert result["rows"] == []
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "publication_member_snapshot_invalid"


def test_published_d7_d9_queries_are_bound_to_publication_member_fact_pks(monkeypatch) -> None:
    """Sector, news, and capital-flow current reads must share publication members."""

    tables = {
        "sector.membership": "data_center_sector_membership",
        "market.news": "data_center_news_fact",
        "market.capital_flow": "data_center_capital_flow_fact",
    }

    member_pks = {dataset_key: f"{dataset_key}-1" for dataset_key in tables}
    publication_repo = _PublicationRepository(fact_pks=member_pks)

    monkeypatch.setattr(
        query_services,
        "get_canonical_publication_repository",
        lambda: publication_repo,
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        query_services,
        "get_sector_membership_repository",
        lambda: SimpleNamespace(
            get_members=lambda *args, **kwargs: captured.update(sector_pks=kwargs["fact_pks"]) or []
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_news_repository",
        lambda: SimpleNamespace(
            get_recent=lambda *args, **kwargs: captured.update(news_pks=kwargs["fact_pks"]) or [],
            list_market_news_for_date=lambda *args, **kwargs: captured.update(
                market_news_pks=kwargs["fact_pks"]
            )
            or [],
        ),
    )
    monkeypatch.setattr(
        query_services,
        "get_capital_flow_repository",
        lambda: SimpleNamespace(
            get_series=lambda *args, **kwargs: captured.update(flow_pks=kwargs["fact_pks"]) or []
        ),
    )

    query_services.query_published_sector_memberships("SW1_BANK")
    query_services.query_published_market_news(asset_code="600000.SH")
    query_services.query_published_market_news(target_date=date(2026, 8, 1))
    query_services.query_published_capital_flow_series("600000.SH")

    assert captured == {
        "sector_pks": ["sector.membership-1"],
        "news_pks": ["market.news-1"],
        "market_news_pks": ["market.news-1"],
        "flow_pks": ["market.capital_flow-1"],
    }
