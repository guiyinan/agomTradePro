"""Synchronize macro facts through the canonical Data Center provider registry."""

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.macro.application.use_cases import (
    SyncMacroDataRequest,
    build_sync_macro_data_use_case,
)


class Command(BaseCommand):
    """Run a provider-selected macro synchronization batch."""

    help = "从指定数据源同步宏观数据"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--source",
            type=str,
            default="akshare",
            help="数据源 (akshare, tushare)",
        )
        parser.add_argument(
            "--indicators",
            nargs="+",
            default=["CN_PMI", "CN_CPI", "CN_PPI"],
            help="要同步的指标代码列表",
        )
        parser.add_argument(
            "--years",
            type=int,
            default=10,
            help="同步最近 N 年的数据",
        )

    def handle(self, *args, **options) -> None:
        source = str(options["source"])
        indicators = list(options["indicators"])
        years = int(options["years"])
        end_date = date.today()
        start_date = end_date - timedelta(days=365 * years)

        result = build_sync_macro_data_use_case(source).execute(
            SyncMacroDataRequest(
                start_date=start_date,
                end_date=end_date,
                indicators=indicators,
                force_refresh=True,
            )
        )

        if result.success:
            self.stdout.write(
                self.style.SUCCESS(f"同步完成，成功保存 {result.synced_count} 条")
            )
            return

        for error in result.errors:
            self.stderr.write(self.style.ERROR(error))
        self.stderr.write(
            self.style.ERROR(f"同步完成但存在错误，成功保存 {result.synced_count} 条")
        )
