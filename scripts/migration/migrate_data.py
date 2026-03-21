#!/usr/bin/env python
"""数据迁移脚本：SQLite -> PostgreSQL"""
import os
import sys
import django

# 第一步：从 SQLite 导出
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development_temp')

# 创建临时 settings 文件（使用 SQLite）
temp_settings = '''
from .base import *
import os
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'D:/githv/agomTradePro/db.sqlite3',
    }
}
CORS_ALLOW_ALL_ORIGINS = True
'''

with open('core/settings/development_temp.py', 'w', encoding='utf-8') as f:
    f.write(temp_settings)

django.setup()

from django.core.management import call_command

print("正在从 SQLite 导出数据...")
with open('backup.json', 'w', encoding='utf-8') as f:
    call_command('dumpdata', '--natural-foreign', '--natural-primary',
                 '-e', 'contenttypes', '-e', 'auth.Permission',
                 stdout=f)

print(f"导出完成，文件大小: {os.path.getsize('backup.json') / 1024:.2f} KB")

# 删除临时文件
os.remove('core/settings/development_temp.py')
print("数据导出完成！现在可以切换到 PostgreSQL 并运行:")
print("  python manage.py loaddata backup.json")
