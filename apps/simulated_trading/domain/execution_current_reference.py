"""Current-purpose instrument identity receipts for simulated execution.

This module preserves the exact V1 source evidence while binding it to an
explicit local selector and one retained per-security source occurrence. The
local age window does not qualify upstream clocks, authorize a broker, or prove
historical point-in-time availability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TypedDict, cast
from uuid import UUID

from .execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
    IdentityEvidenceValidationError,
)
from .execution_settlement_identity import _normalize_utc as _normalize_identity_utc
from .execution_settlement_identity import _object as _identity_object
from .execution_settlement_identity import _parse_utc as _parse_identity_utc
from .execution_settlement_identity import _parse_uuid as _parse_identity_uuid
from .execution_settlement_identity import _require_token as _require_identity_token
from .execution_settlement_identity import _utc_text as _identity_utc_text
from .execution_settlement_plan_binding import (
    SettlementPlanBindingValidationError,
    SimulatedSettlementPlanBindingV1,
    _build_settlement_plan_common_binding,
    _canonical_hash,
)
from .execution_settlement_uow import (
    SettlementExecutionPlan,
    SimulatedTradeIntent,
)

_SELECTION_SCHEMA = "simulated-current-reference-selection.v1"
_IDENTITY_V2_SCHEMA = "simulated-execution-instrument-identity.v2"
_BINDING_V3_SCHEMA = "simulated-settlement-plan-binding.v3"
_LOCAL_STOP_LOSS_AUDIT_SCHEMA = "local-simulated-stop-loss-market-audit.v1"
_SHA256_LENGTH = 64


class LocalSimulatedExecutionMarketAuditPayload(TypedDict):
    """Exact persisted audit fields for a scoped local stop-loss execution."""

    schema: str
    purpose: str
    account_id: int
    user_id: int
    idempotency_key: str
    request_payload_hash: str
    security_id: str
    asset_code: str
    side: str
    execution_price: str
    source_id: str
    source_version: str
    source_hash: str
    source_observed_at: str
    source_available_at: str
    source_valid_until: str
    policy_id: str
    policy_version: str
    policy_hash: str
    market_hash: str
    market_bundle_hash: str
    rule_hash: str
    calendar_hash: str
    risk_decision_hash: str
    risk_evaluated_at: str
    evidence: dict[str, object]
    evidence_hash: str
    content_hash: str


def _canonical_json_text(value: object) -> str:
    """Return one exact canonical JSON string for immutable nested audit data."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise SettlementPlanBindingValidationError(
            "local market audit evidence is not canonical JSON"
        ) from error


def _audit_json_hash(value: object) -> str:
    """Hash an exact JSON-compatible audit value with canonical UTF-8 encoding."""

    return hashlib.sha256(_canonical_json_text(value).encode("utf-8")).hexdigest()


def _audit_datetime_text(value: datetime) -> str:
    """Return the established UTC text representation for one audit clock."""

    return _identity_utc_text(_normalize_identity_utc(value, "local_market_audit_clock"))


def _parse_audit_datetime(value: object, field_name: str) -> datetime:
    """Parse and normalize one exact aware timestamp from an audit payload."""

    if type(value) is not str:
        raise SettlementPlanBindingValidationError(f"{field_name} must be timestamp text")
    try:
        return _parse_identity_utc(value)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise SettlementPlanBindingValidationError(f"{field_name} is invalid") from error


@dataclass(frozen=True, slots=True)
class LocalSimulatedExecutionMarketAuditV1:
    """Seal raw local-market evidence to one exact normal-simulation SELL.

    Nested source, policy, market, Risk, and locked-position evidence is retained
    as canonical JSON text so a frozen dataclass cannot expose mutable audit
    dictionaries. The enclosing V3 settlement binding adds a second hash seal.
    """

    account_id: int
    user_id: int
    idempotency_key: str
    request_payload_hash: str
    security_id: str
    asset_code: str
    execution_price: Decimal
    source_id: str
    source_version: str
    source_hash: str
    source_observed_at: datetime
    source_available_at: datetime
    source_valid_until: datetime
    policy_id: str
    policy_version: str
    policy_hash: str
    market_hash: str
    market_bundle_hash: str
    rule_hash: str
    calendar_hash: str
    risk_decision_hash: str
    risk_evaluated_at: datetime
    evidence_json: str
    evidence_hash: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate scope, source clocks, qualified purpose, and nested hashes."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise SettlementPlanBindingValidationError("market audit account_id is invalid")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise SettlementPlanBindingValidationError("market audit user_id is invalid")
        _require_identity_token(self.idempotency_key, "idempotency_key")
        _require_sha256(self.request_payload_hash)
        _require_identity_token(self.security_id, "security_id")
        _require_identity_token(self.asset_code, "asset_code")
        if type(self.execution_price) is not Decimal or not self.execution_price.is_finite():
            raise SettlementPlanBindingValidationError("market audit execution price is invalid")
        if self.execution_price <= Decimal(0):
            raise SettlementPlanBindingValidationError("market audit execution price is invalid")
        for name in ("source_id", "source_version", "policy_id", "policy_version"):
            _require_identity_token(getattr(self, name), name)
        for name in (
            "source_hash",
            "policy_hash",
            "market_hash",
            "market_bundle_hash",
            "rule_hash",
            "calendar_hash",
            "risk_decision_hash",
        ):
            _require_sha256(getattr(self, name))
        observed = _normalize_identity_utc(self.source_observed_at, "source_observed_at")
        available = _normalize_identity_utc(self.source_available_at, "source_available_at")
        valid_until = _normalize_identity_utc(self.source_valid_until, "source_valid_until")
        evaluated_at = _normalize_identity_utc(self.risk_evaluated_at, "risk_evaluated_at")
        if not observed <= available <= evaluated_at < valid_until:
            raise SettlementPlanBindingValidationError("market audit source window is invalid")
        if type(self.evidence_json) is not str:
            raise SettlementPlanBindingValidationError("market audit evidence is invalid")
        try:
            evidence = json.loads(self.evidence_json)
        except (TypeError, ValueError) as error:
            raise SettlementPlanBindingValidationError(
                "market audit evidence is invalid"
            ) from error
        if type(evidence) is not dict or set(evidence) != {
            "schema",
            "purpose",
            "retained_source",
            "market_bundle",
            "risk_decision",
            "risk_evaluated_at",
            "locked_position",
            "qualification",
        }:
            raise SettlementPlanBindingValidationError("market audit evidence shape is invalid")
        if (
            evidence["schema"] != _LOCAL_STOP_LOSS_AUDIT_SCHEMA
            or evidence["purpose"] != "local_simulation_only"
            or evidence["risk_evaluated_at"] != _audit_datetime_text(evaluated_at)
        ):
            raise SettlementPlanBindingValidationError("market audit purpose or clock is invalid")
        retained_source = evidence["retained_source"]
        market_bundle = evidence["market_bundle"]
        risk_decision = evidence["risk_decision"]
        qualification = evidence["qualification"]
        if type(retained_source) is not dict or type(market_bundle) is not dict:
            raise SettlementPlanBindingValidationError("market audit source payload is invalid")
        if type(risk_decision) is not dict or type(qualification) is not dict:
            raise SettlementPlanBindingValidationError("market audit Risk payload is invalid")
        if (
            retained_source.get("security_id") != self.security_id
            or retained_source.get("policy_hash") != self.policy_hash
            or type(retained_source.get("capture")) is not dict
            or retained_source["capture"].get("body_sha256") != self.source_hash
        ):
            raise SettlementPlanBindingValidationError("market audit retained source differs")
        if (
            market_bundle.get("purpose") != "local_simulation_only"
            or market_bundle.get("content_hash") != self.market_bundle_hash
            or market_bundle.get("execution_rule_content_hash") != self.rule_hash
            or market_bundle.get("policy") is None
            or market_bundle.get("calendar") is None
            or market_bundle.get("market") is None
        ):
            raise SettlementPlanBindingValidationError("market audit bundle binding differs")
        policy = market_bundle["policy"]
        calendar = market_bundle["calendar"]
        market = market_bundle["market"]
        if (
            type(policy) is not dict
            or policy.get("policy_id") != self.policy_id
            or policy.get("policy_version") != self.policy_version
            or policy.get("content_hash") != self.policy_hash
            or type(calendar) is not dict
            or calendar.get("content_hash") != self.calendar_hash
            or type(market) is not dict
            or market.get("content_hash") != self.market_hash
        ):
            raise SettlementPlanBindingValidationError("market audit policy or market differs")
        if (
            risk_decision.get("status") != "ALLOWED"
            or risk_decision.get("order_id") != self.idempotency_key
            or risk_decision.get("market_evidence_content_hash")
            != self._market_v2_content_hash(market)
            or _audit_json_hash(risk_decision) != self.risk_decision_hash
        ):
            raise SettlementPlanBindingValidationError("market audit Risk decision differs")
        if (
            qualification.get("purpose") != "local_simulation_only"
            or qualification.get("must_not_use_for_decision") is not True
            or qualification.get("must_not_execute") is not True
            or qualification.get("execution_authority") is not False
        ):
            raise SettlementPlanBindingValidationError(
                "market audit lost its scoped-purpose restrictions"
            )
        if self.evidence_hash and self.evidence_hash != _audit_json_hash(evidence):
            raise SettlementPlanBindingValidationError("market audit evidence hash differs")
        object.__setattr__(self, "evidence_hash", _audit_json_hash(evidence))
        if self.content_hash and self.content_hash != _canonical_hash(self._content_payload()):
            raise SettlementPlanBindingValidationError("market audit content hash differs")
        object.__setattr__(self, "content_hash", _canonical_hash(self._content_payload()))

    @staticmethod
    def _market_evidence_hash(market_payload: dict[str, object]) -> str:
        """Validate and return the exact nested V1 market evidence hash."""

        evidence = market_payload.get("market_evidence_v1")
        if type(evidence) is not dict:
            raise SettlementPlanBindingValidationError("market audit V1 evidence is missing")
        digest = evidence.get("content_hash")
        if (
            type(digest) is not str
            or len(digest) != _SHA256_LENGTH
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise SettlementPlanBindingValidationError("market audit V1 hash is invalid")
        return digest

    @classmethod
    def _market_v2_content_hash(cls, market_payload: dict[str, object]) -> str:
        """Validate nested V1 evidence and return the hash Risk V2 actually binds."""

        cls._market_evidence_hash(market_payload)
        digest = market_payload.get("content_hash")
        if (
            type(digest) is not str
            or len(digest) != _SHA256_LENGTH
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise SettlementPlanBindingValidationError("market audit V2 hash is invalid")
        return digest

    def _content_payload(self) -> dict[str, object]:
        """Build the exact typed audit envelope without its digest."""

        return {
            "schema": _LOCAL_STOP_LOSS_AUDIT_SCHEMA,
            "purpose": "local_simulation_only",
            "account_id": self.account_id,
            "user_id": self.user_id,
            "idempotency_key": self.idempotency_key,
            "request_payload_hash": self.request_payload_hash,
            "security_id": self.security_id,
            "asset_code": self.asset_code,
            "side": "sell",
            "execution_price": str(self.execution_price),
            "source_id": self.source_id,
            "source_version": self.source_version,
            "source_hash": self.source_hash,
            "source_observed_at": _audit_datetime_text(self.source_observed_at),
            "source_available_at": _audit_datetime_text(self.source_available_at),
            "source_valid_until": _audit_datetime_text(self.source_valid_until),
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "market_hash": self.market_hash,
            "market_bundle_hash": self.market_bundle_hash,
            "rule_hash": self.rule_hash,
            "calendar_hash": self.calendar_hash,
            "risk_decision_hash": self.risk_decision_hash,
            "risk_evaluated_at": _audit_datetime_text(self.risk_evaluated_at),
            "evidence": json.loads(self.evidence_json),
            "evidence_hash": self.evidence_hash,
        }

    def to_payload(self) -> LocalSimulatedExecutionMarketAuditPayload:
        """Return fresh nested audit JSON with exact source and decision seals."""

        self.__post_init__()
        payload = self._content_payload()
        payload["content_hash"] = self.content_hash
        return cast(LocalSimulatedExecutionMarketAuditPayload, payload)

    @classmethod
    def from_payload(cls, payload: object) -> LocalSimulatedExecutionMarketAuditV1:
        """Strictly decode one exact V1 local-simulation market audit."""

        keys = frozenset(
            {
                "schema",
                "purpose",
                "account_id",
                "user_id",
                "idempotency_key",
                "request_payload_hash",
                "security_id",
                "asset_code",
                "side",
                "execution_price",
                "source_id",
                "source_version",
                "source_hash",
                "source_observed_at",
                "source_available_at",
                "source_valid_until",
                "policy_id",
                "policy_version",
                "policy_hash",
                "market_hash",
                "market_bundle_hash",
                "rule_hash",
                "calendar_hash",
                "risk_decision_hash",
                "risk_evaluated_at",
                "evidence",
                "evidence_hash",
                "content_hash",
            }
        )
        if type(payload) is not dict or frozenset(payload) != keys:
            raise SettlementPlanBindingValidationError("market audit payload shape is invalid")
        fields = payload
        text_fields = (
            "idempotency_key",
            "request_payload_hash",
            "security_id",
            "asset_code",
            "execution_price",
            "source_id",
            "source_version",
            "source_hash",
            "source_observed_at",
            "source_available_at",
            "source_valid_until",
            "policy_id",
            "policy_version",
            "policy_hash",
            "market_hash",
            "market_bundle_hash",
            "rule_hash",
            "calendar_hash",
            "risk_decision_hash",
            "risk_evaluated_at",
            "evidence_hash",
            "content_hash",
        )
        if (
            fields.get("schema") != _LOCAL_STOP_LOSS_AUDIT_SCHEMA
            or fields.get("purpose") != ("local_simulation_only")
            or fields.get("side") != "sell"
        ):
            raise SettlementPlanBindingValidationError("market audit header is invalid")
        if any(type(fields.get(name)) is not str for name in text_fields):
            raise SettlementPlanBindingValidationError("market audit text fields are invalid")
        account_id = fields.get("account_id")
        user_id = fields.get("user_id")
        if type(account_id) is not int or type(user_id) is not int:
            raise SettlementPlanBindingValidationError("market audit account scope is invalid")
        try:
            execution_price = Decimal(fields["execution_price"])
            evidence_json = _canonical_json_text(fields["evidence"])
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SettlementPlanBindingValidationError(
                "market audit payload values are invalid"
            ) from error
        return cls(
            account_id=account_id,
            user_id=user_id,
            idempotency_key=fields["idempotency_key"],
            request_payload_hash=fields["request_payload_hash"],
            security_id=fields["security_id"],
            asset_code=fields["asset_code"],
            execution_price=execution_price,
            source_id=fields["source_id"],
            source_version=fields["source_version"],
            source_hash=fields["source_hash"],
            source_observed_at=_parse_audit_datetime(
                fields["source_observed_at"], "source_observed_at"
            ),
            source_available_at=_parse_audit_datetime(
                fields["source_available_at"], "source_available_at"
            ),
            source_valid_until=_parse_audit_datetime(
                fields["source_valid_until"], "source_valid_until"
            ),
            policy_id=fields["policy_id"],
            policy_version=fields["policy_version"],
            policy_hash=fields["policy_hash"],
            market_hash=fields["market_hash"],
            market_bundle_hash=fields["market_bundle_hash"],
            rule_hash=fields["rule_hash"],
            calendar_hash=fields["calendar_hash"],
            risk_decision_hash=fields["risk_decision_hash"],
            risk_evaluated_at=_parse_audit_datetime(
                fields["risk_evaluated_at"], "risk_evaluated_at"
            ),
            evidence_json=evidence_json,
            evidence_hash=fields["evidence_hash"],
            content_hash=fields["content_hash"],
        )


def _require_sha256(value: object) -> str:
    """Require one bare lowercase SHA-256 digest for selector metadata."""

    if (
        type(value) is not str
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise IdentityEvidenceValidationError("CURRENT_REFERENCE_HASH_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class CurrentReferenceSelectionV1:
    """Bind one normal-simulation selection to exact ConfigCenter metadata."""

    purpose: str
    profile_id: str
    profile_key: str
    environment: str
    profile_version: int
    profile_content_hash: str
    runtime_snapshot_id: str
    runtime_snapshot_hash: str
    selector_content_hash: str
    profile_activated_at: datetime
    runtime_snapshot_generated_at: datetime
    selected_at: datetime
    max_local_reference_age_seconds: int

    def __post_init__(self) -> None:
        """Validate exact selector metadata and normalize its clocks to UTC."""

        if type(self.purpose) is not str or self.purpose != "normal_simulated_current_reference":
            raise IdentityEvidenceValidationError("CURRENT_REFERENCE_PURPOSE_UNSUPPORTED")
        for name in (
            "profile_id",
            "profile_key",
            "environment",
            "runtime_snapshot_id",
        ):
            _require_identity_token(getattr(self, name), name)
        if type(self.profile_version) is not int or self.profile_version <= 0:
            raise IdentityEvidenceValidationError("CURRENT_REFERENCE_VERSION_INVALID")
        if (
            type(self.max_local_reference_age_seconds) is not int
            or self.max_local_reference_age_seconds <= 0
        ):
            raise IdentityEvidenceValidationError("CURRENT_REFERENCE_MAX_AGE_INVALID")
        for name in (
            "profile_content_hash",
            "runtime_snapshot_hash",
            "selector_content_hash",
        ):
            _require_sha256(getattr(self, name))
        for name in (
            "profile_activated_at",
            "runtime_snapshot_generated_at",
            "selected_at",
        ):
            object.__setattr__(
                self,
                name,
                _normalize_identity_utc(getattr(self, name), name),
            )
        if not (
            self.profile_activated_at <= self.runtime_snapshot_generated_at <= self.selected_at
        ):
            raise IdentityEvidenceValidationError("CURRENT_REFERENCE_CLOCK_ORDER_INVALID")

    @property
    def content_hash(self) -> str:
        """Return the canonical bare SHA-256 of the exact selector payload."""

        return _canonical_hash(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return the exact versioned selector payload without secrets or defaults."""

        self.__post_init__()
        return {
            "schema": _SELECTION_SCHEMA,
            "purpose": self.purpose,
            "profile_id": self.profile_id,
            "profile_key": self.profile_key,
            "environment": self.environment,
            "profile_version": self.profile_version,
            "profile_content_hash": self.profile_content_hash,
            "runtime_snapshot_id": self.runtime_snapshot_id,
            "runtime_snapshot_hash": self.runtime_snapshot_hash,
            "selector_content_hash": self.selector_content_hash,
            "profile_activated_at": _identity_utc_text(self.profile_activated_at),
            "runtime_snapshot_generated_at": _identity_utc_text(self.runtime_snapshot_generated_at),
            "selected_at": _identity_utc_text(self.selected_at),
            "max_local_reference_age_seconds": self.max_local_reference_age_seconds,
        }

    @classmethod
    def from_payload(cls, payload: object) -> CurrentReferenceSelectionV1:
        """Strictly decode one exact current-reference selection receipt."""

        expected = frozenset(
            {
                "schema",
                "purpose",
                "profile_id",
                "profile_key",
                "environment",
                "profile_version",
                "profile_content_hash",
                "runtime_snapshot_id",
                "runtime_snapshot_hash",
                "selector_content_hash",
                "profile_activated_at",
                "runtime_snapshot_generated_at",
                "selected_at",
                "max_local_reference_age_seconds",
            }
        )
        fields = _identity_object(payload, expected)
        if type(fields["schema"]) is not str or fields["schema"] != _SELECTION_SCHEMA:
            raise IdentityEvidenceValidationError("CURRENT_REFERENCE_SCHEMA_UNSUPPORTED")
        purpose = fields["purpose"]
        if type(purpose) is not str:
            raise IdentityEvidenceValidationError("CURRENT_REFERENCE_PURPOSE_UNSUPPORTED")
        version = fields["profile_version"]
        max_age = fields["max_local_reference_age_seconds"]
        if type(version) is not int or type(max_age) is not int:
            raise IdentityEvidenceValidationError("CURRENT_REFERENCE_INTEGER_INVALID")
        return cls(
            purpose=purpose,
            profile_id=_require_identity_token(fields["profile_id"], "profile_id"),
            profile_key=_require_identity_token(fields["profile_key"], "profile_key"),
            environment=_require_identity_token(fields["environment"], "environment"),
            profile_version=version,
            profile_content_hash=_require_sha256(fields["profile_content_hash"]),
            runtime_snapshot_id=_require_identity_token(
                fields["runtime_snapshot_id"], "runtime_snapshot_id"
            ),
            runtime_snapshot_hash=_require_sha256(fields["runtime_snapshot_hash"]),
            selector_content_hash=_require_sha256(fields["selector_content_hash"]),
            profile_activated_at=_parse_identity_utc(fields["profile_activated_at"]),
            runtime_snapshot_generated_at=_parse_identity_utc(
                fields["runtime_snapshot_generated_at"]
            ),
            selected_at=_parse_identity_utc(fields["selected_at"]),
            max_local_reference_age_seconds=max_age,
        )


@dataclass(frozen=True, slots=True)
class ExecutionInstrumentIdentityEvidenceV2:
    """Bind unchanged V1 source facts to a selector and exact source occurrence."""

    source_evidence: ExecutionInstrumentIdentityEvidenceV1
    selection: CurrentReferenceSelectionV1
    source_occurrence_id: UUID
    reference_response_completed_at: datetime

    def __post_init__(self) -> None:
        """Validate nested receipts and derive only the bounded local age window."""

        if type(self.source_evidence) is not ExecutionInstrumentIdentityEvidenceV1:
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_TYPE_INVALID")
        if type(self.selection) is not CurrentReferenceSelectionV1:
            raise IdentityEvidenceValidationError("CURRENT_REFERENCE_SELECTION_TYPE_INVALID")
        self.source_evidence.__post_init__()
        self.selection.__post_init__()
        if type(self.source_occurrence_id) is not UUID:
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_UUID_INVALID")
        reference_at = _normalize_identity_utc(
            self.reference_response_completed_at,
            "reference_response_completed_at",
        )
        object.__setattr__(self, "reference_response_completed_at", reference_at)
        source = self.source_evidence
        if source.source_market is None:
            raise IdentityEvidenceValidationError("IDENTITY_SOURCE_MARKET_UNKNOWN")
        if reference_at > source.response_completed_at:
            raise IdentityEvidenceValidationError("IDENTITY_OCCURRENCE_AFTER_BATCH")
        if source.source_observed_at is not None and source.source_observed_at > reference_at:
            raise IdentityEvidenceValidationError("IDENTITY_SOURCE_CLOCK_ORDER_INVALID")
        if source.source_available_at is not None and source.source_available_at > reference_at:
            raise IdentityEvidenceValidationError("IDENTITY_SOURCE_CLOCK_ORDER_INVALID")
        if (
            source.source_observed_at is not None
            and source.source_available_at is not None
            and source.source_observed_at > source.source_available_at
        ):
            raise IdentityEvidenceValidationError("IDENTITY_SOURCE_CLOCK_ORDER_INVALID")

        window_start, window_end = self._local_window()
        if source.identity_valid_from != window_start or source.identity_valid_until != window_end:
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_VALIDITY_WINDOW_MISMATCH")
        known_times = (
            self.selection.profile_activated_at,
            self.selection.runtime_snapshot_generated_at,
            source.first_seen_at,
            source.snapshot_recorded_at,
            source.mapping_recorded_at,
            source.response_completed_at,
            reference_at,
            source.source_observed_at,
            source.source_available_at,
        )
        if any(value is not None and value > self.selection.selected_at for value in known_times):
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_NOT_KNOWN_AT_SELECTION")
        if not window_start <= self.selection.selected_at < window_end:
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_OUTSIDE_VALIDITY_WINDOW")

    def _local_window(self) -> tuple[datetime, datetime]:
        """Return the exact local start and occurrence-based half-open expiry."""

        source = self.source_evidence
        start = max(
            self.selection.profile_activated_at,
            source.snapshot_recorded_at,
            source.mapping_recorded_at,
        )
        try:
            end = self.reference_response_completed_at + timedelta(
                seconds=self.selection.max_local_reference_age_seconds
            )
        except OverflowError as error:
            raise IdentityEvidenceValidationError("IDENTITY_REFERENCE_AGE_OVERFLOW") from error
        if start >= end:
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_VALIDITY_WINDOW_INVALID")
        return start, end

    @property
    def security_id(self) -> str:
        """Return the internal security identifier from the exact V1 receipt."""

        return self.source_evidence.security_id

    @property
    def asset_code(self) -> str:
        """Return the caller-facing asset code from the exact V1 receipt."""

        return self.source_evidence.asset_code

    @property
    def source_exchange(self) -> str:
        """Return the mapped source exchange without changing the Rule market."""

        return self.source_evidence.source_exchange

    @property
    def rule_market(self) -> str:
        """Return the independent Rule market from the exact V1 receipt."""

        return self.source_evidence.rule_market

    @property
    def board(self) -> str:
        """Return the security board from the exact V1 receipt."""

        return self.source_evidence.board

    @property
    def content_hash(self) -> str:
        """Return the canonical bare SHA-256 of the exact V2 payload."""

        return _canonical_hash(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return the exact V2 envelope while preserving the original V1 payload."""

        self.__post_init__()
        return {
            "schema": _IDENTITY_V2_SCHEMA,
            "source_evidence": self.source_evidence.to_payload(),
            "selection": self.selection.to_payload(),
            "source_occurrence_id": str(self.source_occurrence_id),
            "reference_response_completed_at": _identity_utc_text(
                self.reference_response_completed_at
            ),
        }

    @classmethod
    def from_payload(cls, payload: object) -> ExecutionInstrumentIdentityEvidenceV2:
        """Strictly decode one exact V2 identity envelope and its nested receipts."""

        expected = frozenset(
            {
                "schema",
                "source_evidence",
                "selection",
                "source_occurrence_id",
                "reference_response_completed_at",
            }
        )
        fields = _identity_object(payload, expected)
        if type(fields["schema"]) is not str or fields["schema"] != _IDENTITY_V2_SCHEMA:
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_SCHEMA_UNSUPPORTED")
        return cls(
            source_evidence=ExecutionInstrumentIdentityEvidenceV1.from_payload(
                fields["source_evidence"]
            ),
            selection=CurrentReferenceSelectionV1.from_payload(fields["selection"]),
            source_occurrence_id=_parse_identity_uuid(fields["source_occurrence_id"]),
            reference_response_completed_at=_parse_identity_utc(
                fields["reference_response_completed_at"]
            ),
        )

    def validate_at(self, *, as_of: datetime) -> None:
        """Require the local selection and every known clock to be valid at cutoff."""

        self.__post_init__()
        cutoff = _normalize_identity_utc(as_of, "as_of")
        if cutoff < self.selection.selected_at:
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_NOT_KNOWN_AT_CUTOFF")
        source = self.source_evidence
        known_times = (
            self.selection.profile_activated_at,
            self.selection.runtime_snapshot_generated_at,
            source.first_seen_at,
            source.snapshot_recorded_at,
            source.mapping_recorded_at,
            source.response_completed_at,
            self.reference_response_completed_at,
            source.source_observed_at,
            source.source_available_at,
        )
        if any(value is not None and value > cutoff for value in known_times):
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_NOT_KNOWN_AT_CUTOFF")
        _, window_end = self._local_window()
        if cutoff >= window_end:
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_OUTSIDE_VALIDITY_WINDOW")

    def validate_for(self, *, intent: SimulatedTradeIntent, as_of: datetime) -> None:
        """Bind this current-reference receipt to one exact simulated intent."""

        if type(intent) is not SimulatedTradeIntent:
            raise IdentityEvidenceValidationError("IDENTITY_INTENT_INVALID")
        try:
            SimulatedTradeIntent.__post_init__(intent)
        except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
            raise IdentityEvidenceValidationError("IDENTITY_INTENT_INVALID") from error
        self.validate_at(as_of=as_of)
        if self.security_id != intent.security_id or self.asset_code != intent.asset_code:
            raise IdentityEvidenceValidationError("IDENTITY_INTENT_MISMATCH")
        if self.rule_market != intent.market:
            raise IdentityEvidenceValidationError("IDENTITY_RULE_MARKET_MISMATCH")
        if self.board != intent.board:
            raise IdentityEvidenceValidationError("IDENTITY_BOARD_MISMATCH")


@dataclass(frozen=True, slots=True)
class SettlementExecutionPlanV3(SettlementExecutionPlan):
    """Settlement plan using current-purpose V2 identity evidence."""

    identity_evidence: ExecutionInstrumentIdentityEvidenceV2

    @property
    def _expected_calendar_exchange(self) -> str:
        """Return the exchange bound by the exact current-reference receipt."""

        return self.identity_evidence.source_exchange

    def __post_init__(self) -> None:
        """Validate the unchanged settlement plan plus this V3 identity receipt."""

        if type(self.identity_evidence) is not ExecutionInstrumentIdentityEvidenceV2:
            raise IdentityEvidenceValidationError("IDENTITY_EVIDENCE_TYPE_INVALID")
        self.identity_evidence.__post_init__()
        if self.identity_evidence.selection.selected_at != self.pre_read_at:
            raise IdentityEvidenceValidationError("IDENTITY_SELECTION_CUTOFF_MISMATCH")
        SettlementExecutionPlan.__post_init__(self)
        self.identity_evidence.validate_for(intent=self.intent, as_of=self.pre_read_at)

    def validate_at(self, as_of: datetime) -> None:
        """Revalidate settlement and current-reference evidence at the locked clock."""

        SettlementExecutionPlan.validate_at(self, as_of)
        self.identity_evidence.validate_for(intent=self.intent, as_of=as_of)


@dataclass(frozen=True, slots=True)
class SimulatedSettlementPlanBindingV3:
    """Persist the unchanged common plan summary with its exact V2 identity receipt."""

    common_binding: SimulatedSettlementPlanBindingV1
    identity_evidence: ExecutionInstrumentIdentityEvidenceV2
    local_market_audit: LocalSimulatedExecutionMarketAuditV1 | None = None

    def __post_init__(self) -> None:
        """Validate nested receipts, exchange agreement, and both evidence cutoffs."""

        if type(self.common_binding) is not SimulatedSettlementPlanBindingV1:
            raise SettlementPlanBindingValidationError(
                "common_binding must be SimulatedSettlementPlanBindingV1"
            )
        if type(self.identity_evidence) is not ExecutionInstrumentIdentityEvidenceV2:
            raise SettlementPlanBindingValidationError(
                "identity_evidence must be ExecutionInstrumentIdentityEvidenceV2"
            )
        self.common_binding.__post_init__()
        self.identity_evidence.__post_init__()
        if self.identity_evidence.selection.selected_at != self.common_binding.pre_read_at:
            raise SettlementPlanBindingValidationError(
                "identity selection time differs from the bound plan pre-read cutoff"
            )
        if self.common_binding.calendar_snapshot.exchange != self.identity_evidence.source_exchange:
            raise SettlementPlanBindingValidationError(
                "identity source exchange differs from the bound calendar exchange"
            )
        self.identity_evidence.validate_at(as_of=self.common_binding.pre_read_at)
        self.identity_evidence.validate_at(as_of=self.common_binding.executed_at)
        audit = self.local_market_audit
        if audit is not None:
            if type(audit) is not LocalSimulatedExecutionMarketAuditV1:
                raise SettlementPlanBindingValidationError(
                    "local_market_audit must be LocalSimulatedExecutionMarketAuditV1"
                )
            audit.__post_init__()
            audit_binding = (
                audit.account_id,
                audit.user_id,
                audit.idempotency_key,
                audit.request_payload_hash,
                audit.security_id,
                audit.asset_code,
                audit.risk_evaluated_at,
            )
            plan_binding = (
                self.common_binding.account_id,
                self.common_binding.user_id,
                self.common_binding.idempotency_key,
                self.common_binding.request_payload_hash,
                self.identity_evidence.security_id,
                self.identity_evidence.asset_code,
                self.common_binding.executed_at,
            )
            if audit_binding != plan_binding:
                raise SettlementPlanBindingValidationError(
                    "local market audit differs from the exact V3 execution binding"
                )

    @property
    def content_hash(self) -> str:
        """Return the unprefixed SHA-256 over this exact V3 envelope."""

        return _canonical_hash(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return the exact V3 binding payload without embedding its storage hash."""

        self.__post_init__()
        payload: dict[str, object] = {
            "schema": _BINDING_V3_SCHEMA,
            "common_binding": self.common_binding.to_payload(),
            "identity_evidence": self.identity_evidence.to_payload(),
        }
        if self.local_market_audit is not None:
            payload["local_market_audit"] = self.local_market_audit.to_payload()
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> SimulatedSettlementPlanBindingV3:
        """Strictly decode one V3 envelope without weakening either nested codec."""

        if type(payload) is not dict or frozenset(payload) not in {
            frozenset({"schema", "common_binding", "identity_evidence"}),
            frozenset({"schema", "common_binding", "identity_evidence", "local_market_audit"}),
        }:
            raise SettlementPlanBindingValidationError("binding_v3 fields are invalid")
        fields = payload
        if type(fields["schema"]) is not str or fields["schema"] != _BINDING_V3_SCHEMA:
            raise SettlementPlanBindingValidationError("binding_v3 schema is unsupported")
        audit_value = fields.get("local_market_audit")
        audit = (
            None
            if "local_market_audit" not in fields
            else LocalSimulatedExecutionMarketAuditV1.from_payload(audit_value)
        )
        return cls(
            common_binding=SimulatedSettlementPlanBindingV1.from_payload(fields["common_binding"]),
            identity_evidence=ExecutionInstrumentIdentityEvidenceV2.from_payload(
                fields["identity_evidence"]
            ),
            local_market_audit=audit,
        )


def bind_settlement_execution_plan_v3(
    plan: SettlementExecutionPlanV3,
    *,
    executed_at: datetime,
    local_market_audit: LocalSimulatedExecutionMarketAuditV1 | None = None,
) -> SimulatedSettlementPlanBindingV3:
    """Seal one exact V3 plan using the established common V1 summary builder."""

    if type(plan) is not SettlementExecutionPlanV3:
        raise SettlementPlanBindingValidationError("plan must be SettlementExecutionPlanV3")
    try:
        common_binding = _build_settlement_plan_common_binding(plan, executed_at=executed_at)
        if (
            local_market_audit is not None
            and local_market_audit.execution_price != plan.intent.price
        ):
            raise SettlementPlanBindingValidationError(
                "local market audit price differs from the exact plan intent"
            )
        return SimulatedSettlementPlanBindingV3(
            common_binding=common_binding,
            identity_evidence=plan.identity_evidence,
            local_market_audit=local_market_audit,
        )
    except SettlementPlanBindingValidationError:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SettlementPlanBindingValidationError(
            "settlement V3 plan failed binding validation"
        ) from error


__all__: tuple[str, ...] = (
    "CurrentReferenceSelectionV1",
    "ExecutionInstrumentIdentityEvidenceV2",
    "LocalSimulatedExecutionMarketAuditV1",
    "SettlementExecutionPlanV3",
    "SimulatedSettlementPlanBindingV3",
    "bind_settlement_execution_plan_v3",
)
