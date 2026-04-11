"""
Django development settings for AgomTradePro project.
"""

import os

from core.log_file_paths import (
    get_celery_beat_log_path,
    get_celery_log_backup_count,
    get_celery_log_max_bytes,
    get_celery_worker_log_path,
    get_development_log_backup_count,
    get_development_log_max_bytes,
    get_runserver_log_path,
)
from core.logging_utils import normalize_log_level

from .base import *

# DEBUG
DEBUG = True
# Development only: relax host checks for local debugging/tools.
ALLOWED_HOSTS = ['*']

# Database - 使用 PostgreSQL (从 .env 读取 DATABASE_URL)
DATABASES = {
    'default': env.db('DATABASE_URL', default='sqlite:///db.sqlite3')
}

# Cache - default to local memory for development unless Redis cache is
# explicitly requested. This keeps first-run/local UI flows responsive even
# when REDIS_URL is present but no Redis server is running.
USE_REDIS_CACHE = env.bool("USE_REDIS_CACHE", default=False)
if USE_REDIS_CACHE and env("REDIS_URL", default=None):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": env("REDIS_URL"),
            "TIMEOUT": 900,
            "KEY_PREFIX": "agomtradepro-dev",
            "OPTIONS": {
                "socket_connect_timeout": env.float("DEV_REDIS_SOCKET_CONNECT_TIMEOUT", default=0.2),
                "socket_timeout": env.float("DEV_REDIS_SOCKET_TIMEOUT", default=0.2),
                "retry_on_timeout": False,
            },
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "agomtradepro-dev-cache",
            "TIMEOUT": 900,
            "OPTIONS": {
                "MAX_ENTRIES": 1000,
            },
        }
    }

# CORS settings (for development)
CORS_ALLOW_ALL_ORIGINS = True

# Use django-celery-beat in development so startup task reconciliation remains the
# single source of truth for local periodic tasks.
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers.DatabaseScheduler"

# CSRF trusted origins (for development)
CSRF_TRUSTED_ORIGINS = [
    'http://localhost',
    'http://localhost:8000',
    'http://127.0.0.1',
    'http://127.0.0.1:8000',
]
# Allow cookie to work across localhost variants
CSRF_COOKIE_SAMESITE = 'Lax'

# Logging
# 结构化日志配置 - 支持 trace_id/request_id 追踪
DEVELOPMENT_LOG_FILE = get_runserver_log_path(BASE_DIR)
CELERY_WORKER_LOG_FILE = get_celery_worker_log_path(BASE_DIR)
CELERY_BEAT_LOG_FILE = get_celery_beat_log_path(BASE_DIR)
DEVELOPMENT_LOG_MAX_BYTES = get_development_log_max_bytes()
DEVELOPMENT_LOG_BACKUP_COUNT = get_development_log_backup_count()
CELERY_LOG_MAX_BYTES = get_celery_log_max_bytes()
CELERY_LOG_BACKUP_COUNT = get_celery_log_backup_count()
DEFAULT_HANDLERS = ['console', 'in_memory', 'file']
CELERY_WORKER_HANDLERS = DEFAULT_HANDLERS + ['celery_worker_file']
CELERY_BEAT_HANDLERS = DEFAULT_HANDLERS + ['celery_beat_file']
CELERY_LOG_LEVEL = normalize_log_level(os.getenv('CELERY_LOG_LEVEL') or os.getenv('DJANGO_LOG_LEVEL'))

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'trace_context': {
            '()': 'core.logging_utils.TraceContextFilter',
        },
    },
    'formatters': {
        # 结构化 JSON 格式（用于生产环境日志收集）
        'structured': {
            '()': 'core.logging_utils.StructuredFormatter',
        },
        # 详细结构化 JSON 格式（用于调试）
        'structured_verbose': {
            '()': 'core.logging_utils.StructuredFormatterVerbose',
        },
        # 简单文本格式（用于开发环境控制台）
        'simple': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        # 带 trace_id 的简单文本格式
        'simple_with_trace': {
            'format': '{levelname} {asctime} {module} [trace_id={trace_id}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple_with_trace',
            'filters': ['trace_context'],
        },
        'console_json': {
            'class': 'logging.StreamHandler',
            'formatter': 'structured',
            'filters': ['trace_context'],
        },
        'in_memory': {
            'class': 'core.logging_handlers.InMemoryLogHandler',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(DEVELOPMENT_LOG_FILE),
            'encoding': 'utf-8',
            'maxBytes': DEVELOPMENT_LOG_MAX_BYTES,
            'backupCount': DEVELOPMENT_LOG_BACKUP_COUNT,
            'formatter': 'simple_with_trace',
            'filters': ['trace_context'],
        },
        'celery_worker_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(CELERY_WORKER_LOG_FILE),
            'encoding': 'utf-8',
            'maxBytes': CELERY_LOG_MAX_BYTES,
            'backupCount': CELERY_LOG_BACKUP_COUNT,
            'formatter': 'simple_with_trace',
            'filters': ['trace_context'],
        },
        'celery_beat_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(CELERY_BEAT_LOG_FILE),
            'encoding': 'utf-8',
            'maxBytes': CELERY_LOG_MAX_BYTES,
            'backupCount': CELERY_LOG_BACKUP_COUNT,
            'formatter': 'simple_with_trace',
            'filters': ['trace_context'],
        },
    },
    'root': {
        'handlers': DEFAULT_HANDLERS,
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': DEFAULT_HANDLERS,
            'level': normalize_log_level(os.getenv('DJANGO_LOG_LEVEL')),
            'propagate': False,
        },
        'django.request': {
            'handlers': DEFAULT_HANDLERS,
            'level': 'WARNING',
            'propagate': False,
        },
        'django.server': {
            'handlers': DEFAULT_HANDLERS,
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': DEFAULT_HANDLERS,
            'level': 'INFO',
            'propagate': False,
        },
        'core': {
            'handlers': DEFAULT_HANDLERS,
            'level': 'DEBUG',
            'propagate': False,
        },
        'celery': {
            'handlers': CELERY_WORKER_HANDLERS,
            'level': CELERY_LOG_LEVEL,
            'propagate': False,
        },
        'celery.task': {
            'handlers': CELERY_WORKER_HANDLERS,
            'level': CELERY_LOG_LEVEL,
            'propagate': False,
        },
        'celery.worker': {
            'handlers': CELERY_WORKER_HANDLERS,
            'level': CELERY_LOG_LEVEL,
            'propagate': False,
        },
        'celery.app.trace': {
            'handlers': CELERY_WORKER_HANDLERS,
            'level': CELERY_LOG_LEVEL,
            'propagate': False,
        },
        'celery.beat': {
            'handlers': CELERY_BEAT_HANDLERS,
            'level': CELERY_LOG_LEVEL,
            'propagate': False,
        },
    },
}

# 环境变量控制是否使用 JSON 格式日志
USE_JSON_LOGGING = os.getenv('USE_JSON_LOGGING', 'false').lower() == 'true'
if USE_JSON_LOGGING:
    LOGGING['handlers']['console']['formatter'] = 'structured'
