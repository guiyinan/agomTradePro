"""Read explicit account-bound share-capital simulation declarations from Config Center."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, cast

from apps.simulated_trading.application.corporate_action_share_tax_model import (
    ShareCapitalTaxModelQuery,
)
from apps.simulated_trading.corporate_action_configuration_composition import (
    CorporateActionConfigurationEvidence,
    read_corporate_action_configuration,
)
from apps.simulated_trading.domain.corporate_action_capital_tax_terms import CapitalTaxSourceOrigin
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionStageRequest
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
    SimulatedDividendTaxExchange,
    SimulatedDividendTaxInstrumentKind,
    SimulatedDividendTaxPersona,
)
from core.exceptions import BusinessLogicError

SHARE_CAPITAL_TAX_MODELS_KEY = "config_center.simulated_trading.share_capital_tax_models"
_SCHEMA = "simulated.corporate_action.share_capital_tax_models.v1"
_MODEL_KIND = "stock_issue_premium_transfer_no_withholding_simulation"
_SCOPE_FIELDS = frozenset(
    {
        "account_kind",
        "physical_account_id",
        "canonical_account_id",
        "owner_user_id",
        "security_id",
        "asset_code",
        "exchange",
        "persona",
        "instrument_kind",
        "currency",
        "capital_source",
    }
)
_ROW_FIELDS = frozenset(
    {
        "enabled",
        "simulation_only",
        "must_not_use_for_real_tax_decision",
        "model_kind",
        "model_rule_id",
        "simulated_asset_type",
        "scope",
        "valid_from",
        "valid_until",
        "record_date_start",
        "record_date_end",
        "statutory_bundle_id",
        "statutory_bundle_version",
        "statutory_source_bundle_sha256",
        "document_1997_id",
        "document_1998_id",
    }
)


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "缺少本账户、本证券适用的显式送转模拟税务模型，请联系管理员核对。",
        code="SHARE_CAPITAL_TAX_MODEL_CONFIGURATION_UNAVAILABLE",
    )


def _object(value: object, fields: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise _blocked()
    return cast(dict[str, object], value)


def _text(value: object, *, maximum: int = 240) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or value != value.strip()
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        raise _blocked()
    return value


def _positive(value: object) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise _blocked()
    return value


def _digest(value: object) -> str:
    text = _text(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise _blocked()
    return text


def _day(value: object) -> date:
    text = _text(value)
    parsed = date.fromisoformat(text)
    if parsed.isoformat() != text:
        raise _blocked()
    return parsed


def _instant(value: object) -> datetime:
    parsed = datetime.fromisoformat(_text(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _blocked()
    return parsed


@dataclass(frozen=True, slots=True)
class ShareCapitalTaxModelDeclaredScope:
    """One explicitly configured simulated account, owner and listed-security scenario."""

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
    capital_source: CapitalTaxSourceOrigin

    def matches(self, query: ShareCapitalTaxModelQuery) -> bool:
        """Match every actual server query field; omitted scope is never a wildcard."""
        query.__post_init__()
        return all(getattr(self, name) == getattr(query, name) for name in _SCOPE_FIELDS)


@dataclass(frozen=True, slots=True)
class ConfiguredShareCapitalTaxModelPolicy:
    """A declared simulation model, not real-holder identity or a statutory effective date."""

    configuration: CorporateActionConfigurationEvidence
    scope: ShareCapitalTaxModelDeclaredScope
    enabled: bool
    model_rule_id: str
    model_rule_sha256: str
    simulated_asset_type: str
    valid_from: datetime
    valid_until: datetime
    record_date_start: date
    record_date_end: date
    statutory_bundle_id: str
    statutory_bundle_version: str
    statutory_source_bundle_sha256: str
    document_1997_id: str
    document_1998_id: str

    def verify_for(self, query: ShareCapitalTaxModelQuery, *, as_of: datetime) -> None:
        """Require the exact enabled declared scenario and both explicit model windows."""
        self.configuration.__post_init__()
        if (
            type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
            or self.enabled is not True
            or not self.scope.matches(query)
            or not self.valid_from <= as_of < self.valid_until
            or not self.record_date_start <= query.record_date <= self.record_date_end
            or self.configuration.known_at > as_of
            or self.configuration.checked_at > as_of
        ):
            raise _blocked()

    @property
    def simulation_only(self) -> Literal[True]:
        """Restrict the declared policy to an explicitly simulated scenario."""
        return True

    @property
    def must_not_use_for_real_tax_decision(self) -> Literal[True]:
        """Retain the independent real-holder and real-tax qualification prohibition."""
        return True


def _scope(value: object) -> ShareCapitalTaxModelDeclaredScope:
    raw = _object(value, _SCOPE_FIELDS)
    if (
        raw["account_kind"] != "simulated"
        or type(raw["account_kind"]) is not str
        or raw["capital_source"] != CapitalTaxSourceOrigin.STOCK_ISSUE_PREMIUM_CAPITAL_RESERVE.value
        or raw["persona"] != SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE.value
        or raw["instrument_kind"] != SimulatedDividendTaxInstrumentKind.LISTED_EQUITY.value
        or raw["currency"] != SimulatedDividendTaxCurrency.CNY.value
    ):
        raise _blocked()
    return ShareCapitalTaxModelDeclaredScope(
        account_kind="simulated",
        physical_account_id=_positive(raw["physical_account_id"]),
        canonical_account_id=_text(raw["canonical_account_id"], maximum=192),
        owner_user_id=_positive(raw["owner_user_id"]),
        security_id=_text(raw["security_id"], maximum=96),
        asset_code=_text(raw["asset_code"], maximum=96),
        exchange=SimulatedDividendTaxExchange(_text(raw["exchange"])),
        persona=SimulatedDividendTaxPersona(_text(raw["persona"])),
        instrument_kind=SimulatedDividendTaxInstrumentKind(_text(raw["instrument_kind"])),
        currency=SimulatedDividendTaxCurrency(_text(raw["currency"])),
        capital_source=CapitalTaxSourceOrigin(_text(raw["capital_source"])),
    )


def _candidate(
    value: object, configuration: CorporateActionConfigurationEvidence
) -> ConfiguredShareCapitalTaxModelPolicy:
    raw = _object(value, _ROW_FIELDS)
    if (
        type(raw["enabled"]) is not bool
        or raw["simulation_only"] is not True
        or raw["must_not_use_for_real_tax_decision"] is not True
        or raw["model_kind"] != _MODEL_KIND
        or type(raw["model_kind"]) is not str
    ):
        raise _blocked()
    start, end = _instant(raw["valid_from"]), _instant(raw["valid_until"])
    record_start, record_end = _day(raw["record_date_start"]), _day(raw["record_date_end"])
    first, second = _text(raw["document_1997_id"]), _text(raw["document_1998_id"])
    if start >= end or record_start > record_end or first == second:
        raise _blocked()
    digest = hashlib.sha256(
        json.dumps(
            raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return ConfiguredShareCapitalTaxModelPolicy(
        configuration=configuration,
        scope=_scope(raw["scope"]),
        enabled=raw["enabled"],
        model_rule_id=_text(raw["model_rule_id"], maximum=192),
        model_rule_sha256=digest,
        simulated_asset_type=_text(raw["simulated_asset_type"]),
        valid_from=start,
        valid_until=end,
        record_date_start=record_start,
        record_date_end=record_end,
        statutory_bundle_id=_text(raw["statutory_bundle_id"]),
        statutory_bundle_version=_text(raw["statutory_bundle_version"], maximum=120),
        statutory_source_bundle_sha256=_digest(raw["statutory_source_bundle_sha256"]),
        document_1997_id=first,
        document_1998_id=second,
    )


def read_current_share_capital_tax_policy(
    *,
    query: ShareCapitalTaxModelQuery,
    environment: str,
    as_of: datetime,
) -> ConfiguredShareCapitalTaxModelPolicy:
    """Select exactly one fully declared current model without seeding or inference."""
    try:
        if type(query) is not ShareCapitalTaxModelQuery:
            raise _blocked()
        query.__post_init__()
        configuration = read_corporate_action_configuration(
            definition_key=SHARE_CAPITAL_TAX_MODELS_KEY, environment=environment, as_of=as_of
        )
        if (
            configuration.environment != environment
            or configuration.definition_key != SHARE_CAPITAL_TAX_MODELS_KEY
        ):
            raise _blocked()
        payload = _object(json.loads(configuration.value_json), frozenset({"schema", "models"}))
        if payload["schema"] != _SCHEMA or type(payload["models"]) is not list:
            raise _blocked()
        rows = cast(list[object], payload["models"])
        if not 0 < len(rows) <= 10_000:
            raise _blocked()
        candidates = tuple(_candidate(row, configuration) for row in rows)
        matching = tuple(candidate for candidate in candidates if candidate.scope.matches(query))
        if len(matching) != 1:
            raise _blocked()
        result = matching[0]
        result.verify_for(query, as_of=configuration.checked_at)
        if configuration.known_at > as_of:
            raise _blocked()
        return result
    except BusinessLogicError:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _blocked() from error


def read_share_capital_tax_policy_for_stage(
    *,
    request: CorporateActionStageRequest,
    canonical_account_id: str,
    environment: str,
    as_of: datetime,
) -> ConfiguredShareCapitalTaxModelPolicy:
    """Select a declaration by actual owner/security/date before reading its explicit persona.

    The caller must independently qualify the official body, source lineage and
    instrument. A configured persona is a simulation label, never taxpayer proof.
    """
    try:
        request.__post_init__()
        configuration = read_corporate_action_configuration(
            definition_key=SHARE_CAPITAL_TAX_MODELS_KEY, environment=environment, as_of=as_of
        )
        if (
            configuration.environment != environment
            or configuration.definition_key != SHARE_CAPITAL_TAX_MODELS_KEY
        ):
            raise _blocked()
        payload = _object(json.loads(configuration.value_json), frozenset({"schema", "models"}))
        if payload["schema"] != _SCHEMA or type(payload["models"]) is not list:
            raise _blocked()
        rows = cast(list[object], payload["models"])
        if not 0 < len(rows) <= 10_000:
            raise _blocked()
        candidates = tuple(_candidate(row, configuration) for row in rows)
        matches = tuple(
            item
            for item in candidates
            if (
                item.scope.physical_account_id == request.account_id
                and item.scope.canonical_account_id == canonical_account_id
                and item.scope.owner_user_id == request.owner_user_id
                and item.scope.security_id == request.security_id
                and item.scope.asset_code == request.asset_code
            )
        )
        if len(matches) != 1:
            raise _blocked()
        result = matches[0]
        if (
            result.enabled is not True
            or not result.valid_from <= configuration.checked_at < result.valid_until
            or not result.record_date_start <= request.record_date <= result.record_date_end
            or configuration.known_at > as_of
        ):
            raise _blocked()
        return result
    except BusinessLogicError:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _blocked() from error
