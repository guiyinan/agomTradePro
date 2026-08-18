"""User-facing metadata contracts for A-share behavior indicators."""

from apps.data_center.application.market_thermometer_specs import (
    MARKET_BEHAVIOR_COLLECTION_SPECS,
)
from apps.data_center.infrastructure.seed_data.macro_indicator_governance import (
    INDICATOR_METADATA_UPDATES,
)


def test_price_limit_labels_disclose_non_st_scope() -> None:
    """Price-limit labels and catalog descriptions must disclose ST exclusion."""

    expected = {
        "limit_up_count": "CN_A_LIMIT_UP_COUNT",
        "limit_down_count": "CN_A_LIMIT_DOWN_COUNT",
    }
    for component_key, indicator_code in expected.items():
        assert "不含 ST" in MARKET_BEHAVIOR_COLLECTION_SPECS[component_key]["label"]
        metadata = INDICATOR_METADATA_UPDATES[indicator_code]
        assert "不含 ST" in metadata["name_cn"]
        assert "ST" in metadata["description"]
