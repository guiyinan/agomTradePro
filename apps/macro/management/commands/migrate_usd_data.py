"""
数据迁移命令：修复美元口径数据

将所有美元单位的宏观数据乘以汇率，转换为人民币单位

⚠️ 安全第一：执行前必须做全量备份
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from datetime import datetime
from decimal import Decimal

from apps.macro.infrastructure.models import MacroIndicatorModel
from apps.macro.domain.entities import normalize_currency_unit
from apps.macro.infrastructure.exchange_rate_config import ExchangeRateService


class Command(BaseCommand):
    help = '迁移美元口径宏观数据，添加汇率转换'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='模拟运行，不实际修改数据',
        )
        parser.add_argument(
            '--exchange-rate',
            type=float,
            default=None,
            help='指定汇率（默认从 ExchangeRateService 获取）',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        manual_rate = options.get('exchange_rate')

        # 🔒 安全检查：强制先做备份
        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write(self.style.WARNING("⚠️  安全第一：执行迁移前必须做全量备份"))
        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write("请按以下步骤操作：")
        self.stdout.write("1. 备份数据：")
        self.stdout.write("   python manage.py dumpdata macro.MacroIndicatorModel > backup_before_usd_fix.json")
        self.stdout.write("")
        self.stdout.write("2. 确认备份完成后，运行模拟迁移：")
        self.stdout.write("   python manage.py migrate_usd_data --dry-run")
        self.stdout.write("")
        self.stdout.write("3. 确认无误后，执行正式迁移：")
        self.stdout.write("   python manage.py migrate_usd_data")
        self.stdout.write("")
        self.stdout.write("=" * 60)

        # 询问用户是否已备份
        if not dry_run:
            confirm = input("请确认您已完成数据备份 (输入 'yes' 继续): ")
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.ERROR("❌ 未确认备份，迁移已取消"))
                return

        # 获取汇率
        if manual_rate:
            exchange_rate = manual_rate
            self.stdout.write(f"使用手动指定汇率: {exchange_rate}")
        else:
            exchange_rate = ExchangeRateService.get_usd_cny_rate()
            self.stdout.write(f"使用服务获取汇率: {exchange_rate}")

        # 查找所有美元单位的数据
        usd_indicators = MacroIndicatorModel._default_manager.filter(
            original_unit__icontains='美元'
        )

        total_count = usd_indicators.count()
        self.stdout.write(f"找到 {total_count} 条美元口径数据")

        if total_count == 0:
            self.stdout.write(self.style.WARNING("没有需要迁移的数据"))
            return

        # 统计信息
        migrated_count = 0
        error_count = 0
        error_details = []

        with transaction.atomic():
            for indicator in usd_indicators:
                try:
                    # 计算转换后的值
                    old_value = float(indicator.value)
                    new_value, new_unit = normalize_currency_unit(
                        old_value,
                        indicator.original_unit,
                        exchange_rate=exchange_rate,
                    )

                    # 计算变化
                    change_pct = (new_value - old_value) / old_value * 100 if old_value != 0 else 0

                    if dry_run:
                        self.stdout.write(
                            f"[DRY RUN] {indicator.code} | {indicator.reporting_period}: "
                            f"{old_value:,.0f} → {new_value:,.0f} ({change_pct:+.1f}%)"
                        )
                    else:
                        # 更新数据
                        indicator.value = Decimal(str(new_value))
                        indicator.unit = new_unit
                        indicator.save()

                        migrated_count += 1
                        if migrated_count % 100 == 0:
                            self.stdout.write(f"已迁移 {migrated_count}/{total_count}...")

                except Exception as e:
                    error_count += 1
                    error_details.append(f"{indicator.code}@{indicator.reporting_period}: {str(e)}")
                    self.stdout.write(self.style.ERROR(f"错误: {indicator.code}@{indicator.reporting_period}: {e}"))

        # 输出总结
        self.stdout.write("=" * 60)
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"[DRY RUN 完成] 将迁移 {total_count} 条数据"))
        else:
            self.stdout.write(self.style.SUCCESS(f"迁移完成: {migrated_count}/{total_count} 成功"))

        if error_count > 0:
            self.stdout.write(self.style.ERROR(f"错误: {error_count} 条"))
            for detail in error_details[:10]:  # 只显示前 10 个错误
                self.stdout.write(f"  - {detail}")

