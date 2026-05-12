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
from core.integration.runtime_settings import get_runtime_macro_index_metadata_map

DOMAIN_PERIOD_TYPES = {
    "D": PeriodType.DAY,
    "W": PeriodType.WEEK,
    "M": PeriodType.MONTH,
    "Q": PeriodType.QUARTER,
    "H": PeriodType.HALF_YEAR,
    "Y": PeriodType.YEAR,
}


def _resolve_period_types(
    indicator_code: str,
    runtime_metadata_map: dict[str, dict],
) -> tuple[str, PeriodType]:
    metadata = runtime_metadata_map.get(indicator_code, {})
    orm_period_type = str(
        metadata.get("orm_period_type_override")
        or metadata.get("default_period_type")
        or ""
    ).strip()
    domain_period_token = str(
        metadata.get("domain_period_type_override")
        or metadata.get("default_period_type")
        or orm_period_type
        or ""
    ).strip()
    domain_period_type = DOMAIN_PERIOD_TYPES.get(domain_period_token)

    if orm_period_type and domain_period_type is not None:
        return orm_period_type, domain_period_type

    fallback_period_type = orm_period_type or "M"
    return fallback_period_type, DOMAIN_PERIOD_TYPES.get(fallback_period_type, PeriodType.MONTH)


def _load_runtime_metadata_map() -> dict[str, dict]:
    try:
        return get_runtime_macro_index_metadata_map()
    except Exception:
        return {}


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
        runtime_metadata_map = _load_runtime_metadata_map()

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
                    orm_period_type, domain_period_type = _resolve_period_types(
                        indicator_code,
                        runtime_metadata_map,
                    )

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
