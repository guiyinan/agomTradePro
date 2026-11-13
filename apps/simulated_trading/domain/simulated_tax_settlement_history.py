"""Map complete simulated V4 fills into explicitly modeled tax settlement days.

The values here are structural Domain evidence only. A trusted adapter must
authenticate every retained fill against its immutable source event, read the
current Config Center rule and published calendar, and independently qualify
the record-date entitlement before calling the builder. Modeled dates never
prove real custody or legal settlement.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal, NoReturn
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
    TaxLotOrigin,
    _require_account_id,
    _require_date,
    _require_digest,
    _require_token,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    CorporateActionOwnershipEvidence,
    OwnershipAnchorKind,
    OwnershipFillFact,
    OwnershipOpeningAnchor,
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionKind
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    QualifiedTaxSettlementHistory,
    RecordDateTaxEntitlementEvidence,
    RecordDateTaxEntitlementRuleKind,
    TaxSettlementDayEvidence,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
)
from apps.simulated_trading.domain.simulated_tax_date_convention import (
    SimulatedDividendTaxDateConvention,
    SimulatedDividendTaxDateEvidence,
    derive_simulated_dividend_tax_date,
)

_ZERO = Decimal("0.000000")
_DATE_RULE_DEFINITION = "config_center.simulated_trading.dividend_tax_date_conventions"
_FAILURE = "DEFERRED_DIVIDEND_TAX_SIMULATED_HISTORY_INVALID"


def _reject(message: str) -> NoReturn:
    """Raise a stable error for incomplete modeled settlement history."""

    raise DeferredDividendTaxValidationError(message, _FAILURE)


def _aware(value: object, field: str) -> datetime:
    """Require an aware instant representable as UTC."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _reject(f"{field} must be an exact aware datetime")
    try:
        value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise DeferredDividendTaxValidationError(
            f"{field} is outside the UTC range", _FAILURE
        ) from error
    return value


def _sha(payload: dict[str, object]) -> str:
    """Hash one canonical payload without floating-point values."""

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as error:
        raise DeferredDividendTaxValidationError(
            "modeled history is not canonical", _FAILURE
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _instant(value: datetime) -> str:
    """Preserve the original timezone representation in observation manifests."""

    return _aware(value, "observation clock").isoformat(timespec="microseconds")


def _share_text(value: Decimal, field: str) -> str:
    """Render an exactly supported six-place share value independent of context."""

    if type(value) is not Decimal or not value.is_finite():
        _reject(f"{field} must be a finite exact Decimal share amount")
    try:
        with localcontext() as context:
            context.prec = 80
            normalized = value.quantize(_ZERO)
    except InvalidOperation as error:
        raise DeferredDividendTaxValidationError(
            f"{field} exceeds the supported share precision", _FAILURE
        ) from error
    if normalized != value:
        _reject(f"{field} exceeds the supported six-place share precision")
    return format(normalized, "f")


@dataclass(frozen=True, slots=True)
class SimulatedTaxDateRuleRuntimeProvenance:
    """Active Config Center profile/snapshot clocks for an explicit simulation rule."""

    convention_sha256: str
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
        """Validate immutable runtime identities and knowledge ordering."""

        _require_digest(self.convention_sha256, "convention_sha256")
        if self.definition_key != _DATE_RULE_DEFINITION:
            _reject("runtime evidence does not name the explicit simulation date rule")
        for name in ("environment", "profile_id", "profile_key", "snapshot_id"):
            _require_token(getattr(self, name), name, 128)
        for name in ("profile_content_hash", "snapshot_hash"):
            _require_digest(getattr(self, name), name)
        if type(self.profile_version) is not int or self.profile_version <= 0:
            _reject("runtime profile version must be a positive exact integer")
        cutoff = _aware(self.as_of, "runtime as_of")
        created = _aware(self.created_at, "runtime created_at")
        known = _aware(self.known_at, "runtime known_at")
        activated = _aware(self.activated_at, "runtime activated_at")
        snapshot = _aware(self.snapshot_generated_at, "runtime snapshot_generated_at")
        effective = _aware(self.effective_at, "runtime effective_at")
        if (
            known != created
            or effective != activated
            or not created <= activated <= snapshot <= cutoff
        ):
            _reject("runtime profile and snapshot clocks are inconsistent or not current")


def _history_identity(
    history: QualifiedTaxSettlementHistory,
) -> str:
    """Hash stable exact scope/rule/calendar/source identity from validated history."""

    if type(history) is not QualifiedTaxSettlementHistory:
        _reject("history identity requires exact qualified tax settlement history")
    history.__post_init__()
    return _sha(
        {
            "schema": "simulated-tax-settlement-history-identity.v1",
            "scope": [
                history.account_id,
                history.owner_user_id,
                history.security_id,
                history.asset_code,
            ],
            "target": [history.record_date.isoformat(), history.complete_through.isoformat()],
            "date_rule_sha256": history.settlement_date_rule_sha256,
            "calendar_sha256": history.settlement_calendar_sha256,
            "source_revision_sha256": history.source_revision_sha256,
        }
    )


@dataclass(frozen=True, slots=True)
class SimulatedTaxSettlementFillSource:
    """A V4 ownership fill and the exact source identity/clocks needed for date mapping.

    This value does not authenticate the source event. The trusted adapter must
    re-read the exact source locator and compare the entire returned event with
    the event decoded from the immutable V4 receipt before constructing it.
    """

    ownership_fill: OwnershipFillFact
    source_namespace: str
    source_version: str
    source_event_id: str
    event_payload_sha256: str
    source_snapshot_id: str
    source_snapshot_sha256: str
    order_idempotency_key: str
    observation_basis: Literal["legacy_source_observed", "daily_interval_end"]
    source_observed_at: datetime | None
    source_available_at: datetime | None
    local_known_at: datetime | None
    interval_end_at: datetime | None
    source_recorded_at: datetime
    trade_observed_at: datetime

    def __post_init__(self) -> None:
        """Validate exact source references and select an explicit observed clock."""

        if type(self.ownership_fill) is not OwnershipFillFact:
            _reject("simulated tax fill requires the exact V4 ownership fact")
        self.ownership_fill.__post_init__()
        for name in (
            "source_namespace",
            "source_version",
            "source_event_id",
            "source_snapshot_id",
            "order_idempotency_key",
        ):
            _require_token(getattr(self, name), name, 128)
        for name in ("event_payload_sha256", "source_snapshot_sha256"):
            _require_digest(getattr(self, name), name)
        if type(self.observation_basis) is not str or self.observation_basis not in {
            "legacy_source_observed",
            "daily_interval_end",
        }:
            _reject("simulated fill observation basis is unknown")
        for name in (
            "source_observed_at",
            "source_available_at",
            "local_known_at",
            "interval_end_at",
        ):
            value = getattr(self, name)
            if value is not None:
                _aware(value, name)
        _aware(self.source_recorded_at, "source_recorded_at")
        _aware(self.trade_observed_at, "trade_observed_at")
        expected_observed = (
            self.source_observed_at
            if self.observation_basis == "legacy_source_observed"
            else self.local_known_at
        )
        if (
            expected_observed is None
            or self.trade_observed_at != expected_observed
            or self.source_recorded_at < self.ownership_fill.occurred_at
            or self.source_recorded_at < self.trade_observed_at
            or (
                self.observation_basis == "daily_interval_end"
                and self.interval_end_at != self.ownership_fill.occurred_at
            )
        ):
            _reject("simulated fill lacks its exact original observed clock")


@dataclass(frozen=True, slots=True)
class SimulatedTaxSettlementFillObservation:
    """Source/receipt identity and date-rule observation for one tax-history fill."""

    trade_id: int
    reservation_id: int
    fill_sequence: int
    quantity: Decimal
    observation_basis: Literal["legacy_source_observed", "daily_interval_end"]
    receipt_sha256: str
    source_namespace: str
    source_version: str
    source_event_id: str
    event_payload_sha256: str
    source_snapshot_id: str
    source_snapshot_sha256: str
    order_idempotency_key: str
    source_recorded_at: datetime
    source_observed_at: datetime | None
    source_available_at: datetime | None
    local_known_at: datetime | None
    interval_end_at: datetime | None
    date_evidence: SimulatedDividendTaxDateEvidence

    def __post_init__(self) -> None:
        """Validate the identity cross-links to the derived date observation."""

        if (
            type(self.trade_id) is not int
            or self.trade_id <= 0
            or type(self.reservation_id) is not int
            or self.reservation_id <= 0
            or type(self.fill_sequence) is not int
            or self.fill_sequence <= 0
        ):
            _reject("simulated tax fill observation identity is invalid")
        _share_text(self.quantity, "fill_observation.quantity")
        if type(self.observation_basis) is not str or self.observation_basis not in {
            "legacy_source_observed",
            "daily_interval_end",
        }:
            _reject("simulated tax fill observation basis is unknown")
        _require_digest(self.receipt_sha256, "receipt_sha256")
        _require_token(self.source_namespace, "source_namespace", 128)
        _require_token(self.source_version, "source_version", 128)
        _require_token(self.source_event_id, "source_event_id", 128)
        _require_digest(self.event_payload_sha256, "event_payload_sha256")
        _require_token(self.source_snapshot_id, "source_snapshot_id", 128)
        _require_digest(self.source_snapshot_sha256, "source_snapshot_sha256")
        _require_token(self.order_idempotency_key, "order_idempotency_key", 128)
        _aware(self.source_recorded_at, "source_recorded_at")
        for name in (
            "source_observed_at",
            "source_available_at",
            "local_known_at",
            "interval_end_at",
        ):
            value = getattr(self, name)
            if value is not None:
                _aware(value, name)
        if type(self.date_evidence) is not SimulatedDividendTaxDateEvidence:
            _reject("simulated tax fill observation requires the exact modeled date evidence")
        self.date_evidence.__post_init__()
        if (
            self.date_evidence.trade_id != self.source_event_id
            or self.date_evidence.trade_payload_sha256 != self.event_payload_sha256
            or self.source_recorded_at > self.date_evidence.read_at
            or self.date_evidence.trade_observed_at
            != (
                self.source_observed_at
                if self.observation_basis == "legacy_source_observed"
                else self.local_known_at
            )
            or (
                self.observation_basis == "daily_interval_end"
                and self.interval_end_at != self.date_evidence.trade_occurred_at
            )
        ):
            _reject("modeled tax date evidence differs from its exact source fill")

    def to_payload(self) -> dict[str, object]:
        """Return the complete fill source and date observation for retention."""

        self.__post_init__()
        return {
            "trade_id": self.trade_id,
            "reservation_id": self.reservation_id,
            "fill_sequence": self.fill_sequence,
            "quantity": _share_text(self.quantity, "fill_observation.quantity"),
            "observation_basis": self.observation_basis,
            "receipt_sha256": self.receipt_sha256,
            "source_namespace": self.source_namespace,
            "source_version": self.source_version,
            "source_event_id": self.source_event_id,
            "event_payload_sha256": self.event_payload_sha256,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "order_idempotency_key": self.order_idempotency_key,
            "source_recorded_at": _instant(self.source_recorded_at),
            "source_observed_at": (
                _instant(self.source_observed_at) if self.source_observed_at is not None else None
            ),
            "source_available_at": (
                _instant(self.source_available_at) if self.source_available_at is not None else None
            ),
            "local_known_at": _instant(self.local_known_at) if self.local_known_at else None,
            "interval_end_at": _instant(self.interval_end_at) if self.interval_end_at else None,
            "date_evidence": {
                "semantic_sha256": self.date_evidence.semantic_sha256,
                "observation_sha256": self.date_evidence.observation_sha256,
                "modeled_tax_date": self.date_evidence.modeled_tax_date.isoformat(),
                "trade_session": self.date_evidence.trade_session.isoformat(),
                "trade_occurred_at": _instant(self.date_evidence.trade_occurred_at),
                "trade_observed_at": _instant(self.date_evidence.trade_observed_at),
                "convention_known_at": _instant(self.date_evidence.convention_known_at),
                "convention_valid_from": _instant(self.date_evidence.convention_valid_from),
                "convention_valid_until": _instant(self.date_evidence.convention_valid_until),
                "read_at": _instant(self.date_evidence.read_at),
                "calendar_evidence_sha256": self.date_evidence.calendar_evidence_sha256,
            },
        }


@dataclass(frozen=True, slots=True)
class SimulatedTaxSettlementHistoryObservation:
    """Capture Config Center, current calendar, and per-fill date observations separately."""

    date_rule: SimulatedTaxDateRuleRuntimeProvenance
    history_identity_sha256: str
    convention_valid_from: datetime
    convention_valid_until: datetime
    calendar_evidence_sha256: str
    calendar_snapshot_id: str
    calendar_content_sha256: str
    calendar_record_digest: str
    calendar_first_seen_at: datetime
    calendar_recorded_at: datetime
    calendar_response_completed_at: datetime
    calendar_publication_id: str
    calendar_publication_hash: str
    calendar_published_at: datetime
    calendar_publication_recorded_at: datetime
    calendar_reference_valid_from: datetime
    calendar_reference_valid_until: datetime
    calendar_timezone_name: str
    read_at: datetime
    date_observations: tuple[SimulatedTaxSettlementFillObservation, ...]

    def __post_init__(self) -> None:
        """Validate current calendar identity and each fill's original clocks."""

        if type(self.date_rule) is not SimulatedTaxDateRuleRuntimeProvenance:
            _reject("date-rule runtime observation is incomplete")
        self.date_rule.__post_init__()
        _require_digest(self.history_identity_sha256, "history_identity_sha256")
        _require_digest(self.calendar_evidence_sha256, "calendar_evidence_sha256")
        _require_digest(self.calendar_publication_hash, "calendar_publication_hash")
        for name in ("calendar_content_sha256", "calendar_record_digest"):
            value = getattr(self, name)
            if (
                type(value) is not str
                or not value.startswith("sha256:")
                or len(value) != 71
                or any(character not in "0123456789abcdef" for character in value[7:])
            ):
                _reject(f"{name} must be a prefixed lowercase SHA-256 digest")
        for name in ("calendar_snapshot_id", "calendar_publication_id", "calendar_timezone_name"):
            _require_token(getattr(self, name), name, 128)
        for name in (
            "calendar_first_seen_at",
            "calendar_recorded_at",
            "calendar_response_completed_at",
            "calendar_published_at",
            "calendar_publication_recorded_at",
            "calendar_reference_valid_from",
            "calendar_reference_valid_until",
            "convention_valid_from",
            "convention_valid_until",
            "read_at",
        ):
            _aware(getattr(self, name), name)
        observation_clocks = (
            self.calendar_first_seen_at,
            self.calendar_recorded_at,
            self.calendar_response_completed_at,
            self.calendar_published_at,
            self.calendar_publication_recorded_at,
        )
        if (
            self.calendar_response_completed_at != self.calendar_first_seen_at
            or self.calendar_recorded_at < self.calendar_first_seen_at
            or self.calendar_publication_recorded_at < self.calendar_published_at
            or self.calendar_reference_valid_from >= self.calendar_reference_valid_until
            or not self.calendar_reference_valid_from
            <= self.read_at
            < self.calendar_reference_valid_until
            or any(clock > self.read_at for clock in observation_clocks)
            or self.convention_valid_from >= self.convention_valid_until
            or not self.convention_valid_from <= self.read_at < self.convention_valid_until
            or self.read_at != self.date_rule.as_of
        ):
            _reject("calendar observation clocks or current runtime cutoff are inconsistent")
        if type(self.date_observations) is not tuple or any(
            type(item) is not SimulatedTaxSettlementFillObservation
            for item in self.date_observations
        ):
            _reject("per-fill date observations must be an exact typed tuple")
        for item in self.date_observations:
            item.__post_init__()
            evidence = item.date_evidence
            if (
                evidence.calendar_evidence_sha256 != self.calendar_evidence_sha256
                or evidence.convention_sha256 != self.date_rule.convention_sha256
                or evidence.convention_known_at != self.date_rule.known_at
                or evidence.convention_valid_from != self.convention_valid_from
                or evidence.convention_valid_until != self.convention_valid_until
                or evidence.read_at != self.read_at
            ):
                _reject("fill date observation differs from its current rule or calendar envelope")

    def verify_for(self, history: QualifiedTaxSettlementHistory) -> None:
        """Require the current runtime observation to describe this exact history prefix."""

        self.__post_init__()
        if (
            self.history_identity_sha256 != _history_identity(history)
            or self.date_rule.convention_sha256 != history.settlement_date_rule_sha256
        ):
            _reject("simulated tax observation belongs to a different history prefix")

    def to_payload(self) -> dict[str, object]:
        """Return the independently retained observation envelope."""

        self.__post_init__()
        return {
            "schema": "simulated-tax-settlement-history-observation.v1",
            "history_identity_sha256": self.history_identity_sha256,
            "date_rule": {
                "convention_sha256": self.date_rule.convention_sha256,
                "environment": self.date_rule.environment,
                "definition_key": self.date_rule.definition_key,
                "profile_id": self.date_rule.profile_id,
                "profile_key": self.date_rule.profile_key,
                "profile_version": self.date_rule.profile_version,
                "profile_content_hash": self.date_rule.profile_content_hash,
                "snapshot_id": self.date_rule.snapshot_id,
                "snapshot_hash": self.date_rule.snapshot_hash,
                "created_at": _instant(self.date_rule.created_at),
                "known_at": _instant(self.date_rule.known_at),
                "activated_at": _instant(self.date_rule.activated_at),
                "snapshot_generated_at": _instant(self.date_rule.snapshot_generated_at),
                "effective_at": _instant(self.date_rule.effective_at),
                "as_of": _instant(self.date_rule.as_of),
                "convention_valid_from": _instant(self.convention_valid_from),
                "convention_valid_until": _instant(self.convention_valid_until),
            },
            "current_calendar": {
                "evidence_sha256": self.calendar_evidence_sha256,
                "snapshot_id": self.calendar_snapshot_id,
                "content_sha256": self.calendar_content_sha256,
                "record_digest": self.calendar_record_digest,
                "first_seen_at": _instant(self.calendar_first_seen_at),
                "recorded_at": _instant(self.calendar_recorded_at),
                "response_completed_at": _instant(self.calendar_response_completed_at),
                "publication_id": self.calendar_publication_id,
                "publication_hash": self.calendar_publication_hash,
                "published_at": _instant(self.calendar_published_at),
                "publication_recorded_at": _instant(self.calendar_publication_recorded_at),
                "reference_valid_from": _instant(self.calendar_reference_valid_from),
                "reference_valid_until": _instant(self.calendar_reference_valid_until),
                "timezone_name": self.calendar_timezone_name,
            },
            "read_at": _instant(self.read_at),
            "fills": [item.to_payload() for item in self.date_observations],
            "must_not_use_as_real_custody_proof": True,
        }

    @property
    def observation_sha256(self) -> str:
        """Return the digest of the exact full read observation envelope."""

        return _sha(self.to_payload())


@dataclass(frozen=True, slots=True)
class SimulatedTaxSettlementHistoryRequest:
    """All inputs required to build one complete, explicitly simulated history prefix."""

    account_kind: str
    physical_account_id: int
    canonical_account_id: str
    owner_user_id: int
    security_id: str
    asset_code: str
    record_date: date
    complete_through: date
    record_date_ownership_proof: RecordDateOwnershipProof
    opening_anchor: OwnershipOpeningAnchor
    source_fills: tuple[SimulatedTaxSettlementFillSource, ...]
    corporate_action_evidence: tuple[CorporateActionOwnershipEvidence, ...]
    record_date_entitlement: RecordDateTaxEntitlementEvidence
    convention: SimulatedDividendTaxDateConvention
    date_rule_provenance: SimulatedTaxDateRuleRuntimeProvenance
    calendar: ExecutionCalendarEvidence
    as_of: datetime

    def __post_init__(self) -> None:
        """Reject mixed physical/logical scope before mapping any source dates."""

        _require_account_id(self.physical_account_id, "physical_account_id")
        _require_account_id(self.owner_user_id, "owner_user_id")
        _require_token(self.canonical_account_id, "canonical_account_id", 128)
        _require_token(self.security_id, "security_id", 96)
        _require_token(self.asset_code, "asset_code", 96)
        if self.account_kind != "simulated":
            _reject("the modeled tax-date convention is restricted to simulated accounts")
        _require_date(self.record_date, "record_date")
        _require_date(self.complete_through, "complete_through")
        if self.complete_through <= self.record_date:
            _reject("settlement history must extend beyond the record date")
        _aware(self.as_of, "as_of")
        if type(self.record_date_ownership_proof) is not RecordDateOwnershipProof:
            _reject("the exact record-date ownership proof is required")
        if type(self.opening_anchor) is not OwnershipOpeningAnchor:
            _reject("the immutable zero-origin anchor is required")
        if type(self.record_date_entitlement) is not RecordDateTaxEntitlementEvidence:
            _reject("an explicitly qualified record-date entitlement rule is required")
        if type(self.convention) is not SimulatedDividendTaxDateConvention:
            _reject("the exact configured simulated date convention is required")
        if type(self.date_rule_provenance) is not SimulatedTaxDateRuleRuntimeProvenance:
            _reject("the exact active Config Center rule provenance is required")
        if type(self.calendar) is not ExecutionCalendarEvidence:
            _reject("the exact current published exchange calendar is required")
        if type(self.source_fills) is not tuple or any(
            type(item) is not SimulatedTaxSettlementFillSource for item in self.source_fills
        ):
            _reject("simulated V4 source fills must be an exact typed tuple")
        if type(self.corporate_action_evidence) is not tuple or any(
            type(item) is not CorporateActionOwnershipEvidence
            for item in self.corporate_action_evidence
        ):
            _reject("account action history must be an exact typed tuple")
        proof = self.record_date_ownership_proof
        anchor = self.opening_anchor
        if (
            proof.account_id != self.physical_account_id
            or proof.owner_user_id != self.owner_user_id
            or proof.security_id != self.security_id
            or proof.asset_code != self.asset_code
            or proof.record_date != self.record_date
            or proof.ownership_snapshot_as_of_date != self.record_date
            or anchor.account_id != self.physical_account_id
            or anchor.owner_user_id != self.owner_user_id
            or anchor.anchor_kind is not OwnershipAnchorKind.ZERO_ORIGIN
            or anchor.quantity != _ZERO
        ):
            _reject("ownership proof or zero-origin anchor differs from requested scope")
        convention = self.convention
        convention.__post_init__()
        if (
            convention.physical_account_id != self.physical_account_id
            or convention.canonical_account_id != self.canonical_account_id
            or convention.owner_user_id != self.owner_user_id
            or convention.exchange != proof.exchange
        ):
            _reject("active simulated date convention differs from account or exchange scope")
        provenance = self.date_rule_provenance
        provenance.__post_init__()
        if (
            provenance.convention_sha256 != convention.semantic_sha256
            or provenance.as_of != self.as_of
            or provenance.known_at != convention.known_at
        ):
            _reject("Config Center runtime observation differs from the exact date rule")
        self.record_date_entitlement.__post_init__()
        if (
            self.record_date_entitlement.kind
            is not RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS
            or self.record_date_entitlement.qualified_total_quantity != proof.eligible_quantity
        ):
            _reject("all-covered entitlement must equal the independent ownership proof")


@dataclass(frozen=True, slots=True)
class SimulatedTaxSettlementHistoryBuild:
    """Stable settlement history plus a separately hashed observation envelope."""

    history: QualifiedTaxSettlementHistory
    observation: SimulatedTaxSettlementHistoryObservation

    def __post_init__(self) -> None:
        """Revalidate both independently retained outputs."""

        if type(self.history) is not QualifiedTaxSettlementHistory:
            _reject("history build must contain the exact tax settlement history")
        if type(self.observation) is not SimulatedTaxSettlementHistoryObservation:
            _reject("history build must contain the exact observation envelope")
        self.history.__post_init__()
        self.observation.verify_for(self.history)


def build_simulated_tax_settlement_history(
    request: SimulatedTaxSettlementHistoryRequest,
) -> SimulatedTaxSettlementHistoryBuild:
    """Derive a full modeled-day prefix from authenticated simulated fills.

    The date convention's explicit open-session offset is the only mapping
    applied. The function never reads a sellability date, receipt release date,
    or UTC date as a tax settlement date. Input hashes validate consistency;
    source qualification and currentness remain the trusted adapter's job.
    """

    if type(request) is not SimulatedTaxSettlementHistoryRequest:
        _reject("a complete simulated tax-history request is required")
    request.__post_init__()
    proof = request.record_date_ownership_proof
    anchor = request.opening_anchor
    calendar = request.calendar
    try:
        calendar.validate_for(request.as_of)
        publication = calendar.publication
        if publication is None:
            _reject("a formal current calendar publication is required")
        if (
            calendar.snapshot.exchange != request.convention.exchange
            or publication.timezone_name != proof.exchange_timezone_name
        ):
            _reject("current calendar exchange or timezone differs from the ownership proof")
        exchange_timezone = ZoneInfo(publication.timezone_name)
        if request.complete_through >= request.as_of.astimezone(exchange_timezone).date():
            _reject("completion day has not ended at the history cutoff")
        anchor_date = anchor.effective_at.astimezone(exchange_timezone).date()
        if (
            calendar.snapshot.coverage_start > anchor_date
            or calendar.snapshot.coverage_end < request.complete_through
        ):
            _reject("current calendar does not cover the complete zero-origin prefix")
    except (
        AttributeError,
        CalendarEvidenceValidationError,
        OverflowError,
        ValueError,
        ZoneInfoNotFoundError,
    ) as error:
        raise DeferredDividendTaxValidationError(
            "current published calendar failed complete-prefix validation", _FAILURE
        ) from error

    if (
        anchor_date >= request.record_date
        or anchor.observed_at > proof.ownership_snapshot_observed_at
    ):
        _reject("the exact zero-origin anchor is not valid for the ownership cutoff")
    if (
        proof.record_date_end_exclusive > request.as_of
        or proof.ownership_snapshot_observed_at > request.as_of
    ):
        _reject("record-date ownership proof was not known at the history cutoff")
    open_sessions = tuple(
        row.calendar_date
        for row in calendar.snapshot.days
        if row.is_open and anchor_date <= row.calendar_date <= request.complete_through
    )
    if request.record_date not in open_sessions or request.complete_through not in open_sessions:
        _reject("record and completion dates must be explicitly covered open sessions")

    action_evidence = request.corporate_action_evidence
    for action in action_evidence:
        action.__post_init__()
        if (
            action.account_id != request.physical_account_id
            or action.owner_user_id != request.owner_user_id
            or action.security_id != request.security_id
            or action.asset_code != request.asset_code
        ):
            _reject("corporate-action history crosses the account or instrument scope")
        if action.recorded_at > request.as_of or action.stage_date > request.complete_through:
            continue
        if (
            action.action_kind is not CorporateActionKind.CASH_DIVIDEND
            or action.share_delta != _ZERO
            or action.share_receivable_delta != _ZERO
        ):
            _reject("share distributions, rights, and nontrade position changes are unsupported")

    source_fills = tuple(
        sorted(
            request.source_fills,
            key=lambda item: (
                item.ownership_fill.occurred_at.astimezone(UTC),
                item.ownership_fill.reservation_id,
                item.ownership_fill.fill_sequence,
                item.ownership_fill.trade_id,
            ),
        )
    )
    seen_trade_keys: set[tuple[int, int, int]] = set()
    seen_receipts: set[str] = set()
    seen_source_events: set[tuple[str, str]] = set()
    mapped: list[tuple[SimulatedTaxSettlementFillSource, SimulatedDividendTaxDateEvidence]] = []
    for source in source_fills:
        source.__post_init__()
        fill = source.ownership_fill
        if (
            fill.account_id != request.physical_account_id
            or fill.owner_user_id != request.owner_user_id
            or fill.security_id != request.security_id
            or fill.asset_code != request.asset_code
            or fill.binding_version != 4
        ):
            _reject("V4 fill source crosses owner/account/instrument or binding scope")
        key = (fill.reservation_id, fill.fill_sequence, fill.trade_id)
        source_key = (source.source_namespace, source.source_event_id)
        if (
            key in seen_trade_keys
            or fill.receipt_sha256 in seen_receipts
            or source_key in seen_source_events
        ):
            _reject("simulated tax history contains a duplicate source fill")
        seen_trade_keys.add(key)
        seen_receipts.add(fill.receipt_sha256)
        seen_source_events.add(source_key)
        if (
            fill.occurred_at > request.as_of
            or fill.recorded_at > request.as_of
            or source.source_recorded_at > request.as_of
            or source.trade_observed_at > request.as_of
        ):
            _reject("V4 fill source was not known at the requested cutoff")
        if fill.occurred_at <= anchor.effective_at:
            _reject("V4 fill predates the zero-origin account anchor")
        try:
            fill_session = fill.occurred_at.astimezone(exchange_timezone).date()
        except (OverflowError, ValueError) as error:
            raise DeferredDividendTaxValidationError(
                "V4 fill time is outside calendar range", _FAILURE
            ) from error
        if fill.execution_date != fill_session:
            _reject("ownership replay execution date differs from the original exchange session")
        if fill_session > request.complete_through:
            continue
        date_evidence = derive_simulated_dividend_tax_date(
            convention=request.convention,
            calendar=calendar,
            account_kind=request.account_kind,
            physical_account_id=request.physical_account_id,
            canonical_account_id=request.canonical_account_id,
            owner_user_id=request.owner_user_id,
            trade_id=source.source_event_id,
            trade_payload_sha256=source.event_payload_sha256,
            side=fill.side.value,
            trade_occurred_at=fill.occurred_at,
            trade_observed_at=source.trade_observed_at,
            as_of=request.as_of,
        )
        if date_evidence.modeled_tax_date <= request.complete_through:
            mapped.append((source, date_evidence))

    used_dates = tuple(item.modeled_tax_date for _, item in mapped)
    if any(day < anchor_date for day in used_dates):
        _reject("modeled tax date predates the verified zero-origin anchor")
    settlement_days, date_observations, source_revision_sha256 = _build_days(
        request=request,
        open_sessions=open_sessions,
        mapped=tuple(mapped),
    )
    rule_id = f"{request.convention.convention_id}:{request.convention.version}"
    calendar_semantic_sha256 = _sha(
        {
            "schema": "simulated-tax-calendar-semantics.v1",
            "exchange": request.convention.exchange,
            "timezone_name": publication.timezone_name,
            "coverage_start": anchor_date.isoformat(),
            "complete_through": request.complete_through.isoformat(),
            "days": [
                row.to_payload()
                for row in calendar.snapshot.days
                if anchor_date <= row.calendar_date <= request.complete_through
            ],
        }
    )
    calendar_semantic_id = f"simulated-calendar-semantics.v1:{calendar_semantic_sha256}"
    history = QualifiedTaxSettlementHistory(
        account_id=request.physical_account_id,
        owner_user_id=request.owner_user_id,
        security_id=request.security_id,
        asset_code=request.asset_code,
        record_date=request.record_date,
        complete_through=request.complete_through,
        record_date_ownership_proof=proof,
        opening_anchor=anchor,
        settlement_date_rule_id=rule_id,
        settlement_date_rule_sha256=request.convention.semantic_sha256,
        settlement_calendar_id=calendar_semantic_id,
        settlement_calendar_sha256=calendar_semantic_sha256,
        source_revision_id=f"simulated-v4-tax-history.v1:{source_revision_sha256}",
        source_revision_sha256=source_revision_sha256,
        covered_session_dates=open_sessions,
        settlement_days=settlement_days,
        record_date_entitlement=request.record_date_entitlement,
    )
    observation = _observation(
        request=request,
        history=history,
        date_observations=date_observations,
        calendar=calendar,
    )
    return SimulatedTaxSettlementHistoryBuild(history, observation)


def _build_days(
    *,
    request: SimulatedTaxSettlementHistoryRequest,
    open_sessions: tuple[date, ...],
    mapped: tuple[tuple[SimulatedTaxSettlementFillSource, SimulatedDividendTaxDateEvidence], ...],
) -> tuple[
    tuple[TaxSettlementDayEvidence, ...],
    tuple[SimulatedTaxSettlementFillObservation, ...],
    str,
]:
    """Build EOD facts without treating zero-share cash posting as a FIFO revision.

    The caller validates every action's scope and rejects unsupported ownership
    changes first. Cash posting evidence remains in its immutable ledger/Audit
    chain; it does not change the share quantities used by this tax history.
    """

    grouped: dict[
        date, list[tuple[SimulatedTaxSettlementFillSource, SimulatedDividendTaxDateEvidence]]
    ] = {}
    for source, date_evidence in mapped:
        grouped.setdefault(date_evidence.modeled_tax_date, []).append((source, date_evidence))
    source_payload: dict[str, object] = {
        "schema": "simulated-v4-tax-source-revision.v1",
        "anchor": {
            "id": request.opening_anchor.anchor_id,
            "kind": request.opening_anchor.anchor_kind.value,
            "quantity": _share_text(request.opening_anchor.quantity, "opening_anchor.quantity"),
            "evidence_sha256": request.opening_anchor.evidence_sha256,
        },
        "fills": [
            {
                "trade_id": source.ownership_fill.trade_id,
                "reservation_id": source.ownership_fill.reservation_id,
                "fill_sequence": source.ownership_fill.fill_sequence,
                "receipt_sha256": source.ownership_fill.receipt_sha256,
                "source_namespace": source.source_namespace,
                "source_version": source.source_version,
                "source_event_id": source.source_event_id,
                "event_payload_sha256": source.event_payload_sha256,
                "source_snapshot_id": source.source_snapshot_id,
                "source_snapshot_sha256": source.source_snapshot_sha256,
                "side": source.ownership_fill.side.value,
                "quantity": _share_text(source.ownership_fill.quantity, "fill.quantity"),
                "occurred_at": source.ownership_fill.occurred_at.astimezone(UTC).isoformat(),
            }
            for source, _ in mapped
        ],
        "actions": [
            {
                "entry_id": action.entry_id,
                "source_event_id": action.source_event_id,
                "source_revision_id": action.source_revision_id,
                "evidence_sha256": action.evidence_sha256,
            }
            for action in request.corporate_action_evidence
            if action.recorded_at <= request.as_of
            and action.stage_date <= request.complete_through
            and (action.share_delta != _ZERO or action.share_receivable_delta != _ZERO)
        ],
    }
    source_revision_sha256 = _sha(source_payload)
    rows: list[TaxSettlementDayEvidence] = []
    observations: list[SimulatedTaxSettlementFillObservation] = []
    opening = _ZERO
    for session in open_sessions:
        purchases = Decimal("0")
        sales = Decimal("0")
        day_sources = grouped.get(session, [])
        with localcontext() as context:
            context.prec = 80
            for source, _ in day_sources:
                fill = source.ownership_fill
                if fill.side.value == "buy":
                    purchases += fill.quantity
                elif fill.side.value == "sell":
                    sales += fill.quantity
                else:
                    _reject("V4 fill side has no supported tax lot lineage")
        with localcontext() as context:
            context.prec = 80
            closing = opening + purchases - sales
        if closing < _ZERO:
            _reject("modeled daily net produces a negative simulated position")
        day_payload: dict[str, object] = {
            "schema": "simulated-tax-settlement-day.v1",
            "settlement_date": session.isoformat(),
            "source_revision_sha256": source_revision_sha256,
            "fills": [
                {
                    "source_event_id": source.source_event_id,
                    "event_payload_sha256": source.event_payload_sha256,
                    "receipt_sha256": source.ownership_fill.receipt_sha256,
                    "date_semantic_sha256": date_evidence.semantic_sha256,
                    "side": source.ownership_fill.side.value,
                    "quantity": _share_text(source.ownership_fill.quantity, "fill.quantity"),
                }
                for source, date_evidence in day_sources
            ],
            "opening": _share_text(opening, "day.opening"),
            "gross_purchases": _share_text(purchases, "day.gross_purchases"),
            "gross_sales": _share_text(sales, "day.gross_sales"),
            "closing": _share_text(closing, "day.closing"),
        }
        rows.append(
            TaxSettlementDayEvidence(
                account_id=request.physical_account_id,
                owner_user_id=request.owner_user_id,
                security_id=request.security_id,
                asset_code=request.asset_code,
                settlement_date=session,
                opening_eod_quantity=opening,
                gross_purchase_quantity=purchases,
                gross_sale_quantity=sales,
                non_trade_quantity_delta=_ZERO,
                closing_eod_quantity=closing,
                purchase_origin=TaxLotOrigin.PURCHASE,
                evidence_id=f"simulated-tax-eod.v1:{session.isoformat()}",
                evidence_sha256=_sha(day_payload),
                source_revision_id=f"simulated-v4-tax-history.v1:{source_revision_sha256}",
                source_revision_sha256=source_revision_sha256,
            )
        )
        for source, date_evidence in day_sources:
            fill = source.ownership_fill
            observations.append(
                SimulatedTaxSettlementFillObservation(
                    trade_id=fill.trade_id,
                    reservation_id=fill.reservation_id,
                    fill_sequence=fill.fill_sequence,
                    quantity=fill.quantity,
                    observation_basis=source.observation_basis,
                    receipt_sha256=fill.receipt_sha256,
                    source_namespace=source.source_namespace,
                    source_version=source.source_version,
                    source_event_id=source.source_event_id,
                    event_payload_sha256=source.event_payload_sha256,
                    source_snapshot_id=source.source_snapshot_id,
                    source_snapshot_sha256=source.source_snapshot_sha256,
                    order_idempotency_key=source.order_idempotency_key,
                    source_recorded_at=source.source_recorded_at,
                    source_observed_at=source.source_observed_at,
                    source_available_at=source.source_available_at,
                    local_known_at=source.local_known_at,
                    interval_end_at=source.interval_end_at,
                    date_evidence=date_evidence,
                )
            )
        opening = closing
    return tuple(rows), tuple(observations), source_revision_sha256


def _observation(
    *,
    request: SimulatedTaxSettlementHistoryRequest,
    history: QualifiedTaxSettlementHistory,
    date_observations: tuple[SimulatedTaxSettlementFillObservation, ...],
    calendar: ExecutionCalendarEvidence,
) -> SimulatedTaxSettlementHistoryObservation:
    """Capture exact current runtime/calendar clocks separate from history semantics."""

    publication = calendar.publication
    if publication is None:
        _reject("current published calendar reference is missing")
    snapshot = calendar.snapshot
    return SimulatedTaxSettlementHistoryObservation(
        date_rule=request.date_rule_provenance,
        history_identity_sha256=_history_identity(history),
        convention_valid_from=request.convention.valid_from,
        convention_valid_until=request.convention.valid_until,
        calendar_evidence_sha256=calendar.evidence_hash,
        calendar_snapshot_id=snapshot.snapshot_id,
        calendar_content_sha256=snapshot.content_hash,
        calendar_record_digest=snapshot.record_digest,
        calendar_first_seen_at=snapshot.first_seen_at,
        calendar_recorded_at=snapshot.recorded_at,
        calendar_response_completed_at=snapshot.raw_reference.response_completed_at,
        calendar_publication_id=publication.publication_id,
        calendar_publication_hash=publication.publication_hash,
        calendar_published_at=publication.published_at,
        calendar_publication_recorded_at=publication.recorded_at,
        calendar_reference_valid_from=publication.reference_valid_from,
        calendar_reference_valid_until=publication.reference_valid_until,
        calendar_timezone_name=publication.timezone_name,
        read_at=request.as_of,
        date_observations=date_observations,
    )


__all__ = [
    "SimulatedTaxDateRuleRuntimeProvenance",
    "SimulatedTaxSettlementFillObservation",
    "SimulatedTaxSettlementFillSource",
    "SimulatedTaxSettlementHistoryBuild",
    "SimulatedTaxSettlementHistoryObservation",
    "SimulatedTaxSettlementHistoryRequest",
    "build_simulated_tax_settlement_history",
]
