#!/usr/bin/env python
"""直接迁移：SQLite -> PostgreSQL"""
import os
import sys

# 切换到 SQLite
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings.development_sqlite'

# 创建临时 SQLite settings
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent

temp_settings = f'''
from .base import *
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
DATABASES = {{
    'default': {{
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': '{BASE_DIR / "db.sqlite3"}',
    }}
}}
CORS_ALLOW_ALL_ORIGINS = True
'''

settings_path = BASE_DIR / 'core' / 'settings' / 'development_sqlite.py'
with open(settings_path, 'w', encoding='utf-8') as f:
    f.write(temp_settings)

import django

django.setup()

from django.core.management import call_command

print("=== 步骤 1: 从 SQLite 导出 ===")
with open('data.json', 'w', encoding='utf-8') as f:
    call_command('dumpdata', stdout=f,
                 exclude=['contenttypes', 'auth.Permission'])

print(f"导出完成: data.json ({os.path.getsize('data.json') / 1024:.1f} KB)")

# 清理临时文件
os.remove(settings_path)

print("\n=== 步骤 2: 切换到 PostgreSQL ===")
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings.development'

# 重新加载 Django
from importlib import reload

import core.settings.development

reload(core.settings.development)

from django.conf import settings

print(f"当前数据库: {settings.DATABASES['default']['ENGINE']}")

print("\n=== 步骤 3: 导入到 PostgreSQL ===")
call_command('loaddata', 'data.json')

print("\n=== 迁移完成 ===")
