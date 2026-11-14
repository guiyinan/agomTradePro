"""Exact source-clause values for the supported share-capital tax references.

These values retain two document identities and their interpreted full text.
They do not establish current law, a document's current legal effect, holder
eligibility, or financial authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import NoReturn

_TITLE_1997_198 = "国家税务总局关于股份制企业转增股本和派发红股征免个人所得税的通知"
_TITLE_1998_289 = (
    "国家税务总局关于原城市信用社在转制为城市合作银行过程中个人股增值所得应纳个人所得税的批复"
)
_LEGAL_NUMBER_1997_198 = "国税发〔1997〕198号"
_LEGAL_NUMBER_1998_289 = "国税函〔1998〕289号"
_ISSUER = "国家税务总局"


class CapitalTaxTermsValidationError(ValueError):
    """Raised when the two exact source documents or their clauses are invalid."""

    code = "CAPITAL_TAX_SOURCE_TERMS_INVALID"


class CapitalTaxSourceDocumentId(StrEnum):
    """One of the two explicitly supported national tax source identities."""

    SAT_1997_198 = "sat-1997-198"
    SAT_1998_289 = "sat-1998-289"


class CapitalTaxSourcePageStatus(StrEnum):
    """The exact status label displayed by a source page, not a legal finding."""

    FULL_TEXT_EFFECTIVE = "全文有效"


class CapitalTaxSourceClauseKind(StrEnum):
    """Position and subject of a retained source paragraph."""

    BACKGROUND_CONTEXT = "background_context"
    CAPITAL_RESERVE_TRANSFER_PERSONAL_TREATMENT = "capital_reserve_transfer_personal_treatment"
    SURPLUS_RESERVE_STOCK_BONUS_PERSONAL_TREATMENT = (
        "surplus_reserve_stock_bonus_personal_treatment"
    )
    WITHHOLDING_ADMINISTRATION = "withholding_administration"
    RESPONSE_CONTEXT = "response_context"
    REQUEST_CONTEXT = "request_context"
    ASSET_VALUATION_INCOME_TREATMENT = "asset_valuation_income_treatment"
    CAPITAL_RESERVE_SOURCE_RESTRICTION = "capital_reserve_source_restriction"


class CapitalTaxSourceOrigin(StrEnum):
    """Explicit modeled origin classes named by the retained source clauses."""

    STOCK_ISSUE_PREMIUM_CAPITAL_RESERVE = "stock_issue_premium_capital_reserve"
    OTHER_CAPITAL_RESERVE = "other_capital_reserve"
    EARNINGS_RESERVE = "earnings_reserve"


def _invalid(message: str) -> NoReturn:
    """Raise one stable Domain error for incomplete or ambiguous source terms."""

    raise CapitalTaxTermsValidationError(message)


def _require_digest(value: object, field_name: str) -> str:
    """Require one lowercase SHA-256 digest without coercion."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _invalid(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_text(value: object, field_name: str, *, maximum: int) -> str:
    """Require one bounded, nonempty UTF-8 source fact."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        _invalid(f"{field_name} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise CapitalTaxTermsValidationError(f"{field_name} is not UTF-8") from error
    return value


def _expected_document_facts(
    document_id: CapitalTaxSourceDocumentId,
) -> tuple[str, str, date, tuple[CapitalTaxSourceClauseKind, ...]]:
    """Return the fixed source identity and complete clause ordering."""

    if document_id is CapitalTaxSourceDocumentId.SAT_1997_198:
        return (
            _TITLE_1997_198,
            _LEGAL_NUMBER_1997_198,
            date(1997, 12, 25),
            (
                CapitalTaxSourceClauseKind.BACKGROUND_CONTEXT,
                CapitalTaxSourceClauseKind.CAPITAL_RESERVE_TRANSFER_PERSONAL_TREATMENT,
                CapitalTaxSourceClauseKind.SURPLUS_RESERVE_STOCK_BONUS_PERSONAL_TREATMENT,
                CapitalTaxSourceClauseKind.WITHHOLDING_ADMINISTRATION,
            ),
        )
    if document_id is CapitalTaxSourceDocumentId.SAT_1998_289:
        return (
            _TITLE_1998_289,
            _LEGAL_NUMBER_1998_289,
            date(1998, 5, 15),
            (
                CapitalTaxSourceClauseKind.RESPONSE_CONTEXT,
                CapitalTaxSourceClauseKind.REQUEST_CONTEXT,
                CapitalTaxSourceClauseKind.ASSET_VALUATION_INCOME_TREATMENT,
                CapitalTaxSourceClauseKind.CAPITAL_RESERVE_SOURCE_RESTRICTION,
            ),
        )
    _invalid("unsupported capital-tax source document")


@dataclass(frozen=True, slots=True)
class CapitalTaxSourceClause:
    """One complete normalized article paragraph tied to the original body hash."""

    kind: CapitalTaxSourceClauseKind
    normalized_text: str
    source_body_sha256: str

    def __post_init__(self) -> None:
        """Validate paragraph identity, exact text shape, and body binding."""

        if type(self.kind) is not CapitalTaxSourceClauseKind:
            _invalid("source clause kind is unsupported")
        _require_text(self.normalized_text, "normalized_text", maximum=12000)
        _require_digest(self.source_body_sha256, "source_body_sha256")

    @property
    def clause_sha256(self) -> str:
        """Return a stable digest for this exact typed source paragraph."""

        payload = {
            "schema": "share-capital-tax-source-clause.v1",
            "kind": self.kind.value,
            "normalized_text": self.normalized_text,
            "source_body_sha256": self.source_body_sha256,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ParsedCapitalTaxSourceDocument:
    """One fully parsed source page, retaining its document date as metadata.

    ``source_page_status`` is the source site's displayed label. Neither it nor
    ``document_date`` supplies a legal effective window.
    """

    document_id: CapitalTaxSourceDocumentId
    title: str
    legal_number: str
    issuer: str
    source_page_status: CapitalTaxSourcePageStatus
    document_date: date
    body_sha256: str
    clauses: tuple[CapitalTaxSourceClause, ...]

    def __post_init__(self) -> None:
        """Require the exact supported source identity and every body paragraph."""

        if type(self.document_id) is not CapitalTaxSourceDocumentId:
            _invalid("source document identifier is unsupported")
        title, legal_number, source_date, expected_kinds = _expected_document_facts(
            self.document_id
        )
        if (
            _require_text(self.title, "title", maximum=1000) != title
            or _require_text(self.legal_number, "legal_number", maximum=240) != legal_number
            or _require_text(self.issuer, "issuer", maximum=240) != _ISSUER
        ):
            _invalid("source title, issuer, or legal number differs from the supported document")
        if type(self.source_page_status) is not CapitalTaxSourcePageStatus:
            _invalid("source page status is not the exact full-text label")
        if type(self.document_date) is not date or self.document_date != source_date:
            _invalid("source document date differs from its exact metadata")
        body_sha256 = _require_digest(self.body_sha256, "body_sha256")
        if type(self.clauses) is not tuple or any(
            type(clause) is not CapitalTaxSourceClause for clause in self.clauses
        ):
            _invalid("source clauses must be an exact typed tuple")
        if tuple(clause.kind for clause in self.clauses) != expected_kinds:
            _invalid("source document is missing, duplicating, or reordering full-text clauses")
        if any(clause.source_body_sha256 != body_sha256 for clause in self.clauses):
            _invalid("source paragraph is bound to another original body")


@dataclass(frozen=True, slots=True)
class ParsedShareCapitalTaxSourceTerms:
    """The two complete source documents and their exact clause provenance.

    This value reports only what the retained texts state. It has no current
    applicability window or holder-specific eligibility result.
    """

    source_1997_198: ParsedCapitalTaxSourceDocument
    source_1998_289: ParsedCapitalTaxSourceDocument

    def __post_init__(self) -> None:
        """Require the two exact documents in their declared semantic roles."""

        if (
            type(self.source_1997_198) is not ParsedCapitalTaxSourceDocument
            or self.source_1997_198.document_id is not CapitalTaxSourceDocumentId.SAT_1997_198
            or type(self.source_1998_289) is not ParsedCapitalTaxSourceDocument
            or self.source_1998_289.document_id is not CapitalTaxSourceDocumentId.SAT_1998_289
        ):
            _invalid("both exact source documents are required in their declared roles")
        if self.source_1997_198.body_sha256 == self.source_1998_289.body_sha256:
            _invalid("the two source body identities must be distinct")

    @property
    def clauses(self) -> tuple[CapitalTaxSourceClause, ...]:
        """Return every source paragraph in the fixed document order."""

        self.__post_init__()
        return self.source_1997_198.clauses + self.source_1998_289.clauses

    @property
    def terms_sha256(self) -> str:
        """Hash the complete ordered document and clause identities."""

        self.__post_init__()
        payload = {
            "schema": "share-capital-tax-source-terms.v1",
            "source_1997_198": self.source_1997_198.body_sha256,
            "source_1998_289": self.source_1998_289.body_sha256,
            "clauses": [clause.clause_sha256 for clause in self.clauses],
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()


def combine_share_capital_tax_source_terms(
    *,
    source_1997_198: ParsedCapitalTaxSourceDocument,
    source_1998_289: ParsedCapitalTaxSourceDocument,
) -> ParsedShareCapitalTaxSourceTerms:
    """Combine the two complete source parses without inferring applicability."""

    return ParsedShareCapitalTaxSourceTerms(
        source_1997_198=source_1997_198,
        source_1998_289=source_1998_289,
    )


__all__ = [
    "CapitalTaxSourceClause",
    "CapitalTaxSourceClauseKind",
    "CapitalTaxSourceDocumentId",
    "CapitalTaxSourceOrigin",
    "CapitalTaxSourcePageStatus",
    "CapitalTaxTermsValidationError",
    "ParsedCapitalTaxSourceDocument",
    "ParsedShareCapitalTaxSourceTerms",
    "combine_share_capital_tax_source_terms",
]
