"""Pure interpreted-term validation and exact policy reconciliation."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

import pytest

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_statutory_tax_terms import (
    ParsedStatutoryDividendTaxTerms,
    StatutoryDividendTaxClause,
)
from apps.simulated_trading.domain.corporate_action_statutory_tax_terms import (
    StatutoryDividendTaxClausePurpose as Purpose,
)
from tests.unit.simulated_trading.test_statutory_dividend_tax_parser import _policy

MECHANICS = {Purpose.HOLDING_DATE_SCOPE, Purpose.FIFO, Purpose.DAILY_NET, Purpose.NATURAL_CALENDAR}


def _terms() -> ParsedStatutoryDividendTaxTerms:
    return ParsedStatutoryDividendTaxTerms(
        1,
        12,
        Decimal("0.5"),
        Decimal("0.2"),
        date(2015, 9, 8),
        tuple(
            StatutoryDividendTaxClause(
                p, ("b" if p in MECHANICS else "a") * 64, f"Synthetic {p.value} clause"
            )
            for p in Purpose
        ),
    )


def test_complete_terms_are_canonical_and_independent_of_ambient_precision() -> None:
    first = _terms()
    with localcontext() as context:
        context.prec = 2
        second = replace(
            first,
            clauses=tuple(reversed(first.clauses)),
            middle_taxable_ratio=Decimal("0.500"),
            withholding_rate=Decimal("0.20"),
        )
        assert first.terms_sha256 == second.terms_sha256
        second.validate_policy(_policy())
    assert len(first.terms_sha256) == 64
    assert first.clauses[0].purpose.value == sorted(p.value for p in Purpose)[0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("short_maximum_months", True),
        ("short_maximum_months", 0),
        ("short_maximum_months", 12),
        ("middle_maximum_months", 119988),
        ("middle_maximum_months", False),
        ("record_date_exclusive_boundary", datetime(2015, 9, 8, tzinfo=UTC)),
        ("middle_taxable_ratio", 0.5),
        ("middle_taxable_ratio", Decimal("sNaN")),
        ("middle_taxable_ratio", Decimal("-0.1")),
        ("middle_taxable_ratio", Decimal("1.1")),
        ("middle_taxable_ratio", Decimal("0.1234567890123")),
        ("withholding_rate", Decimal("NaN")),
    ],
)
def test_invalid_terms_fail_before_hashing(field: str, value: object) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(_terms(), **{field: value})


@pytest.mark.parametrize(
    "variant", ["list", "untyped", "missing", "duplicate", "mixed_rate", "same_source"]
)
def test_incomplete_or_crossed_clause_provenance_is_rejected(variant: str) -> None:
    terms = _terms()
    clauses = terms.clauses
    if variant == "list":
        changed = list(clauses)
    elif variant == "untyped":
        changed = (object(),)
    elif variant == "missing":
        changed = clauses[:-1]
    elif variant == "duplicate":
        changed = clauses + (clauses[0],)
    elif variant == "mixed_rate":
        changed = tuple(
            replace(c, source_revision_sha256="c" * 64) if c.purpose is Purpose.HOLDING_BANDS else c
            for c in clauses
        )
    else:
        changed = tuple(replace(c, source_revision_sha256="a" * 64) for c in clauses)
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(terms, clauses=changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("purpose", "fifo"),
        ("source_revision_sha256", "bad"),
        ("normalized_text", ""),
        ("normalized_text", " leading"),
        ("normalized_text", "bad\x00text"),
        ("normalized_text", "bad\x7ftext"),
        ("normalized_text", "x" * 16001),
        ("normalized_text", "\ud800"),
    ],
)
def test_invalid_clause_cannot_become_source_evidence(field: str, value: object) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(_terms().clauses[0], **{field: value})


def test_changed_actual_clause_changes_terms_hash() -> None:
    first = _terms()
    changed = replace(first.clauses[0], normalized_text="Changed synthetic source clause")
    assert replace(first, clauses=(changed,) + first.clauses[1:]).terms_sha256 != first.terms_sha256


def test_whole_unit_ratios_have_canonical_text_and_valid_digest() -> None:
    assert (
        len(
            replace(
                _terms(), middle_taxable_ratio=Decimal("1"), withholding_rate=Decimal("0")
            ).terms_sha256
        )
        == 64
    )


def test_unknown_policy_type_is_rejected() -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        _terms().validate_policy(object())


@pytest.mark.parametrize("change", ["boundary", "bands", "threshold", "ratio", "rate"])
def test_explicit_policy_must_reconcile_every_source_numeric_term(change: str) -> None:
    policy = _policy()
    if change == "boundary":
        policy = replace(policy, effective_from=date(2015, 9, 8))
    elif change == "bands":
        policy = replace(policy, bands=(policy.bands[0], policy.bands[2]))
    else:
        first = policy.bands[0]
        if change == "threshold":
            first = replace(first, maximum_holding_months=2)
        elif change == "ratio":
            first = replace(first, taxable_dividend_ratio=Decimal("0.9"))
        else:
            first = replace(first, withholding_rate=Decimal("0.02"))
        policy = replace(policy, bands=(first,) + policy.bands[1:])
    with pytest.raises(DeferredDividendTaxValidationError):
        _terms().validate_policy(policy)
