"""
Django base settings for AgomTradePro project.
"""

import os
import sys
from pathlib import Path

import environ  # type: ignore[import-untyped]
from kombu import Queue  # type: ignore[import-untyped]

from core.settings.celery_schedule import CELERY_BEAT_SCHEDULE as CELERY_BEAT_SCHEDULE

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Environment variables
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

# Optional feature flags / external app URLs
STREAMLIT_DASHBOARD_ENABLED = env.bool("STREAMLIT_DASHBOARD_ENABLED", default=False)
STREAMLIT_DASHBOARD_URL = env(
    "STREAMLIT_DASHBOARD_URL",
    default="http://127.0.0.1:8501",
)

# Debug automation API (for Codex / Claude Code log polling)
# Disabled by default. Enable explicitly via .env.
AUTOMATION_DEBUG_API_ENABLED = env.bool("AUTOMATION_DEBUG_API_ENABLED", default=False)
AUTOMATION_DEBUG_API_TOKENS = [
    t.strip() for t in env.list("AUTOMATION_DEBUG_API_TOKENS", default=[]) if t.strip()
]
AUTOMATION_DEBUG_API_IP_ALLOWLIST = [
    ip.strip() for ip in env.list("AUTOMATION_DEBUG_API_IP_ALLOWLIST", default=[]) if ip.strip()
]
AUTOMATION_DEBUG_API_MAX_LIMIT = env.int("AUTOMATION_DEBUG_API_MAX_LIMIT", default=1000)

# TUI runtime performance flags. Both paths retain their legacy fallbacks.
TUI_RUNTIME_CACHE_ENABLED = env.bool("TUI_RUNTIME_CACHE_ENABLED", default=True)
TUI_RUNTIME_CACHE_TTL_SECONDS = env.int("TUI_RUNTIME_CACHE_TTL_SECONDS", default=300)
TUI_OPTIMIZED_BOOTSTRAP_ENABLED = env.bool("TUI_OPTIMIZED_BOOTSTRAP_ENABLED", default=True)
TUI_ACTION_MAX_CONCURRENCY = env.int("TUI_ACTION_MAX_CONCURRENCY", default=6)
TUI_ACTION_ACQUIRE_TIMEOUT_SECONDS = env.float(
    "TUI_ACTION_ACQUIRE_TIMEOUT_SECONDS",
    default=3.0,
)
# Inline Qlib inference is an explicitly bounded development-only fallback.
# Production settings override this to False so a missing worker can never
# turn a web request into an unbounded model run.
ALPHA_ALLOW_INLINE_INFERENCE = env.bool("ALPHA_ALLOW_INLINE_INFERENCE", default=False)
ALPHA_SIMPLE_MAX_POOL_SIZE = env.int("ALPHA_SIMPLE_MAX_POOL_SIZE", default=120)

# Terminal Agent migration flags.  The queued path remains dormant until TAR-02
# supplies durable admission/dispatch; keeping the defaults explicit prevents a
# deployment environment from accidentally treating the contract as a runtime
# implementation.  The legacy path remains bounded by the service's hard cap.
TERMINAL_RUNTIME_AUTHORIZED = env.bool("TERMINAL_RUNTIME_AUTHORIZED", default=False)
TERMINAL_RUNTIME_ROLE = env("TERMINAL_RUNTIME_ROLE", default="legacy_inline")
TERMINAL_QUEUED_INTAKE_ENABLED = env.bool("TERMINAL_QUEUED_INTAKE_ENABLED", default=False)
TERMINAL_QUEUED_WORKER_ENABLED = env.bool("TERMINAL_QUEUED_WORKER_ENABLED", default=False)
TERMINAL_LEGACY_INLINE_ENABLED = env.bool("TERMINAL_LEGACY_INLINE_ENABLED", default=True)
TERMINAL_EMERGENCY_STOP = env.bool("TERMINAL_EMERGENCY_STOP", default=False)
TERMINAL_PER_USER_QUEUED_LIMIT = env.int("TERMINAL_PER_USER_QUEUED_LIMIT", default=4)
TERMINAL_GLOBAL_QUEUED_LIMIT = env.int("TERMINAL_GLOBAL_QUEUED_LIMIT", default=40)
TERMINAL_PER_USER_ACTIVE_LIMIT = env.int("TERMINAL_PER_USER_ACTIVE_LIMIT", default=1)
TERMINAL_GLOBAL_ACTIVE_LIMIT = env.int("TERMINAL_GLOBAL_ACTIVE_LIMIT", default=4)
TERMINAL_LEGACY_INLINE_CONCURRENCY = env.int("TERMINAL_LEGACY_INLINE_CONCURRENCY", default=1)
TERMINAL_LEGACY_INLINE_TIMEOUT_SECONDS = env.int(
    "TERMINAL_LEGACY_INLINE_TIMEOUT_SECONDS",
    default=60,
)
TERMINAL_AGENT_ORPHAN_AFTER_SECONDS = env.int(
    "TERMINAL_AGENT_ORPHAN_AFTER_SECONDS",
    default=90,
)
TERMINAL_AGENT_DISPATCH_RETRY_AFTER_SECONDS = env.int(
    "TERMINAL_AGENT_DISPATCH_RETRY_AFTER_SECONDS",
    default=15,
)

# Immutable deployment identity artifacts. Production mounts the release
# manifest read-only; the build identity is embedded in the application image.
AGOM_BUILD_IDENTITY_PATH = Path(
    env("AGOM_BUILD_IDENTITY_PATH", default=str(BASE_DIR / ".agom-build-identity.json"))
)
AGOM_RELEASE_MANIFEST_PATH = Path(
    env(
        "AGOM_RELEASE_MANIFEST_PATH",
        default=str(BASE_DIR / ".agom-release-manifest.json"),
    )
)

# Field-level encryption for sensitive data (API keys, etc.)
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Set via environment variable: AGOMTRADEPRO_ENCRYPTION_KEY
AGOMTRADEPRO_ENCRYPTION_KEY = env("AGOMTRADEPRO_ENCRYPTION_KEY", default="")
DATABASE_URL = env("DATABASE_URL", default="")
# Mounted cold-storage root for governed Data Center archives.  Empty is an
# intentional fail-closed state; production must configure a path outside the
# PostgreSQL/VPS hot-data volume before archive tasks can run.
DATA_CENTER_ARCHIVE_ROOT = env("DATA_CENTER_ARCHIVE_ROOT", default="")
DATA_CENTER_ARCHIVE_ENCRYPTION_KEY = env(
    "DATA_CENTER_ARCHIVE_ENCRYPTION_KEY",
    default="",
)
DATA_CENTER_ARCHIVE_ENCRYPTION_KEY_VERSION = env(
    "DATA_CENTER_ARCHIVE_ENCRYPTION_KEY_VERSION",
    default="",
)
_SHOW_ENCRYPTION_KEY_WARNING = env.bool(
    "AGOMTRADEPRO_SHOW_ENCRYPTION_KEY_WARNING",
    default=True,
)
_IS_FIRST_INSTALL = not DATABASE_URL and not (BASE_DIR / "db.sqlite3").exists()
if not AGOMTRADEPRO_ENCRYPTION_KEY and _SHOW_ENCRYPTION_KEY_WARNING and not _IS_FIRST_INSTALL:
    import warnings

    warnings.warn(
        "AGOMTRADEPRO_ENCRYPTION_KEY not configured. New AI provider API key writes will be rejected. "
        'Generate a key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"',
        stacklevel=2,
    )

# Decision Workspace V2 feature flag
# When disabled, the unified recommendation API returns a fallback response
DECISION_WORKSPACE_V2_ENABLED = env.bool("DECISION_WORKSPACE_V2_ENABLED", default=True)

# Research integrity cutover flags. Defaults preserve legacy read paths while
# all new evidence is recorded; production enables each gate after shadowing.
RESEARCH_PIT_REQUIRED_FOR_PROMOTION = env.bool("RESEARCH_PIT_REQUIRED_FOR_PROMOTION", default=False)
PORTFOLIO_CANONICAL_PLANNER_ENABLED = env.bool("PORTFOLIO_CANONICAL_PLANNER_ENABLED", default=False)
DECISION_SNAPSHOT_REQUIRED = env.bool("DECISION_SNAPSHOT_REQUIRED", default=False)
PROMPT_EVAL_GATE_ENABLED = env.bool("PROMPT_EVAL_GATE_ENABLED", default=False)
SIGNAL_FORECAST_LEDGER_ENABLED = env.bool("SIGNAL_FORECAST_LEDGER_ENABLED", default=False)

# ========================================================================
# M3: 执行升级灰度开关
# ========================================================================

# 执行模式配置
EXECUTION_MODE = env("EXECUTION_MODE", default="paper")  # paper | broker | canary
BROKER_CANARY_RATIO = env.float("BROKER_CANARY_RATIO", default=0.1)  # 金丝雀比例 (0.0 - 1.0)

REQUIRE_CONFIRMATION_FOR_WATCH = env.bool(
    "REQUIRE_CONFIRMATION_FOR_WATCH", default=True
)  # WATCH 状态是否需要人工确认

# 决策引擎配置
DECISION_SIGNAL_THRESHOLD = env.float("DECISION_SIGNAL_THRESHOLD", default=0.6)
DECISION_CONFIDENCE_THRESHOLD = env.float("DECISION_CONFIDENCE_THRESHOLD", default=0.7)
DECISION_REGIME_ALIGNMENT_REQUIRED = env.bool("DECISION_REGIME_ALIGNMENT_REQUIRED", default=True)
DECISION_READINESS_ASSET_CODES = [
    code.strip().upper()
    for code in env.list("DECISION_READINESS_ASSET_CODES", default=["510300.SH", "000300.SH"])
    if code.strip()
]
DECISION_QUOTE_MAX_AGE_HOURS = env.float("DECISION_QUOTE_MAX_AGE_HOURS", default=4.0)
PRODUCTION_STRICT_READINESS = env.bool("PRODUCTION_STRICT_READINESS", default=False)
# 仓位引擎配置
SIZING_DEFAULT_METHOD = env("SIZING_DEFAULT_METHOD", default="fixed_fraction")
SIZING_RISK_PER_TRADE_PCT = env.float("SIZING_RISK_PER_TRADE_PCT", default=1.0)
SIZING_MAX_POSITION_PCT = env.float("SIZING_MAX_POSITION_PCT", default=20.0)
# 錙仓限制
SIZING_MIN_QTY = env.int("SIZING_MIN_QTY", default=1)
# 风控配置
RISK_MAX_SINGLE_POSITION_PCT = env.float("RISK_MAX_SINGLE_POSITION_PCT", default=20.0)
RISK_MAX_DAILY_TRADES = env.int("RISK_MAX_DAILY_TRADES", default=10)
RISK_MAX_DAILY_LOSS_PCT = env.float("RISK_MAX_DAILY_LOSS_PCT", default=5.0)
RISK_MIN_VOLUME = env.int("RISK_MIN_VOLUME", default=100000)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("SECRET_KEY", default="django-insecure-change-this-in-production")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False
ALLOWED_HOSTS: list[str] = []
FORMS_URLFIELD_ASSUME_HTTPS = True

# Application definition

# P1-3: DoS 基线 - 请求体大小限制
# 防止大请求耗尽服务器资源
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int(
    "DATA_UPLOAD_MAX_MEMORY_SIZE", default=10 * 1024 * 1024
)  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = env.int(
    "FILE_UPLOAD_MAX_MEMORY_SIZE", default=10 * 1024 * 1024
)  # 10MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = env.int(
    "DATA_UPLOAD_MAX_NUMBER_FIELDS", default=1000
)  # 最多1000个字段

INSTALLED_APPS = [
    "daphne",
    "channels",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps
    "jazzmin",  # Django Admin 美化主题
    "rest_framework",
    "rest_framework.authtoken",  # Token 认证
    "drf_spectacular",
    "django_celery_beat",
    # Shared infrastructure
    "shared",
    "core",  # For templatetags
    # Local apps
    "apps.macro",
    "apps.regime",
    "apps.filter",
    "apps.policy",
    "apps.signal",
    "apps.backtest",
    "apps.audit",
    "apps.ai_provider",
    "apps.prompt",
    "apps.config_center",
    "apps.account",  # 新增：用户账户管理
    "apps.dashboard",  # 新增：仪表盘
    "apps.equity",  # 新增：个股分析模块
    "apps.sector",  # 新增：板块分析模块
    "apps.fund",  # 新增：基金分析模块
    "apps.asset_analysis",  # 新增：通用资产分析模块
    "apps.sentiment",  # 新增：舆情情感分析模块
    "apps.simulated_trading",  # 新增：模拟盘自动交易模块
    "apps.strategy",  # 新增：投资组合策略系统
    "apps.realtime",  # 新增：实时价格监控模块
    # ========== 新模块：决策流程优化 ==========
    "apps.valuation",  # 独立估值引擎 owner（R3-lite）
    "apps.decision_rhythm",  # 决策频率约束模块（新增）
    "apps.alpha_trigger",  # Alpha 离散触发模块（新增）
    "apps.beta_gate",  # Beta 闸门模块（新增）
    "apps.events",  # 事件总线（必须位于事件订阅模块之后）
    "apps.risk_center",  # 集中风控中心（新增）
    "apps.broker_execution",  # QMT 实盘执行桥（默认关闭真实执行）
    "apps.alpha",  # Alpha AI 选股模块（新增）
    # ========== 新模块：因子选股 + 资产轮动 + 对冲组合 ==========
    "apps.factor",  # 因子选股模块（新增）
    "apps.rotation",  # 资产轮动模块（新增）
    "apps.terminal",  # 终端CLI模块（新增）
    "apps.hedge",  # 对冲组合模块（新增）
    # ========== 新模块：任务监控 ==========
    "apps.task_monitor",  # 任务监控模块（新增）
    "apps.operational_readiness",  # 生产 readiness 取证与验收
    # ========== 新模块：账户分享 ==========
    "apps.share",  # 账户分享模块（新增）
    # ========== 新模块：AI-native Agent Runtime ==========
    "apps.agent_runtime",  # AI-native 任务执行框架（新增）
    # ========== 新模块：系统级 AI Capability Catalog ==========
    "apps.ai_capability",  # 系统级 AI 能力目录与统一路由（新增）
    # ========== Prometheus 指标 ==========
    "django_prometheus",  # Prometheus 指标导出（新增）
    # ========== 新模块：安装向导 ==========
    "apps.setup_wizard",  # 系统初始化向导（新增）
    # ========== 新模块：Pulse 脉搏层 ==========
    "apps.pulse",  # Pulse 战术层脉搏模块（新增）
    # ========== 新模块：数据中台 ==========
    "apps.data_center",  # 统一数据接入与分发中心（新增）
    "apps.portfolio",  # canonical portfolio construction and transition planning
    "apps.research",  # experiment registry and promotion governance
    "apps.fixed_income",  # research-only bond analytics and relative value
    "apps.macro_factor",  # research-only external macro-factor evidence validation
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # CORS middleware - must be before CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    # 结构化日志中间件 - 在 CommonMiddleware 之前设置
    "core.middleware.logging.TraceIDMiddleware",  # 添加 trace_id 追踪
    "core.middleware.logging.RequestLoggingMiddleware",  # 记录请求日志
    "core.middleware.prometheus.PrometheusMetricsMiddleware",  # 自定义 API 业务指标
    "core.middleware.query_profiler.QueryProfilerMiddleware",  # 慢查询分析（需 QUERY_PROFILER_ENABLED=True）
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.decision_gate.DecisionRuntimeGateMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "core.urls"

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

REALTIME_WEBSOCKET_ENABLED = env.bool(
    "REALTIME_WEBSOCKET_ENABLED",
    default=False,
)
EVENT_REPLAY_ENABLED = env.bool("EVENT_REPLAY_ENABLED", default=False)
REDIS_URL = env("REDIS_URL", default="")
CHANNEL_LAYERS = (
    {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
    if REDIS_URL
    else {}
)

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Authentication URLs
LOGIN_URL = "/account/login/"
LOGIN_REDIRECT_URL = "/tui/"
LOGOUT_REDIRECT_URL = "/"

# Authentication backends
# Add lockout-aware backend to mitigate brute-force login attempts.
AUTHENTICATION_BACKENDS = [
    "core.security.LockoutModelBackend",
]

# Login lockout settings
LOGIN_LOCKOUT_MAX_ATTEMPTS = env.int("LOGIN_LOCKOUT_MAX_ATTEMPTS", default=5)
LOGIN_LOCKOUT_WINDOW_SECONDS = env.int("LOGIN_LOCKOUT_WINDOW_SECONDS", default=900)
SCENARIO_GOVERNANCE_PREVIEW_TTL_SECONDS = env.int(
    "SCENARIO_GOVERNANCE_PREVIEW_TTL_SECONDS",
    default=900,
)
LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR = env.bool(
    "LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR",
    default=False,
)

# Internationalization
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATICFILES_DIRS = [
    # Project-level assets live here. App-level assets (including core/static)
    # are discovered via AppDirectoriesFinder from INSTALLED_APPS.
    os.path.join(BASE_DIR, "static"),
]
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "core.staticfiles.ProjectAppDirectoriesFinder",
]

# Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "core", "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Global alerts for decision platform
                "core.context_processors.get_alerts",
                "core.context_processors.get_market_visuals",
                "core.context_processors.get_ui_mode",
            ],
        },
    },
]

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache Configuration (易用性改进 - Redis缓存层)
# 优先使用 Redis，开发环境可降级为内存缓存
if env("REDIS_URL", default=None):
    # 生产环境：使用 Redis
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": env("REDIS_URL", default="redis://127.0.0.1:6379/1"),
            "TIMEOUT": 900,  # 默认15分钟
            "KEY_PREFIX": "agomtradepro",
        }
    }
else:
    # 开发环境：使用内存缓存（同步模式，不需要Redis服务）
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "agomtradepro-cache",
            "TIMEOUT": 900,  # 默认15分钟
            "OPTIONS": {
                "MAX_ENTRIES": 1000,
            },
        }
    }

# Admin Site Configuration
ADMIN_TITLE = "AgomTradePro 管理后台"
ADMIN_HEADER = "AgomTradePro"
ADMIN_INDEX_TITLE = "欢迎使用 AgomTradePro 管理后台"

# Email / Notification settings
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@agomtradepro.com")
DAILY_INSPECTION_EMAIL_ENABLED = env.bool("DAILY_INSPECTION_EMAIL_ENABLED", default=True)
APP_BASE_URL = env("APP_BASE_URL", default="")

# REST Framework settings
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "core.schema.AgomAutoSchema",
    # 异常处理器（P0-1：统一异常返回格式）
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    # 认证配置
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",  # Session 认证（Web界面）
        "apps.account.interface.authentication.TerminalInternalAuthentication",  # Terminal 内部签名认证
        "apps.account.interface.authentication.MultiTokenAuthentication",  # Token 认证（API调用）
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",  # 默认需要登录
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "core.throttling.ResilientAnonRateThrottle",
        "core.throttling.ResilientUserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("DRF_THROTTLE_ANON", default="100/hour"),
        "user": env("DRF_THROTTLE_USER", default="1000/hour"),
        "backtest": env("DRF_THROTTLE_BACKTEST", default="10/hour"),  # P0-2：回测专用限流
        "write": env("DRF_THROTTLE_WRITE", default="100/hour"),  # P0-2：写操作限流
        "burst": env("DRF_THROTTLE_BURST", default="30/minute"),  # P0-2：突发保护限流
    },
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    # 避免与业务参数 ?format=csv 冲突（如审计导出接口）
    "URL_FORMAT_OVERRIDE": None,
}

# CORS Configuration (跨域资源共享)
# 默认关闭全量放行，优先白名单策略
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
)
CORS_ALLOW_CREDENTIALS = env.bool("CORS_ALLOW_CREDENTIALS", default=True)

# CORS 可信来源（允许 redirect 和预检请求缓存）
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

# CSRF 可信来源（用于 SameSite 配置）
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
)

# Spectacular settings
SPECTACULAR_SETTINGS = {
    "TITLE": "AgomTradePro API",
    "DESCRIPTION": "Agom Strategic Asset Allocation Framework API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Performance optimizations
    "SCHEMA_PATH_PREFIX": "/api/",
    "COMPONENT_SPLIT_REQUEST": True,
    "COMPONENT_NO_READ_ONLY_REQUIRED": True,
    "PREPROCESSING_HOOKS": [
        "core.schema.api_only_endpoints_preprocessing_hook",
    ],
    "ENUM_NAME_OVERRIDES": {
        "AgentTaskStatusEnum": "apps.agent_runtime.domain.entities.TaskStatus",
        "AgentTaskDomainEnum": "apps.agent_runtime.domain.entities.TaskDomain",
        "SignalDirectionEnum": [
            ("LONG", "Long"),
            ("SHORT", "Short"),
            ("NEUTRAL", "Neutral"),
        ],
        "AlphaTriggerDirectionEnum": [
            ("LONG", "LONG"),
            ("SHORT", "SHORT"),
            ("NEUTRAL", "NEUTRAL"),
        ],
        "TerminalCommandTypeEnum": [
            ("prompt", "prompt"),
            ("api", "api"),
        ],
        "TerminalCommandRiskLevelEnum": [
            ("read", "read"),
            ("write_low", "write_low"),
            ("write_high", "write_high"),
            ("admin", "admin"),
        ],
        "PromptCategoryEnum": [
            ("report", "report"),
            ("signal", "signal"),
            ("analysis", "analysis"),
            ("chat", "chat"),
        ],
        "PolicySourceCategoryEnum": [
            ("gov_docs", "政府文件库"),
            ("central_bank", "央行公告"),
            ("mof", "财政部"),
            ("csrc", "证监会"),
            ("media", "财经媒体"),
            ("other", "其他"),
        ],
        "TradeActionEnum": [
            ("buy", "买入"),
            ("sell", "卖出"),
        ],
        "StrategyActionEnum": [
            ("buy", "买入"),
            ("sell", "卖出"),
            ("hold", "持有"),
            ("weight", "设置权重"),
        ],
        "StrategyTypeEnum": [
            ("rule_based", "规则驱动"),
            ("script_based", "脚本驱动"),
            ("hybrid", "混合模式"),
            ("ai_driven", "AI驱动"),
        ],
        "BacktestRebalanceFrequencyEnum": ["monthly", "quarterly", "yearly"],
        "FactorRebalanceFrequencyEnum": ["daily", "weekly", "monthly", "quarterly"],
        "RegimeEnum": ["Recovery", "Overheat", "Stagflation", "Deflation"],
    },
    # UI optimizations
    "SWAGGER_UI_SETTINGS": {
        "defaultModelsExpandDepth": 1,
        "defaultModelExpandDepth": 1,
        "docExpansion": "none",
        "filter": True,
        "showRequestHeaders": True,
        "persistAuthorization": True,
    },
}

# Celery settings
# For development without Redis, use memory broker (tasks execute immediately)
# For production, install Redis and set REDIS_URL environment variable
if env("REDIS_URL", default=None):
    # Production mode with Redis
    CELERY_BROKER_URL = env("REDIS_URL")
    CELERY_RESULT_BACKEND = env("REDIS_URL")
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

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

# Celery safety: re-deliver tasks if worker crashes mid-execution
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_ACKS_LATE = True

CELERY_TASK_DEFAULT_QUEUE = "celery"
CELERY_TASK_QUEUES = (
    Queue("celery"),
    Queue("qlib_infer"),
    Queue("qlib_train"),
)

# Celery 队列路由配置（Qlib 任务专用队列）
CELERY_TASK_ROUTES = {
    "apps.alpha.application.tasks.qlib_train_model": {"queue": "qlib_train"},
    "apps.alpha.application.tasks.qlib_predict_scores": {"queue": "qlib_infer"},
    "apps.alpha.application.tasks.qlib_evaluate_model": {"queue": "qlib_train"},
    "apps.alpha.application.tasks.qlib_refresh_cache": {"queue": "qlib_infer"},
    "apps.alpha.application.tasks.qlib_refresh_runtime_data_task": {"queue": "qlib_infer"},
    "apps.alpha.application.tasks.qlib_refresh_runtime_data_for_codes_task": {
        "queue": "qlib_infer"
    },
}

# Qlib 任务超时配置
CELERY_TASK_TIME_LIMIT = 3600  # 1 小时
CELERY_TASK_SOFT_TIME_LIMIT = 3300  # 55 分钟

# Equity 估值修复任务超时配置（单位：秒）
EQUITY_VALUATION_SYNC_TASK_TIMEOUT = env.int(
    "EQUITY_VALUATION_SYNC_TASK_TIMEOUT", default=3600
)  # 60 分钟；314 只生产全量同步实测约 37 分钟
EQUITY_VALUATION_SYNC_TASK_SOFT_TIMEOUT = env.int(
    "EQUITY_VALUATION_SYNC_TASK_SOFT_TIMEOUT", default=3500
)

EQUITY_VALUATION_VALIDATE_TASK_TIMEOUT = env.int(
    "EQUITY_VALUATION_VALIDATE_TASK_TIMEOUT", default=600
)  # 10 分钟
EQUITY_VALUATION_VALIDATE_TASK_SOFT_TIMEOUT = env.int(
    "EQUITY_VALUATION_VALIDATE_TASK_SOFT_TIMEOUT", default=570
)

EQUITY_VALUATION_SCAN_TASK_TIMEOUT = env.int(
    "EQUITY_VALUATION_SCAN_TASK_TIMEOUT", default=3600
)  # 60 分钟；包含同步、校验与 scan
EQUITY_VALUATION_SCAN_TASK_SOFT_TIMEOUT = env.int(
    "EQUITY_VALUATION_SCAN_TASK_SOFT_TIMEOUT", default=3500
)

# Equity 估值修复默认参数
EQUITY_VALUATION_DEFAULT_LOOKBACK_DAYS = env.int(
    "EQUITY_VALUATION_DEFAULT_LOOKBACK_DAYS", default=756
)
EQUITY_VALUATION_SCAN_BATCH_LIMIT = env.int(
    "EQUITY_VALUATION_SCAN_BATCH_LIMIT", default=0
)  # 0 = 无限制

# Qlib Worker 配置建议
# celery -A core worker -l info -Q qlib_infer --max-tasks-per-child=10 --concurrency=2
# celery -A core worker -l info -Q qlib_train --max-tasks-per-child=1 --concurrency=1

# ========== MCP/SDK 操作审计日志配置 ==========
AUDIT_RETENTION_DAYS = env.int("AUDIT_RETENTION_DAYS", default=90)
AUDIT_EXPORT_MAX_ROWS = env.int("AUDIT_EXPORT_MAX_ROWS", default=10000)
AUDIT_EXPORT_MAX_DAYS = env.int("AUDIT_EXPORT_MAX_DAYS", default=90)
AUDIT_INTERNAL_SECRET_KEY = env("AUDIT_INTERNAL_SECRET_KEY", default="")
AGOMTRADEPRO_INTERNAL_AUTH_SECRET = env(
    "AGOMTRADEPRO_INTERNAL_AUTH_SECRET",
    default=AUDIT_INTERNAL_SECRET_KEY or SECRET_KEY,
)

# ========== Prometheus 指标配置 ==========
PROMETHEUS_EXPORT_MIGRATIONS = False  # 不导出 Django 迁移指标

# ========== 慢查询分析配置 ==========
# 查询性能分析中间件开关（默认关闭，生产环境按需开启）
QUERY_PROFILER_ENABLED = env.bool("QUERY_PROFILER_ENABLED", default=False)
# 慢查询阈值（毫秒），超过此值的查询会被记录
SLOW_QUERY_THRESHOLD_MS = env.int("SLOW_QUERY_THRESHOLD_MS", default=100)
# 每个请求的查询数量阈值（超过则警告）
QUERY_COUNT_WARNING_THRESHOLD = env.int("QUERY_COUNT_WARNING_THRESHOLD", default=50)
