"""
Django production settings for AgomSAAF project.
"""

from .base import *
import os

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])

# Database - PostgreSQL for production
DATABASES = {
    'default': env.db('DATABASE_URL', default='sqlite:///db.sqlite3')
}

# Security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)

# HSTS settings
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True)
SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=True)

# Logging configuration
LOG_TO_FILE = env.bool('LOG_TO_FILE', default=False)

handlers = {
    'console': {
        'class': 'logging.StreamHandler',
        'formatter': 'verbose',
    },
}

django_handlers = ['console']

if LOG_TO_FILE:
    os.makedirs('/var/log/agomsaaf', exist_ok=True)
    handlers['file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': '/var/log/agomsaaf/django.log',
        'maxBytes': 1024 * 1024 * 100,
        'backupCount': 10,
        'formatter': 'verbose',
    }
    django_handlers.append('file')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': handlers,
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': django_handlers,
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': django_handlers,
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Celery Beat settings (use database scheduler)
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers.DatabaseScheduler'

# 注意: 定时任务配置通过 Django Admin 或 setup_celery_beat.py 脚本配置
