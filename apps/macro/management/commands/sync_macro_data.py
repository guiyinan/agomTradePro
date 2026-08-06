"""Synchronize macro facts through the canonical Data Center provider registry."""

from datetime import date, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.public import list_macro_indicator_codes
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
            help="同步最近 N 年的数据；显式提供 --start/--end 时忽略",
        )
        parser.add_argument(
            "--start",
            type=str,
            default=None,
            help="显式起始日期（YYYY-MM-DD，必须与 --end 同时提供）",
        )
        parser.add_argument(
            "--end",
            type=str,
            default=None,
            help="显式结束日期（YYYY-MM-DD，必须与 --start 同时提供）",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_indicators",
            help="列出 Data Center Catalog 中的可用指标后退出",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="兼容旧脚本参数；canonical 同步始终按幂等强制刷新执行",
        )

    def handle(self, *args: str, **options: Any) -> None:
        if not isinstance(options.get("list_indicators", False), bool):
            raise CommandError("macro_list_option_invalid")
        if bool(options.get("list_indicators", False)):
            codes = sorted(set(list_macro_indicator_codes()))
            self.stdout.write("\n".join(codes))
            return

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
        raw_start = options.get("start")
        raw_end = options.get("end")
        if bool(raw_start) != bool(raw_end):
            raise CommandError("macro_date_range_incomplete")
        if raw_start and raw_end:
            start_date = self._parse_date(raw_start, "macro_start_date_invalid")
            end_date = self._parse_date(raw_end, "macro_end_date_invalid")
            if start_date > end_date:
                raise CommandError("macro_date_range_invalid")
            if end_date > date.today():
                raise CommandError("macro_end_date_in_future")
            if (end_date - start_date).days > 36525:
                raise CommandError("macro_date_range_too_large")
        else:
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

    @staticmethod
    def _parse_date(value: object, error_code: str) -> date:
        """Parse one explicit ISO date without accepting implicit coercion."""

        if isinstance(value, date):
            return value
        if not isinstance(value, str) or not value.strip():
            raise CommandError(error_code)
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise CommandError(error_code) from exc
