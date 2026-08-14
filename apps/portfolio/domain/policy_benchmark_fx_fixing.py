"""Portfolio-owned benchmark FX-fixing methodology definition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

POLICY_BENCHMARK_FX_FIXING_OWNER = "portfolio"
POLICY_BENCHMARK_FX_FIXING_TYPE = "fx_fixing_methodology"
POLICY_BENCHMARK_FX_FIXING_SCHEMA = "portfolio-policy-benchmark-fx-fixing.v1"
POLICY_BENCHMARK_FX_FIXING_PERMISSION = "methodology_definition_only"

_FIXING_CONVENTIONS = frozenset({"quote_per_base", "base_per_quote"})
_SOURCE_TYPE = "benchmark_fx_source_definition"
_MAX_VALIDITY_DAYS = 3660


def _token(value: object, field_name: str, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _currency(value: object, field_name: str) -> str:
    token = _token(value, field_name, 3)
    if len(token) != 3 or token.upper() != token or not token.isascii() or not token.isalpha():
        raise ValueError(f"{field_name} currency must be an uppercase three-letter code")
    return token


def _digest(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _time_text(value: time) -> str:
    text = value.isoformat(timespec="microseconds" if value.microsecond else "seconds")
    return f"{text}[fold=1]" if value.fold else text


def _canonical_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkFxSourceRef:
    """Exact immutable reference to one eligible FX-fixing source."""

    owner: str
    artifact_type: str
    artifact_id: str
    artifact_version: str
    content_hash: str
    ordinal: int
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for name in ("owner", "artifact_type", "artifact_id", "artifact_version"):
            _token(getattr(self, name), name)
        if self.artifact_type != _SOURCE_TYPE:
            raise ValueError("FX source artifact_type is fixed")
        _digest(self.content_hash, "content_hash")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("source ordinal must be an exact non-negative integer")
        _aware(self.recorded_at, "source recorded_at")
        _aware(self.valid_until, "source valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("FX source validity window is invalid")

    def to_payload(self) -> dict[str, object]:
        """Return the exact ordered source reference."""
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "artifact_version": self.artifact_version,
            "content_hash": self.content_hash,
            "ordinal": self.ordinal,
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
        }


@dataclass(frozen=True, slots=True)
class PortfolioPolicyBenchmarkFxFixing:
    """Immutable direct-pair FX-fixing definition without activation authority."""

    methodology_id: str
    methodology_version: str
    base_currency: str
    quote_currency: str
    fixing_convention: str
    inverse_rate_allowed: bool
    timezone: str
    valuation_cutoff_local: time
    source_priority: tuple[PolicyBenchmarkFxSourceRef, ...]
    stale_after_seconds: int
    triangulation_policy: str
    source_failure_policy: str
    missing_fx_policy: str
    recorded_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = POLICY_BENCHMARK_FX_FIXING_OWNER
    artifact_type: str = POLICY_BENCHMARK_FX_FIXING_TYPE
    schema: str = POLICY_BENCHMARK_FX_FIXING_SCHEMA
    permission: str = POLICY_BENCHMARK_FX_FIXING_PERMISSION
    triangulation_currency: str | None = None

    def __post_init__(self) -> None:
        self._validate_authority()
        _token(self.methodology_id, "methodology_id")
        _token(self.methodology_version, "methodology_version")
        base = _currency(self.base_currency, "base_currency")
        quote = _currency(self.quote_currency, "quote_currency")
        if base == quote:
            raise ValueError("base and quote currencies must be distinct")
        if self.fixing_convention not in _FIXING_CONVENTIONS:
            raise ValueError("fixing_convention is outside the exact supported enum")
        if type(self.inverse_rate_allowed) is not bool:
            raise TypeError("inverse_rate_allowed must be an exact boolean")
        _token(self.timezone, "timezone")
        if self.triangulation_policy != "prohibited":
            raise ValueError("triangulation_policy is fixed prohibited in v1")
        if self.triangulation_currency is not None:
            raise ValueError(
                "triangulation_currency must be absent when triangulation is prohibited"
            )
        if self.source_failure_policy != "block":
            raise ValueError("source_failure_policy is fixed block")
        if self.missing_fx_policy != "fail_closed":
            raise ValueError("missing_fx_policy is fixed fail_closed")
        if type(self.stale_after_seconds) is not int:
            raise TypeError("stale_after_seconds must be an exact positive integer")
        if self.stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        recorded = _aware(self.recorded_at, "recorded_at")
        valid = _aware(self.valid_until, "valid_until")
        if recorded >= valid:
            raise ValueError("FX-fixing validity window is invalid")
        self._validate_cutoff(self._zone())
        self._validate_sources()
        identity = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", identity)
        elif _digest(self.identity_hash, "identity_hash") != identity:
            raise ValueError("FX-fixing identity_hash is invalid")
        content = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", content)
        elif _digest(self.content_hash, "content_hash") != content:
            raise ValueError("FX-fixing content_hash is invalid")

    def _validate_authority(self) -> None:
        if (
            self.owner != POLICY_BENCHMARK_FX_FIXING_OWNER
            or self.artifact_type != POLICY_BENCHMARK_FX_FIXING_TYPE
            or self.schema != POLICY_BENCHMARK_FX_FIXING_SCHEMA
            or self.permission != POLICY_BENCHMARK_FX_FIXING_PERMISSION
        ):
            raise ValueError("policy benchmark FX-fixing authority is fixed")

    def _zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("timezone must name an installed IANA timezone") from error

    def _validate_cutoff(self, zone: ZoneInfo) -> None:
        clock = self.valuation_cutoff_local
        if type(clock) is not time or clock.tzinfo is not None:
            raise ValueError("valuation_cutoff_local must be an exact timezone-free time")
        first = self.recorded_at.astimezone(zone).date()
        last = (self.valid_until - timedelta(microseconds=1)).astimezone(zone).date()
        if (last - first).days > _MAX_VALIDITY_DAYS:
            raise ValueError("FX-fixing validity exceeds the bounded DST audit window")
        while first <= last:
            _resolve_local(first, clock, zone)
            first += timedelta(days=1)

    def _validate_sources(self) -> None:
        if type(self.source_priority) is not tuple or not self.source_priority:
            raise ValueError("source_priority must be a non-empty exact tuple")
        identities: set[tuple[str, str, str]] = set()
        for ordinal, source in enumerate(self.source_priority):
            if type(source) is not PolicyBenchmarkFxSourceRef:
                raise TypeError("source_priority must contain exact FX source refs")
            PolicyBenchmarkFxSourceRef.__post_init__(source)
            if source.ordinal != ordinal:
                raise ValueError("source ordinal must be contiguous and ordered")
            identity = (source.owner, source.artifact_id, source.artifact_version)
            if identity in identities:
                raise ValueError("FX source identities must be unique")
            identities.add(identity)
            if source.recorded_at > self.recorded_at:
                raise ValueError("FX source is not knowable at methodology recording")
        if self.valid_until != min(source.valid_until for source in self.source_priority):
            raise ValueError("methodology valid_until must equal source validity minimum")

    @property
    def currency_pair(self) -> str:
        """Return the sealed base/quote pair without inferring direction."""
        return f"{self.base_currency}/{self.quote_currency}"

    @property
    def activation_available(self) -> bool:
        """Remain false until separate governance exists."""
        return False

    @property
    def automatic_fallback_allowed(self) -> bool:
        """Remain false because source ordering grants no fallback authority."""
        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a methodology grants no execution authority."""
        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this definition is knowable and unexpired."""
        _aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "methodology_id": self.methodology_id,
            "methodology_version": self.methodology_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "currency_pair": self.currency_pair,
            "fixing_convention": self.fixing_convention,
            "inverse_rate_allowed": self.inverse_rate_allowed,
            "timezone": self.timezone,
            "valuation_cutoff_local": _time_text(self.valuation_cutoff_local),
            "source_priority": [source.to_payload() for source in self.source_priority],
            "stale_after_seconds": self.stale_after_seconds,
            "triangulation_policy": self.triangulation_policy,
            "triangulation_currency": self.triangulation_currency,
            "source_failure_policy": self.source_failure_policy,
            "missing_fx_policy": self.missing_fx_policy,
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "permission": self.permission,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the exact inactive definition and safety markers."""
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "automatic_fallback_allowed": False,
            "must_not_execute": True,
        }


def _resolve_local(day: date, clock: time, zone: ZoneInfo) -> datetime:
    naive = datetime.combine(day, clock.replace(tzinfo=None))
    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        roundtrip = candidate.astimezone(UTC).astimezone(zone)
        if roundtrip.replace(tzinfo=None) == naive and roundtrip.fold == fold:
            candidates.append(candidate)
    if not candidates:
        raise ValueError("valuation cutoff local time does not exist in the IANA timezone")
    if len({candidate.utcoffset() for candidate in candidates}) > 1:
        raise ValueError("valuation cutoff local time is ambiguous in the IANA timezone")
    if clock.fold != 0:
        raise ValueError("fold=1 is noncanonical for an unambiguous valuation cutoff")
    return candidates[0]


__all__ = [
    "POLICY_BENCHMARK_FX_FIXING_OWNER",
    "POLICY_BENCHMARK_FX_FIXING_PERMISSION",
    "POLICY_BENCHMARK_FX_FIXING_SCHEMA",
    "POLICY_BENCHMARK_FX_FIXING_TYPE",
    "PolicyBenchmarkFxSourceRef",
    "PortfolioPolicyBenchmarkFxFixing",
]
