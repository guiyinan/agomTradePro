import pytest

from apps.pulse.infrastructure.data_provider import DjangoPulseDataProvider
from apps.pulse.infrastructure.models import (
    PulseIndicatorConfigModel,
    PulseIndicatorWeight,
    PulseWeightConfig,
)


@pytest.mark.django_db
def test_pulse_weights_override_from_db():
    # 1. 创建假的 PulseWeightConfig
    config = PulseWeightConfig.objects.create(name="Test Config", is_active=True)
    PulseIndicatorWeight.objects.create(
        config=config,
        indicator_code="CN_M2_YOY",
        dimension="liquidity",
        weight=2.5,
        is_enabled=True,
    )
    PulseIndicatorConfigModel.objects.update_or_create(
        indicator_code="CN_PMI",
        defaults={
            "indicator_name": "制造业PMI",
            "dimension": "growth",
            "frequency": "monthly",
            "weight": 1.0,
            "signal_type": "level",
            "bullish_threshold": 50.0,
            "bearish_threshold": 49.0,
            "neutral_band": 0.5,
            "signal_multiplier": 0.4,
            "is_active": True,
        },
    )

    # 2. 从 DataProvider 里读取 defs
    provider = DjangoPulseDataProvider()
    defs = provider._load_indicator_defs()

    # 3. 验证对于 M2 同比, weight 被 override 成了 2.5
    m2_def = next((x for x in defs if x.code == "CN_M2_YOY"), None)
    assert m2_def is not None
    assert m2_def.weight == 2.5

    # 未被 override 的依然是默认权重
    other_def = next((x for x in defs if x.code == "CN_PMI"), None)
    assert other_def is not None
    assert other_def.weight == 1.0  # default
