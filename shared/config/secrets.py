"""
Unified Secrets Management.

支持从环境变量和数据库加载敏感配置。
优先级: 数据库 > 环境变量
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


@dataclass(frozen=True)
class DataSourceSecrets:
    """数据源 API 密钥"""
    tushare_token: str
    fred_api_key: str
    juhe_api_key: Optional[str] = None


@dataclass(frozen=True)
class AppSecrets:
    """应用密钥配置"""
    data_sources: DataSourceSecrets
    slack_webhook: Optional[str] = None
    alert_email: Optional[str] = None


def _load_from_env() -> AppSecrets:
    """从环境变量加载密钥（降级方案）"""
    tushare_token = os.environ.get("TUSHARE_TOKEN", "")

    # 不在启动时强制要求 token，允许从数据库读取
    return AppSecrets(
        data_sources=DataSourceSecrets(
            tushare_token=tushare_token,
            fred_api_key=os.environ.get("FRED_API_KEY", ""),
            juhe_api_key=os.environ.get("JUHE_API_KEY"),
        ),
        slack_webhook=os.environ.get("SLACK_WEBHOOK_URL"),
        alert_email=os.environ.get("ALERT_EMAIL"),
    )


def _load_from_database() -> Optional[AppSecrets]:
    """
    从数据库加载数据源配置

    Returns:
        Optional[AppSecrets]: 如果数据库中有配置则返回，否则返回 None
    """
    try:
        # 延迟导入 Django（避免启动循环）
        import django
        from django.conf import settings

        # 如果 Django 未配置，跳过数据库读取
        if not settings.configured:
            return None

        django.setup()

        from apps.macro.infrastructure.models import DataSourceConfig

        # 只获取启用的配置
        configs = DataSourceConfig.objects.filter(is_active=True).order_by('priority')

        tushare_token = None
        fred_api_key = ""
        juhe_api_key = None

        for config in configs:
            if config.source_type == 'tushare' and config.api_key:
                tushare_token = config.api_key
            elif config.source_type == 'fred' and config.api_key:
                fred_api_key = config.api_key
            elif config.source_type == 'juhe' and config.api_key:
                juhe_api_key = config.api_key

        if tushare_token:
            return AppSecrets(
                data_sources=DataSourceSecrets(
                    tushare_token=tushare_token,
                    fred_api_key=fred_api_key,
                    juhe_api_key=juhe_api_key,
                ),
                slack_webhook=os.environ.get("SLACK_WEBHOOK_URL"),
                alert_email=os.environ.get("ALERT_EMAIL"),
            )

        return None

    except Exception as e:
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
        raise EnvironmentError(
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
