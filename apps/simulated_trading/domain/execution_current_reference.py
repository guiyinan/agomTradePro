"""Current-purpose instrument identity receipts for simulated execution.

This module preserves the exact V1 source evidence while binding it to an
explicit local selector and one retained per-security source occurrence. The
local age window does not qualify upstream clocks, authorize a broker, or prove
historical point-in-time availability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
    _expect_object,
)
from .execution_settlement_uow import (
    SettlementExecutionPlan,
    SimulatedTradeIntent,
)

_SELECTION_SCHEMA = "simulated-current-reference-selection.v1"
_IDENTITY_V2_SCHEMA = "simulated-execution-instrument-identity.v2"
_BINDING_V3_SCHEMA = "simulated-settlement-plan-binding.v3"
_SHA256_LENGTH = 64


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

    @property
    def content_hash(self) -> str:
        """Return the unprefixed SHA-256 over this exact V3 envelope."""

        return _canonical_hash(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return the exact V3 binding payload without embedding its storage hash."""

        self.__post_init__()
        return {
            "schema": _BINDING_V3_SCHEMA,
            "common_binding": self.common_binding.to_payload(),
            "identity_evidence": self.identity_evidence.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: object) -> SimulatedSettlementPlanBindingV3:
        """Strictly decode one V3 envelope without weakening either nested codec."""

        fields = _expect_object(
            payload,
            expected_keys=frozenset({"schema", "common_binding", "identity_evidence"}),
            field_name="binding_v3",
        )
        if type(fields["schema"]) is not str or fields["schema"] != _BINDING_V3_SCHEMA:
            raise SettlementPlanBindingValidationError("binding_v3 schema is unsupported")
        return cls(
            common_binding=SimulatedSettlementPlanBindingV1.from_payload(fields["common_binding"]),
            identity_evidence=ExecutionInstrumentIdentityEvidenceV2.from_payload(
                fields["identity_evidence"]
            ),
        )


def bind_settlement_execution_plan_v3(
    plan: SettlementExecutionPlanV3,
    *,
    executed_at: datetime,
) -> SimulatedSettlementPlanBindingV3:
    """Seal one exact V3 plan using the established common V1 summary builder."""

    if type(plan) is not SettlementExecutionPlanV3:
        raise SettlementPlanBindingValidationError("plan must be SettlementExecutionPlanV3")
    try:
        common_binding = _build_settlement_plan_common_binding(plan, executed_at=executed_at)
        return SimulatedSettlementPlanBindingV3(
            common_binding=common_binding,
            identity_evidence=plan.identity_evidence,
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
    "SettlementExecutionPlanV3",
    "SimulatedSettlementPlanBindingV3",
    "bind_settlement_execution_plan_v3",
)
