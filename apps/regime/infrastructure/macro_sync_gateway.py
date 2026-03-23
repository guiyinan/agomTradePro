"""
Macro Sync Task Gateway for Regime Module.

通过 Gateway + 延迟导入封装 regime 对 macro Celery 任务的依赖。
"""

from typing import Optional

from apps.regime.domain.protocols import MacroSyncTaskGatewayProtocol


class DjangoMacroSyncTaskGateway(MacroSyncTaskGatewayProtocol):
    """使用延迟导入构建 macro 同步任务签名。"""

    def build_sync_signature(
        self,
        source: str,
        indicator: str | None,
        days_back: int,
    ):
        from apps.macro.application.tasks import sync_macro_data

        return sync_macro_data.s(
            source=source,
            indicator=indicator,
            days_back=days_back,
        )
