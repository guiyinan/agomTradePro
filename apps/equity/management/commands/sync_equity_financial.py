"""
同步股票财务数据的管理命令
"""

from typing import Any, Protocol

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.public import list_active_stock_codes
from apps.data_center.composition import get_financial_fact_repository
from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.equity.infrastructure.financial_source_gateway import (
    AKShareFinancialGateway,
    FinancialSyncBatch,
    TushareFinancialGateway,
)
from shared.config.secrets import get_secrets


class FinancialGateway(Protocol):
    """Financial source contract used by the command."""

    def fetch(self, stock_code: str, periods: int = 8) -> FinancialSyncBatch: ...


class Command(BaseCommand):
    help = "Sync equity financial data from external providers."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register financial synchronization options."""

        parser.add_argument(
            "--stock-code", action="append", dest="stock_codes", help="指定股票代码"
        )
        parser.add_argument("--periods", type=int, default=8, help="获取最近几个报告期（默认8个）")
        parser.add_argument("--source", type=str, default="tushare", choices=["tushare", "akshare"])

    def handle(self, *args: Any, **options: Any) -> None:
        """Synchronize a bounded stock universe from one configured source."""

        raw_stock_codes = options.get("stock_codes")
        if raw_stock_codes is not None and (
            not isinstance(raw_stock_codes, list)
            or not all(
                isinstance(code, str) and 0 < len(code.strip()) <= 32 for code in raw_stock_codes
            )
            or len(raw_stock_codes) > 5000
        ):
            raise CommandError("stock-code must be a list of at most 5000 bounded strings")
        stock_codes = (
            [code.strip().upper() for code in raw_stock_codes]
            if raw_stock_codes is not None
            else None
        )
        periods = options.get("periods")
        if isinstance(periods, bool) or not isinstance(periods, int) or not 1 <= periods <= 40:
            raise CommandError("periods must be an integer between 1 and 40")
        source = options.get("source")
        if source not in {"tushare", "akshare"}:
            raise CommandError("source must be tushare or akshare")

        # The governed stock universe is owned by Data Center; the command is
        # only a compatibility entry point for reading/summarizing canonical
        # facts, never a writer to the legacy equity table.
        active_codes = list_active_stock_codes()
        if stock_codes:
            selected_codes = [code for code in stock_codes if code in active_codes]
        else:
            selected_codes = active_codes

        if not selected_codes:
            raise CommandError("没有找到活跃股票")

        # 初始化网关
        if source == "tushare":
            try:
                tushare_settings = get_secrets().data_sources
            except OSError as exc:
                raise CommandError("TUSHARE_TOKEN 未配置，请先在数据源中台配置") from exc
            if not tushare_settings.tushare_token:
                raise CommandError("TUSHARE_TOKEN 未配置，请先在数据源中台配置")
            gateway: FinancialGateway = TushareFinancialGateway(
                token=tushare_settings.tushare_token,
                http_url=tushare_settings.tushare_http_url,
            )
        else:
            gateway = AKShareFinancialGateway()

        synced_count = 0
        error_count = 0

        financial_repository = get_financial_fact_repository()
        for stock_code in selected_codes:
            try:
                batch = gateway.fetch(stock_code, periods=periods)
                facts: list[FinancialFact] = []
                for record in batch.records:
                    period_type = {
                        "1Q": FinancialPeriodType.QUARTERLY,
                        "2Q": FinancialPeriodType.QUARTERLY,
                        "3Q": FinancialPeriodType.QUARTERLY,
                        "4Q": FinancialPeriodType.ANNUAL,
                    }.get(record.report_type, FinancialPeriodType.QUARTERLY)
                    metrics = {
                        "revenue": record.revenue,
                        "net_profit": record.net_profit,
                        "revenue_growth": record.revenue_growth,
                        "net_profit_growth": record.net_profit_growth,
                        "total_assets": record.total_assets,
                        "total_liabilities": record.total_liabilities,
                        "equity": record.equity,
                        "roe": record.roe,
                        "roa": record.roa,
                        "debt_ratio": record.debt_ratio,
                    }
                    for metric_code, value in metrics.items():
                        if value is None:
                            continue
                        facts.append(
                            FinancialFact(
                                asset_code=record.stock_code,
                                period_end=record.report_date,
                                period_type=period_type,
                                metric_code=metric_code,
                                value=float(value),
                                unit="%" if metric_code.endswith(("_growth", "roe", "roa", "debt_ratio")) else "",
                                source=batch.source_provider or source,
                                report_date=record.report_date,
                                extra={"legacy_report_type": record.report_type},
                            )
                        )
                stored = financial_repository.bulk_upsert(facts)
                synced_count += stored
                self.stdout.write(f"{stock_code}: {stored} canonical records")
            except Exception as exc:
                error_count += 1
                self.stderr.write(f"{stock_code}: ERROR ({type(exc).__name__})")

        self.stdout.write(
            self.style.SUCCESS(
                f"Financial sync completed: {synced_count} records, {error_count} errors"
            )
        )
