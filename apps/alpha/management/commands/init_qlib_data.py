"""Initialize and verify the configured local Qlib data runtime."""

from __future__ import annotations

import importlib
from datetime import timedelta
from pathlib import Path
from typing import Protocol, cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

from core.integration import runtime_settings


class _QlibIndexValuesProtocol(Protocol):
    """Index values used only for human-readable range output."""

    def min(self) -> object:
        """Return the minimum index value."""

    def max(self) -> object:
        """Return the maximum index value."""


class _QlibIndexProtocol(Protocol):
    """Minimal MultiIndex contract returned by Qlib feature frames."""

    def get_level_values(self, level: str) -> _QlibIndexValuesProtocol:
        """Return values for one named index level."""


class _QlibFrameProtocol(Protocol):
    """Minimal DataFrame contract consumed by this command."""

    @property
    def empty(self) -> bool:
        """Return whether the frame contains no rows."""

    @property
    def index(self) -> _QlibIndexProtocol:
        """Return the frame index."""

    def __len__(self) -> int:
        """Return the row count."""


class _QlibDataProtocol(Protocol):
    """Dynamic Qlib data API boundary used by integrity checks."""

    def features(
        self,
        instruments: list[str],
        *,
        fields: list[str],
        start_time: str,
        end_time: str,
    ) -> _QlibFrameProtocol:
        """Return feature rows for the requested instruments and window."""


class _QlibRuntimeProtocol(Protocol):
    """Dynamic Qlib module boundary."""

    __version__: object

    def init(self, *, provider_uri: str, region: str) -> object:
        """Initialize Qlib against one provider directory and region."""


class _QlibDownloaderProtocol(Protocol):
    """Qlib binary-data downloader boundary."""

    def qlib_data(
        self,
        *,
        target_dir: str,
        region: str,
        delete_old: bool,
        exists_skip: bool,
    ) -> object:
        """Download Qlib data into the target directory."""


class _QlibDownloaderFactoryProtocol(Protocol):
    """Callable downloader constructor from the optional Qlib package."""

    def __call__(self, *, delete_zip_file: bool) -> _QlibDownloaderProtocol:
        """Build a downloader."""


def _optional_nonempty_string(value: object, *, option_name: str) -> str | None:
    """Narrow an optional CLI value to a non-empty string."""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"{option_name} must be a non-empty string")
    return value.strip()


def _runtime_string(config: dict[str, object], *, key: str) -> str:
    """Read one required non-empty runtime configuration string."""

    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"runtime Qlib {key} must be a non-empty string")
    return value.strip()


def _boolean_option(value: object, *, option_name: str) -> bool:
    """Require a real boolean from the dynamic management-command boundary."""

    if not isinstance(value, bool):
        raise CommandError(f"{option_name} must be a boolean")
    return value


class Command(BaseCommand):
    """Initialize, download, prepare, or verify configured Qlib data."""

    help = "Initialize Qlib data for alpha signals"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register Qlib initialization command options."""

        parser.add_argument(
            "--download",
            action="store_true",
            dest="download",
            help="Download Qlib data if not present",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            dest="check",
            help="Check data integrity only",
        )
        parser.add_argument(
            "--universe",
            type=str,
            default=None,
            dest="universe",
            help="Universe to prepare (default: config-center runtime setting)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=365,
            dest="days",
            help="Positive number of calendar days to verify",
        )
        parser.add_argument(
            "--region",
            type=str,
            default=None,
            dest="region",
            help="Region configuration (default: config-center runtime setting)",
        )
        parser.add_argument(
            "--provider-uri",
            type=str,
            default=None,
            dest="provider_uri",
            help="Qlib data path (default: config-center runtime setting)",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Execute initialization and fail closed when data is not usable."""

        del args
        download = _boolean_option(options.get("download", False), option_name="download")
        check_only = _boolean_option(options.get("check", False), option_name="check")
        days_value = options.get("days", 365)
        if isinstance(days_value, bool) or not isinstance(days_value, int) or days_value <= 0:
            raise CommandError("days must be a positive integer")

        runtime_config = runtime_settings.get_runtime_qlib_config()
        universe = _optional_nonempty_string(
            options.get("universe"), option_name="universe"
        ) or _runtime_string(runtime_config, key="default_universe")
        region = _optional_nonempty_string(
            options.get("region"), option_name="region"
        ) or _runtime_string(runtime_config, key="region")
        provider_uri = _optional_nonempty_string(
            options.get("provider_uri"), option_name="provider_uri"
        ) or _runtime_string(runtime_config, key="provider_uri")

        self.stdout.write(self.style.SUCCESS("Qlib 数据初始化"))
        self.stdout.write(f"  股票池: {universe}")
        self.stdout.write(f"  天数: {days_value}")
        self.stdout.write(f"  区域: {region}")
        self.stdout.write(f"  数据路径: {provider_uri}")

        if not self._check_qlib_installed():
            message = "Qlib 未安装！请安装项目声明的 pyqlib 依赖"
            self.stdout.write(self.style.ERROR(message))
            raise CommandError(message)

        data_path = Path(provider_uri).expanduser()
        if check_only:
            if not self._check_data_integrity(data_path, universe, region):
                raise CommandError("Qlib 数据完整性检查失败")
            return

        if download:
            self._download_data(data_path, region)
        else:
            self.stdout.write("跳过数据下载（使用 --download 选项下载）")

        if not self._prepare_universe_data(data_path, universe, days_value, region):
            raise CommandError("Qlib 数据准备失败")
        self.stdout.write(self.style.SUCCESS("Qlib 数据初始化完成"))

    def _check_qlib_installed(self) -> bool:
        """Return whether the optional Qlib runtime can be imported."""

        try:
            qlib = cast(_QlibRuntimeProtocol, importlib.import_module("qlib"))
        except ImportError:
            return False
        self.stdout.write(f"  Qlib 版本: {qlib.__version__}")
        return True

    @staticmethod
    def _load_qlib_components() -> tuple[_QlibRuntimeProtocol, _QlibDataProtocol]:
        """Load typed Qlib runtime and data components at the third-party boundary."""

        qlib = cast(_QlibRuntimeProtocol, importlib.import_module("qlib"))
        data_module = importlib.import_module("qlib.data")
        data_provider: object = getattr(data_module, "D", None)
        if data_provider is None or not callable(getattr(data_provider, "features", None)):
            raise ImportError("qlib.data.D is unavailable")
        return qlib, cast(_QlibDataProtocol, data_provider)

    def _check_data_integrity(self, data_path: Path, universe: str, region: str) -> bool:
        """Verify directory, universe, calendar, and recent price data."""

        self.stdout.write("\n检查数据完整性...")
        if not data_path.exists() or not data_path.is_dir():
            self.stdout.write(self.style.ERROR(f"  数据目录不存在: {data_path}"))
            return False
        self.stdout.write(self.style.SUCCESS("  ✓ 数据目录存在"))

        try:
            qlib, data_provider = self._load_qlib_components()
            from apps.alpha.application.tasks import (
                _get_qlib_data_latest_date,
                _resolve_qlib_stock_list,
            )

            qlib.init(provider_uri=str(data_path), region=region.lower())
            stock_list = _resolve_qlib_stock_list(data_provider, universe_id=universe)
            if not stock_list:
                self.stdout.write(self.style.ERROR(f"  ✗ {universe} 股票池为空"))
                return False
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ {universe} 股票池: {len(stock_list)} 只股票")
            )

            latest_trade_date = _get_qlib_data_latest_date()
            if latest_trade_date is None:
                self.stdout.write(self.style.ERROR("  ✗ 本地交易日历为空"))
                return False
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ 本地最新交易日: {latest_trade_date.isoformat()}")
            )
            start_date = latest_trade_date - timedelta(days=7)
            frame = data_provider.features(
                stock_list[:10],
                fields=["$close"],
                start_time=start_date.isoformat(),
                end_time=latest_trade_date.isoformat(),
            )
            if frame.empty:
                self.stdout.write(self.style.ERROR("  ✗ 最近 7 个自然日窗口行情数据为空"))
                return False
            self.stdout.write(self.style.SUCCESS("  ✓ 最近 7 个自然日窗口存在行情数据"))
            return True
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  ✗ 检查失败: {type(exc).__name__}"))
            return False

    def _download_data(self, data_path: Path, region: str) -> None:
        """Download Qlib binary data through the optional downloader package."""

        self.stdout.write(f"\n下载 Qlib 数据到 {data_path}...")
        try:
            data_module = importlib.import_module("qlib.tests.data")
            downloader_factory: object = getattr(data_module, "GetData", None)
            if not callable(downloader_factory):
                raise ImportError("qlib.tests.data.GetData is unavailable")
            data_path.mkdir(parents=True, exist_ok=True)
            downloader = cast(_QlibDownloaderFactoryProtocol, downloader_factory)(
                delete_zip_file=True
            )
            downloader.qlib_data(
                target_dir=str(data_path),
                region=region.lower(),
                delete_old=False,
                exists_skip=False,
            )
            self.stdout.write(self.style.SUCCESS("  ✓ 数据下载完成"))
        except Exception as exc:
            error_type = type(exc).__name__
            self.stdout.write(self.style.ERROR(f"  ✗ 数据下载失败: {error_type}"))
            raise CommandError(f"数据下载失败: {error_type}") from exc

    def _prepare_universe_data(
        self,
        data_path: Path,
        universe: str,
        days: int,
        region: str,
    ) -> bool:
        """Verify that the configured universe has usable local feature rows."""

        self.stdout.write(f"\n准备 {universe} 数据...")
        try:
            qlib, data_provider = self._load_qlib_components()
            from apps.alpha.application.tasks import (
                _get_qlib_data_latest_date,
                _resolve_qlib_stock_list,
            )

            qlib.init(provider_uri=str(data_path), region=region.lower())
            stock_list = _resolve_qlib_stock_list(data_provider, universe_id=universe)
            self.stdout.write(f"  股票池大小: {len(stock_list)}")
            if not stock_list:
                self.stdout.write(self.style.ERROR("  ✗ 股票池为空"))
                return False

            latest_trade_date = _get_qlib_data_latest_date()
            if latest_trade_date is None:
                self.stdout.write(self.style.ERROR("  ✗ 本地交易日历为空"))
                return False
            start_date = latest_trade_date - timedelta(days=days)
            frame = data_provider.features(
                stock_list,
                fields=["$close", "$volume", "$turnover"],
                start_time=start_date.isoformat(),
                end_time=latest_trade_date.isoformat(),
            )
            if frame.empty:
                self.stdout.write(self.style.ERROR("  ✗ 没有获取到数据"))
                return False

            self.stdout.write(self.style.SUCCESS(f"  ✓ 数据准备完成: {len(frame)} 条记录"))
            self.stdout.write(
                "    数据范围: "
                f'{frame.index.get_level_values("datetime").min()} '
                f'到 {frame.index.get_level_values("datetime").max()}'
            )
            return True
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  ✗ 数据准备失败: {type(exc).__name__}"))
            return False
