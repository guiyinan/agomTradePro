"""
从 SQLite 迁移 USD 数据到 PostgreSQL，同时应用汇率转换

⚠️ 安全第一：执行前确保 PostgreSQL 中有备份
"""

import sqlite3
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')
django.setup()

from apps.macro.infrastructure.models import MacroIndicatorModel
from django.db import transaction
from dotenv import load_dotenv

load_dotenv()

# 获取汇率
EXCHANGE_RATE = float(os.getenv('USD_CNY_EXCHANGE_RATE', 7.2))

print(f"📌 使用汇率: {EXCHANGE_RATE} USD/CNY")
print("=" * 60)

# 连接 SQLite
sqlite_path = os.path.join(os.path.dirname(__file__), 'db.sqlite3')
print(f"📂 SQLite 路径: {sqlite_path}")

sqlite_conn = sqlite3.connect(sqlite_path)
sqlite_conn.row_factory = sqlite3.Row
sqlite_cursor = sqlite_conn.cursor()

# 查找 USD 数据
sqlite_cursor.execute("""
    SELECT id, code, name, date, value, unit, original_unit, source
    FROM macro_indicator
    WHERE unit LIKE '%美元%' OR unit LIKE '%USD%'
    ORDER BY date, code
""")

usd_rows = sqlite_cursor.fetchall()
print(f"📊 找到 {len(usd_rows)} 条 USD 数据")

# 单位转换因子
UNIT_CONVERSION_FACTORS = {
    '万美元': 10000,
    '亿美元': 100000000,
    '万亿美元': 1000000000000,
    '百万美元': 1000000,
    '十亿美元': 1000000000,
    '美元': 1,
}

def convert_usd_to_cny(value: float, unit: str, exchange_rate: float) -> tuple[float, str]:
    """将美元单位数据转换为人民币元"""
    if unit in UNIT_CONVERSION_FACTORS:
        factor = UNIT_CONVERSION_FACTORS[unit]
        converted_value = value * factor * exchange_rate
        return (converted_value, "元")
    return (value, unit)

# 显示前 5 条预览
print("\n📋 数据预览 (前 5 条):")
print("-" * 80)
for i, row in enumerate(usd_rows[:5]):
    original_value = row['value']
    original_unit = row['unit']
    converted_value, new_unit = convert_usd_to_cny(original_value, original_unit, EXCHANGE_RATE)

    print(f"{i+1}. [{row['date']}] {row['name']} ({row['code']})")
    print(f"   原始: {original_value} {original_unit}")
    print(f"   转换: {converted_value:,.2f} {new_unit}")
    print(f"   汇率: {EXCHANGE_RATE}")
    print()

# 确认执行
print("=" * 60)
confirm = input("是否执行迁移? (输入 'yes' 继续): ")

if confirm.lower() != 'yes':
    print("❌ 迁移已取消")
    sqlite_conn.close()
    exit(0)

# 执行迁移
print("\n🔄 开始迁移...")

with transaction.atomic():
    for row in usd_rows:
        # 检查是否已存在
        existing = MacroIndicatorModel.objects.filter(
            code=row['code'],
            date=row['date']
        ).first()

        if existing:
            # 更新现有记录
            original_value = row['value']
            original_unit = row['unit']
            converted_value, new_unit = convert_usd_to_cny(original_value, original_unit, EXCHANGE_RATE)

            existing.value = converted_value
            existing.unit = new_unit
            existing.original_unit = original_unit  # 保留原始单位
            existing.source = row['source']
            existing.save()
            print(f"✏️  更新: {row['code']} @ {row['date']}: {original_value} {original_unit} → {converted_value:,.2f} {new_unit}")
        else:
            # 创建新记录
            original_value = row['value']
            original_unit = row['unit']
            converted_value, new_unit = convert_usd_to_cny(original_value, original_unit, EXCHANGE_RATE)

            MacroIndicatorModel.objects.create(
                code=row['code'],
                name=row['name'],
                date=row['date'],
                value=converted_value,
                unit=new_unit,
                original_unit=original_unit,
                source=row['source']
            )
            print(f"✅ 创建: {row['code']} @ {row['date']}: {original_value} {original_unit} → {converted_value:,.2f} {new_unit}")

sqlite_conn.close()

print("\n" + "=" * 60)
print("✅ 迁移完成!")

# 验证结果
usd_count = MacroIndicatorModel.objects.filter(original_unit__icontains='美元').count()
print(f"📊 PostgreSQL 中现有 {usd_count} 条美元数据（已转换为人民币）")
