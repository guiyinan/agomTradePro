"""Canonical R3 macro-factor source definitions and strict PIT projections."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum


class MacroFactorResearchPeriodKind(StrEnum):
    """Whether one calendar member carries a historical label or inference only."""

    HISTORICAL = "historical"
    INFERENCE = "inference"


class MacroFactorResearchMemberRole(StrEnum):
    """Semantic role of one exact source member."""

    TARGET = "target"
    PROXY = "proxy"


class MacroFactorValueEncoding(StrEnum):
    """Explicit JSON numeric encoding accepted from the canonical fact payload."""

    DECIMAL_TEXT = "decimal_text.v1"
    JSON_NUMBER = "json_number.v1"


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    rendered = format(normalized, "f")
    return "0" if rendered in {"-0", ""} else rendered


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be an exact bounded token")
    return value


def _require_hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest")
    return value.lower()


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_date(value: object, field_name: str) -> date:
    if type(value) is not date:
        raise ValueError(f"{field_name} must be an exact date")
    return value


def _require_decimal(value: object, field_name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    return value


@dataclass(frozen=True)
class MacroFactorSourceSeal:
    """Exact versioned owner/source identity."""

    stable_id: str
    version: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.stable_id, "macro-factor source stable_id")
        _require_token(self.version, "macro-factor source version")
        _require_hash(self.content_hash, "macro-factor source content_hash")

    def validated_copy(self) -> MacroFactorSourceSeal:
        """Return an independently validated exact copy."""

        return MacroFactorSourceSeal(self.stable_id, self.version, self.content_hash)

    def canonical_payload(self) -> dict[str, str]:
        """Return canonical identity fields."""

        return {
            "stable_id": self.stable_id,
            "version": self.version,
            "content_hash": self.content_hash.lower(),
        }


@dataclass(frozen=True)
class MacroFactorResearchPeriodRule:
    """One complete target-calendar member and its research-row identity."""

    row_id: str
    period_id: str
    kind: MacroFactorResearchPeriodKind
    observation_date: date
    target_period_start: date
    target_period_end: date

    def __post_init__(self) -> None:
        _require_token(self.row_id, "macro-factor period row_id")
        _require_token(self.period_id, "macro-factor period period_id")
        if type(self.kind) is not MacroFactorResearchPeriodKind:
            raise TypeError("macro-factor period kind must be exact")
        _require_date(self.observation_date, "macro-factor period observation_date")
        _require_date(self.target_period_start, "macro-factor target_period_start")
        _require_date(self.target_period_end, "macro-factor target_period_end")
        if self.target_period_start > self.target_period_end:
            raise ValueError("macro-factor target period is invalid")
        if self.observation_date > self.target_period_end:
            raise ValueError("macro-factor observation cannot follow its target period")

    def validated_copy(self) -> MacroFactorResearchPeriodRule:
        """Return an independently validated exact copy."""

        return MacroFactorResearchPeriodRule(
            row_id=self.row_id,
            period_id=self.period_id,
            kind=self.kind,
            observation_date=self.observation_date,
            target_period_start=self.target_period_start,
            target_period_end=self.target_period_end,
        )

    def canonical_payload(self) -> dict[str, str]:
        """Return the complete calendar-member payload."""

        return {
            "row_id": self.row_id,
            "period_id": self.period_id,
            "kind": self.kind.value,
            "observation_date": self.observation_date.isoformat(),
            "target_period_start": self.target_period_start.isoformat(),
            "target_period_end": self.target_period_end.isoformat(),
        }


@dataclass(frozen=True)
class MacroFactorResearchCalendar:
    """Versioned calendar whose hash includes every period member."""

    calendar_id: str
    calendar_version: str
    periods: tuple[MacroFactorResearchPeriodRule, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        calendar_id: str,
        calendar_version: str,
        periods: tuple[MacroFactorResearchPeriodRule, ...],
    ) -> MacroFactorResearchCalendar:
        """Build a full calendar seal from exact period members."""

        validated = tuple(
            sorted(
                (item.validated_copy() for item in periods),
                key=lambda item: (item.observation_date, item.row_id),
            )
        )
        payload = cls._payload(calendar_id, calendar_version, validated)
        return cls(
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            periods=validated,
            content_hash=_hash_payload(payload),
        )

    @staticmethod
    def _payload(
        calendar_id: str,
        calendar_version: str,
        periods: tuple[MacroFactorResearchPeriodRule, ...],
    ) -> dict[str, object]:
        return {
            "calendar_id": calendar_id,
            "calendar_version": calendar_version,
            "periods": [item.canonical_payload() for item in periods],
        }

    def __post_init__(self) -> None:
        _require_token(self.calendar_id, "macro-factor calendar_id")
        _require_token(self.calendar_version, "macro-factor calendar_version")
        if type(self.periods) is not tuple or not self.periods:
            raise ValueError("macro-factor calendar periods must be a non-empty tuple")
        validated = tuple(item.validated_copy() for item in self.periods)
        if validated != tuple(
            sorted(validated, key=lambda item: (item.observation_date, item.row_id))
        ):
            raise ValueError("macro-factor calendar periods must be canonical")
        row_ids = tuple(item.row_id for item in validated)
        period_ids = tuple(item.period_id for item in validated)
        if len(row_ids) != len(set(row_ids)) or len(period_ids) != len(set(period_ids)):
            raise ValueError("macro-factor calendar identities must be unique")
        if sum(item.kind is MacroFactorResearchPeriodKind.INFERENCE for item in validated) != 1:
            raise ValueError("macro-factor calendar requires exactly one inference period")
        expected = _hash_payload(self._payload(self.calendar_id, self.calendar_version, validated))
        if _require_hash(self.content_hash, "macro-factor calendar content_hash") != expected:
            raise ValueError("macro-factor calendar content_hash differs")

    @property
    def inference_period(self) -> MacroFactorResearchPeriodRule:
        """Return the unique label-free inference calendar member."""

        return next(
            item for item in self.periods if item.kind is MacroFactorResearchPeriodKind.INFERENCE
        )

    def validated_copy(self) -> MacroFactorResearchCalendar:
        """Replay the full period graph and its canonical hash."""

        copied = MacroFactorResearchCalendar.create(
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            periods=tuple(item.validated_copy() for item in self.periods),
        )
        if copied != self:
            raise ValueError("macro-factor calendar differs after replay")
        return copied

    def canonical_payload(self) -> dict[str, object]:
        """Return the calendar body and derived seal."""

        return {
            **self._payload(self.calendar_id, self.calendar_version, self.periods),
            "content_hash": self.content_hash.lower(),
        }


@dataclass(frozen=True)
class MacroFactorResearchMemberRule:
    """Exact expected PIT fact identity and value-decoding rule."""

    row_id: str
    role: MacroFactorResearchMemberRole
    member_code: str
    dataset_key: str
    business_key: str
    value_field: str
    unit_field: str
    expected_unit: str
    value_encoding: MacroFactorValueEncoding

    def __post_init__(self) -> None:
        for value, name, maximum in (
            (self.row_id, "row_id", 192),
            (self.member_code, "member_code", 192),
            (self.dataset_key, "dataset_key", 64),
            (self.business_key, "business_key", 255),
            (self.value_field, "value_field", 192),
            (self.unit_field, "unit_field", 192),
            (self.expected_unit, "expected_unit", 192),
        ):
            _require_token(value, f"macro-factor member {name}", maximum=maximum)
        if type(self.role) is not MacroFactorResearchMemberRole:
            raise TypeError("macro-factor member role must be exact")
        if type(self.value_encoding) is not MacroFactorValueEncoding:
            raise TypeError("macro-factor value encoding must be exact")
        if self.value_field == self.unit_field:
            raise ValueError("macro-factor value and unit fields must differ")

    def validated_copy(self) -> MacroFactorResearchMemberRule:
        """Return an independently validated exact copy."""

        return MacroFactorResearchMemberRule(
            row_id=self.row_id,
            role=self.role,
            member_code=self.member_code,
            dataset_key=self.dataset_key,
            business_key=self.business_key,
            value_field=self.value_field,
            unit_field=self.unit_field,
            expected_unit=self.expected_unit,
            value_encoding=self.value_encoding,
        )

    def canonical_payload(self) -> dict[str, str]:
        """Return the complete expected member rule."""

        return {
            "row_id": self.row_id,
            "role": self.role.value,
            "member_code": self.member_code,
            "dataset_key": self.dataset_key,
            "business_key": self.business_key,
            "value_field": self.value_field,
            "unit_field": self.unit_field,
            "expected_unit": self.expected_unit,
            "value_encoding": self.value_encoding.value,
        }


@dataclass(frozen=True)
class MacroFactorResearchCoveragePolicy:
    """Explicit, versioned acceptance policy for one PIT projection."""

    require_verified: bool
    minimum_coverage_ratio: Decimal
    maximum_missing_count: int
    maximum_estimated_count: int
    maximum_unknown_count: int

    def __post_init__(self) -> None:
        if type(self.require_verified) is not bool:
            raise TypeError("macro-factor require_verified must be exact bool")
        ratio = _require_decimal(
            self.minimum_coverage_ratio,
            "macro-factor minimum_coverage_ratio",
        )
        if not Decimal("0") <= ratio <= Decimal("1"):
            raise ValueError("macro-factor minimum coverage must be between zero and one")
        for value, name in (
            (self.maximum_missing_count, "maximum_missing_count"),
            (self.maximum_estimated_count, "maximum_estimated_count"),
            (self.maximum_unknown_count, "maximum_unknown_count"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"macro-factor {name} must be a non-negative exact int")

    def validated_copy(self) -> MacroFactorResearchCoveragePolicy:
        """Return an independently validated policy copy."""

        return MacroFactorResearchCoveragePolicy(
            require_verified=self.require_verified,
            minimum_coverage_ratio=self.minimum_coverage_ratio,
            maximum_missing_count=self.maximum_missing_count,
            maximum_estimated_count=self.maximum_estimated_count,
            maximum_unknown_count=self.maximum_unknown_count,
        )

    def canonical_payload(self) -> dict[str, object]:
        """Return explicit acceptance values without hidden defaults."""

        return {
            "require_verified": self.require_verified,
            "minimum_coverage_ratio": _decimal_text(self.minimum_coverage_ratio),
            "maximum_missing_count": self.maximum_missing_count,
            "maximum_estimated_count": self.maximum_estimated_count,
            "maximum_unknown_count": self.maximum_unknown_count,
        }


@dataclass(frozen=True)
class MacroFactorResearchSourceDefinition:
    """Data Center-owned complete source/calendar/member definition."""

    source_id: str
    source_version: str
    target_code: str
    candidate_asset_codes: tuple[str, ...]
    manifest_calendar_version: str
    calendar: MacroFactorResearchCalendar
    source_contract: MacroFactorSourceSeal
    knowledge_scope: str
    members: tuple[MacroFactorResearchMemberRule, ...]
    coverage_policy: MacroFactorResearchCoveragePolicy
    registered_at: datetime
    valid_until: datetime
    content_hash: str
    owner: str = "data_center"
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        source_version: str,
        target_code: str,
        candidate_asset_codes: tuple[str, ...],
        manifest_calendar_version: str,
        calendar: MacroFactorResearchCalendar,
        source_contract: MacroFactorSourceSeal,
        knowledge_scope: str,
        members: tuple[MacroFactorResearchMemberRule, ...],
        coverage_policy: MacroFactorResearchCoveragePolicy,
        registered_at: datetime,
        valid_until: datetime,
    ) -> MacroFactorResearchSourceDefinition:
        """Build a canonical definition from owner-controlled source rules."""

        candidates = tuple(sorted(candidate_asset_codes))
        validated_members = tuple(
            sorted(
                (item.validated_copy() for item in members),
                key=lambda item: (item.row_id, item.role.value, item.member_code),
            )
        )
        validated_calendar = calendar.validated_copy()
        validated_source = source_contract.validated_copy()
        validated_policy = coverage_policy.validated_copy()
        payload = cls._payload(
            source_id=source_id,
            source_version=source_version,
            target_code=target_code,
            candidate_asset_codes=candidates,
            manifest_calendar_version=manifest_calendar_version,
            calendar=validated_calendar,
            source_contract=validated_source,
            knowledge_scope=knowledge_scope,
            members=validated_members,
            coverage_policy=validated_policy,
            registered_at=registered_at,
            valid_until=valid_until,
        )
        return cls(
            source_id=source_id,
            source_version=source_version,
            target_code=target_code,
            candidate_asset_codes=candidates,
            manifest_calendar_version=manifest_calendar_version,
            calendar=validated_calendar,
            source_contract=validated_source,
            knowledge_scope=knowledge_scope,
            members=validated_members,
            coverage_policy=validated_policy,
            registered_at=registered_at,
            valid_until=valid_until,
            content_hash=_hash_payload(payload),
        )

    @staticmethod
    def _payload(
        *,
        source_id: str,
        source_version: str,
        target_code: str,
        candidate_asset_codes: tuple[str, ...],
        manifest_calendar_version: str,
        calendar: MacroFactorResearchCalendar,
        source_contract: MacroFactorSourceSeal,
        knowledge_scope: str,
        members: tuple[MacroFactorResearchMemberRule, ...],
        coverage_policy: MacroFactorResearchCoveragePolicy,
        registered_at: datetime,
        valid_until: datetime,
    ) -> dict[str, object]:
        return {
            "schema": "data-center-macro-factor-source-definition.v1",
            "source_id": source_id,
            "source_version": source_version,
            "target_code": target_code,
            "candidate_asset_codes": list(candidate_asset_codes),
            "manifest_calendar_version": manifest_calendar_version,
            "calendar": calendar.canonical_payload(),
            "source_contract": source_contract.canonical_payload(),
            "knowledge_scope": knowledge_scope,
            "members": [item.canonical_payload() for item in members],
            "coverage_policy": coverage_policy.canonical_payload(),
            "registered_at": _utc_text(registered_at),
            "valid_until": _utc_text(valid_until),
            "owner": "data_center",
            "safety": [True, True, True, True],
        }

    def __post_init__(self) -> None:
        _require_token(self.source_id, "macro-factor source_id")
        _require_token(self.source_version, "macro-factor source_version")
        _require_token(self.target_code, "macro-factor target_code")
        _require_token(
            self.manifest_calendar_version,
            "macro-factor manifest_calendar_version",
            maximum=64,
        )
        if self.owner != "data_center":
            raise ValueError("macro-factor source definition owner must be data_center")
        if type(self.candidate_asset_codes) is not tuple or not self.candidate_asset_codes:
            raise ValueError("macro-factor candidate_asset_codes must be a non-empty tuple")
        for code in self.candidate_asset_codes:
            _require_token(code, "macro-factor candidate asset code")
        if self.candidate_asset_codes != tuple(sorted(set(self.candidate_asset_codes))):
            raise ValueError("macro-factor candidate_asset_codes must be canonical")
        if type(self.calendar) is not MacroFactorResearchCalendar:
            raise TypeError("macro-factor calendar type differs")
        calendar = self.calendar.validated_copy()
        if type(self.source_contract) is not MacroFactorSourceSeal:
            raise TypeError("macro-factor source contract type differs")
        source_contract = self.source_contract.validated_copy()
        if self.knowledge_scope != "public":
            raise ValueError("macro-factor R3 projection requires public knowledge scope")
        if type(self.members) is not tuple or not self.members:
            raise ValueError("macro-factor members must be a non-empty tuple")
        members = tuple(item.validated_copy() for item in self.members)
        if members != tuple(
            sorted(members, key=lambda item: (item.row_id, item.role.value, item.member_code))
        ):
            raise ValueError("macro-factor members must be canonical")
        identities = tuple((item.dataset_key, item.business_key) for item in members)
        if len(identities) != len(set(identities)):
            raise ValueError("macro-factor source member fact identities must be unique")
        if type(self.coverage_policy) is not MacroFactorResearchCoveragePolicy:
            raise TypeError("macro-factor coverage policy type differs")
        policy = self.coverage_policy.validated_copy()
        _require_aware(self.registered_at, "macro-factor registered_at")
        _require_aware(self.valid_until, "macro-factor valid_until")
        if self.registered_at >= self.valid_until:
            raise ValueError("macro-factor source validity window is invalid")
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("macro-factor source safety flags must remain true")
        period_by_row = {item.row_id: item for item in calendar.periods}
        if any(item.row_id not in period_by_row for item in members):
            raise ValueError("macro-factor member references an unknown calendar row")
        expected_proxies = frozenset(self.candidate_asset_codes)
        for period in calendar.periods:
            row_members = tuple(item for item in members if item.row_id == period.row_id)
            proxies = tuple(
                item for item in row_members if item.role is MacroFactorResearchMemberRole.PROXY
            )
            targets = tuple(
                item for item in row_members if item.role is MacroFactorResearchMemberRole.TARGET
            )
            if frozenset(item.member_code for item in proxies) != expected_proxies or len(
                proxies
            ) != len(expected_proxies):
                raise ValueError("macro-factor row does not cover the exact proxy universe")
            if period.kind is MacroFactorResearchPeriodKind.HISTORICAL:
                if len(targets) != 1 or targets[0].member_code != self.target_code:
                    raise ValueError("macro-factor historical row requires its exact target")
            elif targets:
                raise ValueError("macro-factor inference row cannot include a target label")
        expected_hash = _hash_payload(
            self._payload(
                source_id=self.source_id,
                source_version=self.source_version,
                target_code=self.target_code,
                candidate_asset_codes=self.candidate_asset_codes,
                manifest_calendar_version=self.manifest_calendar_version,
                calendar=calendar,
                source_contract=source_contract,
                knowledge_scope=self.knowledge_scope,
                members=members,
                coverage_policy=policy,
                registered_at=self.registered_at,
                valid_until=self.valid_until,
            )
        )
        if (
            _require_hash(self.content_hash, "macro-factor definition content_hash")
            != expected_hash
        ):
            raise ValueError("macro-factor definition content_hash differs")

    @property
    def periods(self) -> tuple[MacroFactorResearchPeriodRule, ...]:
        """Return the sealed calendar members."""

        return self.calendar.periods

    @property
    def inference_period(self) -> MacroFactorResearchPeriodRule:
        """Return the unique inference member."""

        return self.calendar.inference_period

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether owner validity covers the PIT cutoff."""

        _require_aware(as_of, "macro-factor definition as_of")
        return self.registered_at <= as_of < self.valid_until

    def validated_copy(self) -> MacroFactorResearchSourceDefinition:
        """Replay the full source/calendar/member graph."""

        copied = MacroFactorResearchSourceDefinition.create(
            source_id=self.source_id,
            source_version=self.source_version,
            target_code=self.target_code,
            candidate_asset_codes=self.candidate_asset_codes,
            manifest_calendar_version=self.manifest_calendar_version,
            calendar=self.calendar.validated_copy(),
            source_contract=self.source_contract.validated_copy(),
            knowledge_scope=self.knowledge_scope,
            members=tuple(item.validated_copy() for item in self.members),
            coverage_policy=self.coverage_policy.validated_copy(),
            registered_at=self.registered_at,
            valid_until=self.valid_until,
        )
        if copied != self:
            raise ValueError("macro-factor source definition differs after replay")
        return copied

    def canonical_payload(self) -> dict[str, object]:
        """Return the complete definition body and content seal."""

        return {
            **self._payload(
                source_id=self.source_id,
                source_version=self.source_version,
                target_code=self.target_code,
                candidate_asset_codes=self.candidate_asset_codes,
                manifest_calendar_version=self.manifest_calendar_version,
                calendar=self.calendar,
                source_contract=self.source_contract,
                knowledge_scope=self.knowledge_scope,
                members=self.members,
                coverage_policy=self.coverage_policy,
                registered_at=self.registered_at,
                valid_until=self.valid_until,
            ),
            "content_hash": self.content_hash.lower(),
        }


def _record_hash(
    definition: MacroFactorResearchSourceDefinition,
    ledger_recorded_at: datetime,
) -> str:
    return _hash_payload(
        {
            "schema": "data-center-macro-factor-source-record.v1",
            "definition": [
                definition.source_id,
                definition.source_version,
                definition.content_hash.lower(),
            ],
            "ledger_recorded_at": _utc_text(ledger_recorded_at),
            "safety": [True, True, True, True],
        }
    )


@dataclass(frozen=True)
class PersistedMacroFactorResearchSourceDefinition:
    """Strictly persisted source definition and trusted ledger clock."""

    definition: MacroFactorResearchSourceDefinition
    ledger_recorded_at: datetime
    record_hash: str
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        definition: MacroFactorResearchSourceDefinition,
        ledger_recorded_at: datetime,
    ) -> PersistedMacroFactorResearchSourceDefinition:
        """Create one server-clock registration receipt."""

        validated = definition.validated_copy()
        _require_aware(ledger_recorded_at, "macro-factor ledger_recorded_at")
        return cls(
            definition=validated,
            ledger_recorded_at=ledger_recorded_at,
            record_hash=_record_hash(validated, ledger_recorded_at),
        )

    def __post_init__(self) -> None:
        if type(self.definition) is not MacroFactorResearchSourceDefinition:
            raise TypeError("persisted macro-factor definition type differs")
        definition = self.definition.validated_copy()
        _require_aware(self.ledger_recorded_at, "macro-factor ledger_recorded_at")
        if not definition.registered_at <= self.ledger_recorded_at < definition.valid_until:
            raise ValueError("macro-factor definition ledger clock is invalid")
        if _require_hash(self.record_hash, "macro-factor record_hash") != _record_hash(
            definition,
            self.ledger_recorded_at,
        ):
            raise ValueError("macro-factor definition record_hash differs")
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("macro-factor persisted safety flags must remain true")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether both owner and ledger clocks permit this definition."""

        _require_aware(as_of, "macro-factor persisted as_of")
        return self.ledger_recorded_at <= as_of and self.definition.is_active_at(as_of)

    def validated_copy(self) -> PersistedMacroFactorResearchSourceDefinition:
        """Replay definition, clock, receipt seal, and safety flags."""

        copied = PersistedMacroFactorResearchSourceDefinition.create(
            definition=self.definition.validated_copy(),
            ledger_recorded_at=self.ledger_recorded_at,
        )
        if copied != self:
            raise ValueError("persisted macro-factor definition differs after replay")
        return copied


@dataclass(frozen=True)
class CanonicalMacroFactorPITFact:
    """One resolved definition member backed by an exact canonical PIT fact."""

    row_id: str
    role: MacroFactorResearchMemberRole
    member_code: str
    dataset_key: str
    business_key: str
    version_id: int
    content_hash: str
    payload_hash: str
    source_record_id: str
    revision_number: int
    effective_at: datetime
    available_at: datetime
    ingested_at: datetime
    pit_quality: str
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        for value, name, maximum in (
            (self.row_id, "row_id", 192),
            (self.member_code, "member_code", 192),
            (self.dataset_key, "dataset_key", 192),
            (self.business_key, "business_key", 255),
            (self.source_record_id, "source_record_id", 255),
            (self.pit_quality, "pit_quality", 32),
            (self.unit, "unit", 192),
        ):
            _require_token(value, f"macro-factor fact {name}", maximum=maximum)
        if type(self.role) is not MacroFactorResearchMemberRole:
            raise TypeError("macro-factor fact role must be exact")
        if type(self.version_id) is not int or self.version_id <= 0:
            raise ValueError("macro-factor fact version_id must be a positive exact int")
        if type(self.revision_number) is not int or self.revision_number < 0:
            raise ValueError("macro-factor fact revision_number must be non-negative exact int")
        _require_hash(self.content_hash, "macro-factor fact content_hash")
        _require_hash(self.payload_hash, "macro-factor fact payload_hash")
        _require_aware(self.effective_at, "macro-factor fact effective_at")
        _require_aware(self.available_at, "macro-factor fact available_at")
        _require_aware(self.ingested_at, "macro-factor fact ingested_at")
        if self.available_at > self.ingested_at:
            raise ValueError("macro-factor public fact cannot be ingested before availability")
        _require_decimal(self.value, "macro-factor fact value")

    def validated_copy(self) -> CanonicalMacroFactorPITFact:
        """Return a live-validated fact projection."""

        return CanonicalMacroFactorPITFact(
            row_id=self.row_id,
            role=self.role,
            member_code=self.member_code,
            dataset_key=self.dataset_key,
            business_key=self.business_key,
            version_id=self.version_id,
            content_hash=self.content_hash,
            payload_hash=self.payload_hash,
            source_record_id=self.source_record_id,
            revision_number=self.revision_number,
            effective_at=self.effective_at,
            available_at=self.available_at,
            ingested_at=self.ingested_at,
            pit_quality=self.pit_quality,
            value=self.value,
            unit=self.unit,
        )


@dataclass(frozen=True)
class CanonicalMacroFactorPITProjection:
    """Complete strict read projection from one existing PIT manifest."""

    source: PersistedMacroFactorResearchSourceDefinition
    manifest_id: str
    manifest_hash: str
    manifest_as_of: datetime
    manifest_created_at: datetime
    knowledge_scope: str
    coverage_ratio: Decimal
    missing_count: int
    estimated_count: int
    unknown_count: int
    is_verified: bool
    facts: tuple[CanonicalMacroFactorPITFact, ...]
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        if type(self.source) is not PersistedMacroFactorResearchSourceDefinition:
            raise TypeError("macro-factor projection source type differs")
        source = self.source.validated_copy()
        _require_token(self.manifest_id, "macro-factor projection manifest_id")
        _require_hash(self.manifest_hash, "macro-factor projection manifest_hash")
        _require_aware(self.manifest_as_of, "macro-factor projection manifest_as_of")
        _require_aware(self.manifest_created_at, "macro-factor projection manifest_created_at")
        _require_token(self.knowledge_scope, "macro-factor projection knowledge_scope")
        ratio = _require_decimal(self.coverage_ratio, "macro-factor projection coverage_ratio")
        if not Decimal("0") <= ratio <= Decimal("1"):
            raise ValueError("macro-factor projection coverage is outside zero and one")
        for value, name in (
            (self.missing_count, "missing_count"),
            (self.estimated_count, "estimated_count"),
            (self.unknown_count, "unknown_count"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"macro-factor projection {name} is invalid")
        if type(self.is_verified) is not bool:
            raise TypeError("macro-factor projection is_verified must be exact bool")
        if type(self.facts) is not tuple or not self.facts:
            raise ValueError("macro-factor projection facts must be a non-empty tuple")
        facts = tuple(item.validated_copy() for item in self.facts)
        fact_keys = tuple((item.dataset_key, item.business_key) for item in facts)
        rule_keys = tuple(
            (item.dataset_key, item.business_key) for item in source.definition.members
        )
        if frozenset(fact_keys) != frozenset(rule_keys) or len(fact_keys) != len(rule_keys):
            raise ValueError("macro-factor projection does not cover exact member rules")
        facts_by_key = {(item.dataset_key, item.business_key): item for item in facts}
        for rule in source.definition.members:
            fact = facts_by_key[(rule.dataset_key, rule.business_key)]
            if (
                fact.row_id != rule.row_id
                or fact.role is not rule.role
                or fact.member_code != rule.member_code
                or fact.unit != rule.expected_unit
            ):
                raise ValueError("macro-factor projection fact differs from its exact member rule")
        if (
            self.knowledge_scope != source.definition.knowledge_scope
            or not source.is_active_at(self.manifest_as_of)
            or source.ledger_recorded_at > self.manifest_created_at
            or self.manifest_as_of > self.manifest_created_at
            or any(item.available_at > self.manifest_as_of for item in facts)
        ):
            raise ValueError("macro-factor projection clock/source graph differs")
        policy = source.definition.coverage_policy
        derived_verified = (
            ratio == Decimal("1")
            and self.missing_count == 0
            and self.estimated_count == 0
            and self.unknown_count == 0
            and all(item.pit_quality == "verified" for item in facts)
        )
        if self.is_verified is not derived_verified:
            raise ValueError("macro-factor projection verified status differs from facts")
        expected_verified = (
            (not policy.require_verified or self.is_verified)
            and ratio >= policy.minimum_coverage_ratio
            and self.missing_count <= policy.maximum_missing_count
            and self.estimated_count <= policy.maximum_estimated_count
            and self.unknown_count <= policy.maximum_unknown_count
        )
        if not expected_verified:
            raise ValueError("macro-factor projection violates its coverage policy")
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("macro-factor projection safety flags must remain true")

    def validated_copy(self) -> CanonicalMacroFactorPITProjection:
        """Replay the entire source, manifest, fact, clock, and policy graph."""

        copied = CanonicalMacroFactorPITProjection(
            source=self.source.validated_copy(),
            manifest_id=self.manifest_id,
            manifest_hash=self.manifest_hash,
            manifest_as_of=self.manifest_as_of,
            manifest_created_at=self.manifest_created_at,
            knowledge_scope=self.knowledge_scope,
            coverage_ratio=self.coverage_ratio,
            missing_count=self.missing_count,
            estimated_count=self.estimated_count,
            unknown_count=self.unknown_count,
            is_verified=self.is_verified,
            facts=tuple(item.validated_copy() for item in self.facts),
        )
        if copied != self:
            raise ValueError("macro-factor projection differs after replay")
        return copied


__all__ = [
    "CanonicalMacroFactorPITFact",
    "CanonicalMacroFactorPITProjection",
    "MacroFactorResearchCalendar",
    "MacroFactorResearchCoveragePolicy",
    "MacroFactorResearchMemberRole",
    "MacroFactorResearchMemberRule",
    "MacroFactorResearchPeriodKind",
    "MacroFactorResearchPeriodRule",
    "MacroFactorResearchSourceDefinition",
    "MacroFactorSourceSeal",
    "MacroFactorValueEncoding",
    "PersistedMacroFactorResearchSourceDefinition",
]
