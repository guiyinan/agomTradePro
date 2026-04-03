"""
Django development settings for AgomTradePro project.
"""

import os

from core.log_file_paths import (
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

# CORS settings (for development)
CORS_ALLOW_ALL_ORIGINS = True

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
DEVELOPMENT_LOG_MAX_BYTES = get_development_log_max_bytes()
DEVELOPMENT_LOG_BACKUP_COUNT = get_development_log_backup_count()

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
    },
    'root': {
        'handlers': ['console', 'in_memory', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'in_memory', 'file'],
            'level': normalize_log_level(os.getenv('DJANGO_LOG_LEVEL')),
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'in_memory', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.server': {
            'handlers': ['console', 'in_memory', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console', 'in_memory', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'core': {
            'handlers': ['console', 'in_memory', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# 环境变量控制是否使用 JSON 格式日志
USE_JSON_LOGGING = os.getenv('USE_JSON_LOGGING', 'false').lower() == 'true'
if USE_JSON_LOGGING:
    LOGGING['handlers']['console']['formatter'] = 'structured'
