"""Application contracts for an explicit simulated share-capital tax model.

The model binds one simulated scenario to source text and current configured
policy. It never authenticates a real holder, decides real tax eligibility, or
grants financial authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, Protocol, runtime_checkable

from apps.simulated_trading.domain.corporate_action_capital_tax_terms import (
    CapitalTaxSourceDocumentId,
    CapitalTaxSourceOrigin,
    ParsedShareCapitalTaxSourceTerms,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
    SimulatedDividendTaxExchange,
    SimulatedDividendTaxInstrumentKind,
    SimulatedDividendTaxPersona,
)
from core.exceptions import BusinessLogicError

_INVALID = "SHARE_CAPITAL_TAX_MODEL_INVALID"
_SOURCE_NAMESPACE = "exchange_official_disclosure"
_SHARE_STAGES = frozenset(
    {
        CorporateActionStage.SHARE_ENTITLEMENT,
        CorporateActionStage.SHARE_DELIVERY,
        CorporateActionStage.SHARE_SELLABLE_RELEASE,
    }
)
_ENTRY_KINDS = frozenset(
    {
        CorporateActionEntryKind.POSTING,
        CorporateActionEntryKind.REVERSAL,
        CorporateActionEntryKind.SUCCESSOR,
    }
)


def _invalid(message: str) -> BusinessLogicError:
    """Return one stable error for an incomplete or mismatched model contract."""

    return BusinessLogicError(message, code=_INVALID)


def _token(value: object, field_name: str, *, maximum: int = 192) -> str:
    """Require one bounded canonical UTF-8 token."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        raise _invalid(f"{field_name} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise _invalid(f"{field_name} is invalid") from error
    return value


def _digest(value: object, field_name: str) -> str:
    """Require one lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _invalid(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _utc(value: object, field_name: str) -> datetime:
    """Require an exact aware instant and normalize it for comparison."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _invalid(f"{field_name} must be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise _invalid(f"{field_name} is outside the representable UTC range") from error


def _date(value: object, field_name: str) -> date:
    """Require an exact date and reject datetime subclasses."""

    if type(value) is not date:
        raise _invalid(f"{field_name} must be an exact calendar date")
    return value


@dataclass(frozen=True, slots=True)
class ShareCapitalTaxModelQuery:
    """Server-built scope for one explicit simulated shareholder scenario.

    Source namespace, event/revision/body identities, holder/account scope,
    action stage, and original dates are all required. This query is not a
    public client input and its persona is a model label, not holder evidence.
    ``effective_date`` is the source-confirmed event date, not a statutory
    effective date; only configured model policy supplies its validity window.
    """

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
    source_namespace: str
    source_record_id: str
    source_event_id: str
    source_revision_id: str
    source_revision_sha256: str
    source_payload_sha256: str
    action_kind: CorporateActionKind
    stage: CorporateActionStage
    entry_kind: CorporateActionEntryKind
    capital_source: CapitalTaxSourceOrigin
    record_date: date
    effective_date: date
    stage_date: date
    source_observed_at: datetime

    def __post_init__(self) -> None:
        """Validate every exact query identity and the bounded model scenario."""

        if type(self.account_kind) is not str or self.account_kind != "simulated":
            raise _invalid("only an explicitly simulated account model is supported")
        for name, identifier in (
            ("physical_account_id", self.physical_account_id),
            ("owner_user_id", self.owner_user_id),
        ):
            if type(identifier) is not int or identifier <= 0:
                raise _invalid(f"{name} must be a positive exact integer")
        _token(self.canonical_account_id, "canonical_account_id")
        _token(self.security_id, "security_id", maximum=96)
        _token(self.asset_code, "asset_code", maximum=96)
        _token(self.source_namespace, "source_namespace", maximum=128)
        _token(self.source_record_id, "source_record_id")
        _token(self.source_event_id, "source_event_id")
        _token(self.source_revision_id, "source_revision_id")
        _digest(self.source_revision_sha256, "source_revision_sha256")
        _digest(self.source_payload_sha256, "source_payload_sha256")
        if self.source_namespace != _SOURCE_NAMESPACE:
            raise _invalid(
                "only an independently qualified official disclosure namespace is modeled"
            )
        if type(self.exchange) is not SimulatedDividendTaxExchange:
            raise _invalid("an explicit supported simulated exchange is required")
        if self.persona is not SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE:
            raise _invalid("only the explicit simulated domestic A-share persona is modeled")
        if self.instrument_kind is not SimulatedDividendTaxInstrumentKind.LISTED_EQUITY:
            raise _invalid("only the explicit simulated listed-equity model is supported")
        if self.currency is not SimulatedDividendTaxCurrency.CNY:
            raise _invalid("only the explicit simulated CNY model is supported")
        if self.asset_code != self.security_id:
            raise _invalid("security and asset identity must match this explicit model")
        if re.fullmatch(
            r"[0-9]{6}\.(?:SH|SZ)", self.asset_code
        ) is None or not self.asset_code.endswith(f".{self.exchange.value}"):
            raise _invalid("canonical A-share security and exchange must agree")
        if type(self.action_kind) is not CorporateActionKind or (
            self.action_kind is not CorporateActionKind.SHARE_DISTRIBUTION
        ):
            raise _invalid("only a qualified share-distribution action is supported")
        if type(self.stage) is not CorporateActionStage or self.stage not in _SHARE_STAGES:
            raise _invalid("only an explicit share-distribution stage is supported")
        if (
            type(self.entry_kind) is not CorporateActionEntryKind
            or self.entry_kind not in _ENTRY_KINDS
        ):
            raise _invalid("the share stage entry kind is unsupported")
        if type(self.capital_source) is not CapitalTaxSourceOrigin:
            raise _invalid("a capital source origin must be explicit")
        for name, calendar_date in (
            ("record_date", self.record_date),
            ("effective_date", self.effective_date),
            ("stage_date", self.stage_date),
        ):
            _date(calendar_date, name)
        _utc(self.source_observed_at, "source_observed_at")

    def semantic_payload(self) -> dict[str, object]:
        """Return every immutable scope field for stable exact binding."""

        self.__post_init__()
        return {
            "schema": "simulated-share-capital-tax-model-query.v1",
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
            "source_namespace": self.source_namespace,
            "source_record_id": self.source_record_id,
            "source_event_id": self.source_event_id,
            "source_revision_id": self.source_revision_id,
            "source_revision_sha256": self.source_revision_sha256,
            "source_payload_sha256": self.source_payload_sha256,
            "action_kind": self.action_kind.value,
            "stage": self.stage.value,
            "entry_kind": self.entry_kind.value,
            "capital_source": self.capital_source.value,
            "record_date": self.record_date.isoformat(),
            "effective_date": self.effective_date.isoformat(),
            "stage_date": self.stage_date.isoformat(),
            "source_observed_at": _utc(self.source_observed_at, "source_observed_at").isoformat(),
        }

    @property
    def semantic_sha256(self) -> str:
        """Hash the complete selected action and simulated holder scope."""

        payload = self.semantic_payload()
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ShareCapitalTaxSourceReference:
    """One original Data Center capture mapped to its exact parser body."""

    document_id: CapitalTaxSourceDocumentId
    issuer: str
    source_version: str
    source_revision_sha256: str
    body_sha256: str
    capture_id: str
    captured_at: datetime

    def __post_init__(self) -> None:
        """Validate source identity, revision, body digest, and original clock."""

        if type(self.document_id) is not CapitalTaxSourceDocumentId:
            raise _invalid("retained statutory source identity is unsupported")
        _token(self.issuer, "source.issuer", maximum=240)
        _token(self.source_version, "source.source_version", maximum=120)
        _digest(self.source_revision_sha256, "source.source_revision_sha256")
        _digest(self.body_sha256, "source.body_sha256")
        _token(self.capture_id, "source.capture_id", maximum=64)
        _utc(self.captured_at, "source.captured_at")


@dataclass(frozen=True, slots=True)
class CurrentShareCapitalTaxModel:
    """Finite current-config model for one simulated personal-shareholder scope.

    The record binds the two exact retained source revisions to an explicit
    model rule and Config Center read. It never reports actual holder identity,
    real tax eligibility, or permission to write any financial stage.
    """

    query_semantic_sha256: str
    persona: SimulatedDividendTaxPersona
    capital_source: CapitalTaxSourceOrigin
    source_terms: ParsedShareCapitalTaxSourceTerms
    source_1997_198: ShareCapitalTaxSourceReference
    source_1998_289: ShareCapitalTaxSourceReference
    model_rule_id: str
    model_rule_sha256: str
    runtime_profile_id: str
    runtime_profile_content_sha256: str
    runtime_snapshot_id: str
    runtime_snapshot_sha256: str
    known_at: datetime
    valid_from: datetime
    valid_until: datetime
    checked_at: datetime

    def __post_init__(self) -> None:
        """Require a complete explicit model record and exact retained source pair."""

        _digest(self.query_semantic_sha256, "query_semantic_sha256")
        if self.persona is not SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE:
            raise _invalid("the configured model must name its explicit simulated persona")
        if type(self.capital_source) is not CapitalTaxSourceOrigin:
            raise _invalid("the configured model must name its explicit capital origin")
        if type(self.source_terms) is not ParsedShareCapitalTaxSourceTerms:
            raise _invalid("both exact source documents must be parsed and paired")
        self.source_terms.__post_init__()
        if type(self.source_1997_198) is not ShareCapitalTaxSourceReference or (
            self.source_1997_198.document_id is not CapitalTaxSourceDocumentId.SAT_1997_198
        ):
            raise _invalid("the retained 1997/198 source reference is invalid")
        if type(self.source_1998_289) is not ShareCapitalTaxSourceReference or (
            self.source_1998_289.document_id is not CapitalTaxSourceDocumentId.SAT_1998_289
        ):
            raise _invalid("the retained 1998/289 source reference is invalid")
        for reference in (self.source_1997_198, self.source_1998_289):
            reference.__post_init__()
        if (
            self.source_1997_198.issuer != self.source_terms.source_1997_198.issuer
            or self.source_1998_289.issuer != self.source_terms.source_1998_289.issuer
            or self.source_1997_198.body_sha256 != self.source_terms.source_1997_198.body_sha256
            or self.source_1998_289.body_sha256 != self.source_terms.source_1998_289.body_sha256
        ):
            raise _invalid("retained source references differ from parsed original bodies")
        _token(self.model_rule_id, "model_rule_id")
        _digest(self.model_rule_sha256, "model_rule_sha256")
        _token(self.runtime_profile_id, "runtime_profile_id")
        _digest(self.runtime_profile_content_sha256, "runtime_profile_content_sha256")
        _token(self.runtime_snapshot_id, "runtime_snapshot_id")
        _digest(self.runtime_snapshot_sha256, "runtime_snapshot_sha256")
        known = _utc(self.known_at, "known_at")
        valid_from = _utc(self.valid_from, "valid_from")
        valid_until = _utc(self.valid_until, "valid_until")
        checked = _utc(self.checked_at, "checked_at")
        if not valid_from <= checked < valid_until or known > checked:
            raise _invalid("model knowledge, validity, or check clocks are unordered")
        if any(
            _utc(reference.captured_at, "source.captured_at") > known
            for reference in (
                self.source_1997_198,
                self.source_1998_289,
            )
        ):
            raise _invalid("a retained source capture occurs after the model's original knowledge")

    @property
    def simulation_only(self) -> Literal[True]:
        """Declare that this configured value applies only to a simulation model."""

        return True

    @property
    def must_not_use_for_real_tax_decision(self) -> Literal[True]:
        """Keep this model ineligible for real-holder or real-tax decisions."""

        return True

    def verify_for(self, query: ShareCapitalTaxModelQuery, *, as_of: datetime) -> None:
        """Require the exact original action scope within the configured window."""

        if type(query) is not ShareCapitalTaxModelQuery:
            raise _invalid("an exact typed server-built model query is required")
        query.__post_init__()
        self.__post_init__()
        cutoff = _utc(as_of, "as_of")
        if (
            query.semantic_sha256 != self.query_semantic_sha256
            or query.persona is not self.persona
            or query.capital_source is not self.capital_source
        ):
            raise _invalid("current model differs from the exact selected source and account scope")
        if (
            cutoff < _utc(self.known_at, "known_at")
            or cutoff < _utc(self.checked_at, "checked_at")
            or cutoff < _utc(self.valid_from, "valid_from")
            or cutoff >= _utc(self.valid_until, "valid_until")
            or cutoff < _utc(query.source_observed_at, "source_observed_at")
            or _utc(self.known_at, "known_at")
            < _utc(query.source_observed_at, "source_observed_at")
            or _utc(query.source_observed_at, "source_observed_at")
            > _utc(self.checked_at, "checked_at")
        ):
            raise _invalid("current model is not known and valid for the selected cutoff")


@runtime_checkable
class CurrentShareCapitalTaxModelPort(Protocol):
    """Read one current explicitly configured simulated share-tax model."""

    def read_current(
        self,
        query: ShareCapitalTaxModelQuery,
        *,
        using: str,
        as_of: datetime,
    ) -> CurrentShareCapitalTaxModel:
        """Return exact finite model evidence or raise without a qualification claim."""


__all__ = [
    "CurrentShareCapitalTaxModel",
    "CurrentShareCapitalTaxModelPort",
    "ShareCapitalTaxModelQuery",
    "ShareCapitalTaxSourceReference",
]
