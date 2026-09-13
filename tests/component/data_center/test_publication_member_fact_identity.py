"""Component coverage for canonical fact identity and immutable member binding."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.data_center.application.publication_utils import publication_member_from_reference
from apps.data_center.domain.control_plane import PublicationMember
from apps.data_center.domain.entities import ValuationFact
from apps.data_center.infrastructure.models import (
    CapitalFlowFactModel,
    FinancialFactModel,
    FundNavFactModel,
    MacroFactModel,
    NewsFactModel,
    PriceBarModel,
    QuoteSnapshotModel,
    SectorMembershipFactModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.publication_fact_evidence import (
    publication_fact_reference_for_dataset,
)
from apps.data_center.infrastructure.publication_fact_identity import (
    PublicationFactIdentity,
    build_publication_fact_identity,
)
from apps.data_center.infrastructure.publication_member_store import (
    publication_fact_content_hashes,
)
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository

pytestmark = pytest.mark.django_db


def _persist_valuation_member() -> PublicationMember:
    """Persist a real ORM row whose raw and source record fields are blank."""

    observed = datetime(2026, 9, 11, 7, tzinfo=UTC)
    available = observed + timedelta(minutes=5)
    fact = ValuationFact(
        asset_code="000001.SZ",
        val_date=observed.date(),
        pe_ttm=12.5,
        source="valuation",
        observed_at=observed,
        available_at=available,
        fetched_at=available,
        source_record_id="",
        raw_payload_hash="",
        extra={},
    )
    repository = ValuationFactRepository()
    assert repository.bulk_upsert([fact]) == 1
    references = repository.list_publication_candidates([fact])
    assert len(references) == 1
    reference = references[0]
    return publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=str(uuid4()),
        dataset_key="equity.valuation.fact",
    )


def test_valid_member_with_empty_scope_binds_fallback_identity_and_row_hash() -> None:
    """Blank scope still carries the producer's effective fallback values."""

    member = _persist_valuation_member()
    assert member.raw_payload_scope == ""
    assert member.source_record_id == member.natural_key
    assert member.raw_payload_hash
    assert publication_fact_content_hashes((member,)) == {
        (member.fact_table, member.fact_pk): member.fact_content_hash
    }


@pytest.mark.parametrize(
    ("field", "changed"),
    (
        ("natural_key", "forged:natural:key"),
        ("observed_at", datetime(2026, 9, 11, 7, 1, tzinfo=UTC)),
        ("quality_status", "rejected"),
        ("revision_number", 2),
        ("source_record_id", "forged-record"),
        ("raw_payload_hash", "f" * 64),
    ),
)
def test_real_row_hash_cannot_authorize_forged_frozen_identity(
    field: str,
    changed: object,
) -> None:
    """A real normalized row SHA does not bless invented member metadata."""

    member = _persist_valuation_member()
    forged = replace(member, **{field: changed})
    assert publication_fact_content_hashes((forged,)) == {}


def test_canonical_positive_primary_key_is_accepted() -> None:
    """A canonical positive decimal primary key resolves the persisted row."""

    member = _persist_valuation_member()
    assert member.fact_pk.isascii()
    assert member.fact_pk == str(int(member.fact_pk))
    assert publication_fact_content_hashes((replace(member, fact_pk=member.fact_pk),))


def test_rejected_valuation_quality_cannot_be_laundered_as_accepted() -> None:
    """A real row SHA cannot authorize changing rejected quality to accepted."""

    observed = datetime(2026, 9, 11, 7, tzinfo=UTC)
    row = ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=observed.date(),
        pe_ttm=Decimal("12.5"),
        source="valuation",
        observed_at=observed,
        fetched_at=observed + timedelta(minutes=5),
        available_at=observed + timedelta(minutes=1),
        quality_status="rejected",
        source_record_id="",
        raw_payload_hash="",
        extra={},
    )
    row.refresh_from_db()
    reference = publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.valuation.fact",
    )
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=str(uuid4()),
        dataset_key="equity.valuation.fact",
    )
    assert member.quality_status == "rejected"
    assert publication_fact_content_hashes((member,))[(member.fact_table, member.fact_pk)] == (
        member.fact_content_hash
    )
    forged = replace(member, quality_status="accepted")
    assert publication_fact_content_hashes((forged,)) == {}


def test_macro_zero_based_row_revision_is_frozen_as_one() -> None:
    """Macro row revision zero maps to reference revision one and cannot be forged."""

    row = MacroFactModel.objects.create(
        indicator_code="CN_GDP",
        reporting_period=date(2026, 6, 30),
        value=Decimal("123.456789"),
        unit="CNY",
        source="macro",
        revision_number=0,
        published_at=date(2026, 8, 15),
        quality="valid",
        source_record_id="",
        raw_payload_hash="",
        extra={},
    )
    reference = publication_fact_reference_for_dataset(row, dataset_key="macro.fact")
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=str(uuid4()),
        dataset_key="macro.fact",
    )
    assert member.revision_number == 1
    assert publication_fact_content_hashes((member,))[(member.fact_table, member.fact_pk)] == (
        member.fact_content_hash
    )
    forged = replace(member, revision_number=2)
    assert publication_fact_content_hashes((forged,)) == {}


@pytest.mark.parametrize("fact_pk", ("001", "١", "-1", "1x", str(1 << 63)))
def test_malformed_primary_key_fails_closed_before_fact_lookup(fact_pk: str) -> None:
    """Ambiguous or out-of-range primary-key text cannot obtain a fact digest."""

    member = _persist_valuation_member()
    malformed = replace(member, fact_pk=fact_pk)
    with pytest.raises(ValueError, match="primary key"):
        publication_fact_content_hashes((malformed,))


def test_legacy_fallback_payload_hashes_are_byte_compatible() -> None:
    """All nine normalized fallback payloads retain their pre-existing SHA bytes."""

    rows: tuple[
        tuple[str, object, PublicationFactIdentity],
        ...,
    ] = (
        (
            "equity.financial.fact",
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=date(2024, 12, 31),
                period_type="annual",
                metric_code="revenue",
                value=Decimal("123.4500"),
                unit="CNY",
                source="provider",
                report_date=date(2025, 3, 31),
                available_at=datetime(2025, 4, 1, 1, 2, 3, 456789, tzinfo=UTC),
            ),
            PublicationFactIdentity(
                natural_key="000001.SZ:2024-12-31:annual:revenue:provider",
                source="provider",
                observed_at=datetime(2025, 4, 1, 1, 2, 3, 456789, tzinfo=UTC),
                source_record_id="000001.SZ:2024-12-31:annual:revenue:provider",
                raw_payload_hash="e102cc216e3e5bd4d6e4552565ed9db193d272d835ea3c910edf899ba46027d3",
                quality_status="accepted",
                revision_number=1,
            ),
        ),
        (
            "fund.nav",
            FundNavFactModel(
                fund_code="110011",
                nav_date=date(2026, 9, 11),
                nav=Decimal("1.234567"),
                acc_nav=Decimal("2.345678"),
                daily_return=Decimal("0.012345"),
                source="fundsrc",
            ),
            PublicationFactIdentity(
                natural_key="110011:2026-09-11:fundsrc",
                source="fundsrc",
                observed_at=datetime(2026, 9, 10, 16, tzinfo=UTC),
                source_record_id="110011:2026-09-11:fundsrc",
                raw_payload_hash="13a336f194e5259998012ec0fc1b9e7955cad7805609b19bb77e2c9cd17d5c00",
                quality_status="accepted",
                revision_number=1,
            ),
        ),
        (
            "macro.fact",
            MacroFactModel(
                indicator_code="CN_GDP",
                reporting_period=date(2026, 6, 30),
                value=Decimal("123.456789"),
                unit="\u4ebf\u5143",
                source="macro",
                revision_number=2,
                published_at=date(2026, 8, 15),
                quality="valid",
            ),
            PublicationFactIdentity(
                natural_key="CN_GDP:2026-06-30:macro:2",
                source="macro",
                observed_at=datetime(2026, 8, 14, 16, tzinfo=UTC),
                source_record_id="CN_GDP:2026-06-30:macro:2",
                raw_payload_hash="d4b3d31eca878f9d31140b79b146d35b3cd16f150918a3fc2d2aafb0240017ea",
                quality_status="accepted",
                revision_number=3,
            ),
        ),
        (
            "market.news",
            NewsFactModel(
                asset_code="000001.SZ",
                title="\u91cd\u5927\u6d88\u606f",
                summary="\u6458\u8981",
                url="https://example.test/n",
                published_at=datetime(2026, 9, 11, 1, 2, 3, 456789, tzinfo=UTC),
                source="news",
                external_id="article-1",
            ),
            PublicationFactIdentity(
                natural_key="news:article-1",
                source="news",
                observed_at=datetime(2026, 9, 11, 1, 2, 3, 456789, tzinfo=UTC),
                source_record_id="article-1",
                raw_payload_hash="ee1acadea81c2269bdde8096c5a09dbbed5a47bcd95f17493338e72c577a726c",
                quality_status="accepted",
                revision_number=1,
            ),
        ),
        (
            "equity.price.bar",
            PriceBarModel(
                asset_code="000001.SZ",
                bar_date=date(2026, 9, 11),
                freq="1d",
                adjustment="none",
                open=Decimal("10.0000"),
                high=Decimal("11.0000"),
                low=Decimal("9.5000"),
                close=Decimal("10.5000"),
                volume=Decimal("1000.00"),
                amount=Decimal("10000.00"),
                source="bars",
            ),
            PublicationFactIdentity(
                natural_key="000001.SZ:2026-09-11:1d:none:bars",
                source="bars",
                observed_at=datetime(2026, 9, 10, 16, tzinfo=UTC),
                source_record_id="000001.SZ:2026-09-11:1d:none:bars",
                raw_payload_hash="518330846cef9e7dc2ecc20f94e20b8007897aa620d33d799fb9ce795ee25c4b",
                quality_status="accepted",
                revision_number=1,
            ),
        ),
        (
            "equity.quote.snapshot",
            QuoteSnapshotModel(
                asset_code="000001.SZ",
                snapshot_at=datetime(2026, 9, 11, 1, 2, 3, 456789, tzinfo=UTC),
                current_price=Decimal("10.5000"),
                open=Decimal("10.0000"),
                high=Decimal("11.0000"),
                low=Decimal("9.5000"),
                prev_close=Decimal("10.1000"),
                volume=Decimal("1000.00"),
                amount=Decimal("10000.00"),
                bid=Decimal("10.4900"),
                ask=Decimal("10.5100"),
                source="quotes",
            ),
            PublicationFactIdentity(
                natural_key="000001.SZ:2026-09-11T01:02:03.456789+00:00:quotes",
                source="quotes",
                observed_at=datetime(2026, 9, 11, 1, 2, 3, 456789, tzinfo=UTC),
                source_record_id="000001.SZ:2026-09-11T01:02:03.456789+00:00:quotes",
                raw_payload_hash="a1a85ca0ea36dec56aa327b2ae904df0c90699ad9837bb5bdbd75015e0954f12",
                quality_status="accepted",
                revision_number=1,
            ),
        ),
        (
            "market.capital_flow",
            CapitalFlowFactModel(
                asset_code="000001.SZ",
                flow_date=date(2026, 9, 11),
                main_net=Decimal("100.00"),
                retail_net=None,
                super_large_net=Decimal("30.00"),
                large_net=Decimal("70.00"),
                medium_net=Decimal("-20.00"),
                small_net=Decimal("20.00"),
                source="flows",
            ),
            PublicationFactIdentity(
                natural_key="000001.SZ:2026-09-11:flows",
                source="flows",
                observed_at=datetime(2026, 9, 10, 16, tzinfo=UTC),
                source_record_id="000001.SZ:2026-09-11:flows",
                raw_payload_hash="9e846535407c9b7dc4b9c1c9995c76837329bfcb24bf5fdd9d2d9d4dd5f7f51d",
                quality_status="accepted",
                revision_number=1,
            ),
        ),
        (
            "sector.membership",
            SectorMembershipFactModel(
                asset_code="000001.SZ",
                sector_code="CSI300",
                sector_name="\u6caa\u6df1300",
                effective_date=date(2026, 9, 1),
                expiry_date=None,
                weight=Decimal("0.123456"),
                source="membership",
            ),
            PublicationFactIdentity(
                natural_key="000001.SZ:CSI300:2026-09-01",
                source="membership",
                observed_at=datetime(2026, 8, 31, 16, tzinfo=UTC),
                source_record_id="000001.SZ:CSI300:2026-09-01",
                raw_payload_hash="e4c0010c31f2a6c8d4e830543aea6218c74796c434212ea7ca1d47a987d3cef0",
                quality_status="accepted",
                revision_number=1,
            ),
        ),
        (
            "equity.valuation.fact",
            ValuationFactModel(
                asset_code="000001.SZ",
                val_date=date(2026, 9, 11),
                pe_ttm=Decimal("12.3456"),
                pb=Decimal("1.2345"),
                market_cap=Decimal("100000.00"),
                dv_ratio=Decimal("0.012345"),
                source="valuation",
                observed_at=datetime(2026, 9, 11, 7, tzinfo=UTC),
                available_at=datetime(2026, 9, 11, 8, tzinfo=UTC),
            ),
            PublicationFactIdentity(
                natural_key="000001.SZ:2026-09-11:valuation",
                source="valuation",
                observed_at=datetime(2026, 9, 11, 7, tzinfo=UTC),
                source_record_id="000001.SZ:2026-09-11:valuation",
                raw_payload_hash="9758947fd0c952a9385845ef2f46b123993a01a5c52d0fce7dc9a1f4efee43ad",
                quality_status="accepted",
                revision_number=1,
            ),
        ),
    )
    for dataset_key, row, expected in rows:
        assert build_publication_fact_identity(dataset_key, row) == expected
