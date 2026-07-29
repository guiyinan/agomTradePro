import pytest

from apps.regime.domain.navigator_services import (
    WatchIndicatorConfig,
    determine_watch_indicators,
)
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


def test_watch_indicator_payloads_are_detached_from_config():
    config = WatchIndicatorConfig.defaults()
    first = determine_watch_indicators(RegimeType.RECOVERY, "stable", None, config=config)
    first[0]["name"] = "被调用方修改"

    second = determine_watch_indicators(RegimeType.RECOVERY, "stable", None, config=config)

    assert second[0]["name"] == "制造业PMI"


@pytest.mark.parametrize(
    ("direction", "target"),
    [("unknown", None), ("stable", "Unknown")],
)
def test_invalid_navigation_state_is_rejected(direction, target):
    with pytest.raises(ValueError):
        determine_watch_indicators(RegimeType.RECOVERY, direction, target)
