"""Official PDF transport and immutable body retention boundaries."""

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from apps.data_center.domain.security_disclosure_event import SecurityDisclosureEventType
from apps.data_center.infrastructure import official_szse_pdf_capture as capture_module
from apps.data_center.infrastructure.official_szse_pdf_capture import (
    OfficialDisclosureCaptureError,
    OfficialSzsePdfBodyStore,
    capture_official_szse_pdf,
    classify_szse_pdf_disclosure,
    extract_szse_distribution_dates,
    extract_szse_distribution_terms,
    verify_szse_pdf_security_code,
)

_URL = (
    "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-17/"
    "37e23922-f64d-4203-9d27-9ed981a8f799.PDF"
)
_BODY = b"%PDF-1.4\nsource bytes\n%%EOF\n"


def _response(body: bytes, *, content_type: str = "application/pdf") -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = content_type
    response.raw = BytesIO(body)
    return response


def test_official_pdf_is_captured_with_native_document_id_and_exact_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))

    capture = capture_official_szse_pdf(_URL)
    store = OfficialSzsePdfBodyStore(tmp_path)
    first_path = store.retain(capture)

    assert capture.source_document_id == "37e23922-f64d-4203-9d27-9ed981a8f799"
    assert capture.first_seen_at.tzinfo is not None
    assert store.retain(capture) == first_path
    assert store.read(capture.body_sha256) == _BODY


@pytest.mark.parametrize(
    "url",
    [
        "http://disc.static.szse.cn/disc/disk03/finalpage/2026-09-17/"
        "37e23922-f64d-4203-9d27-9ed981a8f799.PDF",
        "https://evil.example/disc/disk03/finalpage/2026-09-17/"
        "37e23922-f64d-4203-9d27-9ed981a8f799.PDF",
        "https://disc.static.szse.cn/disc/disk03/finalpage/2026-09-17/file.PDF",
    ],
)
def test_unapproved_url_rejected_before_network(url: str) -> None:
    with pytest.raises(OfficialDisclosureCaptureError):
        capture_official_szse_pdf(url)


def test_html_response_does_not_become_source_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _response(b"<html>blocked</html>", content_type="text/html"),
    )

    with pytest.raises(OfficialDisclosureCaptureError, match="complete PDF"):
        capture_official_szse_pdf(_URL)


def test_corrupt_retained_pdf_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    store = OfficialSzsePdfBodyStore(tmp_path)
    path = store.retain(capture)
    path.write_bytes(b"corrupt")

    with pytest.raises(OfficialDisclosureCaptureError, match="hash mismatch"):
        store.read(capture.body_sha256)
    with pytest.raises(OfficialDisclosureCaptureError, match="integrity check"):
        store.retain(capture)


def test_pdf_header_must_match_exact_security(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: "股票代码：002727 股票简称：一心堂"),)
        ),
    )

    assert verify_szse_pdf_security_code(capture, "002727") == "002727"
    with pytest.raises(OfficialDisclosureCaptureError, match="does not match"):
        verify_szse_pdf_security_code(capture, "301237")


def test_full_first_page_issuer_name_can_bind_pdf_without_a_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A listed issuer visible later on page one can bind a legal opinion PDF."""

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    first_page = "普通文本" * 180 + "杭州和顺科技股份有限公司法律意见书"
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: first_page),)
        ),
    )

    assert (
        verify_szse_pdf_security_code(
            capture,
            "301237",
            expected_issuer_name="和顺科技",
        )
        == "301237"
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: "一份无关公司的法律文件"),)
        ),
    )
    with pytest.raises(OfficialDisclosureCaptureError, match="does not match"):
        verify_szse_pdf_security_code(
            capture,
            "301237",
            expected_issuer_name="和顺科技",
        )


def test_conflicting_first_page_code_cannot_be_overridden_by_issuer_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A numeric source identity conflict blocks even when the issuer name matches."""

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(
                SimpleNamespace(
                    extract_text=lambda: "证券代码：002727 一心堂 和顺科技股份有限公司"
                ),
            )
        ),
    )

    with pytest.raises(OfficialDisclosureCaptureError, match="does not match"):
        verify_szse_pdf_security_code(
            capture,
            "301237",
            expected_issuer_name="和顺科技",
        )


@pytest.mark.parametrize(
    ("terms", "expected"),
    [
        ("每10股派发现金红利2元，不以公积金转增股本", SecurityDisclosureEventType.CASH_DIVIDEND),
        ("每10股转增4股，不派发现金红利", SecurityDisclosureEventType.STOCK_DIVIDEND),
        ("每10股派发现金红利2元，每10股转增4股", SecurityDisclosureEventType.UNKNOWN),
        ("每10股派现金红利2元，每10股转增4股", SecurityDisclosureEventType.UNKNOWN),
        ("每10股派2元人民币现金，每10股转增4股", SecurityDisclosureEventType.UNKNOWN),
    ],
)
def test_ambiguous_corporate_action_stays_unknown(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    terms: str,
    expected: SecurityDisclosureEventType,
) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "verify_szse_pdf_security_code",
        lambda value, security_code: security_code,
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: f"2026 年中期权益分派实施公告\n{terms}"),)
        ),
    )

    title, event_type = classify_szse_pdf_disclosure(capture, "002727")

    assert title == "2026 年中期权益分派实施公告"
    assert event_type is expected
    if expected is SecurityDisclosureEventType.UNKNOWN:
        assert "SZSE PDF disclosure classification is ambiguous" in caplog.text


def test_verified_legal_opinion_title_is_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit, security-bound legal opinion is a known non-action document."""

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "verify_szse_pdf_security_code",
        lambda value, security_code: security_code,
    )
    title = "2026 年第二次临时股东会法律意见书"
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(
                SimpleNamespace(
                    extract_text=lambda: (
                        "证券代码：301237 股票简称：和顺科技\n" + title + "\n"
                        "浙江律师事务所根据法律规定出具本法律意见书。"
                    )
                ),
            )
        ),
    )

    observed_title, event_type = classify_szse_pdf_disclosure(
        capture,
        "301237",
        expected_listing_title="和顺科技：2026年第二次临时股东会法律意见书",
    )

    assert observed_title == title
    assert event_type is SecurityDisclosureEventType.OTHER


def test_same_security_pdf_with_unmatched_listing_title_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching stock code alone cannot establish a broken title identity chain."""

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    page_text = (
        "证券代码：301237\n关于财务总监、董事会秘书辞任暨董事长代行董事会\n" "秘书职责的公告"
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: page_text),)
        ),
    )

    with pytest.raises(OfficialDisclosureCaptureError, match="title does not match"):
        classify_szse_pdf_disclosure(
            capture,
            "301237",
            expected_issuer_name="和顺科技",
            expected_listing_title="和顺科技：关于为控股子公司提供担保的进展公告",
        )


@pytest.mark.parametrize(
    ("title", "body_evidence", "expected"),
    [
        (
            "关于使用闲置自有资金进行现金管理的进展公告",
            "公告称公司购买理财产品并进行现金管理，说明产品期限和金额。",
            SecurityDisclosureEventType.OTHER,
        ),
        (
            "关于为控股子公司提供担保的进展公告",
            "公司就控股子公司担保事项披露进展情况。",
            SecurityDisclosureEventType.OTHER,
        ),
        (
            "2026年度第二次临时股东会决议公告",
            "公司股东会审议通过相关议案并形成决议。",
            SecurityDisclosureEventType.OTHER,
        ),
        (
            "关于财务总监、董事会秘书辞任的公告",
            "公司董事会秘书辞任，董事长代行董事会秘书职责。",
            SecurityDisclosureEventType.OTHER,
        ),
        (
            "关于控股股东、实际控制人及其一致行动人持股比例被动触及1%及5%整数倍的公告",
            "权益分派及资本公积转增股本导致公司总股本变化，持股比例被动触及1%及5%整数倍；"
            "不触及要约收购，不会导致公司控制权发生变更。",
            SecurityDisclosureEventType.OTHER,
        ),
        (
            "关于控股股东、实际控制人及其一致行动人持股比例被动触及1%及5%整数倍的公告",
            "权益分派导致持股比例被动触及1%及5%整数倍。",
            SecurityDisclosureEventType.UNKNOWN,
        ),
        (
            "2026 年年度报告摘要公告",
            "2026年度报告摘要，披露年度财务报告信息。",
            SecurityDisclosureEventType.UNKNOWN,
        ),
    ],
)
def test_non_distribution_classification_requires_bounded_topic_evidence(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    title: str,
    body_evidence: str,
    expected: SecurityDisclosureEventType,
) -> None:
    """Only explicit source topics with their full body evidence become OTHER."""

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "verify_szse_pdf_security_code",
        lambda value, security_code: security_code,
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(
                SimpleNamespace(extract_text=lambda: f"证券代码：301237\n{title}\n{body_evidence}"),
            )
        ),
    )
    listed_title = (
        "和顺科技：关于控股股东、实际控制人及其一致行动人持股比例" "被动触及1%及5%整数倍的公告"
    )

    observed_title, event_type = classify_szse_pdf_disclosure(
        capture,
        "301237",
        expected_listing_title=listed_title if "持股比例" in title else None,
    )

    assert observed_title == title
    assert event_type is expected
    if expected is SecurityDisclosureEventType.UNKNOWN:
        assert "SZSE PDF disclosure classification is ambiguous" in caplog.text


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("2026 年中期权益分派实施公告（更正后）", SecurityDisclosureEventType.CASH_DIVIDEND),
        (
            "2026 年中期权益分派实施的更正公告",
            SecurityDisclosureEventType.CORRECTION_NOTICE,
        ),
    ],
)
def test_corrected_distribution_and_correction_notice_have_distinct_types(
    monkeypatch: pytest.MonkeyPatch, title: str, expected: SecurityDisclosureEventType
) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "verify_szse_pdf_security_code",
        lambda value, security_code: security_code,
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: f"{title}\n每10股派发现金红利2元"),)
        ),
    )

    observed_title, event_type = classify_szse_pdf_disclosure(capture, "002727")

    assert observed_title == title
    assert event_type is expected


def test_distribution_dates_preserve_source_date_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    monkeypatch.setattr(
        capture_module,
        "verify_szse_pdf_security_code",
        lambda value, security_code: security_code,
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(
                SimpleNamespace(
                    extract_text=lambda: (
                        "股权登记日为：2026 年09 月23 日，"
                        "除权日（除息日）为：2026 年09 月24 日。"
                    )
                ),
            )
        ),
    )

    assert extract_szse_distribution_dates(capture, "002727") == (
        date(2026, 9, 23),
        date(2026, 9, 24),
    )


@pytest.mark.parametrize("phrase", ["派现金红利", "派发现金红利", "派现金股利", "派发现金股利"])
def test_exact_cash_payout_wording_preserves_gross_terms_and_source_dates(
    monkeypatch: pytest.MonkeyPatch, phrase: str
) -> None:
    """The observed official '派现金' variant means the same exact gross cash stage."""
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    text = (
        "证券代码：002727\n2026年半年度权益分派实施公告\n"
        f"每10股{phrase}1.00元（含税）。\n"
        "股权登记日为：2026年11月12日，除权除息日为：2026年11月13日。\n"
        "现金红利将于2026年11月13日派发。暂不扣缴个人所得税，待个人转让股票时计算。"
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: text),)
        ),
    )
    _, kind = classify_szse_pdf_disclosure(capture, "002727")
    assert kind is SecurityDisclosureEventType.CASH_DIVIDEND
    terms = extract_szse_distribution_terms(capture, "002727")
    assert terms is not None
    assert terms.cash_per_ten == Decimal("1.00")
    assert terms.shares_per_ten is None
    assert terms.record_date == date(2026, 11, 12)
    assert terms.ex_date == terms.payment_date == date(2026, 11, 13)
    assert terms.tax_treatment == "deferred_withholding"


@pytest.mark.parametrize(
    ("cash_text", "expected"),
    [
        ("每10股派1.000000元人民币现金（含税）", Decimal("1.00")),
        (
            "原方案每10股派现金红利1.00元；本次每10股派1.000000元人民币现金（含税）",
            Decimal("1.00"),
        ),
        (
            "原方案每10股派现金红利2.00元；本次每10股派1.000000元人民币现金（含税）",
            None,
        ),
    ],
)
def test_postfix_cash_wording_cannot_hide_a_conflicting_earlier_proposal(
    monkeypatch: pytest.MonkeyPatch, cash_text: str, expected: Decimal | None
) -> None:
    """A prior proposal cannot substitute for a different implementation amount."""
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _response(_BODY))
    capture = capture_official_szse_pdf(_URL)
    text = (
        "证券代码：002727\n2026年半年度权益分派实施公告\n"
        f"{cash_text}。\n"
        "股权登记日为：2026年11月12日，除权除息日为：2026年11月13日。\n"
        "现金红利将于2026年11月13日派发。暂不扣缴个人所得税，待个人转让股票时计算。"
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(
            pages=(SimpleNamespace(extract_text=lambda: text),)
        ),
    )
    terms = extract_szse_distribution_terms(capture, "002727")
    if expected is None:
        assert terms is None
    else:
        assert terms is not None
        assert terms.cash_per_ten == expected


@pytest.mark.parametrize(
    ("date_text", "delivery", "sellable"),
    [
        (
            "新增股份到账日为：2026年9月24日。新增可流通股份上市日为：2026年9月25日。",
            date(2026, 9, 24),
            date(2026, 9, 25),
        ),
        ("", None, None),
        (
            "新增股份到账日为：2026年9月24日。新增股份到账日为：2026年9月25日。新增股份上市日为：2026年9月25日。",
            None,
            date(2026, 9, 25),
        ),
    ],
)
def test_share_delivery_and_sellable_dates_are_independent_explicit_facts(
    monkeypatch, date_text, delivery, sellable
):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _response(_BODY))
    captured = capture_official_szse_pdf(_URL)
    text = (
        "证券代码：002727\n2026年半年度权益分派实施公告\n每10股转增4股，不派发现金红利。不涉及扣税情形。"
        "股权登记日为：2026年9月23日。除权除息日为：2026年9月24日。" + date_text
    )
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *a, **kw: SimpleNamespace(pages=(SimpleNamespace(extract_text=lambda: text),)),
    )
    terms = extract_szse_distribution_terms(captured, "002727")
    assert terms is not None
    assert terms.share_delivery_date == delivery
    assert terms.share_sellable_date == sellable
    assert terms.tax_treatment == "not_applicable"


def test_notification_title_can_be_read_without_promoting_unknown_category(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _response(_BODY))
    captured = capture_official_szse_pdf(_URL)
    text = "证券代码：002727\n关于召开2026年第五次临时股东会的通知\n会议时间及投票方式。"
    monkeypatch.setattr(
        capture_module,
        "PdfReader",
        lambda *a, **kw: SimpleNamespace(pages=(SimpleNamespace(extract_text=lambda: text),)),
    )
    title, kind = classify_szse_pdf_disclosure(
        captured, "002727", expected_listing_title="一心堂：关于召开2026年第五次临时股东会的通知"
    )
    assert title == "关于召开2026年第五次临时股东会的通知"
    assert kind is SecurityDisclosureEventType.UNKNOWN
