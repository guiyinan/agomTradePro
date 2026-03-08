"""
Django base settings for AgomSAAF project.
"""

import os
import sys
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

# Debug automation API (for Codex / Claude Code log polling)
# Disabled by default. Enable explicitly via .env.
AUTOMATION_DEBUG_API_ENABLED = env.bool('AUTOMATION_DEBUG_API_ENABLED', default=False)
AUTOMATION_DEBUG_API_TOKENS = [t.strip() for t in env.list('AUTOMATION_DEBUG_API_TOKENS', default=[]) if t.strip()]
AUTOMATION_DEBUG_API_IP_ALLOWLIST = [ip.strip() for ip in env.list('AUTOMATION_DEBUG_API_IP_ALLOWLIST', default=[]) if ip.strip()]
AUTOMATION_DEBUG_API_MAX_LIMIT = env.int('AUTOMATION_DEBUG_API_MAX_LIMIT', default=1000)

# Field-level encryption for sensitive data (API keys, etc.)
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Set via environment variable: AGOMSAAF_ENCRYPTION_KEY
AGOMSAAF_ENCRYPTION_KEY = env('AGOMSAAF_ENCRYPTION_KEY', default='')
if not AGOMSAAF_ENCRYPTION_KEY:
    import warnings
    warnings.warn(
        "AGOMSAAF_ENCRYPTION_KEY not configured. New AI provider API key writes will be rejected. "
        "Generate a key with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )

# Decision Workspace V2 feature flag
# When disabled, the unified recommendation API returns a fallback response
DECISION_WORKSPACE_V2_ENABLED = env.bool('DECISION_WORKSPACE_V2_ENABLED', default=True)

# ========================================================================
# M3: 执行升级灰度开关
# ========================================================================

# 执行模式配置
EXECUTION_MODE = env('EXECUTION_MODE', default='paper')  # paper | broker | canary
BROKER_CANARY_RATIO = env.float('BROKER_CANARY_RATIO', default=0.1)  # 金丝雀比例 (0.0 - 1.0)

REQUIRE_CONFIRMATION_FOR_WATCH = env.bool('REQUIRE_CONFIRMATION_FOR_WATCH', default=True)  # WATCH 状态是否需要人工确认

# 决策引擎配置
DECISION_SIGNAL_THRESHOLD = env.float('DECISION_SIGNAL_THRESHOLD', default=0.6)
DECISION_CONFIDENCE_THRESHOLD = env.float('DECISION_CONFIDENCE_THRESHOLD', default=0.7)
DECISION_REGIME_ALIGNMENT_REQUIRED = env.bool('DECISION_REGIME_ALIGNMENT_REQUIRED', default=True)
# 仓位引擎配置
SIZING_DEFAULT_METHOD = env('SIZING_DEFAULT_METHOD', default='fixed_fraction')
SIZING_RISK_PER_TRADE_PCT = env.float('SIZING_RISK_PER_TRADE_PCT', default=1.0)
SIZING_MAX_POSITION_PCT = env.float('SIZING_MAX_POSITION_PCT', default=20.0)
# 錙仓限制
SIZING_MIN_QTY = env.int('SIZING_MIN_QTY', default=1)
# 风控配置
RISK_MAX_SINGLE_POSITION_PCT = env.float('RISK_MAX_SINGLE_POSITION_PCT', default=20.0)
RISK_MAX_DAILY_TRADES = env.int('RISK_MAX_DAILY_TRADES', default=10)
RISK_MAX_DAILY_LOSS_PCT = env.float('RISK_MAX_DAILY_LOSS_PCT', default=5.0)
RISK_MIN_VOLUME = env.int('RISK_MIN_VOLUME', default=100000)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
ALLOWED_HOSTS = []

# Application definition

# P1-3: DoS 基线 - 请求体大小限制
# 防止大请求耗尽服务器资源
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int('DATA_UPLOAD_MAX_MEMORY_SIZE', default=10 * 1024 * 1024)  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = env.int('FILE_UPLOAD_MAX_MEMORY_SIZE', default=10 * 1024 * 1024)  # 10MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = env.int('DATA_UPLOAD_MAX_NUMBER_FIELDS', default=1000)  # 最多1000个字段

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

    # ========== 新模块：任务监控 ==========
    'apps.task_monitor',   # 任务监控模块（新增）

    # ========== Prometheus 指标 ==========
    'django_prometheus',   # Prometheus 指标导出（新增）
]

MIDDLEWARE = [
    'django_prometheus.middleware.PrometheusBeforeMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # CORS middleware - must be before CommonMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    # 结构化日志中间件 - 在 CommonMiddleware 之前设置
    'core.middleware.logging.TraceIDMiddleware',  # 添加 trace_id 追踪
    'core.middleware.logging.RequestLoggingMiddleware',  # 记录请求日志
    'core.middleware.prometheus.PrometheusMetricsMiddleware',  # 自定义 API 业务指标
    'core.middleware.query_profiler.QueryProfilerMiddleware',  # 慢查询分析（需 QUERY_PROFILER_ENABLED=True）
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.DeprecationHeaderMiddleware',  # Add deprecation headers for legacy routes
    'django_prometheus.middleware.PrometheusAfterMiddleware',
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

# Authentication backends
# Add lockout-aware backend to mitigate brute-force login attempts.
AUTHENTICATION_BACKENDS = [
    'core.security.LockoutModelBackend',
]

# Login lockout settings
LOGIN_LOCKOUT_MAX_ATTEMPTS = env.int('LOGIN_LOCKOUT_MAX_ATTEMPTS', default=5)
LOGIN_LOCKOUT_WINDOW_SECONDS = env.int('LOGIN_LOCKOUT_WINDOW_SECONDS', default=900)

# Internationalization
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    # Project-level assets live here. App-level assets (including core/static)
    # are discovered via AppDirectoriesFinder from INSTALLED_APPS.
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
APP_BASE_URL = env('APP_BASE_URL', default='')

# REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # 异常处理器（P0-1：统一异常返回格式）
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
    # 认证配置
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',  # Session 认证（Web界面）
        'rest_framework.authentication.TokenAuthentication',     # Token 认证（API调用）
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',  # 默认需要登录
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': env('DRF_THROTTLE_ANON', default='100/hour'),
        'user': env('DRF_THROTTLE_USER', default='1000/hour'),
        'backtest': env('DRF_THROTTLE_BACKTEST', default='10/hour'),  # P0-2：回测专用限流
        'write': env('DRF_THROTTLE_WRITE', default='100/hour'),  # P0-2：写操作限流
        'burst': env('DRF_THROTTLE_BURST', default='30/minute'),  # P0-2：突发保护限流
    },
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
    # 避免与业务参数 ?format=csv 冲突（如审计导出接口）
    'URL_FORMAT_OVERRIDE': None,
}

# CORS Configuration (跨域资源共享)
# 默认关闭全量放行，优先白名单策略
CORS_ALLOW_ALL_ORIGINS = env.bool('CORS_ALLOW_ALL_ORIGINS', default=False)
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

# Pytest mode: force in-process Celery execution regardless of external broker config
_is_pytest = ("pytest" in sys.modules) or any("pytest" in arg for arg in sys.argv)
if _is_pytest or os.environ.get("PYTEST_CURRENT_TEST"):
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Celery safety: re-deliver tasks if worker crashes mid-execution
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_ACKS_LATE = True

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
    'send-database-backup-email': {
        'task': 'apps.account.application.tasks.send_database_backup_email_task',
        'schedule': crontab(hour=8, minute=10),
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
        "task": "apps.alpha.application.tasks.qlib_daily_inference",
        "schedule": crontab(hour=17, minute=30, day_of_week="mon-fri"),  # 每个交易日 17:30
        "kwargs": {
            "universe_id": "csi300",
            "top_n": 30,
        },
        "options": {
            "expires": 7200,  # 2 小时超时
        }
    },
    "qlib-weekly-cache-refresh": {
        "task": "apps.alpha.application.tasks.qlib_refresh_cache",
        "schedule": crontab(hour=2, minute=0, day_of_week="sun"),  # 每周日凌晨 2:00
        "kwargs": {
            "universe_id": "csi300",
            "days_back": 7,
        },
        "options": {
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

    # ========== 任务监控清理 ==========
    "task-monitor-cleanup": {
        "task": "apps.task_monitor.application.tasks.cleanup_old_task_records",
        "schedule": crontab(hour=4, minute=0, day_of_week="sun"),  # 每周日凌晨 4:00
        "options": {
            "days_to_keep": 30,  # 保留 30 天
            "expires": 3600,  # 1 小时超时
        }
    },
    # ============================================

    # ========== P1-2: 数据库备份 ==========
    "database-daily-backup": {
        "task": "apps.task_monitor.application.tasks.backup_database_task",
        "schedule": crontab(hour=3, minute=0),  # 每天凌晨 3:00
        "kwargs": {
            "keep_days": 7,  # 保留 7 天
            "compress": True,
        },
        "options": {
            "expires": 3600,  # 1 小时超时
        }
    },
    # ============================================

    # ========== Policy Workbench 任务 ==========
    'policy-fetch-rss-sources': {
        'task': 'apps.policy.application.tasks.fetch_rss_sources',
        'schedule': crontab(hour='*/6', minute=0),  # 每 6 小时
        'options': {
            'expires': 3600,  # 1 小时超时
        }
    },
    'policy-review-auto-assign': {
        'task': 'apps.policy.application.tasks.auto_assign_pending_audits_task',
        'schedule': crontab(minute='*/15'),  # 每 15 分钟
        'options': {
            'expires': 600,  # 10 分钟超时
        }
    },
    'policy-sla-monitor': {
        'task': 'apps.policy.application.tasks.monitor_sla_exceeded_task',
        'schedule': crontab(minute='*/10'),  # 每 10 分钟
        'options': {
            'expires': 300,  # 5 分钟超时
        }
    },
    'policy-gate-refresh': {
        'task': 'apps.policy.application.tasks.refresh_gate_constraints_task',
        'schedule': crontab(minute='*/5'),  # 每 5 分钟
        'options': {
            'expires': 180,  # 3 分钟超时
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

# ========== MCP/SDK 操作审计日志配置 ==========
AUDIT_RETENTION_DAYS = env.int('AUDIT_RETENTION_DAYS', default=90)
AUDIT_EXPORT_MAX_ROWS = env.int('AUDIT_EXPORT_MAX_ROWS', default=10000)
AUDIT_EXPORT_MAX_DAYS = env.int('AUDIT_EXPORT_MAX_DAYS', default=90)
AUDIT_INTERNAL_SECRET_KEY = env('AUDIT_INTERNAL_SECRET_KEY', default='')

# ========== Prometheus 指标配置 ==========
PROMETHEUS_EXPORT_MIGRATIONS = False  # 不导出 Django 迁移指标

# ========== 慢查询分析配置 ==========
# 查询性能分析中间件开关（默认关闭，生产环境按需开启）
QUERY_PROFILER_ENABLED = env.bool('QUERY_PROFILER_ENABLED', default=False)
# 慢查询阈值（毫秒），超过此值的查询会被记录
SLOW_QUERY_THRESHOLD_MS = env.int('SLOW_QUERY_THRESHOLD_MS', default=100)
# 每个请求的查询数量阈值（超过则警告）
QUERY_COUNT_WARNING_THRESHOLD = env.int('QUERY_COUNT_WARNING_THRESHOLD', default=50)
