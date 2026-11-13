"""Conservative text extraction for official SZSE rights notices."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from re import Pattern

from apps.data_center.domain.szse_rights_terms import (
    SzseRightsCompletionTerms,
    SzseRightsOfferingTerms,
)

_NUMBER = r"([0-9]+(?:\.[0-9]+)?)"
_DATE = r"([0-9]{4})\s*年\s*([0-9]{1,2})\s*月\s*([0-9]{1,2})\s*日"
_SECURITY_HEADER = re.compile(
    r"(?m)^[ \t]*(?:证券代码|股票代码)[ \t]*[:：][ \t]*([0-9]{6})(?![0-9])"
)
_RECORD_DATE = re.compile(r"股权登记日\s*(?:为\s*)?(?:[:：]\s*)?" + _DATE)
_SUBSCRIPTION_RANGE = re.compile(
    r"配股缴款(?:起止日期|时间|日期|期限)\s*[:：]?\s*(?:刊登提示性公告\s*)?"
    + _DATE
    + r"(?:\s*[（(][^）)]*[）)])?\s*(?:起\s*)?(?:至|到|－|—|~|～)\s*"
    + _DATE
)
_SUBSCRIPTION_END = re.compile(r"(?:认购|配股)缴款结束日\s*[:：]?\s*[（(]?\s*" + _DATE)
_ANNOUNCED_RATIO_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"(?:按照|按|以)\s*每?\s*10\s*股\s*配(?:售)?\s*" + _NUMBER + r"\s*股"),
    re.compile(r"(?:按|按照)\s*10\s*[:：]\s*" + _NUMBER + r"\s*比例"),
)
_ACTUAL_RATIO = re.compile(
    r"实际(?:配股|配售)比例\s*相当于\s*每\s*10\s*股\s*配售\s*" + _NUMBER + r"\s*股"
)
_PRICE_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(
        r"(?:配股|发行|配售|认购)?价格\s*(?:为|是|[:：])?\s*"
        r"(?:(?P<cny>人民币)\s*)?(?P<amount>[0-9]+(?:\.[0-9]+)?)\s*元"
    ),
    re.compile(r"每股\s*(?P<cny>人民币)\s*" r"(?P<amount>[0-9]+(?:\.[0-9]+)?)\s*元"),
)
_CNY_GLOSSARY = re.compile(r"元\s*指\s*人民币元")
_NON_CNY_CURRENCY = re.compile(r"(?:港币|港元|HKD|美元|USD|欧元|EUR|日元|JPY)", re.IGNORECASE)
_SUCCESS = re.compile(r"(?:本次配股发行成功|配股发行成功|本次配股成功)")
_CONDITIONAL_SUCCESS_PREFIX = re.compile(
    r"(?:若|如果|倘若|倘|假如|如若|如(?=本次|配股|条件|达到|满足|符合)|一旦|只有|除非|"
    r"是否|不排除|可能|预计|假设|推测)"
)
_CONDITIONAL_OR_UNCONFIRMED_SUCCESS_SUFFIX = re.compile(
    r"^[\s,，]*(?:(?:的\s*)?(?:条件|前提)(?:是|为|包括)?|(?:尚待|尚未|仍未|并未|未|待|有待)"
    r"(?:确认|完成|确定|成立|实现)?|(?:并非|并不|不是|不代表|不能|无法|是否|与否)|"
    r"(?:的)?(?:风险|可能|可能性|不确定性))"
)
_NEGATED_SUCCESS_PREFIX = re.compile(r"(?:并非|并不是|不是|不能证明|不代表|不能确认|无法确认)")
_HYPOTHETICAL_FAILURE_SUFFIX = re.compile(
    r"^\s*(?:的\s*)?(?:风险|可能|可能性|不确定性|情形|情况下)"
)
_NEGATIVE_SUCCESS = re.compile(
    r"(?:本次)?配股(?:发行)?(?:(?:并)?未|没有|尚未|未能|不(?:会)?)(?:成功|完成)|"
    r"(?:本次)?配股(?:发行)?失败"
)
_SENTENCE_BOUNDARIES = ("。", "；", ";", "！", "!", "？", "?", "\n\n")
_ACTUAL_EX_DATE = re.compile(
    r"(?:本公告披露当日|本公告刊登当日|本公告发布当日)\s*[（(]\s*"
    + _DATE
    + r"(?:\s*[,，]\s*[^）)]*)?[）)]\s*即为发行成功的"
    r"(?:除权基准日|除权日)(?:\s*\n[ \t]*[0-9]{1,3}[ \t]*\n)?\s*[（(]\s*配股除权日\s*[）)]"
)


def _valid_source_code(value: object) -> bool:
    """Return whether the requested source identity is a six-digit code."""
    return (
        type(value) is str
        and len(value) == 6
        and all("0" <= character <= "9" for character in value)
    )


def _has_exact_security_header(text: str, expected_code: str) -> bool:
    """Require the document header code, excluding rights subscription codes."""
    codes = {match.group(1) for match in _SECURITY_HEADER.finditer(text)}
    return bool(codes) and codes == {expected_code}


def _date_from_groups(year: str, month: str, day: str) -> date | None:
    """Build a calendar date from one exact Chinese date token."""
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _unique_date(text: str, pattern: Pattern[str]) -> date | None:
    """Return one unambiguous date value from contextual date matches."""
    found: set[date] = set()
    for match in pattern.finditer(text):
        parsed = _date_from_groups(match.group(1), match.group(2), match.group(3))
        if parsed is None:
            return None
        found.add(parsed)
    return next(iter(found)) if len(found) == 1 else None


def _unique_subscription_range(text: str) -> tuple[date, date] | None:
    """Return one unambiguous inclusive subscription date range."""
    found: set[tuple[date, date]] = set()
    for match in _SUBSCRIPTION_RANGE.finditer(text):
        start = _date_from_groups(match.group(1), match.group(2), match.group(3))
        end = _date_from_groups(match.group(4), match.group(5), match.group(6))
        if start is None or end is None or start > end:
            return None
        found.add((start, end))
    return next(iter(found)) if len(found) == 1 else None


def _decimal_from_token(token: str) -> Decimal | None:
    """Parse a bounded, non-exponent decimal token without float conversion."""
    if len(token) > 25:
        return None
    try:
        value = Decimal(token)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0:
        return None
    parts = value.as_tuple()
    exponent = parts.exponent
    if not isinstance(exponent, int):
        return None
    if len(parts.digits) > 24 or abs(exponent) > 18:
        return None
    if not -18 <= value.adjusted() <= 18:
        return None
    return value


def _unique_decimal(text: str, patterns: tuple[Pattern[str], ...]) -> Decimal | None:
    """Return one unambiguous positive decimal from source-context patterns."""
    found: set[Decimal] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            value = _decimal_from_token(match.group(1))
            if value is None:
                return None
            found.add(value)
    return next(iter(found)) if len(found) == 1 else None


def _unique_cny_price(text: str) -> Decimal | None:
    """Require one price and explicit source evidence that its unit is CNY."""
    found: set[Decimal] = set()
    explicitly_cny = bool(_CNY_GLOSSARY.search(text))
    for pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(text):
            if _has_local_non_cny_currency(text, match.start(), match.end()):
                return None
            value = _decimal_from_token(match.group("amount"))
            if value is None:
                return None
            found.add(value)
            explicitly_cny = explicitly_cny or match.group("cny") is not None
    if len(found) != 1 or not explicitly_cny:
        return None
    value = next(iter(found))
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        return None
    digits = value.as_tuple().digits
    while exponent < -2 and digits and digits[-1] == 0:
        digits = digits[:-1]
        exponent += 1
    return value if exponent >= -2 else None


def _has_local_non_cny_currency(text: str, start: int, end: int) -> bool:
    """Reject foreign-currency labels attached to a source price clause."""
    boundaries = ("。", "；", ";", "，", ",", "\n\n")
    left = max((text.rfind(boundary, 0, start) for boundary in boundaries), default=-1) + 1
    right_candidates = tuple(
        index for boundary in boundaries if (index := text.find(boundary, end)) >= 0
    )
    right = min(right_candidates, default=len(text))
    return bool(_NON_CNY_CURRENCY.search(text[left:right]))


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Return the clause bounds around a result phrase, retaining comma conditions."""
    previous = max(
        ((text.rfind(mark, 0, start), len(mark)) for mark in _SENTENCE_BOUNDARIES),
        default=(-1, 0),
        key=lambda item: item[0],
    )
    following = tuple(
        index for mark in _SENTENCE_BOUNDARIES if (index := text.find(mark, end)) >= 0
    )
    return previous[0] + previous[1], min(following, default=len(text))


def _is_conditional_prefix(prefix: str) -> bool:
    """Return whether a result is asserted only under a condition or forecast."""
    compact = re.sub(r"\s+", "", prefix)
    return bool(_CONDITIONAL_SUCCESS_PREFIX.search(compact))


def _has_confirmed_success(text: str) -> bool:
    """Accept an unconditional positive result and reject any conflicting failure."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    saw_positive = False
    for match in _SUCCESS.finditer(normalized):
        segment_start, segment_end = _sentence_bounds(normalized, match.start(), match.end())
        prefix = normalized[segment_start : match.start()]
        suffix = re.sub(r"\s+", "", normalized[match.end() : segment_end])
        if _is_conditional_prefix(prefix):
            continue
        if _NEGATED_SUCCESS_PREFIX.search(re.sub(r"\s+", "", prefix)):
            return False
        if _CONDITIONAL_OR_UNCONFIRMED_SUCCESS_SUFFIX.match(suffix):
            continue
        saw_positive = True
    if not saw_positive:
        return False
    for match in _NEGATIVE_SUCCESS.finditer(normalized):
        segment_start, segment_end = _sentence_bounds(normalized, match.start(), match.end())
        prefix = normalized[segment_start : match.start()]
        suffix = re.sub(r"\s+", "", normalized[match.end() : segment_end])
        if not _is_conditional_prefix(prefix) and not _HYPOTHETICAL_FAILURE_SUFFIX.match(suffix):
            return False
    return True


def extract_szse_rights_offering_terms(
    text: str, *, source_security_code: str
) -> SzseRightsOfferingTerms | None:
    """Extract explicit offering terms from a single SZSE source document.

    Dates remain date-only inclusive endpoints. The parser returns ``None`` if
    the security header, dates, ratio, currency, or price is missing or conflicts.
    """
    if not isinstance(text, str) or not _valid_source_code(source_security_code):
        return None
    if not _has_exact_security_header(text, source_security_code):
        return None
    record_date = _unique_date(text, _RECORD_DATE)
    subscription_range = _unique_subscription_range(text)
    offered_ratio = _unique_decimal(text, _ANNOUNCED_RATIO_PATTERNS)
    price = _unique_cny_price(text)
    if record_date is None or subscription_range is None:
        return None
    if offered_ratio is None or price is None:
        return None
    try:
        return SzseRightsOfferingTerms(
            source_security_code=source_security_code,
            record_date=record_date,
            subscription_start_date=subscription_range[0],
            subscription_end_date=subscription_range[1],
            offered_rights_per_ten=offered_ratio,
            subscription_price_cny_per_share=price,
        )
    except ValueError:
        return None


def extract_szse_rights_completion_terms(
    text: str, *, source_security_code: str
) -> SzseRightsCompletionTerms | None:
    """Extract only a successful result with an explicitly named actual ex-date.

    This parses facts within one result document and does not associate it with
    a separate offering notice or infer the ex-rights date from a schedule.
    """
    if not isinstance(text, str) or not _valid_source_code(source_security_code):
        return None
    if not _has_exact_security_header(text, source_security_code):
        return None
    if not _has_confirmed_success(text):
        return None
    record_date = _unique_date(text, _RECORD_DATE)
    subscription_end = _unique_date(text, _SUBSCRIPTION_END)
    offered_ratio = _unique_decimal(text, _ANNOUNCED_RATIO_PATTERNS)
    price = _unique_cny_price(text)
    actual_ratio = _unique_decimal(text, (_ACTUAL_RATIO,))
    actual_ex_date = _unique_date(text, _ACTUAL_EX_DATE)
    if any(
        value is None
        for value in (
            record_date,
            subscription_end,
            offered_ratio,
            price,
            actual_ratio,
            actual_ex_date,
        )
    ):
        return None
    assert record_date is not None
    assert subscription_end is not None
    assert offered_ratio is not None
    assert price is not None
    assert actual_ratio is not None
    assert actual_ex_date is not None
    try:
        return SzseRightsCompletionTerms(
            source_security_code=source_security_code,
            record_date=record_date,
            subscription_end_date=subscription_end,
            offered_rights_per_ten=offered_ratio,
            subscription_price_cny_per_share=price,
            actual_aggregate_rights_per_ten=actual_ratio,
            actual_ex_rights_date=actual_ex_date,
        )
    except ValueError:
        return None
