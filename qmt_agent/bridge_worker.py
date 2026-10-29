"""Isolated, bounded market collection worker for the integrated QMT Agent."""

from __future__ import annotations

import importlib
import json
import logging
import math
import numbers
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast

from .api_client import AgentApiError

_logger = logging.getLogger(__name__)
_CHINA_TIMEZONE = timezone(timedelta(hours=8))


class DailyStatusSample(TypedDict):
    """One explicit QMT daily suspension observation for a returned source row."""

    asset_code: str
    bar_date: str
    suspend_flag: int | None


@dataclass(frozen=True, slots=True)
class DailyHistoryResult:
    """Bars and independent statuses parsed from one native daily-history read."""

    bars: tuple[dict[str, Any], ...]
    statuses: tuple[DailyStatusSample, ...]


class BridgeTransport(Protocol):
    """Minimal transport used by the durable market worker."""

    def post(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class MarketSource(Protocol):
    """Source observation adapter, independent of trading callbacks and queues."""

    def quotes(self, assets: list[str]) -> list[dict[str, Any]]: ...
    def bars(self, assets: list[str], start: str, end: str) -> list[dict[str, Any]]: ...


class DailyHistorySource(Protocol):
    """Optional source port that returns daily bars and statuses from one read."""

    def daily_history(self, assets: list[str], start: str, end: str) -> DailyHistoryResult: ...


class XtDataSource:
    """Use the market SDK only; never import or construct XtQuantTrader."""

    def __init__(self) -> None:
        self.sdk: Any = importlib.import_module("xtquant.xtdata")
        self.subscriptions: set[str] = set()

    def quotes(self, assets: list[str]) -> list[dict[str, Any]]:
        """Subscribe and read source-timestamped snapshots without fabricating missing time."""
        try:
            result = self._quotes(assets)
        except (RuntimeError, OSError, ValueError, TypeError, OverflowError) as exc:
            self.subscriptions.clear()
            raise AgentApiError("QMT market read failed; subscriptions will be renewed") from exc
        if not result:
            self.subscriptions.clear()
        return result

    def _quotes(self, assets: list[str]) -> list[dict[str, Any]]:
        for asset in assets:
            if asset not in self.subscriptions:
                sequence = self.sdk.subscribe_quote(asset, period="tick")
                if sequence < 0:
                    raise AgentApiError("QMT market subscription failed")
                self.subscriptions.add(asset)
        raw = self.sdk.get_full_tick(assets)
        rows: list[dict[str, Any]] = []
        for asset in assets:
            tick = raw.get(asset) if isinstance(raw, dict) else None
            if not isinstance(tick, dict) or not tick.get("time"):
                continue
            price = _wire_number(tick.get("lastPrice"), positive=True)
            if price is None:
                continue
            rows.append(
                {
                    "asset_code": asset,
                    "observed_at": datetime.fromtimestamp(
                        int(tick["time"]) / 1000, UTC
                    ).isoformat(),
                    "price": price,
                    "open": _wire_number(tick.get("open"), positive=True),
                    "high": _wire_number(tick.get("high"), positive=True),
                    "low": _wire_number(tick.get("low"), positive=True),
                    "prev_close": _wire_number(tick.get("lastClose"), positive=True),
                    "volume": _wire_number(tick.get("volume")),
                    "amount": _wire_number(tick.get("amount")),
                }
            )
        return rows

    def bars(self, assets: list[str], start: str, end: str) -> list[dict[str, Any]]:
        """Return the old price-only API backed by one combined daily SDK read."""

        return list(self.daily_history(assets, start, end).bars)

    def daily_history(self, assets: list[str], start: str, end: str) -> DailyHistoryResult:
        """Collect explicit status and price rows from one unadjusted daily SDK response."""

        start_day, end_day = _completed_history_range(start, end)
        if (
            type(assets) is not list
            or not 1 <= len(assets) <= 200
            or any(
                type(asset) is not str or not asset or asset != asset.strip() for asset in assets
            )
            or len(set(assets)) != len(assets)
        ):
            raise ValueError("Daily history requires unique explicit asset codes")
        for asset in assets:
            self.sdk.download_history_data(
                asset,
                period="1d",
                start_time=start_day.strftime("%Y%m%d"),
                end_time=end_day.strftime("%Y%m%d"),
            )

        data = self.sdk.get_market_data_ex(
            ["open", "high", "low", "close", "volume", "amount", "suspendFlag"],
            assets,
            period="1d",
            start_time=start_day.strftime("%Y%m%d"),
            end_time=end_day.strftime("%Y%m%d"),
            dividend_type="none",
            fill_data=False,
        )
        if not isinstance(data, dict):
            raise AgentApiError("QMT daily history response is invalid")

        observations: dict[tuple[str, date], tuple[dict[str, Any], DailyStatusSample]] = {}
        for asset in assets:
            frame = data.get(asset)
            if frame is None:
                continue
            iterrows = getattr(frame, "iterrows", None)
            if not callable(iterrows):
                raise AgentApiError("QMT daily history frame is invalid")
            for index, bar in iterrows():
                day = _parse_daily_index(index)
                if not start_day <= day <= end_day:
                    raise AgentApiError("QMT daily history returned an out-of-range date")
                raw_flag = _row_value(bar, "suspendFlag")
                status: DailyStatusSample = {
                    "asset_code": asset,
                    "bar_date": day.isoformat(),
                    "suspend_flag": _normalize_suspend_flag(
                        raw_flag, asset_code=asset, bar_date=day
                    ),
                }

                prices = {
                    key: _wire_number(_row_value(bar, key), positive=True)
                    for key in ("open", "high", "low", "close")
                }
                bar_sample: dict[str, Any] = {}
                if all(value is not None for value in prices.values()):
                    # Daily source date, never request time. Midnight only anchors the legacy bar wire.
                    observed = datetime(day.year, day.month, day.day, tzinfo=UTC)
                    bar_sample = {
                        "asset_code": asset,
                        "bar_date": day.isoformat(),
                        "observed_at": observed.isoformat(),
                        "price": prices["close"],
                        "open": prices["open"],
                        "high": prices["high"],
                        "low": prices["low"],
                        "volume": _wire_number(_row_value(bar, "volume")),
                        "amount": _wire_number(_row_value(bar, "amount")),
                    }
                key = (asset, day)
                previous = observations.get(key)
                current = (bar_sample, status)
                if previous is not None:
                    if previous != current:
                        raise AgentApiError(
                            "QMT daily history contains conflicting duplicate asset dates"
                        )
                    continue
                observations[key] = current

        bars = tuple(bar for bar, _ in observations.values() if bar)
        statuses = tuple(status for _, status in observations.values())
        return DailyHistoryResult(bars=bars, statuses=statuses)


def _completed_history_range(start: str, end: str) -> tuple[date, date]:
    """Require a canonical ISO range of completed historical sessions within 31 days."""

    try:
        start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise ValueError("Backfill requires canonical ISO dates") from exc
    if (
        start_day.isoformat() != start
        or end_day.isoformat() != end
        or start_day > end_day
        or (end_day - start_day).days > 31
        or end_day >= datetime.now(UTC).astimezone(_CHINA_TIMEZONE).date()
    ):
        raise ValueError("Backfill requires up to 31 completed historical days")
    return start_day, end_day


def _parse_daily_index(value: object) -> date:
    """Parse only the source's leading YYYYMMDD token; reject malformed indexes."""

    raw = str(value)
    if len(raw) < 8 or not raw[:8].isdigit() or (raw[8:] and not raw[8:].isdigit()):
        raise AgentApiError("QMT daily history returned an invalid date index")
    try:
        return datetime.strptime(raw[:8], "%Y%m%d").date()
    except ValueError as exc:
        raise AgentApiError("QMT daily history returned an invalid date index") from exc


def _row_value(row: Any, field_name: str) -> object:
    """Read one SDK row field while treating absent columns as unknown."""

    try:
        return row[field_name]
    except (KeyError, IndexError, TypeError):
        return None


def _normalize_suspend_flag(value: object, *, asset_code: str, bar_date: date) -> int | None:
    """Normalize only exact native suspend flags; all other values remain unknown."""

    if value is None:
        return None
    normalized: int | None = None
    if isinstance(value, bool):
        normalized = None
    elif isinstance(value, numbers.Integral):
        normalized = int(value)
    elif isinstance(value, numbers.Real):
        number = float(value)
        if math.isfinite(number) and number.is_integer():
            normalized = int(number)
    if normalized not in (-1, 0, 1):
        _logger.warning(
            "QMT returned an unknown suspendFlag for %s on %s: %r",
            asset_code,
            bar_date.isoformat(),
            value,
        )
        return None
    return normalized


def _wire_number(value: object, *, positive: bool = False) -> str | None:
    """Narrow SDK scalars; absent/zero quote prices are missing, never fabricated."""
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0 or (positive and number == 0):
        return None
    return str(number)


class BridgeWorker:
    """Persist before upload and remove only after an exact durable receipt."""

    def __init__(self, state_dir: Path, transport: BridgeTransport, source: MarketSource) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        self.lease = sqlite3.connect(state_dir / "market-worker-lock.sqlite3", timeout=0)
        try:
            self.lease.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            self.lease.close()
            raise AgentApiError("A market worker already owns this state directory") from exc
        self.state_dir, self.transport, self.source = state_dir, transport, source
        self.db = sqlite3.connect(state_dir / "market-outbox.sqlite3")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )

    def close(self) -> None:
        """Close only market state; the trading state store is independent."""
        self.db.close()
        self.lease.close()

    def _flush(self) -> int:
        row = self.db.execute("SELECT id,payload FROM outbox ORDER BY rowid LIMIT 1").fetchone()
        if row is None:
            return 0
        payload = json.loads(row[1])
        if payload.get("kind") not in ("quote", "bar", "daily_status"):
            raise AgentApiError("Unknown market batch kind; retained for retry")
        receipt = self.transport.post("batches", payload)
        if (
            receipt.get("batch_id") != row[0]
            or receipt.get("outcome") not in ("success", "noop")
            or receipt.get("failed") != 0
            or receipt.get("succeeded") != len(payload["samples"])
        ):
            raise AgentApiError("Batch was not durably acknowledged; retained for retry")
        with self.db:
            self.db.execute("DELETE FROM outbox WHERE id=?", (row[0],))
        return int(receipt.get("stored", 0))

    def run_once(self, *, start: str = "", end: str = "") -> dict[str, object]:
        """Respect remote/local pause and flush bounded backlog before collecting more."""
        plan = self.transport.post("plan", {})
        poll = int(plan.get("poll_seconds", 10))
        if not 1 <= poll <= 60:
            raise AgentApiError("Invalid server polling budget")
        if plan.get("enabled") is not True or (self.state_dir / "PAUSE_MARKET").exists():
            return {
                "outcome": "blocked",
                "reason": "market_collection_paused",
                "poll_seconds": poll,
            }
        if self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]:
            stored = self._flush()
            return {
                "outcome": "success",
                "stored": stored,
                "poll_seconds": poll,
                "pending_batches": self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
            }
        assets = plan.get("assets")
        if (
            not isinstance(assets, list)
            or not 1 <= len(assets) <= 200
            or not all(isinstance(a, str) for a in assets)
        ):
            raise AgentApiError("Invalid server asset selection")
        asset_list = cast(list[str], assets)
        status_rows: list[DailyStatusSample] = []
        history_start = ""
        history_end = ""
        history_end_day: date | None = None
        if start:
            daily_history = getattr(self.source, "daily_history", None)
            if callable(daily_history):
                start_day, end_day = _completed_history_range(start, end)
                history_start, history_end = start_day.isoformat(), end_day.isoformat()
                history_end_day = end_day
                history = cast(DailyHistorySource, self.source).daily_history(
                    asset_list, history_start, history_end
                )
                rows = list(history.bars)
                status_rows = list(history.statuses)
            else:
                rows = self.source.bars(asset_list, start, end)
        else:
            rows = self.source.quotes(asset_list)
        if not rows and not status_rows:
            return {
                "outcome": "noop",
                "reason": "source_returned_no_observations",
                "poll_seconds": poll,
                "collected": True,
            }
        if len(rows) > 10000 or len(status_rows) > 10000:
            raise AgentApiError("Source result exceeds bounded collection budget")
        collected_at = datetime.now(UTC)
        if status_rows and history_end_day is not None:
            if history_end_day >= collected_at.astimezone(_CHINA_TIMEZONE).date():
                raise AgentApiError(
                    "QMT daily-status request end must precede China-local collection date"
                )
        collected = collected_at.isoformat()
        with self.db:
            groups: list[tuple[str, list[dict[str, Any]]]] = []
            if rows:
                kind = "bar" if start else "quote"
                groups.extend(
                    (kind, rows[offset : offset + 500]) for offset in range(0, len(rows), 500)
                )
            if status_rows:
                groups.extend(
                    (
                        "daily_status",
                        [dict(row) for row in status_rows[offset : offset + 500]],
                    )
                    for offset in range(0, len(status_rows), 500)
                )
            for kind, samples in groups:
                batch_id = str(uuid.uuid4())
                payload: dict[str, Any] = {
                    "batch_id": batch_id,
                    "kind": kind,
                    "collected_at": collected,
                    "samples": samples,
                }
                if kind == "daily_status":
                    payload.update(
                        {
                            "schema_version": "qmt-native-daily-status.v1",
                            "request_start": history_start,
                            "request_end": history_end,
                        }
                    )
                encoded = json.dumps(payload, allow_nan=False)
                if len(encoded) > 1_000_000:
                    raise AgentApiError("Source batch exceeds bounded payload budget")
                self.db.execute("INSERT INTO outbox VALUES (?,?)", (batch_id, encoded))
        return {
            "outcome": "success",
            "stored": self._flush(),
            "poll_seconds": poll,
            "collected": True,
            "pending_batches": self.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
        }
