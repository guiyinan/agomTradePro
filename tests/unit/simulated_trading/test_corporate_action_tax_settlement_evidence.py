from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
    TaxLotOrigin,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    OwnershipAnchorKind,
    OwnershipEvidenceError,
    OwnershipOpeningAnchor,
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    QualifiedTaxSettlementHistory,
    RecordDateTaxEntitlementEvidence,
    RecordDateTaxEntitlementRuleKind,
    TaxSettlementDayEvidence,
)

_RECORD_DATE = date(2026, 4, 10)
_SOURCE_REVISION_ID = "synthetic-settlement-source:v1"


def _proof(
    *,
    quantity: Decimal = Decimal("80.000000"),
    account_id: int = 7,
    owner_user_id: int = 11,
) -> RecordDateOwnershipProof:
    return RecordDateOwnershipProof(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id="600000.SH",
        asset_code="600000.SH",
        record_date=_RECORD_DATE,
        ownership_snapshot_as_of_date=_RECORD_DATE,
        record_date_end_exclusive=datetime(2026, 4, 10, 16, tzinfo=UTC),
        exchange="SYNTHETIC",
        exchange_timezone_name="Asia/Shanghai",
        cutoff_policy_id="synthetic-close:v1",
        cutoff_policy_sha256="a" * 64,
        eligible_quantity=quantity,
        ownership_snapshot_id="synthetic-ownership-proof:v1",
        ownership_snapshot_sha256="b" * 64,
        ownership_snapshot_observed_at=datetime(2026, 4, 11, tzinfo=UTC),
    )


def _anchor(
    *,
    account_id: int = 7,
    owner_user_id: int = 11,
    quantity: Decimal = Decimal("0.000000"),
) -> OwnershipOpeningAnchor:
    return OwnershipOpeningAnchor(
        account_id=account_id,
        owner_user_id=owner_user_id,
        anchor_id="synthetic-zero-origin-anchor:v1",
        anchor_kind=OwnershipAnchorKind.ZERO_ORIGIN,
        quantity=quantity,
        effective_at=datetime(2026, 4, 1, tzinfo=UTC),
        observed_at=datetime(2026, 4, 1, tzinfo=UTC),
        evidence_sha256="c" * 64,
    )


def _entitlement(
    *,
    quantity: Decimal = Decimal("80.000000"),
) -> RecordDateTaxEntitlementEvidence:
    return RecordDateTaxEntitlementEvidence(
        kind=RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS,
        rule_source_id="synthetic-all-positions-rule:v1",
        rule_source_sha256="d" * 64,
        qualified_total_quantity=quantity,
        total_evidence_id="synthetic-entitlement-total:v1",
        total_evidence_sha256="e" * 64,
    )


def _day(
    settlement_date: date,
    opening: str,
    purchases: str,
    sales: str,
    closing: str,
    *,
    account_id: int = 7,
    owner_user_id: int = 11,
    security_id: str = "600000.SH",
    asset_code: str = "600000.SH",
    source_revision_id: str = _SOURCE_REVISION_ID,
    non_trade_delta: str = "0.000000",
) -> TaxSettlementDayEvidence:
    return TaxSettlementDayEvidence(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=security_id,
        asset_code=asset_code,
        settlement_date=settlement_date,
        opening_eod_quantity=Decimal(opening),
        gross_purchase_quantity=Decimal(purchases),
        gross_sale_quantity=Decimal(sales),
        non_trade_quantity_delta=Decimal(non_trade_delta),
        closing_eod_quantity=Decimal(closing),
        purchase_origin=TaxLotOrigin.PURCHASE,
        evidence_id=f"synthetic-eod:{settlement_date.isoformat()}",
        evidence_sha256=f"{settlement_date.day:02x}" * 32,
        source_revision_id=source_revision_id,
        source_revision_sha256="f" * 64,
    )


def _history(
    *,
    proof: RecordDateOwnershipProof | None = None,
    anchor: OwnershipOpeningAnchor | None = None,
    entitlement: RecordDateTaxEntitlementEvidence | None = None,
    days: tuple[TaxSettlementDayEvidence, ...] | None = None,
    session_dates: tuple[date, ...] | None = None,
) -> QualifiedTaxSettlementHistory:
    before = date(2026, 4, 8)
    prior = date(2026, 4, 9)
    after = date(2026, 4, 11)
    selected_days = (
        (
            _day(before, "0", "100", "0", "100"),
            _day(prior, "100", "0", "20", "80"),
            _day(_RECORD_DATE, "80", "0", "0", "80"),
            _day(after, "80", "0", "0", "80"),
        )
        if days is None
        else days
    )
    selected_sessions = (
        (before, prior, _RECORD_DATE, after) if session_dates is None else session_dates
    )
    return QualifiedTaxSettlementHistory(
        account_id=7,
        owner_user_id=11,
        security_id="600000.SH",
        asset_code="600000.SH",
        record_date=_RECORD_DATE,
        complete_through=after,
        record_date_ownership_proof=_proof() if proof is None else proof,
        opening_anchor=_anchor() if anchor is None else anchor,
        settlement_date_rule_id="synthetic-date-rule:v1",
        settlement_date_rule_sha256="1" * 64,
        settlement_calendar_id="synthetic-calendar:v1",
        settlement_calendar_sha256="2" * 64,
        source_revision_id=_SOURCE_REVISION_ID,
        source_revision_sha256="f" * 64,
        covered_session_dates=selected_sessions,
        settlement_days=selected_days,
        record_date_entitlement=_entitlement() if entitlement is None else entitlement,
    )


def test_history_binds_zero_anchor_all_covered_entitlement_and_zero_change_sessions() -> None:
    history = _history()

    assert history.covered_session_dates == tuple(
        day.settlement_date for day in history.settlement_days
    )
    assert history.settlement_days[-1].net_quantity_change == Decimal("0.000000")
    assert history.record_date_entitlement.kind is (
        RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS
    )


@pytest.mark.parametrize(
    "values",
    (
        {"account_id": True},
        {"owner_user_id": 0},
        {"security_id": " "},
        {"settlement_date": datetime(2026, 4, 8, tzinfo=UTC)},
        {"opening_eod_quantity": Decimal("0.0000001")},
        {"gross_purchase_quantity": Decimal("-1")},
        {"gross_sale_quantity": Decimal("NaN")},
        {"non_trade_quantity_delta": 1.0},
        {"non_trade_quantity_delta": Decimal("sNaN")},
        {"purchase_origin": "purchase"},
        {"closing_eod_quantity": 1.0},
        {"closing_eod_quantity": Decimal("1")},
        {"closing_eod_quantity": Decimal("1000000000000000000")},
        {"evidence_sha256": "A" * 64},
    ),
)
def test_settlement_day_rejects_wrong_types_and_unbounded_share_facts(
    values: dict[str, object],
) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(_day(date(2026, 4, 8), "0", "0", "0", "0"), **values)


def test_history_rejects_a_missing_zero_change_session_row() -> None:
    valid = _history()

    with pytest.raises(DeferredDividendTaxValidationError) as caught:
        replace(valid, settlement_days=valid.settlement_days[:2] + valid.settlement_days[3:])

    assert caught.value.code == "DEFERRED_DIVIDEND_TAX_HISTORY_INCOMPLETE"


def test_history_rejects_duplicate_or_unordered_sessions() -> None:
    valid = _history()
    duplicate = (
        valid.covered_session_dates[:2]
        + (valid.covered_session_dates[1],)
        + (valid.covered_session_dates[3],)
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, covered_session_dates=duplicate)
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, settlement_days=tuple(reversed(valid.settlement_days)))


def test_history_rejects_invalid_cutoff_types_and_unbound_nested_evidence() -> None:
    valid = _history()
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, complete_through=_RECORD_DATE)
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, record_date_ownership_proof=object())  # type: ignore[arg-type]
    naive_proof = replace(
        valid.record_date_ownership_proof,
        record_date_end_exclusive=datetime(2026, 4, 11),
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, record_date_ownership_proof=naive_proof)
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, opening_anchor=object())  # type: ignore[arg-type]
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, record_date_entitlement=object())  # type: ignore[arg-type]


def test_history_rejects_invalid_coverage_containers_and_session_values() -> None:
    valid = _history()
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, covered_session_dates=[])  # type: ignore[arg-type]
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(
            valid,
            covered_session_dates=(
                datetime(2026, 4, 8, tzinfo=UTC),
                *valid.covered_session_dates[1:],
            ),
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, settlement_days=[])  # type: ignore[arg-type]
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, settlement_days=(object(), *valid.settlement_days[1:]))  # type: ignore[arg-type]


def test_history_rejects_broken_daily_chain_and_record_date_total_mismatch() -> None:
    valid = _history()
    broken_chain_day = replace(
        valid.settlement_days[1],
        opening_eod_quantity=Decimal("90.000000"),
        closing_eod_quantity=Decimal("70.000000"),
    )
    with pytest.raises(DeferredDividendTaxValidationError) as chain:
        replace(
            valid,
            settlement_days=(
                valid.settlement_days[0],
                broken_chain_day,
                *valid.settlement_days[2:],
            ),
        )
    assert chain.value.code == "DEFERRED_DIVIDEND_TAX_HISTORY_INCOMPLETE"

    mismatched_proof = replace(
        valid.record_date_ownership_proof,
        eligible_quantity=Decimal("81.000000"),
    )
    mismatched_entitlement = replace(
        valid.record_date_entitlement,
        qualified_total_quantity=Decimal("81.000000"),
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(
            valid,
            record_date_ownership_proof=mismatched_proof,
            record_date_entitlement=mismatched_entitlement,
        )


@pytest.mark.parametrize(
    "change",
    (
        lambda history: replace(history, record_date_ownership_proof=_proof(account_id=8)),
        lambda history: replace(
            history, record_date_ownership_proof=_proof(quantity=Decimal("79"))
        ),
        lambda history: replace(
            history, record_date_entitlement=_entitlement(quantity=Decimal("79"))
        ),
        lambda history: replace(history, opening_anchor=_anchor(account_id=8)),
        lambda history: replace(
            history,
            settlement_days=(
                history.settlement_days[0],
                replace(history.settlement_days[1], owner_user_id=99),
                *history.settlement_days[2:],
            ),
        ),
        lambda history: replace(
            history,
            settlement_days=(
                history.settlement_days[0],
                replace(history.settlement_days[1], source_revision_id="changed-revision"),
                *history.settlement_days[2:],
            ),
        ),
    ),
)
def test_history_rejects_scope_anchor_entitlement_or_revision_mismatch(change: object) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        change(_history())  # type: ignore[operator]


@pytest.mark.parametrize("offset", (timedelta(0), timedelta(minutes=1)))
def test_history_rejects_zero_anchor_effective_at_or_after_record_date_cutoff(
    offset: timedelta,
) -> None:
    valid = _history()
    cutoff = valid.record_date_ownership_proof.record_date_end_exclusive
    effective_at = cutoff + offset

    with pytest.raises(DeferredDividendTaxValidationError):
        replace(
            valid,
            opening_anchor=replace(
                valid.opening_anchor,
                effective_at=effective_at,
                observed_at=effective_at + timedelta(minutes=1),
            ),
        )


def test_history_rejects_record_date_trade_and_nontrade_share_change() -> None:
    valid = _history()
    record_trade = replace(
        valid.settlement_days[2],
        gross_purchase_quantity=Decimal("1"),
        closing_eod_quantity=Decimal("81"),
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(
            valid,
            settlement_days=(*valid.settlement_days[:2], record_trade, *valid.settlement_days[3:]),
        )

    with pytest.raises(DeferredDividendTaxValidationError) as caught:
        replace(
            valid.settlement_days[0],
            non_trade_quantity_delta=Decimal("1"),
            closing_eod_quantity=Decimal("101"),
        )
    assert caught.value.code == "DEFERRED_DIVIDEND_TAX_UNSUPPORTED_ORIGIN"


def test_history_rejects_bad_revision_scope_and_calendar_identity() -> None:
    valid = _history()
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, source_revision_sha256="not-a-digest")
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, settlement_date_rule_id=" ")
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, settlement_calendar_id=" ")
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(valid, complete_through=date(2026, 4, 12))


def test_entitlement_rule_and_total_require_explicit_source_evidence() -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        RecordDateTaxEntitlementEvidence(
            kind="all_covered_positions",  # type: ignore[arg-type]
            rule_source_id="synthetic-rule",
            rule_source_sha256="d" * 64,
            qualified_total_quantity=Decimal("80"),
            total_evidence_id="synthetic-total",
            total_evidence_sha256="e" * 64,
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        RecordDateTaxEntitlementEvidence(
            kind=RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS,
            rule_source_id="synthetic-rule",
            rule_source_sha256="d" * 64,
            qualified_total_quantity=Decimal("80"),
            total_evidence_id="",
            total_evidence_sha256="e" * 64,
        )


def test_zero_origin_anchor_rejects_nonzero_quantity() -> None:
    with pytest.raises(OwnershipEvidenceError):
        _anchor(quantity=Decimal("1"))
