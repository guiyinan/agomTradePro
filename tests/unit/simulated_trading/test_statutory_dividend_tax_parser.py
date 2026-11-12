"""Synthetic clause fixtures exercise supported grammar, not official qualification."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxPolicy,
    DeferredDividendTaxValidationError,
    HoldingPeriodTaxBand,
    TaxRoundingMode,
)
from apps.simulated_trading.infrastructure.statutory_dividend_tax_parser import (
    _percentage,
    parse_statutory_dividend_tax_terms,
)
from core.exceptions import DataValidationError

RATE_PARAGRAPHS = (
    "一、个人从公开发行和转让市场取得的上市公司股票，持股期限超过1年的，股息红利所得暂免征收个人所得税。",
    "个人从公开发行和转让市场取得的上市公司股票，持股期限在1个月以内（含1个月）的，其股息红利所得全额计入应纳税所得额；持股期限在1个月以上至1年（含1年）的，暂减按50%计入应纳税所得额；上述所得统一适用20%的税率计征个人所得税。",
    "二、上市公司派发股息红利时，对个人持股1年以内（含1年）的，上市公司暂不扣缴个人所得税；待个人转让股票时，证券登记结算公司根据其持股期限计算应纳税额，由证券公司等股份托管机构从个人资金账户中扣收并划付证券登记结算公司，后续划转程序依明示通知执行。",
    "三、上市公司股息红利差别化个人所得税政策其他有关操作事项，按照《合成操作通知》（SYNTHETIC-MECHANICS）的相关规定执行。",
    "五、本通知自2015年9月8日起施行。",
    "上市公司派发股息红利，股权登记日在2015年9月8日之后的，股息红利所得按照本通知的规定执行。本通知实施之日个人投资者证券账户已持有的上市公司股票，其持股时间自取得之日起计算。",
)
MECHANICS_PARAGRAPHS = (
    "前款所称上市公司是指在上海证券交易所、深圳证券交易所挂牌交易的上市公司；持股期限是指个人从公开发行和转让市场取得上市公司股票之日至转让交割该股票之日前一日的持有时间。",
    "三、个人转让股票时，按照先进先出的原则计算持股期限，即证券账户中先取得的股票视为先转让。",
    "应纳税所得额以个人投资者证券账户为单位计算，持股数量以每日日终结算后个人投资者证券账户的持有记录为准，证券账户取得或转让的股份数为每日日终结算后的净增（减）股份数。",
    "八、本通知所称年（月）是指自然年（月），即持股一年是指从上一年某月某日至本年同月同日的前一日连续持股，持股一个月是指从上月某日至本月同日的前一日连续持股。",
)


def _html(number: str, paragraphs: tuple[str, ...]) -> bytes:
    return (
        "<html><meta charset='utf-8'><h1>"
        + number
        + "</h1>"
        + "".join(f"<p>{p}</p>" for p in paragraphs)
        + "</html>"
    ).encode("utf-8")


def _parse(
    rate: tuple[str, ...] = RATE_PARAGRAPHS, mechanics: tuple[str, ...] = MECHANICS_PARAGRAPHS
) -> object:
    return parse_statutory_dividend_tax_terms(
        rate_document_body=_html("SYNTHETIC-RATE", rate),
        rate_legal_number="SYNTHETIC-RATE",
        rate_source_revision_sha256="a" * 64,
        mechanics_document_body=_html("SYNTHETIC-MECHANICS", mechanics),
        mechanics_legal_number="SYNTHETIC-MECHANICS",
        mechanics_source_revision_sha256="b" * 64,
        max_body_bytes=16384,
    )


def _policy() -> DeferredDividendTaxPolicy:
    return DeferredDividendTaxPolicy(
        policy_id="synthetic-policy",
        version="v1",
        effective_from=date(2015, 9, 9),
        effective_through=None,
        source_identity="synthetic-unqualified-source",
        source_sha256="c" * 64,
        bands=(
            HoldingPeriodTaxBand("short", 1, Decimal("1"), Decimal("0.2")),
            HoldingPeriodTaxBand("middle", 12, Decimal("0.5"), Decimal("0.2")),
            HoldingPeriodTaxBand("long", None, Decimal("0"), Decimal("0.2")),
        ),
        currency_quantum=Decimal("0.01"),
        rounding_mode=TaxRoundingMode.HALF_UP,
    )


def test_supported_clauses_derive_terms_and_reconcile_explicit_policy() -> None:
    result = _parse()
    assert result.short_maximum_months == 1
    assert result.middle_maximum_months == 12
    assert result.middle_taxable_ratio == Decimal("0.5")
    assert result.withholding_rate == Decimal("0.2")
    assert result.record_date_exclusive_boundary == date(2015, 9, 8)
    assert len(result.clauses) == 9
    result.validate_policy(_policy())


def test_numeric_rates_are_read_from_source_not_built_in() -> None:
    result = _parse(tuple(p.replace("50%", "40%").replace("20%", "18%") for p in RATE_PARAGRAPHS))
    assert result.middle_taxable_ratio == Decimal("0.4")
    assert result.withholding_rate == Decimal("0.18")
    with pytest.raises(DeferredDividendTaxValidationError):
        result.validate_policy(_policy())


@pytest.mark.parametrize("position", range(6))
def test_missing_rate_or_operating_clause_blocks(position: int) -> None:
    with pytest.raises(DataValidationError):
        _parse(RATE_PARAGRAPHS[:position] + RATE_PARAGRAPHS[position + 1 :])


@pytest.mark.parametrize("position", range(4))
def test_missing_mechanics_clause_blocks(position: int) -> None:
    with pytest.raises(DataValidationError):
        _parse(mechanics=MECHANICS_PARAGRAPHS[:position] + MECHANICS_PARAGRAPHS[position + 1 :])


def test_duplicate_rate_clause_is_ambiguous() -> None:
    with pytest.raises(DataValidationError):
        _parse(RATE_PARAGRAPHS + (RATE_PARAGRAPHS[1],))


def test_mismatched_inclusive_threshold_blocks() -> None:
    with pytest.raises(DataValidationError):
        _parse(tuple(p.replace("（含1个月）", "（含2个月）") for p in RATE_PARAGRAPHS))


def test_superseded_mechanics_document_cannot_supply_missing_exemption() -> None:
    with pytest.raises(DataValidationError):
        _parse(MECHANICS_PARAGRAPHS)


def test_wrong_cross_reference_blocks() -> None:
    with pytest.raises(DataValidationError):
        _parse(
            tuple(
                p.replace("（SYNTHETIC-MECHANICS）", "（OTHER-DOCUMENT）") for p in RATE_PARAGRAPHS
            )
        )


def test_record_date_boundary_is_exclusive_and_not_issuance_date() -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        _parse().validate_policy(replace(_policy(), effective_from=date(2015, 9, 8)))


def test_policy_currency_rounding_is_explicit_accounting_not_inferred_statute() -> None:
    _parse().validate_policy(
        replace(_policy(), currency_quantum=Decimal("0.001"), rounding_mode=TaxRoundingMode.DOWN)
    )


@pytest.mark.parametrize("cap", [0, -1, True, 1.5])
def test_explicit_positive_exact_parsing_cap_is_required(cap: object) -> None:
    with pytest.raises(DataValidationError):
        parse_statutory_dividend_tax_terms(
            rate_document_body=_html("SYNTHETIC-RATE", RATE_PARAGRAPHS),
            rate_legal_number="SYNTHETIC-RATE",
            rate_source_revision_sha256="a" * 64,
            mechanics_document_body=_html("SYNTHETIC-MECHANICS", MECHANICS_PARAGRAPHS),
            mechanics_legal_number="SYNTHETIC-MECHANICS",
            mechanics_source_revision_sha256="b" * 64,
            max_body_bytes=cap,
        )


def test_normative_effective_and_record_date_boundaries_must_agree() -> None:
    with pytest.raises(DataValidationError):
        _parse(tuple(p.replace("自2015年9月8日", "自2015年9月7日") for p in RATE_PARAGRAPHS))


def test_invalid_normative_calendar_date_is_classified() -> None:
    with pytest.raises(DataValidationError):
        _parse(tuple(p.replace("2015年9月8日", "2015年99月8日") for p in RATE_PARAGRAPHS))


def test_rate_source_and_mechanics_source_cannot_share_one_unqualified_hash() -> None:
    with pytest.raises(DataValidationError):
        parse_statutory_dividend_tax_terms(
            rate_document_body=_html("SYNTHETIC-RATE", RATE_PARAGRAPHS),
            rate_legal_number="SYNTHETIC-RATE",
            rate_source_revision_sha256="a" * 64,
            mechanics_document_body=_html("SYNTHETIC-MECHANICS", MECHANICS_PARAGRAPHS),
            mechanics_legal_number="SYNTHETIC-MECHANICS",
            mechanics_source_revision_sha256="a" * 64,
            max_body_bytes=16384,
        )


def test_percentage_scaling_is_exact_under_low_ambient_precision() -> None:
    from decimal import localcontext

    with localcontext() as context:
        context.prec = 2
        assert _percentage("12.3456789012") == Decimal("0.123456789012")


@pytest.mark.parametrize("text", ["2" * 33, "NaN"])
def test_unsupported_percentage_text_is_blocked_before_domain_use(text: str) -> None:
    with pytest.raises(DataValidationError):
        _percentage(text)
