"""
从 SQLite 导出 USD 数据，生成 SQL 迁移脚本
"""

import sqlite3
from datetime import datetime

# 汇率
EXCHANGE_RATE = 7.2

# 单位转换因子
UNIT_CONVERSION_FACTORS = {
    '万美元': 10000,
    '亿美元': 100000000,
    '万亿美元': 1000000000000,
    '百万美元': 1000000,
    '十亿美元': 1000000000,
    '美元': 1,
}

def convert_usd_to_cny(value: float, unit: str, exchange_rate: float) -> tuple:
    """将美元单位数据转换为人民币元"""
    if unit in UNIT_CONVERSION_FACTORS:
        factor = UNIT_CONVERSION_FACTORS[unit]
        converted_value = value * factor * exchange_rate
        return (converted_value, "元")
    return (value, unit)

# 连接 SQLite
conn = sqlite3.connect('D:/githv/agomTradePro/db.sqlite3')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 查找 USD 数据
cursor.execute("""
    SELECT id, code, published_at, publication_lag_days, source,
           revision_number, created_at, updated_at, period_type,
           reporting_period, unit, original_unit, value
    FROM macro_indicator
    WHERE unit LIKE '%美元%' OR unit LIKE '%USD%'
    ORDER BY reporting_period, code
""")

usd_rows = cursor.fetchall()

# 生成 SQL 文件
with open('migrate_usd_data.sql', 'w', encoding='utf-8') as f:
    f.write("-- USD 数据迁移 SQL\n")
    f.write(f"-- 生成时间: {datetime.now()}\n")
    f.write(f"-- 汇率: {EXCHANGE_RATE} USD/CNY\n")
    f.write(f"-- 记录数: {len(usd_rows)}\n\n")

    f.write("BEGIN;\n\n")
    f.write("-- 设置时区\n")
    f.write("SET TIME ZONE 'Asia/Shanghai';\n\n")

    for row in usd_rows:
        original_value = row['value']
        original_unit = row['unit']  # 可能是乱码，但数据库中的值是正确的
        converted_value, new_unit = convert_usd_to_cny(original_value, original_unit, EXCHANGE_RATE)

        # 处理可能为 None 的字段
        published_at = f"'{row['published_at']}'" if row['published_at'] else 'NULL'
        created_at = f"'{row['created_at']}'" if row['created_at'] else "'now()'"
        updated_at = f"'{row['updated_at']}'" if row['updated_at'] else "'now()'"

        # 生成 INSERT 语句（使用 ON CONFLICT 更新）
        sql = f"""INSERT INTO macro_indicator (
    code, value, reporting_period, published_at, publication_lag_days,
    source, revision_number, created_at, updated_at, period_type,
    unit, original_unit
) VALUES (
    '{row['code']}',
    {converted_value},
    '{row['reporting_period']}',
    {published_at},
    {row['publication_lag_days'] or 0},
    '{row['source']}',
    {row['revision_number'] or 0},
    {created_at},
    {updated_at},
    '{row['period_type']}',
    '{new_unit}',
    '{original_unit}'
)
ON CONFLICT (code, reporting_period, revision_number)
DO UPDATE SET
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    original_unit = EXCLUDED.original_unit,
    updated_at = now();
"""
        f.write(sql)
        f.write("\n")

    f.write("\nCOMMIT;\n")

conn.close()

print("Generated SQL file: migrate_usd_data.sql")
print(f"Total records: {len(usd_rows)}")
print("\nTo execute:")
print("  docker exec -i agomtradepro_postgres_dev psql -U agomtradepro -d agomtradepro < migrate_usd_data.sql")
