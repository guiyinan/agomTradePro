"""Read complete, explicitly simulated tax settlement history through typed ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.simulated_trading.application.execution_settlement_uow import (
    PublishedExecutionCalendarReader,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    CorporateActionOwnershipEvidence,
    OwnershipFillFact,
    OwnershipOpeningAnchor,
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    RecordDateTaxEntitlementEvidence,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
)
from apps.simulated_trading.domain.simulated_tax_date_convention import (
    SimulatedDividendTaxDateConvention,
)
from apps.simulated_trading.domain.simulated_tax_settlement_history import (
    SimulatedTaxDateRuleRuntimeProvenance,
    SimulatedTaxSettlementFillSource,
    SimulatedTaxSettlementHistoryBuild,
    SimulatedTaxSettlementHistoryRequest,
    build_simulated_tax_settlement_history,
)
from core.exceptions import BusinessLogicError


def _token(value: object, *, label: str, limit: int = 192) -> str:
    """Require a bounded application-scope token."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(character.isspace() for character in value)
    ):
        raise BusinessLogicError(f"{label} is invalid", code="TAX_SETTLEMENT_HISTORY_BLOCKED")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise BusinessLogicError(
            f"{label} is invalid UTF-8", code="TAX_SETTLEMENT_HISTORY_BLOCKED"
        ) from error
    return value


def _aware(value: object, *, label: str) -> datetime:
    """Require one exact aware clock."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise BusinessLogicError(
            f"{label} must be timezone-aware", code="TAX_SETTLEMENT_HISTORY_BLOCKED"
        )
    return value


@dataclass(frozen=True, slots=True)
class SimulatedTaxSettlementHistoryQuery:
    """Owner-scoped request to read one complete simulated settlement prefix."""

    environment: str
    account_kind: Literal["simulated"]
    physical_account_id: int
    canonical_account_id: str
    owner_user_id: int
    security_id: str
    asset_code: str
    record_date: date
    complete_through: date
    record_date_entitlement: RecordDateTaxEntitlementEvidence

    def __post_init__(self) -> None:
        """Reject incomplete request scope without inferring tax dates or eligibility."""

        _token(self.environment, label="environment", limit=64)
        _token(self.canonical_account_id, label="canonical_account_id", limit=128)
        _token(self.security_id, label="security_id", limit=96)
        _token(self.asset_code, label="asset_code", limit=96)
        if (
            self.account_kind != "simulated"
            or type(self.physical_account_id) is not int
            or self.physical_account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or type(self.record_date) is not date
            or type(self.complete_through) is not date
            or self.complete_through <= self.record_date
            or type(self.record_date_entitlement) is not RecordDateTaxEntitlementEvidence
        ):
            raise BusinessLogicError(
                "simulated tax settlement query scope is incomplete",
                code="TAX_SETTLEMENT_HISTORY_BLOCKED",
            )
        try:
            self.record_date_entitlement.__post_init__()
        except DeferredDividendTaxValidationError as error:
            raise BusinessLogicError(
                "qualified record-date entitlement is invalid",
                code="TAX_SETTLEMENT_HISTORY_BLOCKED",
            ) from error


@dataclass(frozen=True, slots=True)
class RecordDateOwnershipHistoryRead:
    """One repository result with the exact proof, anchor, source-backed fills, and actions."""

    proof: RecordDateOwnershipProof
    opening_anchor: OwnershipOpeningAnchor
    source_fills: tuple[SimulatedTaxSettlementFillSource, ...]
    corporate_action_evidence: tuple[CorporateActionOwnershipEvidence, ...]

    def __post_init__(self) -> None:
        """Require all returned facts to match the proof's physical owner scope."""

        if type(self.proof) is not RecordDateOwnershipProof:
            raise BusinessLogicError("ownership reader returned no exact proof")
        if type(self.opening_anchor) is not OwnershipOpeningAnchor:
            raise BusinessLogicError("ownership reader returned no exact zero-origin anchor")
        if type(self.source_fills) is not tuple or any(
            type(row) is not SimulatedTaxSettlementFillSource for row in self.source_fills
        ):
            raise BusinessLogicError("ownership reader returned untyped source fills")
        if type(self.corporate_action_evidence) is not tuple or any(
            type(row) is not CorporateActionOwnershipEvidence
            for row in self.corporate_action_evidence
        ):
            raise BusinessLogicError("ownership reader returned untyped action history")
        proof = self.proof
        if (
            self.opening_anchor.account_id != proof.account_id
            or self.opening_anchor.owner_user_id != proof.owner_user_id
            or any(
                row.ownership_fill.account_id != proof.account_id
                or row.ownership_fill.owner_user_id != proof.owner_user_id
                or row.ownership_fill.security_id != proof.security_id
                or row.ownership_fill.asset_code != proof.asset_code
                for row in self.source_fills
            )
            or any(
                row.account_id != proof.account_id
                or row.owner_user_id != proof.owner_user_id
                or row.security_id != proof.security_id
                or row.asset_code != proof.asset_code
                for row in self.corporate_action_evidence
            )
        ):
            raise BusinessLogicError(
                "ownership read result crosses account, owner, or instrument scope",
                code="TAX_SETTLEMENT_HISTORY_SCOPE_INVALID",
            )


@dataclass(frozen=True, slots=True)
class OwnershipHistoryFillSource:
    """Source event decoded from the exact retained V4 receipt and reservation."""

    ownership_fill: OwnershipFillFact
    source_event: LocalSimulatedFillEventV1
    order_idempotency_key: str

    def __post_init__(self) -> None:
        """Validate complete row/event equality without granting source authority."""

        if type(self.ownership_fill) is not OwnershipFillFact:
            raise BusinessLogicError("ownership fill source lacks an exact V4 fact")
        if type(self.source_event) is not LocalSimulatedFillEventV1:
            raise BusinessLogicError("ownership fill source lacks its decoded event")
        _token(self.order_idempotency_key, label="order_idempotency_key", limit=128)
        event = self.source_event
        fill = self.ownership_fill
        if (
            event.event_kind
            not in {LocalSimulatedFillEventKind.FILL, LocalSimulatedFillEventKind.FINAL_FILL}
            or event.account_id != fill.account_id
            or event.user_id != fill.owner_user_id
            or event.reservation_id != fill.reservation_id
            or event.security_id != fill.security_id
            or event.asset_code != fill.asset_code
            or event.side.value != fill.side.value
            or event.quantity != fill.quantity
            or event.occurred_at != fill.occurred_at
            or event.recorded_at > fill.recorded_at
            or event.order_idempotency_key != self.order_idempotency_key
        ):
            raise BusinessLogicError(
                "decoded V4 event differs from the ownership fill",
                code="TAX_SETTLEMENT_HISTORY_SOURCE_MISMATCH",
            )


@dataclass(frozen=True, slots=True)
class RecordDateOwnershipSourceRead:
    """Single-pass ownership replay output before current source-event revalidation."""

    proof: RecordDateOwnershipProof
    opening_anchor: OwnershipOpeningAnchor
    source_fills: tuple[OwnershipHistoryFillSource, ...]
    corporate_action_evidence: tuple[CorporateActionOwnershipEvidence, ...]

    def __post_init__(self) -> None:
        """Require one exact proof/anchor and typed complete source tuples."""

        if (
            type(self.proof) is not RecordDateOwnershipProof
            or type(self.opening_anchor) is not OwnershipOpeningAnchor
            or type(self.source_fills) is not tuple
            or any(type(row) is not OwnershipHistoryFillSource for row in self.source_fills)
            or type(self.corporate_action_evidence) is not tuple
            or any(
                type(row) is not CorporateActionOwnershipEvidence
                for row in self.corporate_action_evidence
            )
        ):
            raise BusinessLogicError("ownership source read is incomplete or untyped")
        if (
            self.opening_anchor.account_id != self.proof.account_id
            or self.opening_anchor.owner_user_id != self.proof.owner_user_id
            or any(
                source.ownership_fill.account_id != self.proof.account_id
                or source.ownership_fill.owner_user_id != self.proof.owner_user_id
                or source.ownership_fill.security_id != self.proof.security_id
                or source.ownership_fill.asset_code != self.proof.asset_code
                for source in self.source_fills
            )
            or any(
                action.account_id != self.proof.account_id
                or action.owner_user_id != self.proof.owner_user_id
                or action.security_id != self.proof.security_id
                or action.asset_code != self.proof.asset_code
                for action in self.corporate_action_evidence
            )
        ):
            raise BusinessLogicError(
                "ownership source read crosses the proof scope",
                code="TAX_SETTLEMENT_HISTORY_SCOPE_INVALID",
            )
        for row in self.source_fills:
            row.__post_init__()


@dataclass(frozen=True, slots=True)
class SimulatedTaxDateConventionRead:
    """Exact configured rule paired with its persisted Config Center provenance."""

    convention: SimulatedDividendTaxDateConvention
    provenance: SimulatedTaxDateRuleRuntimeProvenance

    def __post_init__(self) -> None:
        """Recheck the active rule identity before the calendar or fill mapping runs."""

        if (
            type(self.convention) is not SimulatedDividendTaxDateConvention
            or type(self.provenance) is not SimulatedTaxDateRuleRuntimeProvenance
        ):
            raise BusinessLogicError("current simulated tax date rule is untyped")
        try:
            self.convention.__post_init__()
            self.provenance.__post_init__()
        except DeferredDividendTaxValidationError as error:
            raise BusinessLogicError(
                "current simulated tax date rule failed validation",
                code="TAX_SETTLEMENT_DATE_RULE_UNAVAILABLE",
            ) from error
        if self.provenance.convention_sha256 != self.convention.semantic_sha256:
            raise BusinessLogicError(
                "Config Center provenance differs from the selected tax date rule",
                code="TAX_SETTLEMENT_DATE_RULE_UNAVAILABLE",
            )


class TaxSettlementHistoryInputReader(Protocol):
    """Read one exact anchored history after rechecking every source event."""

    @property
    def database_alias(self) -> str:
        """Return the alias used by both the ownership and original-event readers."""

    def read_record_date_history(
        self,
        *,
        account_id: int,
        owner_user_id: int,
        security_id: str,
        asset_code: str,
        record_date: date,
        as_of: datetime,
    ) -> RecordDateOwnershipHistoryRead:
        """Return the complete exact-source ownership evidence or raise a typed block."""


class CurrentSimulatedTaxDateRuleReader(Protocol):
    """Read the unique current explicitly configured rule for one simulated owner."""

    def read_current(
        self,
        *,
        environment: str,
        as_of: datetime,
        physical_account_id: int,
        canonical_account_id: str,
        owner_user_id: int,
    ) -> SimulatedTaxDateConventionRead:
        """Return the exact active configured rule and Config Center evidence."""


class TaxSettlementHistoryClock(Protocol):
    """Supply the server read cutoff used by Config Center and calendar sources."""

    def now(self) -> datetime:
        """Return an aware server time."""


class ReadSimulatedTaxSettlementHistoryUseCase:
    """Assemble current rule/calendar observations with the verified V4 source prefix."""

    def __init__(
        self,
        *,
        input_reader: TaxSettlementHistoryInputReader,
        date_rule_reader: CurrentSimulatedTaxDateRuleReader,
        calendar_reader: PublishedExecutionCalendarReader,
        clock: TaxSettlementHistoryClock,
        using: str,
    ) -> None:
        """Require explicit current readers and one shared database alias."""

        self._input_reader = input_reader
        self._date_rule_reader = date_rule_reader
        self._calendar_reader = calendar_reader
        self._clock = clock
        self._using = _token(using, label="database_alias", limit=64)
        if input_reader.database_alias != self._using:
            raise BusinessLogicError(
                "tax settlement history readers must share one database alias",
                code="TAX_SETTLEMENT_HISTORY_ALIAS_MISMATCH",
            )

    def execute(
        self,
        query: SimulatedTaxSettlementHistoryQuery,
    ) -> SimulatedTaxSettlementHistoryBuild:
        """Re-read source events and map them only with current explicit rule/calendar facts."""

        if type(query) is not SimulatedTaxSettlementHistoryQuery:
            raise BusinessLogicError("a typed simulated tax settlement query is required")
        query.__post_init__()
        as_of = _aware(self._clock.now(), label="server as_of")
        inputs = self._input_reader.read_record_date_history(
            account_id=query.physical_account_id,
            owner_user_id=query.owner_user_id,
            security_id=query.security_id,
            asset_code=query.asset_code,
            record_date=query.record_date,
            as_of=as_of,
        )
        if type(inputs) is not RecordDateOwnershipHistoryRead:
            raise BusinessLogicError("ownership repository returned an invalid history value")
        inputs.__post_init__()
        proof = inputs.proof
        if (
            proof.account_id != query.physical_account_id
            or proof.owner_user_id != query.owner_user_id
            or proof.security_id != query.security_id
            or proof.asset_code != query.asset_code
            or proof.record_date != query.record_date
        ):
            raise BusinessLogicError(
                "ownership proof differs from the requested account or action scope",
                code="TAX_SETTLEMENT_HISTORY_SCOPE_INVALID",
            )
        selected = self._date_rule_reader.read_current(
            environment=query.environment,
            as_of=as_of,
            physical_account_id=query.physical_account_id,
            canonical_account_id=query.canonical_account_id,
            owner_user_id=query.owner_user_id,
        )
        if type(selected) is not SimulatedTaxDateConventionRead:
            raise BusinessLogicError("date rule reader returned an invalid configured value")
        selected.__post_init__()
        if (
            selected.provenance.environment != query.environment
            or selected.provenance.as_of != as_of
        ):
            raise BusinessLogicError(
                "active date rule is not bound to this environment and read cutoff",
                code="TAX_SETTLEMENT_DATE_RULE_UNAVAILABLE",
            )
        try:
            timezone = ZoneInfo(proof.exchange_timezone_name)
            anchor_date = inputs.opening_anchor.effective_at.astimezone(timezone).date()
        except (OverflowError, TypeError, ValueError, ZoneInfoNotFoundError) as error:
            raise BusinessLogicError(
                "ownership cutoff timezone cannot be used to request calendar coverage",
                code="TAX_SETTLEMENT_CALENDAR_UNAVAILABLE",
            ) from error
        calendar = self._calendar_reader.get_effective_execution_calendar(
            exchange=selected.convention.exchange,
            as_of=as_of,
            coverage_start=anchor_date,
        )
        if type(calendar) is not ExecutionCalendarEvidence:
            raise BusinessLogicError(
                "the exact current published execution calendar is unavailable",
                code="TAX_SETTLEMENT_CALENDAR_UNAVAILABLE",
            )
        request = SimulatedTaxSettlementHistoryRequest(
            account_kind="simulated",
            physical_account_id=query.physical_account_id,
            canonical_account_id=query.canonical_account_id,
            owner_user_id=query.owner_user_id,
            security_id=query.security_id,
            asset_code=query.asset_code,
            record_date=query.record_date,
            complete_through=query.complete_through,
            record_date_ownership_proof=proof,
            opening_anchor=inputs.opening_anchor,
            source_fills=inputs.source_fills,
            corporate_action_evidence=inputs.corporate_action_evidence,
            record_date_entitlement=query.record_date_entitlement,
            convention=selected.convention,
            date_rule_provenance=selected.provenance,
            calendar=calendar,
            as_of=as_of,
        )
        try:
            result = build_simulated_tax_settlement_history(request)
        except DeferredDividendTaxValidationError as error:
            raise BusinessLogicError(
                "simulated tax settlement history is incomplete or inconsistent",
                code=error.code,
            ) from error
        checked_at = _aware(self._clock.now(), label="server checked_at")
        if checked_at < as_of:
            raise BusinessLogicError(
                "server clock moved backwards while reading tax settlement history",
                code="TAX_SETTLEMENT_HISTORY_BLOCKED",
            )
        if not selected.convention.valid_from <= checked_at < selected.convention.valid_until:
            raise BusinessLogicError(
                "simulated tax date rule expired while reading settlement history",
                code="TAX_SETTLEMENT_DATE_RULE_UNAVAILABLE",
            )
        try:
            calendar.validate_for(checked_at)
        except CalendarEvidenceValidationError as error:
            raise BusinessLogicError(
                "published calendar expired while reading tax settlement history",
                code="TAX_SETTLEMENT_CALENDAR_UNAVAILABLE",
            ) from error
        return result


__all__ = [
    "CurrentSimulatedTaxDateRuleReader",
    "ReadSimulatedTaxSettlementHistoryUseCase",
    "RecordDateOwnershipHistoryRead",
    "RecordDateOwnershipSourceRead",
    "OwnershipHistoryFillSource",
    "SimulatedTaxDateConventionRead",
    "SimulatedTaxSettlementHistoryQuery",
    "TaxSettlementHistoryInputReader",
    "TaxSettlementHistoryClock",
]
