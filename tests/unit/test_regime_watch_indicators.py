from apps.regime.domain.navigator_services import determine_watch_indicators
from apps.regime.domain.services_v2 import RegimeType


def test_watch_indicators_include_term_spread_when_transitioning():
    indicators = determine_watch_indicators(
        RegimeType.RECOVERY,
        "transitioning",
        "Deflation",
    )

    codes = {item["code"] for item in indicators}
    assert "PMI" in codes
    assert "CPI" in codes
    assert "CN_TERM_SPREAD_10Y2Y" in codes


def test_watch_indicators_include_inflation_proxy_for_overheat():
    indicators = determine_watch_indicators(
        RegimeType.OVERHEAT,
        "stable",
        None,
    )

    codes = {item["code"] for item in indicators}
    assert "CN_NHCI" in codes


def test_watch_indicators_include_credit_for_deflation():
    indicators = determine_watch_indicators(
        RegimeType.DEFLATION,
        "stable",
        "Recovery",
    )

    codes = {item["code"] for item in indicators}
    assert "CN_NEW_CREDIT" in codes
