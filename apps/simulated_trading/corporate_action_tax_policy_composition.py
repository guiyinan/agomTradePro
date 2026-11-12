"""Read one exact current Config Center policy candidate for simulated tax."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, TypedDict, TypeGuard, cast

from apps.config_center.application.runtime_value_evidence import (
    ActiveRuntimeValueEvidence,
    read_active_runtime_value_evidence,
)
from apps.simulated_trading.application.corporate_action_tax_policy import (
    CorporateActionTaxPolicyDecodeError,
    decode_deferred_dividend_tax_policy,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    RecordDateTaxEntitlementRuleKind,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
    SimulatedDividendTaxExchange,
    SimulatedDividendTaxInstrumentKind,
    SimulatedDividendTaxPersona,
    SimulatedDividendTaxPolicyScope,
)
from core.exceptions import BusinessLogicError

SIMULATED_DIVIDEND_TAX_POLICY_KEY = "config_center.simulated_trading.dividend_tax_policies"
_SCHEMA_VERSION = "simulated-dividend-tax-policies.v1"
_TOP_FIELDS = frozenset({"schema_version", "enabled", "policies"})
_POLICY_FIELDS = frozenset(
    {
        "candidate_id",
        "candidate_version",
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
        "record_date_entitlement_rule",
        "applicability_ref",
        "record_date_from",
        "record_date_through",
        "valid_from",
        "valid_until",
        "statutory_bundle_id",
        "statutory_bundle_version",
        "statutory_revision_set_sha256",
        "tax_policy",
    }
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class SimulatedDividendTaxPolicyRowJSON(TypedDict):
    """One exact explicit per-owner/instrument policy selector in runtime JSON."""

    candidate_id: str
    candidate_version: str
    account_kind: str
    physical_account_id: int
    canonical_account_id: str
    owner_user_id: int
    security_id: str
    asset_code: str
    exchange: str
    persona: str
    instrument_kind: str
    currency: str
    record_date_entitlement_rule: str
    applicability_ref: str
    record_date_from: str
    record_date_through: str
    valid_from: str
    valid_until: str
    statutory_bundle_id: str
    statutory_bundle_version: str
    statutory_revision_set_sha256: str
    tax_policy: object


class SimulatedDividendTaxPoliciesJSON(TypedDict):
    """Strict current Config Center value for explicit simulated tax candidates."""

    schema_version: str
    enabled: bool
    policies: list[SimulatedDividendTaxPolicyRowJSON]


class SimulatedDividendTaxPolicyUnavailable(BusinessLogicError):
    """The current explicit simulation policy is absent or cannot be trusted."""

    default_message = "当前模拟股息税务政策缺失或无效"
    default_code = "SIMULATED_DIVIDEND_TAX_POLICY_UNAVAILABLE"


def _invalid(field: str, reason: str) -> SimulatedDividendTaxPolicyUnavailable:
    """Build a stable application error without echoing raw runtime values."""

    return SimulatedDividendTaxPolicyUnavailable(f"{field}: {reason}")


def _is_string_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow one exact JSON object whose keys are exact strings."""

    return type(value) is dict and all(
        type(key) is str for key in cast(dict[object, object], value)
    )


def _require_object(
    value: object,
    *,
    fields: frozenset[str],
    field: str,
) -> dict[str, object]:
    """Require every expected key and reject missing or unknown fields."""

    if not _is_string_object(value):
        raise _invalid(field, "must be an exact JSON object with string keys")
    if frozenset(value) != fields:
        raise _invalid(field, "required fields are missing or unknown fields are present")
    return value


def _require_string(value: object, *, field: str) -> str:
    """Require an exact UTF-8 string instead of coercing JSON values."""

    if type(value) is not str:
        raise _invalid(field, "must be an exact string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise _invalid(field, "must be valid UTF-8") from error
    return value


def _require_token(value: object, *, field: str, limit: int = 192) -> str:
    """Require a bounded nonempty identity token with no whitespace."""

    text = _require_string(value, field=field)
    if not text or text != text.strip() or len(text) > limit:
        raise _invalid(field, "must be an explicit bounded token")
    if any(character.isspace() for character in text):
        raise _invalid(field, "must not contain whitespace")
    return text


def _require_positive_int(value: object, *, field: str) -> int:
    """Require a positive exact JSON integer and reject booleans."""

    if type(value) is not int or value <= 0:
        raise _invalid(field, "must be a positive exact integer")
    return value


def _utc_clock(value: object, *, field: str) -> datetime:
    """Require a representable aware instant and return it in UTC for comparison."""

    if type(value) is not datetime:
        raise _invalid(field, "must be a timezone-aware datetime")
    try:
        if value.utcoffset() is None:
            raise _invalid(field, "must be a timezone-aware datetime")
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise _invalid(field, "must be a representable timezone-aware instant") from error


def _parse_date(value: object, *, field: str) -> date:
    """Parse only canonical YYYY-MM-DD strings."""

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


def _parse_enum(
    value: object,
    *,
    field: str,
    enum_type: (
        type[SimulatedDividendTaxExchange]
        | type[SimulatedDividendTaxPersona]
        | type[SimulatedDividendTaxInstrumentKind]
    ),
) -> (
    SimulatedDividendTaxExchange | SimulatedDividendTaxPersona | SimulatedDividendTaxInstrumentKind
):
    """Select one exact member of a closed supported simulation taxonomy."""

    text = _require_token(value, field=field)
    try:
        return enum_type(text)
    except ValueError as error:
        raise _invalid(field, "is outside the supported explicit enum") from error


def _parse_scope(
    value: object, *, index: int, known_at: datetime
) -> SimulatedDividendTaxPolicyScope:
    """Narrow one strict row and its embedded policy through the existing decoder."""

    field = f"policies[{index}]"
    raw = _require_object(value, fields=_POLICY_FIELDS, field=field)
    row = cast(SimulatedDividendTaxPolicyRowJSON, raw)
    try:
        tax_policy = decode_deferred_dividend_tax_policy(row["tax_policy"])
    except CorporateActionTaxPolicyDecodeError as error:
        raise _invalid(
            f"{field}.tax_policy", "failed the existing strict policy decoder"
        ) from error
    try:
        if _require_string(row["account_kind"], field=f"{field}.account_kind") != "simulated":
            raise _invalid(f"{field}.account_kind", "only simulated accounts are supported")
        exchange_value = _parse_enum(
            row["exchange"], field=f"{field}.exchange", enum_type=SimulatedDividendTaxExchange
        )
        persona_value = _parse_enum(
            row["persona"], field=f"{field}.persona", enum_type=SimulatedDividendTaxPersona
        )
        instrument_value = _parse_enum(
            row["instrument_kind"],
            field=f"{field}.instrument_kind",
            enum_type=SimulatedDividendTaxInstrumentKind,
        )
        if (
            type(exchange_value) is not SimulatedDividendTaxExchange
            or type(persona_value) is not SimulatedDividendTaxPersona
            or type(instrument_value) is not SimulatedDividendTaxInstrumentKind
        ):
            raise _invalid(field, "contains an unsupported explicit taxonomy value")
        return SimulatedDividendTaxPolicyScope(
            candidate_id=_require_token(row["candidate_id"], field=f"{field}.candidate_id"),
            candidate_version=_require_token(
                row["candidate_version"], field=f"{field}.candidate_version"
            ),
            account_kind="simulated",
            physical_account_id=_require_positive_int(
                row["physical_account_id"], field=f"{field}.physical_account_id"
            ),
            canonical_account_id=_require_token(
                row["canonical_account_id"], field=f"{field}.canonical_account_id"
            ),
            owner_user_id=_require_positive_int(
                row["owner_user_id"], field=f"{field}.owner_user_id"
            ),
            security_id=_require_token(row["security_id"], field=f"{field}.security_id"),
            asset_code=_require_token(row["asset_code"], field=f"{field}.asset_code"),
            exchange=exchange_value,
            persona=persona_value,
            instrument_kind=instrument_value,
            currency=SimulatedDividendTaxCurrency(
                _require_token(row["currency"], field=f"{field}.currency")
            ),
            record_date_entitlement_rule=RecordDateTaxEntitlementRuleKind(
                _require_token(
                    row["record_date_entitlement_rule"],
                    field=f"{field}.record_date_entitlement_rule",
                )
            ),
            applicability_ref=_require_token(
                row["applicability_ref"], field=f"{field}.applicability_ref"
            ),
            record_date_from=_parse_date(
                row["record_date_from"], field=f"{field}.record_date_from"
            ),
            record_date_through=_parse_date(
                row["record_date_through"], field=f"{field}.record_date_through"
            ),
            valid_from=_parse_clock(row["valid_from"], field=f"{field}.valid_from"),
            valid_until=_parse_clock(row["valid_until"], field=f"{field}.valid_until"),
            known_at=known_at,
            statutory_bundle_id=_require_token(
                row["statutory_bundle_id"], field=f"{field}.statutory_bundle_id"
            ),
            statutory_bundle_version=_require_token(
                row["statutory_bundle_version"], field=f"{field}.statutory_bundle_version"
            ),
            statutory_revision_set_sha256=_require_digest(
                row["statutory_revision_set_sha256"],
                field=f"{field}.statutory_revision_set_sha256",
            ),
            tax_policy=tax_policy,
        )
    except (DeferredDividendTaxValidationError, OverflowError, TypeError, ValueError) as error:
        raise _invalid(field, "failed typed policy-scope validation") from error


def _require_digest(value: object, *, field: str) -> str:
    """Require one exact lowercase SHA-256 digest in runtime JSON."""

    text = _require_string(value, field=field)
    if _SHA256.fullmatch(text) is None:
        raise _invalid(field, "must be a lowercase SHA-256 digest")
    return text


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
    """Recheck current profile/snapshot identity and creation/activation clocks."""

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
    _require_digest(profile_content_hash, field="profile_content_hash")
    _require_digest(snapshot_hash, field="snapshot_hash")
    cutoff = _utc_clock(as_of, field="as_of")
    clocks = {
        "created_at": created_at,
        "known_at": known_at,
        "activated_at": activated_at,
        "snapshot_generated_at": snapshot_generated_at,
        "effective_at": effective_at,
    }
    normalized = {name: _utc_clock(value, field=name) for name, value in clocks.items()}
    if any(value > cutoff for value in normalized.values()):
        raise _invalid("runtime_clocks", "must not be later than the requested cutoff")
    if normalized["created_at"] != normalized["known_at"]:
        raise _invalid("known_at", "must preserve Config Center profile creation time")
    if normalized["activated_at"] != normalized["effective_at"]:
        raise _invalid("effective_at", "must match active snapshot effective time")
    if not (
        normalized["created_at"]
        <= normalized["activated_at"]
        <= normalized["snapshot_generated_at"]
        <= cutoff
    ):
        raise _invalid("runtime_clocks", "profile and snapshot clocks are out of order")


@dataclass(frozen=True, slots=True)
class ConfiguredSimulatedDividendTaxPolicy:
    """Current configured candidate and its immutable Config Center provenance.

    The value records active configuration only. It does not mark statutory
    sources as authentic/current or authorize assessment, collection or refund.
    """

    candidate: SimulatedDividendTaxPolicyScope
    record_date: date
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
        """Revalidate selected date, current candidate, and runtime evidence facts."""

        if type(self.candidate) is not SimulatedDividendTaxPolicyScope:
            raise _invalid("candidate", "must be the exact typed simulation tax scope")
        try:
            self.candidate.verify_for(
                account_kind=self.account_kind,
                physical_account_id=self.candidate.physical_account_id,
                canonical_account_id=self.candidate.canonical_account_id,
                owner_user_id=self.candidate.owner_user_id,
                security_id=self.candidate.security_id,
                asset_code=self.candidate.asset_code,
                exchange=self.candidate.exchange,
                persona=self.candidate.persona,
                instrument_kind=self.candidate.instrument_kind,
                record_date=self.record_date,
                as_of=self.as_of,
            )
        except DeferredDividendTaxValidationError as error:
            raise _invalid("candidate", "is not applicable at the current read cutoff") from error
        if self.definition_key != SIMULATED_DIVIDEND_TAX_POLICY_KEY:
            raise _invalid("definition_key", "does not identify the explicit tax-policy setting")
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
        if _utc_clock(self.known_at, field="known_at") != _utc_clock(
            self.candidate.known_at, field="candidate.known_at"
        ):
            raise _invalid("candidate.known_at", "must come from current runtime evidence")

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
        """Recheck the requested scope against this fixed current Config Center read."""

        self.__post_init__()
        if _utc_clock(as_of, field="as_of") != _utc_clock(self.as_of, field="configured.as_of"):
            raise _invalid("as_of", "differs from the cutoff that selected this candidate")
        try:
            self.candidate.verify_for(
                account_kind=account_kind,
                physical_account_id=physical_account_id,
                canonical_account_id=canonical_account_id,
                owner_user_id=owner_user_id,
                security_id=security_id,
                asset_code=asset_code,
                exchange=exchange,
                persona=persona,
                instrument_kind=instrument_kind,
                record_date=record_date,
                as_of=as_of,
            )
        except DeferredDividendTaxValidationError as error:
            raise _invalid("candidate", "does not match the requested current scope") from error


def _validate_runtime_evidence(
    evidence: ActiveRuntimeValueEvidence,
    *,
    environment: str,
    as_of: datetime,
) -> None:
    """Require Config Center's stable active value for this exact read."""

    if type(evidence) is not ActiveRuntimeValueEvidence:
        raise _invalid("runtime_evidence", "must use the Config Center evidence contract")
    if (
        evidence.environment != environment
        or evidence.definition_key != SIMULATED_DIVIDEND_TAX_POLICY_KEY
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


def read_current_simulated_dividend_tax_policy(
    *,
    environment: str,
    as_of: datetime,
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
) -> ConfiguredSimulatedDividendTaxPolicy:
    """Read the unique current configured candidate for one exact simulated owner.

    Runtime evidence, the configuration schema, every row and the configured
    statutory revision-set pin are checked structurally. No older profile,
    source qualification, instrument discovery, tax authority or legal claim is
    inferred when any required evidence is absent or mismatched.
    """

    _require_token(environment, field="environment", limit=64)
    canonical = _require_token(canonical_account_id, field="canonical_account_id")
    physical = _require_positive_int(physical_account_id, field="physical_account_id")
    owner = _require_positive_int(owner_user_id, field="owner_user_id")
    security = _require_token(security_id, field="security_id", limit=96)
    asset = _require_token(asset_code, field="asset_code", limit=96)
    selected_record_date = (
        _parse_date(record_date.isoformat(), field="record_date")
        if type(record_date) is date
        else None
    )
    if selected_record_date is None:
        raise _invalid("record_date", "must be an exact calendar date")
    if type(account_kind) is not str or account_kind != "simulated":
        raise _invalid("account_kind", "only simulated account scope is supported")
    if type(exchange) is not SimulatedDividendTaxExchange:
        raise _invalid("exchange", "must be an explicit supported exchange")
    if type(persona) is not SimulatedDividendTaxPersona:
        raise _invalid("persona", "must be an explicit supported investor persona")
    if type(instrument_kind) is not SimulatedDividendTaxInstrumentKind:
        raise _invalid("instrument_kind", "must be an explicit supported instrument")
    _utc_clock(as_of, field="as_of")

    evidence = read_active_runtime_value_evidence(
        environment=environment,
        definition_key=SIMULATED_DIVIDEND_TAX_POLICY_KEY,
        as_of=as_of,
    )
    if evidence is None:
        raise _invalid("runtime_evidence", "active explicit setting is unavailable")
    _validate_runtime_evidence(evidence, environment=environment, as_of=as_of)

    raw = _require_object(evidence.value, fields=_TOP_FIELDS, field="configuration")
    payload = cast(SimulatedDividendTaxPoliciesJSON, raw)
    if _require_string(payload["schema_version"], field="schema_version") != _SCHEMA_VERSION:
        raise _invalid("schema_version", "is unsupported")
    if type(payload["enabled"]) is not bool:
        raise _invalid("enabled", "must be an exact boolean")
    raw_rows = payload["policies"]
    if type(raw_rows) is not list or not raw_rows:
        raise _invalid("policies", "must be a nonempty JSON array")
    candidates = tuple(
        _parse_scope(row, index=index, known_at=evidence.known_at)
        for index, row in enumerate(cast(list[object], raw_rows))
    )
    if payload["enabled"] is not True:
        raise _invalid("enabled", "explicit simulated tax policies are disabled")

    selector_matches = tuple(
        candidate
        for candidate in candidates
        if candidate.canonical_account_id == canonical and candidate.asset_code == asset
    )
    if len(selector_matches) != 1:
        reason = (
            "has duplicate canonical-account/asset mappings"
            if len(selector_matches) > 1
            else "has no canonical-account/asset mapping"
        )
        raise _invalid("policies", reason)
    selected = selector_matches[0]
    try:
        selected.verify_for(
            account_kind=account_kind,
            physical_account_id=physical,
            canonical_account_id=canonical,
            owner_user_id=owner,
            security_id=security,
            asset_code=asset,
            exchange=exchange,
            persona=persona,
            instrument_kind=instrument_kind,
            record_date=selected_record_date,
            as_of=as_of,
        )
        return ConfiguredSimulatedDividendTaxPolicy(
            candidate=selected,
            record_date=selected_record_date,
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
        raise _invalid(
            "policies", "selected candidate failed final current-scope validation"
        ) from error


__all__ = [
    "ConfiguredSimulatedDividendTaxPolicy",
    "SIMULATED_DIVIDEND_TAX_POLICY_KEY",
    "SimulatedDividendTaxPolicyUnavailable",
    "SimulatedDividendTaxPolicyRowJSON",
    "SimulatedDividendTaxPoliciesJSON",
    "read_current_simulated_dividend_tax_policy",
]
