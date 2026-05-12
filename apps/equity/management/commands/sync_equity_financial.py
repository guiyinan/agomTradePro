"""
同步股票财务数据的管理命令
"""


from django.core.management.base import BaseCommand, CommandError

from apps.equity.infrastructure.financial_source_gateway import (
    AKShareFinancialGateway,
    TushareFinancialGateway,
)
from apps.equity.infrastructure.models import FinancialDataModel, StockInfoModel
from shared.config.secrets import get_secrets


class Command(BaseCommand):
    help = "Sync equity financial data from external providers."

    def add_arguments(self, parser):
        parser.add_argument("--stock-code", action="append", dest="stock_codes", help="指定股票代码")
        parser.add_argument("--periods", type=int, default=8, help="获取最近几个报告期（默认8个）")
        parser.add_argument("--source", type=str, default="tushare", choices=["tushare", "akshare"])

    def handle(self, *args, **options):
        stock_codes = options.get("stock_codes")
        periods = options["periods"]
        source = options["source"]

        # 获取要同步的股票列表
        if stock_codes:
            stocks = StockInfoModel.objects.filter(stock_code__in=stock_codes, is_active=True)
        else:
            stocks = StockInfoModel.objects.filter(is_active=True).order_by("stock_code")

        if not stocks.exists():
            raise CommandError("没有找到活跃股票")

        # 初始化网关
        if source == "tushare":
            try:
                tushare_settings = get_secrets().data_sources
            except OSError as exc:
                raise CommandError("TUSHARE_TOKEN 未配置，请先在数据源中台配置") from exc
            if not tushare_settings.tushare_token:
                raise CommandError("TUSHARE_TOKEN 未配置，请先在数据源中台配置")
            gateway = TushareFinancialGateway(
                token=tushare_settings.tushare_token,
                http_url=tushare_settings.tushare_http_url,
            )
        else:
            gateway = AKShareFinancialGateway()

        synced_count = 0
        error_count = 0

        for stock in stocks:
            try:
                batch = gateway.fetch(stock.stock_code, periods=periods)
                for record in batch.records:
                    FinancialDataModel.objects.update_or_create(
                        stock_code=record.stock_code,
                        report_date=record.report_date,
                        report_type=record.report_type,
                        defaults={
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
                    )
                synced_count += len(batch.records)
                self.stdout.write(f"{stock.stock_code}: {len(batch.records)} records")
            except Exception as e:
                error_count += 1
                self.stderr.write(f"{stock.stock_code}: ERROR - {e}")

        self.stdout.write(self.style.SUCCESS(f"Financial sync completed: {synced_count} records, {error_count} errors"))
