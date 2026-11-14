"""Synthetic current-model contracts never authenticate a real holder."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.simulated_trading.application.corporate_action_share_tax_model import (
    CurrentShareCapitalTaxModel,
    ShareCapitalTaxModelQuery,
    ShareCapitalTaxSourceReference,
)
from apps.simulated_trading.domain.corporate_action_capital_tax_terms import (
    CapitalTaxSourceClause,
    CapitalTaxSourceClauseKind,
    CapitalTaxSourceDocumentId,
    CapitalTaxSourceOrigin,
    CapitalTaxSourcePageStatus,
    ParsedCapitalTaxSourceDocument,
    combine_share_capital_tax_source_terms,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
    SimulatedDividendTaxExchange,
    SimulatedDividendTaxInstrumentKind,
    SimulatedDividendTaxPersona,
)
from core.exceptions import BusinessLogicError

_NOW = datetime(2026, 11, 14, 4, 0, tzinfo=UTC)


def _source_document(
    document_id: CapitalTaxSourceDocumentId,
) -> ParsedCapitalTaxSourceDocument:
    """Build explicit synthetic source terms for DTO validation."""
    if document_id is CapitalTaxSourceDocumentId.SAT_1997_198:
        title = "国家税务总局关于股份制企业转增股本和派发红股征免个人所得税的通知"
        legal_number = "国税发〔1997〕198号"
        body_sha256 = "a" * 64
        kinds = (
            CapitalTaxSourceClauseKind.BACKGROUND_CONTEXT,
            CapitalTaxSourceClauseKind.CAPITAL_RESERVE_TRANSFER_PERSONAL_TREATMENT,
            CapitalTaxSourceClauseKind.SURPLUS_RESERVE_STOCK_BONUS_PERSONAL_TREATMENT,
            CapitalTaxSourceClauseKind.WITHHOLDING_ADMINISTRATION,
        )
    else:
        title = "国家税务总局关于原城市信用社在转制为城市合作银行过程中个人股增值所得应纳个人所得税的批复"
        legal_number = "国税函〔1998〕289号"
        body_sha256 = "b" * 64
        kinds = (
            CapitalTaxSourceClauseKind.RESPONSE_CONTEXT,
            CapitalTaxSourceClauseKind.REQUEST_CONTEXT,
            CapitalTaxSourceClauseKind.ASSET_VALUATION_INCOME_TREATMENT,
            CapitalTaxSourceClauseKind.CAPITAL_RESERVE_SOURCE_RESTRICTION,
        )
    clauses = tuple(
        CapitalTaxSourceClause(
            kind=kind,
            normalized_text=f"合成条款 {index}",
            source_body_sha256=body_sha256,
        )
        for index, kind in enumerate(kinds)
    )
    return ParsedCapitalTaxSourceDocument(
        document_id=document_id,
        title=title,
        legal_number=legal_number,
        issuer="国家税务总局",
        source_page_status=CapitalTaxSourcePageStatus.FULL_TEXT_EFFECTIVE,
        document_date=(
            date(1997, 12, 25)
            if document_id is CapitalTaxSourceDocumentId.SAT_1997_198
            else date(1998, 5, 15)
        ),
        body_sha256=body_sha256,
        clauses=clauses,
    )


def _terms() -> object:
    """Return the explicitly paired synthetic source terms."""
    return combine_share_capital_tax_source_terms(
        source_1997_198=_source_document(CapitalTaxSourceDocumentId.SAT_1997_198),
        source_1998_289=_source_document(CapitalTaxSourceDocumentId.SAT_1998_289),
    )


def _query() -> ShareCapitalTaxModelQuery:
    """Build one fully bound explicit simulated scenario query."""
    return ShareCapitalTaxModelQuery(
        account_kind="simulated",
        physical_account_id=17,
        canonical_account_id="sim-account-17",
        owner_user_id=29,
        security_id="000001.SZ",
        asset_code="000001.SZ",
        exchange=SimulatedDividendTaxExchange.SZ,
        persona=SimulatedDividendTaxPersona.DOMESTIC_PUBLIC_MARKET_A_SHARE,
        instrument_kind=SimulatedDividendTaxInstrumentKind.LISTED_EQUITY,
        currency=SimulatedDividendTaxCurrency.CNY,
        source_namespace="exchange_official_disclosure",
        source_record_id="notice-17",
        source_event_id="event-17",
        source_revision_id="revision-2",
        source_revision_sha256="c" * 64,
        source_payload_sha256="d" * 64,
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_DELIVERY,
        entry_kind=CorporateActionEntryKind.POSTING,
        capital_source=CapitalTaxSourceOrigin.STOCK_ISSUE_PREMIUM_CAPITAL_RESERVE,
        record_date=date(2026, 10, 30),
        effective_date=date(2026, 11, 2),
        stage_date=date(2026, 11, 10),
        source_observed_at=_NOW - timedelta(days=2),
    )


def _source_reference(
    document_id: CapitalTaxSourceDocumentId,
) -> ShareCapitalTaxSourceReference:
    """Build one synthetic retained source reference paired to its parser result."""
    is_1997 = document_id is CapitalTaxSourceDocumentId.SAT_1997_198
    return ShareCapitalTaxSourceReference(
        document_id=document_id,
        issuer="国家税务总局",
        source_version="synthetic-v1",
        source_revision_sha256=("e" if is_1997 else "f") * 64,
        body_sha256=("a" if is_1997 else "b") * 64,
        capture_id=f"capture-{document_id.value}",
        captured_at=_NOW - timedelta(days=30 if is_1997 else 20),
    )


def _model(query: ShareCapitalTaxModelQuery | None = None) -> CurrentShareCapitalTaxModel:
    """Build one synthetic finite model result without a legal eligibility claim."""
    selected_query = query or _query()
    return CurrentShareCapitalTaxModel(
        query_semantic_sha256=selected_query.semantic_sha256,
        persona=selected_query.persona,
        capital_source=selected_query.capital_source,
        source_terms=_terms(),
        source_1997_198=_source_reference(CapitalTaxSourceDocumentId.SAT_1997_198),
        source_1998_289=_source_reference(CapitalTaxSourceDocumentId.SAT_1998_289),
        model_rule_id="synthetic-capital-tax-model-v1",
        model_rule_sha256="1" * 64,
        runtime_profile_id="synthetic-profile-1",
        runtime_profile_content_sha256="2" * 64,
        runtime_snapshot_id="synthetic-snapshot-1",
        runtime_snapshot_sha256="3" * 64,
        known_at=_NOW - timedelta(hours=2),
        valid_from=_NOW - timedelta(days=1),
        valid_until=_NOW + timedelta(days=1),
        checked_at=_NOW - timedelta(minutes=1),
    )


def test_explicit_synthetic_model_verifies_exact_query_and_never_claims_real_tax_status() -> None:
    query = _query()
    model = _model(query)

    model.verify_for(query, as_of=_NOW)
    assert model.simulation_only is True
    assert model.must_not_use_for_real_tax_decision is True
    assert model.source_1997_198.body_sha256 == "a" * 64
    assert model.source_1998_289.body_sha256 == "b" * 64
    assert not hasattr(model, "eligible")
    assert not hasattr(model, "tax_exempt")


@pytest.mark.parametrize(
    "change",
    [
        {"source_event_id": "different-event"},
        {"source_revision_id": "different-revision"},
        {"source_revision_sha256": "9" * 64},
        {"source_payload_sha256": "8" * 64},
        {"record_date": date(2026, 10, 31)},
        {"effective_date": date(2026, 11, 3)},
        {"stage_date": date(2026, 11, 11)},
    ],
)
def test_model_cannot_be_reused_for_different_source_or_stage_facts(
    change: dict[str, object],
) -> None:
    query = _query()
    model = _model(query)
    with pytest.raises(BusinessLogicError):
        model.verify_for(replace(query, **change), as_of=_NOW)


@pytest.mark.parametrize(
    "change",
    [
        {"action_kind": CorporateActionKind.CASH_DIVIDEND},
        {"stage": CorporateActionStage.CASH_PAYMENT},
        {"stage": CorporateActionStage.RIGHTS_NOT_EXERCISED},
        {"source_namespace": "synthetic-disclosure"},
        {"persona": None},
    ],
)
def test_query_rejects_non_share_or_implicit_model_scenarios(change: dict[str, object]) -> None:
    with pytest.raises(BusinessLogicError):
        replace(_query(), **change)


@pytest.mark.parametrize(
    "as_of",
    [
        _NOW - timedelta(days=2),
        _NOW + timedelta(days=2),
    ],
)
def test_model_rejects_before_known_or_expired_cutoff(as_of: datetime) -> None:
    query = _query()
    with pytest.raises(BusinessLogicError):
        _model(query).verify_for(query, as_of=as_of)


def test_source_reference_must_match_exact_parser_body_and_ordered_clocks() -> None:
    query = _query()
    model = _model(query)
    with pytest.raises(BusinessLogicError):
        replace(model, source_1997_198=replace(model.source_1997_198, body_sha256="7" * 64))
    with pytest.raises(BusinessLogicError):
        replace(
            model,
            source_1998_289=replace(model.source_1998_289, captured_at=_NOW + timedelta(days=1)),
        )


def test_model_check_clock_cannot_predate_selected_source_observation() -> None:
    query = replace(_query(), source_observed_at=_NOW + timedelta(minutes=1))
    model = _model(query)

    with pytest.raises(BusinessLogicError):
        model.verify_for(query, as_of=_NOW + timedelta(minutes=2))


def test_non_stock_premium_origin_is_bound_as_a_distinct_model_input() -> None:
    query = replace(_query(), capital_source=CapitalTaxSourceOrigin.OTHER_CAPITAL_RESERVE)
    model = _model(query)

    model.verify_for(query, as_of=_NOW)
    with pytest.raises(BusinessLogicError):
        model.verify_for(_query(), as_of=_NOW)


def test_model_checked_in_the_future_cannot_qualify_an_earlier_cutoff() -> None:
    query = _query()
    with pytest.raises(BusinessLogicError):
        replace(_model(query), checked_at=_NOW + timedelta(minutes=1)).verify_for(query, as_of=_NOW)


def test_current_model_cannot_be_checked_before_its_explicit_valid_from() -> None:
    with pytest.raises(BusinessLogicError):
        replace(_model(), valid_from=_NOW + timedelta(minutes=1))


def test_combined_model_knowledge_cannot_predate_a_retained_original_source_capture() -> None:
    with pytest.raises(BusinessLogicError):
        replace(
            _model(),
            source_1998_289=replace(
                _model().source_1998_289, captured_at=_NOW - timedelta(hours=1)
            ),
        )


@pytest.mark.parametrize("name", ["source_record_id", "canonical_account_id", "source_revision_id"])
def test_model_tokens_reject_control_characters(name: str) -> None:
    with pytest.raises(BusinessLogicError):
        replace(_query(), **{name: "invalid\x00token"})


def test_current_model_knowledge_includes_the_selected_source_observation() -> None:
    query = replace(_query(), source_observed_at=_NOW - timedelta(hours=1))
    with pytest.raises(BusinessLogicError):
        _model(query).verify_for(query, as_of=_NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"exchange": SimulatedDividendTaxExchange.SH},
        {"asset_code": "AAPL.US", "security_id": "AAPL.US"},
    ],
)
def test_model_query_requires_consistent_canonical_a_share_exchange(
    changes: dict[str, object],
) -> None:
    with pytest.raises(BusinessLogicError):
        replace(_query(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"physical_account_id": 18},
        {"owner_user_id": 30},
        {"canonical_account_id": "another-account"},
    ],
)
def test_current_model_cannot_be_reused_for_another_owner_account(
    changes: dict[str, object],
) -> None:
    with pytest.raises(BusinessLogicError):
        _model().verify_for(replace(_query(), **changes), as_of=_NOW)
