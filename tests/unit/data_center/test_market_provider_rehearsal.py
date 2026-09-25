"""Production rehearsal must detect identity and clock failures, including empty calls."""

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.data_center.application.market_provider_rehearsal import (
    assess_market_probe,
    select_rehearsal_sample,
)
from apps.data_center.domain.entities import QuoteSnapshot


def test_sample_is_deterministic_bounded_and_covers_present_exchange_groups() -> None:
    codes = tuple(f"{i:06}.{suffix}" for suffix in ("SH", "SZ", "BJ") for i in range(100))
    result = select_rehearsal_sample(codes, 50)
    assert len(result) == len(set(result)) == 50
    assert result == select_rehearsal_sample(tuple(reversed(codes)), 50)
    assert {code.rsplit(".", 1)[-1] for code in result} == {"SH", "SZ", "BJ"}
    assert select_rehearsal_sample(("600000.SH",), 50) == ("600000.SH",)


@pytest.mark.parametrize("codes,size", [((), 50), (("600000.SH",), True), (("600000.SH",), 0)])
def test_empty_or_invalid_sample_is_not_a_rehearsal(codes, size) -> None:
    with pytest.raises(ValueError):
        select_rehearsal_sample(codes, size)


@pytest.mark.parametrize(
    "defect", ["empty", "duplicate", "unexpected", "stale", "cached", "future"]
)
def test_probe_rejects_coverage_and_real_clock_defects(defect: str) -> None:
    start = datetime(2026, 9, 24, 8, tzinfo=UTC)
    code = "600000.SH"
    observed = start - timedelta(hours=1)
    fetched = start + timedelta(seconds=1)
    if defect == "unexpected":
        code = "600001.SH"
    if defect == "stale":
        observed -= timedelta(days=1)
    if defect == "cached":
        fetched = start - timedelta(minutes=1)
    if defect == "future":
        fetched = start + timedelta(minutes=1)
    fact = QuoteSnapshot(code, observed, 12.3, "real-provider", fetched_at=fetched)
    facts = [] if defect == "empty" else [fact, fact] if defect == "duplicate" else [fact]
    report = assess_market_probe(
        dataset="equity.quote.snapshot",
        facts=facts,
        sample=("600000.SH",),
        target_date=date(2026, 9, 24),
        started_at=start,
        finished_at=start + timedelta(seconds=3),
    )
    assert report["outcome"] != "success"
    assert report["stored"] == 0
    assert report["issues"]


def test_current_complete_probe_reports_facts_not_publication_success() -> None:
    start = datetime(2026, 9, 24, 8, tzinfo=UTC)
    fact = QuoteSnapshot(
        "600000.SH",
        start - timedelta(hours=1),
        12.3,
        "provider",
        fetched_at=start + timedelta(seconds=1),
        volume=100.0,
        amount=1_000.0,
    )
    report = assess_market_probe(
        dataset="equity.quote.snapshot",
        facts=[fact],
        sample=(fact.asset_code,),
        target_date=date(2026, 9, 24),
        started_at=start,
        finished_at=start + timedelta(seconds=3),
    )
    assert report["outcome"] == "success"
    assert report["requested"] == report["succeeded"] == 1
    assert report["failed"] == report["stored"] == 0
    assert report["publication_updated"] is False


def test_probe_blocks_quote_without_volume_or_amount_witnesses() -> None:
    start = datetime(2026, 9, 24, 8, tzinfo=UTC)
    fact = QuoteSnapshot(
        "600000.SH",
        start - timedelta(hours=1),
        12.3,
        "provider",
        fetched_at=start + timedelta(seconds=1),
    )

    report = assess_market_probe(
        dataset="equity.quote.snapshot",
        facts=[fact],
        sample=(fact.asset_code,),
        target_date=date(2026, 9, 24),
        started_at=start,
        finished_at=start + timedelta(seconds=3),
    )

    assert report["outcome"] == "blocked"
    assert report["issues"] == [
        {"asset_code": "600000.SH", "code": "REHEARSAL_QUOTE_MEASURES_MISSING"}
    ]
