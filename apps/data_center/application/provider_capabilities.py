"""Canonical provider-to-capability mapping used by data-center workflows."""

from apps.data_center.domain.enums import DataCapability

SOURCE_TYPE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "tushare": (
        DataCapability.MACRO.value,
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.REALTIME_QUOTE.value,
        DataCapability.FUND_NAV.value,
        DataCapability.FINANCIAL.value,
        DataCapability.VALUATION.value,
    ),
    "akshare": (
        DataCapability.MACRO.value,
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.REALTIME_QUOTE.value,
        DataCapability.FUND_NAV.value,
        DataCapability.FINANCIAL.value,
        DataCapability.VALUATION.value,
        DataCapability.SECTOR_MEMBERSHIP.value,
        DataCapability.NEWS.value,
        DataCapability.CAPITAL_FLOW.value,
    ),
    "eastmoney": (
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.REALTIME_QUOTE.value,
        DataCapability.NEWS.value,
        DataCapability.CAPITAL_FLOW.value,
    ),
    "qmt": (
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.REALTIME_QUOTE.value,
    ),
    "fred": (DataCapability.MACRO.value,),
    "wind": (
        DataCapability.MACRO.value,
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.FINANCIAL.value,
        DataCapability.VALUATION.value,
        DataCapability.SECTOR_MEMBERSHIP.value,
    ),
    "choice": (
        DataCapability.MACRO.value,
        DataCapability.HISTORICAL_PRICE.value,
        DataCapability.FINANCIAL.value,
    ),
}
