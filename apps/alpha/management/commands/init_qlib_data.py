"""
Initialize Qlib Data Management Command

初始化 Qlib 数据的 Django 管理命令。
"""

import os
import sys
import logging
from pathlib import Path
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    初始化 Qlib 数据命令

    用法:
        python manage.py init_qlib_data [options]

    选项:
        --download: 下载 Qlib 数据（如果没有）
        --check: 检查数据完整性
        --universe: 指定股票池（默认 csi300）
        --days: 准备多少天的数据（默认 365）
        --region: 区域配置（默认 CN）
    """

    help = 'Initialize Qlib data for alpha signals'

    def add_arguments(self, parser):
        parser.add_argument(
            '--download',
            action='store_true',
            dest='download',
            help='Download Qlib data if not exists',
        )
        parser.add_argument(
            '--check',
            action='store_true',
            dest='check',
            help='Check data integrity only',
        )
        parser.add_argument(
            '--universe',
            type=str,
            default='csi300',
            dest='universe',
            help='Universe to prepare (default: csi300)',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=365,
            dest='days',
            help='Number of days to prepare (default: 365)',
        )
        parser.add_argument(
            '--region',
            type=str,
            default='CN',
            dest='region',
            help='Region configuration (default: CN)',
        )
        parser.add_argument(
            '--provider-uri',
            type=str,
            default='~/.qlib/qlib_data/cn_data',
            dest='provider_uri',
            help='Qlib data path (default: ~/.qlib/qlib_data/cn_data)',
        )

    def handle(self, *args, **options):
        """执行命令"""
        download = options.get('download', False)
        check_only = options.get('check', False)
        universe = options.get('universe', 'csi300')
        days = options.get('days', 365)
        region = options.get('region', 'CN')
        provider_uri = options.get('provider_uri', '~/.qlib/qlib_data/cn_data')

        self.stdout.write(self.style.SUCCESS(f'Qlib 数据初始化'))
        self.stdout.write(f'  股票池: {universe}')
        self.stdout.write(f'  天数: {days}')
        self.stdout.write(f'  区域: {region}')
        self.stdout.write(f'  数据路径: {provider_uri}')

        # 检查 Qlib 是否安装
        if not self._check_qlib_installed():
            self.stdout.write(
                self.style.ERROR('Qlib 未安装！请运行: pip install pyqlib')
            )
            return

        # 检查数据目录
        data_path = Path(provider_uri).expanduser()

        if check_only:
            self._check_data_integrity(data_path, universe)
            return

        # 初始化数据
        if download:
            self._download_data(data_path, region)
        else:
            self.stdout.write('跳过数据下载（使用 --download 选项下载）')

        # 准备数据
        self._prepare_universe_data(data_path, universe, days)

        self.stdout.write(self.style.SUCCESS('Qlib 数据初始化完成'))

    def _check_qlib_installed(self) -> bool:
        """检查 Qlib 是否安装"""
        try:
            import qlib
            self.stdout.write(f'  Qlib 版本: {qlib.__version__}')
            return True
        except ImportError:
            return False

    def _check_data_integrity(self, data_path: Path, universe: str) -> bool:
        """检查数据完整性"""
        self.stdout.write('\n检查数据完整性...')

        if not data_path.exists():
            self.stdout.write(
                self.style.ERROR(f'  数据目录不存在: {data_path}')
            )
            return False

        self.stdout.write(self.style.SUCCESS(f'  ✓ 数据目录存在'))

        # 检查股票池数据
        try:
            import qlib
            from qlib.data import D

            qlib.init(provider_uri=str(data_path), region="cn")

            # 检查股票列表
            instruments = D.instruments(market=universe)
            if instruments:
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ {universe} 股票池: {len(instruments)} 只股票')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'  ⚠ {universe} 股票池为空')
                )

            # 检查最近数据
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)

            # 尝试获取一些数据
            try:
                df = D.features(
                    instruments[:10],  # 只检查前 10 只
                    fields=["$close"],
                    start_time=start_date,
                    end_time=end_date
                )
                if not df.empty:
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ 最近 7 天数据存在')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f'  ⚠ 最近 7 天数据为空')
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f'  ⚠ 无法检查最近数据: {e}')
                )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'  ✗ 检查失败: {e}')
            )
            return False

        return True

    def _download_data(self, data_path: Path, region: str):
        """下载 Qlib 数据"""
        self.stdout.write(f'\n下载 Qlib 数据到 {data_path}...')

        try:
            import qlib

            # 初始化并下载
            qlib.init(provider_uri=str(data_path), region=region.lower())

            self.stdout.write(
                self.style.SUCCESS('  ✓ 数据下载完成')
            )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'  ✗ 数据下载失败: {e}')
            )
            raise CommandError(f'数据下载失败: {e}')

    def _prepare_universe_data(self, data_path: Path, universe: str, days: int):
        """准备股票池数据"""
        self.stdout.write(f'\n准备 {universe} 数据...')

        try:
            import qlib
            from qlib.data import D
            from datetime import datetime, timedelta

            # 初始化 Qlib
            qlib.init(provider_uri=str(data_path), region="cn")

            # 获取股票列表
            instruments = D.instruments(market=universe)
            self.stdout.write(f'  股票池大小: {len(instruments)}')

            # 检查数据范围
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            # 尝试获取数据
            try:
                df = D.features(
                    instruments,
                    fields=["$close", "$volume", "$turnover"],
                    start_time=start_date,
                    end_time=end_date
                )

                if not df.empty:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✓ 数据准备完成: {len(df)} 条记录'
                        )
                    )
                    self.stdout.write(
                        f'    数据范围: {df.index.get_level_values("datetime").min()} '
                        f'到 {df.index.get_level_values("datetime").max()}'
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING('  ⚠ 没有获取到数据')
                    )

            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f'  ⚠ 数据获取失败: {e}')
                )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'  ✗ 数据准备失败: {e}')
            )
            raise CommandError(f'数据准备失败: {e}')


def _run_qlib_init_scripts(data_path: Path, region: str):
    """
    运行 Qlib 初始化脚本

    Args:
        data_path: 数据路径
        region: 区域
    """
    # 这里可以添加运行 Qlib 数据初始化脚本的逻辑
    # 例如运行 qlib 的数据获取脚本
    pass
