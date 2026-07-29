"""Synchronize macro facts through the canonical Data Center provider registry."""

from datetime import date, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.macro.application.use_cases import (
    SyncMacroDataRequest,
    build_sync_macro_data_use_case,
)


class Command(BaseCommand):
    """Run a provider-selected macro synchronization batch."""

    help = "从指定数据源同步宏观数据"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--source",
            type=str,
            choices=("akshare", "tushare"),
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

    def handle(self, *args: str, **options: Any) -> None:
        source = str(options["source"])
        if source not in {"akshare", "tushare"}:
            raise CommandError("macro_source_invalid")
        raw_indicators = options["indicators"]
        if not isinstance(raw_indicators, list) or not raw_indicators:
            raise CommandError("macro_indicators_invalid")
        indicators: list[str] = []
        for item in raw_indicators:
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > 64:
                raise CommandError("macro_indicators_invalid")
            indicators.append(item.strip().upper())
        if len(indicators) > 100 or len(set(indicators)) != len(indicators):
            raise CommandError("macro_indicators_invalid")
        years = int(options["years"])
        if years < 1 or years > 100:
            raise CommandError("macro_years_invalid")
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
            self.stdout.write(self.style.SUCCESS(f"同步完成，成功保存 {result.synced_count} 条"))
            return

        if result.errors:
            self.stderr.write(self.style.ERROR("macro_sync_failed"))
        self.stderr.write(
            self.style.ERROR(f"同步完成但存在错误，成功保存 {result.synced_count} 条")
        )
