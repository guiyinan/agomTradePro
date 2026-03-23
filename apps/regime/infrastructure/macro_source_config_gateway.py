"""
Macro Source Config Gateway for Regime Module.

封装 regime 页面层对 macro 数据源配置的访问。
"""

from types import SimpleNamespace
from typing import List

from apps.regime.domain.protocols import (
    MacroSourceConfigGatewayProtocol,
    MacroSourceSummary,
)


class DjangoMacroSourceConfigGateway(MacroSourceConfigGatewayProtocol):
    """延迟导入 macro 数据源配置模型。"""

    def list_active_sources(self) -> list[MacroSourceSummary]:
        try:
            from apps.macro.infrastructure.models import DataSourceConfig

            sources = list(
                DataSourceConfig._default_manager.filter(is_active=True).order_by("priority")
            )
            if sources:
                return [
                    MacroSourceSummary(
                        source_type=source.source_type,
                        name=source.name,
                    )
                    for source in sources
                ]
        except Exception:
            pass

        return [
            MacroSourceSummary(source_type="akshare", name="AKShare"),
            MacroSourceSummary(source_type="tushare", name="Tushare Pro"),
        ]
