"""Small synthetic HTML fixtures test the grammar, never legal qualification."""

from hashlib import sha256

import pytest

from apps.simulated_trading.domain.corporate_action_capital_tax_terms import (
    CapitalTaxSourceClauseKind,
    CapitalTaxSourceDocumentId,
    CapitalTaxSourcePageStatus,
)
from apps.simulated_trading.infrastructure.statutory_capital_tax_parser import (
    StatutoryCapitalTaxParserError,
    parse_sat_capital_tax_source_document,
)

_TITLE_1997 = "国家税务总局关于股份制企业转增股本和派发红股征免个人所得税的通知"
_TITLE_1998 = (
    "国家税务总局关于原城市信用社在转制为城市合作银行过程中个人股增值所得应纳个人所得税的批复"
)
_NUMBER_1997 = "国税发〔1997〕198号"
_NUMBER_1998 = "国税函〔1998〕289号"
_REFERENCE_1994_TEXT = "《国家税务总局关于印发〈征收个人所得税若干问题的规定〉的通知》"
_REFERENCE_1994_URL = "https://fgk.chinatax.gov.cn/zcfgk/c100011/c5216297/content.html"
_REFERENCE_1997_TEXT = "《国家税务总局关于股份制企业转增股本和派发红股征免个人所得税的通知》"
_REFERENCE_1997_URL = "https://fgk.chinatax.gov.cn/zcfgk/c100012/c5193235/content.html"
_TEXT_1997 = (
    "近接一些地区和单位来文、来电请示，要求对股份制企业用资本公积金转增个人股本是否征收个人所得税的问题作出明确规定。经研究，现明确如下：",
    "一、股份制企业用资本公积金转增股本不属于股息、红利性质的分配，对个人取得的转增股本数额，不作为个人所得，不征收个人所得税。",
    "二、股份制企业用盈余公积金派发红股属于股息、红利性质的分配，对个人取得的红股数额，应作为个人所得征税。",
    "各地要严格按照《国家税务总局关于印发〈征收个人所得税若干问题的规定〉的通知》（国税发[1994]89号）的有关规定执行，没有执行的要尽快纠正。派发红股的股份制企业作为支付所得的单位应按照税法规定履行扣缴义务。",
)
_TEXT_1998 = (
    "重庆市地方税务局：",
    "你局《重庆市地方税务局关于重庆市信用社在转制为重庆城市合作银行过程中个人股增值所得应纳个人所得税问题的请示》（渝地税发[1998]88号）收悉。经研究，现批复如下：",
    "一、在城市信用社改制为城市合作银行过程中，个人以现金或股份及其他形式取得的资产评估增值数额，应当按“利息、股息、红利所得”项目计征个人所得税，税款由城市合作银行负责代扣代缴。",
    "二、《国家税务总局关于股份制企业转增股本和派发红股征免个人所得税的通知》（国税发[1997]198号）中所表述的“资本公积金”是指股份制企业股票溢价发行收入所形成的资本公积金。将此转增股本由个人取得的数额，不作为应税所得征收个人所得税。而与此不相符合的其他资本公积金分配个人所得部分，应当依法征收个人所得税。",
)


def _html(
    document_id: CapitalTaxSourceDocumentId,
    *,
    paragraphs: tuple[str, ...] | None = None,
    title: str | None = None,
    legal_number: str | None = None,
    page_status: str = "全文有效",
    document_date: str | None = None,
    charset: str = "UTF-8",
) -> bytes:
    """Create one compact synthetic official-page-shaped HTML body."""
    is_1997 = document_id is CapitalTaxSourceDocumentId.SAT_1997_198
    selected_title = title or (_TITLE_1997 if is_1997 else _TITLE_1998)
    selected_number = legal_number or (_NUMBER_1997 if is_1997 else _NUMBER_1998)
    selected_paragraphs = paragraphs or (_TEXT_1997 if is_1997 else _TEXT_1998)
    selected_date = document_date or ("1997-12-25" if is_1997 else "1998-05-15")
    rendered_paragraphs = list(selected_paragraphs)
    if is_1997 and len(rendered_paragraphs) > 3:
        rendered_paragraphs[3] = rendered_paragraphs[3].replace(
            _REFERENCE_1994_TEXT,
            f'<a href="{_REFERENCE_1994_URL}">{_REFERENCE_1994_TEXT}</a>',
        )
    elif not is_1997 and len(rendered_paragraphs) > 3:
        rendered_paragraphs[3] = rendered_paragraphs[3].replace(
            _REFERENCE_1997_TEXT,
            f'<a href="{_REFERENCE_1997_URL}">{_REFERENCE_1997_TEXT}</a>',
        )
    body = (
        f'<html><head><meta charset="{charset}">'
        f'<meta name="ArticleTitle" content="{selected_title}"></head><body>'
        '<div class="detials contentLeft"><h3>'
        f'{selected_title}</h3><div class="arctips"><h5>{selected_number}</h5></div>'
        f'<p class="arc_date"><span class="xg">{page_status}</span>'
        f'<span class="date">成文日期：{selected_date}</span></p>'
        '<div class="article"><div class="arc_cont">'
        + "".join(f"<div>{paragraph}</div>" for paragraph in rendered_paragraphs)
        + "<p>&ensp;</p></div></div></div></body></html>"
    )
    return body.encode("utf-8")


@pytest.mark.parametrize(
    ("document_id", "expected_kinds", "expected_date"),
    [
        (
            CapitalTaxSourceDocumentId.SAT_1997_198,
            (
                CapitalTaxSourceClauseKind.BACKGROUND_CONTEXT,
                CapitalTaxSourceClauseKind.CAPITAL_RESERVE_TRANSFER_PERSONAL_TREATMENT,
                CapitalTaxSourceClauseKind.SURPLUS_RESERVE_STOCK_BONUS_PERSONAL_TREATMENT,
                CapitalTaxSourceClauseKind.WITHHOLDING_ADMINISTRATION,
            ),
            "1997-12-25",
        ),
        (
            CapitalTaxSourceDocumentId.SAT_1998_289,
            (
                CapitalTaxSourceClauseKind.RESPONSE_CONTEXT,
                CapitalTaxSourceClauseKind.REQUEST_CONTEXT,
                CapitalTaxSourceClauseKind.ASSET_VALUATION_INCOME_TREATMENT,
                CapitalTaxSourceClauseKind.CAPITAL_RESERVE_SOURCE_RESTRICTION,
            ),
            "1998-05-15",
        ),
    ],
)
def test_complete_synthetic_document_extracts_identity_and_exact_source_terms(
    document_id: CapitalTaxSourceDocumentId,
    expected_kinds: tuple[CapitalTaxSourceClauseKind, ...],
    expected_date: str,
) -> None:
    body = _html(document_id)
    result = parse_sat_capital_tax_source_document(
        body,
        expected_document_id=document_id,
        max_body_bytes=16384,
    )

    assert result.document_id is document_id
    assert result.source_page_status is CapitalTaxSourcePageStatus.FULL_TEXT_EFFECTIVE
    assert result.document_date.isoformat() == expected_date
    assert tuple(clause.kind for clause in result.clauses) == expected_kinds
    assert all(clause.normalized_text for clause in result.clauses)
    assert result.body_sha256 == sha256(body).hexdigest()
    assert not hasattr(result, "effective_date")


def test_source_page_status_must_be_full_text_effective() -> None:
    body = _html(
        CapitalTaxSourceDocumentId.SAT_1997_198,
        page_status="部分有效",
    )
    with pytest.raises(StatutoryCapitalTaxParserError):
        parse_sat_capital_tax_source_document(
            body,
            expected_document_id=CapitalTaxSourceDocumentId.SAT_1997_198,
            max_body_bytes=16384,
        )


@pytest.mark.parametrize(
    ("document_id", "url"),
    [
        (CapitalTaxSourceDocumentId.SAT_1997_198, _REFERENCE_1994_URL),
        (CapitalTaxSourceDocumentId.SAT_1998_289, _REFERENCE_1997_URL),
    ],
)
def test_document_must_retain_exact_embedded_statutory_reference(
    document_id: CapitalTaxSourceDocumentId,
    url: str,
) -> None:
    body = _html(document_id).replace(url.encode("ascii"), b"https://example.invalid/changed")
    with pytest.raises(StatutoryCapitalTaxParserError):
        parse_sat_capital_tax_source_document(
            body,
            expected_document_id=document_id,
            max_body_bytes=16384,
        )


def test_document_date_is_source_metadata_not_an_effective_date() -> None:
    body = _html(CapitalTaxSourceDocumentId.SAT_1997_198, document_date="1997-12-25")
    result = parse_sat_capital_tax_source_document(
        body,
        expected_document_id=CapitalTaxSourceDocumentId.SAT_1997_198,
        max_body_bytes=16384,
    )
    assert result.document_date.isoformat() == "1997-12-25"
    assert "effective" not in result.__dataclass_fields__


@pytest.mark.parametrize(
    ("document_id", "kwargs"),
    [
        (
            CapitalTaxSourceDocumentId.SAT_1997_198,
            {"title": _TITLE_1998},
        ),
        (
            CapitalTaxSourceDocumentId.SAT_1997_198,
            {"legal_number": _NUMBER_1998},
        ),
        (
            CapitalTaxSourceDocumentId.SAT_1998_289,
            {"paragraphs": _TEXT_1998[:-1]},
        ),
        (
            CapitalTaxSourceDocumentId.SAT_1998_289,
            {
                "paragraphs": _TEXT_1998[:-1]
                + (_TEXT_1998[-1].replace("股票溢价发行收入", "股票发行收入"),)
            },
        ),
        (
            CapitalTaxSourceDocumentId.SAT_1998_289,
            {"paragraphs": _TEXT_1998 + ("新增不支持的内容。",)},
        ),
    ],
)
def test_identity_or_any_required_full_text_clause_mismatch_blocks(
    document_id: CapitalTaxSourceDocumentId,
    kwargs: dict[str, object],
) -> None:
    body = _html(document_id, **kwargs)
    with pytest.raises(StatutoryCapitalTaxParserError):
        parse_sat_capital_tax_source_document(
            body,
            expected_document_id=document_id,
            max_body_bytes=16384,
        )


@pytest.mark.parametrize("charset", ["ISO-8859-1", "GBK", "utf8 "])
def test_unexpected_html_meta_encoding_is_not_silently_reinterpreted(charset: str) -> None:
    with pytest.raises(StatutoryCapitalTaxParserError):
        parse_sat_capital_tax_source_document(
            _html(CapitalTaxSourceDocumentId.SAT_1997_198, charset=charset),
            expected_document_id=CapitalTaxSourceDocumentId.SAT_1997_198,
            max_body_bytes=16384,
        )


def test_invalid_utf8_and_non_byte_input_fail_closed() -> None:
    with pytest.raises(StatutoryCapitalTaxParserError):
        parse_sat_capital_tax_source_document(
            b"<meta charset='utf-8'>\xff",
            expected_document_id=CapitalTaxSourceDocumentId.SAT_1997_198,
            max_body_bytes=16384,
        )
    with pytest.raises(StatutoryCapitalTaxParserError):
        parse_sat_capital_tax_source_document(
            "<html></html>",
            expected_document_id=CapitalTaxSourceDocumentId.SAT_1997_198,
            max_body_bytes=16384,
        )


def test_conflicting_later_or_http_equiv_charset_blocks() -> None:
    valid = _html(CapitalTaxSourceDocumentId.SAT_1997_198)
    conflicting_meta = valid.replace(
        b"<head>",
        b'<head><meta charset="UTF-8"><meta charset="ISO-8859-1">',
        1,
    )
    conflicting_http_equiv = valid.replace(
        b"<head>",
        b'<head><meta http-equiv="Content-Type" content="text/html; charset=ISO-8859-1">',
        1,
    )
    for body in (conflicting_meta, conflicting_http_equiv):
        with pytest.raises(StatutoryCapitalTaxParserError):
            parse_sat_capital_tax_source_document(
                body,
                expected_document_id=CapitalTaxSourceDocumentId.SAT_1997_198,
                max_body_bytes=16384,
            )


def test_invalid_calendar_document_date_blocks() -> None:
    with pytest.raises(StatutoryCapitalTaxParserError):
        parse_sat_capital_tax_source_document(
            _html(CapitalTaxSourceDocumentId.SAT_1997_198, document_date="1997-99-25"),
            expected_document_id=CapitalTaxSourceDocumentId.SAT_1997_198,
            max_body_bytes=16384,
        )


@pytest.mark.parametrize("byte_cap", [0, -1, True, 1.5])
def test_parser_requires_explicit_bounded_exact_byte_cap(byte_cap: object) -> None:
    with pytest.raises(StatutoryCapitalTaxParserError):
        parse_sat_capital_tax_source_document(
            _html(CapitalTaxSourceDocumentId.SAT_1997_198),
            expected_document_id=CapitalTaxSourceDocumentId.SAT_1997_198,
            max_body_bytes=byte_cap,
        )
