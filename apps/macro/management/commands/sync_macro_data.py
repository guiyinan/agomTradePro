"""
Django Management Command: 同步宏观数据

用法:
    python manage.py sync_macro_data --source akshare
    python manage.py sync_macro_data --source akshare --indicators PMI CPI
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.macro.domain.entities import MacroIndicator, PeriodType
from apps.macro.infrastructure.adapters.akshare_adapter import AKShareAdapter
from apps.macro.infrastructure.providers import DjangoMacroRepository

# 高频指标映射到对应的 period_type
# 注意：ORM 支持扩展类型（10Y, 5Y 等），但 Domain 层 PeriodType 枚举不支持
# 对于这些指标，我们使用 PeriodType.DAY 并在 ORM 层存储实际类型
HIGH_FREQ_INDICATORS = {
    # Phase 1: 日度核心指标
    "CN_BOND_10Y": ("10Y", PeriodType.DAY),
    "CN_BOND_5Y": ("5Y", PeriodType.DAY),
    "CN_BOND_2Y": ("2Y", PeriodType.DAY),
    "CN_BOND_1Y": ("1Y", PeriodType.DAY),
    "CN_TERM_SPREAD_10Y1Y": ("D", PeriodType.DAY),
    "CN_TERM_SPREAD_10Y2Y": ("D", PeriodType.DAY),
    "CN_CORP_YIELD_AAA": ("10Y", PeriodType.DAY),
    "CN_CORP_YIELD_AA": ("10Y", PeriodType.DAY),
    "CN_CREDIT_SPREAD": ("D", PeriodType.DAY),
    "CN_NHCI": ("W", PeriodType.WEEK),
    "CN_FX_CENTER": ("D", PeriodType.DAY),
    "US_BOND_10Y": ("10Y", PeriodType.DAY),
    "USD_INDEX": ("D", PeriodType.DAY),
    "VIX_INDEX": ("D", PeriodType.DAY),

    # Phase 2: 周度指标（使用公开数据源替代）
    "CN_POWER_GEN": ("M", PeriodType.MONTH),  # 月度用电量数据
    "CN_BLAST_FURNACE": ("W", PeriodType.WEEK),  # 钢铁指数周聚合
    "CN_CCFI": ("W", PeriodType.WEEK),  # BDI航运指数周聚合
    "CN_SCFI": ("W", PeriodType.WEEK),  # BCI航运指数周聚合

    # Phase 3: PMI 分项指标（手动维护数据文件）
    "CN_PMI_NEW_ORDER": ("M", PeriodType.MONTH),  # 新订单指数
    "CN_PMI_INVENTORY": ("M", PeriodType.MONTH),  # 产成品库存指数
    "CN_PMI_RAW_MAT": ("M", PeriodType.MONTH),  # 原材料库存指数
    "CN_PMI_PURCHASE": ("M", PeriodType.MONTH),  # 采购量指数
    "CN_PMI_PRODUCTION": ("M", PeriodType.MONTH),  # 生产指数
    "CN_PMI_EMPLOYMENT": ("M", PeriodType.MONTH),  # 从业人员指数
}


class Command(BaseCommand):
    help = '从指定数据源同步宏观数据'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            default='akshare',
            help='数据源 (akshare, tushare)'
        )
        parser.add_argument(
            '--indicators',
            nargs='+',
            default=['CN_PMI', 'CN_CPI', 'CN_PPI'],
            help='要同步的指标代码列表'
        )
        parser.add_argument(
            '--years',
            type=int,
            default=10,
            help='同步最近 N 年的数据'
        )

    def handle(self, *args, **options):
        source = options['source']
        indicators = options['indicators']
        years = options['years']

        self.stdout.write(self.style.SUCCESS(f'\n{"="*60}'))
        self.stdout.write(self.style.SUCCESS('开始同步宏观数据'))
        self.stdout.write(self.style.SUCCESS(f'数据源: {source}'))
        self.stdout.write(self.style.SUCCESS(f'指标: {", ".join(indicators)}'))
        self.stdout.write(self.style.SUCCESS(f'{"="*60}\n'))

        if source == 'akshare':
            adapter = AKShareAdapter()
        else:
            self.stdout.write(self.style.ERROR(f'不支持的数据源: {source}'))
            return

        repository = DjangoMacroRepository()
        end_date = date.today()
        start_date = end_date - timedelta(days=365 * years)

        total_saved = 0

        for indicator_code in indicators:
            self.stdout.write(f'\n同步 {indicator_code}...')

            try:
                # 获取数据
                data_points = adapter.fetch(indicator_code, start_date, end_date)

                if not data_points:
                    self.stdout.write(self.style.WARNING('  未获取到数据'))
                    continue

                self.stdout.write(f'  获取到 {len(data_points)} 条数据')

                # 保存数据
                saved_count = 0
                for dp in data_points:
                    # 确定正确的 period_type
                    if indicator_code in HIGH_FREQ_INDICATORS:
                        orm_period_type, domain_period_type = HIGH_FREQ_INDICATORS[indicator_code]
                    elif 'GDP' in indicator_code:
                        orm_period_type = domain_period_type = PeriodType.QUARTER
                    else:
                        orm_period_type = domain_period_type = PeriodType.MONTH

                    # 构建指标实体（使用 domain PeriodType）
                    indicator = MacroIndicator(
                        code=dp.code,
                        value=dp.value,
                        reporting_period=dp.observed_at,
                        period_type=domain_period_type,
                        unit=dp.unit,
                        original_unit=dp.original_unit,
                        published_at=dp.published_at or dp.observed_at,
                        source=dp.source
                    )

                    try:
                        # 保存时传入 ORM period_type
                        repository.save_indicator(indicator, revision_number=1, period_type_override=orm_period_type)
                        saved_count += 1
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f'  保存失败: {e}'))

                self.stdout.write(self.style.SUCCESS(f'  成功保存 {saved_count} 条'))
                total_saved += saved_count

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  同步失败: {e}'))

        self.stdout.write(self.style.SUCCESS(f'\n{"="*60}'))
        self.stdout.write(self.style.SUCCESS(f'同步完成！共保存 {total_saved} 条数据'))
        self.stdout.write(self.style.SUCCESS(f'{"="*60}\n'))
