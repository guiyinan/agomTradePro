"""Explicit simulation-only scope for a currently configured tax-policy candidate.

This value can bind a tax policy to one declared simulation persona, instrument,
account, native source revision-set pin and applicability window. Its fields do
not prove that a legal source is authentic/current or that an account may assess
or withhold tax; trusted adapters must establish those facts separately.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal, NoReturn

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxPolicy,
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    RecordDateTaxEntitlementRuleKind,
)

_INVALID = "SIMULATED_DIVIDEND_TAX_POLICY_SCOPE_INVALID"
STATUTORY_REVISION_SET_SCHEMA = "statutory-revision-set.v1"


class SimulatedDividendTaxExchange(StrEnum):
    """Supported domestic A-share exchange codes for this explicit simulation scope."""

    SH = "SH"
    SZ = "SZ"


class SimulatedDividendTaxPersona(StrEnum):
    """One supported individual-investor tax applicability persona."""

    DOMESTIC_PUBLIC_MARKET_A_SHARE = "domestic_public_market_a_share"


class SimulatedDividendTaxInstrumentKind(StrEnum):
    """Closed instrument classes whose modeled dividend policy is implemented."""

    LISTED_EQUITY = "listed_equity"


class SimulatedDividendTaxCurrency(StrEnum):
    """Currency supported by the existing yuan-denominated simulated cash ledger."""

    CNY = "CNY"


def _reject(message: str) -> NoReturn:
    """Raise one recognized tax Domain validation error."""

    raise DeferredDividendTaxValidationError(message, _INVALID)


def _token(value: object, field_name: str, *, limit: int = 192) -> str:
    """Require a bounded, whitespace-free UTF-8 identity token."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(character.isspace() for character in value)
    ):
        _reject(f"{field_name} must be an explicit bounded identity")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise DeferredDividendTaxValidationError(
            f"{field_name} must be valid UTF-8", _INVALID
        ) from error
    return value


def _positive_id(value: object, field_name: str) -> int:
    """Require a positive exact integer identifier and reject booleans."""

    if type(value) is not int or value <= 0:
        _reject(f"{field_name} must be a positive exact integer")
    return value


def _date(value: object, field_name: str) -> date:
    """Require an exact calendar date rather than a datetime subclass."""

    if type(value) is not date:
        _reject(f"{field_name} must be an exact calendar date")
    return value


def _digest(value: object, field_name: str) -> str:
    """Require one lowercase SHA-256 source-set pin."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _reject(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _utc(value: object, field_name: str) -> datetime:
    """Require a representable aware instant and return its UTC comparison value."""

    if type(value) is not datetime or value.tzinfo is None:
        _reject(f"{field_name} must be an aware datetime")
    try:
        if value.utcoffset() is None:
            _reject(f"{field_name} must be an aware datetime")
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise DeferredDividendTaxValidationError(
            f"{field_name} is outside the representable UTC range", _INVALID
        ) from error


def _utc_text(value: datetime) -> str:
    """Serialize an already validated instant at canonical UTC precision."""

    return _utc(value, "runtime clock").isoformat(timespec="microseconds")


def _sha256(payload: dict[str, object]) -> str:
    """Hash one complete, typed semantic policy-scope payload."""

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise DeferredDividendTaxValidationError(
            "tax policy scope contains noncanonical facts", _INVALID
        ) from error
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SimulatedDividendTaxPolicyScope:
    """One explicit candidate policy for one simulated account and instrument.

    ``known_at`` is the Config Center profile-creation clock. It is retained as
    observation provenance but excluded from semantic identity; repeated reads
    of unchanged terms do not create a different policy candidate hash.
    """

    candidate_id: str
    candidate_version: str
    account_kind: Literal["simulated"]
    physical_account_id: int
    canonical_account_id: str
    owner_user_id: int
    security_id: str
    asset_code: str
    exchange: SimulatedDividendTaxExchange
    persona: SimulatedDividendTaxPersona
    instrument_kind: SimulatedDividendTaxInstrumentKind
    currency: SimulatedDividendTaxCurrency
    record_date_entitlement_rule: RecordDateTaxEntitlementRuleKind
    applicability_ref: str
    record_date_from: date
    record_date_through: date
    valid_from: datetime
    valid_until: datetime
    known_at: datetime
    statutory_bundle_id: str
    statutory_bundle_version: str
    statutory_revision_set_sha256: str
    tax_policy: DeferredDividendTaxPolicy

    def __post_init__(self) -> None:
        """Reject incomplete, unsupported, or internally inconsistent scope facts."""

        for field_name, value in (
            ("candidate_id", self.candidate_id),
            ("candidate_version", self.candidate_version),
            ("canonical_account_id", self.canonical_account_id),
            ("security_id", self.security_id),
            ("asset_code", self.asset_code),
            ("applicability_ref", self.applicability_ref),
            ("statutory_bundle_id", self.statutory_bundle_id),
            ("statutory_bundle_version", self.statutory_bundle_version),
        ):
            _token(value, field_name)
        if type(self.account_kind) is not str or self.account_kind != "simulated":
            _reject("only the explicit simulated account kind is supported")
        _positive_id(self.physical_account_id, "physical_account_id")
        _positive_id(self.owner_user_id, "owner_user_id")
        if type(self.exchange) is not SimulatedDividendTaxExchange:
            _reject("exchange is outside the supported domestic A-share set")
        if type(self.persona) is not SimulatedDividendTaxPersona:
            _reject("investor persona is unsupported or implicit")
        if type(self.instrument_kind) is not SimulatedDividendTaxInstrumentKind:
            _reject("instrument kind is unsupported or implicit")
        if type(self.record_date_entitlement_rule) is not RecordDateTaxEntitlementRuleKind:
            _reject("record-date entitlement coverage must be explicitly declared")
        if type(self.currency) is not SimulatedDividendTaxCurrency:
            _reject("tax currency is unsupported or implicit")
        start = _date(self.record_date_from, "record_date_from")
        through = _date(self.record_date_through, "record_date_through")
        if start > through:
            _reject("record-date applicability range is reversed")
        valid_from = _utc(self.valid_from, "valid_from")
        valid_until = _utc(self.valid_until, "valid_until")
        _utc(self.known_at, "known_at")
        if valid_from >= valid_until:
            _reject("current candidate validity must be finite and ordered")
        _digest(self.statutory_revision_set_sha256, "statutory_revision_set_sha256")
        if type(self.tax_policy) is not DeferredDividendTaxPolicy:
            _reject("candidate requires the existing typed deferred-tax policy")
        try:
            self.tax_policy.__post_init__()
        except (OverflowError, TypeError, ValueError) as error:
            raise DeferredDividendTaxValidationError(
                "configured tax policy failed Domain validation", _INVALID
            ) from error
        expected_identity = f"{STATUTORY_REVISION_SET_SCHEMA}:{self.statutory_revision_set_sha256}"
        if (
            self.tax_policy.source_identity != expected_identity
            or self.tax_policy.source_sha256 != self.statutory_revision_set_sha256
        ):
            _reject("policy source identity/hash differs from the declared native revision set")
        if self.tax_policy.effective_from > start or (
            self.tax_policy.effective_through is not None
            and self.tax_policy.effective_through < through
        ):
            _reject("tax policy effective dates do not cover the candidate record-date range")

    def semantic_payload(self) -> dict[str, object]:
        """Return all candidate terms except the separate runtime known-at clock."""

        self.__post_init__()
        return {
            "schema": "simulated-dividend-tax-policy-scope.v1",
            "candidate_id": self.candidate_id,
            "candidate_version": self.candidate_version,
            "account_kind": self.account_kind,
            "physical_account_id": self.physical_account_id,
            "canonical_account_id": self.canonical_account_id,
            "owner_user_id": self.owner_user_id,
            "security_id": self.security_id,
            "asset_code": self.asset_code,
            "exchange": self.exchange.value,
            "persona": self.persona.value,
            "instrument_kind": self.instrument_kind.value,
            "currency": self.currency.value,
            "record_date_entitlement_rule": self.record_date_entitlement_rule.value,
            "applicability_ref": self.applicability_ref,
            "record_date_from": self.record_date_from.isoformat(),
            "record_date_through": self.record_date_through.isoformat(),
            "valid_from": _utc_text(self.valid_from),
            "valid_until": _utc_text(self.valid_until),
            "statutory_bundle_id": self.statutory_bundle_id,
            "statutory_bundle_version": self.statutory_bundle_version,
            "statutory_revision_set_sha256": self.statutory_revision_set_sha256,
            "tax_policy_sha256": self.tax_policy.policy_sha256,
        }

    @property
    def semantic_sha256(self) -> str:
        """Hash the exact scoped candidate without granting source or write authority."""

        return _sha256(self.semantic_payload())

    def verify_for(
        self,
        *,
        account_kind: str,
        physical_account_id: int,
        canonical_account_id: str,
        owner_user_id: int,
        security_id: str,
        asset_code: str,
        exchange: SimulatedDividendTaxExchange,
        persona: SimulatedDividendTaxPersona,
        instrument_kind: SimulatedDividendTaxInstrumentKind,
        record_date: date,
        as_of: datetime,
    ) -> None:
        """Require exact account/instrument/persona scope and current validity."""

        self.__post_init__()
        _positive_id(physical_account_id, "requested.physical_account_id")
        _positive_id(owner_user_id, "requested.owner_user_id")
        _token(canonical_account_id, "requested.canonical_account_id")
        _token(security_id, "requested.security_id")
        _token(asset_code, "requested.asset_code")
        selected_date = _date(record_date, "requested.record_date")
        current = _utc(as_of, "as_of")
        if (
            type(account_kind) is not str
            or account_kind != "simulated"
            or physical_account_id != self.physical_account_id
            or canonical_account_id != self.canonical_account_id
            or owner_user_id != self.owner_user_id
            or security_id != self.security_id
            or asset_code != self.asset_code
            or type(exchange) is not SimulatedDividendTaxExchange
            or exchange is not self.exchange
            or type(persona) is not SimulatedDividendTaxPersona
            or persona is not self.persona
            or type(instrument_kind) is not SimulatedDividendTaxInstrumentKind
            or instrument_kind is not self.instrument_kind
        ):
            _reject("current candidate differs from the exact simulated owner or instrument")
        if not self.record_date_from <= selected_date <= self.record_date_through:
            _reject("record date is outside the explicit candidate applicability window")
        if not self.tax_policy.effective_from <= selected_date or (
            self.tax_policy.effective_through is not None
            and selected_date > self.tax_policy.effective_through
        ):
            _reject("record date is outside the injected tax-policy effective window")
        if _utc(self.known_at, "known_at") > current:
            _reject("candidate policy was not known at the requested cutoff")
        if (
            not _utc(self.valid_from, "valid_from")
            <= current
            < _utc(self.valid_until, "valid_until")
        ):
            _reject("candidate is not current at the requested cutoff")


__all__ = [
    "STATUTORY_REVISION_SET_SCHEMA",
    "SimulatedDividendTaxExchange",
    "SimulatedDividendTaxCurrency",
    "SimulatedDividendTaxInstrumentKind",
    "SimulatedDividendTaxPersona",
    "SimulatedDividendTaxPolicyScope",
]
