"""
Django development settings for AgomSAAF project.
"""

from .base import *
import os

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
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
        'in_memory': {
            'class': 'core.logging_handlers.InMemoryLogHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console', 'in_memory'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'in_memory'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
    },
}
