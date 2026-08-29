"""SQLite contract tests for canonical fact replay evidence resolution."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from apps.data_center.domain.control_plane import PublicationMember
from apps.data_center.infrastructure.data_chain_replay_evidence import (
    DjangoReplayFactEvidenceReader,
)
from apps.data_center.infrastructure.models import (
    MacroFactModel,
    PriceBarModel,
    QuoteSnapshotModel,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
MACRO_RUN = UUID("11111111-1111-4111-8111-111111111111")
PRICE_RUN = UUID("22222222-2222-4222-8222-222222222222")
QUOTE_RUN = UUID("33333333-3333-4333-8333-333333333333")
SCHEMA_MODELS = (MacroFactModel, PriceBarModel, QuoteSnapshotModel)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Isolate only the three whitelisted fact tables."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(SCHEMA_MODELS):
            yield


def _seed_facts() -> tuple[int, int, int]:
    """Insert one valid fact row per supported replay table."""

    macro = MacroFactModel._default_manager.create(
        indicator_code="CN_CPI",
        reporting_period=date(2026, 8, 1),
        value=Decimal("2.1"),
        unit="%",
        source="provider-macro",
        published_at=date(2026, 8, 3),
        raw_payload_hash="a" * 64,
        ingested_run_id=MACRO_RUN,
    )
    price = PriceBarModel._default_manager.create(
        asset_code="000001.SZ",
        bar_date=date(2026, 8, 27),
        freq="1d",
        adjustment="none",
        open=Decimal("10.0"),
        high=Decimal("11.0"),
        low=Decimal("9.5"),
        close=Decimal("10.5"),
        source="provider-price",
        raw_payload_hash="b" * 64,
        ingested_run_id=PRICE_RUN,
    )
    quote = QuoteSnapshotModel._default_manager.create(
        asset_code="000001.SZ",
        snapshot_at=NOW,
        fetched_at=NOW,
        current_price=Decimal("10.5"),
        source="provider-quote",
        raw_payload_hash="c" * 64,
        ingested_run_id=QUOTE_RUN,
    )
    assert macro.pk is not None
    assert price.pk is not None
    assert quote.pk is not None
    return int(macro.pk), int(price.pk), int(quote.pk)


def _member(
    *,
    fact_table: str,
    fact_pk: str,
    member_id: str | None = None,
) -> PublicationMember:
    """Build a publication member targeting one exact fact row."""

    return PublicationMember(
        member_id=member_id or str(uuid4()),
        publication_id="publication-1",
        dataset_key="data.reliability",
        natural_key=f"{fact_table}:{fact_pk}",
        source="provider-main",
        source_record_id=f"source:{fact_pk}",
        fact_table=fact_table,
        fact_pk=fact_pk,
        observed_at=NOW,
    )


def test_whitelisted_tables_return_exact_input_order_and_ingestion_ids() -> None:
    macro_pk, price_pk, quote_pk = _seed_facts()
    members = (
        _member(fact_table="data_center_quote_snapshot", fact_pk=str(quote_pk)),
        _member(fact_table="data_center_macro_fact", fact_pk=str(macro_pk)),
        _member(fact_table="data_center_price_bar", fact_pk=str(price_pk)),
    )

    evidence = DjangoReplayFactEvidenceReader().list_member_evidence(members)

    assert len(evidence) == 3
    assert [(item.fact_table, item.fact_pk, item.ingested_run_id) for item in evidence] == [
        ("data_center_quote_snapshot", str(quote_pk), str(QUOTE_RUN)),
        ("data_center_macro_fact", str(macro_pk), str(MACRO_RUN)),
        ("data_center_price_bar", str(price_pk), str(PRICE_RUN)),
    ]


@pytest.mark.parametrize(
    "member",
    [
        _member(fact_table="data_center_price_bar", fact_pk="999999"),
        _member(fact_table="data_center_price_bar", fact_pk="not-an-integer"),
        _member(fact_table="data_center_unknown", fact_pk="1"),
    ],
)
def test_missing_unknown_or_malformed_member_never_fabricates_evidence(
    member: PublicationMember,
) -> None:
    _seed_facts()

    evidence = DjangoReplayFactEvidenceReader().list_member_evidence((member,))

    assert evidence == ()


def test_existing_fact_without_ingested_run_is_omitted() -> None:
    _, price_pk, _ = _seed_facts()
    PriceBarModel._default_manager.filter(pk=price_pk).update(ingested_run_id=None)
    member = _member(fact_table="data_center_price_bar", fact_pk=str(price_pk))

    evidence = DjangoReplayFactEvidenceReader().list_member_evidence((member,))

    assert evidence == ()
