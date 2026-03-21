"""
初始化权重配置数据

运行：
    agomtradepro/Scripts/python manage.py shell < scripts/init_weight_config.py
"""

from apps.asset_analysis.infrastructure.models import WeightConfigModel


def init_weight_configs():
    """初始化权重配置数据"""

    # 1. 默认配置（通用）
    default_config, created = WeightConfigModel.objects.get_or_create(
        name='default',
        defaults={
            'description': '默认权重配置（适用所有资产）',
            'regime_weight': 0.40,
            'policy_weight': 0.25,
            'sentiment_weight': 0.20,
            'signal_weight': 0.15,
            'is_active': True,
            'priority': 0,
        }
    )
    if created:
        print(f"✓ 创建默认配置: {default_config.name}")
    else:
        print(f"- 默认配置已存在: {default_config.name}")

    # 2. 政策危机配置
    crisis_config, created = WeightConfigModel.objects.get_or_create(
        name='policy_crisis',
        defaults={
            'description': '政策危机时提高Policy权重',
            'regime_weight': 0.20,
            'policy_weight': 0.50,
            'sentiment_weight': 0.20,
            'signal_weight': 0.10,
            'market_condition': 'crisis',
            'is_active': True,
            'priority': 10,
        }
    )
    if created:
        print(f"✓ 创建政策危机配置: {crisis_config.name}")
    else:
        print(f"- 政策危机配置已存在: {crisis_config.name}")

    # 3. 情绪极端配置
    sentiment_config, created = WeightConfigModel.objects.get_or_create(
        name='sentiment_extreme',
        defaults={
            'description': '市场情绪极端时提高Sentiment权重',
            'regime_weight': 0.30,
            'policy_weight': 0.30,
            'sentiment_weight': 0.30,
            'signal_weight': 0.10,
            'market_condition': 'extreme_sentiment',
            'is_active': True,
            'priority': 10,
        }
    )
    if created:
        print(f"✓ 创建情绪极端配置: {sentiment_config.name}")
    else:
        print(f"- 情绪极端配置已存在: {sentiment_config.name}")

    # 4. 基金专用配置
    fund_config, created = WeightConfigModel.objects.get_or_create(
        name='fund_default',
        defaults={
            'description': '基金默认权重配置',
            'regime_weight': 0.35,
            'policy_weight': 0.25,
            'sentiment_weight': 0.25,
            'signal_weight': 0.15,
            'asset_type': 'fund',
            'is_active': True,
            'priority': 5,
        }
    )
    if created:
        print(f"✓ 创建基金配置: {fund_config.name}")
    else:
        print(f"- 基金配置已存在: {fund_config.name}")

    # 5. 股票专用配置
    equity_config, created = WeightConfigModel.objects.get_or_create(
        name='equity_default',
        defaults={
            'description': '股票默认权重配置',
            'regime_weight': 0.40,
            'policy_weight': 0.25,
            'sentiment_weight': 0.20,
            'signal_weight': 0.15,
            'asset_type': 'equity',
            'is_active': True,
            'priority': 5,
        }
    )
    if created:
        print(f"✓ 创建股票配置: {equity_config.name}")
    else:
        print(f"- 股票配置已存在: {equity_config.name}")

    print("\n权重配置初始化完成！")
    print(f"当前配置数量: {WeightConfigModel.objects.count()}")


if __name__ == "__main__":
    init_weight_configs()
