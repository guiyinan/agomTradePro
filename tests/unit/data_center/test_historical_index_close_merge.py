import json
from datetime import date
from decimal import Decimal

import pytest

from apps.data_center.domain.historical_index_closes import IndexCloseSeries, merge_index_closes
from apps.data_center.infrastructure.historical_index_close_snapshots import (
    merge_historical_index_snapshots,
)

DAY = date(2025, 12, 17)
NEXT = date(2025, 12, 18)


def series(source, places, values, code="000300.SH"):
    return IndexCloseSeries(code, source, places, {k: Decimal(v) for k, v in values.items()})


def test_precision_and_calendar_select_one_original_per_day():
    coarse = series("official", 2, {DAY: "4579.88", NEXT: "4580.10"})
    fine = series("relay", None, {DAY: "4579.8750"})
    for sources in [(coarse, fine), (fine, coarse)]:
        first, second = merge_index_closes((DAY, NEXT), sources)
        assert (first.close, first.source) == (Decimal("4579.8750"), "relay")
        assert first.reason == "rounding_equivalent"
        assert second.source == "official" and second.reason == "single_source"


def test_equal_numeric_values_keep_priority_even_when_text_is_padded():
    coarse = series("priority", 2, {DAY: "100.10"})
    fine = series("other", None, {DAY: "100.10000"})
    assert merge_index_closes((DAY,), (coarse, fine))[0].source == "priority"
    declared = series("verified", 4, {DAY: "100.1"})
    assert merge_index_closes((DAY,), (coarse, declared))[0].source == "verified"


@pytest.mark.parametrize("bad", ["4579.8749", "4579.89", "4580"])
def test_small_but_non_rounding_differences_raise(bad):
    with pytest.raises(ValueError, match="conflict"):
        merge_index_closes(
            (DAY,), (series("a", 2, {DAY: "4579.88"}), series("b", None, {DAY: bad}))
        )


def test_no_calendar_compression_or_unverified_switch():
    a = series("a", 2, {DAY: "100"})
    with pytest.raises(ValueError, match="missing"):
        merge_index_closes((DAY, NEXT), (a,))
    with pytest.raises(ValueError, match="overlap"):
        merge_index_closes((DAY, NEXT), (a, series("b", None, {NEXT: "101"})))
    with pytest.raises(ValueError, match="index"):
        merge_index_closes((DAY,), (a, series("b", None, {DAY: "100"}, "000016.SH")))


def test_snapshot_reader_keeps_original_precision_and_exchange_calendar(tmp_path):
    def file(name, body):
        path = tmp_path / name
        path.write_text(json.dumps(body), encoding="utf8")
        return path

    def table(columns, rows):
        return {"code": 0, "data": {"fields": columns, "items": rows}}

    calendar = file(
        "calendar",
        table(
            ["exchange", "cal_date", "is_open"], [["SSE", "20251217", 1], ["SSE", "20251218", 0]]
        ),
    )
    official = file(
        "official",
        {
            "code": "200",
            "data": [
                {"indexCode": "000300", "tradeDate": "20251217", "close": 4579.88},
                {"indexCode": "000300", "tradeDate": "20251218", "close": 4579.88},
            ],
        },
    )
    relay = file(
        "relay", table(["close", "ts_code", "trade_date"], [["4579.8750", "000300.SH", "20251217"]])
    )
    args = {"csi": [official], "relay": [relay], "calendars": [calendar]}
    report = merge_historical_index_snapshots("000300.SH", DAY, NEXT, **args)
    assert len(report["inputs_sha256"]) == 3
    assert report["rows"] == [
        {
            "date": "2025-12-17",
            "close": "4579.8750",
            "source": "tushare_compatible",
            "reason": "rounding_equivalent",
            "originals": {"csi": "4579.88", "tushare_compatible": "4579.8750"},
        }
    ]
    with pytest.raises(ValueError, match="full requested"):
        merge_historical_index_snapshots("000300.SH", DAY, date(2025, 12, 19), **args)
    with pytest.raises(ValueError, match="CSI index"):
        merge_historical_index_snapshots("000016.SH", DAY, NEXT, **args)
