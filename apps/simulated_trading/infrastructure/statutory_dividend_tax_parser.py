"""Interpret only the explicitly supported listed-individual statutory clause grammar."""

from __future__ import annotations

import re
import sys
from datetime import date
from decimal import Decimal

from bs4 import BeautifulSoup

from apps.simulated_trading.domain.corporate_action_statutory_tax_terms import (
    ParsedStatutoryDividendTaxTerms,
    StatutoryDividendTaxClause,
    StatutoryDividendTaxClausePurpose,
)
from core.exceptions import DataValidationError

_NUMBER = r"[0-9]+(?:\.[0-9]+)?"
_PREFIX = r"(?:[一二三四五六七八九十]+、)?"
_PERSONAL_STOCK = "个人从公开发行和转让市场取得的上市公司股票"
_BANDS = re.compile(
    _PREFIX
    + _PERSONAL_STOCK
    + r"，持股期限在(?P<short>[0-9]+)个月以内（含(?P<short_inclusive>[0-9]+)个月）的，其股息红利所得全额计入应纳税所得额；"
    r"持股期限在(?P<middle_start>[0-9]+)个月以上至(?P<middle_years>[0-9]+)年（含(?P<middle_inclusive>[0-9]+)年）的，暂减按(?P<ratio>"
    + _NUMBER
    + r")%计入应纳税所得额；"
    r"上述所得统一适用(?P<rate>" + _NUMBER + r")%的税率计征个人所得税。"
)
_EXEMPTION = re.compile(
    _PREFIX
    + _PERSONAL_STOCK
    + r"，持股期限超过(?P<years>[0-9]+)年的，股息红利所得暂免征收个人所得税。"
)
_DEFERRED = re.compile(
    r"二、上市公司派发股息红利时，对个人持股(?P<years>[0-9]+)年以内（含(?P<inclusive>[0-9]+)年）的，上市公司暂不扣缴个人所得税；"
    r"待个人转让股票时，证券登记结算公司根据其持股期限计算应纳税额，由证券公司等股份托管机构从个人资金账户中扣收并划付证券登记结算公司，[^。]+。"
)
_DATE = r"(?P<year>[0-9]{4})年(?P<month>[0-9]{1,2})月(?P<day>[0-9]{1,2})日"
_EFFECTIVE = re.compile(r"五、本通知自" + _DATE + r"起施行。")
_RECORD_BOUNDARY = re.compile(
    r"上市公司派发股息红利，股权登记日在"
    + _DATE
    + r"之后的，股息红利所得按照本通知的规定执行。[^。]+。"
)
_HOLDING_SCOPE = re.compile(
    r"前款所称上市公司是指在上海证券交易所、深圳证券交易所挂牌交易的上市公司；持股期限是指个人从公开发行和转让市场取得上市公司股票之日至转让交割该股票之日前一日的持有时间。"
)
_FIFO = re.compile(
    r"三、个人转让股票时，按照先进先出的原则计算持股期限，即证券账户中先取得的股票视为先转让。"
)
_NET = re.compile(
    r"应纳税所得额以个人投资者证券账户为单位计算，持股数量以每日日终结算后个人投资者证券账户的持有记录为准，证券账户取得或转让的股份数为每日日终结算后的净增（减）股份数。"
)
_CALENDAR = re.compile(
    r"八、本通知所称年（月）是指自然年（月），即持股一年是指从上一年某月某日至本年同月同日的前一日连续持股，持股一个月是指从上月某日至本月同日的前一日连续持股。"
)


def _invalid(message: str) -> DataValidationError:
    """Report a stable unsupported/ambiguous statutory-grammar block."""
    return DataValidationError(message, code="STATUTORY_DIVIDEND_TAX_CLAUSE_UNSUPPORTED")


def _paragraphs(body: bytes, legal_number: str, maximum: int) -> tuple[str, ...]:
    """Read bounded original HTML with its declared native legal number intact."""
    if (
        type(body) is not bytes
        or not body
        or len(body) > maximum
        or type(legal_number) is not str
        or not legal_number
        or len(legal_number) > 240
        or legal_number != legal_number.strip()
    ):
        raise _invalid("Statutory body or native legal number is invalid.")
    soup = BeautifulSoup(body, "html.parser")
    for tag in soup.find_all(("script", "style", "noscript")):
        tag.decompose()
    if legal_number not in "".join(soup.stripped_strings):
        raise _invalid("Statutory body does not contain its exact native legal number.")
    return tuple(re.sub(r"\s+", "", p.get_text()) for p in soup.find_all("p"))


def _one(paragraphs: tuple[str, ...], pattern: re.Pattern[str]) -> tuple[str, re.Match[str]]:
    """Require exactly one complete matching clause, preserving ambiguity failures."""
    matches = tuple((p, m) for p in paragraphs if (m := pattern.fullmatch(p)) is not None)
    if len(matches) != 1:
        raise _invalid("A required statutory clause is missing, changed or ambiguous.")
    return matches[0]


def _source_date(match: re.Match[str]) -> date:
    """Read the explicit normative date without substituting source issue clocks."""
    return date(int(match["year"]), int(match["month"]), int(match["day"]))


def _percentage(text: str) -> Decimal:
    """Scale a bounded plain percentage exactly before Domain precision checks."""
    if len(text) > 32:
        raise _invalid("Statutory percentage text exceeds supported exact precision.")
    value = Decimal(text)
    sign, digits, exponent = value.as_tuple()
    if type(exponent) is not int:
        raise _invalid("Statutory percentage must be a finite plain decimal.")
    return Decimal((sign, digits, exponent - 2))


def parse_statutory_dividend_tax_terms(
    *,
    rate_document_body: bytes,
    rate_legal_number: str,
    rate_source_revision_sha256: str,
    mechanics_document_body: bytes,
    mechanics_legal_number: str,
    mechanics_source_revision_sha256: str,
    max_body_bytes: int,
) -> ParsedStatutoryDividendTaxTerms:
    """Derive supported terms from two source-verified normative documents.

    The caller must first verify native revision facts, original byte hashes,
    configured official-source scope and current applicability. This grammar
    reader confers none of those permissions and never maps custody dates.
    It extracts numeric rates/thresholds, checks the explicit cross-reference,
    and rejects unsupported or ambiguous text instead of using a default.
    """
    if type(max_body_bytes) is not int or not 0 < max_body_bytes < sys.maxsize:
        raise _invalid("An explicit positive statutory parsing byte cap is required.")
    rates = _paragraphs(rate_document_body, rate_legal_number, max_body_bytes)
    mechanics = _paragraphs(mechanics_document_body, mechanics_legal_number, max_body_bytes)
    rate_text, bands = _one(rates, _BANDS)
    exempt_text, exempt = _one(rates, _EXEMPTION)
    deferred_text, deferred = _one(rates, _DEFERRED)
    reference_pattern = re.compile(
        r"三、上市公司股息红利差别化个人所得税政策其他有关操作事项，按照《[^》]+》（"
        + re.escape(mechanics_legal_number)
        + r"）的相关规定执行。"
    )
    reference_text, _ = _one(rates, reference_pattern)
    effective_text, effective = _one(rates, _EFFECTIVE)
    boundary_text, boundary = _one(rates, _RECORD_BOUNDARY)
    scope_text, _ = _one(mechanics, _HOLDING_SCOPE)
    fifo_text, _ = _one(mechanics, _FIFO)
    net_text, _ = _one(mechanics, _NET)
    calendar_text, _ = _one(mechanics, _CALENDAR)
    try:
        short = int(bands["short"])
        years = int(bands["middle_years"])
        if (
            short != int(bands["short_inclusive"])
            or short != int(bands["middle_start"])
            or years != int(bands["middle_inclusive"])
            or years != int(exempt["years"])
            or years != int(deferred["years"])
            or years != int(deferred["inclusive"])
            or _source_date(effective) != _source_date(boundary)
        ):
            raise _invalid("Statutory thresholds or normative date clauses conflict.")
        ratio = _percentage(bands["ratio"])
        rate = _percentage(bands["rate"])
        purpose = StatutoryDividendTaxClausePurpose
        rate_clauses = (
            (purpose.HOLDING_BANDS, rate_text),
            (purpose.LONG_HOLDING_EXEMPTION, exempt_text),
            (purpose.DEFERRED_WITHHOLDING, deferred_text),
            (purpose.MECHANICS_CROSS_REFERENCE, reference_text),
            (purpose.RECORD_DATE_BOUNDARY, effective_text + boundary_text),
        )
        mechanics_clauses = (
            (purpose.HOLDING_DATE_SCOPE, scope_text),
            (purpose.FIFO, fifo_text),
            (purpose.DAILY_NET, net_text),
            (purpose.NATURAL_CALENDAR, calendar_text),
        )
        clauses = tuple(
            StatutoryDividendTaxClause(p, rate_source_revision_sha256, text)
            for p, text in rate_clauses
        ) + tuple(
            StatutoryDividendTaxClause(p, mechanics_source_revision_sha256, text)
            for p, text in mechanics_clauses
        )
        return ParsedStatutoryDividendTaxTerms(
            short, years * 12, ratio, rate, _source_date(boundary), clauses
        )
    except (ArithmeticError, ValueError) as error:
        raise _invalid(
            "Statutory source terms exceed supported exact arithmetic or date scope."
        ) from error


__all__ = ["parse_statutory_dividend_tax_terms"]
