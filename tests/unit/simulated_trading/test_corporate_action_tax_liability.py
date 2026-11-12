from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime
from decimal import ROUND_FLOOR, Decimal, localcontext

import pytest

from apps.simulated_trading.domain import corporate_action_tax_liability as liability_domain
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
    TaxLotOrigin,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    CorporateActionTaxLiabilityState,
    CorporateActionTaxLiabilityTransition,
    TaxLiabilityCashAction,
    TaxLiabilityCashRequest,
    TaxLiabilityStatus,
    TaxLiabilityTransitionKind,
    plan_corporate_action_tax_liability,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    TaxSettlementDayEvidence,
)
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import _assessment


def _taxable_assessment(
    *,
    revision_id: str = "liability-assessment-v1",
    supersedes: str | None = None,
    dividend_per_share: Decimal = Decimal("0.50"),
    action_revision_id: str | None = None,
) -> CorporateActionTaxAssessment:
    """Build an explicitly synthetic assessment with an exact positive tax amount."""

    base = _assessment()
    policy = replace(
        base.policy,
        bands=tuple(
            replace(
                band,
                taxable_dividend_ratio=Decimal("1"),
                withholding_rate=Decimal("0.2"),
            )
            for band in base.policy.bands
        ),
    )
    selected_action_revision = (
        f"synthetic-action-{revision_id}" if action_revision_id is None else action_revision_id
    )
    revision_bytes = selected_action_revision.encode("utf-8")
    action = replace(
        base.action,
        source_revision_id=selected_action_revision,
        source_revision_sha256=hashlib.sha256(revision_bytes).hexdigest(),
        source_payload_sha256=hashlib.sha256(revision_bytes + b"-payload").hexdigest(),
        dividend_per_share=dividend_per_share,
    )
    return replace(
        base,
        assessment_revision_id=revision_id,
        supersedes_assessment_revision_id=supersedes,
        action=action,
        policy=policy,
    )


def _cash_request(
    action: TaxLiabilityCashAction,
    *,
    book_cash: Decimal = Decimal("100.00"),
    reserved_cash: Decimal = Decimal("0.00"),
) -> TaxLiabilityCashRequest:
    """Build fresh cash evidence for one explicitly selected settlement action."""

    return TaxLiabilityCashRequest(
        action=action,
        book_cash=book_cash,
        reserved_cash=reserved_cash,
    )


def _later_sale_assessment(
    assessment: CorporateActionTaxAssessment,
) -> CorporateActionTaxAssessment:
    """Extend the synthetic complete history with one independent later net sale."""

    history = assessment.history
    later_date = date(2025, 3, 4)
    later_day = TaxSettlementDayEvidence(
        account_id=history.account_id,
        owner_user_id=history.owner_user_id,
        security_id=history.security_id,
        asset_code=history.asset_code,
        settlement_date=later_date,
        opening_eod_quantity=Decimal("60.000000"),
        gross_purchase_quantity=Decimal("0.000000"),
        gross_sale_quantity=Decimal("10.000000"),
        non_trade_quantity_delta=Decimal("0.000000"),
        closing_eod_quantity=Decimal("50.000000"),
        purchase_origin=TaxLotOrigin.PURCHASE,
        evidence_id="synthetic-liability-later-sale-day",
        evidence_sha256="a" * 64,
        source_revision_id=history.source_revision_id,
        source_revision_sha256=history.source_revision_sha256,
    )
    extended_history = replace(
        history,
        complete_through=later_date,
        covered_session_dates=history.covered_session_dates + (later_date,),
        settlement_days=history.settlement_days + (later_day,),
    )
    return replace(
        assessment,
        assessment_revision_id="liability-later-sale-v1",
        supersedes_assessment_revision_id=None,
        history=extended_history,
        target_settlement_date=later_date,
    )


def test_first_assessment_recognizes_disposition_liability_without_collecting() -> None:
    assessment = _taxable_assessment()

    plan = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )

    assert assessment.calculation.withholding_amount == Decimal("1.00")
    assert plan.kind is TaxLiabilityTransitionKind.INITIAL_RECOGNITION
    assert plan.state_after.assessed_amount == Decimal("1.00")
    assert plan.state_after.net_collected_amount == Decimal("0.00")
    assert plan.state_after.status is TaxLiabilityStatus.OUTSTANDING
    assert plan.tax_due_delta == Decimal("1.00")
    assert plan.collected_delta == Decimal("0.00")
    assert plan.outstanding_delta == Decimal("1.00")
    assert plan.cash_delta == Decimal("0.00")
    assert plan.state_after.scope.target_settlement_date == assessment.target_settlement_date


def test_collection_is_capped_by_fresh_unreserved_cash_and_liability() -> None:
    assessment = _taxable_assessment()

    plan = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=_cash_request(
            TaxLiabilityCashAction.COLLECT_AVAILABLE,
            book_cash=Decimal("0.75"),
            reserved_cash=Decimal("0.25"),
        ),
    )

    assert plan.collected_delta == Decimal("0.50")
    assert plan.cash_delta == Decimal("-0.50")
    assert plan.outstanding_delta == Decimal("0.50")
    assert plan.state_after.status is TaxLiabilityStatus.PARTIALLY_COLLECTED


def test_collection_never_exceeds_the_assessed_disposition_amount() -> None:
    assessment = _taxable_assessment()

    plan = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=_cash_request(
            TaxLiabilityCashAction.COLLECT_AVAILABLE,
            book_cash=Decimal("100.00"),
        ),
    )

    assert plan.collected_delta == assessment.calculation.withholding_amount
    assert plan.state_after.net_collected_amount == assessment.calculation.withholding_amount
    assert plan.state_after.status is TaxLiabilityStatus.SETTLED


def test_exact_revision_replay_is_stable_and_does_not_duplicate_collection() -> None:
    assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )

    replay = plan_corporate_action_tax_liability(
        assessment,
        prior_state=initial.state_after,
        cash_request=None,
    )
    replay_again = plan_corporate_action_tax_liability(
        assessment,
        prior_state=initial.state_after,
        cash_request=None,
    )

    assert replay.kind is TaxLiabilityTransitionKind.EXACT_REPLAY
    assert replay.tax_due_delta == Decimal("0")
    assert replay.collected_delta == Decimal("0")
    assert replay.state_after == initial.state_after
    assert replay.transition_sha256 == replay_again.transition_sha256


def test_exact_assessment_replay_can_plan_a_separate_cash_recovery() -> None:
    assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )

    recovery = plan_corporate_action_tax_liability(
        assessment,
        prior_state=initial.state_after,
        cash_request=_cash_request(
            TaxLiabilityCashAction.COLLECT_AVAILABLE,
            book_cash=Decimal("0.75"),
            reserved_cash=Decimal("0.25"),
        ),
    )

    assert recovery.kind is TaxLiabilityTransitionKind.EXACT_REPLAY
    assert recovery.collected_delta == Decimal("0.50")
    assert recovery.state_after.net_collected_amount == Decimal("0.50")


def test_successor_correction_changes_only_this_disposition_and_keeps_collection() -> None:
    initial_assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        initial_assessment,
        prior_state=None,
        cash_request=_cash_request(TaxLiabilityCashAction.COLLECT_AVAILABLE),
    )
    corrected = _taxable_assessment(
        revision_id="liability-assessment-v2",
        supersedes=initial_assessment.assessment_revision_id,
        dividend_per_share=Decimal("0.75"),
    )

    correction = plan_corporate_action_tax_liability(
        corrected,
        prior_state=initial.state_after,
        cash_request=None,
    )

    assert correction.kind is TaxLiabilityTransitionKind.SUCCESSOR_CORRECTION
    assert correction.tax_due_delta == Decimal("0.50")
    assert correction.collected_delta == Decimal("0.00")
    assert correction.state_after.net_collected_amount == Decimal("1.00")
    assert correction.state_after.assessed_amount == Decimal("1.50")
    assert correction.outstanding_delta == Decimal("0.50")


def test_reducing_tax_below_collected_amount_requires_explicit_refund() -> None:
    initial_assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        initial_assessment,
        prior_state=None,
        cash_request=_cash_request(TaxLiabilityCashAction.COLLECT_AVAILABLE),
    )
    corrected = _taxable_assessment(
        revision_id="liability-assessment-v2",
        supersedes=initial_assessment.assessment_revision_id,
        dividend_per_share=Decimal("0.25"),
    )

    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            corrected,
            prior_state=initial.state_after,
            cash_request=None,
        )

    refund = plan_corporate_action_tax_liability(
        corrected,
        prior_state=initial.state_after,
        cash_request=_cash_request(
            TaxLiabilityCashAction.REFUND_OVERCOLLECTION,
            book_cash=Decimal("99.00"),
            reserved_cash=Decimal("50.00"),
        ),
    )

    assert refund.tax_due_delta == Decimal("-0.50")
    assert refund.collected_delta == Decimal("-0.50")
    assert refund.cash_delta == Decimal("0.50")
    assert refund.state_after.net_collected_amount == Decimal("0.50")
    assert refund.state_after.status is TaxLiabilityStatus.SETTLED


def test_new_sale_target_has_independent_liability_and_rejects_foreign_target_state() -> None:
    first_assessment = _taxable_assessment()
    first = plan_corporate_action_tax_liability(
        first_assessment,
        prior_state=None,
        cash_request=None,
    )
    later_assessment = _later_sale_assessment(first_assessment)

    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            later_assessment,
            prior_state=first.state_after,
            cash_request=None,
        )

    later = plan_corporate_action_tax_liability(
        later_assessment,
        prior_state=None,
        cash_request=None,
    )
    assert later.kind is TaxLiabilityTransitionKind.INITIAL_RECOGNITION
    assert (
        later.state_after.scope.target_settlement_date
        != first.state_after.scope.target_settlement_date
    )
    assert later.state_after.assessed_amount == later_assessment.calculation.withholding_amount


def test_successor_requires_exact_predecessor_and_changed_semantic_facts() -> None:
    assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )
    wrong_predecessor = _taxable_assessment(
        revision_id="liability-assessment-v2",
        supersedes="another-revision",
        dividend_per_share=Decimal("0.25"),
    )
    unchanged_successor = _taxable_assessment(
        revision_id="liability-assessment-v2",
        supersedes=assessment.assessment_revision_id,
        action_revision_id="synthetic-action-liability-assessment-v1",
    )

    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            wrong_predecessor,
            prior_state=initial.state_after,
            cash_request=None,
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            unchanged_successor,
            prior_state=initial.state_after,
            cash_request=None,
        )


def test_cross_account_prior_state_is_rejected_even_with_valid_hash() -> None:
    assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )
    foreign_state = replace(
        initial.state_after,
        scope=replace(
            initial.state_after.scope, account_id=initial.state_after.scope.account_id + 1
        ),
    )

    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            assessment,
            prior_state=foreign_state,
            cash_request=None,
        )


def test_liability_arithmetic_and_transition_hash_ignore_decimal_context() -> None:
    initial_assessment = _taxable_assessment(dividend_per_share=Decimal("50.00"))
    initial = plan_corporate_action_tax_liability(
        initial_assessment,
        prior_state=None,
        cash_request=_cash_request(TaxLiabilityCashAction.COLLECT_AVAILABLE),
    )
    corrected = _taxable_assessment(
        revision_id="liability-assessment-v2",
        supersedes=initial_assessment.assessment_revision_id,
        dividend_per_share=Decimal("49.995"),
    )

    with localcontext() as context:
        context.prec = 2
        correction = plan_corporate_action_tax_liability(
            corrected,
            prior_state=initial.state_after,
            cash_request=_cash_request(
                TaxLiabilityCashAction.REFUND_OVERCOLLECTION,
                book_cash=Decimal("100.00"),
                reserved_cash=Decimal("90.00"),
            ),
        )

    assert correction.state_after.assessed_amount == Decimal("99.99")
    assert correction.cash_delta == Decimal("0.01")
    assert correction.collected_delta == Decimal("-0.01")
    assert correction.transition_sha256


def test_multi_digit_refund_is_exact_under_low_precision_decimal_context() -> None:
    initial_assessment = _taxable_assessment(dividend_per_share=Decimal("50.00"))
    initial = plan_corporate_action_tax_liability(
        initial_assessment,
        prior_state=None,
        cash_request=_cash_request(TaxLiabilityCashAction.COLLECT_AVAILABLE),
    )
    corrected = _taxable_assessment(
        revision_id="liability-assessment-v2",
        supersedes=initial_assessment.assessment_revision_id,
        dividend_per_share=Decimal("43.83"),
    )

    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_FLOOR
        refund = plan_corporate_action_tax_liability(
            corrected,
            prior_state=initial.state_after,
            cash_request=_cash_request(
                TaxLiabilityCashAction.REFUND_OVERCOLLECTION,
                book_cash=Decimal("100.00"),
                reserved_cash=Decimal("0.00"),
            ),
        )

    assert refund.tax_due_delta == Decimal("-12.34")
    assert refund.collected_delta == Decimal("-12.34")
    assert refund.cash_delta == Decimal("12.34")


def test_exact_replay_rejects_changed_currency_quantum_in_direct_constructor() -> None:
    state = plan_corporate_action_tax_liability(
        _taxable_assessment(),
        prior_state=None,
        cash_request=None,
    ).state_after
    changed_quantum = CorporateActionTaxLiabilityState(
        scope=state.scope,
        assessment_revision_id=state.assessment_revision_id,
        supersedes_assessment_revision_id=state.supersedes_assessment_revision_id,
        assessment_semantic_sha256=state.assessment_semantic_sha256,
        currency_quantum=Decimal("0.001"),
        assessed_amount=state.assessed_amount,
        net_collected_amount=state.net_collected_amount,
    )

    with pytest.raises(DeferredDividendTaxValidationError):
        CorporateActionTaxLiabilityTransition(
            kind=TaxLiabilityTransitionKind.EXACT_REPLAY,
            before_state=state,
            state_after=changed_quantum,
            cash_request=None,
            tax_due_delta=Decimal("0"),
            collected_delta=Decimal("0"),
            outstanding_delta=Decimal("0"),
            cash_delta=Decimal("0"),
        )


@pytest.mark.parametrize(
    ("book_cash", "reserved_cash"),
    [
        (Decimal("NaN"), Decimal("0.00")),
        (Decimal("1.001"), Decimal("0.00")),
        (Decimal("1.00"), Decimal("1.01")),
        (1.0, Decimal("0.00")),
        (Decimal("1.00"), True),
    ],
)
def test_invalid_or_inconsistent_cash_inputs_are_rejected(
    book_cash: object,
    reserved_cash: object,
) -> None:
    assessment = _taxable_assessment()
    with pytest.raises(DeferredDividendTaxValidationError):
        request = TaxLiabilityCashRequest(
            action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
            book_cash=book_cash,  # type: ignore[arg-type]
            reserved_cash=reserved_cash,  # type: ignore[arg-type]
        )
        plan_corporate_action_tax_liability(
            assessment,
            prior_state=None,
            cash_request=request,
        )


def test_zero_tax_is_explicit_no_liability_and_refund_cannot_create_cash() -> None:
    zero_tax = _taxable_assessment(dividend_per_share=Decimal("0"))
    plan = plan_corporate_action_tax_liability(
        zero_tax,
        prior_state=None,
        cash_request=None,
    )
    assert plan.state_after.status is TaxLiabilityStatus.NO_TAX_DUE

    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            zero_tax,
            prior_state=None,
            cash_request=_cash_request(TaxLiabilityCashAction.REFUND_OVERCOLLECTION),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": True},
        {"owner_user_id": -1},
        {"security_id": ""},
        {"security_id": "not a token"},
        {"security_id": "x" * 97},
        {"logical_source_event_id": "\ud800"},
        {"record_date": datetime(2025, 2, 28)},
        {"target_settlement_date": date(2025, 2, 28)},
    ],
)
def test_scope_rejects_malformed_identity_and_date(changes: dict[str, object]) -> None:
    state = plan_corporate_action_tax_liability(
        _taxable_assessment(),
        prior_state=None,
        cash_request=None,
    ).state_after

    with pytest.raises(DeferredDividendTaxValidationError):
        replace(state.scope, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"assessment_revision_id": "bad token"},
        {"assessment_revision_id": "\ud800"},
        {"supersedes_assessment_revision_id": "liability-assessment-v1"},
        {"assessment_semantic_sha256": "G" * 64},
        {"currency_quantum": Decimal("0")},
        {"currency_quantum": Decimal("0.010")},
        {"currency_quantum": Decimal("1e-13")},
        {"assessed_amount": Decimal("NaN")},
        {"assessed_amount": Decimal("-0.01")},
        {"assessed_amount": Decimal("1.001")},
        {"assessed_amount": Decimal("1e-13")},
        {"assessed_amount": Decimal("1e68")},
        {"assessed_amount": Decimal("1" + ("0" * 80))},
        {"net_collected_amount": Decimal("1.01")},
    ],
)
def test_state_rejects_malformed_seal_and_money(changes: dict[str, object]) -> None:
    state = plan_corporate_action_tax_liability(
        _taxable_assessment(),
        prior_state=None,
        cash_request=None,
    ).state_after

    with pytest.raises(DeferredDividendTaxValidationError):
        replace(state, **changes)


def test_mutated_prior_state_and_mutated_plan_fail_seal_reverification() -> None:
    assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )
    object.__setattr__(initial.state_after, "net_collected_amount", Decimal("0.01"))

    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            assessment,
            prior_state=initial.state_after,
            cash_request=None,
        )

    clean = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )
    object.__setattr__(clean, "cash_delta", Decimal("0.01"))
    with pytest.raises(DeferredDividendTaxValidationError):
        clean.verify_integrity()


def test_liability_dtos_reject_unknown_types_and_inconsistent_transitions() -> None:
    assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )
    replay = plan_corporate_action_tax_liability(
        assessment,
        prior_state=initial.state_after,
        cash_request=None,
    )
    corrected = _taxable_assessment(
        revision_id="liability-assessment-v2",
        supersedes=assessment.assessment_revision_id,
        dividend_per_share=Decimal("0.25"),
    )
    correction = plan_corporate_action_tax_liability(
        corrected,
        prior_state=initial.state_after,
        cash_request=None,
    )

    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(None, prior_state=None, cash_request=None)  # type: ignore[arg-type]
    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(assessment, prior_state=object(), cash_request=None)  # type: ignore[arg-type]
    with pytest.raises(DeferredDividendTaxValidationError):
        TaxLiabilityCashRequest("collect_available", Decimal("1"), Decimal("0"))  # type: ignore[arg-type]
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(initial, kind="initial_recognition")  # type: ignore[arg-type]
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(initial, tax_due_delta=Decimal("0.99"))
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(replay, kind=TaxLiabilityTransitionKind.INITIAL_RECOGNITION)
    with pytest.raises(DeferredDividendTaxValidationError):
        CorporateActionTaxLiabilityTransition(
            kind=TaxLiabilityTransitionKind.EXACT_REPLAY,
            before_state=initial.state_after,
            state_after=correction.state_after,
            cash_request=None,
            tax_due_delta=Decimal("-0.50"),
            collected_delta=Decimal("0"),
            outstanding_delta=Decimal("-0.50"),
            cash_delta=Decimal("0"),
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(correction, cash_request=None, cash_delta=Decimal("0.01"))


def test_cash_request_rejects_reserved_balance_above_book_balance() -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            _taxable_assessment(),
            prior_state=None,
            cash_request=_cash_request(
                TaxLiabilityCashAction.COLLECT_AVAILABLE,
                book_cash=Decimal("0.50"),
                reserved_cash=Decimal("0.75"),
            ),
        )


def test_liability_constructor_rejects_untyped_scope_and_state_facts() -> None:
    state = plan_corporate_action_tax_liability(
        _taxable_assessment(),
        prior_state=None,
        cash_request=None,
    ).state_after
    with pytest.raises(DeferredDividendTaxValidationError):
        CorporateActionTaxLiabilityState(
            scope=object(),  # type: ignore[arg-type]
            assessment_revision_id=state.assessment_revision_id,
            supersedes_assessment_revision_id=None,
            assessment_semantic_sha256=state.assessment_semantic_sha256,
            currency_quantum=state.currency_quantum,
            assessed_amount=state.assessed_amount,
            net_collected_amount=state.net_collected_amount,
        )


def test_transition_constructor_rejects_untyped_and_cross_scope_states() -> None:
    assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )
    replay = plan_corporate_action_tax_liability(
        assessment,
        prior_state=initial.state_after,
        cash_request=None,
    )
    foreign_state = replace(
        initial.state_after,
        scope=replace(
            initial.state_after.scope, owner_user_id=initial.state_after.scope.owner_user_id + 1
        ),
    )

    with pytest.raises(DeferredDividendTaxValidationError):
        CorporateActionTaxLiabilityTransition(
            kind=initial.kind,
            before_state=None,
            state_after=object(),  # type: ignore[arg-type]
            cash_request=None,
            tax_due_delta=initial.tax_due_delta,
            collected_delta=initial.collected_delta,
            outstanding_delta=initial.outstanding_delta,
            cash_delta=initial.cash_delta,
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        CorporateActionTaxLiabilityTransition(
            kind=TaxLiabilityTransitionKind.EXACT_REPLAY,
            before_state=object(),  # type: ignore[arg-type]
            state_after=initial.state_after,
            cash_request=None,
            tax_due_delta=Decimal("0"),
            collected_delta=Decimal("0"),
            outstanding_delta=Decimal("0"),
            cash_delta=Decimal("0"),
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(replay, before_state=foreign_state)
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(initial, kind=TaxLiabilityTransitionKind.SUCCESSOR_CORRECTION)


def test_transition_constructor_rejects_inconsistent_collection_and_refund_facts() -> None:
    assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )
    partially_collected_state = CorporateActionTaxLiabilityState(
        scope=initial.state_after.scope,
        assessment_revision_id=initial.state_after.assessment_revision_id,
        supersedes_assessment_revision_id=None,
        assessment_semantic_sha256=initial.state_after.assessment_semantic_sha256,
        currency_quantum=initial.state_after.currency_quantum,
        assessed_amount=initial.state_after.assessed_amount,
        net_collected_amount=Decimal("0.50"),
    )
    paid = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=_cash_request(TaxLiabilityCashAction.COLLECT_AVAILABLE),
    )
    corrected = _taxable_assessment(
        revision_id="liability-assessment-v2",
        supersedes=assessment.assessment_revision_id,
        dividend_per_share=Decimal("0.25"),
    )
    refunded = plan_corporate_action_tax_liability(
        corrected,
        prior_state=paid.state_after,
        cash_request=_cash_request(TaxLiabilityCashAction.REFUND_OVERCOLLECTION),
    )

    with pytest.raises(DeferredDividendTaxValidationError):
        CorporateActionTaxLiabilityTransition(
            kind=initial.kind,
            before_state=None,
            state_after=partially_collected_state,
            cash_request=None,
            tax_due_delta=Decimal("1.00"),
            collected_delta=Decimal("0.50"),
            outstanding_delta=Decimal("0.50"),
            cash_delta=Decimal("-0.50"),
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(initial, cash_request=object())  # type: ignore[arg-type]
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(
            initial,
            cash_request=_cash_request(
                TaxLiabilityCashAction.COLLECT_AVAILABLE,
                book_cash=Decimal("0.50"),
                reserved_cash=Decimal("0.75"),
            ),
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(
            initial,
            state_after=partially_collected_state,
            cash_request=_cash_request(
                TaxLiabilityCashAction.COLLECT_AVAILABLE,
                book_cash=Decimal("0.25"),
            ),
            collected_delta=Decimal("0.50"),
            outstanding_delta=Decimal("0.50"),
            cash_delta=Decimal("-0.50"),
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(
            initial,
            cash_request=_cash_request(TaxLiabilityCashAction.REFUND_OVERCOLLECTION),
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        CorporateActionTaxLiabilityTransition(
            kind=TaxLiabilityTransitionKind.SUCCESSOR_CORRECTION,
            before_state=paid.state_after,
            state_after=refunded.state_after,
            cash_request=_cash_request(TaxLiabilityCashAction.COLLECT_AVAILABLE),
            tax_due_delta=Decimal("-0.50"),
            collected_delta=Decimal("-0.50"),
            outstanding_delta=Decimal("0"),
            cash_delta=Decimal("0.50"),
        )


def test_planner_rejects_revision_currency_and_cash_contract_conflicts() -> None:
    assessment = _taxable_assessment()
    initial = plan_corporate_action_tax_liability(
        assessment,
        prior_state=None,
        cash_request=None,
    )
    changed_same_revision = _taxable_assessment(
        revision_id=assessment.assessment_revision_id,
        dividend_per_share=Decimal("0.25"),
    )
    successor_without_state = _taxable_assessment(
        revision_id="liability-assessment-v2",
        supersedes=assessment.assessment_revision_id,
        dividend_per_share=Decimal("0.25"),
    )
    different_quantum = replace(
        successor_without_state,
        policy=replace(successor_without_state.policy, currency_quantum=Decimal("0.1")),
    )

    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            changed_same_revision,
            prior_state=initial.state_after,
            cash_request=None,
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            successor_without_state,
            prior_state=None,
            cash_request=None,
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            different_quantum,
            prior_state=initial.state_after,
            cash_request=None,
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        plan_corporate_action_tax_liability(
            assessment,
            prior_state=None,
            cash_request=object(),  # type: ignore[arg-type]
        )


def test_canonical_json_seal_rejects_non_json_domain_payload() -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        liability_domain._hash_payload({"unsupported": object()})
