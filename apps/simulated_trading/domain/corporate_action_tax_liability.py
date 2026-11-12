"""Pure per-disposition liability recognition and cash-transition planning.

This module plans one simulated tax liability from an integrity-verified tax
assessment. It does not prove the assessment's sources, authorize a write, or
change an account balance. A trusted Application/repository must load the
current immutable state, revalidate owner scope and capability, and append any
returned transition with its Audit/Outbox facts atomically.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import NoReturn

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)

_ZERO = Decimal("0")
_PRECISION = 80
_MAX_SCALE = 12
_MAX_ADJUSTED_EXPONENT = 67


class TaxLiabilityStatus(StrEnum):
    """Current due-versus-collected status for one action disposition."""

    NO_TAX_DUE = "no_tax_due"
    OUTSTANDING = "outstanding"
    PARTIALLY_COLLECTED = "partially_collected"
    SETTLED = "settled"


class TaxLiabilityTransitionKind(StrEnum):
    """Assessment revision relationship to the prior state for this disposition."""

    INITIAL_RECOGNITION = "initial_recognition"
    EXACT_REPLAY = "exact_replay"
    SUCCESSOR_CORRECTION = "successor_correction"


class TaxLiabilityCashAction(StrEnum):
    """Explicit cash operation requested alongside liability planning."""

    COLLECT_AVAILABLE = "collect_available"
    REFUND_OVERCOLLECTION = "refund_overcollection"


def _fail(message: str, code: str = "CORPORATE_ACTION_TAX_LIABILITY_INVALID") -> NoReturn:
    """Raise the Domain's recognizable assessment validation error."""

    raise DeferredDividendTaxValidationError(message, code)


def _token(value: object, field_name: str, *, limit: int = 192) -> str:
    """Require a bounded, whitespace-free UTF-8 identity token."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(character.isspace() for character in value)
    ):
        _fail(f"{field_name} is not a valid identity token")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise DeferredDividendTaxValidationError(f"{field_name} is not valid UTF-8") from error
    return value


def _date(value: object, field_name: str) -> date:
    """Require an exact date value, excluding datetime subclasses."""

    if type(value) is not date:
        _fail(f"{field_name} must be an exact calendar date")
    return value


def _positive_id(value: object, field_name: str) -> int:
    """Require a positive exact integer identity."""

    if type(value) is not int or value <= 0:
        _fail(f"{field_name} must be a positive exact integer")
    return value


def _digest(value: object, field_name: str) -> str:
    """Require one exact lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _positive_quantum(value: object) -> Decimal:
    """Require the calculator's explicit power-of-ten currency quantum."""

    if type(value) is not Decimal or not value.is_finite() or value <= _ZERO:
        _fail("currency quantum must be a positive exact Decimal")
    sign, digits, exponent = value.as_tuple()
    if sign != 0 or digits != (1,) or type(exponent) is not int:
        _fail("currency quantum must be an explicit power of ten")
    if exponent > 0 or exponent < -_MAX_SCALE:
        _fail("currency quantum exceeds supported precision")
    return value


def _money(value: object, field_name: str, *, nonnegative: bool = True) -> Decimal:
    """Require finite money within the planner's exact Decimal capacity."""

    if type(value) is not Decimal or not value.is_finite():
        _fail(f"{field_name} must be an exact finite Decimal")
    sign, digits, exponent = value.as_tuple()
    if type(exponent) is not int or exponent < -_MAX_SCALE or len(digits) > _PRECISION:
        _fail(f"{field_name} exceeds supported Decimal scale or precision")
    if value != _ZERO and value.adjusted() > _MAX_ADJUSTED_EXPONENT:
        _fail(f"{field_name} exceeds supported Decimal magnitude")
    if nonnegative and value < _ZERO:
        _fail(f"{field_name} cannot be negative")
    return value


def _require_quantized(value: Decimal, quantum: Decimal, field_name: str) -> None:
    """Reject rather than round any amount outside the explicit currency unit."""

    # _money caps the magnitude and scale so this exact rescaling fits precision 80.
    with localcontext() as context:
        context.prec = _PRECISION
        quantized = value.quantize(quantum)
    if quantized != value:
        _fail(f"{field_name} is not an exact multiple of the selected currency quantum")


def _subtract(left: Decimal, right: Decimal) -> Decimal:
    """Subtract supported amounts independently of the caller's Decimal context."""

    with localcontext() as context:
        context.prec = _PRECISION
        return left - right


def _add(left: Decimal, right: Decimal) -> Decimal:
    """Add supported amounts independently of the caller's Decimal context."""

    with localcontext() as context:
        context.prec = _PRECISION
        return left + right


def _decimal_text(value: Decimal) -> str:
    """Encode a finite Decimal canonically without context-sensitive normalization."""

    sign, raw_digits, exponent = value.as_tuple()
    if type(exponent) is not int:
        _fail("liability amount must have a finite Decimal exponent")
    digits = list(raw_digits)
    if not any(digits):
        return "0"
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        text = coefficient + ("0" * exponent)
    else:
        places = -exponent
        split = len(coefficient) - places
        text = (
            f"{coefficient[:split]}.{coefficient[split:]}"
            if split > 0
            else f"0.{('0' * (-split))}{coefficient}"
        )
    return f"-{text}" if sign else text


def _hash_payload(payload: object) -> str:
    """Hash one canonical JSON object composed from validated Domain values."""

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise DeferredDividendTaxValidationError(
            "liability identity payload is not canonical"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class TaxLiabilityScope:
    """Logical identity of one dividend action and one sale settlement target.

    The source event must be an immutable logical event identity supplied by a
    trusted source qualifier. This DTO cannot detect a caller-created alias.
    """

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    corporate_action_id: str
    source_namespace: str
    logical_source_event_id: str
    target_disposition_id: str
    record_date: date
    target_settlement_date: date

    def __post_init__(self) -> None:
        """Validate the complete owner, action, and disposition scope."""

        _positive_id(self.account_id, "scope.account_id")
        _positive_id(self.owner_user_id, "scope.owner_user_id")
        for name, value, limit in (
            ("scope.security_id", self.security_id, 96),
            ("scope.asset_code", self.asset_code, 96),
            ("scope.corporate_action_id", self.corporate_action_id, 128),
            ("scope.source_namespace", self.source_namespace, 128),
            ("scope.logical_source_event_id", self.logical_source_event_id, 192),
            ("scope.target_disposition_id", self.target_disposition_id, 128),
        ):
            _token(value, name, limit=limit)
        _date(self.record_date, "scope.record_date")
        _date(self.target_settlement_date, "scope.target_settlement_date")
        if self.target_settlement_date <= self.record_date:
            _fail("target settlement must be after the dividend record date")


def _scope_payload(scope: TaxLiabilityScope) -> dict[str, object]:
    """Serialize every stable logical key for one disposition liability."""

    return {
        "account_id": scope.account_id,
        "owner_user_id": scope.owner_user_id,
        "security_id": scope.security_id,
        "asset_code": scope.asset_code,
        "corporate_action_id": scope.corporate_action_id,
        "source_namespace": scope.source_namespace,
        "logical_source_event_id": scope.logical_source_event_id,
        "target_disposition_id": scope.target_disposition_id,
        "record_date": scope.record_date.isoformat(),
        "target_settlement_date": scope.target_settlement_date.isoformat(),
    }


def _scope_for_assessment(
    assessment: CorporateActionTaxAssessment,
) -> TaxLiabilityScope:
    """Derive scope only from an integrity-verified assessment and its target."""

    assessment.verify_integrity()
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


@dataclass(frozen=True, slots=True)
class TaxLiabilityOperationIdentity:
    """Stable client intent shared by financial writes and historical verification.

    Mutable balances, observation clocks and renewed grant versions do not
    belong to this identity. The original stored assessment manifest does.
    A public request hash validates consistency and grants no permission.
    """

    operation_id: str
    scope: TaxLiabilityScope
    canonical_account_namespace: str
    canonical_account_id: str
    currency: SimulatedDividendTaxCurrency
    assessment_revision_id: str
    supersedes_assessment_revision_id: str | None
    assessment_semantic_sha256: str
    stored_assessment_manifest_sha256: str
    cash_action: TaxLiabilityCashAction | None
    request_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate exact intent and retain its context-independent wire seal."""
        if type(self.scope) is not TaxLiabilityScope:
            _fail("operation identity requires an exact disposition scope")
        self.scope.__post_init__()
        for name, value in (
            ("operation_id", self.operation_id),
            ("canonical_account_namespace", self.canonical_account_namespace),
            ("canonical_account_id", self.canonical_account_id),
            ("assessment_revision_id", self.assessment_revision_id),
        ):
            _token(value, name)
        if (
            self.canonical_account_namespace != "account"
            or type(self.currency) is not SimulatedDividendTaxCurrency
            or self.currency is not SimulatedDividendTaxCurrency.CNY
            or (
                self.cash_action is not None
                and type(self.cash_action) is not TaxLiabilityCashAction
            )
        ):
            _fail("operation identity has unsupported canonical currency or action scope")
        if self.supersedes_assessment_revision_id is not None:
            _token(self.supersedes_assessment_revision_id, "supersedes_assessment_revision_id")
            if self.supersedes_assessment_revision_id == self.assessment_revision_id:
                _fail("an operation assessment cannot supersede itself")
        _digest(self.assessment_semantic_sha256, "assessment_semantic_sha256")
        _digest(self.stored_assessment_manifest_sha256, "stored_assessment_manifest_sha256")
        object.__setattr__(self, "request_sha256", _hash_payload(self._payload()))

    def _payload(self) -> dict[str, object]:
        """Preserve the existing Application operation wire schema."""
        return {
            "schema": "simulated-corporate-action-tax-liability-operation.v1",
            "operation_id": self.operation_id,
            "scope": _scope_payload(self.scope),
            "canonical_account_namespace": self.canonical_account_namespace,
            "canonical_account_id": self.canonical_account_id,
            "currency": self.currency.value,
            "assessment_revision_id": self.assessment_revision_id,
            "assessment_supersedes_revision_id": self.supersedes_assessment_revision_id,
            "assessment_semantic_sha256": self.assessment_semantic_sha256,
            "stored_assessment_manifest_sha256": self.stored_assessment_manifest_sha256,
            "cash_action": None if self.cash_action is None else self.cash_action.value,
        }

    def verify_integrity(self) -> TaxLiabilityOperationIdentity:
        """Reject changed identity fields even if frozen-dataclass protection is bypassed."""
        rebuilt = TaxLiabilityOperationIdentity(
            operation_id=self.operation_id,
            scope=self.scope,
            canonical_account_namespace=self.canonical_account_namespace,
            canonical_account_id=self.canonical_account_id,
            currency=self.currency,
            assessment_revision_id=self.assessment_revision_id,
            supersedes_assessment_revision_id=self.supersedes_assessment_revision_id,
            assessment_semantic_sha256=self.assessment_semantic_sha256,
            stored_assessment_manifest_sha256=self.stored_assessment_manifest_sha256,
            cash_action=self.cash_action,
        )
        if rebuilt.request_sha256 != self.request_sha256:
            _fail("operation request hash differs from its immutable intent")
        return rebuilt

    def to_payload(self) -> dict[str, object]:
        """Return fresh wire facts after verifying the original cached request seal."""
        self.verify_integrity()
        return self._payload()


@dataclass(frozen=True, slots=True)
class TaxLiabilityCashRequest:
    """Explicit cash planning input; values must be freshly read by the caller."""

    action: TaxLiabilityCashAction
    book_cash: Decimal
    reserved_cash: Decimal

    def __post_init__(self) -> None:
        """Require a recognized cash operation and exact nonnegative balances."""

        if type(self.action) is not TaxLiabilityCashAction:
            _fail("cash action must be explicitly selected")
        _money(self.book_cash, "cash_request.book_cash")
        _money(self.reserved_cash, "cash_request.reserved_cash")


@dataclass(frozen=True, slots=True)
class CorporateActionTaxLiabilityState:
    """Latest immutable assessment and net collected amount for one disposition."""

    scope: TaxLiabilityScope
    assessment_revision_id: str
    supersedes_assessment_revision_id: str | None
    assessment_semantic_sha256: str
    currency_quantum: Decimal
    assessed_amount: Decimal
    net_collected_amount: Decimal
    state_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate current liability facts and seal their exact immutable identity."""

        if type(self.scope) is not TaxLiabilityScope:
            _fail("liability state requires an exact disposition scope")
        _token(self.assessment_revision_id, "assessment_revision_id")
        if self.supersedes_assessment_revision_id is not None:
            _token(self.supersedes_assessment_revision_id, "supersedes_assessment_revision_id")
            if self.supersedes_assessment_revision_id == self.assessment_revision_id:
                _fail("liability revision cannot supersede itself")
        _digest(self.assessment_semantic_sha256, "assessment_semantic_sha256")
        quantum = _positive_quantum(self.currency_quantum)
        assessed = _money(self.assessed_amount, "assessed_amount")
        collected = _money(self.net_collected_amount, "net_collected_amount")
        _require_quantized(assessed, quantum, "assessed_amount")
        _require_quantized(collected, quantum, "net_collected_amount")
        if collected > assessed:
            _fail("net collected tax cannot exceed the current assessment")
        object.__setattr__(self, "state_sha256", _hash_payload(self._payload()))

    @property
    def outstanding_amount(self) -> Decimal:
        """Return the exact unpaid portion of this one disposition's tax."""

        return _subtract(self.assessed_amount, self.net_collected_amount)

    @property
    def status(self) -> TaxLiabilityStatus:
        """Classify this disposition as unpaid, partial, settled, or zero-tax."""

        if self.assessed_amount == _ZERO:
            return TaxLiabilityStatus.NO_TAX_DUE
        if self.net_collected_amount == _ZERO:
            return TaxLiabilityStatus.OUTSTANDING
        if self.net_collected_amount < self.assessed_amount:
            return TaxLiabilityStatus.PARTIALLY_COLLECTED
        return TaxLiabilityStatus.SETTLED

    def _payload(self) -> dict[str, object]:
        """Build canonical facts used by the state seal."""

        return {
            "schema": "corporate-action-tax-liability-state.v1",
            "scope": _scope_payload(self.scope),
            "assessment_revision_id": self.assessment_revision_id,
            "supersedes_assessment_revision_id": self.supersedes_assessment_revision_id,
            "assessment_semantic_sha256": self.assessment_semantic_sha256,
            "currency_quantum": _decimal_text(self.currency_quantum),
            "assessed_amount": _decimal_text(self.assessed_amount),
            "net_collected_amount": _decimal_text(self.net_collected_amount),
        }

    def verify_integrity(self) -> CorporateActionTaxLiabilityState:
        """Recompute this payload seal before using state as a transition input."""

        rebuilt = CorporateActionTaxLiabilityState(
            scope=self.scope,
            assessment_revision_id=self.assessment_revision_id,
            supersedes_assessment_revision_id=self.supersedes_assessment_revision_id,
            assessment_semantic_sha256=self.assessment_semantic_sha256,
            currency_quantum=self.currency_quantum,
            assessed_amount=self.assessed_amount,
            net_collected_amount=self.net_collected_amount,
        )
        if rebuilt.state_sha256 != self.state_sha256:
            _fail("liability state hash does not match its current facts")
        return rebuilt


@dataclass(frozen=True, slots=True)
class CorporateActionTaxLiabilityTransition:
    """Deterministic before/after liability plan for one explicit request."""

    kind: TaxLiabilityTransitionKind
    before_state: CorporateActionTaxLiabilityState | None
    state_after: CorporateActionTaxLiabilityState
    cash_request: TaxLiabilityCashRequest | None
    tax_due_delta: Decimal
    collected_delta: Decimal
    outstanding_delta: Decimal
    cash_delta: Decimal
    transition_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate transition lineage, deltas, and exact cash-request effects."""

        if type(self.kind) is not TaxLiabilityTransitionKind:
            _fail("liability transition kind must be explicit")
        if type(self.state_after) is not CorporateActionTaxLiabilityState:
            _fail("liability transition requires a typed resulting state")
        self.state_after.verify_integrity()
        before = self.before_state
        if before is not None:
            if type(before) is not CorporateActionTaxLiabilityState:
                _fail("prior liability state is not typed")
            before.verify_integrity()
            if before.scope != self.state_after.scope:
                _fail("transition crosses liability scope", "CORPORATE_ACTION_TAX_LIABILITY_SCOPE")
            if before.currency_quantum != self.state_after.currency_quantum:
                _fail("currency quantum changed within one disposition liability")
        if self.kind is TaxLiabilityTransitionKind.INITIAL_RECOGNITION:
            if before is not None or self.state_after.supersedes_assessment_revision_id is not None:
                _fail("initial recognition cannot have a predecessor")
        elif self.kind is TaxLiabilityTransitionKind.EXACT_REPLAY:
            if (
                before is None
                or self.state_after.assessment_revision_id != before.assessment_revision_id
                or self.state_after.assessment_semantic_sha256 != before.assessment_semantic_sha256
                or self.state_after.supersedes_assessment_revision_id
                != before.supersedes_assessment_revision_id
            ):
                _fail("exact replay differs from its stored assessment revision")
        elif (
            before is None
            or self.state_after.assessment_revision_id == before.assessment_revision_id
            or self.state_after.supersedes_assessment_revision_id != before.assessment_revision_id
            or self.state_after.assessment_semantic_sha256 == before.assessment_semantic_sha256
        ):
            _fail("successor correction must extend the exact prior revision")

        quantum = self.state_after.currency_quantum
        due_before = _ZERO if before is None else before.assessed_amount
        collected_before = _ZERO if before is None else before.net_collected_amount
        outstanding_before = _ZERO if before is None else before.outstanding_amount
        expected_deltas = (
            _subtract(self.state_after.assessed_amount, due_before),
            _subtract(self.state_after.net_collected_amount, collected_before),
            _subtract(self.state_after.outstanding_amount, outstanding_before),
            _subtract(_ZERO, self.collected_delta),
        )
        actual_deltas = (
            self.tax_due_delta,
            self.collected_delta,
            self.outstanding_delta,
            self.cash_delta,
        )
        for name, value in zip(
            ("tax_due_delta", "collected_delta", "outstanding_delta", "cash_delta"),
            actual_deltas,
            strict=True,
        ):
            _money(value, name, nonnegative=False)
            _require_quantized(value, quantum, name)
        if actual_deltas != expected_deltas:
            _fail("liability transition deltas do not match its resulting state")
        self._verify_cash_effect(before=before)
        object.__setattr__(self, "transition_sha256", _hash_payload(self._payload()))

    def _verify_cash_effect(self, *, before: CorporateActionTaxLiabilityState | None) -> None:
        """Require exact, explicit collection or refund arithmetic."""

        request = self.cash_request
        collected_before = _ZERO if before is None else before.net_collected_amount
        if request is None:
            if self.collected_delta != _ZERO:
                _fail("cash movement requires an explicit cash request")
            if collected_before > self.state_after.assessed_amount:
                _fail("correction requires an explicit overcollection refund")
            return
        if type(request) is not TaxLiabilityCashRequest:
            _fail("cash request must use the exact typed contract")
        request.__post_init__()
        quantum = self.state_after.currency_quantum
        _require_quantized(request.book_cash, quantum, "cash_request.book_cash")
        _require_quantized(request.reserved_cash, quantum, "cash_request.reserved_cash")
        if request.reserved_cash > request.book_cash:
            _fail("reserved cash cannot exceed current book cash")
        if request.action is TaxLiabilityCashAction.COLLECT_AVAILABLE:
            if collected_before > self.state_after.assessed_amount:
                _fail("collection cannot replace a required overcollection refund")
            available = _subtract(request.book_cash, request.reserved_cash)
            requested_outstanding = _subtract(self.state_after.assessed_amount, collected_before)
            expected_collection = min(requested_outstanding, available)
            if self.collected_delta != expected_collection:
                _fail("collection delta exceeds available unreserved cash or current tax due")
            return
        excess = _subtract(collected_before, self.state_after.assessed_amount)
        if excess <= _ZERO or self.collected_delta != excess.copy_negate():
            _fail("refund must exactly remove tax collected above the corrected assessment")

    def _payload(self) -> dict[str, object]:
        """Build canonical identity over lineage, fresh cash input, and exact deltas."""

        before = self.before_state
        request = self.cash_request
        return {
            "schema": "corporate-action-tax-liability-transition.v1",
            "kind": self.kind.value,
            "before_state_sha256": None if before is None else before.state_sha256,
            "state_after_sha256": self.state_after.state_sha256,
            "cash_request": (
                None
                if request is None
                else {
                    "action": request.action.value,
                    "book_cash": _decimal_text(request.book_cash),
                    "reserved_cash": _decimal_text(request.reserved_cash),
                }
            ),
            "tax_due_delta": _decimal_text(self.tax_due_delta),
            "collected_delta": _decimal_text(self.collected_delta),
            "outstanding_delta": _decimal_text(self.outstanding_delta),
            "cash_delta": _decimal_text(self.cash_delta),
        }

    def verify_integrity(self) -> CorporateActionTaxLiabilityTransition:
        """Recompute the transition seal before handing the plan to Application."""

        rebuilt = CorporateActionTaxLiabilityTransition(
            kind=self.kind,
            before_state=self.before_state,
            state_after=self.state_after,
            cash_request=self.cash_request,
            tax_due_delta=self.tax_due_delta,
            collected_delta=self.collected_delta,
            outstanding_delta=self.outstanding_delta,
            cash_delta=self.cash_delta,
        )
        if rebuilt.transition_sha256 != self.transition_sha256:
            _fail("liability transition hash does not match its current facts")
        return rebuilt


def plan_corporate_action_tax_liability(
    assessment: CorporateActionTaxAssessment,
    *,
    prior_state: CorporateActionTaxLiabilityState | None,
    cash_request: TaxLiabilityCashRequest | None,
) -> CorporateActionTaxLiabilityTransition:
    """Plan one disposition's liability recognition and optional cash movement.

    A different sale settlement date is an independent liability and must be
    planned with its own prior state. A changed assessment revision must be an
    explicit semantic successor to the stored state. Source and logical event
    identity, current state, cash, ownership, and authority still require trusted
    adapters; this planner only verifies structural and arithmetic consistency.
    """

    if type(assessment) is not CorporateActionTaxAssessment:
        _fail("an exact corporate-action tax assessment is required")
    assessment.verify_integrity()
    scope = _scope_for_assessment(assessment)
    quantum = _positive_quantum(assessment.policy.currency_quantum)
    assessed_amount = _money(
        assessment.calculation.withholding_amount,
        "assessment.withholding_amount",
    )
    _require_quantized(assessed_amount, quantum, "assessment.withholding_amount")

    before = prior_state
    if before is not None:
        if type(before) is not CorporateActionTaxLiabilityState:
            _fail("prior liability state must be the exact typed state")
        before.verify_integrity()
        if before.scope != scope:
            _fail(
                "prior state belongs to another action or sale",
                "CORPORATE_ACTION_TAX_LIABILITY_SCOPE",
            )
        if before.currency_quantum != quantum:
            _fail("currency quantum changed within one disposition liability")
        if assessment.assessment_revision_id == before.assessment_revision_id:
            if (
                assessment.semantic_sha256 != before.assessment_semantic_sha256
                or assessment.calculation.withholding_amount != before.assessed_amount
                or assessment.supersedes_assessment_revision_id
                != before.supersedes_assessment_revision_id
            ):
                _fail("same assessment revision was reused for changed facts")
            kind = TaxLiabilityTransitionKind.EXACT_REPLAY
        else:
            if (
                assessment.supersedes_assessment_revision_id != before.assessment_revision_id
                or assessment.semantic_sha256 == before.assessment_semantic_sha256
            ):
                _fail(
                    "correction must be a changed semantic successor of the exact current revision"
                )
            kind = TaxLiabilityTransitionKind.SUCCESSOR_CORRECTION
    else:
        if assessment.supersedes_assessment_revision_id is not None:
            _fail("a successor assessment requires its exact prior liability state")
        kind = TaxLiabilityTransitionKind.INITIAL_RECOGNITION

    previous_collected = _ZERO if before is None else before.net_collected_amount
    resulting_collected = previous_collected
    requested_cash = cash_request
    if requested_cash is not None:
        if type(requested_cash) is not TaxLiabilityCashRequest:
            _fail("cash request must use the exact typed contract")
        requested_cash.__post_init__()
        _require_quantized(requested_cash.book_cash, quantum, "cash_request.book_cash")
        _require_quantized(requested_cash.reserved_cash, quantum, "cash_request.reserved_cash")
        if requested_cash.reserved_cash > requested_cash.book_cash:
            _fail("reserved cash cannot exceed current book cash")
        if requested_cash.action is TaxLiabilityCashAction.COLLECT_AVAILABLE:
            if previous_collected > assessed_amount:
                _fail("correction requires an explicit overcollection refund")
            available = _subtract(requested_cash.book_cash, requested_cash.reserved_cash)
            outstanding = _subtract(assessed_amount, previous_collected)
            resulting_collected = _add(previous_collected, min(outstanding, available))
        elif requested_cash.action is TaxLiabilityCashAction.REFUND_OVERCOLLECTION:
            if previous_collected <= assessed_amount:
                _fail("no overcollection exists to refund")
            resulting_collected = assessed_amount
    elif previous_collected > assessed_amount:
        _fail("correction requires an explicit overcollection refund")

    after = CorporateActionTaxLiabilityState(
        scope=scope,
        assessment_revision_id=assessment.assessment_revision_id,
        supersedes_assessment_revision_id=assessment.supersedes_assessment_revision_id,
        assessment_semantic_sha256=assessment.semantic_sha256,
        currency_quantum=quantum,
        assessed_amount=assessed_amount,
        net_collected_amount=resulting_collected,
    )
    due_before = _ZERO if before is None else before.assessed_amount
    outstanding_before = _ZERO if before is None else before.outstanding_amount
    collected_delta = _subtract(after.net_collected_amount, previous_collected)
    return CorporateActionTaxLiabilityTransition(
        kind=kind,
        before_state=before,
        state_after=after,
        cash_request=requested_cash,
        tax_due_delta=_subtract(after.assessed_amount, due_before),
        collected_delta=collected_delta,
        outstanding_delta=_subtract(after.outstanding_amount, outstanding_before),
        cash_delta=_subtract(_ZERO, collected_delta),
    )


__all__ = [
    "CorporateActionTaxLiabilityState",
    "CorporateActionTaxLiabilityTransition",
    "TaxLiabilityCashAction",
    "TaxLiabilityCashRequest",
    "TaxLiabilityOperationIdentity",
    "TaxLiabilityScope",
    "TaxLiabilityStatus",
    "TaxLiabilityTransitionKind",
    "plan_corporate_action_tax_liability",
]
