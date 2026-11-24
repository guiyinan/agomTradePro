"""Unitized shadow valuation from complete owner-certified day records and exact closing marks."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from io import BytesIO, StringIO
from zipfile import BadZipFile, ZipFile


class BenchmarkDayUnavailable(ValueError):
    """The input cannot establish a complete comparable account and benchmark close."""


@dataclass(frozen=True, slots=True)
class DayLedger:
    """One independently retained source statement normalized by the account reconciliation owner."""

    source_account_hash: str
    covered_from: datetime
    cutoff: datetime
    currency: str
    opening_live_equity: Decimal
    closing_live_equity: Decimal
    cash_available: Decimal
    cash_frozen: Decimal
    position_market_value: Decimal
    positions: dict[str, tuple[Decimal, Decimal, Decimal]]
    external_flow_count: int
    external_flow: Decimal
    interest: Decimal
    costs: Decimal
    # One row per constituent explicitly covers both events and FX, including a confirmed no-action.
    instrument_terms: dict[str, tuple[Decimal, Decimal, Decimal]]
    economic_event_ids: tuple[str, ...]


def _number(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise BenchmarkDayUnavailable("invalid decimal in day statement") from exc
    if not result.is_finite() or len(result.as_tuple().digits) > 32 or abs(result.adjusted()) > 32:
        raise BenchmarkDayUnavailable("day statement decimal is outside its supported range")
    return result


def _time(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if instant.utcoffset() is None:
        raise BenchmarkDayUnavailable("day statement requires timezone-aware clocks")
    return instant


def read_day_ledger(raw: bytes) -> DayLedger:
    """Read a closed, bounded CSV statement with explicit coverage and once-only line identities.

    Header: kind,ref,at,asset,currency,value. Number fields are never inferred from missing rows.
    The custody header identifies the physical account hash. Unitization supports flows effective
    at the verified closing fixing; an earlier flow requires intraday marks and is rejected.
    """
    if not raw or len(raw) > 2_000_000:
        raise BenchmarkDayUnavailable("missing or oversized original day ledger")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            archive_entries = archive.infolist()
            if (
                len(archive_entries) != len({e.filename for e in archive_entries})
                or {e.filename for e in archive_entries}
                not in (
                    {"day.csv", "source.csv"},
                    {"day.csv", "source.csv", "action-coverage.json"},
                )
                or any(
                    e.file_size <= 0 or e.file_size > 2_000_000 or e.flag_bits & 1
                    for e in archive_entries
                )
            ):
                raise BenchmarkDayUnavailable("expected bounded day and original custody documents")
            source = archive.read("source.csv")
            normalized = archive.read("day.csv").decode("utf-8-sig")
    except (BadZipFile, UnicodeError, NotImplementedError, RuntimeError) as error:
        raise BenchmarkDayUnavailable("invalid day evidence archive") from error
    try:
        return _read_csv_ledger(source, normalized)
    except (csv.Error, UnicodeError) as exc:
        raise BenchmarkDayUnavailable("malformed custody source or normalized CSV") from exc


def _read_csv_ledger(source: bytes, normalized: str) -> DayLedger:
    source_hash = hashlib.sha256(source).hexdigest()
    source_lines = source.decode("utf-8-sig").splitlines()
    reader = csv.DictReader(StringIO(normalized), strict=True)
    if reader.fieldnames != ["kind", "ref", "at", "asset", "currency", "value"]:
        raise BenchmarkDayUnavailable("unrecognized day ledger schema")
    single: dict[str, tuple[str, datetime, str, str, Decimal]] = {}
    terms: dict[str, dict[str, Decimal]] = {}
    flows: list[tuple[datetime, Decimal]] = []
    ids: set[str] = set()
    economic_events: set[str] = set()
    required = {
        "closing_cash_available",
        "closing_cash_frozen",
        "closing_position_market_value",
        "closing_position_count",
        "opening_equity",
        "closing_equity",
        "external_flow_count",
        "corporate_action_coverage",
        "shadow_interest",
        "shadow_costs",
        "fx_coverage",
    }
    dates: list[datetime] = []
    position_terms: dict[str, dict[str, Decimal]] = {}
    term_dates: list[datetime] = []
    all_currencies: set[str] = set()
    for row in reader:
        if None in row or any(not isinstance(v, str) for v in row.values()):
            raise BenchmarkDayUnavailable("malformed original day ledger row")
        kind, ref, at_raw, asset, currency, amount = (row[key] for key in reader.fieldnames)
        if not ref or ref in ids:
            raise BenchmarkDayUnavailable("statement line identity is missing or repeated")
        digest, sep, line_no = ref.partition("#")
        if (
            digest != source_hash
            or sep != "#"
            or not line_no.isascii()
            or not line_no.isdecimal()
            or len(line_no) > 8
            or str(int(line_no)) != line_no
            or not 1 <= int(line_no) <= len(source_lines)
        ):
            raise BenchmarkDayUnavailable("line is not pinned to the retained custody document")
        # The supported normalized custody export contains the exact economics and effective time.
        source_fields = next(csv.reader([source_lines[int(line_no) - 1]], strict=True))
        if len(source_fields) != 6 or source_fields[1:] != [
            kind,
            at_raw,
            asset,
            currency,
            amount,
        ]:
            raise BenchmarkDayUnavailable(
                "normalized economic fact differs from the retained source line"
            )
        ids.add(ref)
        at, value = _time(at_raw), _number(amount)
        if (
            kind
            in {
                "deposit",
                "withdrawal",
                "distribution_per_open_share",
                "shadow_interest",
                "shadow_costs",
            }
            and value != 0
        ) or (kind == "split_ratio" and value != 1):
            event_key = source_fields[0]
            if not event_key or len(event_key) > 192 or event_key in economic_events:
                raise BenchmarkDayUnavailable(
                    "missing or repeated original economic event identity"
                )
            economic_events.add(event_key)
        dates.append(at)
        all_currencies.add(currency)
        if kind in required:
            if kind in single:
                raise BenchmarkDayUnavailable("duplicate day coverage header")
            single[kind] = (ref, at, asset, currency, value)
        elif kind in {"deposit", "withdrawal"}:
            if value <= 0:
                raise BenchmarkDayUnavailable("cash flow must have a positive magnitude")
            flows.append((at, value if kind == "deposit" else -value))
        elif kind in {"position_quantity", "position_available", "position_value"}:
            if (
                not asset
                or asset.strip().upper() != asset
                or kind in position_terms.setdefault(asset, {})
                or value < 0
            ):
                raise BenchmarkDayUnavailable("ambiguous custody position or negative quantity")
            position_terms[asset][kind] = value
            term_dates.append(at)
        elif kind in {"split_ratio", "distribution_per_open_share", "close_fx"}:
            if not asset or kind in terms.setdefault(asset, {}):
                raise BenchmarkDayUnavailable("ambiguous constituent statement row")
            terms[asset][kind] = value
            term_dates.append(at)
        else:
            raise BenchmarkDayUnavailable(
                "unsupported economic event requires owner reconciliation"
            )
    if len(ids) != len(source_lines):
        raise BenchmarkDayUnavailable("original custody lines were omitted")
    if set(single) != required or len(all_currencies) != 1:
        raise BenchmarkDayUnavailable("day ledger has missing coverage or mixed base currency")
    opening, closing = single["opening_equity"], single["closing_equity"]
    if (
        len(opening[2]) != 64
        or any(c not in "0123456789abcdef" for c in opening[2])
        or closing[2] != opening[2]
        or opening[1] > closing[1]
        or min(opening[4], closing[4]) <= 0
        or any(at < opening[1] or at > closing[1] for at in dates)
        or any(
            header[1] != closing[1] for name, header in single.items() if name != "opening_equity"
        )
        or any(at != closing[1] for at in term_dates)
        or any(at != closing[1] for at, _ in flows)
    ):
        raise BenchmarkDayUnavailable(
            "inconsistent custody account, coverage window, or unpriced intraday flow"
        )
    if (
        single["external_flow_count"][4] != len(flows)
        or single["corporate_action_coverage"][4] != len(terms)
        or single["fx_coverage"][4] != len(terms)
        or single["shadow_costs"][4] < 0
    ):
        raise BenchmarkDayUnavailable(
            "external, corporate-action, FX, or cost coverage is incomplete"
        )
    positions: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    for code, counts in position_terms.items():
        if (
            set(counts) != {"position_quantity", "position_available", "position_value"}
            or counts["position_quantity"] < counts["position_available"]
        ):
            raise BenchmarkDayUnavailable("missing or invalid custody position quantities")
        positions[code] = (
            counts["position_quantity"],
            counts["position_available"],
            counts["position_value"],
        )
    cash, frozen, holdings = (
        single[k][4]
        for k in ("closing_cash_available", "closing_cash_frozen", "closing_position_market_value")
    )
    if (
        single["closing_position_count"][4] != len(positions)
        or min(cash, frozen, holdings) < 0
        or cash + frozen + holdings != closing[4]
        or sum((p[2] for p in positions.values()), Decimal(0)) != holdings
        or any(q == 0 and value for q, _, value in positions.values())
    ):
        raise BenchmarkDayUnavailable("incomplete securities positions or unbalanced custody close")
    components: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    for code, entries in terms.items():
        if set(entries) != {"split_ratio", "distribution_per_open_share", "close_fx"}:
            raise BenchmarkDayUnavailable(
                "valuation requires complete per-asset split, distribution and FX coverage"
            )
        split, income, fx = (
            entries[k] for k in ("split_ratio", "distribution_per_open_share", "close_fx")
        )
        if split <= 0 or income < 0 or fx <= 0:
            raise BenchmarkDayUnavailable("invalid constituent economics")
        components[code] = (split, income, fx)
    return DayLedger(
        opening[2],
        opening[1],
        closing[1],
        opening[3],
        opening[4],
        closing[4],
        cash,
        frozen,
        holdings,
        positions,
        len(flows),
        sum((amount for _, amount in flows), Decimal(0)),
        single["shadow_interest"][4],
        single["shadow_costs"][4],
        components,
        tuple(sorted(economic_events)),
    )


@dataclass(frozen=True, slots=True)
class ShadowBalance:
    """Closing unit count, post-flow holdings, cash, and net asset value per unit."""

    units: Decimal
    cash: Decimal
    quantities: dict[str, Decimal]
    unit_nav: Decimal
    total_value: Decimal


def close_single_stock_day(
    *,
    ledger: DayLedger,
    mark: Decimal,
    code: str,
    prior: ShadowBalance | None,
    rate: Decimal,
    rounding_increment: Decimal,
) -> ShadowBalance:
    """Value a fully invested home-currency stock proxy with the explicitly approved commission."""
    from decimal import ROUND_HALF_UP

    if (
        set(ledger.instrument_terms) != {code}
        or ledger.instrument_terms[code] != (Decimal(1), Decimal(0), Decimal(1))
        or ledger.interest
        or ledger.external_flow_count > 1
        or (prior is None and ledger.external_flow_count)
    ):
        raise BenchmarkDayUnavailable("unsupported action, interest, FX or simultaneous cash flows")
    if prior is not None and (prior.cash != 0 or set(prior.quantities) != {code}):
        raise BenchmarkDayUnavailable("prior shadow is outside the single-stock mandate")
    with localcontext() as ctx:
        ctx.prec = 42
        if prior is None:
            if (
                ledger.covered_from != ledger.cutoff
                or ledger.opening_live_equity != ledger.closing_live_equity
            ):
                raise BenchmarkDayUnavailable("inception needs a single verified live-equity mark")
            initial = ledger.opening_live_equity
            traded = initial - ledger.costs
            units = initial
            total = traded
        else:
            available = prior.quantities[code] * mark - ledger.costs
            if available <= 0 or prior.units <= 0:
                raise BenchmarkDayUnavailable("costs exhaust the shadow book")
            traded = ledger.external_flow - ledger.costs
            total = available + ledger.external_flow
            units = prior.units + ledger.external_flow * prior.units / available
        # The fee base is the absolute trade in the fully invested shadow security.
        # No trade on a no-flow carry day can create an expense by itself.
        fee = ((abs(traded) * rate) / rounding_increment).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        ) * rounding_increment
        if (
            ledger.costs != fee
            or total <= 0
            or units <= 0
            or mark <= 0
            or (prior is not None and ledger.external_flow == 0 and ledger.costs != 0)
        ):
            raise BenchmarkDayUnavailable(
                "shadow commission differs from governed charge or balances are exhausted"
            )
        return ShadowBalance(units, Decimal(0), {code: total / mark}, total / units, total)
