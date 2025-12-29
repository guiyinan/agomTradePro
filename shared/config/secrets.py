"""
Unified Secrets Management.

Loads sensitive configuration from environment variables.
"""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class DataSourceSecrets:
    """数据源 API 密钥"""
    tushare_token: str
    fred_api_key: str
    juhe_api_key: str | None = None


@dataclass(frozen=True)
class AppSecrets:
    """应用密钥配置"""
    data_sources: DataSourceSecrets
    slack_webhook: str | None = None
    alert_email: str | None = None


@lru_cache(maxsize=1)
def get_secrets() -> AppSecrets:
    """
    从环境变量加载密钥，启动时验证必填项
    """
    tushare_token = os.environ.get("TUSHARE_TOKEN")
    if not tushare_token:
        raise EnvironmentError("TUSHARE_TOKEN is required")

    return AppSecrets(
        data_sources=DataSourceSecrets(
            tushare_token=tushare_token,
            fred_api_key=os.environ.get("FRED_API_KEY", ""),
            juhe_api_key=os.environ.get("JUHE_API_KEY"),
        ),
        slack_webhook=os.environ.get("SLACK_WEBHOOK_URL"),
        alert_email=os.environ.get("ALERT_EMAIL"),
    )
