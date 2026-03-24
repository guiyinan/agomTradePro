import pytest
from apps.pulse.infrastructure.models import PulseWeightConfig, PulseIndicatorWeight
from apps.pulse.infrastructure.data_provider import DjangoPulseDataProvider

@pytest.mark.django_db
def test_pulse_weights_override_from_db():
    # 1. 创建假的 PulseWeightConfig
    config = PulseWeightConfig.objects.create(name="Test Config", is_active=True)
    PulseIndicatorWeight.objects.create(
        config=config, 
        indicator_code="CN_M2", 
        dimension="liquidity", 
        weight=2.5, 
        is_enabled=True
    )
    
    # 2. 从 DataProvider 里读取 defs
    provider = DjangoPulseDataProvider()
    defs = provider._load_indicator_defs()
    
    # 3. 验证对于 M2, weight 被 override 成了 2.5
    m2_def = next((x for x in defs if x.code == "CN_M2"), None)
    assert m2_def is not None
    assert m2_def.weight == 2.5
    
    # 未被 override 的依然是默认权重
    other_def = next((x for x in defs if x.code == "CN_TERM_SPREAD_10Y2Y"), None)
    assert other_def is not None
    assert other_def.weight == 1.0 # default
