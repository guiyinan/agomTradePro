#!/usr/bin/env python
import json
import os
import sys
from pathlib import Path

import django

BASE_DIR = Path(__file__).resolve().parent

# Step 1: SQLite settings (export)
print("=== Step 1: Export from SQLite ===")
sqlite_settings = f'''
from .base import *
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
DATABASES = {{
    'default': {{
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': r'{BASE_DIR / "db.sqlite3"}',
    }}
}}
CORS_ALLOW_ALL_ORIGINS = True
'''

with open(BASE_DIR / 'core' / 'settings' / '_sqlite.py', 'w', encoding='utf-8') as f:
    f.write(sqlite_settings)

os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings._sqlite'
django.setup()

from django.core.management import call_command

# Export to file
output_file = BASE_DIR / 'migration_data.json'
with open(output_file, 'w', encoding='utf-8') as f:
    call_command('dumpdata',
                 exclude=['contenttypes', 'auth.Permission'],
                 stdout=f)

print(f"Exported: {output_file.stat().st_size / 1024:.1f} KB")

# Cleanup
os.remove(BASE_DIR / 'core' / 'settings' / '_sqlite.py')

# Step 2: PostgreSQL settings (import)
print("\n=== Step 2: Import to PostgreSQL ===")
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings.development'

# Reload Django
import importlib

import core.settings.development

importlib.reload(core.settings.development)

# Re-setup Django
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SELECT version()")
    print(f"Connected to: {cursor.fetchone()[0][:50]}...")

# Import data
call_command('loaddata', 'migration_data.json')

print("\n=== Migration Complete ===")

# Verify
from django.contrib.auth.models import User

print(f"Users in PostgreSQL: {User.objects.count()}")
