#!/usr/bin/env python
"""检查 SQLite 数据并迁移到 PostgreSQL"""
import sqlite3
import os

print("=== 检查 SQLite 数据库 ===")
db_path = 'D:/githv/agomTradePro/db.sqlite3'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 检查表数量
cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
table_count = cursor.fetchone()[0]
print(f"SQLite 表数量: {table_count}")

# 检查用户数量
cursor.execute("SELECT count(*) FROM auth_user")
user_count = cursor.fetchone()[0]
print(f"SQLite 用户数量: {user_count}")

# 检查一些关键表
tables_to_check = [
    'macro_macroindicatormodel',
    'regime_regimestatemodel',
    'signal_investmentsignalmodel',
    'filter_filterresultmodel',
]

for table in tables_to_check:
    try:
        cursor.execute(f"SELECT count(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  {table}: {count} 条记录")
    except Exception as e:
        print(f"  {table}: 不存在")

conn.close()

print("\n=== 现在切换到 PostgreSQL 导入 ===")
print("请确认 development.py 已配置为 PostgreSQL")
