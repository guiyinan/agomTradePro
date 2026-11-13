"""Pure conservative terms extraction for SZSE rights issuance notices."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from typing import cast

import pytest

from apps.data_center.domain.szse_rights_terms import (
    SzseRightsCompletionTerms,
    SzseRightsOfferingTerms,
)
from apps.data_center.infrastructure.official_szse_rights_terms import (
    extract_szse_rights_completion_terms,
    extract_szse_rights_offering_terms,
)

_OFFERING_TEXT = """
证券代码：300176 证券简称：鸿特科技 公告编号：2026-042
广东鸿特科技股份有限公司配股发行公告
元 指 人民币元
本次配股以股权登记日2026年8月12日收市后发行人总股本为基数，
按每10股配售4股的比例向全体A股股东配售。
本次配股价格为3.36元/股。
配股缴款起止日期：2026年8月13日（R+1日）至2026年8月19日（R+5日）。
"""

_COMPLETION_TEXT = """
证券代码：300176 证券简称：鸿特科技 公告编号：2026-050
广东鸿特科技股份有限公司配股发行结果公告
本次配股发行成功。
本次配股以股权登记日2026年8月12日（R日）收市后公司总股本为基数，
按每10股配售4股的比例配售，发行价格为3.36元/股。
截至认购缴款结束日（2026年8月19日，R+5日），本次配股发行成功。
本公告披露当日（2026年8月21日，R+7日）即为发行成功的除权基准日
（配股除权日），实际配股比例相当于每10股配售3.722702股。
本次配股获配股份上市时间将另行公告。
本次鸿特科技原股东按照每股人民币3.36元的价格，以每10股配售4股的比例参与配售。
"""


def _valid_offering_terms() -> SzseRightsOfferingTerms:
    """Build a valid domain value for constructor boundary tests."""
    return SzseRightsOfferingTerms(
        source_security_code="300176",
        record_date=date(2026, 8, 12),
        subscription_start_date=date(2026, 8, 13),
        subscription_end_date=date(2026, 8, 19),
        offered_rights_per_ten=Decimal("4"),
        subscription_price_cny_per_share=Decimal("3.3600"),
    )


def _valid_completion_terms() -> SzseRightsCompletionTerms:
    """Build a valid domain value for successful-result boundary tests."""
    return SzseRightsCompletionTerms(
        source_security_code="300176",
        record_date=date(2026, 8, 12),
        subscription_end_date=date(2026, 8, 19),
        offered_rights_per_ten=Decimal("4"),
        subscription_price_cny_per_share=Decimal("3.36"),
        actual_aggregate_rights_per_ten=Decimal("3.722702"),
        actual_ex_rights_date=date(2026, 8, 21),
    )


def test_extract_offering_terms_from_exact_security_header_and_inclusive_period() -> None:
    terms = extract_szse_rights_offering_terms(_OFFERING_TEXT, source_security_code="300176")

    assert terms == SzseRightsOfferingTerms(
        source_security_code="300176",
        record_date=date(2026, 8, 12),
        subscription_start_date=date(2026, 8, 13),
        subscription_end_date=date(2026, 8, 19),
        offered_rights_per_ten=Decimal("4"),
        subscription_price_cny_per_share=Decimal("3.36"),
    )


def test_extract_offering_accepts_ratio_colon_variant_without_using_rights_code() -> None:
    text = _OFFERING_TEXT.replace("按每10股配售4股的比例", "按10：4比例").replace(
        "配股缴款起止日期", "配股缴款时间"
    )

    terms = extract_szse_rights_offering_terms(text, source_security_code="300176")

    assert terms is not None
    assert terms.offered_rights_per_ten == Decimal("4")


@pytest.mark.parametrize(
    ("text", "source_security_code"),
    [
        (_OFFERING_TEXT.replace("证券代码：300176", "配股代码：380176"), "300176"),
        (_OFFERING_TEXT.replace("证券代码：300176", "证券代码：300177"), "300176"),
        (_OFFERING_TEXT, "30017"),
    ],
)
def test_offering_requires_exact_six_digit_security_header(
    text: str, source_security_code: str
) -> None:
    assert (
        extract_szse_rights_offering_terms(text, source_security_code=source_security_code) is None
    )


def test_offering_requires_explicit_cny_evidence() -> None:
    text = _OFFERING_TEXT.replace("元 指 人民币元", "元 指 元")

    assert extract_szse_rights_offering_terms(text, source_security_code="300176") is None


def test_offering_rejects_conflicting_ratio_price_or_dates() -> None:
    conflicting_ratio = _OFFERING_TEXT + "按照10：5比例向股东配售。"
    conflicting_price = _OFFERING_TEXT + "本次配股价格为3.37元/股。"
    conflicting_date = _OFFERING_TEXT + "本次配股股权登记日2026年8月13日。"

    assert (
        extract_szse_rights_offering_terms(conflicting_ratio, source_security_code="300176") is None
    )
    assert (
        extract_szse_rights_offering_terms(conflicting_price, source_security_code="300176") is None
    )
    assert (
        extract_szse_rights_offering_terms(conflicting_date, source_security_code="300176") is None
    )


def test_offering_rejects_invalid_or_reversed_subscription_dates() -> None:
    invalid_date = _OFFERING_TEXT.replace("2026年8月19日", "2026年2月30日")
    reversed_period = _OFFERING_TEXT.replace(
        "2026年8月13日（R+1日）至2026年8月19日（R+5日）",
        "2026年8月20日（R+1日）至2026年8月19日（R+5日）",
    )

    assert extract_szse_rights_offering_terms(invalid_date, source_security_code="300176") is None
    assert (
        extract_szse_rights_offering_terms(reversed_period, source_security_code="300176") is None
    )


def test_offering_rejects_record_date_after_subscription_interval() -> None:
    text = _OFFERING_TEXT.replace("股权登记日2026年8月12日", "股权登记日2026年8月20日")

    assert extract_szse_rights_offering_terms(text, source_security_code="300176") is None


def test_extract_completion_keeps_success_ex_date_and_aggregate_ratio_distinct() -> None:
    terms = extract_szse_rights_completion_terms(_COMPLETION_TEXT, source_security_code="300176")

    assert terms == SzseRightsCompletionTerms(
        source_security_code="300176",
        record_date=date(2026, 8, 12),
        subscription_end_date=date(2026, 8, 19),
        offered_rights_per_ten=Decimal("4"),
        subscription_price_cny_per_share=Decimal("3.36"),
        actual_aggregate_rights_per_ten=Decimal("3.722702"),
        actual_ex_rights_date=date(2026, 8, 21),
    )


def test_completion_requires_confirmed_success_not_conditional_schedule() -> None:
    scheduled = _OFFERING_TEXT + ("如本次配股成功，鸿特科技股票将于2026年8月21日进行除权交易。")

    assert extract_szse_rights_completion_terms(scheduled, source_security_code="300176") is None


def test_completion_rejects_explicit_negated_success() -> None:
    failed = _COMPLETION_TEXT.replace("本次配股发行成功。", "本次配股发行未成功。")

    assert extract_szse_rights_completion_terms(failed, source_security_code="300176") is None


@pytest.mark.parametrize(
    "statement",
    [
        "并非本次配股发行成功。",
        "不能证明本次配股发行成功。",
        "本次配股发行成功，尚待确认。",
        "本次配股发行成功，并未确认。",
    ],
)
def test_completion_rejects_negated_or_unconfirmed_success_conclusions(statement: str) -> None:
    """Repeating a negated result cannot establish a completed offering."""
    text = _COMPLETION_TEXT.replace("本次配股发行成功。", statement)
    assert extract_szse_rights_completion_terms(text, source_security_code="300176") is None


def test_offering_rejects_record_date_inside_subscription_interval() -> None:
    """Registration cannot first occur after subscription has already started."""
    text = _OFFERING_TEXT.replace("股权登记日2026年8月12日", "股权登记日2026年8月14日")
    assert extract_szse_rights_offering_terms(text, source_security_code="300176") is None
    with pytest.raises(ValueError):
        replace(_valid_offering_terms(), record_date=date(2026, 8, 14))


@pytest.mark.parametrize(
    "label,separator",
    [
        ("配股缴款时间\n", "起至"),
        ("配股缴款起止日期\n刊登提示性公告\n", "\n至"),
    ],
)
def test_offering_reads_explicit_original_prose_and_table_layout(
    label: str, separator: str
) -> None:
    """Both supported source layouts retain the actual subscription interval."""
    text = _OFFERING_TEXT.replace("配股缴款起止日期：", label).replace(
        "至2026年8月19日", separator + "2026年8月19日"
    )
    terms = extract_szse_rights_offering_terms(text, source_security_code="300176")
    assert terms is not None and terms.subscription_end_date == date(2026, 8, 19)


def test_completion_reads_original_ratio_wording_and_page_break() -> None:
    """A page number within the same explicit ex-date sentence supplies no date."""
    text = _COMPLETION_TEXT.replace("按每10股配售4股", "按每10股配4股").replace(
        "除权基准日\n（配股除权日）", "除权基准日\n3\n（配股除权日）"
    )
    terms = extract_szse_rights_completion_terms(text, source_security_code="300176")
    assert terms is not None and terms.actual_ex_rights_date == date(2026, 8, 21)


def test_completion_rejects_condition_carrying_across_comma() -> None:
    conditional = _COMPLETION_TEXT.replace("本次配股发行成功。", "若达到条件，本次配股发行成功。")

    assert extract_szse_rights_completion_terms(conditional, source_security_code="300176") is None


def test_completion_rejects_condition_carrying_across_line_wrap() -> None:
    conditional = _COMPLETION_TEXT.replace("本次配股发行成功。", "若达到条件，\n本次配股发行成功。")

    assert extract_szse_rights_completion_terms(conditional, source_security_code="300176") is None


def test_completion_rejects_success_phrase_that_introduces_conditions() -> None:
    conditional = _COMPLETION_TEXT.replace(
        "本次配股发行成功。", "本次配股发行成功的条件是达到认购比例。"
    )

    assert extract_szse_rights_completion_terms(conditional, source_security_code="300176") is None


def test_completion_rejects_success_phrase_followed_by_unconfirmed_result() -> None:
    unconfirmed = _COMPLETION_TEXT.replace("本次配股发行成功。", "本次配股发行成功尚未确认。")

    assert extract_szse_rights_completion_terms(unconfirmed, source_security_code="300176") is None


def test_completion_accepts_unconditional_success_after_separate_risk_clause() -> None:
    text = "若发行未成功，公司将依规处理。\n\n" + _COMPLETION_TEXT

    assert extract_szse_rights_completion_terms(text, source_security_code="300176") is not None


def test_completion_accepts_actual_success_despite_separate_conditional_sentence() -> None:
    text = _COMPLETION_TEXT + "\n\n若本次配股发行未成功，公司将依规处理。"

    assert extract_szse_rights_completion_terms(text, source_security_code="300176") is not None


def test_completion_accepts_actual_success_with_separate_failure_risk_paragraph() -> None:
    text = _COMPLETION_TEXT + "\n\n本次配股发行失败的风险已在方案公告中说明。"

    assert extract_szse_rights_completion_terms(text, source_security_code="300176") is not None


def test_completion_rejects_success_phrase_as_only_a_possibility() -> None:
    possible = _COMPLETION_TEXT.replace("本次配股发行成功。", "本次配股发行成功的可能性较大。")

    assert extract_szse_rights_completion_terms(possible, source_security_code="300176") is None


def test_completion_rejects_conflicting_unconditional_failure() -> None:
    conflicting = _COMPLETION_TEXT + "本次配股发行未成功。"

    assert extract_szse_rights_completion_terms(conflicting, source_security_code="300176") is None


@pytest.mark.parametrize(
    "currency_clause", ["3.36元/股（港币）", "港币3.36元/股", "3.36元/股（\n港币）"]
)
def test_offering_rejects_local_non_cny_price_despite_document_glossary(
    currency_clause: str,
) -> None:
    text = _OFFERING_TEXT.replace("3.36元/股", currency_clause)

    assert extract_szse_rights_offering_terms(text, source_security_code="300176") is None


@pytest.mark.parametrize("source_security_code", [None, 300176, "", "30017", "٣٠٠١٧٦"])
def test_extractors_fail_closed_for_malformed_requested_security_code(
    source_security_code: object,
) -> None:
    requested_code = cast(str, source_security_code)

    assert (
        extract_szse_rights_offering_terms(_OFFERING_TEXT, source_security_code=requested_code)
        is None
    )
    assert (
        extract_szse_rights_completion_terms(_COMPLETION_TEXT, source_security_code=requested_code)
        is None
    )


def test_completion_requires_official_security_header_not_allotment_code() -> None:
    text = _COMPLETION_TEXT.replace("证券代码：300176", "配股代码：380176")

    assert extract_szse_rights_completion_terms(text, source_security_code="300176") is None


def test_completion_rejects_missing_success_ex_date_or_result_terms() -> None:
    no_success = _COMPLETION_TEXT.replace("本次配股发行成功", "本次配股尚未完成")
    no_ex_date = _COMPLETION_TEXT.replace("即为发行成功的除权基准日", "即为结果公告日")
    no_actual_ratio = _COMPLETION_TEXT.replace(
        "实际配股比例相当于每10股配售3.722702股。", "实际配股比例待后续公告。"
    )
    no_price = _COMPLETION_TEXT.replace("每股人民币3.36元", "每股价格待后续公告")

    for text in (no_success, no_ex_date, no_actual_ratio, no_price):
        assert extract_szse_rights_completion_terms(text, source_security_code="300176") is None


def test_completion_rejects_conflicting_confirmed_dates_or_ratios() -> None:
    conflicting_ex_date = _COMPLETION_TEXT + (
        "本公告披露当日（2026年8月22日，R+8日）即为发行成功的除权基准日" "（配股除权日）。"
    )
    conflicting_aggregate_ratio = _COMPLETION_TEXT + ("实际配股比例相当于每10股配售3.7股。")
    conflicting_end_date = _COMPLETION_TEXT + "截至认购缴款结束日（2026年8月20日）。"

    assert (
        extract_szse_rights_completion_terms(conflicting_ex_date, source_security_code="300176")
        is None
    )
    assert (
        extract_szse_rights_completion_terms(
            conflicting_aggregate_ratio, source_security_code="300176"
        )
        is None
    )
    assert (
        extract_szse_rights_completion_terms(conflicting_end_date, source_security_code="300176")
        is None
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_security_code", None),
        ("source_security_code", "٣٠٠١٧٦"),
        ("record_date", datetime(2026, 8, 12)),
        ("subscription_start_date", date(2026, 8, 20)),
        ("offered_rights_per_ten", 4.0),
        ("offered_rights_per_ten", Decimal("NaN")),
        ("offered_rights_per_ten", Decimal("1e19")),
        ("subscription_price_cny_per_share", 3.36),
        ("subscription_price_cny_per_share", Decimal("3.361")),
    ],
)
def test_offering_domain_rejects_invalid_identity_dates_and_amounts(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        replace(_valid_offering_terms(), **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_security_code", None),
        ("source_security_code", "3001760"),
        ("actual_ex_rights_date", datetime(2026, 8, 21)),
        ("subscription_end_date", date(2026, 8, 11)),
        ("actual_ex_rights_date", date(2026, 8, 18)),
        ("actual_aggregate_rights_per_ten", Decimal("0")),
        ("actual_aggregate_rights_per_ten", Decimal("NaN")),
        ("subscription_price_cny_per_share", Decimal("3.361")),
    ],
)
def test_completion_domain_rejects_invalid_identity_dates_and_amounts(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        replace(_valid_completion_terms(), **{field: value})
