"""
Django base settings for AgomSAAF project.
"""

import os
from pathlib import Path
import environ
from celery.schedules import crontab

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Environment variables
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
ALLOWED_HOSTS = []

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party apps
    'rest_framework',
    'rest_framework.authtoken',  # Token 认证
    'drf_spectacular',
    'django_celery_beat',

    # Shared infrastructure
    'shared',

    # Local apps
    'apps.macro',
    'apps.regime',
    'apps.filter',
    'apps.policy',
    'apps.signal',
    'apps.backtest',
    'apps.audit',
    'apps.ai_provider',
    'apps.prompt',
    'apps.account',   # 新增：用户账户管理
    'apps.dashboard', # 新增：仪表盘
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

WSGI_APPLICATION = 'core.wsgi.application'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'core', 'static'),
    os.path.join(BASE_DIR, 'static'),
]

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'core', 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Admin Site Configuration
ADMIN_TITLE = 'AgomSAAF 管理后台'
ADMIN_HEADER = 'AgomSAAF'
ADMIN_INDEX_TITLE = '欢迎使用 AgomSAAF 管理后台'

# REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # 认证配置
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',  # Session 认证（Web界面）
        'rest_framework.authentication.TokenAuthentication',     # Token 认证（API调用）
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',  # 默认需要登录
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.FormParser',
        'rest_framework.parsers.MultiPartParser',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# Spectacular settings
SPECTACULAR_SETTINGS = {
    'TITLE': 'AgomSAAF API',
    'DESCRIPTION': 'Agom Strategic Asset Allocation Framework API',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# Celery settings
# For development without Redis, use memory broker (tasks execute immediately)
# For production, install Redis and set REDIS_URL environment variable
if env('REDIS_URL', default=None):
    # Production mode with Redis
    CELERY_BROKER_URL = env('REDIS_URL')
    CELERY_RESULT_BACKEND = env('REDIS_URL')
else:
    # Development mode - tasks execute synchronously (no background worker needed)
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Celery Beat 定时任务配置
CELERY_BEAT_SCHEDULE = {
    'daily-sync-and-calculate': {
        'task': 'apps.macro.application.tasks.sync_and_calculate_regime',
        'schedule': crontab(hour=8, minute=0),  # 每天 8:00 执行
        'options': {
            'source': 'akshare',
            'indicator': None,
            'days_back': 30,
            'use_pit': True,
        }
    },
    'check-data-freshness': {
        'task': 'apps.macro.application.tasks.check_data_freshness',
        'schedule': crontab(minute='*/30'),  # 每 30 分钟执行一次
    },
    'check-regime-health': {
        'task': 'apps.regime.application.tasks.check_regime_health',
        'schedule': crontab(hour='*/6'),  # 每 6 小时执行一次
    },
}
