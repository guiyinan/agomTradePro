from apps.regime.domain.asset_eligibility import (
    Eligibility,
    check_eligibility,
    get_preferred_asset_classes,
)


def test_check_eligibility_returns_preferred_for_growth_in_recovery():
    result = check_eligibility("a_share_growth", "Recovery")

    assert result == Eligibility.PREFERRED


def test_check_eligibility_returns_neutral_for_unknown_regime():
    result = check_eligibility("gold", "UnknownRegime")

    assert result == Eligibility.NEUTRAL


def test_get_preferred_asset_classes_orders_preferred_before_neutral():
    asset_classes = get_preferred_asset_classes("Recovery")

    assert asset_classes[:2] == ["a_share_growth", "a_share_value"]
    assert "gold" in asset_classes
