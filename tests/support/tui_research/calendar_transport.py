"""Offline synthetic calendar transport for a future real-owner test.

This test fixture does not select dates, infer
weekdays, call a provider SDK, alter production composition, or represent an
ExchangeCalendarFact.  The caller must supply the complete bounded sessions,
coverage, observation clock, and raw synthetic response bytes explicitly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final, NoReturn

from apps.data_center.application.model_market_data import (
    ModelMarketDataService,
    ModelMarketRoute,
)
from apps.data_center.domain.model_market_data import (
    ModelDailyBar,
    ModelMarketDataPort,
    TradingCalendarEvidence,
)
from core.exceptions import DataFetchError

SYNTHETIC_CALENDAR_SOURCE: Final[str] = "synthetic fixture"
SYNTHETIC_CALENDAR_ROUTE: Final[str] = "synthetic-calendar-fixture"
_CALENDAR_JSON_KEYS: Final[frozenset[str]] = frozenset(
    {
        "coverage_start",
        "coverage_end",
        "open_sessions",
        "observed_at",
        "source",
    }
)


@dataclass(frozen=True, slots=True)
class SyntheticCalendarRawArtifacts:
    """Exact raw synthetic response and its independently computed digest."""

    raw_path: Path
    sha256_path: Path
    sha256_hex: str


@dataclass(frozen=True, slots=True)
class _SyntheticCalendarJsonBody:
    """Typed values decoded from the exact synthetic JSON contract."""

    coverage_start: date
    coverage_end: date
    open_sessions: tuple[date, ...]
    observed_at: datetime
    source: str


def _json_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON object keys before contract validation."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate synthetic calendar JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    """Reject non-standard JSON constants such as NaN and Infinity."""

    raise ValueError(f"unsupported synthetic calendar JSON constant: {value}")


def _decode_calendar_json(raw_json: bytes) -> dict[str, object]:
    """Decode the strict top-level JSON object without passing ``Any`` onward."""

    try:
        decoded: object = json.loads(
            raw_json,
            object_pairs_hook=_json_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("raw_json must contain one valid synthetic calendar object") from exc
    if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
        raise ValueError("synthetic calendar JSON must be an object with string keys")
    return decoded


def _required_json_string(payload: dict[str, object], key: str) -> str:
    """Return one required string field after a runtime type guard."""

    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"synthetic calendar JSON field {key} must be a nonempty string")
    return value


def _parse_json_date(value: object, *, field_name: str) -> date:
    """Parse one canonical ISO date field without guessing formats."""

    if not isinstance(value, str):
        raise ValueError(f"synthetic calendar JSON field {field_name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"synthetic calendar JSON field {field_name} is not an ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"synthetic calendar JSON field {field_name} is not canonical")
    return parsed


def _parse_json_sessions(value: object) -> tuple[date, ...]:
    """Parse explicit session strings; never infer missing dates."""

    if not isinstance(value, list):
        raise ValueError("synthetic calendar JSON open_sessions must be a list")
    return tuple(
        _parse_json_date(item, field_name=f"open_sessions[{index}]")
        for index, item in enumerate(value)
    )


def _parse_json_datetime(value: object) -> datetime:
    """Parse one aware ISO timestamp from the synthetic contract."""

    if not isinstance(value, str):
        raise ValueError("synthetic calendar JSON observed_at must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("synthetic calendar JSON observed_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("synthetic calendar JSON observed_at must be timezone-aware")
    return parsed


def _parse_calendar_json(raw_json: bytes) -> _SyntheticCalendarJsonBody:
    """Decode and type-narrow the complete synthetic calendar JSON contract."""

    payload = _decode_calendar_json(raw_json)
    if set(payload) != _CALENDAR_JSON_KEYS:
        raise ValueError(
            "synthetic calendar JSON keys must be exactly coverage_start, "
            "coverage_end, open_sessions, observed_at, and source"
        )
    source = _required_json_string(payload, "source")
    if source != SYNTHETIC_CALENDAR_SOURCE:
        raise ValueError("synthetic calendar JSON source must be 'synthetic fixture'")
    return _SyntheticCalendarJsonBody(
        coverage_start=_parse_json_date(payload["coverage_start"], field_name="coverage_start"),
        coverage_end=_parse_json_date(payload["coverage_end"], field_name="coverage_end"),
        open_sessions=_parse_json_sessions(payload["open_sessions"]),
        observed_at=_parse_json_datetime(payload["observed_at"]),
        source=source,
    )


def _assert_body_matches_explicit_input(
    body: _SyntheticCalendarJsonBody,
    *,
    coverage_start: date,
    coverage_end: date,
    open_sessions: tuple[date, ...],
    observed_at: datetime,
) -> None:
    """Require every decoded body field to equal the caller's explicit input."""

    if body.coverage_start != coverage_start:
        raise ValueError("synthetic calendar JSON coverage_start differs from explicit input")
    if body.coverage_end != coverage_end:
        raise ValueError("synthetic calendar JSON coverage_end differs from explicit input")
    if body.open_sessions != open_sessions:
        raise ValueError("synthetic calendar JSON open_sessions differs from explicit input")
    if body.observed_at != observed_at:
        raise ValueError("synthetic calendar JSON observed_at differs from explicit input")
    if body.source != SYNTHETIC_CALENDAR_SOURCE:
        raise ValueError("synthetic calendar JSON source differs from synthetic fixture label")


def write_synthetic_calendar_raw(
    raw_json: bytes,
    *,
    tmp_path: Path,
    coverage_start: date,
    coverage_end: date,
    open_sessions: tuple[date, ...],
    observed_at: datetime,
) -> SyntheticCalendarRawArtifacts:
    """Persist unchanged synthetic JSON bytes and their SHA-256 in ``tmp_path``.

    The complete JSON contract is parsed and checked against the explicit
    arguments before any file is written. Session dates are never inferred.
    """

    if not isinstance(raw_json, bytes):
        raise TypeError("raw_json must be bytes")
    if not isinstance(tmp_path, Path):
        raise TypeError("tmp_path must be a pathlib.Path")
    if not tmp_path.is_dir():
        raise ValueError("tmp_path must be an existing caller-owned directory")
    body = _parse_calendar_json(raw_json)
    _assert_body_matches_explicit_input(
        body,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        open_sessions=open_sessions,
        observed_at=observed_at,
    )

    raw_path = tmp_path / "synthetic-calendar.json"
    sha256_path = tmp_path / "synthetic-calendar.json.sha256"
    digest = sha256(raw_json).hexdigest()
    raw_path.write_bytes(raw_json)
    sha256_path.write_text(f"{digest}  {raw_path.name}\n", encoding="ascii")
    if raw_path.read_bytes() != raw_json:
        raise OSError("synthetic calendar bytes changed while being persisted")
    return SyntheticCalendarRawArtifacts(
        raw_path=raw_path,
        sha256_path=sha256_path,
        sha256_hex=digest,
    )


@dataclass(frozen=True, slots=True)
class SyntheticCalendarSource:
    """A calendar-only source with no silent market-history fallback."""

    open_sessions: tuple[date, ...]
    coverage_start: date
    coverage_end: date
    observed_at: datetime
    raw_artifacts: SyntheticCalendarRawArtifacts
    _evidence: TradingCalendarEvidence = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate artifact integrity, JSON identity, and the Domain DTO."""

        if type(self.open_sessions) is not tuple:
            raise TypeError("open_sessions must be an explicit tuple of dates")
        if type(self.coverage_start) is not date or type(self.coverage_end) is not date:
            raise TypeError("calendar coverage endpoints must be dates")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("calendar observed_at must be timezone-aware")
        raw_bytes = self.raw_artifacts.raw_path.read_bytes()
        actual_digest = sha256(raw_bytes).hexdigest()
        if actual_digest != self.raw_artifacts.sha256_hex:
            raise ValueError("synthetic calendar raw bytes do not match recorded SHA-256")
        recorded_digest = self.raw_artifacts.sha256_path.read_text(encoding="ascii").strip().split()
        if recorded_digest != [actual_digest, self.raw_artifacts.raw_path.name]:
            raise ValueError("synthetic calendar SHA-256 sidecar does not match raw bytes")
        body = _parse_calendar_json(raw_bytes)
        _assert_body_matches_explicit_input(
            body,
            coverage_start=self.coverage_start,
            coverage_end=self.coverage_end,
            open_sessions=self.open_sessions,
            observed_at=self.observed_at,
        )
        evidence = TradingCalendarEvidence(
            coverage_start=self.coverage_start,
            coverage_end=self.coverage_end,
            open_sessions=self.open_sessions,
            source=SYNTHETIC_CALENDAR_SOURCE,
            observed_at=self.observed_at,
        )
        object.__setattr__(self, "_evidence", evidence)

    @property
    def evidence(self) -> TradingCalendarEvidence:
        """Return the Domain-owned source-bound calendar evidence."""

        return self._evidence

    def trading_calendar_evidence(
        self,
        start_date: date,
        end_date: date,
    ) -> TradingCalendarEvidence:
        """Return configured evidence; the service validates requested coverage."""

        if type(start_date) is not date or type(end_date) is not date:
            raise TypeError("calendar request endpoints must be dates")
        return self.evidence

    def trade_days(self, start_date: date, end_date: date) -> tuple[date, ...]:
        """Return only explicitly supplied sessions inside the configured window."""

        if type(start_date) is not date or type(end_date) is not date:
            raise TypeError("calendar request endpoints must be dates")
        if start_date > end_date:
            raise ValueError("calendar request start must not exceed end")
        if start_date < self.coverage_start or end_date > self.coverage_end:
            raise DataFetchError(
                "Synthetic calendar fixture does not cover the requested window",
                code="SYNTHETIC_CALENDAR_COVERAGE_MISMATCH",
                details={
                    "requested_start": start_date.isoformat(),
                    "requested_end": end_date.isoformat(),
                    "coverage_start": self.coverage_start.isoformat(),
                    "coverage_end": self.coverage_end.isoformat(),
                    "source": SYNTHETIC_CALENDAR_SOURCE,
                },
            )
        return tuple(session for session in self.open_sessions if start_date <= session <= end_date)

    def stock_history(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> tuple[ModelDailyBar, ...]:
        """Reject unsupported history reads instead of returning fake bars."""

        return self._unsupported_read("stock_history", asset_code, start_date, end_date)

    def index_history(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> tuple[ModelDailyBar, ...]:
        """Reject unsupported index reads instead of returning fake bars."""

        return self._unsupported_read("index_history", asset_code, start_date, end_date)

    def index_members(self, index_code: str, target_date: date) -> tuple[str, ...]:
        """Reject unsupported membership reads instead of returning fake members."""

        raise DataFetchError(
            "Synthetic calendar fixture does not provide index members",
            code="SYNTHETIC_CALENDAR_READ_UNSUPPORTED",
            details={
                "method": "index_members",
                "index_code": index_code,
                "target_date": target_date.isoformat(),
                "source": SYNTHETIC_CALENDAR_SOURCE,
            },
        )

    @staticmethod
    def _unsupported_read(
        method: str,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> NoReturn:
        """Raise an explicit boundary error for non-calendar reads."""

        raise DataFetchError(
            "Synthetic calendar fixture does not provide market history",
            code="SYNTHETIC_CALENDAR_READ_UNSUPPORTED",
            details={
                "method": method,
                "asset_code": asset_code,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "source": SYNTHETIC_CALENDAR_SOURCE,
            },
        )


def _empty_reference_history(
    _asset_code: str,
    _start_date: date,
    _end_date: date,
) -> NoReturn:
    """Reject accidental history use instead of silently returning no rows."""

    raise DataFetchError(
        "Synthetic calendar fixture does not provide reference market history",
        code="SYNTHETIC_CALENDAR_READ_UNSUPPORTED",
        details={"source": SYNTHETIC_CALENDAR_SOURCE, "method": "reference_history"},
    )


def build_synthetic_calendar_service(
    *,
    open_sessions: tuple[date, ...],
    coverage_start: date,
    coverage_end: date,
    observed_at: datetime,
    raw_json: bytes,
    tmp_path: Path,
    tolerance: float = 0.01,
) -> tuple[ModelMarketDataService, SyntheticCalendarRawArtifacts]:
    """Build the real model-market service around one synthetic calendar route.

    Future tests should replace only the external-source composition seam
    ``apps.data_center.composition.build_model_market_data_service`` with this
    returned service.  The application calendar loader, route coverage checks,
    Domain session resolver, thermometer predicate, and readiness predicates
    remain the production implementations.
    """

    artifacts = write_synthetic_calendar_raw(
        raw_json,
        tmp_path=tmp_path,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        open_sessions=open_sessions,
        observed_at=observed_at,
    )
    source = SyntheticCalendarSource(
        open_sessions=open_sessions,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        observed_at=observed_at,
        raw_artifacts=artifacts,
    )
    route_port: ModelMarketDataPort = source
    route = ModelMarketRoute(
        SYNTHETIC_CALENDAR_ROUTE,
        route_port,
        source_type=SYNTHETIC_CALENDAR_SOURCE,
    )
    service = ModelMarketDataService(
        (route,),
        enable_failover=False,
        tolerance=tolerance,
        reference_history=_empty_reference_history,
    )
    return service, artifacts


__all__ = [
    "SYNTHETIC_CALENDAR_ROUTE",
    "SYNTHETIC_CALENDAR_SOURCE",
    "SyntheticCalendarRawArtifacts",
    "SyntheticCalendarSource",
    "build_synthetic_calendar_service",
    "write_synthetic_calendar_raw",
]
