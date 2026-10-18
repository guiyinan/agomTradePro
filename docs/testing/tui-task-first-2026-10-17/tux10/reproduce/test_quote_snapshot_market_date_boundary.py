"""Private candidate for the TUX10 quote date-boundary regression.

This file is an unapplied test draft.  It is intentionally a repository-level
check: it uses the real typed QuoteSnapshotRepository bulk_upsert and
publication-candidate lookup, without inserting ORM rows directly or mocking
an owner response.  The existing research_scenario remains the integration
fixture that runs the real quote publication after these rows are resolved.
"""

from datetime import UTC, date, datetime

import pytest

from apps.data_center.domain.entities import QuoteSnapshot
from apps.data_center.infrastructure.quote_snapshot_repository import (
    QuoteSnapshotRepository,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("asset_code", "quote_at", "china_market_date"),
    (
        (
            "600000.SH",
            datetime(2026, 8, 8, 15, 59, 59, tzinfo=UTC),
            date(2026, 8, 8),
        ),
        (
            "600001.SH",
            datetime(2026, 8, 8, 16, 0, 0, tzinfo=UTC),
            date(2026, 8, 9),
        ),
    ),
)
def test_quote_repository_resolves_same_aware_snapshot_on_china_date_boundary(
    asset_code: str,
    quote_at: datetime,
    china_market_date: date,
) -> None:
    """The repository date filter follows the China market day at UTC 16:00."""

    quote = QuoteSnapshot(
        asset_code=asset_code,
        snapshot_at=quote_at,
        current_price=12.34,
        source="tux10-utc-date-boundary",
        fetched_at=quote_at,
    )
    repository = QuoteSnapshotRepository()

    assert repository.bulk_upsert([quote]) == 1

    rows = repository.get_series(
        asset_code,
        snapshot_date=china_market_date,
        limit=1,
    )
    assert len(rows) == 1
    assert rows[0].snapshot_at.astimezone(UTC) == quote_at

    candidates = repository.list_publication_candidates([quote])
    assert len(candidates) == 1
    assert candidates[0].fact_table == "data_center_quote_snapshot"
    assert candidates[0].observed_at == quote_at
