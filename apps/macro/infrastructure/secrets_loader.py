"""
Macro Data Source Secrets Loader

从数据库加载宏观数据源 API 密钥。
"""


from apps.data_center.application.repository_provider import list_active_provider_configs
from shared.domain.interfaces import DataSourceSecretsDTO


def load_secrets_from_database() -> DataSourceSecretsDTO | None:
    """
    从数据库加载数据源配置

    Returns:
        Optional[DataSourceSecretsDTO]: 如果数据库中有配置则返回，否则返回 None
    """
    try:
        configs = list_active_provider_configs()

        tushare_token = None
        tushare_http_url = None
        fred_api_key = ""
        juhe_api_key = None

        for config in configs:
            if config.source_type == "tushare" and config.api_key:
                tushare_token = config.api_key
                tushare_http_url = config.http_url or None
            elif config.source_type == "fred" and config.api_key:
                fred_api_key = config.api_key
            elif config.source_type == "juhe" and config.api_key:
                juhe_api_key = config.api_key

        if tushare_token:
            return DataSourceSecretsDTO(
                tushare_token=tushare_token,
                tushare_http_url=tushare_http_url,
                fred_api_key=fred_api_key,
                juhe_api_key=juhe_api_key,
            )

        return None

    except Exception:
        # 数据库未初始化或其他错误，静默失败
        # 开发环境下这很正常
        return None
