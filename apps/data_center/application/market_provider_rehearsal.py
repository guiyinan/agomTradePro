"""Assess real market-provider probes without persisting business facts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

from apps.data_center.domain.entities import QuoteSnapshot, ValuationFact


def select_rehearsal_sample(codes: Sequence[str], size: int = 50) -> tuple[str, ...]:
    """Select stable hash-ranked assets, representing every present exchange suffix."""
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 200:
        raise ValueError("rehearsal size must be an integer between 1 and 200")
    universe = sorted(set(codes))
    if not universe or any(not code or code != code.strip() for code in universe):
        raise ValueError("rehearsal requires a nonempty canonical universe")
    ranked = sorted(universe, key=lambda code: hashlib.sha256(code.encode()).hexdigest())
    groups: dict[str, str] = {}
    for code in ranked:
        groups.setdefault(code.rsplit(".", 1)[-1], code)
    if len(groups) > size:
        raise ValueError("sample size cannot represent all present exchange groups")
    selected = set(groups.values())
    for code in ranked:
        if len(selected) >= min(size, len(universe)):
            break
        selected.add(code)
    return tuple(sorted(selected))


def rehearsal_digest(value: object) -> str:
    """Hash a normalized JSON observation without depending on dictionary order."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def assess_market_probe(
    *,
    dataset: str,
    facts: Sequence[QuoteSnapshot] | Sequence[ValuationFact],
    sample: tuple[str, ...],
    target_date: date,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, object]:
    """Validate exact scope and source/receipt clocks; never claim a publication."""
    if dataset not in {"equity.quote.snapshot", "equity.valuation.fact"}:
        raise ValueError("unsupported market rehearsal dataset")
    if not sample or len(sample) != len(set(sample)):
        raise ValueError("sample must be nonempty and unique")
    if any(value.utcoffset() is None for value in (started_at, finished_at)):
        raise ValueError("rehearsal clocks must be timezone-aware")
    if finished_at < started_at:
        raise ValueError("rehearsal clock moved backwards")
    counts = Counter(fact.asset_code for fact in facts)
    issues: list[dict[str, str]] = []
    accepted: set[str] = set()
    rows: list[dict[str, object]] = []
    for code in sorted(set(sample) - set(counts)):
        issues.append({"asset_code": code, "code": "REHEARSAL_ASSET_MISSING"})
    for fact in facts:
        code = fact.asset_code
        failures: list[str] = []
        if code not in sample:
            failures.append("REHEARSAL_UNEXPECTED_ASSET")
        if counts[code] != 1:
            failures.append("REHEARSAL_DUPLICATE_ASSET")
        if not fact.source:
            failures.append("REHEARSAL_SOURCE_MISSING")
        is_quote = isinstance(fact, QuoteSnapshot)
        if is_quote != (dataset == "equity.quote.snapshot"):
            failures.append("REHEARSAL_DATASET_TYPE_MISMATCH")
        observed = fact.snapshot_at if isinstance(fact, QuoteSnapshot) else fact.observed_at
        fetched = fact.fetched_at
        if observed is None or observed.utcoffset() is None:
            failures.append("REHEARSAL_SOURCE_TIME_MISSING")
        elif observed.astimezone(ZoneInfo("Asia/Shanghai")).date() != target_date:
            failures.append("REHEARSAL_SOURCE_DATE_MISMATCH")
        if fetched is None or fetched.utcoffset() is None:
            failures.append("REHEARSAL_RECEIPT_TIME_MISSING")
        elif not started_at <= fetched <= finished_at:
            failures.append("REHEARSAL_RECEIPT_OUTSIDE_CALL")
        elif observed is not None and observed > fetched:
            failures.append("REHEARSAL_SOURCE_TIME_FUTURE")
        row: dict[str, object] = {
            "asset_code": code,
            "source": fact.source,
            "observed_at": observed.isoformat() if observed else None,
            "fetched_at": fetched.isoformat() if fetched else None,
        }
        if isinstance(fact, QuoteSnapshot):
            row["current_price"] = fact.current_price
        else:
            if fact.val_date != target_date:
                failures.append("REHEARSAL_SOURCE_DATE_MISMATCH")
            if not fact.raw_payload_hash or not fact.source_record_id or fact.available_at is None:
                failures.append("REHEARSAL_SOURCE_EVIDENCE_MISSING")
            if fact.available_at is not None and (fetched is None or fact.available_at > fetched):
                failures.append("REHEARSAL_AVAILABILITY_FUTURE")
            row.update(
                {
                    "val_date": fact.val_date.isoformat(),
                    "pe_ttm": fact.pe_ttm,
                    "pb": fact.pb,
                    "market_cap": fact.market_cap,
                    "float_market_cap": fact.float_market_cap,
                    "available_at": fact.available_at.isoformat() if fact.available_at else None,
                    "raw_payload_hash": fact.raw_payload_hash,
                }
            )
        issues.extend({"asset_code": code, "code": reason} for reason in sorted(set(failures)))
        if not failures:
            accepted.add(code)
        rows.append(row)
    return {
        "dataset": dataset,
        "outcome": "blocked" if issues else "success",
        "requested": len(sample),
        "succeeded": len(accepted),
        "failed": len(sample) - len(accepted),
        "stored": 0,
        "count_unit": "sampled_asset",
        "publication_updated": False,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "target_trade_date": target_date.isoformat(),
        "issues": issues,
        "facts": rows,
        "normalized_facts_sha256": rehearsal_digest(rows),
    }
