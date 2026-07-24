"""Persistence invariants for executable Data Center prices."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.data_center.infrastructure.models import (
    FundNavFactModel,
    MarketThermometerSnapshotModel,
    PriceBarModel,
    QuoteSnapshotModel,
)


@pytest.mark.django_db
def test_direct_price_fact_writes_require_positive_attributed_prices() -> None:
    with pytest.raises(ValidationError):
        PriceBarModel.objects.create(
            asset_code="510300.SH",
            bar_date=date(2026, 7, 25),
            open=4.9,
            high=5.0,
            low=4.8,
            close=0,
            source="test",
        )
    with pytest.raises(ValidationError):
        QuoteSnapshotModel.objects.create(
            asset_code="510300.SH",
            snapshot_at=timezone.now(),
            current_price=-1,
            source="test",
        )
    with pytest.raises(ValidationError):
        FundNavFactModel.objects.create(
            fund_code="110011",
            nav_date=date(2026, 7, 25),
            nav=1.2,
            source="",
        )


@pytest.mark.django_db
def test_database_constraints_block_queryset_price_bypasses() -> None:
    bar = PriceBarModel.objects.create(
        asset_code="510300.SH",
        bar_date=date(2026, 7, 25),
        open=4.9,
        high=5.0,
        low=4.8,
        close=4.95,
        source="test",
    )
    quote = QuoteSnapshotModel.objects.create(
        asset_code="510300.SH",
        snapshot_at=timezone.now(),
        current_price=4.96,
        source="test",
    )
    nav = FundNavFactModel.objects.create(
        fund_code="110011",
        nav_date=date(2026, 7, 25),
        nav=1.2,
        source="test",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        PriceBarModel._default_manager.filter(pk=bar.pk).update(close=0)
    with pytest.raises(IntegrityError), transaction.atomic():
        QuoteSnapshotModel._default_manager.filter(pk=quote.pk).update(current_price=0)
    with pytest.raises(IntegrityError), transaction.atomic():
        FundNavFactModel._default_manager.filter(pk=nav.pk).update(nav=0)


@pytest.mark.django_db
def test_market_thermometer_json_does_not_treat_strings_as_booleans() -> None:
    snapshot = MarketThermometerSnapshotModel(
        observed_at=date(2026, 7, 25),
        score=50,
        band="warm",
        components=[
            {
                "component_key": "turnover",
                "label": "Turnover",
                "indicator_code": "turnover",
                "score": 50,
                "weight": 0.25,
                "is_stale": "false",
            }
        ],
    )

    with pytest.raises(ValueError, match="component.is_stale must be a boolean"):
        snapshot.to_domain()
