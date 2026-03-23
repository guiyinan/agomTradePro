
import os

from .base import *

DEBUG = True
# Development only: relax host checks for local debugging/tools.
ALLOWED_HOSTS = ['*']
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
TEST_DB_NAME = os.path.join(BASE_DIR, f'test_db_{os.getpid()}.sqlite3')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        'OPTIONS': {
            'timeout': 30,
        },
        'TEST': {
            'NAME': TEST_DB_NAME,
        },
    }
}
CORS_ALLOW_ALL_ORIGINS = True

# 使用内存缓存（用于测试环境，避免 Redis 依赖）
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}
