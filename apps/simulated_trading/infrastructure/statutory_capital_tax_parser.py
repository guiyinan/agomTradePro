"""Parse two exact retained SAT share-capital tax documents as source text only."""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import date

from bs4 import BeautifulSoup, Tag

from apps.simulated_trading.domain.corporate_action_capital_tax_terms import (
    CapitalTaxSourceClause,
    CapitalTaxSourceClauseKind,
    CapitalTaxSourceDocumentId,
    CapitalTaxSourcePageStatus,
    ParsedCapitalTaxSourceDocument,
)
from core.exceptions import DataValidationError

_TITLE_1997_198 = "国家税务总局关于股份制企业转增股本和派发红股征免个人所得税的通知"
_TITLE_1998_289 = (
    "国家税务总局关于原城市信用社在转制为城市合作银行过程中个人股增值所得应纳个人所得税的批复"
)
_LEGAL_NUMBER_1997_198 = "国税发〔1997〕198号"
_LEGAL_NUMBER_1998_289 = "国税函〔1998〕289号"
_ISSUER = "国家税务总局"
_REFERENCE_1994_TEXT = "《国家税务总局关于印发〈征收个人所得税若干问题的规定〉的通知》"
_REFERENCE_1994_URL = "https://fgk.chinatax.gov.cn/zcfgk/c100011/c5216297/content.html"
_REFERENCE_1997_TEXT = "《国家税务总局关于股份制企业转增股本和派发红股征免个人所得税的通知》"
_REFERENCE_1997_URL = "https://fgk.chinatax.gov.cn/zcfgk/c100012/c5193235/content.html"
_DATE_PATTERN = re.compile(r"成文日期：(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\Z")
_CHARSET_PATTERN = re.compile(rb"<meta\b[^>]*\bcharset\s*=\s*[\"']?([A-Za-z0-9._-]+)", re.I)
_SPACE_PATTERN = re.compile(r"\s+")

_PARAGRAPHS_1997 = (
    "近接一些地区和单位来文、来电请示，要求对股份制企业用资本公积金转增个人股本是否征收个人所得税的问题作出明确规定。经研究，现明确如下：",
    "一、股份制企业用资本公积金转增股本不属于股息、红利性质的分配，对个人取得的转增股本数额，不作为个人所得，不征收个人所得税。",
    "二、股份制企业用盈余公积金派发红股属于股息、红利性质的分配，对个人取得的红股数额，应作为个人所得征税。",
    "各地要严格按照《国家税务总局关于印发〈征收个人所得税若干问题的规定〉的通知》（国税发[1994]89号）的有关规定执行，没有执行的要尽快纠正。派发红股的股份制企业作为支付所得的单位应按照税法规定履行扣缴义务。",
)
_PARAGRAPHS_1998 = (
    "重庆市地方税务局：",
    "你局《重庆市地方税务局关于重庆市信用社在转制为重庆城市合作银行过程中个人股增值所得应纳个人所得税问题的请示》（渝地税发[1998]88号）收悉。经研究，现批复如下：",
    "一、在城市信用社改制为城市合作银行过程中，个人以现金或股份及其他形式取得的资产评估增值数额，应当按“利息、股息、红利所得”项目计征个人所得税，税款由城市合作银行负责代扣代缴。",
    "二、《国家税务总局关于股份制企业转增股本和派发红股征免个人所得税的通知》（国税发[1997]198号）中所表述的“资本公积金”是指股份制企业股票溢价发行收入所形成的资本公积金。将此转增股本由个人取得的数额，不作为应税所得征收个人所得税。而与此不相符合的其他资本公积金分配个人所得部分，应当依法征收个人所得税。",
)


class StatutoryCapitalTaxParserError(DataValidationError):
    """The retained statutory HTML is malformed, incomplete, or unsupported."""

    default_message = "留存的股份资本税务原文不符合受支持的全文结构"
    default_code = "STATUTORY_CAPITAL_TAX_SOURCE_UNSUPPORTED"


def _invalid(message: str) -> StatutoryCapitalTaxParserError:
    """Create a stable parser error without including untrusted source content."""

    return StatutoryCapitalTaxParserError(message)


def _document_facts(
    document_id: CapitalTaxSourceDocumentId,
) -> tuple[str, str, date, tuple[str, ...], tuple[CapitalTaxSourceClauseKind, ...]]:
    """Return the fixed document identity and complete article paragraph grammar."""

    if document_id is CapitalTaxSourceDocumentId.SAT_1997_198:
        return (
            _TITLE_1997_198,
            _LEGAL_NUMBER_1997_198,
            date(1997, 12, 25),
            _PARAGRAPHS_1997,
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
            _PARAGRAPHS_1998,
            (
                CapitalTaxSourceClauseKind.RESPONSE_CONTEXT,
                CapitalTaxSourceClauseKind.REQUEST_CONTEXT,
                CapitalTaxSourceClauseKind.ASSET_VALUATION_INCOME_TREATMENT,
                CapitalTaxSourceClauseKind.CAPITAL_RESERVE_SOURCE_RESTRICTION,
            ),
        )
    raise _invalid("An exact supported source document identity is required.")


def _normalize_text(value: str) -> str:
    """Remove HTML-layout whitespace while retaining every source character."""

    return _SPACE_PATTERN.sub("", value.replace("\xa0", " ").replace("\u2002", " "))


def _decode_utf8_body(body: bytes, *, max_body_bytes: int) -> str:
    """Decode only the encoding declared by the original HTML meta tag."""

    if type(body) is not bytes or not body or len(body) > max_body_bytes:
        raise _invalid("Source body must be nonempty bytes within the explicit byte cap.")
    charsets = tuple(
        match.group(1).decode("ascii", "strict").lower()
        for match in _CHARSET_PATTERN.finditer(body)
    )
    if charsets != ("utf-8",):
        raise _invalid("Source HTML must declare exactly one UTF-8 meta charset.")
    try:
        text = body.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise _invalid("Source HTML bytes do not match their declared UTF-8 encoding.") from error
    soup = BeautifulSoup(text, "html.parser")
    for meta_element in soup.find_all("meta"):
        if not isinstance(meta_element, Tag):
            raise _invalid("Source HTML metadata contains an unsupported node.")
        meta = meta_element
        explicit_charset = meta.get("charset")
        if explicit_charset is not None and str(explicit_charset).lower() != "utf-8":
            raise _invalid("A source meta charset conflicts with the original UTF-8 body.")
        if str(meta.get("http-equiv", "")).lower() == "content-type":
            content = str(meta.get("content", ""))
            declared = re.search(r"\bcharset\s*=\s*[\"']?([A-Za-z0-9._-]+)", content, re.I)
            if declared is not None and declared[1].lower() != "utf-8":
                raise _invalid(
                    "A source HTTP-equiv charset conflicts with the original UTF-8 body."
                )
    return text


def _one_tag(parent: Tag, selector: str, *, field: str) -> Tag:
    """Require one exact metadata node inside the selected article container."""

    matches = parent.select(selector)
    if len(matches) != 1:
        raise _invalid(f"Source HTML is missing or duplicates {field}.")
    match = matches[0]
    if not isinstance(match, Tag):
        raise _invalid(f"Source HTML {field} node is unsupported.")
    return match


def _article_paragraphs(container: Tag) -> tuple[str, ...]:
    """Read every direct paragraph from the article body in original order."""

    paragraphs: list[str] = []
    for child in container.children:
        if isinstance(child, Tag):
            text = _normalize_text(child.get_text("", strip=False))
            if not text:
                continue
            if child.name != "div":
                raise _invalid("Article body paragraph structure is unsupported.")
            paragraphs.append(text)
        elif str(child).strip():
            raise _invalid("Article body contains unsupported non-paragraph text.")
    if not paragraphs:
        raise _invalid("Article body contains no complete text paragraphs.")
    return tuple(paragraphs)


def _verify_article_reference(text: str, *, document_id: CapitalTaxSourceDocumentId) -> None:
    """Require the exact embedded legal reference in the complete article body."""

    if document_id is CapitalTaxSourceDocumentId.SAT_1997_198:
        expected_text = _REFERENCE_1994_TEXT
        expected_url = _REFERENCE_1994_URL
    else:
        expected_text = _REFERENCE_1997_TEXT
        expected_url = _REFERENCE_1997_URL
    soup = BeautifulSoup(text, "html.parser")
    article = soup.select("div.detials.contentLeft div.arc_cont")
    if len(article) != 1:
        raise _invalid("The complete article body is missing or ambiguous.")
    links = article[0].find_all("a")
    if len(links) != 1 or not isinstance(links[0], Tag):
        raise _invalid("The article's exact statutory cross-reference is missing or ambiguous.")
    link = links[0]
    if link.get("href") != expected_url or _normalize_text(
        link.get_text("", strip=False)
    ) != _normalize_text(expected_text):
        raise _invalid("The article's statutory cross-reference differs from the exact source.")


def _source_page_identity(
    text: str,
    *,
    expected_title: str,
    expected_number: str,
    expected_document_date: date,
) -> None:
    """Require the page header, legal number, full-text marker and source date."""

    soup = BeautifulSoup(text, "html.parser")
    metas = soup.find_all("meta", attrs={"name": "ArticleTitle"})
    if len(metas) != 1 or not isinstance(metas[0], Tag):
        raise _invalid("ArticleTitle metadata differs from the selected source document.")
    if metas[0].get("content") != expected_title:
        raise _invalid("ArticleTitle metadata differs from the selected source document.")
    containers = soup.select("div.detials.contentLeft")
    if len(containers) != 1 or not isinstance(containers[0], Tag):
        raise _invalid("The exact source article container is unavailable or ambiguous.")
    container = containers[0]
    title = _one_tag(container, "h3", field="article title").get_text("", strip=True)
    number = _one_tag(container, "h5", field="legal number").get_text("", strip=True)
    if title != expected_title or number != expected_number:
        raise _invalid("Visible article title or legal number differs from its source identity.")
    status = _one_tag(container, "p.arc_date span.xg", field="page status").get_text("", strip=True)
    if status != CapitalTaxSourcePageStatus.FULL_TEXT_EFFECTIVE.value:
        raise _invalid("The source page does not display the exact full-text status label.")
    date_text = _one_tag(container, "p.arc_date span.date", field="document date").get_text(
        "", strip=True
    )
    date_match = _DATE_PATTERN.fullmatch(_normalize_text(date_text))
    try:
        parsed_date = date.fromisoformat(date_match["date"]) if date_match is not None else None
    except ValueError as error:
        raise _invalid("Visible document date is not a real calendar date.") from error
    if parsed_date != expected_document_date:
        raise _invalid("Visible document date differs from its exact source metadata.")


def _paragraph_clauses(
    text: str,
    *,
    expected_paragraphs: tuple[str, ...],
    kinds: tuple[CapitalTaxSourceClauseKind, ...],
    body_sha256: str,
) -> tuple[CapitalTaxSourceClause, ...]:
    """Require the full ordered article text and bind each paragraph to the body."""

    soup = BeautifulSoup(text, "html.parser")
    articles = soup.select("div.detials.contentLeft div.arc_cont")
    if len(articles) != 1:
        raise _invalid("The complete article body is missing or ambiguous.")
    paragraphs = _article_paragraphs(articles[0])
    expected = tuple(_normalize_text(paragraph) for paragraph in expected_paragraphs)
    if paragraphs != expected or len(kinds) != len(expected):
        raise _invalid("Source full text differs from the supported complete paragraph set.")
    return tuple(
        CapitalTaxSourceClause(
            kind=kind,
            normalized_text=paragraph,
            source_body_sha256=body_sha256,
        )
        for kind, paragraph in zip(kinds, paragraphs, strict=True)
    )


def parse_sat_capital_tax_source_document(
    body: bytes,
    *,
    expected_document_id: CapitalTaxSourceDocumentId,
    max_body_bytes: int,
) -> ParsedCapitalTaxSourceDocument:
    """Parse one complete SAT 1997/198 or 1998/289 retained HTML source.

    The parsed status is the page's literal display label, and the parsed date
    is the document's stated date. Neither is treated as a legal effective date
    or current qualification. The caller must compare ``body_sha256`` with the
    exact retained Data Center revision before using these clauses.
    """

    if type(max_body_bytes) is not int or not 0 < max_body_bytes < sys.maxsize:
        raise _invalid("An explicit positive exact parsing byte cap is required.")
    if type(expected_document_id) is not CapitalTaxSourceDocumentId:
        raise _invalid("An exact supported source document identity is required.")
    title, legal_number, document_date, expected_paragraphs, kinds = _document_facts(
        expected_document_id
    )
    text = _decode_utf8_body(body, max_body_bytes=max_body_bytes)
    _source_page_identity(
        text,
        expected_title=title,
        expected_number=legal_number,
        expected_document_date=document_date,
    )
    body_sha256 = hashlib.sha256(body).hexdigest()
    _verify_article_reference(text, document_id=expected_document_id)
    clauses = _paragraph_clauses(
        text,
        expected_paragraphs=expected_paragraphs,
        kinds=kinds,
        body_sha256=body_sha256,
    )
    return ParsedCapitalTaxSourceDocument(
        document_id=expected_document_id,
        title=title,
        legal_number=legal_number,
        issuer=_ISSUER,
        source_page_status=CapitalTaxSourcePageStatus.FULL_TEXT_EFFECTIVE,
        document_date=document_date,
        body_sha256=body_sha256,
        clauses=clauses,
    )


__all__ = ["StatutoryCapitalTaxParserError", "parse_sat_capital_tax_source_document"]
