"""Integrity-only binding for a complete simulated settlement execution plan.

The binding seals the exact plan inputs that were used for a simulated trade.
Its unkeyed SHA-256 digest detects storage inconsistency; it does not grant
authority, qualify a source, prove a market-to-exchange mapping, or replace
historical point-in-time validation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
    IdentityEvidenceValidationError,
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    CalendarEvidenceValidationError,
    CalendarPublicationReference,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
    SettlementExecutionPlan,
    SimulatedSettlementContractError,
    SimulatedTradeIntent,
)

_SCHEMA = "simulated-settlement-plan-binding.v1"
_FEE_POLICY_SCHEMA = "simulated-fee-policy.v2"
_RESPONSE_TIME_SEMANTICS = "local_response_body_completion"
_HASH_LENGTH = 64
_PREFIXED_HASH_LENGTH = len("sha256:") + _HASH_LENGTH
_MAX_TOKEN_LENGTH = 192
_MAX_IDEMPOTENCY_LENGTH = 128
_MAX_DATABASE_ID = 9_223_372_036_854_775_807
_MAX_LAG_SESSIONS = 2_147_483_647


class SettlementPlanBindingValidationError(SimulatedSettlementContractError):
    """Raised when a settlement-plan integrity binding is malformed or incomplete."""


def _require_token(value: object, field_name: str, *, maximum: int = _MAX_TOKEN_LENGTH) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise SettlementPlanBindingValidationError(
            f"{field_name} must be a bounded canonical token"
        )
    return value


def _require_hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SettlementPlanBindingValidationError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def _require_prefixed_hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != _PREFIXED_HASH_LENGTH
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise SettlementPlanBindingValidationError(
            f"{field_name} must be a prefixed lowercase SHA-256 digest"
        )
    return value


def _require_positive_id(value: object, field_name: str) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_DATABASE_ID:
        raise SettlementPlanBindingValidationError(
            f"{field_name} must be a positive bounded database identifier"
        )
    return value


def _normalize_utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise SettlementPlanBindingValidationError(
            f"{field_name} must be a timezone-aware datetime"
        )
    try:
        if value.utcoffset() is None:
            raise SettlementPlanBindingValidationError(
                f"{field_name} must be a timezone-aware datetime"
            )
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise SettlementPlanBindingValidationError(
            f"{field_name} cannot be normalized to UTC"
        ) from error


def _utc_text(value: datetime) -> str:
    return _normalize_utc(value, "datetime").isoformat().replace("+00:00", "Z")


def _parse_utc(value: object, field_name: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise SettlementPlanBindingValidationError(f"{field_name} must use canonical UTC text")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as error:
        raise SettlementPlanBindingValidationError(
            f"{field_name} is not a valid UTC instant"
        ) from error
    normalized = _normalize_utc(parsed, field_name)
    if _utc_text(normalized) != value:
        raise SettlementPlanBindingValidationError(f"{field_name} is not canonical UTC text")
    return normalized


def _date_text(value: date, field_name: str) -> str:
    if type(value) is not date:
        raise SettlementPlanBindingValidationError(f"{field_name} must be an exact date")
    return value.isoformat()


def _parse_date(value: object, field_name: str) -> date:
    if type(value) is not str:
        raise SettlementPlanBindingValidationError(f"{field_name} must be ISO date text")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise SettlementPlanBindingValidationError(
            f"{field_name} is not a valid ISO date"
        ) from error
    if parsed.isoformat() != value:
        raise SettlementPlanBindingValidationError(f"{field_name} is not canonical ISO date text")
    return parsed


def _canonical_hash(payload: dict[str, object]) -> str:
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise SettlementPlanBindingValidationError(
            "settlement plan binding is not canonical JSON"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _expect_object(
    payload: object,
    *,
    expected_keys: frozenset[str],
    field_name: str,
) -> dict[str, object]:
    if type(payload) is not dict:
        raise SettlementPlanBindingValidationError(f"{field_name} must be an object")
    fields = cast(dict[str, object], payload)
    if set(fields) != expected_keys:
        raise SettlementPlanBindingValidationError(f"{field_name} has missing or unknown fields")
    return fields


@dataclass(frozen=True, slots=True)
class CalendarSnapshotBindingV1:
    """Immutable identity summary for the exact calendar snapshot fact row."""

    snapshot_id: str
    exchange: str
    coverage_start: date
    coverage_end: date
    content_hash: str
    record_digest: str
    first_seen_at: datetime
    recorded_at: datetime
    source_published_at: datetime | None
    provider_name: str

    def __post_init__(self) -> None:
        """Validate snapshot identity and normalize its local/source clocks to UTC."""

        try:
            if str(UUID(self.snapshot_id)) != self.snapshot_id:
                raise ValueError
        except (AttributeError, TypeError, ValueError) as error:
            raise SettlementPlanBindingValidationError(
                "calendar snapshot_id must be a canonical UUID"
            ) from error
        _require_token(self.exchange, "calendar_snapshot.exchange")
        _require_token(self.provider_name, "calendar_snapshot.provider_name")
        if type(self.coverage_start) is not date or type(self.coverage_end) is not date:
            raise SettlementPlanBindingValidationError(
                "calendar snapshot coverage bounds must be exact dates"
            )
        if self.coverage_start > self.coverage_end:
            raise SettlementPlanBindingValidationError("calendar snapshot coverage is reversed")
        _require_prefixed_hash(self.content_hash, "calendar_snapshot.content_hash")
        _require_prefixed_hash(self.record_digest, "calendar_snapshot.record_digest")
        first_seen = _normalize_utc(self.first_seen_at, "calendar_snapshot.first_seen_at")
        recorded = _normalize_utc(self.recorded_at, "calendar_snapshot.recorded_at")
        if recorded < first_seen:
            raise SettlementPlanBindingValidationError(
                "calendar snapshot recorded_at cannot precede first_seen_at"
            )
        object.__setattr__(self, "first_seen_at", first_seen)
        object.__setattr__(self, "recorded_at", recorded)
        if self.source_published_at is not None:
            object.__setattr__(
                self,
                "source_published_at",
                _normalize_utc(self.source_published_at, "calendar_snapshot.source_published_at"),
            )

    def to_payload(self) -> dict[str, object]:
        """Return a fresh canonical payload for the exact snapshot row identity."""

        self.__post_init__()
        return {
            "snapshot_id": self.snapshot_id,
            "exchange": self.exchange,
            "coverage_start": _date_text(self.coverage_start, "coverage_start"),
            "coverage_end": _date_text(self.coverage_end, "coverage_end"),
            "content_hash": self.content_hash,
            "record_digest": self.record_digest,
            "first_seen_at": _utc_text(self.first_seen_at),
            "recorded_at": _utc_text(self.recorded_at),
            "source_published_at": (
                _utc_text(self.source_published_at)
                if self.source_published_at is not None
                else None
            ),
            "provider_name": self.provider_name,
        }

    @classmethod
    def from_payload(cls, payload: object) -> CalendarSnapshotBindingV1:
        """Strictly decode one exact calendar snapshot identity summary."""

        fields = _expect_object(
            payload,
            expected_keys=frozenset(
                {
                    "snapshot_id",
                    "exchange",
                    "coverage_start",
                    "coverage_end",
                    "content_hash",
                    "record_digest",
                    "first_seen_at",
                    "recorded_at",
                    "source_published_at",
                    "provider_name",
                }
            ),
            field_name="calendar_snapshot",
        )
        for name in (
            "snapshot_id",
            "exchange",
            "content_hash",
            "record_digest",
            "first_seen_at",
            "recorded_at",
            "provider_name",
        ):
            if type(fields[name]) is not str:
                raise SettlementPlanBindingValidationError(f"calendar_snapshot.{name} must be text")
        source_published_at = fields["source_published_at"]
        if source_published_at is not None and type(source_published_at) is not str:
            raise SettlementPlanBindingValidationError(
                "calendar_snapshot.source_published_at must be text or null"
            )
        return cls(
            snapshot_id=cast(str, fields["snapshot_id"]),
            exchange=cast(str, fields["exchange"]),
            coverage_start=_parse_date(fields["coverage_start"], "coverage_start"),
            coverage_end=_parse_date(fields["coverage_end"], "coverage_end"),
            content_hash=cast(str, fields["content_hash"]),
            record_digest=cast(str, fields["record_digest"]),
            first_seen_at=_parse_utc(fields["first_seen_at"], "first_seen_at"),
            recorded_at=_parse_utc(fields["recorded_at"], "recorded_at"),
            source_published_at=(
                _parse_utc(source_published_at, "source_published_at")
                if source_published_at is not None
                else None
            ),
            provider_name=cast(str, fields["provider_name"]),
        )


@dataclass(frozen=True, slots=True)
class CalendarRawReferenceBindingV1:
    """Immutable raw-response identity bound to a calendar snapshot summary."""

    payload_id: str
    payload_hash: str
    record_digest: str
    body_sha256: str
    retained_content_sha256: str
    request_scope_sha256: str
    original_body_retained: bool
    response_completed_at: datetime
    response_time_semantics: str
    provider_name: str
    dataset_key: str
    transport: str

    def __post_init__(self) -> None:
        """Validate the retained raw identity without inventing an upstream clock."""

        try:
            if str(UUID(self.payload_id)) != self.payload_id:
                raise ValueError
        except (AttributeError, TypeError, ValueError) as error:
            raise SettlementPlanBindingValidationError(
                "calendar raw payload_id must be a canonical UUID"
            ) from error
        _require_prefixed_hash(self.payload_hash, "calendar_raw_reference.payload_hash")
        _require_prefixed_hash(self.record_digest, "calendar_raw_reference.record_digest")
        _require_hash(self.body_sha256, "calendar_raw_reference.body_sha256")
        _require_hash(
            self.retained_content_sha256,
            "calendar_raw_reference.retained_content_sha256",
        )
        _require_hash(
            self.request_scope_sha256,
            "calendar_raw_reference.request_scope_sha256",
        )
        if type(self.original_body_retained) is not bool or not self.original_body_retained:
            raise SettlementPlanBindingValidationError(
                "calendar raw identity requires the exact retained response body"
            )
        if self.retained_content_sha256 != self.body_sha256:
            raise SettlementPlanBindingValidationError(
                "calendar raw retained-content digest differs from the exact body digest"
            )
        _normalize_utc(self.response_completed_at, "calendar_raw_reference.response_completed_at")
        _require_token(self.provider_name, "calendar_raw_reference.provider_name")
        _require_token(self.dataset_key, "calendar_raw_reference.dataset_key")
        if type(self.response_time_semantics) is not str or (
            self.response_time_semantics != _RESPONSE_TIME_SEMANTICS
        ):
            raise SettlementPlanBindingValidationError(
                "calendar raw response clock must retain its local completion semantics"
            )
        if type(self.transport) is not str or self.transport not in {"direct", "egress"}:
            raise SettlementPlanBindingValidationError(
                "calendar raw transport must be direct or egress"
            )
        object.__setattr__(
            self,
            "response_completed_at",
            _normalize_utc(
                self.response_completed_at,
                "calendar_raw_reference.response_completed_at",
            ),
        )

    def to_payload(self) -> dict[str, object]:
        """Return a fresh exact raw response reference with its clock semantics."""

        self.__post_init__()
        return {
            "payload_id": self.payload_id,
            "payload_hash": self.payload_hash,
            "record_digest": self.record_digest,
            "body_sha256": self.body_sha256,
            "retained_content_sha256": self.retained_content_sha256,
            "request_scope_sha256": self.request_scope_sha256,
            "original_body_retained": self.original_body_retained,
            "response_completed_at": _utc_text(self.response_completed_at),
            "response_time_semantics": self.response_time_semantics,
            "provider_name": self.provider_name,
            "dataset_key": self.dataset_key,
            "transport": self.transport,
        }

    @classmethod
    def from_payload(cls, payload: object) -> CalendarRawReferenceBindingV1:
        """Strictly decode one exact raw-response identity summary."""

        fields = _expect_object(
            payload,
            expected_keys=frozenset(
                {
                    "payload_id",
                    "payload_hash",
                    "record_digest",
                    "body_sha256",
                    "retained_content_sha256",
                    "request_scope_sha256",
                    "original_body_retained",
                    "response_completed_at",
                    "response_time_semantics",
                    "provider_name",
                    "dataset_key",
                    "transport",
                }
            ),
            field_name="calendar_raw_reference",
        )
        for name in (
            "payload_id",
            "payload_hash",
            "record_digest",
            "body_sha256",
            "retained_content_sha256",
            "request_scope_sha256",
            "response_completed_at",
            "response_time_semantics",
            "provider_name",
            "dataset_key",
            "transport",
        ):
            if type(fields[name]) is not str:
                raise SettlementPlanBindingValidationError(
                    f"calendar_raw_reference.{name} must be text"
                )
        if type(fields["original_body_retained"]) is not bool:
            raise SettlementPlanBindingValidationError(
                "calendar_raw_reference.original_body_retained must be boolean"
            )
        return cls(
            payload_id=cast(str, fields["payload_id"]),
            payload_hash=cast(str, fields["payload_hash"]),
            record_digest=cast(str, fields["record_digest"]),
            body_sha256=cast(str, fields["body_sha256"]),
            retained_content_sha256=cast(str, fields["retained_content_sha256"]),
            request_scope_sha256=cast(str, fields["request_scope_sha256"]),
            original_body_retained=fields["original_body_retained"],
            response_completed_at=_parse_utc(
                fields["response_completed_at"], "response_completed_at"
            ),
            response_time_semantics=cast(str, fields["response_time_semantics"]),
            provider_name=cast(str, fields["provider_name"]),
            dataset_key=cast(str, fields["dataset_key"]),
            transport=cast(str, fields["transport"]),
        )


@dataclass(frozen=True, slots=True)
class CalendarPublicationBindingV1:
    """Immutable publication/member/policy identity and exact reference window."""

    publication_id: str
    member_id: str
    publication_hash: str
    fact_content_hash: str
    policy_hash: str
    published_at: datetime
    recorded_at: datetime
    reference_valid_from: datetime
    reference_valid_until: datetime
    timezone_name: str

    def __post_init__(self) -> None:
        """Validate publication identity and normalize its system knowledge clocks."""

        _require_token(self.publication_id, "calendar_publication.publication_id")
        _require_token(self.member_id, "calendar_publication.member_id")
        for field_name in ("publication_hash", "fact_content_hash", "policy_hash"):
            _require_hash(getattr(self, field_name), f"calendar_publication.{field_name}")
        normalized: dict[str, datetime] = {}
        for field_name in (
            "published_at",
            "recorded_at",
            "reference_valid_from",
            "reference_valid_until",
        ):
            normalized[field_name] = _normalize_utc(
                getattr(self, field_name), f"calendar_publication.{field_name}"
            )
        if normalized["published_at"] > normalized["recorded_at"]:
            raise SettlementPlanBindingValidationError(
                "calendar publication recorded_at cannot precede published_at"
            )
        if normalized["reference_valid_from"] >= normalized["reference_valid_until"]:
            raise SettlementPlanBindingValidationError(
                "calendar publication reference window is invalid"
            )
        _require_token(self.timezone_name, "calendar_publication.timezone_name")
        try:
            ZoneInfo(self.timezone_name)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise SettlementPlanBindingValidationError(
                "calendar publication timezone is unknown"
            ) from error
        for field_name, value in normalized.items():
            object.__setattr__(self, field_name, value)

    def to_payload(self) -> dict[str, object]:
        """Return a fresh exact published-member reference payload."""

        self.__post_init__()
        return {
            "publication_id": self.publication_id,
            "member_id": self.member_id,
            "publication_hash": self.publication_hash,
            "fact_content_hash": self.fact_content_hash,
            "policy_hash": self.policy_hash,
            "published_at": _utc_text(self.published_at),
            "recorded_at": _utc_text(self.recorded_at),
            "reference_valid_from": _utc_text(self.reference_valid_from),
            "reference_valid_until": _utc_text(self.reference_valid_until),
            "timezone_name": self.timezone_name,
        }

    @classmethod
    def from_payload(cls, payload: object) -> CalendarPublicationBindingV1:
        """Strictly decode one exact publication-member identity summary."""

        fields = _expect_object(
            payload,
            expected_keys=frozenset(
                {
                    "publication_id",
                    "member_id",
                    "publication_hash",
                    "fact_content_hash",
                    "policy_hash",
                    "published_at",
                    "recorded_at",
                    "reference_valid_from",
                    "reference_valid_until",
                    "timezone_name",
                }
            ),
            field_name="calendar_publication",
        )
        for name in (
            "publication_id",
            "member_id",
            "publication_hash",
            "fact_content_hash",
            "policy_hash",
            "published_at",
            "recorded_at",
            "reference_valid_from",
            "reference_valid_until",
            "timezone_name",
        ):
            if type(fields[name]) is not str:
                raise SettlementPlanBindingValidationError(
                    f"calendar_publication.{name} must be text"
                )
        return cls(
            publication_id=cast(str, fields["publication_id"]),
            member_id=cast(str, fields["member_id"]),
            publication_hash=cast(str, fields["publication_hash"]),
            fact_content_hash=cast(str, fields["fact_content_hash"]),
            policy_hash=cast(str, fields["policy_hash"]),
            published_at=_parse_utc(fields["published_at"], "published_at"),
            recorded_at=_parse_utc(fields["recorded_at"], "recorded_at"),
            reference_valid_from=_parse_utc(fields["reference_valid_from"], "reference_valid_from"),
            reference_valid_until=_parse_utc(
                fields["reference_valid_until"], "reference_valid_until"
            ),
            timezone_name=cast(str, fields["timezone_name"]),
        )


@dataclass(frozen=True, slots=True)
class SimulatedSettlementPlanBindingV1:
    """Canonical integrity summary of one fully validated settlement plan.

    This DTO is a checksum envelope, not a signature, authorization receipt,
    source qualification, exchange mapping, or historical-evidence substitute.
    """

    account_id: int
    user_id: int
    idempotency_key: str
    request_payload_hash: str
    pre_read_at: datetime
    executed_at: datetime
    market_session: date
    settlement_lag_sessions: int
    settlement_release_date: date | None
    settlement_bundle_id: str
    settlement_bundle_version: str
    settlement_bundle_hash: str
    settlement_policy_id: str
    settlement_policy_version: str
    settlement_policy_hash: str
    execution_rule_v2_hash: str
    bundle_source_observed_at: datetime
    bundle_source_available_at: datetime
    bundle_effective_from: datetime
    bundle_valid_until: datetime
    calendar_evidence_hash: str
    calendar_snapshot: CalendarSnapshotBindingV1
    calendar_raw_reference: CalendarRawReferenceBindingV1
    calendar_publication: CalendarPublicationBindingV1
    fee_policy_schema: str
    fee_policy_content_hash: str

    def __post_init__(self) -> None:
        """Validate all summary fields and their derivable cross-field bindings."""

        _require_positive_id(self.account_id, "account_id")
        _require_positive_id(self.user_id, "user_id")
        _require_token(self.idempotency_key, "idempotency_key", maximum=_MAX_IDEMPOTENCY_LENGTH)
        for name in (
            "request_payload_hash",
            "settlement_bundle_hash",
            "settlement_policy_hash",
            "execution_rule_v2_hash",
            "calendar_evidence_hash",
            "fee_policy_content_hash",
        ):
            _require_hash(getattr(self, name), name)
        for name in (
            "settlement_bundle_id",
            "settlement_bundle_version",
            "settlement_policy_id",
            "settlement_policy_version",
        ):
            _require_token(getattr(self, name), name)
        if type(self.market_session) is not date:
            raise SettlementPlanBindingValidationError("market_session must be an exact date")
        if type(self.settlement_lag_sessions) is not int or not (
            0 <= self.settlement_lag_sessions <= _MAX_LAG_SESSIONS
        ):
            raise SettlementPlanBindingValidationError(
                "settlement_lag_sessions must be a bounded nonnegative integer"
            )
        if (
            self.settlement_release_date is not None
            and type(self.settlement_release_date) is not date
        ):
            raise SettlementPlanBindingValidationError(
                "settlement_release_date must be an exact date or null"
            )
        for name in (
            "pre_read_at",
            "executed_at",
            "bundle_source_observed_at",
            "bundle_source_available_at",
            "bundle_effective_from",
            "bundle_valid_until",
        ):
            object.__setattr__(self, name, _normalize_utc(getattr(self, name), name))
        if self.executed_at < self.pre_read_at:
            raise SettlementPlanBindingValidationError(
                "executed_at cannot precede the plan pre_read_at"
            )
        if not (
            self.bundle_source_observed_at <= self.bundle_source_available_at <= self.pre_read_at
            and self.bundle_effective_from <= self.pre_read_at < self.bundle_valid_until
        ):
            raise SettlementPlanBindingValidationError(
                "settlement bundle clocks do not cover the plan pre-read cutoff"
            )
        if not self.bundle_source_observed_at <= self.executed_at < self.bundle_valid_until:
            raise SettlementPlanBindingValidationError(
                "settlement bundle clocks do not cover the execution cutoff"
            )
        if self.fee_policy_schema != _FEE_POLICY_SCHEMA:
            raise SettlementPlanBindingValidationError("fee_policy_schema is unsupported")
        if type(self.calendar_snapshot) is not CalendarSnapshotBindingV1:
            raise SettlementPlanBindingValidationError("calendar_snapshot has an invalid type")
        self.calendar_snapshot.__post_init__()
        if type(self.calendar_raw_reference) is not CalendarRawReferenceBindingV1:
            raise SettlementPlanBindingValidationError("calendar_raw_reference has an invalid type")
        self.calendar_raw_reference.__post_init__()
        if type(self.calendar_publication) is not CalendarPublicationBindingV1:
            raise SettlementPlanBindingValidationError("calendar_publication has an invalid type")
        self.calendar_publication.__post_init__()
        if not (
            self.calendar_snapshot.coverage_start
            <= self.market_session
            <= self.calendar_snapshot.coverage_end
        ):
            raise SettlementPlanBindingValidationError(
                "market_session is outside the retained calendar coverage"
            )
        if self.calendar_snapshot.snapshot_id != self.calendar_publication.member_id:
            raise SettlementPlanBindingValidationError(
                "calendar publication member differs from the exact snapshot identity"
            )
        if self.calendar_snapshot.provider_name != self.calendar_raw_reference.provider_name:
            raise SettlementPlanBindingValidationError(
                "calendar snapshot and raw reference providers differ"
            )
        if (
            self.calendar_snapshot.first_seen_at
            != self.calendar_raw_reference.response_completed_at
        ):
            raise SettlementPlanBindingValidationError(
                "calendar first_seen_at differs from raw response completion"
            )
        if not (
            self.calendar_snapshot.first_seen_at <= self.pre_read_at
            and self.calendar_snapshot.recorded_at <= self.pre_read_at
            and self.calendar_publication.published_at <= self.pre_read_at
            and self.calendar_publication.recorded_at <= self.pre_read_at
            and self.calendar_publication.reference_valid_from
            <= self.pre_read_at
            < self.calendar_publication.reference_valid_until
        ):
            raise SettlementPlanBindingValidationError(
                "calendar evidence was unknown or outside its window at pre_read_at"
            )
        if self.calendar_snapshot.source_published_at is not None and (
            self.calendar_snapshot.source_published_at > self.pre_read_at
        ):
            raise SettlementPlanBindingValidationError(
                "calendar source publication time is later than pre_read_at"
            )
        if not (
            self.calendar_snapshot.first_seen_at <= self.executed_at
            and self.calendar_snapshot.recorded_at <= self.executed_at
            and self.calendar_publication.published_at <= self.executed_at
            and self.calendar_publication.recorded_at <= self.executed_at
            and self.calendar_publication.reference_valid_from
            <= self.executed_at
            < self.calendar_publication.reference_valid_until
        ):
            raise SettlementPlanBindingValidationError(
                "calendar evidence was unknown or outside its window at executed_at"
            )
        if self.calendar_snapshot.source_published_at is not None and (
            self.calendar_snapshot.source_published_at > self.executed_at
        ):
            raise SettlementPlanBindingValidationError(
                "calendar source publication time is later than executed_at"
            )

    @property
    def content_hash(self) -> str:
        """Return the independent unprefixed SHA-256 of the canonical payload."""

        return _canonical_hash(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return a fresh canonical payload without embedding its own hash."""

        self.__post_init__()
        return {
            "schema": _SCHEMA,
            "account_id": self.account_id,
            "user_id": self.user_id,
            "idempotency_key": self.idempotency_key,
            "request_payload_hash": self.request_payload_hash,
            "pre_read_at": _utc_text(self.pre_read_at),
            "executed_at": _utc_text(self.executed_at),
            "market_session": _date_text(self.market_session, "market_session"),
            "settlement_lag_sessions": self.settlement_lag_sessions,
            "settlement_release_date": (
                _date_text(self.settlement_release_date, "settlement_release_date")
                if self.settlement_release_date is not None
                else None
            ),
            "settlement_bundle_id": self.settlement_bundle_id,
            "settlement_bundle_version": self.settlement_bundle_version,
            "settlement_bundle_hash": self.settlement_bundle_hash,
            "settlement_policy_id": self.settlement_policy_id,
            "settlement_policy_version": self.settlement_policy_version,
            "settlement_policy_hash": self.settlement_policy_hash,
            "execution_rule_v2_hash": self.execution_rule_v2_hash,
            "bundle_source_observed_at": _utc_text(self.bundle_source_observed_at),
            "bundle_source_available_at": _utc_text(self.bundle_source_available_at),
            "bundle_effective_from": _utc_text(self.bundle_effective_from),
            "bundle_valid_until": _utc_text(self.bundle_valid_until),
            "calendar_evidence_hash": self.calendar_evidence_hash,
            "calendar_snapshot": self.calendar_snapshot.to_payload(),
            "calendar_raw_reference": self.calendar_raw_reference.to_payload(),
            "calendar_publication": self.calendar_publication.to_payload(),
            "fee_policy_schema": self.fee_policy_schema,
            "fee_policy_content_hash": self.fee_policy_content_hash,
        }

    @classmethod
    def from_payload(cls, payload: object) -> SimulatedSettlementPlanBindingV1:
        """Strictly decode one binding payload and compute its independent hash."""

        expected_keys = frozenset(
            {
                "schema",
                "account_id",
                "user_id",
                "idempotency_key",
                "request_payload_hash",
                "pre_read_at",
                "executed_at",
                "market_session",
                "settlement_lag_sessions",
                "settlement_release_date",
                "settlement_bundle_id",
                "settlement_bundle_version",
                "settlement_bundle_hash",
                "settlement_policy_id",
                "settlement_policy_version",
                "settlement_policy_hash",
                "execution_rule_v2_hash",
                "bundle_source_observed_at",
                "bundle_source_available_at",
                "bundle_effective_from",
                "bundle_valid_until",
                "calendar_evidence_hash",
                "calendar_snapshot",
                "calendar_raw_reference",
                "calendar_publication",
                "fee_policy_schema",
                "fee_policy_content_hash",
            }
        )
        fields = _expect_object(payload, expected_keys=expected_keys, field_name="binding")
        if type(fields["schema"]) is not str or fields["schema"] != _SCHEMA:
            raise SettlementPlanBindingValidationError("binding schema is unsupported")
        for name in (
            "account_id",
            "user_id",
            "settlement_lag_sessions",
        ):
            if type(fields[name]) is not int:
                raise SettlementPlanBindingValidationError(f"{name} must be an exact integer")
        for name in (
            "idempotency_key",
            "request_payload_hash",
            "pre_read_at",
            "executed_at",
            "market_session",
            "settlement_bundle_id",
            "settlement_bundle_version",
            "settlement_bundle_hash",
            "settlement_policy_id",
            "settlement_policy_version",
            "settlement_policy_hash",
            "execution_rule_v2_hash",
            "bundle_source_observed_at",
            "bundle_source_available_at",
            "bundle_effective_from",
            "bundle_valid_until",
            "calendar_evidence_hash",
            "fee_policy_schema",
            "fee_policy_content_hash",
        ):
            if type(fields[name]) is not str:
                raise SettlementPlanBindingValidationError(f"{name} must be text")
        release_text = fields["settlement_release_date"]
        if release_text is not None and type(release_text) is not str:
            raise SettlementPlanBindingValidationError(
                "settlement_release_date must be ISO date text or null"
            )
        return cls(
            account_id=cast(int, fields["account_id"]),
            user_id=cast(int, fields["user_id"]),
            idempotency_key=cast(str, fields["idempotency_key"]),
            request_payload_hash=cast(str, fields["request_payload_hash"]),
            pre_read_at=_parse_utc(fields["pre_read_at"], "pre_read_at"),
            executed_at=_parse_utc(fields["executed_at"], "executed_at"),
            market_session=_parse_date(fields["market_session"], "market_session"),
            settlement_lag_sessions=cast(int, fields["settlement_lag_sessions"]),
            settlement_release_date=(
                _parse_date(release_text, "settlement_release_date")
                if release_text is not None
                else None
            ),
            settlement_bundle_id=cast(str, fields["settlement_bundle_id"]),
            settlement_bundle_version=cast(str, fields["settlement_bundle_version"]),
            settlement_bundle_hash=cast(str, fields["settlement_bundle_hash"]),
            settlement_policy_id=cast(str, fields["settlement_policy_id"]),
            settlement_policy_version=cast(str, fields["settlement_policy_version"]),
            settlement_policy_hash=cast(str, fields["settlement_policy_hash"]),
            execution_rule_v2_hash=cast(str, fields["execution_rule_v2_hash"]),
            bundle_source_observed_at=_parse_utc(
                fields["bundle_source_observed_at"], "bundle_source_observed_at"
            ),
            bundle_source_available_at=_parse_utc(
                fields["bundle_source_available_at"], "bundle_source_available_at"
            ),
            bundle_effective_from=_parse_utc(
                fields["bundle_effective_from"], "bundle_effective_from"
            ),
            bundle_valid_until=_parse_utc(fields["bundle_valid_until"], "bundle_valid_until"),
            calendar_evidence_hash=cast(str, fields["calendar_evidence_hash"]),
            calendar_snapshot=CalendarSnapshotBindingV1.from_payload(fields["calendar_snapshot"]),
            calendar_raw_reference=CalendarRawReferenceBindingV1.from_payload(
                fields["calendar_raw_reference"]
            ),
            calendar_publication=CalendarPublicationBindingV1.from_payload(
                fields["calendar_publication"]
            ),
            fee_policy_schema=cast(str, fields["fee_policy_schema"]),
            fee_policy_content_hash=cast(str, fields["fee_policy_content_hash"]),
        )


@dataclass(frozen=True, slots=True)
class SimulatedSettlementPlanBindingV2:
    """V2 checksum wrapper joining the unchanged common summary and identity.

    The nested V1 summary retains its original payload and digest semantics.
    This outer unkeyed digest detects storage inconsistency only; it does not
    authorize execution or make source-reference evidence decision-ready.
    """

    common_binding: SimulatedSettlementPlanBindingV1
    identity_evidence: ExecutionInstrumentIdentityEvidenceV1

    def __post_init__(self) -> None:
        """Validate the exact nested contracts and their exchange/time binding."""

        if type(self.common_binding) is not SimulatedSettlementPlanBindingV1:
            raise SettlementPlanBindingValidationError(
                "common_binding must be SimulatedSettlementPlanBindingV1"
            )
        if type(self.identity_evidence) is not ExecutionInstrumentIdentityEvidenceV1:
            raise SettlementPlanBindingValidationError(
                "identity_evidence must be ExecutionInstrumentIdentityEvidenceV1"
            )
        self.common_binding.__post_init__()
        self.identity_evidence.__post_init__()
        if self.common_binding.calendar_snapshot.exchange != self.identity_evidence.source_exchange:
            raise SettlementPlanBindingValidationError(
                "identity source exchange differs from the bound calendar exchange"
            )
        try:
            self.identity_evidence.validate_at(as_of=self.common_binding.pre_read_at)
            self.identity_evidence.validate_at(as_of=self.common_binding.executed_at)
        except IdentityEvidenceValidationError as error:
            raise SettlementPlanBindingValidationError(str(error)) from error

    @property
    def content_hash(self) -> str:
        """Return the unprefixed SHA-256 over this exact v2 envelope."""

        return _canonical_hash(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return the strict V2 envelope without embedding its storage hash."""

        self.__post_init__()
        return {
            "schema": "simulated-settlement-plan-binding.v2",
            "common_binding": self.common_binding.to_payload(),
            "identity_evidence": self.identity_evidence.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: object) -> SimulatedSettlementPlanBindingV2:
        """Strictly decode one exact V2 envelope using the unchanged V1 codec."""

        fields = _expect_object(
            payload,
            expected_keys=frozenset({"schema", "common_binding", "identity_evidence"}),
            field_name="binding_v2",
        )
        if (
            type(fields["schema"]) is not str
            or fields["schema"] != "simulated-settlement-plan-binding.v2"
        ):
            raise SettlementPlanBindingValidationError("binding_v2 schema is unsupported")
        return cls(
            common_binding=SimulatedSettlementPlanBindingV1.from_payload(fields["common_binding"]),
            identity_evidence=ExecutionInstrumentIdentityEvidenceV1.from_payload(
                fields["identity_evidence"]
            ),
        )


def _build_settlement_plan_common_binding(
    plan: SettlementExecutionPlan,
    *,
    executed_at: datetime,
) -> SimulatedSettlementPlanBindingV1:
    """Build the unchanged V1 common summary for either exact plan version.

    The supplied execution time is normalized to UTC and revalidates the exact
    plan after its evidence cutoff. It is not a new market/source timestamp.
    """

    try:
        SettlementExecutionPlan.__post_init__(plan)
        normalized_executed_at = _normalize_utc(executed_at, "executed_at")
        plan.validate_at(normalized_executed_at)
        intent: SimulatedTradeIntent = plan.intent
        evidence: ExecutionCalendarEvidence = plan.calendar_evidence
        snapshot: ExchangeCalendarSnapshot = evidence.snapshot
        publication: CalendarPublicationReference | None = evidence.publication
        if publication is None:
            raise CalendarEvidenceValidationError(
                "settlement plan requires an exact published calendar member"
            )
        raw: RawCalendarReference = snapshot.raw_reference
        fee_policy = plan.fee_policy_v2
        if type(fee_policy) is not SimulatedFeePolicyV2:
            raise SettlementPlanBindingValidationError(
                "settlement binding requires the exact SimulatedFeePolicyV2 snapshot"
            )
        SimulatedFeePolicyV2.__post_init__(fee_policy)
        fee_payload = fee_policy.to_payload()
        if fee_payload.get("schema") != _FEE_POLICY_SCHEMA:
            raise SettlementPlanBindingValidationError("fee policy schema is unsupported")
        fee_rebuilt = SimulatedFeePolicyV2.from_payload(fee_payload)
        if fee_rebuilt.content_hash != fee_policy.content_hash:
            raise SettlementPlanBindingValidationError(
                "fee policy payload does not match its declared content hash"
            )
        if snapshot.exchange != plan._expected_calendar_exchange:
            raise SettlementPlanBindingValidationError(
                "calendar exchange does not match the exact plan exchange"
            )
        return SimulatedSettlementPlanBindingV1(
            account_id=intent.account_id,
            user_id=intent.user_id,
            idempotency_key=intent.idempotency_key,
            request_payload_hash=intent.request_payload_hash,
            pre_read_at=_normalize_utc(plan.pre_read_at, "pre_read_at"),
            executed_at=normalized_executed_at,
            market_session=plan.market_session,
            settlement_lag_sessions=plan.settlement_lag_sessions,
            settlement_release_date=plan.settlement_release_date,
            settlement_bundle_id=plan.settlement_bundle_id,
            settlement_bundle_version=plan.settlement_bundle_version,
            settlement_bundle_hash=plan.settlement_bundle_hash,
            settlement_policy_id=plan.settlement_policy_id,
            settlement_policy_version=plan.settlement_policy_version,
            settlement_policy_hash=plan.settlement_policy_hash,
            execution_rule_v2_hash=plan.execution_rule_v2_hash,
            bundle_source_observed_at=_normalize_utc(
                plan.bundle_source_observed_at, "bundle_source_observed_at"
            ),
            bundle_source_available_at=_normalize_utc(
                plan.bundle_source_available_at, "bundle_source_available_at"
            ),
            bundle_effective_from=_normalize_utc(
                plan.bundle_effective_from, "bundle_effective_from"
            ),
            bundle_valid_until=_normalize_utc(plan.bundle_valid_until, "bundle_valid_until"),
            calendar_evidence_hash=evidence.evidence_hash,
            calendar_snapshot=CalendarSnapshotBindingV1(
                snapshot_id=snapshot.snapshot_id,
                exchange=snapshot.exchange,
                coverage_start=snapshot.coverage_start,
                coverage_end=snapshot.coverage_end,
                content_hash=snapshot.content_hash,
                record_digest=snapshot.record_digest,
                first_seen_at=snapshot.first_seen_at,
                recorded_at=snapshot.recorded_at,
                source_published_at=snapshot.source_published_at,
                provider_name=snapshot.provider_name,
            ),
            calendar_raw_reference=CalendarRawReferenceBindingV1(
                payload_id=raw.payload_id,
                payload_hash=raw.payload_hash,
                record_digest=raw.record_digest,
                body_sha256=raw.body_sha256,
                retained_content_sha256=raw.retained_content_sha256,
                request_scope_sha256=raw.request_scope_sha256,
                original_body_retained=raw.original_body_retained,
                response_completed_at=raw.response_completed_at,
                response_time_semantics=_RESPONSE_TIME_SEMANTICS,
                provider_name=raw.provider_name,
                dataset_key=raw.dataset_key,
                transport=raw.transport,
            ),
            calendar_publication=CalendarPublicationBindingV1(
                publication_id=publication.publication_id,
                member_id=publication.member_id,
                publication_hash=publication.publication_hash,
                fact_content_hash=publication.fact_content_hash,
                policy_hash=publication.policy_hash,
                published_at=publication.published_at,
                recorded_at=publication.recorded_at,
                reference_valid_from=publication.reference_valid_from,
                reference_valid_until=publication.reference_valid_until,
                timezone_name=publication.timezone_name,
            ),
            fee_policy_schema=cast(str, fee_payload["schema"]),
            fee_policy_content_hash=fee_policy.content_hash,
        )
    except SettlementPlanBindingValidationError:
        raise
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        if isinstance(error, SimulatedSettlementContractError):
            raise SettlementPlanBindingValidationError(str(error)) from error
        raise SettlementPlanBindingValidationError(
            "settlement execution plan failed binding validation"
        ) from error


def bind_settlement_execution_plan(
    plan: SettlementExecutionPlan,
    *,
    executed_at: datetime,
) -> SimulatedSettlementPlanBindingV1:
    """Seal one exact V1 plan while preserving its established wire contract."""

    if type(plan) is not SettlementExecutionPlan:
        raise SettlementPlanBindingValidationError("plan must be SettlementExecutionPlan")
    return _build_settlement_plan_common_binding(plan, executed_at=executed_at)


def bind_settlement_execution_plan_v2(
    plan: SettlementExecutionPlanV2,
    *,
    executed_at: datetime,
) -> SimulatedSettlementPlanBindingV2:
    """Seal one exact V2 plan with the common V1 summary and identity receipt."""

    if type(plan) is not SettlementExecutionPlanV2:
        raise SettlementPlanBindingValidationError("plan must be SettlementExecutionPlanV2")
    try:
        common_binding = _build_settlement_plan_common_binding(plan, executed_at=executed_at)
        return SimulatedSettlementPlanBindingV2(
            common_binding=common_binding,
            identity_evidence=plan.identity_evidence,
        )
    except SettlementPlanBindingValidationError:
        raise
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise SettlementPlanBindingValidationError(
            "settlement V2 plan failed binding validation"
        ) from error


__all__: tuple[str, ...] = (
    "CalendarPublicationBindingV1",
    "CalendarRawReferenceBindingV1",
    "CalendarSnapshotBindingV1",
    "SettlementPlanBindingValidationError",
    "SimulatedSettlementPlanBindingV1",
    "SimulatedSettlementPlanBindingV2",
    "bind_settlement_execution_plan",
    "bind_settlement_execution_plan_v2",
)
