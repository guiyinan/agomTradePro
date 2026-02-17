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

# Optional feature flags / external app URLs
STREAMLIT_DASHBOARD_ENABLED = env.bool('STREAMLIT_DASHBOARD_ENABLED', default=False)
STREAMLIT_DASHBOARD_URL = env(
    'STREAMLIT_DASHBOARD_URL',
    default='http://127.0.0.1:8501',
)

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
    'jazzmin',  # Django Admin 美化主题
    'rest_framework',
    'rest_framework.authtoken',  # Token 认证
    'drf_spectacular',
    'django_celery_beat',

    # Shared infrastructure
    'shared',
    'core',  # For templatetags

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
    'apps.account',        # 新增：用户账户管理
    'apps.dashboard',      # 新增：仪表盘
    'apps.equity',         # 新增：个股分析模块
    'apps.sector',         # 新增：板块分析模块
    'apps.fund',           # 新增：基金分析模块
    'apps.asset_analysis', # 新增：通用资产分析模块
    'apps.sentiment',      # 新增：舆情情感分析模块
    'apps.simulated_trading', # 新增：模拟盘自动交易模块
    'apps.strategy',       # 新增：投资组合策略系统
    'apps.realtime',       # 新增：实时价格监控模块

    # ========== 新模块：决策流程优化 ==========
    'apps.decision_rhythm', # 决策频率约束模块（新增）
    'apps.events',         # 事件总线模块（新增）
    'apps.beta_gate',      # Beta 闸门模块（新增）
    'apps.alpha_trigger',  # Alpha 离散触发模块（新增）
    'apps.alpha',          # Alpha AI 选股模块（新增）

    # ========== 新模块：因子选股 + 资产轮动 + 对冲组合 ==========
    'apps.factor',         # 因子选股模块（新增）
    'apps.rotation',       # 资产轮动模块（新增）
    'apps.hedge',          # 对冲组合模块（新增）
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # CORS middleware - must be before CommonMiddleware
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

# Authentication URLs
LOGIN_URL = '/account/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# Internationalization
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
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
                # Global alerts for decision platform
                'core.context_processors.get_alerts',
            ],
        },
    },
]

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Cache Configuration (易用性改进 - Redis缓存层)
# 优先使用 Redis，开发环境可降级为内存缓存
if env('REDIS_URL', default=None):
    # 生产环境：使用 Redis
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': env('REDIS_URL', default='redis://127.0.0.1:6379/1'),
            'TIMEOUT': 900,  # 默认15分钟
            'KEY_PREFIX': 'agomsaaf',
        }
    }
else:
    # 开发环境：使用内存缓存（同步模式，不需要Redis服务）
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'agomsaaf-cache',
            'TIMEOUT': 900,  # 默认15分钟
            'OPTIONS': {
                'MAX_ENTRIES': 1000,
            }
        }
    }

# Admin Site Configuration
ADMIN_TITLE = 'AgomSAAF 管理后台'
ADMIN_HEADER = 'AgomSAAF'
ADMIN_INDEX_TITLE = '欢迎使用 AgomSAAF 管理后台'

# Email / Notification settings
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@agomsaaf.com')
DAILY_INSPECTION_EMAIL_ENABLED = env.bool('DAILY_INSPECTION_EMAIL_ENABLED', default=True)

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

# CORS Configuration (跨域资源共享)
# 开发环境默认允许所有来源，生产环境必须通过环境变量配置
CORS_ALLOW_ALL_ORIGINS = env.bool('CORS_ALLOW_ALL_ORIGINS', default=True)
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    'http://127.0.0.1:8000',
    'http://localhost:8000',
    'http://127.0.0.1:3000',
    'http://localhost:3000',
])
CORS_ALLOW_CREDENTIALS = env.bool('CORS_ALLOW_CREDENTIALS', default=True)

# CORS 可信来源（允许 redirect 和预检请求缓存）
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# CSRF 可信来源（用于 SameSite 配置）
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[
    'http://127.0.0.1:8000',
    'http://localhost:8000',
])

# Spectacular settings
SPECTACULAR_SETTINGS = {
    'TITLE': 'AgomSAAF API',
    'DESCRIPTION': 'Agom Strategic Asset Allocation Framework API',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    # Performance optimizations
    'SCHEMA_PATH_PREFIX': '/api/',
    'COMPONENT_SPLIT_REQUEST': True,
    'COMPONENT_NO_READ_ONLY_REQUIRED': True,
    # UI optimizations
    'SWAGGER_UI_SETTINGS': {
        'defaultModelsExpandDepth': 1,
        'defaultModelExpandDepth': 1,
        'docExpansion': 'none',
        'filter': True,
        'showRequestHeaders': True,
        'persistAuthorization': True,
    },
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

    # ========== Signal 证伪自动检查 ==========
    'daily-signal-invalidation': {
        'task': 'signal.check_all_invalidations',
        'schedule': crontab(hour=2, minute=0),  # 每天凌晨 2:00
        'options': {
            'expires': 3600,  # 1 小时超时
        }
    },

    # 可选：每日信号摘要
    'daily-signal-summary': {
        'task': 'signal.daily_summary',
        'schedule': crontab(hour=9, minute=0),  # 每天上午 9:00
    },
    # ============================================

    # ========== Phase 1: 高频数据同步（日度Regime信号）==========
    'high-frequency-sync-bonds': {
        'task': 'apps.macro.application.tasks.sync_high_frequency_bonds',
        'schedule': crontab(hour=16, minute=30, day_of_week='mon-fri'),  # 每个交易日 16:30（收盘后）
        'options': {
            'source': 'akshare',
            'years_back': 1,
            'expires': 3600,  # 1 小时超时
        }
    },
    'high-frequency-sync-commodities': {
        'task': 'apps.macro.application.tasks.sync_high_frequency_commodities',
        'schedule': crontab(hour=16, minute=35, day_of_week='mon-fri'),  # 每个交易日 16:35
        'options': {
            'source': 'akshare',
            'years_back': 1,
            'expires': 3600,
        }
    },
    'high-frequency-generate-signal': {
        'task': 'apps.macro.application.tasks.generate_daily_regime_signal',
        'schedule': crontab(hour=17, minute=0, day_of_week='mon-fri'),  # 每个交易日 17:00
        'options': {
            'expires': 1800,  # 30 分钟超时
        }
    },
    'high-frequency-recalculate-regime': {
        'task': 'apps.macro.application.tasks.recalculate_regime_with_daily_signal',
        'schedule': crontab(hour=17, minute=5, day_of_week='mon-fri'),  # 每个交易日 17:05
        'options': {
            'use_pit': True,
            'expires': 1800,
        }
    },
    # ============================================================

    # ========== 模拟盘自动交易 ==========
    'simulated-daily-auto-trading': {
        'task': 'apps.simulated_trading.application.tasks.daily_auto_trading_task',
        'schedule': crontab(hour=15, minute=30, day_of_week='mon-fri'),  # 每个交易日 15:30
        'options': {
            'expires': 7200,  # 2 小时超时
        }
    },
    'simulated-update-prices': {
        'task': 'apps.simulated_trading.application.tasks.update_position_prices_task',
        'schedule': crontab(hour=16, minute=0, day_of_week='mon-fri'),  # 每个交易日 16:00
    },
    'simulated-weekly-performance': {
        'task': 'apps.simulated_trading.application.tasks.calculate_all_performance_task',
        'schedule': crontab(hour=2, minute=0, day_of_week='sun'),  # 每周日凌晨 2:00
    },
    'simulated-cleanup-accounts': {
        'task': 'apps.simulated_trading.application.tasks.cleanup_inactive_accounts_task',
        'schedule': crontab(hour=3, minute=0, day_of_week='sun'),  # 每周日凌晨 3:00
    },
    'simulated-daily-summary': {
        'task': 'apps.simulated_trading.application.tasks.send_performance_summary_task',
        'schedule': crontab(hour=17, minute=0, day_of_week='mon-fri'),  # 每个交易日 17:00
    },
    'simulated-daily-inspection': {
        'task': 'simulated.daily_portfolio_inspection',
        'schedule': crontab(hour=17, minute=10, day_of_week='mon-fri'),  # 每个交易日 17:10
        'kwargs': {
            'account_id': 679,
            'strategy_id': 4,
        },
        'options': {
            'expires': 1800,
        }
    },
    # ============================================

    # ========== 持仓证伪检查 ==========
    'simulated-check-position-invalidation-morning': {
        'task': 'apps.simulated_trading.application.tasks.check_position_invalidation_task',
        'schedule': crontab(hour=10, minute=0, day_of_week='mon-fri'),  # 每个交易日 10:00
        'options': {
            'expires': 1800,  # 30 分钟超时
        }
    },
    'simulated-check-position-invalidation-afternoon': {
        'task': 'apps.simulated_trading.application.tasks.check_position_invalidation_task',
        'schedule': crontab(hour=14, minute=0, day_of_week='mon-fri'),  # 每个交易日 14:00
        'options': {
            'expires': 1800,  # 30 分钟超时
        }
    },
    'simulated-notify-invalidated-positions': {
        'task': 'apps.simulated_trading.application.tasks.notify_invalidated_positions_task',
        'schedule': crontab(hour=10, minute=5, day_of_week='mon-fri'),  # 每个交易日 10:05
        'options': {
            'expires': 600,  # 10 分钟超时
        }
    },
    # ============================================

    # ========== 实时价格监控 ==========
    'realtime-update-prices-after-close': {
        'task': 'apps.simulated_trading.application.tasks.update_all_prices_after_close',
        'schedule': crontab(hour=16, minute=30, day_of_week='mon-fri'),  # 每个交易日 16:30
        'options': {
            'expires': 3600,  # 1 小时超时
        }
    },
    # ============================================

    # ========== Alpha Qlib 推理任务 ==========
    "qlib-daily-inference": {
        "task": "apps.alpha.application.tasks.qlib_predict_scores",
        "schedule": crontab(hour=17, minute=30, day_of_week="mon-fri"),  # 每个交易日 17:30
        "options": {
            "expires": 7200,  # 2 小时超时
        }
    },
    "qlib-weekly-cache-refresh": {
        "task": "apps.alpha.application.tasks.qlib_refresh_cache",
        "schedule": crontab(hour=2, minute=0, day_of_week="sun"),  # 每周日凌晨 2:00
        "options": {
            "days_back": 7,
            "expires": 14400,  # 4 小时超时
        }
    },
    # ============================================

    # ========== Phase 4: 监控和告警任务 ==========
    "alpha-evaluate-alerts": {
        "task": "alpha.monitor.evaluate_alerts",
        "schedule": crontab(minute="*/1"),  # 每分钟执行一次
        "options": {
            "expires": 60,  # 1 分钟超时
        }
    },
    "alpha-update-provider-metrics": {
        "task": "alpha.monitor.update_provider_metrics",
        "schedule": crontab(minute="*/5"),  # 每 5 分钟执行一次
        "options": {
            "expires": 300,  # 5 分钟超时
        }
    },
    "alpha-check-queue-lag": {
        "task": "alpha.monitor.check_queue_lag",
        "schedule": crontab(minute="*/1"),  # 每分钟执行一次
        "options": {
            "expires": 60,
        }
    },
    "alpha-calculate-ic-drift": {
        "task": "alpha.monitor.calculate_ic_drift",
        "schedule": crontab(hour=2, minute=0, day_of_week="sun"),  # 每周日凌晨 2:00
        "options": {
            "expires": 1800,  # 30 分钟超时
        }
    },
    "alpha-daily-report": {
        "task": "alpha.monitor.generate_daily_report",
        "schedule": crontab(hour=8, minute=0),  # 每天 8:00
        "options": {
            "expires": 600,  # 10 分钟超时
        }
    },
    "alpha-cleanup-metrics": {
        "task": "alpha.monitor.cleanup_old_metrics",
        "schedule": crontab(hour=3, minute=0, day_of_week="sun"),  # 每周日凌晨 3:00
        "options": {
            "days": 30,  # 保留 30 天
            "expires": 3600,  # 1 小时超时
        }
    },
    # ============================================
}

# ========== Qlib 配置 ==========
QLIB_SETTINGS = {
    'provider_uri': env('QLIB_PROVIDER_URI', default='~/.qlib/qlib_data/cn_data'),
    'region': env('QLIB_REGION', default='CN'),
    'model_path': env('QLIB_MODEL_PATH', default='/models/qlib'),
}

# Celery 队列路由配置（Qlib 任务专用队列）
CELERY_TASK_ROUTES = {
    'apps.alpha.application.tasks.qlib_train_model': {'queue': 'qlib_train'},
    'apps.alpha.application.tasks.qlib_predict_scores': {'queue': 'qlib_infer'},
    'apps.alpha.application.tasks.qlib_evaluate_model': {'queue': 'qlib_train'},
    'apps.alpha.application.tasks.qlib_refresh_cache': {'queue': 'qlib_infer'},
}

# Qlib 任务超时配置
CELERY_TASK_TIME_LIMIT = 3600  # 1 小时
CELERY_TASK_SOFT_TIME_LIMIT = 3300  # 55 分钟

# Qlib Worker 配置建议
# celery -A core worker -l info -Q qlib_infer --max-tasks-per-child=10 --concurrency=2
# celery -A core worker -l info -Q qlib_train --max-tasks-per-child=1 --concurrency=1
