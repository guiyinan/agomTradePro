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

# HTTPS settings - secure by default in production
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
SECURE_REFERRER_POLICY = env('SECURE_REFERRER_POLICY', default='strict-origin-when-cross-origin')
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HSTS settings - only enable when using HTTPS
if SECURE_SSL_REDIRECT:
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True)
    SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=True)
else:
    # COOP is only meaningful on potentially trustworthy origins (HTTPS/localhost).
    # Disable it for plain HTTP deployments to avoid browser warnings like:
    # "Cross-Origin-Opener-Policy header has been ignored, because the URL's origin was untrustworthy".
    SECURE_CROSS_ORIGIN_OPENER_POLICY = None

# CORS and CSRF trusted origins for production
# Allow VPS IP and configured domains
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['127.0.0.1', 'localhost'])
CORS_ALLOW_ALL_ORIGINS = env.bool('CORS_ALLOW_ALL_ORIGINS', default=False)

CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    f'http://{host}' for host in ALLOWED_HOSTS
])
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[
    f'http://{host}' for host in ALLOWED_HOSTS
])

# If using HTTPS, add https:// versions
if SECURE_SSL_REDIRECT:
    CORS_ALLOWED_ORIGINS.extend([f'https://{host}' for host in ALLOWED_HOSTS])
    CSRF_TRUSTED_ORIGINS.extend([f'https://{host}' for host in ALLOWED_HOSTS])

# Logging configuration
LOG_TO_FILE = env.bool('LOG_TO_FILE', default=False)

handlers = {
    'console': {
        'class': 'logging.StreamHandler',
        'formatter': 'verbose',
    },
    'in_memory': {
        'class': 'core.logging_handlers.InMemoryLogHandler',
        'formatter': 'simple',
    },
}

django_handlers = ['console', 'in_memory']

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
        'handlers': ['console', 'in_memory'],
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
