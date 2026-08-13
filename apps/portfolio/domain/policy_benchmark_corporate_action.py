"""Portfolio-owned benchmark corporate-action methodology definition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

POLICY_BENCHMARK_CORPORATE_ACTION_OWNER = "portfolio"
POLICY_BENCHMARK_CORPORATE_ACTION_TYPE = "corporate_action_methodology"
POLICY_BENCHMARK_CORPORATE_ACTION_SCHEMA = "portfolio-policy-benchmark-corporate-action.v1"
POLICY_BENCHMARK_CORPORATE_ACTION_PERMISSION = "methodology_definition_only"

_SOURCE_TYPE = "benchmark_corporate_action_source_definition"
_DATE_FIELDS = frozenset({"effective_date", "ex_date", "pay_date"})
_MAX_VALIDITY_DAYS = 3660

_EVENT_RULE_MATRIX: tuple[tuple[str, tuple[str, ...], str, str, str, str, str], ...] = (
    (
        "cash_dividend",
        ("effective_date", "ex_date", "pay_date"),
        "action_terms_effective",
        "recognize_receivable_and_internal_return_once",
        "settle_receivable_without_second_return",
        "cash_receivable_then_cash",
        "internal_return",
    ),
    (
        "stock_dividend",
        ("effective_date", "ex_date", "pay_date"),
        "action_terms_effective",
        "recognize_share_receivable_and_price_adjustment_once",
        "settle_share_receivable_without_second_adjustment",
        "share_receivable_then_quantity",
        "no_return",
    ),
    (
        "split",
        ("effective_date",),
        "adjust_quantity_and_reference_price_once",
        "not_applicable",
        "not_applicable",
        "quantity_and_reference_price_adjustment",
        "no_return",
    ),
    (
        "reverse_split",
        ("effective_date",),
        "adjust_quantity_and_reference_price_once",
        "not_applicable",
        "not_applicable",
        "quantity_and_reference_price_adjustment",
        "no_return",
    ),
    (
        "rights_issue",
        ("effective_date", "ex_date"),
        "action_terms_effective",
        "establish_entitlement_then_block_without_exact_terms_and_election",
        "not_applicable",
        "block",
        "block",
    ),
)


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
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkCorporateActionSourceRef:
    """Exact immutable reference to one corporate-action source definition."""

    owner: str
    artifact_type: str
    artifact_id: str
    artifact_version: str
    content_hash: str
    ordinal: int
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name in ("owner", "artifact_type", "artifact_id", "artifact_version"):
            _token(getattr(self, field_name), field_name)
        if self.artifact_type != _SOURCE_TYPE:
            raise ValueError("corporate-action source artifact_type is fixed")
        _digest(self.content_hash, "content_hash")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("source ordinal must be an exact non-negative integer")
        recorded_at = _aware(self.recorded_at, "source recorded_at")
        valid_until = _aware(self.valid_until, "source valid_until")
        if recorded_at >= valid_until:
            raise ValueError("corporate-action source validity window is invalid")

    def to_payload(self) -> dict[str, object]:
        """Return the exact ordered owner source reference."""

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
class PolicyBenchmarkCorporateActionRule:
    """One closed v1 event rule with explicit date and valuation semantics."""

    ordinal: int
    event_type: str
    required_date_fields: tuple[str, ...]
    effective_date_semantics: str
    ex_date_semantics: str
    pay_date_semantics: str
    valuation_treatment: str
    performance_treatment: str

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("event rule ordinal must be an exact non-negative integer")
        for field_name in (
            "event_type",
            "effective_date_semantics",
            "ex_date_semantics",
            "pay_date_semantics",
            "valuation_treatment",
            "performance_treatment",
        ):
            _token(getattr(self, field_name), field_name)
        if type(self.required_date_fields) is not tuple:
            raise TypeError("required_date_fields must be an exact tuple")
        if (
            not self.required_date_fields
            or len(set(self.required_date_fields)) != len(self.required_date_fields)
            or any(type(value) is not str for value in self.required_date_fields)
            or any(value not in _DATE_FIELDS for value in self.required_date_fields)
        ):
            raise ValueError("required_date_fields must be exact, unique, and supported")
        if self.ordinal >= len(_EVENT_RULE_MATRIX):
            raise ValueError("unknown corporate-action event_type must fail closed")
        actual = (
            self.event_type,
            self.required_date_fields,
            self.effective_date_semantics,
            self.ex_date_semantics,
            self.pay_date_semantics,
            self.valuation_treatment,
            self.performance_treatment,
        )
        if actual != _EVENT_RULE_MATRIX[self.ordinal]:
            raise ValueError("corporate-action event rule differs from the closed v1 matrix")

    def to_payload(self) -> dict[str, object]:
        """Return the complete date and treatment rule."""

        return {
            "ordinal": self.ordinal,
            "event_type": self.event_type,
            "required_date_fields": list(self.required_date_fields),
            "effective_date_semantics": self.effective_date_semantics,
            "ex_date_semantics": self.ex_date_semantics,
            "pay_date_semantics": self.pay_date_semantics,
            "valuation_treatment": self.valuation_treatment,
            "performance_treatment": self.performance_treatment,
        }


@dataclass(frozen=True, slots=True)
class PortfolioPolicyBenchmarkCorporateAction:
    """Immutable corporate-action definition without activation authority."""

    methodology_id: str
    methodology_version: str
    security_identifier_namespace: str
    timezone: str
    business_date_cutoff_local: time
    source_priority: tuple[PolicyBenchmarkCorporateActionSourceRef, ...]
    event_rules: tuple[PolicyBenchmarkCorporateActionRule, ...]
    missing_action_policy: str
    unknown_event_type_policy: str
    recorded_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = POLICY_BENCHMARK_CORPORATE_ACTION_OWNER
    artifact_type: str = POLICY_BENCHMARK_CORPORATE_ACTION_TYPE
    schema: str = POLICY_BENCHMARK_CORPORATE_ACTION_SCHEMA
    permission: str = POLICY_BENCHMARK_CORPORATE_ACTION_PERMISSION
    business_date_policy: str = "issuer_market_local_date"
    non_business_date_policy: str = "block"
    source_failure_policy: str = "block"
    price_input_adjustment_basis: str = "unadjusted"
    adjustment_application_policy: str = "exact_event_once"
    duplicate_event_policy: str = "block"
    pre_adjusted_input_policy: str = "block"

    def __post_init__(self) -> None:
        self._validate_authority()
        for field_name in (
            "methodology_id",
            "methodology_version",
            "security_identifier_namespace",
            "timezone",
        ):
            _token(getattr(self, field_name), field_name)
        self._validate_policies()
        recorded_at = _aware(self.recorded_at, "recorded_at")
        valid_until = _aware(self.valid_until, "valid_until")
        if recorded_at >= valid_until:
            raise ValueError("corporate-action methodology validity window is invalid")
        self._validate_cutoff(self._zone())
        self._validate_sources()
        self._validate_event_rules()
        expected_identity = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity)
        elif _digest(self.identity_hash, "identity_hash") != expected_identity:
            raise ValueError("corporate-action identity_hash is invalid")
        expected_content = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content)
        elif _digest(self.content_hash, "content_hash") != expected_content:
            raise ValueError("corporate-action content_hash is invalid")

    def _validate_authority(self) -> None:
        if (
            self.owner != POLICY_BENCHMARK_CORPORATE_ACTION_OWNER
            or self.artifact_type != POLICY_BENCHMARK_CORPORATE_ACTION_TYPE
            or self.schema != POLICY_BENCHMARK_CORPORATE_ACTION_SCHEMA
            or self.permission != POLICY_BENCHMARK_CORPORATE_ACTION_PERMISSION
        ):
            raise ValueError("policy benchmark corporate-action authority is fixed")

    def _validate_policies(self) -> None:
        exact_policies = {
            "business_date_policy": "issuer_market_local_date",
            "non_business_date_policy": "block",
            "source_failure_policy": "block",
            "missing_action_policy": "fail_closed",
            "unknown_event_type_policy": "fail_closed",
            "price_input_adjustment_basis": "unadjusted",
            "adjustment_application_policy": "exact_event_once",
            "duplicate_event_policy": "block",
            "pre_adjusted_input_policy": "block",
        }
        for field_name, expected in exact_policies.items():
            if getattr(self, field_name) != expected:
                raise ValueError(f"{field_name} is fixed to {expected}")

    def _zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("timezone must name an installed IANA timezone") from error

    def _validate_cutoff(self, zone: ZoneInfo) -> None:
        clock = self.business_date_cutoff_local
        if type(clock) is not time or clock.tzinfo is not None:
            raise ValueError("business_date_cutoff_local must be an exact timezone-free time")
        first = self.recorded_at.astimezone(zone).date()
        last = (self.valid_until - timedelta(microseconds=1)).astimezone(zone).date()
        if (last - first).days > _MAX_VALIDITY_DAYS:
            raise ValueError("corporate-action validity exceeds the bounded DST audit window")
        while first <= last:
            _resolve_local(first, clock, zone)
            first += timedelta(days=1)

    def _validate_sources(self) -> None:
        if type(self.source_priority) is not tuple or not self.source_priority:
            raise ValueError("source_priority must be a non-empty exact tuple")
        identities: set[tuple[str, str, str, str]] = set()
        for ordinal, source in enumerate(self.source_priority):
            if type(source) is not PolicyBenchmarkCorporateActionSourceRef:
                raise TypeError("source_priority must contain exact corporate-action refs")
            PolicyBenchmarkCorporateActionSourceRef.__post_init__(source)
            if source.ordinal != ordinal:
                raise ValueError("source ordinal must be contiguous and ordered")
            identity = (
                source.owner,
                source.artifact_type,
                source.artifact_id,
                source.artifact_version,
            )
            if identity in identities:
                raise ValueError("corporate-action source identities must be unique")
            identities.add(identity)
            if source.recorded_at > self.recorded_at:
                raise ValueError("corporate-action source is not knowable at recording")
        if self.valid_until != min(source.valid_until for source in self.source_priority):
            raise ValueError("methodology valid_until must equal source validity minimum")

    def _validate_event_rules(self) -> None:
        if type(self.event_rules) is not tuple or len(self.event_rules) != len(_EVENT_RULE_MATRIX):
            raise ValueError("event_rules must contain the complete closed v1 matrix")
        event_types: set[str] = set()
        for ordinal, rule in enumerate(self.event_rules):
            if type(rule) is not PolicyBenchmarkCorporateActionRule:
                raise TypeError("event_rules must contain exact corporate-action rules")
            PolicyBenchmarkCorporateActionRule.__post_init__(rule)
            if rule.ordinal != ordinal:
                raise ValueError("event rule ordinal must be contiguous and ordered")
            if rule.event_type in event_types:
                raise ValueError("corporate-action event types must be unique")
            event_types.add(rule.event_type)

    @property
    def activation_available(self) -> bool:
        """Remain false until a separately governed activation exists."""

        return False

    @property
    def automatic_fallback_allowed(self) -> bool:
        """Remain false because ordered sources grant no fallback authority."""

        return False

    @property
    def mutable_fact_projection_allowed(self) -> bool:
        """Remain false because only exact immutable owner refs are admissible."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a methodology definition grants no trade authority."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable definition is knowable and unexpired."""

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
            "security_identifier_namespace": self.security_identifier_namespace,
            "timezone": self.timezone,
            "business_date_cutoff_local": _time_text(self.business_date_cutoff_local),
            "business_date_policy": self.business_date_policy,
            "non_business_date_policy": self.non_business_date_policy,
            "source_priority": [source.to_payload() for source in self.source_priority],
            "event_rules": [rule.to_payload() for rule in self.event_rules],
            "source_failure_policy": self.source_failure_policy,
            "missing_action_policy": self.missing_action_policy,
            "unknown_event_type_policy": self.unknown_event_type_policy,
            "price_input_adjustment_basis": self.price_input_adjustment_basis,
            "adjustment_application_policy": self.adjustment_application_policy,
            "duplicate_event_policy": self.duplicate_event_policy,
            "pre_adjusted_input_policy": self.pre_adjusted_input_policy,
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
            "mutable_fact_projection_allowed": False,
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
        raise ValueError("business-date cutoff does not exist in the IANA timezone")
    if len({candidate.utcoffset() for candidate in candidates}) > 1:
        raise ValueError("business-date cutoff is ambiguous in the IANA timezone")
    if clock.fold != 0:
        raise ValueError("fold=1 is noncanonical for an unambiguous business-date cutoff")
    return candidates[0]


__all__ = [
    "POLICY_BENCHMARK_CORPORATE_ACTION_OWNER",
    "POLICY_BENCHMARK_CORPORATE_ACTION_PERMISSION",
    "POLICY_BENCHMARK_CORPORATE_ACTION_SCHEMA",
    "POLICY_BENCHMARK_CORPORATE_ACTION_TYPE",
    "PolicyBenchmarkCorporateActionRule",
    "PolicyBenchmarkCorporateActionSourceRef",
    "PortfolioPolicyBenchmarkCorporateAction",
]
