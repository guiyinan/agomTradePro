"""Read retained CSI index-perf and Tushare-compatible index_daily / trade_cal responses."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from apps.data_center.domain.historical_index_closes import IndexCloseSeries, merge_index_closes
from shared.numeric import safe_float


def _payload(path: Path, receipts: dict[str, str]) -> dict[str, Any]:
    raw = path.read_bytes()
    receipts[str(path)] = hashlib.sha256(raw).hexdigest()
    obj = json.loads(raw, parse_float=Decimal)
    if not isinstance(obj, dict):
        raise ValueError(f"Invalid response in {path}")
    return obj


def _table(payload: dict[str, Any], fields: tuple[str, ...]) -> Iterator[list[object]]:
    data = payload.get("data")
    if type(payload.get("code")) is not int or payload["code"] != 0 or not isinstance(data, dict):
        raise ValueError("Unsuccessful tabular source response")
    cols, rows = data.get("fields"), data.get("items")
    if (
        not isinstance(cols, list)
        or not all(isinstance(c, str) for c in cols)
        or len(set(cols)) != len(cols)
        or not set(fields) <= set(cols)
        or not isinstance(rows, list)
    ):
        raise ValueError("Invalid response fields or rows")
    positions = [cols.index(field) for field in fields]
    for row in rows:
        if not isinstance(row, list) or len(row) != len(cols):
            raise ValueError("Invalid tabular source row")
        yield [row[i] for i in positions]


def _day(raw: object) -> date:
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{8}", raw):
        raise ValueError("Invalid source date")
    return date.fromisoformat(raw)


def _read_closes(
    paths: list[Path], code: str, receipts: dict[str, str], *, official: bool
) -> dict[date, Decimal]:
    values: dict[date, Decimal] = {}
    for path in paths:
        body = _payload(path, receipts)
        rows: Iterator[list[object]]
        if official:
            data = body.get("data")
            if body.get("code") != "200" or not isinstance(data, list):
                raise ValueError(f"Unsuccessful CSI response in {path}")
            if not all(
                isinstance(r, dict) and r.get("indexCode") == code.split(".")[0] for r in data
            ):
                raise ValueError(f"Unexpected CSI index in {path}")
            rows = ([code, r.get("tradeDate"), r.get("close")] for r in data)
        else:
            rows = _table(body, ("ts_code", "trade_date", "close"))
        seen: set[date] = set()
        for symbol, raw_day, raw_value in rows:
            day = _day(raw_day)
            if (
                symbol != code
                or day in seen
                or isinstance(raw_value, bool)
                or not isinstance(raw_value, (str, Decimal, int))
                or safe_float(raw_value) is None
            ):
                raise ValueError(f"Invalid or duplicate observation in {path} on {day}")
            value = Decimal(str(raw_value))
            if value <= 0 or values.setdefault(day, value) != value:
                raise ValueError(f"Conflicting or nonpositive observation in {path} on {day}")
            seen.add(day)
    return values


def merge_historical_index_snapshots(
    index_code: str,
    start: date,
    end: date,
    *,
    calendars: list[Path],
    csi: list[Path],
    relay: list[Path],
) -> dict[str, object]:
    """Merge original closes on the selected exchange calendar and return auditable JSON."""
    if not re.fullmatch(r"[0-9]{6}\.(SH|SZ)", index_code) or start > end:
        raise ValueError("Invalid index code or date range")
    exchange = "SSE" if index_code.endswith(".SH") else "SZSE"
    receipts: dict[str, str] = {}
    days: dict[date, bool] = {}
    for path in calendars:
        for venue, stamp, flag in _table(
            _payload(path, receipts), ("exchange", "cal_date", "is_open")
        ):
            day = _day(stamp)
            if venue != exchange or type(flag) is not int or flag not in (0, 1):
                raise ValueError(f"Invalid {exchange} calendar row in {path}")
            if start <= day <= end and days.setdefault(day, bool(flag)) != bool(flag):
                raise ValueError(f"Calendar conflict on {day}")
    if len(days) != (end - start).days + 1:
        raise ValueError("Calendar does not cover the full requested date range")
    sessions = tuple(sorted(day for day, opened in days.items() if opened))
    # CSI index-perf closes in the supported snapshot format are rounded to hundredths.
    # The relay's native decimal is preserved; a short printed value supplies no rounding rule.
    sources = (
        IndexCloseSeries(
            index_code, "csi", 2, _read_closes(csi, index_code, receipts, official=True)
        ),
        IndexCloseSeries(
            index_code,
            "tushare_compatible",
            None,
            _read_closes(relay, index_code, receipts, official=False),
        ),
    )
    merged = merge_index_closes(sessions, sources)
    return {
        "index_code": index_code,
        "unit": "index_points",
        "basis": "unadjusted_daily_close",
        "knowledge_semantics": "retrospective_snapshot",
        "inputs_sha256": receipts,
        "rows": [
            {
                "date": row.session.isoformat(),
                "close": str(row.close),
                "source": row.source,
                "reason": row.reason,
                "originals": {s: str(v) for s, v in row.observations},
            }
            for row in merged
        ],
    }
