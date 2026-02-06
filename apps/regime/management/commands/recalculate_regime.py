"""
重新计算 Regime 数据

通胀动量算法已更新为绝对差值动量（避免低基数扭曲）。
需要清除旧数据并重新计算。

使用方法:
    python manage.py recalculate_regime
    python manage.py recalculate_regime --clear-cache-only
    python manage.py recalculate_regime --start-date=2020-01-01
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from datetime import date, timedelta
from typing import Optional

from apps.regime.application.use_cases import CalculateRegimeUseCase, CalculateRegimeRequest
from apps.regime.infrastructure.models import RegimeLog
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from shared.infrastructure.cache_service import CacheService


class Command(BaseCommand):
    help = '重新计算 Regime 数据（使用通胀绝对动量算法）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear-cache-only',
            action='store_true',
            dest='clear_cache_only',
            help='仅清除缓存，不重新计算',
        )
        parser.add_argument(
            '--start-date',
            type=str,
            default='2019-01-01',
            help='重新计算的起始日期 (YYYY-MM-DD)，默认 2019-01-01',
        )
        parser.add_argument(
            '--end-date',
            type=str,
            default=None,
            help='重新计算的结束日期 (YYYY-MM-DD)，默认今天',
        )
        parser.add_argument(
            '--skip-backup',
            action='store_true',
            dest='skip_backup',
            help='跳过数据备份',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('=== Regime 数据重新计算工具 ==='))

        # 1. 清除缓存
        self.stdout.write('\n[1/4] 清除 Redis 缓存...')
        cache_cleared = CacheService.invalidate_regime()
        if cache_cleared:
            self.stdout.write(self.style.SUCCESS('  缓存已清除'))
        else:
            self.stdout.write(self.style.WARNING('  缓存清除失败（可能不存在）'))

        if options.get('clear_cache_only'):
            self.stdout.write(self.style.SUCCESS('仅清除缓存模式，结束执行'))
            return

        # 2. 备份现有数据
        if not options.get('skip_backup'):
            self.stdout.write('\n[2/4] 备份现有数据...')
            backup_count = self._backup_existing_data()
            self.stdout.write(self.style.SUCCESS(f'  已备份 {backup_count} 条记录'))

        # 3. 删除旧数据
        self.stdout.write('\n[3/4] 删除旧 Regime 数据...')
        deleted_count = self._delete_old_data()
        self.stdout.write(self.style.SUCCESS(f'  已删除 {deleted_count} 条记录'))

        # 4. 重新计算
        self.stdout.write('\n[4/4] 重新计算 Regime 数据...')
        start_date = date.fromisoformat(options['start_date'])
        end_date = date.fromisoformat(options['end_date']) if options.get('end_date') else date.today()

        calculated_count = self._recalculate_regime(start_date, end_date)

        self.stdout.write(self.style.SUCCESS(f'\n=== 完成！共计算 {calculated_count} 条 Regime 记录 ==='))

    def _backup_existing_data(self) -> int:
        """备份现有数据到 JSON"""
        import json
        from pathlib import Path

        records = list(RegimeLog._default_manager.all().order_by('observed_at').values(
            'observed_at', 'growth_momentum_z', 'inflation_momentum_z',
            'distribution', 'dominant_regime', 'confidence'
        ))

        if not records:
            self.stdout.write('  没有数据需要备份')
            return 0

        # 保存到文件
        backup_dir = Path('management/backups')
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        backup_file = backup_dir / f'regime_log_backup_{timestamp}.json'

        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2, default=str)

        self.stdout.write(f'  备份文件: {backup_file}')
        return len(records)

    def _delete_old_data(self) -> int:
        """删除所有 RegimeLog 数据"""
        count, _ = RegimeLog._default_manager.all().delete()
        return count

    def _recalculate_regime(self, start_date: date, end_date: date) -> int:
        """
        重新计算 Regime 数据

        策略：按月计算，确保有足够的数据
        """
        # 初始化
        macro_repository = DjangoMacroRepository()
        regime_repository = DjangoRegimeRepository()

        # 显式创建 RegimeCalculator，使用修复后的参数
        # 2026-01-22 修复：调整参数以适应有限数据（35条记录）
        from apps.regime.domain.services import RegimeCalculator
        calculator = RegimeCalculator(
            momentum_period=3,
            zscore_window=24,      # 修复：从60降低到24
            zscore_min_periods=12,  # 修复：从24降低到12
            sigmoid_k=2.0,
            use_absolute_inflation_momentum=True  # 关键：使用绝对动量
        )

        use_case = CalculateRegimeUseCase(
            repository=macro_repository,
            regime_repository=regime_repository,
            calculator=calculator
        )

        # 获取可用日期范围
        available_dates = macro_repository.get_available_dates(
            codes=['CN_PMI', 'CN_CPI'],
            start_date=start_date,
            end_date=end_date
        )

        if not available_dates:
            self.stdout.write(self.style.WARNING('  没有可用的数据日期'))
            return 0

        # 按月采样（每月最后一个可用日期）
        monthly_dates = self._sample_monthly_dates(available_dates)

        self.stdout.write(f'  从 {len(available_dates)} 个可用日期中采样了 {len(monthly_dates)} 个月度日期')

        success_count = 0
        error_count = 0

        for i, calc_date in enumerate(monthly_dates):
            try:
                request = CalculateRegimeRequest(
                    as_of_date=calc_date,
                    use_pit=True,
                    growth_indicator="PMI",
                    inflation_indicator="CPI",
                    data_source="akshare"
                )

                response = use_case.execute(request)

                if response.success:
                    snapshot = response.snapshot

                    # 保存到数据库
                    regime_repository.save_snapshot(snapshot)

                    # 显示进度
                    regime_name = snapshot.dominant_regime
                    confidence = snapshot.confidence
                    growth_z = snapshot.growth_momentum_z
                    inflation_z = snapshot.inflation_momentum_z

                    self.stdout.write(
                        f'  [{i+1}/{len(monthly_dates)}] {calc_date}: '
                        f'{regime_name} ({confidence:.1%}) | '
                        f'Z=[{growth_z:+.2f}, {inflation_z:+.2f}]'
                    )

                    success_count += 1
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'  [{i+1}/{len(monthly_dates)}] {calc_date}: 计算失败 - {response.error}'
                        )
                    )
                    error_count += 1

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'  [{i+1}/{len(monthly_dates)}] {calc_date}: 异常 - {str(e)}'
                    )
                )
                error_count += 1

        self.stdout.write(f'\n  计算完成: 成功 {success_count} 条, 失败 {error_count} 条')

        return success_count

    def _sample_monthly_dates(self, dates: list) -> list:
        """
        从日期列表中每月采样最后一个日期

        Args:
            dates: 排序后的日期列表

        Returns:
            采样后的日期列表（每月一个）
        """
        if not dates:
            return []

        sampled = {}
        for dt in dates:
            year_month = (dt.year, dt.month)
            # 保留每月最后一个日期
            sampled[year_month] = dt

        # 按时间排序返回
        return sorted(sampled.values())

