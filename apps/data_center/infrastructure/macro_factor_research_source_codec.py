"""Strict canonical codec for Data Center R3 source-definition receipts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from apps.data_center.domain.macro_factor_research_source import (
    MacroFactorResearchCalendar,
    MacroFactorResearchCoveragePolicy,
    MacroFactorResearchMemberRole,
    MacroFactorResearchMemberRule,
    MacroFactorResearchPeriodKind,
    MacroFactorResearchPeriodRule,
    MacroFactorResearchSourceDefinition,
    MacroFactorSourceSeal,
    MacroFactorValueEncoding,
    PersistedMacroFactorResearchSourceDefinition,
)


class MacroFactorResearchSourceCodecError(ValueError):
    """Persisted R3 source evidence is malformed or non-canonical."""


def encode_persisted_macro_factor_research_source(
    record: PersistedMacroFactorResearchSourceDefinition,
) -> dict[str, object]:
    """Encode one live-validated receipt into canonical JSON-safe values."""

    if type(record) is not PersistedMacroFactorResearchSourceDefinition:
        raise MacroFactorResearchSourceCodecError("macro-factor source record type must be exact")
    validated = record.validated_copy()
    return {
        "schema": "data-center-macro-factor-source-record.v1",
        "definition": validated.definition.canonical_payload(),
        "ledger_recorded_at": _datetime_text(validated.ledger_recorded_at),
        "record_hash": validated.record_hash.lower(),
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def decode_persisted_macro_factor_research_source(
    value: object,
) -> PersistedMacroFactorResearchSourceDefinition:
    """Restore and replay every nested definition, calendar, member, and seal."""

    try:
        payload = _mapping(value, "macro-factor source record")
        _exact_keys(
            payload,
            {
                "schema",
                "definition",
                "ledger_recorded_at",
                "record_hash",
                "research_only",
                "must_not_publish_current",
                "must_not_use_for_decision",
                "must_not_execute",
            },
            "macro-factor source record",
        )
        if _text(payload["schema"], "macro-factor source schema") != (
            "data-center-macro-factor-source-record.v1"
        ):
            raise ValueError("macro-factor source schema differs")
        for field_name in (
            "research_only",
            "must_not_publish_current",
            "must_not_use_for_decision",
            "must_not_execute",
        ):
            if _boolean(payload[field_name], field_name) is not True:
                raise ValueError("macro-factor source safety boundary differs")
        definition = _decode_definition(payload["definition"])
        record = PersistedMacroFactorResearchSourceDefinition.create(
            definition=definition,
            ledger_recorded_at=_datetime(
                payload["ledger_recorded_at"],
                "macro-factor ledger_recorded_at",
            ),
        )
        if record.record_hash.lower() != _hash(
            payload["record_hash"],
            "macro-factor record_hash",
        ):
            raise ValueError("macro-factor source record hash differs")
        return record
    except MacroFactorResearchSourceCodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise MacroFactorResearchSourceCodecError(
            "macro-factor source payload failed strict replay"
        ) from error


def _decode_definition(value: object) -> MacroFactorResearchSourceDefinition:
    payload = _mapping(value, "macro-factor definition")
    _exact_keys(
        payload,
        {
            "schema",
            "source_id",
            "source_version",
            "target_code",
            "candidate_asset_codes",
            "manifest_calendar_version",
            "calendar",
            "source_contract",
            "knowledge_scope",
            "members",
            "coverage_policy",
            "registered_at",
            "valid_until",
            "owner",
            "safety",
            "content_hash",
        },
        "macro-factor definition",
    )
    if _text(payload["schema"], "macro-factor definition schema") != (
        "data-center-macro-factor-source-definition.v1"
    ):
        raise ValueError("macro-factor definition schema differs")
    if _text(payload["owner"], "macro-factor owner") != "data_center":
        raise ValueError("macro-factor definition owner differs")
    safety = _sequence(payload["safety"], "macro-factor definition safety")
    if safety != [True, True, True, True] or any(type(item) is not bool for item in safety):
        raise ValueError("macro-factor definition safety flags differ")
    candidates_raw = _sequence(
        payload["candidate_asset_codes"],
        "macro-factor candidate_asset_codes",
    )
    candidates = tuple(_text(item, "macro-factor candidate_asset_code") for item in candidates_raw)
    calendar = _decode_calendar(payload["calendar"])
    source_contract = _decode_source_seal(payload["source_contract"])
    members = tuple(
        _decode_member(item) for item in _sequence(payload["members"], "macro-factor members")
    )
    policy = _decode_coverage_policy(payload["coverage_policy"])
    definition = MacroFactorResearchSourceDefinition.create(
        source_id=_text(payload["source_id"], "macro-factor source_id"),
        source_version=_text(
            payload["source_version"],
            "macro-factor source_version",
        ),
        target_code=_text(payload["target_code"], "macro-factor target_code"),
        candidate_asset_codes=candidates,
        manifest_calendar_version=_text(
            payload["manifest_calendar_version"],
            "macro-factor manifest_calendar_version",
        ),
        calendar=calendar,
        source_contract=source_contract,
        knowledge_scope=_text(
            payload["knowledge_scope"],
            "macro-factor knowledge_scope",
        ),
        members=members,
        coverage_policy=policy,
        registered_at=_datetime(payload["registered_at"], "macro-factor registered_at"),
        valid_until=_datetime(payload["valid_until"], "macro-factor valid_until"),
    )
    if definition.content_hash.lower() != _hash(
        payload["content_hash"],
        "macro-factor definition content_hash",
    ):
        raise ValueError("macro-factor definition hash differs")
    return definition


def _decode_calendar(value: object) -> MacroFactorResearchCalendar:
    payload = _mapping(value, "macro-factor calendar")
    _exact_keys(
        payload,
        {"calendar_id", "calendar_version", "periods", "content_hash"},
        "macro-factor calendar",
    )
    periods = tuple(
        _decode_period(item)
        for item in _sequence(payload["periods"], "macro-factor calendar periods")
    )
    calendar = MacroFactorResearchCalendar.create(
        calendar_id=_text(payload["calendar_id"], "macro-factor calendar_id"),
        calendar_version=_text(
            payload["calendar_version"],
            "macro-factor calendar_version",
        ),
        periods=periods,
    )
    if calendar.content_hash.lower() != _hash(
        payload["content_hash"],
        "macro-factor calendar content_hash",
    ):
        raise ValueError("macro-factor calendar hash differs")
    return calendar


def _decode_period(value: object) -> MacroFactorResearchPeriodRule:
    payload = _mapping(value, "macro-factor period")
    _exact_keys(
        payload,
        {
            "row_id",
            "period_id",
            "kind",
            "observation_date",
            "target_period_start",
            "target_period_end",
        },
        "macro-factor period",
    )
    return MacroFactorResearchPeriodRule(
        row_id=_text(payload["row_id"], "macro-factor period row_id"),
        period_id=_text(payload["period_id"], "macro-factor period period_id"),
        kind=MacroFactorResearchPeriodKind(_text(payload["kind"], "macro-factor period kind")),
        observation_date=_date(
            payload["observation_date"],
            "macro-factor observation_date",
        ),
        target_period_start=_date(
            payload["target_period_start"],
            "macro-factor target_period_start",
        ),
        target_period_end=_date(
            payload["target_period_end"],
            "macro-factor target_period_end",
        ),
    )


def _decode_member(value: object) -> MacroFactorResearchMemberRule:
    payload = _mapping(value, "macro-factor member")
    _exact_keys(
        payload,
        {
            "row_id",
            "role",
            "member_code",
            "dataset_key",
            "business_key",
            "value_field",
            "unit_field",
            "expected_unit",
            "value_encoding",
        },
        "macro-factor member",
    )
    return MacroFactorResearchMemberRule(
        row_id=_text(payload["row_id"], "macro-factor member row_id"),
        role=MacroFactorResearchMemberRole(_text(payload["role"], "macro-factor member role")),
        member_code=_text(
            payload["member_code"],
            "macro-factor member member_code",
        ),
        dataset_key=_text(
            payload["dataset_key"],
            "macro-factor member dataset_key",
        ),
        business_key=_text(
            payload["business_key"],
            "macro-factor member business_key",
        ),
        value_field=_text(
            payload["value_field"],
            "macro-factor member value_field",
        ),
        unit_field=_text(
            payload["unit_field"],
            "macro-factor member unit_field",
        ),
        expected_unit=_text(
            payload["expected_unit"],
            "macro-factor member expected_unit",
        ),
        value_encoding=MacroFactorValueEncoding(
            _text(payload["value_encoding"], "macro-factor member value_encoding")
        ),
    )


def _decode_source_seal(value: object) -> MacroFactorSourceSeal:
    payload = _mapping(value, "macro-factor source contract")
    _exact_keys(
        payload,
        {"stable_id", "version", "content_hash"},
        "macro-factor source contract",
    )
    return MacroFactorSourceSeal(
        stable_id=_text(payload["stable_id"], "macro-factor source stable_id"),
        version=_text(payload["version"], "macro-factor source version"),
        content_hash=_hash(
            payload["content_hash"],
            "macro-factor source content_hash",
        ),
    )


def _decode_coverage_policy(value: object) -> MacroFactorResearchCoveragePolicy:
    payload = _mapping(value, "macro-factor coverage policy")
    _exact_keys(
        payload,
        {
            "require_verified",
            "minimum_coverage_ratio",
            "maximum_missing_count",
            "maximum_estimated_count",
            "maximum_unknown_count",
        },
        "macro-factor coverage policy",
    )
    return MacroFactorResearchCoveragePolicy(
        require_verified=_boolean(
            payload["require_verified"],
            "macro-factor require_verified",
        ),
        minimum_coverage_ratio=_decimal(
            payload["minimum_coverage_ratio"],
            "macro-factor minimum_coverage_ratio",
        ),
        maximum_missing_count=_integer(
            payload["maximum_missing_count"],
            "macro-factor maximum_missing_count",
        ),
        maximum_estimated_count=_integer(
            payload["maximum_estimated_count"],
            "macro-factor maximum_estimated_count",
        ),
        maximum_unknown_count=_integer(
            payload["maximum_unknown_count"],
            "macro-factor maximum_unknown_count",
        ),
    )


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise MacroFactorResearchSourceCodecError(f"{field_name} must be an exact object")
    return cast(dict[str, object], value)


def _sequence(value: object, field_name: str) -> list[object]:
    if type(value) is not list:
        raise MacroFactorResearchSourceCodecError(f"{field_name} must be an exact list")
    return cast(list[object], value)


def _exact_keys(payload: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(payload) != expected:
        raise MacroFactorResearchSourceCodecError(f"{field_name} fields differ")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        raise MacroFactorResearchSourceCodecError(f"{field_name} must be exact text")
    return value


def _hash(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if len(text) != 64 or any(character not in "0123456789abcdefABCDEF" for character in text):
        raise MacroFactorResearchSourceCodecError(f"{field_name} must be a SHA-256 digest")
    return text.lower()


def _boolean(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise MacroFactorResearchSourceCodecError(f"{field_name} must be exact bool")
    return value


def _integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise MacroFactorResearchSourceCodecError(f"{field_name} must be a non-negative exact int")
    return value


def _decimal(value: object, field_name: str) -> Decimal:
    text = _text(value, field_name)
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise MacroFactorResearchSourceCodecError(
            f"{field_name} must be canonical Decimal text"
        ) from error
    if not parsed.is_finite():
        raise MacroFactorResearchSourceCodecError(f"{field_name} must be finite")
    return parsed


def _date(value: object, field_name: str) -> date:
    text = _text(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise MacroFactorResearchSourceCodecError(f"{field_name} must be an ISO date") from error
    if parsed.isoformat() != text:
        raise MacroFactorResearchSourceCodecError(f"{field_name} must be canonical")
    return parsed


def _datetime(value: object, field_name: str) -> datetime:
    text = _text(value, field_name)
    if not text.endswith("Z"):
        raise MacroFactorResearchSourceCodecError(f"{field_name} must use canonical UTC Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise MacroFactorResearchSourceCodecError(
            f"{field_name} must be an ISO datetime"
        ) from error
    if _datetime_text(parsed) != text:
        raise MacroFactorResearchSourceCodecError(f"{field_name} must be canonical UTC")
    return parsed


def _datetime_text(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise MacroFactorResearchSourceCodecError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "MacroFactorResearchSourceCodecError",
    "decode_persisted_macro_factor_research_source",
    "encode_persisted_macro_factor_research_source",
]
