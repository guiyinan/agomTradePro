"""
Initialize Qlib Data Management Command

初始化 Qlib 数据的 Django 管理命令。
"""

import logging
from datetime import timedelta
from pathlib import Path

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
            default=None,
            dest='region',
            help='Region configuration (default: runtime setting)',
        )
        parser.add_argument(
            '--provider-uri',
            type=str,
            default=None,
            dest='provider_uri',
            help='Qlib data path (default: runtime setting)',
        )

    def handle(self, *args, **options):
        """执行命令"""
        download = options.get('download', False)
        check_only = options.get('check', False)
        universe = options.get('universe', 'csi300')
        days = options.get('days', 365)
        region = options.get('region')
        provider_uri = options.get('provider_uri')

        from core.integration.runtime_settings import get_runtime_qlib_config

        runtime_config = get_runtime_qlib_config()
        region = region or runtime_config.get('region', 'CN')
        provider_uri = provider_uri or runtime_config.get(
            'provider_uri',
            '~/.qlib/qlib_data/cn_data',
        )

        self.stdout.write(self.style.SUCCESS('Qlib 数据初始化'))
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

        self.stdout.write(self.style.SUCCESS('  ✓ 数据目录存在'))

        # 检查股票池数据
        try:
            import qlib
            from qlib.data import D

            from apps.alpha.application.tasks import (
                _get_qlib_data_latest_date,
                _resolve_qlib_stock_list,
            )

            qlib.init(provider_uri=str(data_path), region="cn")

            stock_list = _resolve_qlib_stock_list(D, universe_id=universe)
            self.stdout.write(
                self.style.SUCCESS(f'  ✓ {universe} 股票池: {len(stock_list)} 只股票')
            )

            latest_trade_date = _get_qlib_data_latest_date()
            if latest_trade_date is not None:
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ 本地最新交易日: {latest_trade_date.isoformat()}')
                )
            else:
                self.stdout.write(self.style.WARNING('  ⚠ 本地交易日历为空'))

            # 基于本地最新交易日检查最近窗口，避免误用系统当前日期导致全空。
            end_date = latest_trade_date or timezone.now().date()
            start_date = end_date - timedelta(days=7)

            try:
                df = D.features(
                    stock_list[:10],
                    fields=["$close"],
                    start_time=start_date.isoformat(),
                    end_time=end_date.isoformat(),
                )
                if not df.empty:
                    self.stdout.write(
                        self.style.SUCCESS('  ✓ 最近 7 个自然日窗口存在行情数据')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING('  ⚠ 最近 7 个自然日窗口行情数据为空')
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
            from qlib.tests.data import GetData

            data_path.mkdir(parents=True, exist_ok=True)
            downloader = GetData(delete_zip_file=True)
            downloader.qlib_data(
                target_dir=str(data_path),
                region=region.lower(),
                delete_old=False,
                exists_skip=False,
            )

            self.stdout.write(
                self.style.SUCCESS('  ✓ 数据下载完成')
            )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'  ✗ 数据下载失败: {e}')
            )
            raise CommandError(f'数据下载失败: {e}') from e

    def _prepare_universe_data(self, data_path: Path, universe: str, days: int):
        """准备股票池数据"""
        self.stdout.write(f'\n准备 {universe} 数据...')

        try:
            import qlib
            from qlib.data import D

            from apps.alpha.application.tasks import (
                _get_qlib_data_latest_date,
                _resolve_qlib_stock_list,
            )

            # 初始化 Qlib
            qlib.init(provider_uri=str(data_path), region="cn")

            stock_list = _resolve_qlib_stock_list(D, universe_id=universe)
            self.stdout.write(f'  股票池大小: {len(stock_list)}')

            # 检查数据范围
            latest_trade_date = _get_qlib_data_latest_date()
            end_date = latest_trade_date or timezone.now().date()
            start_date = end_date - timedelta(days=days)

            # 尝试获取数据
            try:
                df = D.features(
                    stock_list,
                    fields=["$close", "$volume", "$turnover"],
                    start_time=start_date.isoformat(),
                    end_time=end_date.isoformat(),
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
            raise CommandError(f'数据准备失败: {e}') from e


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
