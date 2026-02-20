"""
Macro Data Source Secrets Loader

从数据库加载宏观数据源 API 密钥。
"""

from typing import Optional

from shared.domain.interfaces import DataSourceSecretsDTO


def load_secrets_from_database() -> Optional[DataSourceSecretsDTO]:
    """
    从数据库加载数据源配置

    Returns:
        Optional[DataSourceSecretsDTO]: 如果数据库中有配置则返回，否则返回 None
    """
    try:
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
            return DataSourceSecretsDTO(
                tushare_token=tushare_token,
                fred_api_key=fred_api_key,
                juhe_api_key=juhe_api_key,
            )

        return None

    except Exception:
        # 数据库未初始化或其他错误，静默失败
        # 开发环境下这很正常
        return None
