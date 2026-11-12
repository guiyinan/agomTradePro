"""Orchestrate immutable per-disposition tax liability operations.

This Application layer defines only typed ports and fail-closed coordination.
The supplied verifier must hold an explicit current ``TAX_WITHHOLD`` grant,
and the writer must prove stored source records and retain the liability,
financial journal, Audit event, and Outbox atomically on one database alias.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Protocol

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
)
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentAppendDisposition,
    TaxAssessmentClockPort,
    TaxAssessmentWriteReceipt,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    CorporateActionTaxLiabilityState,
    CorporateActionTaxLiabilityTransition,
    TaxLiabilityCashAction,
    TaxLiabilityCashRequest,
    TaxLiabilityOperationIdentity,
    TaxLiabilityScope,
    plan_corporate_action_tax_liability,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)
from core.exceptions import BusinessLogicError

_WITHHOLD_PERMISSION = SimulatedCorporateActionWriteCapability.TAX_WITHHOLD.value
_ACCOUNT_NAMESPACE = "account"


class TaxLiabilityAppendDisposition(StrEnum):
    """Whether this operation was first appended or exactly replayed."""

    STORED = "stored"
    EXACT_RETRY = "exact_retry"


def _blocked(message: str, code: str = "TAX_LIABILITY_BLOCKED") -> BusinessLogicError:
    """Build a stable, caller-recognizable Application failure."""

    return BusinessLogicError(message, code=code)


def _token(value: object, *, field_name: str, limit: int = 192) -> str:
    """Require one bounded, whitespace-free UTF-8 identity token."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(character.isspace() for character in value)
    ):
        raise _blocked(f"{field_name} is invalid", "TAX_LIABILITY_SCOPE_BLOCKED")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise _blocked(f"{field_name} is invalid UTF-8", "TAX_LIABILITY_SCOPE_BLOCKED") from error
    return value


def _digest(value: object, *, field_name: str) -> str:
    """Require one exact lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _blocked(f"{field_name} is invalid", "TAX_LIABILITY_EVIDENCE_INVALID")
    return value


def _aware(value: object, *, field_name: str) -> datetime:
    """Require an aware instant that can be represented in UTC."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _blocked(f"{field_name} must be timezone-aware", "TAX_LIABILITY_CLOCK_INVALID")
    try:
        value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise _blocked(
            f"{field_name} is outside the UTC range", "TAX_LIABILITY_CLOCK_INVALID"
        ) from error
    return value


def _require_receipt_money(value: object, *, quantum: Decimal, field_name: str) -> Decimal:
    """Validate a receipt amount against the Domain's exact supported money capacity."""

    if type(value) is not Decimal or not value.is_finite():
        raise _blocked(f"receipt {field_name} is not a finite Decimal")
    sign, digits, exponent = value.as_tuple()
    if (
        type(exponent) is not int
        or exponent < -12
        or len(digits) > 80
        or (value != 0 and value.adjusted() > 67)
    ):
        raise _blocked(f"receipt {field_name} exceeds supported money precision")
    try:
        with localcontext() as context:
            context.prec = 80
            quantized = value.quantize(quantum)
    except (InvalidOperation, ValueError) as error:
        raise _blocked(f"receipt {field_name} cannot be represented in its currency") from error
    if quantized != value:
        raise _blocked(f"receipt {field_name} is not an exact currency amount")
    return value


def _scope_for_assessment(assessment: CorporateActionTaxAssessment) -> TaxLiabilityScope:
    """Derive a disposition scope from the complete integrity-checked assessment."""

    return TaxLiabilityScope(
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        security_id=assessment.security_id,
        asset_code=assessment.asset_code,
        corporate_action_id=assessment.action.corporate_action_id,
        source_namespace=assessment.action.source_namespace,
        logical_source_event_id=assessment.action.source_event_id,
        target_disposition_id=assessment.bridge.request.target_disposition_id,
        record_date=assessment.history.record_date,
        target_settlement_date=assessment.target_settlement_date,
    )


def _operation_request_sha256(
    *,
    operation_id: str,
    assessment: CorporateActionTaxAssessment,
    stored_assessment: TaxAssessmentWriteReceipt,
    lease: TaxLiabilityWriteLease,
    cash_action: TaxLiabilityCashAction | None,
) -> str:
    """Use the shared Domain wire identity for initial writes and historical retries."""
    return TaxLiabilityOperationIdentity(
        operation_id=operation_id,
        scope=lease.scope,
        canonical_account_namespace=lease.canonical_account_namespace,
        canonical_account_id=lease.canonical_account_id,
        currency=lease.currency,
        assessment_revision_id=assessment.assessment_revision_id,
        supersedes_assessment_revision_id=assessment.supersedes_assessment_revision_id,
        assessment_semantic_sha256=assessment.semantic_sha256,
        stored_assessment_manifest_sha256=stored_assessment.observation_manifest_sha256,
        cash_action=cash_action,
    ).request_sha256


@dataclass(frozen=True, slots=True)
class TaxLiabilityWriteLease:
    """Finite current TAX_WITHHOLD authority for one persisted assessment."""

    database_alias: str
    actor_user_id: int
    owner_user_id: int
    physical_account_id: int
    scope: TaxLiabilityScope
    canonical_account_namespace: str
    canonical_account_id: str
    currency: SimulatedDividendTaxCurrency
    currency_quantum: Decimal
    assessment_revision_id: str
    assessment_semantic_sha256: str
    operation_id: str
    cash_action: TaxLiabilityCashAction | None
    permission: str
    grant_schema: str
    capabilities: tuple[SimulatedCorporateActionWriteCapability, ...]
    terms_version: str
    terms_sha256: str
    service_actor_id: str
    authority_grant_id: str
    authority_grant_version: str
    authority_grant_content_sha256: str
    audit_tenant_id: str
    audit_owner_id: str
    valid_until: datetime

    def __post_init__(self) -> None:
        """Validate explicit grant, owner, canonical account, currency, and Audit facts."""

        _token(self.database_alias, field_name="database_alias", limit=64)
        if (
            type(self.actor_user_id) is not int
            or self.actor_user_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or self.actor_user_id != self.owner_user_id
            or type(self.physical_account_id) is not int
            or self.physical_account_id <= 0
        ):
            raise _blocked("liability owner scope is invalid", "TAX_LIABILITY_SCOPE_BLOCKED")
        if type(self.scope) is not TaxLiabilityScope:
            raise _blocked("liability scope is untyped", "TAX_LIABILITY_SCOPE_BLOCKED")
        try:
            self.scope.__post_init__()
        except DeferredDividendTaxValidationError as error:
            raise _blocked("liability scope failed Domain validation") from error
        if (
            self.physical_account_id != self.scope.account_id
            or self.owner_user_id != self.scope.owner_user_id
        ):
            raise _blocked("liability physical scope differs from its disposition")
        _token(self.canonical_account_namespace, field_name="canonical_account_namespace")
        _token(self.canonical_account_id, field_name="canonical_account_id")
        if self.canonical_account_namespace != _ACCOUNT_NAMESPACE:
            raise _blocked("canonical Account namespace is required", "TAX_LIABILITY_SCOPE_BLOCKED")
        if type(self.currency) is not SimulatedDividendTaxCurrency:
            raise _blocked("tax liability currency is untyped", "TAX_LIABILITY_SCOPE_BLOCKED")
        if self.currency is not SimulatedDividendTaxCurrency.CNY:
            raise _blocked("the simulated cash ledger supports only configured CNY")
        if (
            type(self.currency_quantum) is not Decimal
            or not self.currency_quantum.is_finite()
            or self.currency_quantum <= 0
        ):
            raise _blocked("current currency quantum is invalid", "TAX_LIABILITY_SCOPE_BLOCKED")
        _token(self.assessment_revision_id, field_name="assessment_revision_id")
        _digest(self.assessment_semantic_sha256, field_name="assessment_semantic_sha256")
        _token(self.operation_id, field_name="operation_id")
        if self.cash_action is not None and type(self.cash_action) is not TaxLiabilityCashAction:
            raise _blocked("current withholding lease has an invalid cash action")
        if (
            self.permission != _WITHHOLD_PERMISSION
            or self.grant_schema != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
            or type(self.capabilities) is not tuple
            or not self.capabilities
            or any(
                type(item) is not SimulatedCorporateActionWriteCapability
                for item in self.capabilities
            )
            or tuple(sorted(set(self.capabilities), key=lambda item: item.value))
            != self.capabilities
            or SimulatedCorporateActionWriteCapability.TAX_WITHHOLD not in self.capabilities
            or self.service_actor_id != SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID
        ):
            raise _blocked(
                "an explicit V2 tax-withholding grant is required",
                "TAX_LIABILITY_AUTHORITY_BLOCKED",
            )
        _token(self.grant_schema, field_name="grant_schema")
        _token(self.terms_version, field_name="terms_version")
        _digest(self.terms_sha256, field_name="terms_sha256")
        _token(self.authority_grant_id, field_name="authority_grant_id")
        _token(self.authority_grant_version, field_name="authority_grant_version", limit=128)
        _digest(self.authority_grant_content_sha256, field_name="authority_grant_content_sha256")
        _token(self.audit_tenant_id, field_name="audit_tenant_id")
        _token(self.audit_owner_id, field_name="audit_owner_id")
        _aware(self.valid_until, field_name="authority valid_until")

    def verify_for(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        using: str,
        operation_id: str,
        cash_action: TaxLiabilityCashAction | None,
        as_of: datetime,
    ) -> None:
        """Bind the live lease to the full persisted assessment and requested owner."""

        self.__post_init__()
        _aware(as_of, field_name="server liability clock")
        if type(assessment) is not CorporateActionTaxAssessment:
            raise _blocked("a typed tax assessment is required", "TAX_LIABILITY_INPUT_INVALID")
        try:
            assessment.verify_integrity()
            scope = _scope_for_assessment(assessment)
        except DeferredDividendTaxValidationError as error:
            raise _blocked(
                "tax assessment failed integrity verification", "TAX_ASSESSMENT_EVIDENCE_INVALID"
            ) from error
        if (
            using != self.database_alias
            or type(actor_user_id) is not int
            or actor_user_id != self.actor_user_id
            or actor_user_id != self.owner_user_id
            or actor_user_id != assessment.owner_user_id
            or self.scope != scope
            or self.physical_account_id != assessment.account_id
            or self.assessment_revision_id != assessment.assessment_revision_id
            or self.assessment_semantic_sha256 != assessment.semantic_sha256
            or self.currency_quantum != assessment.policy.currency_quantum
            or self.operation_id != operation_id
            or self.cash_action is not cash_action
        ):
            raise _blocked("current withholding lease differs from the exact assessment scope")
        if as_of.astimezone(UTC) >= self.valid_until.astimezone(UTC):
            raise _blocked("current withholding lease expired", "TAX_LIABILITY_AUTHORITY_EXPIRED")

    def assert_live(self, *, as_of: datetime) -> None:
        """Cheaply check the half-open lease deadline before transaction commit."""

        _aware(as_of, field_name="server liability clock")
        if as_of.astimezone(UTC) >= self.valid_until.astimezone(UTC):
            raise _blocked("current withholding lease expired", "TAX_LIABILITY_AUTHORITY_EXPIRED")


@dataclass(frozen=True, slots=True)
class TaxLiabilityEvidenceReference:
    """Exact immutable reference to a liability, journal, Audit, or Outbox row."""

    reference_id: str
    reference_version: str
    content_sha256: str

    def __post_init__(self) -> None:
        """Reject incomplete stored-artifact references."""

        _token(self.reference_id, field_name="artifact reference id")
        _token(self.reference_version, field_name="artifact reference version", limit=128)
        _digest(self.content_sha256, field_name="artifact reference hash")


@dataclass(frozen=True, slots=True)
class TaxLiabilityFinancialSnapshot:
    """Writer-read current cash and holds, bound to one locked liability scope."""

    physical_account_id: int
    owner_user_id: int
    scope: TaxLiabilityScope
    canonical_account_namespace: str
    canonical_account_id: str
    currency: SimulatedDividendTaxCurrency
    book_cash: Decimal
    reserved_cash: Decimal
    evidence: TaxLiabilityEvidenceReference
    observed_at: datetime

    def __post_init__(self) -> None:
        """Validate current balance facts without granting authority from their hash."""

        if (
            type(self.physical_account_id) is not int
            or self.physical_account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or type(self.scope) is not TaxLiabilityScope
            or self.physical_account_id != self.scope.account_id
            or self.owner_user_id != self.scope.owner_user_id
        ):
            raise _blocked("financial snapshot physical owner scope is invalid")
        try:
            self.scope.__post_init__()
        except DeferredDividendTaxValidationError as error:
            raise _blocked("financial snapshot scope failed Domain validation") from error
        _token(self.canonical_account_namespace, field_name="canonical_account_namespace")
        _token(self.canonical_account_id, field_name="canonical_account_id")
        if self.canonical_account_namespace != _ACCOUNT_NAMESPACE:
            raise _blocked("financial snapshot has another canonical namespace")
        if type(self.currency) is not SimulatedDividendTaxCurrency:
            raise _blocked("financial snapshot currency is untyped")
        for name in ("book_cash", "reserved_cash"):
            amount = getattr(self, name)
            if type(amount) is not Decimal or not amount.is_finite() or amount < 0:
                raise _blocked(f"financial snapshot {name} is invalid")
        if type(self.evidence) is not TaxLiabilityEvidenceReference:
            raise _blocked("financial snapshot evidence reference is untyped")
        self.evidence.__post_init__()
        _aware(self.observed_at, field_name="financial snapshot observed_at")

    def verify_for(
        self,
        lease: TaxLiabilityWriteLease,
        *,
        as_of: datetime,
    ) -> None:
        """Bind a locked current balance read to its exact account and liability."""

        self.__post_init__()
        _aware(as_of, field_name="server liability clock")
        if (
            self.physical_account_id != lease.physical_account_id
            or self.owner_user_id != lease.owner_user_id
            or self.scope != lease.scope
            or self.canonical_account_namespace != lease.canonical_account_namespace
            or self.canonical_account_id != lease.canonical_account_id
            or self.currency is not lease.currency
            or self.observed_at.astimezone(UTC) > as_of.astimezone(UTC)
            or self.reserved_cash > self.book_cash
        ):
            raise _blocked("current financial snapshot differs from the locked owner scope")


@dataclass(frozen=True, slots=True)
class TaxLiabilityWriteReceipt:
    """Persisted operation identity and complete original journal/Audit/Outbox references."""

    disposition: TaxLiabilityAppendDisposition
    operation_id: str
    operation_request_sha256: str
    scope: TaxLiabilityScope
    canonical_account_namespace: str
    canonical_account_id: str
    currency: SimulatedDividendTaxCurrency
    currency_quantum: Decimal
    cash_action: TaxLiabilityCashAction | None
    cash_snapshot_reference: TaxLiabilityEvidenceReference | None
    assessment_revision_id: str
    assessment_semantic_sha256: str
    assessment_observation_manifest_sha256: str
    transition_sha256: str
    state_after_sha256: str
    tax_due_delta: Decimal
    collected_delta: Decimal
    outstanding_delta: Decimal
    cash_delta: Decimal
    liability_record: TaxLiabilityEvidenceReference
    journal_entry: TaxLiabilityEvidenceReference
    audit_event: TaxLiabilityEvidenceReference
    outbox_record: TaxLiabilityEvidenceReference

    def __post_init__(self) -> None:
        """Require one complete, stable operation result."""

        if type(self.disposition) is not TaxLiabilityAppendDisposition:
            raise _blocked("liability operation disposition is invalid")
        _token(self.operation_id, field_name="operation_id")
        _digest(self.operation_request_sha256, field_name="operation_request_sha256")
        if type(self.scope) is not TaxLiabilityScope:
            raise _blocked("liability operation scope is untyped")
        try:
            self.scope.__post_init__()
        except DeferredDividendTaxValidationError as error:
            raise _blocked("liability receipt scope failed Domain validation") from error
        _token(self.canonical_account_namespace, field_name="canonical_account_namespace")
        _token(self.canonical_account_id, field_name="canonical_account_id")
        if self.canonical_account_namespace != _ACCOUNT_NAMESPACE:
            raise _blocked("liability receipt has another canonical namespace")
        if type(self.currency) is not SimulatedDividendTaxCurrency:
            raise _blocked("liability receipt currency is untyped")
        if (
            type(self.currency_quantum) is not Decimal
            or not self.currency_quantum.is_finite()
            or self.currency_quantum <= 0
        ):
            raise _blocked("liability receipt quantum is invalid")
        quantum_sign, quantum_digits, quantum_exponent = self.currency_quantum.as_tuple()
        if (
            quantum_sign != 0
            or quantum_digits != (1,)
            or type(quantum_exponent) is not int
            or quantum_exponent > 0
            or quantum_exponent < -12
        ):
            raise _blocked("liability receipt quantum is unsupported")
        if self.cash_action is not None and type(self.cash_action) is not TaxLiabilityCashAction:
            raise _blocked("liability receipt cash action is invalid")
        if self.cash_action is None:
            if self.cash_snapshot_reference is not None:
                raise _blocked("a no-cash operation cannot reference a cash snapshot")
        else:
            if type(self.cash_snapshot_reference) is not TaxLiabilityEvidenceReference:
                raise _blocked("cash operation lacks its original balance snapshot reference")
            self.cash_snapshot_reference.__post_init__()
        _token(self.assessment_revision_id, field_name="assessment_revision_id")
        for name in (
            "assessment_semantic_sha256",
            "assessment_observation_manifest_sha256",
            "transition_sha256",
            "state_after_sha256",
        ):
            _digest(getattr(self, name), field_name=name)
        amounts = {
            name: _require_receipt_money(
                getattr(self, name), quantum=self.currency_quantum, field_name=name
            )
            for name in ("tax_due_delta", "collected_delta", "outstanding_delta", "cash_delta")
        }
        if amounts["cash_delta"] != amounts["collected_delta"].copy_negate():
            raise _blocked("liability receipt cash and collection deltas disagree")
        with localcontext() as context:
            context.prec = 80
            if amounts["tax_due_delta"] != (
                amounts["collected_delta"] + amounts["outstanding_delta"]
            ):
                raise _blocked("liability receipt due and outstanding deltas disagree")
        if self.cash_action is None and amounts["collected_delta"] != 0:
            raise _blocked("liability receipt collected tax without explicit cash action")
        for name in ("liability_record", "journal_entry", "audit_event", "outbox_record"):
            reference = getattr(self, name)
            if type(reference) is not TaxLiabilityEvidenceReference:
                raise _blocked(f"liability receipt {name} reference is missing")
            reference.__post_init__()


@dataclass(frozen=True, slots=True)
class TaxLiabilityCurrentState:
    """Current liability state with the exact currency and last audited operation."""

    state: CorporateActionTaxLiabilityState
    canonical_account_namespace: str
    canonical_account_id: str
    currency: SimulatedDividendTaxCurrency
    assessment_observation_manifest_sha256: str
    last_operation_receipt: TaxLiabilityWriteReceipt

    def __post_init__(self) -> None:
        """Tie the current state to its stored assessment and complete operation receipt."""

        if type(self.state) is not CorporateActionTaxLiabilityState:
            raise _blocked("current liability state is untyped")
        try:
            self.state.verify_integrity()
        except DeferredDividendTaxValidationError as error:
            raise _blocked("current liability state failed Domain validation") from error
        _token(self.canonical_account_namespace, field_name="canonical_account_namespace")
        _token(self.canonical_account_id, field_name="canonical_account_id")
        if self.canonical_account_namespace != _ACCOUNT_NAMESPACE:
            raise _blocked("current liability uses another canonical namespace")
        if type(self.currency) is not SimulatedDividendTaxCurrency:
            raise _blocked("current liability currency is untyped")
        _digest(
            self.assessment_observation_manifest_sha256,
            field_name="assessment_observation_manifest_sha256",
        )
        if type(self.last_operation_receipt) is not TaxLiabilityWriteReceipt:
            raise _blocked("current liability lacks its original operation receipt")
        receipt = self.last_operation_receipt
        receipt.__post_init__()
        if (
            receipt.disposition is not TaxLiabilityAppendDisposition.STORED
            or receipt.scope != self.state.scope
            or receipt.canonical_account_namespace != self.canonical_account_namespace
            or receipt.canonical_account_id != self.canonical_account_id
            or receipt.currency is not self.currency
            or receipt.currency_quantum != self.state.currency_quantum
            or receipt.assessment_revision_id != self.state.assessment_revision_id
            or receipt.assessment_semantic_sha256 != self.state.assessment_semantic_sha256
            or receipt.assessment_observation_manifest_sha256
            != self.assessment_observation_manifest_sha256
            or receipt.state_after_sha256 != self.state.state_sha256
        ):
            raise _blocked("current liability differs from its last persisted operation")


class CurrentTaxLiabilityScopeVerifierPort(Protocol):
    """Hold current owner, physical source, V2 TAX_WITHHOLD grant, and Audit scope locks."""

    @property
    def database_alias(self) -> str:
        """Return the alias on which all current scope facts are locked."""

    def locked_current_scope(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        using: str,
        operation_id: str,
        cash_action: TaxLiabilityCashAction | None,
    ) -> AbstractContextManager[TaxLiabilityWriteLease]:
        """Yield a finite exact lease and recheck all mutable facts before UOW commit."""


class TaxLiabilityAtomicWriterPort(Protocol):
    """Lock operation/current-liability state and atomically persist complete evidence."""

    def require_stored_assessment(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
    ) -> TaxAssessmentWriteReceipt:
        """Read the original assessment only after verifying its allocations, Audit, and Outbox.

        This is a readback guard: it must never append or synthesize missing assessment evidence.
        """

    def lock_operation_and_state(
        self,
        *,
        operation_id: str,
        scope: TaxLiabilityScope,
        canonical_account_namespace: str,
        canonical_account_id: str,
        currency: SimulatedDividendTaxCurrency,
    ) -> None:
        """Serialize the operation-id slot and disposition state, even when no row exists."""

    def get_operation(self, *, operation_id: str) -> TaxLiabilityWriteReceipt | None:
        """Return the original fully verified journal/Audit/Outbox receipt or ``None``."""

    def read_current_state(
        self,
        *,
        scope: TaxLiabilityScope,
        canonical_account_namespace: str,
        canonical_account_id: str,
        currency: SimulatedDividendTaxCurrency,
    ) -> TaxLiabilityCurrentState | None:
        """Read the complete locked current liability and prove its stored assessment chain."""

    def read_financial_snapshot(
        self,
        *,
        scope: TaxLiabilityScope,
        canonical_account_namespace: str,
        canonical_account_id: str,
        currency: SimulatedDividendTaxCurrency,
    ) -> TaxLiabilityFinancialSnapshot:
        """Read locked server cash and active holds with immutable evidence provenance."""

    def append_transition(
        self,
        assessment: CorporateActionTaxAssessment,
        transition: CorporateActionTaxLiabilityTransition,
        *,
        actor_user_id: int,
        stored_assessment: TaxAssessmentWriteReceipt,
        lease: TaxLiabilityWriteLease,
        operation_id: str,
        operation_request_sha256: str,
        expected_prior_state_sha256: str | None,
        cash_action: TaxLiabilityCashAction | None,
        cash_snapshot: TaxLiabilityFinancialSnapshot | None,
    ) -> TaxLiabilityWriteReceipt:
        """Append the exact transition, liability/journal rows, Audit, and Outbox in this UOW."""


class TaxLiabilityAtomicUnitOfWorkPort(Protocol):
    """Open an outer same-alias transaction around authority and financial writes."""

    @property
    def database_alias(self) -> str:
        """Return the database alias used by the writer."""

    def atomic(self, *, using: str) -> AbstractContextManager[TaxLiabilityAtomicWriterPort]:
        """Open one unnested atomic UOW for current locks, state, journal, Audit, and Outbox."""


def _validate_assessment_receipt(
    assessment: CorporateActionTaxAssessment,
    receipt: object,
) -> TaxAssessmentWriteReceipt:
    """Require a persisted exact assessment revision without demanding a new manifest."""

    if type(receipt) is not TaxAssessmentWriteReceipt:
        raise _blocked("stored assessment receipt is untyped", "TAX_LIABILITY_EVIDENCE_INVALID")
    receipt.__post_init__()
    if (
        receipt.assessment_revision_id != assessment.assessment_revision_id
        or receipt.semantic_sha256 != assessment.semantic_sha256
        or (
            receipt.disposition is TaxAssessmentAppendDisposition.STORED
            and receipt.observation_manifest_sha256 != assessment.observation_manifest_sha256
        )
    ):
        raise _blocked("stored assessment differs from the requested revision")
    return receipt


def _validate_current_state(
    current: object,
    *,
    scope: TaxLiabilityScope,
    lease: TaxLiabilityWriteLease,
) -> CorporateActionTaxLiabilityState:
    """Require exact disposition, canonical account, and currency on the current head."""

    if type(current) is not TaxLiabilityCurrentState:
        raise _blocked("current liability reader returned an untyped result")
    current.__post_init__()
    if (
        current.state.scope != scope
        or current.canonical_account_namespace != lease.canonical_account_namespace
        or current.canonical_account_id != lease.canonical_account_id
        or current.currency is not lease.currency
        or current.state.currency_quantum != lease.currency_quantum
    ):
        raise _blocked("current liability head belongs to another scope or currency")
    return current.state


def _validate_operation_receipt(
    receipt: object,
    *,
    disposition: TaxLiabilityAppendDisposition,
    operation_id: str,
    request_sha256: str,
    assessment: CorporateActionTaxAssessment,
    assessment_manifest_sha256: str,
    lease: TaxLiabilityWriteLease,
    cash_action: TaxLiabilityCashAction | None,
    cash_snapshot: TaxLiabilityFinancialSnapshot | None,
    transition: CorporateActionTaxLiabilityTransition | None,
) -> TaxLiabilityWriteReceipt:
    """Reject wrong operation, scope, amount, or missing original evidence references."""

    if type(receipt) is not TaxLiabilityWriteReceipt:
        raise _blocked("liability writer returned an untyped receipt")
    receipt.__post_init__()
    if (
        receipt.disposition is not disposition
        or receipt.operation_id != operation_id
        or receipt.operation_request_sha256 != request_sha256
        or receipt.scope != lease.scope
        or receipt.canonical_account_namespace != lease.canonical_account_namespace
        or receipt.canonical_account_id != lease.canonical_account_id
        or receipt.currency is not lease.currency
        or receipt.currency_quantum != lease.currency_quantum
        or receipt.cash_action is not cash_action
        or receipt.assessment_revision_id != assessment.assessment_revision_id
        or receipt.assessment_semantic_sha256 != assessment.semantic_sha256
        or receipt.assessment_observation_manifest_sha256 != assessment_manifest_sha256
    ):
        raise _blocked("liability writer receipt belongs to another operation or scope")
    if cash_snapshot is not None and receipt.cash_snapshot_reference != cash_snapshot.evidence:
        raise _blocked("liability writer receipt does not retain its exact cash snapshot")
    if transition is not None and (
        receipt.transition_sha256 != transition.transition_sha256
        or receipt.state_after_sha256 != transition.state_after.state_sha256
        or receipt.tax_due_delta != transition.tax_due_delta
        or receipt.collected_delta != transition.collected_delta
        or receipt.outstanding_delta != transition.outstanding_delta
        or receipt.cash_delta != transition.cash_delta
    ):
        raise _blocked("stored liability receipt differs from the planned transition")
    return receipt


class CorporateActionTaxLiabilityUseCase:
    """Apply one immutable assessment/liability operation under current withholding authority."""

    def __init__(
        self,
        *,
        scope_verifier: CurrentTaxLiabilityScopeVerifierPort,
        unit_of_work: TaxLiabilityAtomicUnitOfWorkPort,
        clock: TaxAssessmentClockPort,
        using: str,
    ) -> None:
        """Require explicit same-alias verifier, writer, and server clock ports."""

        self._scope_verifier = scope_verifier
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._using = _token(using, field_name="database_alias", limit=64)

    def execute(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        operation_id: str,
        cash_action: TaxLiabilityCashAction | None = None,
    ) -> TaxLiabilityWriteReceipt:
        """Persist one assessment liability operation or return its exact audited retry."""

        if type(assessment) is not CorporateActionTaxAssessment:
            raise _blocked("a typed corporate-action tax assessment is required")
        if type(actor_user_id) is not int or actor_user_id <= 0:
            raise _blocked("an authenticated owner identity is required")
        if actor_user_id != assessment.owner_user_id:
            raise _blocked("only the exact assessment owner may request this operation")
        operation = _token(operation_id, field_name="operation_id")
        if cash_action is not None and type(cash_action) is not TaxLiabilityCashAction:
            raise _blocked("cash movement requires an explicit typed action")
        if (
            self._scope_verifier.database_alias != self._using
            or self._unit_of_work.database_alias != self._using
        ):
            raise _blocked("authority, liability, journal, Audit, and Outbox aliases must match")
        try:
            assessment.verify_integrity()
            scope = _scope_for_assessment(assessment)
        except DeferredDividendTaxValidationError as error:
            raise _blocked(
                "tax assessment failed Domain integrity verification",
                "TAX_ASSESSMENT_EVIDENCE_INVALID",
            ) from error

        with self._unit_of_work.atomic(using=self._using) as writer:
            with self._scope_verifier.locked_current_scope(
                assessment,
                actor_user_id=actor_user_id,
                using=self._using,
                operation_id=operation,
                cash_action=cash_action,
            ) as lease:
                if type(lease) is not TaxLiabilityWriteLease:
                    raise _blocked("current tax-withholding lease is untyped")
                entry_at = _aware(self._clock.now(), field_name="server liability clock")
                lease.verify_for(
                    assessment,
                    actor_user_id=actor_user_id,
                    using=self._using,
                    operation_id=operation,
                    cash_action=cash_action,
                    as_of=entry_at,
                )
                stored_assessment = _validate_assessment_receipt(
                    assessment,
                    writer.require_stored_assessment(assessment, actor_user_id=actor_user_id),
                )
                request_sha256 = _operation_request_sha256(
                    operation_id=operation,
                    assessment=assessment,
                    stored_assessment=stored_assessment,
                    lease=lease,
                    cash_action=cash_action,
                )
                writer.lock_operation_and_state(
                    operation_id=operation,
                    scope=scope,
                    canonical_account_namespace=lease.canonical_account_namespace,
                    canonical_account_id=lease.canonical_account_id,
                    currency=lease.currency,
                )
                existing = writer.get_operation(operation_id=operation)
                if existing is not None:
                    receipt = _validate_operation_receipt(
                        existing,
                        disposition=TaxLiabilityAppendDisposition.EXACT_RETRY,
                        operation_id=operation,
                        request_sha256=request_sha256,
                        assessment=assessment,
                        assessment_manifest_sha256=(stored_assessment.observation_manifest_sha256),
                        lease=lease,
                        cash_action=cash_action,
                        cash_snapshot=None,
                        transition=None,
                    )
                else:
                    current = writer.read_current_state(
                        scope=scope,
                        canonical_account_namespace=lease.canonical_account_namespace,
                        canonical_account_id=lease.canonical_account_id,
                        currency=lease.currency,
                    )
                    prior_state = (
                        None
                        if current is None
                        else _validate_current_state(current, scope=scope, lease=lease)
                    )
                    append_at = _aware(self._clock.now(), field_name="server liability clock")
                    if append_at.astimezone(UTC) < entry_at.astimezone(UTC):
                        raise _blocked(
                            "server clock moved backwards before liability append",
                            "TAX_LIABILITY_CLOCK_INVALID",
                        )
                    cash_snapshot: TaxLiabilityFinancialSnapshot | None = None
                    cash_request: TaxLiabilityCashRequest | None = None
                    try:
                        if cash_action is not None:
                            candidate_snapshot = writer.read_financial_snapshot(
                                scope=scope,
                                canonical_account_namespace=lease.canonical_account_namespace,
                                canonical_account_id=lease.canonical_account_id,
                                currency=lease.currency,
                            )
                            if type(candidate_snapshot) is not TaxLiabilityFinancialSnapshot:
                                raise _blocked(
                                    "financial writer returned an untyped current snapshot"
                                )
                            snapshot_read_at = _aware(
                                self._clock.now(), field_name="server liability clock"
                            )
                            if snapshot_read_at.astimezone(UTC) < append_at.astimezone(UTC):
                                raise _blocked("server clock moved backwards during cash read")
                            candidate_snapshot.verify_for(lease, as_of=snapshot_read_at)
                            append_at = snapshot_read_at
                            cash_snapshot = candidate_snapshot
                            cash_request = TaxLiabilityCashRequest(
                                action=cash_action,
                                book_cash=cash_snapshot.book_cash,
                                reserved_cash=cash_snapshot.reserved_cash,
                            )
                        transition = plan_corporate_action_tax_liability(
                            assessment,
                            prior_state=prior_state,
                            cash_request=cash_request,
                        )
                        transition.verify_integrity()
                    except DeferredDividendTaxValidationError as error:
                        raise _blocked(
                            "liability transition failed Domain validation",
                            "TAX_LIABILITY_INPUT_INVALID",
                        ) from error
                    plan_checked_at = _aware(self._clock.now(), field_name="server liability clock")
                    if plan_checked_at.astimezone(UTC) < append_at.astimezone(UTC):
                        raise _blocked("server clock moved backwards during liability planning")
                    append_at = plan_checked_at
                    lease.verify_for(
                        assessment,
                        actor_user_id=actor_user_id,
                        using=self._using,
                        operation_id=operation,
                        cash_action=cash_action,
                        as_of=append_at,
                    )
                    receipt = _validate_operation_receipt(
                        writer.append_transition(
                            assessment,
                            transition,
                            actor_user_id=actor_user_id,
                            stored_assessment=stored_assessment,
                            lease=lease,
                            operation_id=operation,
                            operation_request_sha256=request_sha256,
                            expected_prior_state_sha256=(
                                None if prior_state is None else prior_state.state_sha256
                            ),
                            cash_action=cash_action,
                            cash_snapshot=cash_snapshot,
                        ),
                        disposition=TaxLiabilityAppendDisposition.STORED,
                        operation_id=operation,
                        request_sha256=request_sha256,
                        assessment=assessment,
                        assessment_manifest_sha256=(stored_assessment.observation_manifest_sha256),
                        lease=lease,
                        cash_action=cash_action,
                        cash_snapshot=cash_snapshot,
                        transition=transition,
                    )
            exit_at = _aware(self._clock.now(), field_name="server liability clock")
            last_at = append_at if existing is None else entry_at
            if exit_at.astimezone(UTC) < last_at.astimezone(UTC):
                raise _blocked(
                    "server clock moved backwards before liability commit",
                    "TAX_LIABILITY_CLOCK_INVALID",
                )
            lease.assert_live(as_of=exit_at)

        return receipt


__all__ = [
    "CorporateActionTaxLiabilityUseCase",
    "CurrentTaxLiabilityScopeVerifierPort",
    "TaxLiabilityAppendDisposition",
    "TaxLiabilityAtomicUnitOfWorkPort",
    "TaxLiabilityAtomicWriterPort",
    "TaxLiabilityCurrentState",
    "TaxLiabilityEvidenceReference",
    "TaxLiabilityFinancialSnapshot",
    "TaxLiabilityWriteLease",
    "TaxLiabilityWriteReceipt",
]
