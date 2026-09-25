"""Offline negative-case replay of retained responses through production parsers."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import cast

from apps.data_center.application.market_provider_rehearsal import rehearsal_digest
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.infrastructure.tushare_client import TushareResponseEvidence

from .rehearsal_response_store import RehearsalResponseContext, parse_validate_tushare_response
from .tushare_replay_parser import (
    map_tushare_daily_basic_row,
    parse_tushare_daily_quote_rows,
)


@dataclass(frozen=True)
class ReplayResponse:
    """Exact retained bytes and their captured, immutable association and receipt clock."""

    context: RehearsalResponseContext
    body: bytes
    body_sha256: str
    finished_at: datetime
    normalization_completed_at: datetime | None = None


@dataclass(frozen=True)
class ReplayUnitContract:
    """One explicit frozen source-unit contract; no inferred business default."""

    field: str
    raw_unit: str
    canonical_unit: str
    multiplier: float

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.field, self.raw_unit, self.canonical_unit)
        ):
            raise ValueError("REHEARSAL_REPLAY_UNIT_CONTRACT_MISSING")
        if (
            isinstance(self.multiplier, bool)
            or not isinstance(self.multiplier, (int, float))
            or not math.isfinite(self.multiplier)
            or self.multiplier <= 0
        ):
            raise ValueError("REHEARSAL_REPLAY_UNIT_CONTRACT_INVALID")


def verify_response_digest(body: bytes, expected: str) -> None:
    """Reject later file/fact replacement instead of following mutable latest data."""
    if hashlib.sha256(body).hexdigest() != expected:
        raise ValueError("REHEARSAL_RESPONSE_DIGEST_MISMATCH")


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("REHEARSAL_REPLAY_NUMBER_INVALID")
    return float(value)


def verify_unit_pair(raw: object, canonical: object, multiplier: float) -> None:
    """Compare actual raw/canonical observations using an explicit unit contract."""
    raw_number, canonical_number = _number(raw), _number(canonical)
    if raw_number is None or canonical_number is None:
        raise ValueError("REHEARSAL_REPLAY_UNIT_WITNESS_MISSING")
    if raw_number < 0 or canonical_number < 0:
        raise ValueError("REHEARSAL_REPLAY_NUMBER_INVALID")
    expected = Decimal(str(raw_number)) * Decimal(str(multiplier))
    if not math.isclose(float(expected), canonical_number, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("REHEARSAL_REPLAY_UNIT_MISMATCH")


def _selected_rows(
    rows: Sequence[Mapping[str, object]], sample: tuple[str, ...], target_date: date
) -> list[Mapping[str, object]]:
    selected = [
        row
        for row in rows
        if row.get("ts_code") in sample and row.get("trade_date") == target_date.strftime("%Y%m%d")
    ]
    counts = Counter(str(row["ts_code"]) for row in selected)
    if any(counts[code] == 0 for code in sample):
        raise ValueError("REHEARSAL_REPLAY_ASSET_MISSING")
    if any(counts[code] != 1 for code in sample):
        raise ValueError("REHEARSAL_REPLAY_DUPLICATE_ASSET")
    return selected


def _replay_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    response_by_asset: Mapping[str, ReplayResponse],
    context: RehearsalResponseContext,
    unit_contracts: Mapping[str, ReplayUnitContract],
) -> list[dict[str, object]]:
    target_date = date.fromisoformat(context.target_trade_date)
    selected = _selected_rows(rows, context.sample_codes, target_date)
    observations: list[dict[str, object]] = []
    for row in selected:
        asset = str(row["ts_code"])
        response = response_by_asset[asset]
        transport_finished = response.finished_at
        finished = response.normalization_completed_at or transport_finished
        observed = cn_market_session_close_utc(target_date)
        if finished.utcoffset() is None or finished < observed:
            raise ValueError("REHEARSAL_REPLAY_SOURCE_TIME_INVALID")
        units: list[dict[str, object]] = []
        if context.dataset == "equity.quote.snapshot":
            quote = parse_tushare_daily_quote_rows(
                [row],
                requested_asset_code=asset,
                source=context.provider_source,
                fetched_at=finished,
                target_date=target_date,
            )
            if quote is None or quote.observed_at != observed:
                raise ValueError("REHEARSAL_REPLAY_SOURCE_TIME_MISMATCH")
            for field, raw, canonical in (
                ("close", row.get("close"), float(quote.price)),
                ("vol", row.get("vol"), quote.volume),
                (
                    "amount",
                    row.get("amount"),
                    float(quote.amount) if quote.amount is not None else None,
                ),
            ):
                contract = unit_contracts[field]
                verify_unit_pair(raw, canonical, contract.multiplier)
                units.append(
                    {
                        "field": field,
                        "raw": raw,
                        "canonical": canonical,
                        "raw_unit": contract.raw_unit,
                        "canonical_unit": contract.canonical_unit,
                        "multiplier": contract.multiplier,
                    }
                )
        else:
            fact = map_tushare_daily_basic_row(
                row,
                asset_code=asset,
                source=context.provider_source,
                provider_extra={},
                response_completed_at=finished,
                response_evidence=TushareResponseEvidence(response.body_sha256, finished),
            )
            if (
                fact is None
                or fact.observed_at != observed
                or fact.available_at != finished
                or fact.raw_payload_hash != response.body_sha256
            ):
                raise ValueError("REHEARSAL_REPLAY_SOURCE_TIME_MISMATCH")
            multiplier = _number(fact.extra.get("market_cap_multiplier_to_storage"))
            if multiplier is None or multiplier <= 0:
                raise ValueError("REHEARSAL_REPLAY_UNIT_CONTRACT_MISSING")
            for field, valuation_canonical in (
                ("total_mv", fact.market_cap),
                ("circ_mv", fact.float_market_cap),
            ):
                contract = unit_contracts[field]
                if (
                    contract.multiplier != multiplier
                    or contract.raw_unit != fact.extra.get("market_cap_original_unit")
                    or contract.canonical_unit != fact.extra.get("market_cap_canonical_unit")
                ):
                    raise ValueError("REHEARSAL_REPLAY_UNIT_CONTRACT_MISMATCH")
                verify_unit_pair(row.get(field), valuation_canonical, contract.multiplier)
                units.append(
                    {
                        "field": field,
                        "raw": row.get(field),
                        "canonical": valuation_canonical,
                        "raw_unit": fact.extra.get("market_cap_original_unit"),
                        "canonical_unit": fact.extra.get("market_cap_canonical_unit"),
                        "multiplier": multiplier,
                    }
                )
        observations.append(
            {
                "asset_code": asset,
                "source_observed_at": observed.isoformat(),
                "transport_received_at": transport_finished.isoformat(),
                "normalization_completed_at": finished.isoformat(),
                "response_completed_at": finished.isoformat(),
                "body_sha256": response.body_sha256,
                "units": units,
            }
        )
    return sorted(observations, key=lambda row: str(row["asset_code"]))


def replay_retained_dataset(
    responses: Sequence[ReplayResponse], unit_contracts: Sequence[ReplayUnitContract]
) -> dict[str, object]:
    """Exercise seven explicit cases; synthetic mutations never become provider evidence.

    The subsequent-update case verifies immutable response/fact lineage only.
    PostgreSQL publication immutability remains a separate release gate.
    """
    if not responses:
        raise ValueError("REHEARSAL_REAL_RESPONSE_MISSING")
    context = responses[0].context
    units_by_field = {contract.field: contract for contract in unit_contracts}
    required_fields = (
        {"close", "vol", "amount"}
        if context.dataset == "equity.quote.snapshot"
        else {"total_mv", "circ_mv"}
    )
    if len(units_by_field) != len(unit_contracts) or set(units_by_field) != required_fields:
        raise ValueError("REHEARSAL_REPLAY_UNIT_CONTRACT_MISSING")
    rows: list[Mapping[str, object]] = []
    response_by_asset: dict[str, ReplayResponse] = {}
    for response in responses:
        if response.context != context:
            raise ValueError("REHEARSAL_REPLAY_CONTEXT_MISMATCH")
        verify_response_digest(response.body, response.body_sha256)
        batch = parse_validate_tushare_response(response.body, context)
        rows.extend(batch)
        for row in batch:
            if row.get("ts_code") in context.sample_codes and row.get(
                "trade_date"
            ) == context.target_trade_date.replace("-", ""):
                response_by_asset[str(row["ts_code"])] = response
    baseline = _replay_rows(
        rows, response_by_asset=response_by_asset, context=context, unit_contracts=units_by_field
    )
    cases: list[dict[str, object]] = [
        {
            "case": "valid",
            "origin": "retained_provider_bytes",
            "outcome": "success",
            "facts_sha256": rehearsal_digest(baseline),
        }
    ]

    def rejected(name: str, operation: Callable[[], object], expected: str) -> None:
        try:
            operation()
        except ValueError as exc:
            if str(exc) != expected:
                raise ValueError("REHEARSAL_NEGATIVE_CASE_WRONG_FAILURE") from exc
            cases.append(
                {
                    "case": name,
                    "origin": "offline_mutation",
                    "outcome": "rejected",
                    "error_code": expected,
                }
            )
            return
        raise ValueError("REHEARSAL_NEGATIVE_CASE_ACCEPTED")

    first_asset = context.sample_codes[0]
    selected = _selected_rows(
        rows, context.sample_codes, date.fromisoformat(context.target_trade_date)
    )
    selected_first = next(row for row in selected if row["ts_code"] == first_asset)

    def run(changed: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
        return _replay_rows(
            changed,
            response_by_asset=response_by_asset,
            context=context,
            unit_contracts=units_by_field,
        )

    rejected(
        "missing",
        lambda: run([row for row in rows if row.get("ts_code") != first_asset]),
        "REHEARSAL_REPLAY_ASSET_MISSING",
    )
    rejected("duplicate", lambda: run([*rows, selected_first]), "REHEARSAL_REPLAY_DUPLICATE_ASSET")
    old_date = (date.fromisoformat(context.target_trade_date) - timedelta(days=1)).strftime(
        "%Y%m%d"
    )
    rejected(
        "stale",
        lambda: run(
            [
                {**row, "trade_date": old_date} if row.get("ts_code") == first_asset else row
                for row in rows
            ]
        ),
        "REHEARSAL_REPLAY_ASSET_MISSING",
    )
    # Use the same digest boundary as input loading; partial bytes cannot be promoted.
    first_response = responses[0]
    rejected(
        "truncated",
        lambda: verify_response_digest(first_response.body[:-1], first_response.body_sha256),
        "REHEARSAL_RESPONSE_DIGEST_MISMATCH",
    )
    unit_rows = [
        cast(dict[str, object], unit)
        for item in baseline
        for unit in cast(list[object], item["units"])
    ]
    witness = next(
        (
            unit
            for unit in unit_rows
            if isinstance(unit.get("canonical"), (int, float)) and unit["canonical"] != 0
        ),
        None,
    )
    if witness is None:
        raise ValueError("REHEARSAL_REPLAY_UNIT_WITNESS_MISSING")
    canonical_number = _number(witness["canonical"])
    multiplier_number = _number(witness["multiplier"])
    assert canonical_number is not None and multiplier_number is not None
    rejected(
        "unit_error",
        lambda: verify_unit_pair(witness["raw"], canonical_number * 100.0, multiplier_number),
        "REHEARSAL_REPLAY_UNIT_MISMATCH",
    )
    # Derive a later changed fact from an actual selected row; never write it as raw evidence.
    later_fact = dict(selected_first)
    changed_field = "close" if context.dataset == "equity.quote.snapshot" else "total_mv"
    original_value = _number(later_fact.get(changed_field))
    later_fact[changed_field] = (original_value if original_value is not None else 0.0) + 1.0
    replacement = json.dumps(
        {"code": 0, "data": {"fields": list(later_fact), "items": [list(later_fact.values())]}},
        separators=(",", ":"),
    ).encode()
    rejected(
        "subsequent_fact_update",
        lambda: verify_response_digest(replacement, response_by_asset[first_asset].body_sha256),
        "REHEARSAL_RESPONSE_DIGEST_MISMATCH",
    )
    if baseline != run(rows):
        raise ValueError("REHEARSAL_REPLAY_BASELINE_CHANGED")
    return {
        "outcome": "success",
        "dataset": context.dataset,
        "sampled_assets": list(context.sample_codes),
        "observations": baseline,
        "case_results": cases,
        "replay_cases": [item["case"] for item in cases],
        "units_verified": True,
        "source_time_verified": True,
        "subsequent_update_scope": "immutable_response_lineage_only",
        "publication_immutability_verified": False,
    }
