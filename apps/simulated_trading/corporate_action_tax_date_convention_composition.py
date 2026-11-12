"""Read one explicit simulation-only tax-date rule from current Config Center evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, TypedDict, TypeGuard, cast

from apps.config_center.application.runtime_value_evidence import (
    ActiveRuntimeValueEvidence,
    read_active_runtime_value_evidence,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.simulated_tax_date_convention import (
    SimulatedDividendTaxDateConvention,
)
from core.exceptions import BusinessLogicError

SIMULATED_TAX_DATE_CONVENTION_KEY = "config_center.simulated_trading.dividend_tax_date_conventions"
_SCHEMA_VERSION = "simulated-dividend-tax-date-conventions.v1"
_TOP_FIELDS = frozenset({"schema_version", "enabled", "policies"})
_POLICY_FIELDS = frozenset(
    {
        "convention_id",
        "version",
        "physical_account_id",
        "canonical_account_id",
        "owner_user_id",
        "exchange",
        "purchase_open_session_offset",
        "sale_open_session_offset",
        "trade_window_start",
        "trade_window_end",
        "valid_from",
        "valid_until",
        "approval_ref",
    }
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class SimulatedDividendTaxDatePolicyJSON(TypedDict):
    """Exact per-account JSON rule; runtime known-at is supplied separately."""

    convention_id: str
    version: str
    physical_account_id: int
    canonical_account_id: str
    owner_user_id: int
    exchange: str
    purchase_open_session_offset: int
    sale_open_session_offset: int
    trade_window_start: str
    trade_window_end: str
    valid_from: str
    valid_until: str
    approval_ref: str


class SimulatedDividendTaxDateConventionsJSON(TypedDict):
    """Strict current runtime value for explicitly configured simulations."""

    schema_version: str
    enabled: bool
    policies: list[SimulatedDividendTaxDatePolicyJSON]


class SimulatedDividendTaxDateConventionUnavailable(BusinessLogicError):
    """The current explicit simulation date rule is absent or cannot be trusted."""

    default_message = "当前模拟税务日期规则缺失或无效"
    default_code = "SIMULATED_TAX_DATE_CONVENTION_UNAVAILABLE"


def _invalid(field: str, reason: str) -> SimulatedDividendTaxDateConventionUnavailable:
    """Create one stable application error without echoing runtime values."""

    return SimulatedDividendTaxDateConventionUnavailable(f"{field}: {reason}")


def _is_string_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow an exact JSON object with exact string keys."""

    return type(value) is dict and all(
        type(key) is str for key in cast(dict[object, object], value)
    )


def _require_object(
    value: object,
    *,
    fields: frozenset[str],
    field: str,
) -> dict[str, object]:
    """Require all and only the declared fields in one JSON object."""

    if not _is_string_object(value):
        raise _invalid(field, "must be an exact JSON object with string keys")
    if frozenset(value) != fields:
        raise _invalid(field, "required fields are missing or unknown fields are present")
    return value


def _require_string(value: object, *, field: str) -> str:
    """Require an exact string without implicit conversion."""

    if type(value) is not str:
        raise _invalid(field, "must be an exact string")
    return value


def _require_positive_int(value: object, *, field: str) -> int:
    """Require a positive JSON integer and reject booleans."""

    if type(value) is not int or value <= 0:
        raise _invalid(field, "must be a positive exact integer")
    return value


def _require_nonnegative_int(value: object, *, field: str) -> int:
    """Require an explicit nonnegative JSON integer and reject booleans."""

    if type(value) is not int or value < 0:
        raise _invalid(field, "must be a nonnegative exact integer")
    return value


def _require_token(value: object, *, field: str) -> str:
    """Require a bounded stable identifier using the Domain token contract."""

    if type(value) is not str or not value or value != value.strip() or len(value) > 192:
        raise _invalid(field, "must be an explicit bounded token")
    if any(character.isspace() for character in value):
        raise _invalid(field, "must not contain whitespace")
    return value


def _utc_clock(value: object, *, field: str) -> datetime:
    """Require a representable aware instant and return its UTC comparison value."""

    if type(value) is not datetime:
        raise _invalid(field, "must be a timezone-aware datetime")
    try:
        if value.utcoffset() is None:
            raise _invalid(field, "must be a timezone-aware datetime")
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise _invalid(field, "must be a representable timezone-aware instant") from error


def _parse_date(value: object, *, field: str) -> date:
    """Parse only canonical YYYY-MM-DD date text."""

    text = _require_string(value, field=field)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise _invalid(field, "must be canonical YYYY-MM-DD text") from error
    if parsed.isoformat() != text:
        raise _invalid(field, "must be canonical YYYY-MM-DD text")
    return parsed


def _parse_clock(value: object, *, field: str) -> datetime:
    """Parse a canonical ISO datetime with an explicit UTC offset."""

    text = _require_string(value, field=field)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise _invalid(field, "must be a canonical aware ISO datetime") from error
    if parsed.isoformat() != text:
        raise _invalid(field, "must be a canonical aware ISO datetime")
    _utc_clock(parsed, field=field)
    return parsed


def _parse_policy(
    value: object,
    *,
    index: int,
    known_at: datetime,
) -> SimulatedDividendTaxDateConvention:
    """Narrow one exact account policy into the simulation Domain value."""

    field = f"policies[{index}]"
    raw = _require_object(value, fields=_POLICY_FIELDS, field=field)
    item = cast(SimulatedDividendTaxDatePolicyJSON, raw)
    try:
        return SimulatedDividendTaxDateConvention(
            convention_id=_require_token(item["convention_id"], field=f"{field}.convention_id"),
            version=_require_token(item["version"], field=f"{field}.version"),
            physical_account_id=_require_positive_int(
                item["physical_account_id"], field=f"{field}.physical_account_id"
            ),
            canonical_account_id=_require_token(
                item["canonical_account_id"], field=f"{field}.canonical_account_id"
            ),
            owner_user_id=_require_positive_int(
                item["owner_user_id"], field=f"{field}.owner_user_id"
            ),
            exchange=_require_token(item["exchange"], field=f"{field}.exchange"),
            purchase_open_session_offset=_require_nonnegative_int(
                item["purchase_open_session_offset"],
                field=f"{field}.purchase_open_session_offset",
            ),
            sale_open_session_offset=_require_nonnegative_int(
                item["sale_open_session_offset"], field=f"{field}.sale_open_session_offset"
            ),
            trade_window_start=_parse_date(
                item["trade_window_start"], field=f"{field}.trade_window_start"
            ),
            trade_window_end=_parse_date(
                item["trade_window_end"], field=f"{field}.trade_window_end"
            ),
            valid_from=_parse_clock(item["valid_from"], field=f"{field}.valid_from"),
            valid_until=_parse_clock(item["valid_until"], field=f"{field}.valid_until"),
            known_at=known_at,
            approval_ref=_require_token(item["approval_ref"], field=f"{field}.approval_ref"),
        )
    except (DeferredDividendTaxValidationError, OverflowError, TypeError, ValueError) as error:
        raise _invalid(field, "failed Domain validation") from error


def _validate_runtime_provenance(
    *,
    environment: str,
    definition_key: str,
    profile_id: str,
    profile_key: str,
    profile_version: int,
    profile_content_hash: str,
    snapshot_id: str,
    snapshot_hash: str,
    created_at: datetime,
    known_at: datetime,
    activated_at: datetime,
    snapshot_generated_at: datetime,
    effective_at: datetime,
    as_of: datetime,
) -> None:
    """Recheck the public Config Center identity and clock relationships."""

    for name, value in (
        ("environment", environment),
        ("definition_key", definition_key),
        ("profile_id", profile_id),
        ("profile_key", profile_key),
        ("snapshot_id", snapshot_id),
    ):
        _require_token(value, field=name)
    if type(profile_version) is not int or profile_version <= 0:
        raise _invalid("profile_version", "must be a positive exact integer")
    for name, value in (
        ("profile_content_hash", profile_content_hash),
        ("snapshot_hash", snapshot_hash),
    ):
        if type(value) is not str or _SHA256.fullmatch(value) is None:
            raise _invalid(name, "must be a lowercase SHA-256 digest")

    as_of_utc = _utc_clock(as_of, field="as_of")
    clocks = {
        "created_at": created_at,
        "known_at": known_at,
        "activated_at": activated_at,
        "snapshot_generated_at": snapshot_generated_at,
        "effective_at": effective_at,
    }
    normalized = {name: _utc_clock(value, field=name) for name, value in clocks.items()}
    if any(value > as_of_utc for value in normalized.values()):
        raise _invalid("runtime_clocks", "must not be later than the requested cutoff")
    if normalized["created_at"] != normalized["known_at"]:
        raise _invalid("known_at", "must preserve Config Center profile creation time")
    if normalized["activated_at"] != normalized["effective_at"]:
        raise _invalid("effective_at", "must match the active snapshot effective time")
    if not (
        normalized["created_at"]
        <= normalized["activated_at"]
        <= normalized["snapshot_generated_at"]
        <= as_of_utc
    ):
        raise _invalid("runtime_clocks", "profile and snapshot clocks are out of order")


@dataclass(frozen=True, slots=True)
class ConfiguredSimulatedDividendTaxDateConvention:
    """Configured simulation hypothesis and the active runtime observation that supplied it.

    This binding proves only what Config Center currently returned at ``as_of``.
    It is not legal-source qualification, a real-account custody date, or posting
    authority.
    """

    convention: SimulatedDividendTaxDateConvention
    account_kind: Literal["simulated"]
    environment: str
    definition_key: str
    profile_id: str
    profile_key: str
    profile_version: int
    profile_content_hash: str
    snapshot_id: str
    snapshot_hash: str
    created_at: datetime
    known_at: datetime
    activated_at: datetime
    snapshot_generated_at: datetime
    effective_at: datetime
    as_of: datetime

    def __post_init__(self) -> None:
        """Revalidate the scope, active window, and all runtime provenance clocks."""

        if type(self.convention) is not SimulatedDividendTaxDateConvention:
            raise _invalid("convention", "must be the exact simulation Domain type")
        try:
            self.convention.__post_init__()
        except (DeferredDividendTaxValidationError, OverflowError, TypeError, ValueError) as error:
            raise _invalid("convention", "failed Domain validation") from error
        if type(self.account_kind) is not str or self.account_kind != "simulated":
            raise _invalid("account_kind", "real-account dates are not modeled here")
        if self.definition_key != SIMULATED_TAX_DATE_CONVENTION_KEY:
            raise _invalid("definition_key", "does not identify the explicit tax-date setting")
        _validate_runtime_provenance(
            environment=self.environment,
            definition_key=self.definition_key,
            profile_id=self.profile_id,
            profile_key=self.profile_key,
            profile_version=self.profile_version,
            profile_content_hash=self.profile_content_hash,
            snapshot_id=self.snapshot_id,
            snapshot_hash=self.snapshot_hash,
            created_at=self.created_at,
            known_at=self.known_at,
            activated_at=self.activated_at,
            snapshot_generated_at=self.snapshot_generated_at,
            effective_at=self.effective_at,
            as_of=self.as_of,
        )
        as_of_utc = _utc_clock(self.as_of, field="as_of")
        if _utc_clock(self.known_at, field="known_at") != _utc_clock(
            self.convention.known_at, field="convention.known_at"
        ):
            raise _invalid("convention.known_at", "must come from active runtime evidence")

        valid_from = _utc_clock(self.convention.valid_from, field="convention.valid_from")
        valid_until = _utc_clock(self.convention.valid_until, field="convention.valid_until")
        if valid_from > as_of_utc or as_of_utc >= valid_until:
            raise _invalid("convention", "is not active at the requested cutoff")


def _validate_runtime_evidence(
    evidence: ActiveRuntimeValueEvidence,
    *,
    environment: str,
    as_of: datetime,
) -> None:
    """Require the evidence returned by Config Center to match this exact read."""

    if type(evidence) is not ActiveRuntimeValueEvidence:
        raise _invalid("runtime_evidence", "must use the Config Center evidence contract")
    if (
        evidence.environment != environment
        or evidence.definition_key != SIMULATED_TAX_DATE_CONVENTION_KEY
    ):
        raise _invalid("runtime_evidence", "environment or definition key does not match")
    if _utc_clock(evidence.as_of, field="runtime_evidence.as_of") != _utc_clock(
        as_of, field="as_of"
    ):
        raise _invalid("runtime_evidence.as_of", "does not match the requested cutoff")
    _validate_runtime_provenance(
        environment=evidence.environment,
        definition_key=evidence.definition_key,
        profile_id=evidence.profile_id,
        profile_key=evidence.profile_key,
        profile_version=evidence.profile_version,
        profile_content_hash=evidence.profile_content_hash,
        snapshot_id=evidence.snapshot_id,
        snapshot_hash=evidence.snapshot_hash,
        created_at=evidence.created_at,
        known_at=evidence.known_at,
        activated_at=evidence.activated_at,
        snapshot_generated_at=evidence.snapshot_generated_at,
        effective_at=evidence.effective_at,
        as_of=evidence.as_of,
    )


def read_current_simulated_dividend_tax_date_convention(
    *,
    environment: str,
    as_of: datetime,
    account_kind: str,
    physical_account_id: int,
    canonical_account_id: str,
    owner_user_id: int,
) -> ConfiguredSimulatedDividendTaxDateConvention:
    """Select the unique current simulation rule for the exact requested owner account.

    Missing, disabled, malformed, duplicate, inactive, stale, or mismatched
    configuration blocks this tax-date consumer. No prior runtime profile or
    real-account date convention is used as fallback.
    """

    _require_token(environment, field="environment")
    requested_canonical = _require_token(canonical_account_id, field="canonical_account_id")
    physical_id = _require_positive_int(physical_account_id, field="physical_account_id")
    owner_id = _require_positive_int(owner_user_id, field="owner_user_id")
    if type(account_kind) is not str or account_kind != "simulated":
        raise _invalid("account_kind", "only simulated accounts may use this date convention")
    _utc_clock(as_of, field="as_of")

    evidence = read_active_runtime_value_evidence(
        environment=environment,
        definition_key=SIMULATED_TAX_DATE_CONVENTION_KEY,
        as_of=as_of,
    )
    if evidence is None:
        raise _invalid("runtime_evidence", "active explicit setting is unavailable")
    _validate_runtime_evidence(evidence, environment=environment, as_of=as_of)

    raw = _require_object(evidence.value, fields=_TOP_FIELDS, field="configuration")
    payload = cast(SimulatedDividendTaxDateConventionsJSON, raw)
    if _require_string(payload["schema_version"], field="schema_version") != _SCHEMA_VERSION:
        raise _invalid("schema_version", "is unsupported")
    if type(payload["enabled"]) is not bool:
        raise _invalid("enabled", "must be an exact boolean")
    raw_policies = payload["policies"]
    if type(raw_policies) is not list or not raw_policies:
        raise _invalid("policies", "must be a nonempty JSON array")
    policies = tuple(
        _parse_policy(item, index=index, known_at=evidence.known_at)
        for index, item in enumerate(cast(list[object], raw_policies))
    )
    if payload["enabled"] is not True:
        raise _invalid("enabled", "explicit simulation date rules are disabled")

    matches = tuple(
        policy for policy in policies if policy.canonical_account_id == requested_canonical
    )
    if len(matches) != 1:
        reason = (
            "has duplicate canonical account rows"
            if len(matches) > 1
            else "has no current account row"
        )
        raise _invalid("policies", reason)
    selected = matches[0]
    if selected.physical_account_id != physical_id or selected.owner_user_id != owner_id:
        raise _invalid("policies", "current canonical row does not match physical account owner")

    try:
        return ConfiguredSimulatedDividendTaxDateConvention(
            convention=selected,
            account_kind="simulated",
            environment=environment,
            definition_key=evidence.definition_key,
            profile_id=evidence.profile_id,
            profile_key=evidence.profile_key,
            profile_version=evidence.profile_version,
            profile_content_hash=evidence.profile_content_hash,
            snapshot_id=evidence.snapshot_id,
            snapshot_hash=evidence.snapshot_hash,
            created_at=evidence.created_at,
            known_at=evidence.known_at,
            activated_at=evidence.activated_at,
            snapshot_generated_at=evidence.snapshot_generated_at,
            effective_at=evidence.effective_at,
            as_of=evidence.as_of,
        )
    except DeferredDividendTaxValidationError as error:
        raise _invalid("convention", "failed final Domain validation") from error


__all__ = [
    "ConfiguredSimulatedDividendTaxDateConvention",
    "SIMULATED_TAX_DATE_CONVENTION_KEY",
    "SimulatedDividendTaxDateConventionUnavailable",
    "read_current_simulated_dividend_tax_date_convention",
]
