"""
Unified Secrets Management.

支持从环境变量和数据库加载敏感配置。
优先级: 数据库 > 环境变量

架构说明：
- 本模块使用注册表模式，避免直接依赖 apps/ 模块
- 数据库加载器由 apps.macro 在启动时注册
- 这确保了 shared/ 不依赖 apps/，符合四层架构规范
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from shared.domain.interfaces import DataSourceSecretsDTO


@dataclass(frozen=True)
class DataSourceSecrets:
    """数据源 API 密钥"""
    tushare_token: str
    fred_api_key: str
    tushare_http_url: str | None = None
    juhe_api_key: str | None = None


@dataclass(frozen=True)
class AppSecrets:
    """应用密钥配置"""
    data_sources: DataSourceSecrets
    slack_webhook: str | None = None
    alert_email: str | None = None


# ========== 注册表模式 ==========

# 数据库密钥加载器注册表
# 由 apps.macro.apps.MacroConfig.ready() 注册
_database_secrets_loader: Callable[[], DataSourceSecretsDTO | None] | None = None


def register_database_secrets_loader(loader: Callable[[], DataSourceSecretsDTO | None]) -> None:
    """
    注册数据库密钥加载器

    由 apps.macro.apps.MacroConfig.ready() 调用，
    将数据库加载逻辑注册到本模块。

    Args:
        loader: 返回 DataSourceSecretsDTO 的可调用对象
    """
    global _database_secrets_loader
    _database_secrets_loader = loader


def _load_from_env() -> AppSecrets:
    """从环境变量加载密钥（降级方案）"""
    tushare_token = os.environ.get("TUSHARE_TOKEN", "")
    tushare_http_url = os.environ.get("TUSHARE_HTTP_URL")

    # 不在启动时强制要求 token，允许从数据库读取
    return AppSecrets(
        data_sources=DataSourceSecrets(
            tushare_token=tushare_token,
            tushare_http_url=tushare_http_url,
            fred_api_key=os.environ.get("FRED_API_KEY", ""),
            juhe_api_key=os.environ.get("JUHE_API_KEY"),
        ),
        slack_webhook=os.environ.get("SLACK_WEBHOOK_URL"),
        alert_email=os.environ.get("ALERT_EMAIL"),
    )


def _load_from_database() -> AppSecrets | None:
    """
    从数据库加载数据源配置

    使用注册的加载器，避免直接依赖 apps/ 模块。

    Returns:
        Optional[AppSecrets]: 如果数据库中有配置则返回，否则返回 None
    """
    global _database_secrets_loader

    if _database_secrets_loader is None:
        return None

    try:
        db_secrets = _database_secrets_loader()
        if db_secrets and db_secrets.tushare_token:
            return AppSecrets(
                data_sources=DataSourceSecrets(
                    tushare_token=db_secrets.tushare_token,
                    tushare_http_url=db_secrets.tushare_http_url,
                    fred_api_key=db_secrets.fred_api_key,
                    juhe_api_key=db_secrets.juhe_api_key,
                ),
                slack_webhook=os.environ.get("SLACK_WEBHOOK_URL"),
                alert_email=os.environ.get("ALERT_EMAIL"),
            )
        return None

    except Exception:
        # 数据库未初始化或其他错误，静默失败
        # 开发环境下这很正常
        return None


@lru_cache(maxsize=1)
def get_secrets() -> AppSecrets:
    """
    获取应用密钥配置

    优先级:
    1. 数据库配置（DataSourceConfig）
    2. 环境变量

    Returns:
        AppSecrets: 应用密钥配置

    Raises:
        EnvironmentError: 如果没有配置 Tushare Token
    """
    # 先尝试从数据库读取
    db_secrets = _load_from_database()
    if db_secrets and db_secrets.data_sources.tushare_token:
        return db_secrets

    # 降级到环境变量
    env_secrets = _load_from_env()

    # 检查是否有至少一个配置源
    if not env_secrets.data_sources.tushare_token:
        raise OSError(
            "未配置 Tushare Token！\n"
            "请通过以下方式之一配置:\n"
            "1. 访问 http://127.0.0.1:8000/admin/ 添加数据源配置\n"
            "2. 设置环境变量 TUSHARE_TOKEN"
        )

    return env_secrets


def clear_secrets_cache() -> None:
    """清除密钥缓存（用于测试或配置更新后）"""
    get_secrets.cache_clear()


def get_tushare_token() -> str:
    """
    获取 Tushare Token 的便捷函数

    Returns:
        str: Tushare Token
    """
    return get_secrets().data_sources.tushare_token


def get_tushare_http_url() -> str | None:
    """
    获取 Tushare 自定义 HTTP URL。

    Returns:
        Optional[str]: 自定义 URL，未配置则返回 None
    """
    return get_secrets().data_sources.tushare_http_url
