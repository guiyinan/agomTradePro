"""The operator dry-run must keep database reads bounded at full-market scale."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.data_center.infrastructure.models import (
    PriceBarModel,
    QuoteSnapshotModel,
    ValuationFactModel,
)

pytestmark = pytest.mark.django_db


def test_full_market_publication_dry_run_has_bounded_query_budget(mocker) -> None:
    """Preview 5,557 securities through the real command without per-asset queries."""

    asset_codes = tuple(f"{index:06d}.SZ" for index in range(5557))
    observed_at = datetime(2026, 9, 24, 7, tzinfo=UTC)
    observed_date = date(2026, 9, 24)
    QuoteSnapshotModel.objects.bulk_create(
        [
            QuoteSnapshotModel(
                asset_code=asset_code,
                snapshot_at=observed_at,
                fetched_at=observed_at,
                current_price="10.2500",
                source="scale-fixture",
            )
            for asset_code in asset_codes
        ],
        batch_size=500,
    )
    PriceBarModel.objects.bulk_create(
        [
            PriceBarModel(
                asset_code=asset_code,
                bar_date=observed_date,
                open="10.0000",
                high="10.5000",
                low="9.9000",
                close="10.2500",
                source="scale-fixture",
            )
            for asset_code in asset_codes
        ],
        batch_size=500,
    )
    ValuationFactModel.objects.bulk_create(
        [
            ValuationFactModel(
                asset_code=asset_code,
                val_date=observed_date,
                pe_ttm="12.5000",
                source="scale-fixture",
                observed_at=observed_at,
                fetched_at=observed_at,
                available_at=observed_at,
            )
            for asset_code in asset_codes
        ],
        batch_size=500,
    )
    mocker.patch(
        "apps.data_center.management.commands.rebuild_active_a_share_core_publications."
        "list_active_stock_codes_for_backfill",
        return_value=list(asset_codes),
    )
    stdout = StringIO()

    with CaptureQueriesContext(connection) as queries:
        call_command("rebuild_active_a_share_core_publications", stdout=stdout)

    payload = json.loads(stdout.getvalue())
    datasets = {item["dataset_key"]: item for item in payload["datasets"]}
    assert payload["mode"] == "dry_run"
    assert payload["asset_count"] == 5557
    assert payload["ready"] is False
    assert datasets["equity.quote.snapshot"]["member_count"] == 5557
    assert datasets["equity.price.bar"]["member_count"] == 5557
    assert datasets["equity.valuation.fact"]["member_count"] == 5557
    assert datasets["equity.financial.fact"]["member_count"] == 0
    assert len(queries) <= 8
    assert all(
        not query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
        for query in queries
    )
