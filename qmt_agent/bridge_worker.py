"""Isolated, bounded market collection worker for the integrated QMT Agent."""

from __future__ import annotations

import importlib
import json
import sqlite3
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol, cast

from .api_client import AgentApiError


class BridgeTransport(Protocol):
    """Minimal transport used by the durable market worker."""

    def post(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class MarketSource(Protocol):
    """Source observation adapter, independent of trading callbacks and queues."""

    def quotes(self, assets: list[str]) -> list[dict[str, Any]]: ...
    def bars(self, assets: list[str], start: str, end: str) -> list[dict[str, Any]]: ...


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
        """Download a bounded historical slice and retain unadjusted source dates."""
        start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
        if start_day > end_day or (end_day - start_day).days > 31 or end_day >= date.today():
            raise ValueError("Backfill requires up to 31 completed historical days")
        rows: list[dict[str, Any]] = []
        for asset in assets:
            self.sdk.download_history_data(
                asset,
                period="1d",
                start_time=start_day.strftime("%Y%m%d"),
                end_time=end_day.strftime("%Y%m%d"),
            )
            data = self.sdk.get_market_data_ex(
                [],
                [asset],
                period="1d",
                start_time=start_day.strftime("%Y%m%d"),
                end_time=end_day.strftime("%Y%m%d"),
                dividend_type="none",
                fill_data=False,
            )
            frame = data.get(asset)
            if frame is None:
                continue
            for index, bar in frame.iterrows():
                prices = {
                    key: _wire_number(bar[key], positive=True)
                    for key in ("open", "high", "low", "close")
                }
                if any(value is None for value in prices.values()):
                    continue
                day = datetime.strptime(str(index)[:8], "%Y%m%d").date()
                # Daily source date, never request time. Midnight is only a date anchor.
                observed = datetime(day.year, day.month, day.day, tzinfo=UTC)
                rows.append(
                    {
                        "asset_code": asset,
                        "bar_date": day.isoformat(),
                        "observed_at": observed.isoformat(),
                        "price": prices["close"],
                        "open": prices["open"],
                        "high": prices["high"],
                        "low": prices["low"],
                        "volume": _wire_number(bar["volume"]),
                        "amount": _wire_number(bar["amount"]),
                    }
                )
        return rows


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
        rows = (
            self.source.bars(cast(list[str], assets), start, end)
            if start
            else self.source.quotes(cast(list[str], assets))
        )
        if not rows:
            return {
                "outcome": "noop",
                "reason": "source_returned_no_observations",
                "poll_seconds": poll,
                "collected": True,
            }
        if len(rows) > 10000:
            raise AgentApiError("Source result exceeds bounded collection budget")
        collected = datetime.now(UTC).isoformat()
        with self.db:
            for offset in range(0, len(rows), 500):
                batch_id = str(uuid.uuid4())
                payload = {
                    "batch_id": batch_id,
                    "kind": "bar" if start else "quote",
                    "collected_at": collected,
                    "samples": rows[offset : offset + 500],
                }
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
