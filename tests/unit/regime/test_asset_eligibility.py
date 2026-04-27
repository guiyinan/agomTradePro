from apps.regime.domain.asset_eligibility import (
    DEFAULT_ELIGIBILITY_MATRIX,
    Eligibility,
    check_eligibility,
    get_preferred_asset_classes,
    set_eligibility_matrix_provider,
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


def test_get_eligibility_matrix_falls_back_to_default_when_provider_raises():
    def failing_provider():
        raise RuntimeError("config not ready")

    set_eligibility_matrix_provider(failing_provider)
    try:
        assert (
            check_eligibility("gold", "Recovery") == DEFAULT_ELIGIBILITY_MATRIX["gold"]["Recovery"]
        )
    finally:
        set_eligibility_matrix_provider(lambda: DEFAULT_ELIGIBILITY_MATRIX)
