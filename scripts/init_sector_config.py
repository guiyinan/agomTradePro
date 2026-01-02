"""
初始化板块配置

运行方式：
    python manage.py shell < scripts/init_sector_config.py
"""

from shared.infrastructure.models import SectorPreferenceConfigModel


def init_sector_preferences():
    """初始化板块偏好配置"""
    preferences = [
        # Recovery - 复苏期
        {"regime": "Recovery", "sector_name": "农林牧渔", "weight": 0.6},
        {"regime": "Recovery", "sector_name": "基础化工", "weight": 0.7},
        {"regime": "Recovery", "sector_name": "钢铁", "weight": 0.8},
        {"regime": "Recovery", "sector_name": "有色金属", "weight": 0.7},
        {"regime": "Recovery", "sector_name": "电子", "weight": 0.9},
        {"regime": "Recovery", "sector_name": "汽车", "weight": 0.9},
        {"regime": "Recovery", "sector_name": "家用电器", "weight": 0.8},
        {"regime": "Recovery", "sector_name": "食品饮料", "weight": 0.7},

        # Overheat - 过热期
        {"regime": "Overheat", "sector_name": "煤炭", "weight": 1.0},
        {"regime": "Overheat", "sector_name": "石油石化", "weight": 1.0},
        {"regime": "Overheat", "sector_name": "有色金属", "weight": 0.9},
        {"regime": "Overheat", "sector_name": "钢铁", "weight": 0.8},
        {"regime": "Overheat", "sector_name": "基础化工", "weight": 0.7},
        {"regime": "Overheat", "sector_name": "建筑材料", "weight": 0.7},

        # Stagflation - 滞胀期
        {"regime": "Stagflation", "sector_name": "煤炭", "weight": 0.9},
        {"regime": "Stagflation", "sector_name": "石油石化", "weight": 0.9},
        {"regime": "Stagflation", "sector_name": "医药生物", "weight": 0.8},
        {"regime": "Stagflation", "sector_name": "食品饮料", "weight": 0.8},
        {"regime": "Stagflation", "sector_name": "公用事业", "weight": 0.9},
        {"regime": "Stagflation", "sector_name": "交通运输", "weight": 0.7},

        # Deflation - 通缩期
        {"regime": "Deflation", "sector_name": "银行", "weight": 1.0},
        {"regime": "Deflation", "sector_name": "非银金融", "weight": 0.9},
        {"regime": "Deflation", "sector_name": "建筑装饰", "weight": 0.5},
        {"regime": "Deflation", "sector_name": "建筑材料", "weight": 0.4},
        {"regime": "Deflation", "sector_name": "电力设备", "weight": 0.6},
        {"regime": "Deflation", "sector_name": "食品饮料", "weight": 0.7},
    ]

    for pref in preferences:
        SectorPreferenceConfigModel.objects.update_or_create(
            regime=pref["regime"],
            sector_name=pref["sector_name"],
            defaults=pref
        )

    print(f"[OK] 已初始化 {len(preferences)} 条板块偏好配置")


# 执行初始化
if __name__ == "__main__":
    print("开始初始化板块配置...")
    init_sector_preferences()
    print("[OK] 板块配置初始化完成！")
