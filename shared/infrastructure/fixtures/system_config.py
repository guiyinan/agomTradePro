"""
System Configuration Initial Data

初始化系统配置值，替代硬编码。
运行方式: python manage.py loaddata system_config (需要先生成 fixture)
或者: python manage.py shell < shared/infrastructure/fixtures/init_system_config.py
"""

# 配置初始数据
SYSTEM_CONFIG_INITIAL_DATA = [
    # AI 分类阈值
    {
        "key": "ai.auto_approve_threshold",
        "name": "AI 自动通过阈值",
        "parameter_type": "adjustment_factor",
        "value_float": 0.75,
        "description": "AI 分类置信度高于此值时自动通过",
    },
    {
        "key": "ai.auto_reject_threshold",
        "name": "AI 自动拒绝阈值",
        "parameter_type": "adjustment_factor",
        "value_float": 0.30,
        "description": "AI 分类置信度低于此值时自动拒绝",
    },

    # Regime 指标阈值
    {
        "key": "regime.spread_bp_threshold",
        "name": "期限利差阈值（BP）",
        "parameter_type": "adjustment_factor",
        "value_float": 100.0,
        "description": "10Y-2Y 期限利差阈值（基点），高于此值为看涨信号",
    },
    {
        "key": "regime.us_yield_threshold",
        "name": "美债收益率阈值",
        "parameter_type": "adjustment_factor",
        "value_float": 4.5,
        "description": "美国10年期国债收益率阈值（%），高于此值为看跌信号",
    },

    # Regime 信号冲突解决
    {
        "key": "regime.daily_persist_days",
        "name": "日线信号持续天数",
        "parameter_type": "adjustment_factor",
        "value_float": 10.0,
        "description": "日线信号持续超过此天数时优先采用日线信号",
    },
    {
        "key": "regime.conflict_confidence_boost",
        "name": "信号一致时置信度提升",
        "parameter_type": "adjustment_factor",
        "value_float": 0.20,
        "description": "日线和月线信号一致时置信度提升值",
    },

    # Sentiment 权重
    {
        "key": "sentiment.news_weight",
        "name": "新闻情绪权重",
        "parameter_type": "adjustment_factor",
        "value_float": 0.40,
        "description": "综合情绪指数中新闻情绪的权重",
    },
    {
        "key": "sentiment.policy_weight",
        "name": "政策情绪权重",
        "parameter_type": "adjustment_factor",
        "value_float": 0.60,
        "description": "综合情绪指数中政策情绪的权重",
    },

    # Backtest 参数
    {
        "key": "backtest.risk_free_rate",
        "name": "无风险利率",
        "parameter_type": "adjustment_factor",
        "value_float": 0.03,
        "description": "回测时使用的无风险利率（年化）",
    },
]


def init_system_config():
    """初始化系统配置"""
    from shared.infrastructure.models import RiskParameterConfigModel

    created_count = 0
    updated_count = 0

    for data in SYSTEM_CONFIG_INITIAL_DATA:
        obj, created = RiskParameterConfigModel._default_manager.update_or_create(
            key=data["key"],
            defaults={
                "name": data["name"],
                "parameter_type": data["parameter_type"],
                "value_float": data["value_float"],
                "description": data["description"],
                "is_active": True,
            }
        )
        if created:
            created_count += 1
        else:
            updated_count += 1

    return {
        "created": created_count,
        "updated": updated_count,
        "total": len(SYSTEM_CONFIG_INITIAL_DATA),
    }


if __name__ == "__main__":
    # 通过 Django shell 运行
    result = init_system_config()
    print(f"配置初始化完成: 创建 {result['created']} 条，更新 {result['updated']} 条")
