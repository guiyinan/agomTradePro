"""Application arithmetic over real typed current and retained price proofs.

The source-response facts are the explicit synthetic fixtures already used by
the raw mark and retained-source contract suites. Every proof is built by its
actual typed reader; these tests do not create owner or financial authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.data_center.application.retained_historical_price_source import (
    RetainedHistoricalPriceEvidence,
)
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.simulated_trading.application.corporate_action_nav_mark import (
    SimulatedCorporateActionNavRawMarkPolicyBinding,
    SimulatedCorporateActionNavRawMarkProof,
)
from apps.simulated_trading.application.corporate_action_reference_return import (
    CorporateActionReferenceReturnInputs,
    CorporateActionReferenceReturnReport,
    build_corporate_action_reference_return,
)
from apps.simulated_trading.domain.corporate_action_performance_projection import (
    RestatementEntitlement,
)
from core.exceptions import BusinessLogicError
from tests.unit.data_center import test_published_price_source as price_fixtures
from tests.unit.data_center import test_retained_historical_price_source as retained_fixtures
from tests.unit.simulated_trading import test_corporate_action_nav_mark_reader as mark_fixtures
from tests.unit.simulated_trading import (
    test_published_price_initial_position_mark_reader as mark_source_fixtures,
)


def _current_mark() -> SimulatedCorporateActionNavRawMarkProof:
    """Build a current proof with the same explicit M1 key as retained prices."""

    def binding(as_of: datetime) -> SimulatedCorporateActionNavRawMarkPolicyBinding:
        if type(as_of) is not datetime:
            raise AssertionError("raw mark policy request did not provide a datetime")
        original = mark_fixtures._binding(as_of)
        policy = replace(
            original.policy,
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        )
        return replace(original, policy=policy)

    target_date = mark_fixtures._AS_OF.date() - timedelta(days=1)
    base_price = replace(
        mark_source_fixtures._source_evidence(trade_date=target_date),
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    )
    price_reader = mark_fixtures._PriceReader(
        transform=lambda cutoff: replace(base_price, knowledge_cutoff=cutoff)
    )
    reader, _dependencies = mark_fixtures._reader(
        policy_reader=mark_fixtures._PolicyReader(transform=binding),
        price_reader=price_reader,
    )
    proof = reader.read_current_mark(mark_fixtures._query())
    if type(proof) is not SimulatedCorporateActionNavRawMarkProof:
        raise AssertionError("typed current raw-mark fixture did not qualify")
    return proof


def _retained_price(
    monkeypatch: pytest.MonkeyPatch,
    *,
    trade_date: date,
    publication_id: str,
    knowledge_cutoff: datetime,
) -> RetainedHistoricalPriceEvidence:
    """Read one exact retained publication through the real typed source use case."""
    if type(knowledge_cutoff) is not datetime:
        raise AssertionError("historical fixture cutoff is not an aware datetime")
    # The shared fixture's default response bytes encode 20261026 literally.
    # Build a new synthetic capture with the requested exact date, then let the
    # real retainer, manifest and reader verify its newly computed original hash.
    capture_type = price_fixtures.ProviderResponseCapture

    def capture_for_session(**values: Any) -> price_fixtures.ProviderResponseCapture:
        body = values["body"]
        assert type(body) is bytes
        body = body.replace(b"20261026", trade_date.strftime("%Y%m%d").encode("ascii"))
        values.update(
            body=body,
            payload=price_fixtures.parse_provider_response_json(body),
            body_sha256=hashlib.sha256(body).hexdigest(),
            body_size_bytes=len(body),
        )
        return capture_type(**values)

    with monkeypatch.context() as source:
        source.setattr(price_fixtures, "TRADE_DATE", trade_date)
        source.setattr(price_fixtures, "PUBLICATION_ID", publication_id)
        source.setattr(price_fixtures, "ProviderResponseCapture", capture_for_session)
        fixture = retained_fixtures._fixture()
        fixture.cutoff = knowledge_cutoff
        result, _repository, _activation = retained_fixtures._read(fixture)
    if type(result.evidence) is not RetainedHistoricalPriceEvidence:
        raise AssertionError(
            f"typed retained historical source fixture did not qualify: {result.blocked_reason}"
        )
    return result.evidence


def _inputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cash: Decimal,
    shares: Decimal,
) -> CorporateActionReferenceReturnInputs:
    """Bind one current mark and two exact retained sessions to a synthetic event."""
    mark = _current_mark()
    cutoff = mark.checked_at
    opening_days = tuple(
        row.calendar_date
        for row in mark.calendar.snapshot.days
        if row.is_open and row.calendar_date < mark.trade_date
    )
    if not opening_days:
        raise AssertionError("current typed calendar fixture lacks a pre-ex session")
    record_date = max(opening_days)
    action = RestatementEntitlement(
        action_id="synthetic-logical-event-600000",
        asset_code=mark.query.asset_code,
        effective_on=mark.trade_date,
        gross_cash=cash,
        gross_shares=shares,
        known_at=cutoff - timedelta(seconds=1),
        cash_transfers=(),
        share_transfers=(),
    )
    opening = _retained_price(
        monkeypatch,
        trade_date=record_date,
        publication_id="11111111-1111-4111-8111-111111111111",
        knowledge_cutoff=cutoff,
    )
    closing = _retained_price(
        monkeypatch,
        trade_date=mark.trade_date,
        publication_id="22222222-2222-4222-8222-222222222222",
        knowledge_cutoff=cutoff,
    )
    return CorporateActionReferenceReturnInputs(
        record_date=record_date,
        reference_quantity=Decimal("70.000000"),
        entitlement=action,
        current_mark=mark,
        opening_source=opening,
        closing_source=closing,
        currency_quantum=Decimal("0.01"),
        quantity_quantum=Decimal("0.000001"),
        knowledge_cutoff=cutoff,
        source_scope_valid_until=mark.valid_until,
    )


def _report(inputs: CorporateActionReferenceReturnInputs) -> CorporateActionReferenceReturnReport:
    """Run the pure Application builder over its independently typed evidence."""
    result = build_corporate_action_reference_return(inputs)
    if type(result) is not CorporateActionReferenceReturnReport:
        raise AssertionError("reference-return Application returned an untyped report")
    return result


def test_cash_reference_return_uses_current_mark_and_retained_raw_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Count the exact current gross dividend once without account-return claims."""
    inputs = _inputs(monkeypatch, cash=Decimal("14.00"), shares=Decimal("0"))

    result = _report(inputs)

    assert result.record_date == inputs.record_date
    assert result.opening_source.price.trade_date < result.closing_source.price.trade_date
    assert result.opening_source.price.values.close == Decimal("12.5")
    assert result.comparison.opening.total_value == Decimal("875.00000000")
    assert result.comparison.closing.dividend_receivable == Decimal("14.00")
    assert result.comparison.closing.total_value == Decimal("889.00000000")
    assert result.comparison.wealth_change == Decimal("14.00000000")
    assert result.opening_source.price.source_observed_at is None
    assert result.closing_source.price.source_observed_at is None
    assert result.must_not_use_for_decision is True
    assert result.return_basis == "gross_unreinvested_record_date_holding"


def test_share_reference_return_counts_unreleased_shares_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Represent source shares as a receivable until an original transfer exists."""
    inputs = _inputs(monkeypatch, cash=Decimal("0"), shares=Decimal("7.000000"))

    result = _report(inputs)

    assert result.comparison.opening.total_value == Decimal("875.00000000")
    assert result.comparison.closing.share_receivable == Decimal("7.000000")
    assert result.comparison.closing.total_value == Decimal("962.50000000")
    assert result.comparison.wealth_change == Decimal("87.50000000")
    assert result.must_not_use_for_decision is True


def test_reference_return_rejects_a_price_selected_for_the_wrong_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed price proof for another date cannot fill a missing bracket member."""
    inputs = _inputs(monkeypatch, cash=Decimal("14.00"), shares=Decimal("0"))
    wrong_opening = replace(inputs, opening_source=inputs.closing_source)

    with pytest.raises(BusinessLogicError) as blocked:
        build_corporate_action_reference_return(wrong_opening)

    assert blocked.value.code == "REFERENCE_RETURN_RAW_PRICE_SCOPE_INVALID"


def test_reference_return_rejects_a_retained_source_from_another_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Original historical evidence keeps its selected cutoff; it is not retimed."""
    inputs = _inputs(monkeypatch, cash=Decimal("14.00"), shares=Decimal("0"))
    future_source = replace(
        inputs.opening_source,
        knowledge_cutoff=inputs.knowledge_cutoff + timedelta(seconds=1),
    )
    changed = replace(inputs, opening_source=future_source)

    with pytest.raises(BusinessLogicError) as blocked:
        build_corporate_action_reference_return(changed)

    assert blocked.value.code == "REFERENCE_RETURN_RAW_PRICE_SCOPE_INVALID"
