"""ORM selectors for full-universe current-publication candidates."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256

import pytest

from apps.data_center.infrastructure.financial_fact_repository import (
    FinancialFactRepository,
)
from apps.data_center.infrastructure.models import (
    FinancialFactModel,
    PriceBarModel,
    QuoteSnapshotModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.quote_snapshot_repository import (
    QuoteSnapshotRepository,
)
from apps.data_center.infrastructure.valuation_fact_repository import (
    ValuationFactRepository,
)
from core.exceptions import InvalidInputError
from tests.component.data_center.test_financial_source_provenance import (
    _decision_projection,
    _decision_transport_extra,
)

AVAILABLE_AT = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def _evidenced_financial_row(
    *,
    asset_code: str,
    period_end: date,
    metric_code: str,
    value: int,
    source: str,
    available_at: datetime,
) -> FinancialFactModel:
    """Persist a selector fixture with exact v2 source-time evidence."""

    announced_at = available_at - timedelta(minutes=5)
    source_record_id = f"{asset_code}:{period_end.isoformat()}:{metric_code}:{source}"
    raw_payload_hash = sha256(source_record_id.encode("utf-8")).hexdigest()
    decision_evidence = _decision_projection(
        asset_code=asset_code,
        period_end=period_end,
        provider_name=source,
        source_record_id=source_record_id,
        announced_at=announced_at,
        available_at=available_at,
        raw_payload_hash=raw_payload_hash,
    )
    return FinancialFactModel.objects.create(
        asset_code=asset_code,
        period_end=period_end,
        period_type="quarterly",
        metric_code=metric_code,
        value=value,
        source=source,
        report_date=announced_at.date(),
        announced_at=announced_at,
        available_at=available_at,
        source_record_id=source_record_id,
        raw_payload_hash=raw_payload_hash,
        extra=_decision_transport_extra(decision_evidence),
        decision_evidence=decision_evidence,
    )


@pytest.mark.django_db
def test_quote_selector_returns_latest_snapshot_per_asset() -> None:
    for asset_code in ("000001.SZ", "600000.SH"):
        QuoteSnapshotModel.objects.create(
            asset_code=asset_code,
            snapshot_at=AVAILABLE_AT - timedelta(minutes=2),
            current_price=10,
            source="source-old",
        )
        QuoteSnapshotModel.objects.create(
            asset_code=asset_code,
            snapshot_at=AVAILABLE_AT,
            current_price=11,
            source="source-new",
        )

    references = QuoteSnapshotRepository().list_current_publication_candidates(
        ("000001.SZ", "600000.SH")
    )

    assert len(references) == 2
    assert all(item.observed_at == AVAILABLE_AT for item in references)
    assert all(item.fact_table == "data_center_quote_snapshot" for item in references)


@pytest.mark.django_db
def test_price_selector_returns_latest_daily_unadjusted_fact_per_asset() -> None:
    for asset_code in ("000001.SZ", "600000.SH"):
        PriceBarModel.objects.create(
            asset_code=asset_code,
            bar_date=date(2026, 8, 27),
            freq="1d",
            adjustment="none",
            open=10,
            high=11,
            low=9,
            close=10,
            source="source-old",
        )
        PriceBarModel.objects.create(
            asset_code=asset_code,
            bar_date=date(2026, 8, 28),
            freq="1d",
            adjustment="none",
            open=11,
            high=12,
            low=10,
            close=11,
            source="source-new",
        )
        PriceBarModel.objects.create(
            asset_code=asset_code,
            bar_date=date(2026, 8, 29),
            freq="1w",
            adjustment="none",
            open=11,
            high=12,
            low=10,
            close=11,
            source="source-weekly",
        )

    references = PriceBarRepository().list_current_publication_candidates(
        ("000001.SZ", "600000.SH")
    )

    assert len(references) == 2
    assert {item.natural_key.split(":", 1)[0] for item in references} == {
        "000001.SZ",
        "600000.SH",
    }
    assert all(":2026-08-28:1d:none:source-new" in item.natural_key for item in references)
    assert all(item.fact_table == "data_center_price_bar" for item in references)


@pytest.mark.django_db
def test_valuation_selector_returns_latest_fact_per_asset() -> None:
    for asset_code in ("000001.SZ", "600000.SH"):
        ValuationFactModel.objects.create(
            asset_code=asset_code,
            val_date=date(2026, 8, 27),
            pe_ttm=10,
            source="source-old",
            observed_at=AVAILABLE_AT - timedelta(days=1),
        )
        ValuationFactModel.objects.create(
            asset_code=asset_code,
            val_date=date(2026, 8, 28),
            pe_ttm=11,
            source="source-new",
            observed_at=AVAILABLE_AT,
            available_at=AVAILABLE_AT,
        )

    references = ValuationFactRepository().list_current_publication_candidates(
        ("000001.SZ", "600000.SH")
    )

    assert len(references) == 2
    assert all(":2026-08-28:source-new" in item.natural_key for item in references)
    assert all(item.fact_table == "data_center_valuation_fact" for item in references)


@pytest.mark.django_db
def test_financial_selector_uses_latest_available_period_and_one_source_per_metric() -> None:
    _evidenced_financial_row(
        asset_code="000001.SZ",
        period_end=date(2026, 3, 31),
        metric_code="revenue",
        value=90,
        source="source-old",
        available_at=AVAILABLE_AT - timedelta(days=90),
    )
    _evidenced_financial_row(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        metric_code="revenue",
        value=100,
        source="source-a",
        available_at=AVAILABLE_AT - timedelta(hours=1),
    )
    _evidenced_financial_row(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        metric_code="revenue",
        value=101,
        source="source-b",
        available_at=AVAILABLE_AT,
    )
    _evidenced_financial_row(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        metric_code="net_profit",
        value=20,
        source="source-a",
        available_at=AVAILABLE_AT,
    )
    FinancialFactModel.objects.create(
        asset_code="600000.SH",
        period_end=date(2026, 6, 30),
        period_type="quarterly",
        metric_code="revenue",
        value=200,
        source="missing-evidence",
        available_at=None,
    )
    _evidenced_financial_row(
        asset_code="600000.SH",
        period_end=date(2026, 3, 31),
        metric_code="revenue",
        value=190,
        source="source-valid",
        available_at=AVAILABLE_AT - timedelta(days=80),
    )

    references = FinancialFactRepository(
        source_time_evidence_verifier=lambda _decision: True
    ).list_current_publication_candidates(("000001.SZ", "600000.SH"))

    assert len(references) == 3
    keys = {item.natural_key for item in references}
    assert "000001.SZ:2026-06-30:quarterly:revenue:source-b" in keys
    assert "000001.SZ:2026-06-30:quarterly:net_profit:source-a" in keys
    assert "600000.SH:2026-03-31:quarterly:revenue:source-valid" in keys
    assert all(item.fact_table == "data_center_financial_fact" for item in references)
    assert all(item.observed_at is not None for item in references)


@pytest.mark.django_db
def test_financial_calendar_date_backfill_is_blocked_without_changing_history() -> None:
    eligible = FinancialFactModel.objects.create(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type="quarterly",
        metric_code="revenue",
        value=100,
        source="source-a",
        report_date=date(2026, 8, 15),
        available_at=None,
    )
    FinancialFactModel.objects.create(
        asset_code="600000.SH",
        period_end=date(2026, 6, 30),
        period_type="quarterly",
        metric_code="revenue",
        value=200,
        source="source-a",
        report_date=None,
        available_at=None,
    )
    repository = FinancialFactRepository()

    preview = repository.preview_availability_backfill(
        asset_codes=("000001.SZ", "600000.SH"),
        recorded_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    before = list(FinancialFactModel.objects.order_by("pk").values())
    with pytest.raises(InvalidInputError, match="verified source timestamp"):
        repository.backfill_available_at_from_report_date(
            asset_codes=("000001.SZ", "600000.SH"),
            recorded_at=datetime(2026, 8, 30, tzinfo=UTC),
        )

    eligible.refresh_from_db()
    assert preview.missing_row_count == 2
    assert preview.eligible_row_count == 1
    assert preview.unresolved_row_count == 1
    assert preview.safe_to_execute is False
    assert eligible.available_at is None
    assert list(FinancialFactModel.objects.order_by("pk").values()) == before
