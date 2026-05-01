"""
Macro Sync Task Gateway for Regime Module.

通过 Gateway + 任务名签名封装 regime 对 macro Celery 任务的依赖。
"""

from celery import signature

from apps.regime.domain.protocols import MacroSyncTaskGatewayProtocol


class DjangoMacroSyncTaskGateway(MacroSyncTaskGatewayProtocol):
    """使用延迟导入构建 macro 同步任务签名。"""

    def build_sync_signature(
        self,
        source: str,
        indicator: str | None,
        days_back: int,
    ):
        return signature(
            "apps.macro.application.tasks.sync_macro_data",
            kwargs={
                "source": source,
                "indicator": indicator,
                "days_back": days_back,
            },
        )
