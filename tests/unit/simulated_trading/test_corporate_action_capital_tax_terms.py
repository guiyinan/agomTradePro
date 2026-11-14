"""Synthetic clauses test source-text classification, not legal applicability."""

from dataclasses import replace
from datetime import date

import pytest

from apps.simulated_trading.domain.corporate_action_capital_tax_terms import (
    CapitalTaxSourceClause,
    CapitalTaxSourceClauseKind,
    CapitalTaxSourceDocumentId,
    CapitalTaxSourcePageStatus,
    CapitalTaxTermsValidationError,
    ParsedCapitalTaxSourceDocument,
    combine_share_capital_tax_source_terms,
)

_TITLE_1997 = "国家税务总局关于股份制企业转增股本和派发红股征免个人所得税的通知"
_TITLE_1998 = (
    "国家税务总局关于原城市信用社在转制为城市合作银行过程中个人股增值所得应纳个人所得税的批复"
)


def _document(document_id: CapitalTaxSourceDocumentId) -> ParsedCapitalTaxSourceDocument:
    """Build a small explicit synthetic source document for Domain checks."""
    if document_id is CapitalTaxSourceDocumentId.SAT_1997_198:
        title = _TITLE_1997
        number = "国税发〔1997〕198号"
        body_sha256 = "a" * 64
        kinds = (
            CapitalTaxSourceClauseKind.BACKGROUND_CONTEXT,
            CapitalTaxSourceClauseKind.CAPITAL_RESERVE_TRANSFER_PERSONAL_TREATMENT,
            CapitalTaxSourceClauseKind.SURPLUS_RESERVE_STOCK_BONUS_PERSONAL_TREATMENT,
            CapitalTaxSourceClauseKind.WITHHOLDING_ADMINISTRATION,
        )
    else:
        title = _TITLE_1998
        number = "国税函〔1998〕289号"
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
        legal_number=number,
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


def test_exact_pair_retains_all_source_clauses_and_stable_hash() -> None:
    terms = combine_share_capital_tax_source_terms(
        source_1997_198=_document(CapitalTaxSourceDocumentId.SAT_1997_198),
        source_1998_289=_document(CapitalTaxSourceDocumentId.SAT_1998_289),
    )

    assert terms.source_1997_198.body_sha256 == "a" * 64
    assert terms.source_1998_289.body_sha256 == "b" * 64
    assert len(terms.clauses) == 8
    assert (
        terms.terms_sha256
        == combine_share_capital_tax_source_terms(
            source_1997_198=_document(CapitalTaxSourceDocumentId.SAT_1997_198),
            source_1998_289=_document(CapitalTaxSourceDocumentId.SAT_1998_289),
        ).terms_sha256
    )
    assert not hasattr(terms, "effective_from")
    assert not hasattr(terms, "eligible")


def test_source_documents_cannot_be_swapped_or_reused() -> None:
    first = _document(CapitalTaxSourceDocumentId.SAT_1997_198)
    second = _document(CapitalTaxSourceDocumentId.SAT_1998_289)
    with pytest.raises(CapitalTaxTermsValidationError):
        combine_share_capital_tax_source_terms(
            source_1997_198=second,
            source_1998_289=first,
        )
    with pytest.raises(CapitalTaxTermsValidationError):
        combine_share_capital_tax_source_terms(
            source_1997_198=first,
            source_1998_289=replace(second, body_sha256=first.body_sha256),
        )


def test_required_source_clause_cannot_be_omitted_or_duplicated() -> None:
    first = _document(CapitalTaxSourceDocumentId.SAT_1997_198)
    second = _document(CapitalTaxSourceDocumentId.SAT_1998_289)
    with pytest.raises(CapitalTaxTermsValidationError):
        combine_share_capital_tax_source_terms(
            source_1997_198=replace(first, clauses=first.clauses[:-1]),
            source_1998_289=second,
        )
    with pytest.raises(CapitalTaxTermsValidationError):
        replace(first, clauses=first.clauses + (first.clauses[-1],))


def test_document_clause_hash_must_bind_to_exact_body() -> None:
    first = _document(CapitalTaxSourceDocumentId.SAT_1997_198)
    altered = replace(
        first.clauses[1],
        source_body_sha256="c" * 64,
    )
    with pytest.raises(CapitalTaxTermsValidationError):
        replace(first, clauses=(first.clauses[0], altered, *first.clauses[2:]))


@pytest.mark.parametrize(
    "bad_text",
    [None, "", " leading", "trailing ", "control\x01", "x" * 12001, "\ud800"],
)
def test_source_clause_rejects_invalid_text_without_normalizing_it(bad_text: object) -> None:
    with pytest.raises(CapitalTaxTermsValidationError):
        CapitalTaxSourceClause(
            kind=CapitalTaxSourceClauseKind.BACKGROUND_CONTEXT,
            normalized_text=bad_text,
            source_body_sha256="a" * 64,
        )


@pytest.mark.parametrize("bad_digest", [None, "a" * 63, "A" * 64])
def test_source_clause_requires_lowercase_exact_body_digest(bad_digest: object) -> None:
    with pytest.raises(CapitalTaxTermsValidationError):
        CapitalTaxSourceClause(
            kind=CapitalTaxSourceClauseKind.BACKGROUND_CONTEXT,
            normalized_text="合成原文",
            source_body_sha256=bad_digest,
        )


def test_source_clause_rejects_unknown_kind() -> None:
    with pytest.raises(CapitalTaxTermsValidationError):
        CapitalTaxSourceClause(
            kind="unknown",
            normalized_text="合成原文",
            source_body_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"document_id": "unknown"},
        {"title": "另一个标题"},
        {"legal_number": "其他文号"},
        {"issuer": "其他机关"},
        {"source_page_status": "全文有效"},
        {"document_date": date(1997, 12, 26)},
        {"body_sha256": "A" * 64},
        {"clauses": []},
        {"clauses": ("not-a-clause",)},
    ],
)
def test_source_document_rejects_invalid_identity_metadata_or_clause_container(
    changes: dict[str, object],
) -> None:
    with pytest.raises(CapitalTaxTermsValidationError):
        replace(_document(CapitalTaxSourceDocumentId.SAT_1997_198), **changes)


def test_source_document_rejects_reordered_paragraphs_and_body_mismatch() -> None:
    document = _document(CapitalTaxSourceDocumentId.SAT_1997_198)
    with pytest.raises(CapitalTaxTermsValidationError):
        replace(document, clauses=(document.clauses[1], document.clauses[0], *document.clauses[2:]))
    with pytest.raises(CapitalTaxTermsValidationError):
        replace(
            document,
            clauses=(
                document.clauses[0],
                replace(document.clauses[1], source_body_sha256="c" * 64),
                *document.clauses[2:],
            ),
        )


def test_source_term_pair_rejects_untyped_document_values() -> None:
    source_1997 = _document(CapitalTaxSourceDocumentId.SAT_1997_198)
    source_1998 = _document(CapitalTaxSourceDocumentId.SAT_1998_289)
    with pytest.raises(CapitalTaxTermsValidationError):
        combine_share_capital_tax_source_terms(
            source_1997_198="not-a-document",
            source_1998_289=source_1998,
        )
    with pytest.raises(CapitalTaxTermsValidationError):
        combine_share_capital_tax_source_terms(
            source_1997_198=source_1997,
            source_1998_289=None,
        )
