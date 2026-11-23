"""Reconcile unadjusted historical index points from the same market session."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext


@dataclass(frozen=True)
class IndexCloseSeries:
    """Original values for one index in points; places is a known rounding contract."""

    index_code: str
    source: str
    decimal_places: int | None
    values: Mapping[date, Decimal]


@dataclass(frozen=True)
class MergedIndexClose:
    """One selected original observation and every source value used to choose it."""

    session: date
    close: Decimal
    source: str
    reason: str
    observations: tuple[tuple[str, Decimal], ...]


def _rounded(value: Decimal, places: int) -> Decimal:
    with localcontext() as context:
        context.prec = max(len(value.as_tuple().digits), value.adjusted() + places + 2, 1)
        return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _select_source(
    available: list[tuple[IndexCloseSeries, Decimal]], day: date, tolerance: Decimal
) -> tuple[IndexCloseSeries, Decimal]:
    # Stable sorting keeps configured priority when declared scales tie.
    by_precision = sorted(
        available,
        key=lambda item: (item[0].decimal_places if item[0].decimal_places is not None else -1),
        reverse=True,
    )
    for series, close in by_precision:
        if all(
            close == other
            or (
                peer.decimal_places is not None
                and abs(close - other) <= min(close, other) * tolerance
                and _rounded(close, peer.decimal_places) == other
            )
            for peer, other in available
        ):
            return series, close
    details = ", ".join(f"{s.source}={v}" for s, v in available)
    raise ValueError(f"Index close conflict for {available[0][0].index_code} on {day}: {details}")


def merge_index_closes(
    sessions: tuple[date, ...],
    sources: tuple[IndexCloseSeries, ...],
    *,
    relative_tolerance: Decimal = Decimal("0.01"),
) -> tuple[MergedIndexClose, ...]:
    """Select an original close compatible with all peers on each requested session.

    Declared precision, then input order, settles exact ties. Only a source with a known decimal-place
    contract can explain a difference by rounding. A source switch across
    disjoint histories requires overlap evidence within the requested window.
    """
    if not sessions or sessions != tuple(sorted(set(sessions))) or not sources:
        raise ValueError("Expected ordered unique sessions and at least one source")
    if not relative_tolerance.is_finite() or not 0 <= relative_tolerance <= 1:
        raise ValueError("Invalid source tolerance")
    if len({s.index_code for s in sources}) != 1 or not sources[0].index_code.strip():
        raise ValueError("Expected one index identity")
    if len({s.source for s in sources}) != len(sources) or any(
        not s.source.strip() for s in sources
    ):
        raise ValueError("Expected distinct source identities")
    for s in sources:
        places = s.decimal_places
        if places is not None and (type(places) is not int or not 0 <= places <= 28):
            raise ValueError("Invalid source decimal precision")
    result: list[MergedIndexClose] = []
    # Groups of contributing sources joined by at least one verified common close.
    connected: list[set[str]] = []
    for day in sessions:
        available = [(s, s.values[day]) for s in sources if day in s.values]
        if not available:
            raise ValueError(f"{sources[0].index_code} missing close on {day}")
        for series, value in available:
            if (
                not value.is_finite()
                or value <= 0
                or abs(value.adjusted()) > 128
                or len(value.as_tuple().digits) > 128
            ):
                raise ValueError(f"Invalid close for {series.source} on {day}")
            places = series.decimal_places
            if places is not None and _rounded(value, places) != value:
                raise ValueError(f"Close exceeds source precision for {series.source} on {day}")
        selected, close = _select_source(available, day, relative_tolerance)
        observations = tuple((s.source, value) for s, value in available)
        names = {s for s, _ in observations}
        merged = set(names)
        for group in connected:
            if names & group:
                merged.update(group)
        connected = [group for group in connected if group.isdisjoint(names)] + [merged]
        reason = "single_source" if len(available) == 1 else "identical"
        if any(v != close for _, v in observations):
            reason = "rounding_equivalent"
        result.append(MergedIndexClose(day, close, selected.source, reason, observations))
    if len(connected) > 1:
        raise ValueError("No verified source overlap in requested sessions")
    return tuple(result)
