"""Portfolio-owned benchmark cost and tax methodology definition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

POLICY_BENCHMARK_COST_TAX_OWNER = "portfolio"
POLICY_BENCHMARK_COST_TAX_TYPE = "cost_tax_methodology"
POLICY_BENCHMARK_COST_TAX_SCHEMA = "portfolio-policy-benchmark-cost-tax.v1"
POLICY_BENCHMARK_COST_TAX_PERMISSION = "methodology_definition_only"

_SOURCE_TYPES = {
    "fee": "benchmark_fee_definition",
    "tax": "benchmark_tax_definition",
}
_CHARGE_EVENTS = frozenset({"trade", "cash_dividend", "corporate_action"})
_TRADE_SIDES = frozenset({"buy", "sell", "both", "not_applicable"})
_CALCULATION_MODES = frozenset(
    {
        "rate",
        "fixed_amount",
        "rate_with_minimum",
        "rate_with_maximum",
        "rate_with_minimum_and_maximum",
    }
)
_ROUNDING_MODES = frozenset({"half_up", "half_even", "down", "up"})
_EVENT_SEMANTICS: dict[str, tuple[frozenset[str], frozenset[str], frozenset[str]]] = {
    "trade": (
        frozenset({"buy", "sell", "both"}),
        frozenset({"gross_trade_notional", "executed_quantity", "fixed_per_order"}),
        frozenset({"trade_execution", "trade_settlement"}),
    ),
    "cash_dividend": (
        frozenset({"not_applicable"}),
        frozenset({"gross_cash_dividend_entitlement", "fixed_per_event"}),
        frozenset({"entitlement_recognition"}),
    ),
    "corporate_action": (
        frozenset({"not_applicable"}),
        frozenset({"gross_corporate_action_cash_entitlement", "fixed_per_event"}),
        frozenset({"effective_date_recognition"}),
    ),
}


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
        raise ValueError(f"{field_name} must be an uppercase three-letter currency code")
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


def _decimal(value: object, field_name: str) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError(f"{field_name} must be an exact Decimal")
    if not value.is_finite() or (value.is_zero() and value.is_signed()):
        raise ValueError(f"{field_name} must be finite and cannot be negative zero")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return value


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field_name)


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _fraction_places(value: Decimal) -> int:
    if value.is_zero():
        return 0
    exponent = value.normalize().as_tuple().exponent
    if type(exponent) is not int:
        raise ValueError("finite Decimal exponent must be an integer")
    return max(0, -exponent)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
class PolicyBenchmarkCostTaxSourceRef:
    """Exact owner-issued fee or tax definition reference and applicability key."""

    owner: str
    artifact_type: str
    artifact_id: str
    artifact_version: str
    content_hash: str
    ordinal: int
    charge_kind: str
    charge_code: str
    asset_scope_code: str
    jurisdiction_code: str
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "owner",
            "artifact_type",
            "artifact_id",
            "artifact_version",
            "charge_kind",
            "charge_code",
            "asset_scope_code",
            "jurisdiction_code",
        ):
            _token(getattr(self, field_name), field_name)
        if self.charge_kind not in _SOURCE_TYPES:
            raise ValueError("charge_kind must be exactly fee or tax")
        if self.artifact_type != _SOURCE_TYPES[self.charge_kind]:
            raise ValueError("cost/tax source artifact_type does not match charge_kind")
        _digest(self.content_hash, "content_hash")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("source ordinal must be an exact non-negative integer")
        recorded_at = _aware(self.recorded_at, "source recorded_at")
        valid_until = _aware(self.valid_until, "source valid_until")
        if recorded_at >= valid_until:
            raise ValueError("cost/tax source validity window is invalid")

    def to_payload(self) -> dict[str, object]:
        """Return the exact ordered owner definition reference."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "artifact_version": self.artifact_version,
            "content_hash": self.content_hash,
            "ordinal": self.ordinal,
            "charge_kind": self.charge_kind,
            "charge_code": self.charge_code,
            "asset_scope_code": self.asset_scope_code,
            "jurisdiction_code": self.jurisdiction_code,
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
        }


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkCostTaxRule:
    """Exact application rule copied from one referenced owner definition."""

    ordinal: int
    source_ordinal: int
    charge_kind: str
    charge_code: str
    asset_scope_code: str
    jurisdiction_code: str
    charge_event: str
    trade_side: str
    calculation_basis: str
    recognition_timing: str
    calculation_mode: str
    rate: Decimal | None
    fixed_amount: Decimal | None
    minimum_amount: Decimal | None
    maximum_amount: Decimal | None
    charge_currency: str
    rate_precision_places: int
    amount_precision_places: int
    rounding_increment: Decimal
    rounding_mode: str

    def __post_init__(self) -> None:
        self._validate_identity_and_enums()
        self._validate_event_semantics()
        self._validate_value_shape()
        self._validate_precision_and_rounding()

    def _validate_identity_and_enums(self) -> None:
        for field_name in (
            "charge_kind",
            "charge_code",
            "asset_scope_code",
            "jurisdiction_code",
            "charge_event",
            "trade_side",
            "calculation_basis",
            "recognition_timing",
            "calculation_mode",
            "rounding_mode",
        ):
            _token(getattr(self, field_name), field_name)
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("rule ordinal must be an exact non-negative integer")
        if type(self.source_ordinal) is not int or self.source_ordinal < 0:
            raise ValueError("source_ordinal must be an exact non-negative integer")
        if self.source_ordinal != self.ordinal:
            raise ValueError("each cost/tax rule must bind its same-ordinal exact source")
        if self.charge_kind not in _SOURCE_TYPES:
            raise ValueError("charge_kind must be exactly fee or tax")
        if self.charge_event not in _CHARGE_EVENTS:
            raise ValueError("unknown charge_event must fail closed")
        if self.trade_side not in _TRADE_SIDES:
            raise ValueError("unknown trade_side must fail closed")
        if self.calculation_mode not in _CALCULATION_MODES:
            raise ValueError("unknown calculation_mode must fail closed")
        if self.rounding_mode not in _ROUNDING_MODES:
            raise ValueError("rounding_mode must be explicit and supported")
        _currency(self.charge_currency, "charge_currency")

    def _validate_event_semantics(self) -> None:
        allowed_sides, allowed_bases, allowed_timings = _EVENT_SEMANTICS[self.charge_event]
        if self.trade_side not in allowed_sides:
            raise ValueError("trade_side is incompatible with charge_event")
        if self.calculation_basis not in allowed_bases:
            raise ValueError("calculation_basis is incompatible with charge_event")
        if self.recognition_timing not in allowed_timings:
            raise ValueError("recognition_timing is incompatible with charge_event")
        is_fixed_basis = self.calculation_basis in {"fixed_per_order", "fixed_per_event"}
        if (self.calculation_mode == "fixed_amount") != is_fixed_basis:
            raise ValueError("fixed amount mode and basis must be declared together")

    def _validate_value_shape(self) -> None:
        rate = _optional_decimal(self.rate, "rate")
        fixed = _optional_decimal(self.fixed_amount, "fixed_amount")
        minimum = _optional_decimal(self.minimum_amount, "minimum_amount")
        maximum = _optional_decimal(self.maximum_amount, "maximum_amount")
        expected_presence = {
            "rate": (True, False, False, False),
            "fixed_amount": (False, True, False, False),
            "rate_with_minimum": (True, False, True, False),
            "rate_with_maximum": (True, False, False, True),
            "rate_with_minimum_and_maximum": (True, False, True, True),
        }[self.calculation_mode]
        actual_presence = tuple(value is not None for value in (rate, fixed, minimum, maximum))
        if actual_presence != expected_presence:
            raise ValueError("calculation values must exactly match calculation_mode")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("minimum_amount cannot exceed maximum_amount")

    def _validate_precision_and_rounding(self) -> None:
        if type(self.rate_precision_places) is not int or not (
            0 <= self.rate_precision_places <= 18
        ):
            raise ValueError("rate_precision_places must be an exact integer within 0..18")
        if type(self.amount_precision_places) is not int or not (
            0 <= self.amount_precision_places <= 18
        ):
            raise ValueError("amount_precision_places must be an exact integer within 0..18")
        increment = _decimal(self.rounding_increment, "rounding_increment")
        expected_increment = Decimal(1).scaleb(-self.amount_precision_places)
        if increment != expected_increment:
            raise ValueError("rounding_increment must exactly match amount precision")
        if self.rate is not None and _fraction_places(self.rate) > self.rate_precision_places:
            raise ValueError("rate exceeds the exact declared rate precision")
        for field_name in ("fixed_amount", "minimum_amount", "maximum_amount"):
            amount = getattr(self, field_name)
            if amount is not None and _fraction_places(amount) > self.amount_precision_places:
                raise ValueError(f"{field_name} exceeds the exact declared amount precision")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical owner-bound calculation rule."""

        return {
            "ordinal": self.ordinal,
            "source_ordinal": self.source_ordinal,
            "charge_kind": self.charge_kind,
            "charge_code": self.charge_code,
            "asset_scope_code": self.asset_scope_code,
            "jurisdiction_code": self.jurisdiction_code,
            "charge_event": self.charge_event,
            "trade_side": self.trade_side,
            "calculation_basis": self.calculation_basis,
            "recognition_timing": self.recognition_timing,
            "calculation_mode": self.calculation_mode,
            "rate": _decimal_text(self.rate),
            "fixed_amount": _decimal_text(self.fixed_amount),
            "minimum_amount": _decimal_text(self.minimum_amount),
            "maximum_amount": _decimal_text(self.maximum_amount),
            "charge_currency": self.charge_currency,
            "rate_precision_places": self.rate_precision_places,
            "amount_precision_places": self.amount_precision_places,
            "rounding_increment": _decimal_text(self.rounding_increment),
            "rounding_mode": self.rounding_mode,
        }


@dataclass(frozen=True, slots=True)
class PortfolioPolicyBenchmarkCostTax:
    """Immutable cost/tax methodology without activation or execution authority."""

    methodology_id: str
    methodology_version: str
    source_priority: tuple[PolicyBenchmarkCostTaxSourceRef, ...]
    charge_rules: tuple[PolicyBenchmarkCostTaxRule, ...]
    recorded_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = POLICY_BENCHMARK_COST_TAX_OWNER
    artifact_type: str = POLICY_BENCHMARK_COST_TAX_TYPE
    schema: str = POLICY_BENCHMARK_COST_TAX_SCHEMA
    permission: str = POLICY_BENCHMARK_COST_TAX_PERMISSION
    business_date_policy: str = "benchmark_trading_calendar_date"
    currency_basis_policy: str = "event_gross_currency"
    currency_conversion_policy: str = "exact_benchmark_fx_fixing_only"
    missing_fx_policy: str = "fail_closed"
    unknown_asset_policy: str = "fail_closed"
    unknown_fee_policy: str = "fail_closed"
    unknown_tax_policy: str = "fail_closed"
    missing_source_policy: str = "fail_closed"
    source_failure_policy: str = "block"
    estimation_policy: str = "prohibited"
    silent_zero_policy: str = "prohibited"
    duplicate_charge_policy: str = "block"
    cash_dividend_charge_policy: str = "entitlement_once"
    cash_dividend_payment_policy: str = "settlement_only_no_second_charge"
    corporate_action_charge_policy: str = "exact_event_once"
    already_net_amount_policy: str = "block"

    def __post_init__(self) -> None:
        self._validate_authority_and_policies()
        _token(self.methodology_id, "methodology_id")
        _token(self.methodology_version, "methodology_version")
        recorded_at = _aware(self.recorded_at, "recorded_at")
        valid_until = _aware(self.valid_until, "valid_until")
        if recorded_at >= valid_until:
            raise ValueError("cost/tax methodology validity window is invalid")
        self._validate_sources_and_rules()
        identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", identity_hash)
        elif _digest(self.identity_hash, "identity_hash") != identity_hash:
            raise ValueError("cost/tax identity_hash is invalid")
        content_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", content_hash)
        elif _digest(self.content_hash, "content_hash") != content_hash:
            raise ValueError("cost/tax content_hash is invalid")

    def _validate_authority_and_policies(self) -> None:
        if (
            self.owner != POLICY_BENCHMARK_COST_TAX_OWNER
            or self.artifact_type != POLICY_BENCHMARK_COST_TAX_TYPE
            or self.schema != POLICY_BENCHMARK_COST_TAX_SCHEMA
            or self.permission != POLICY_BENCHMARK_COST_TAX_PERMISSION
        ):
            raise ValueError("policy benchmark cost/tax authority is fixed")
        exact_policies = {
            "business_date_policy": "benchmark_trading_calendar_date",
            "currency_basis_policy": "event_gross_currency",
            "currency_conversion_policy": "exact_benchmark_fx_fixing_only",
            "missing_fx_policy": "fail_closed",
            "unknown_asset_policy": "fail_closed",
            "unknown_fee_policy": "fail_closed",
            "unknown_tax_policy": "fail_closed",
            "missing_source_policy": "fail_closed",
            "source_failure_policy": "block",
            "estimation_policy": "prohibited",
            "silent_zero_policy": "prohibited",
            "duplicate_charge_policy": "block",
            "cash_dividend_charge_policy": "entitlement_once",
            "cash_dividend_payment_policy": "settlement_only_no_second_charge",
            "corporate_action_charge_policy": "exact_event_once",
            "already_net_amount_policy": "block",
        }
        for field_name, expected in exact_policies.items():
            if getattr(self, field_name) != expected:
                raise ValueError(f"{field_name} is fixed to {expected}")

    def _validate_sources_and_rules(self) -> None:
        if type(self.source_priority) is not tuple or not self.source_priority:
            raise ValueError("source_priority must be a non-empty exact tuple")
        if type(self.charge_rules) is not tuple or not self.charge_rules:
            raise ValueError("charge_rules must be a non-empty exact tuple")
        if len(self.source_priority) != len(self.charge_rules):
            raise ValueError("every charge rule must have exactly one source definition")
        source_identities: set[tuple[str, str, str, str]] = set()
        charge_identities: set[tuple[str, str, str, str]] = set()
        coverage_keys: set[tuple[str, str, str, str, str, str, str]] = set()
        kinds: set[str] = set()
        for ordinal, (source, rule) in enumerate(
            zip(self.source_priority, self.charge_rules, strict=True)
        ):
            if type(source) is not PolicyBenchmarkCostTaxSourceRef:
                raise TypeError("source_priority must contain exact cost/tax source refs")
            if type(rule) is not PolicyBenchmarkCostTaxRule:
                raise TypeError("charge_rules must contain exact cost/tax rules")
            PolicyBenchmarkCostTaxSourceRef.__post_init__(source)
            PolicyBenchmarkCostTaxRule.__post_init__(rule)
            if source.ordinal != ordinal or rule.ordinal != ordinal:
                raise ValueError("cost/tax sources and rules must be contiguous and ordered")
            source_identity = (
                source.owner,
                source.artifact_type,
                source.artifact_id,
                source.artifact_version,
            )
            if source_identity in source_identities:
                raise ValueError("cost/tax owner source identities must be unique")
            source_identities.add(source_identity)
            if source.recorded_at > self.recorded_at:
                raise ValueError("cost/tax source is not knowable at methodology recording")
            if (
                source.charge_kind,
                source.charge_code,
                source.asset_scope_code,
                source.jurisdiction_code,
            ) != (
                rule.charge_kind,
                rule.charge_code,
                rule.asset_scope_code,
                rule.jurisdiction_code,
            ):
                raise ValueError("charge rule does not match its exact owner definition")
            charge_identity = (
                rule.charge_kind,
                rule.charge_code,
                rule.asset_scope_code,
                rule.jurisdiction_code,
            )
            if charge_identity in charge_identities:
                raise ValueError("one exact charge cannot be applied through multiple events")
            charge_identities.add(charge_identity)
            coverage_key = (
                rule.charge_kind,
                rule.charge_code,
                rule.asset_scope_code,
                rule.jurisdiction_code,
                rule.charge_event,
                rule.trade_side,
                rule.recognition_timing,
            )
            if coverage_key in coverage_keys:
                raise ValueError("duplicate cost/tax charge coverage must fail closed")
            coverage_keys.add(coverage_key)
            kinds.add(source.charge_kind)
        if kinds != set(_SOURCE_TYPES):
            raise ValueError("methodology requires exact fee and tax owner definitions")
        if self.valid_until != min(source.valid_until for source in self.source_priority):
            raise ValueError("methodology valid_until must equal source validity minimum")

    @property
    def activation_available(self) -> bool:
        """Remain false until a separately governed activation exists."""

        return False

    @property
    def automatic_fallback_allowed(self) -> bool:
        """Remain false because source ordering grants no fallback authority."""

        return False

    @property
    def silent_zero_allowed(self) -> bool:
        """Remain false; only an explicit zero in an exact owner rule is admissible."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a methodology definition grants no trade authority."""

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
            "source_priority": [source.to_payload() for source in self.source_priority],
            "charge_rules": [rule.to_payload() for rule in self.charge_rules],
            "business_date_policy": self.business_date_policy,
            "currency_basis_policy": self.currency_basis_policy,
            "currency_conversion_policy": self.currency_conversion_policy,
            "missing_fx_policy": self.missing_fx_policy,
            "unknown_asset_policy": self.unknown_asset_policy,
            "unknown_fee_policy": self.unknown_fee_policy,
            "unknown_tax_policy": self.unknown_tax_policy,
            "missing_source_policy": self.missing_source_policy,
            "source_failure_policy": self.source_failure_policy,
            "estimation_policy": self.estimation_policy,
            "silent_zero_policy": self.silent_zero_policy,
            "duplicate_charge_policy": self.duplicate_charge_policy,
            "cash_dividend_charge_policy": self.cash_dividend_charge_policy,
            "cash_dividend_payment_policy": self.cash_dividend_payment_policy,
            "corporate_action_charge_policy": self.corporate_action_charge_policy,
            "already_net_amount_policy": self.already_net_amount_policy,
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
            "silent_zero_allowed": False,
            "must_not_execute": True,
        }


__all__ = [
    "POLICY_BENCHMARK_COST_TAX_OWNER",
    "POLICY_BENCHMARK_COST_TAX_PERMISSION",
    "POLICY_BENCHMARK_COST_TAX_SCHEMA",
    "POLICY_BENCHMARK_COST_TAX_TYPE",
    "PolicyBenchmarkCostTaxRule",
    "PolicyBenchmarkCostTaxSourceRef",
    "PortfolioPolicyBenchmarkCostTax",
]
