from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from apps.account.infrastructure.models import SystemSettingsModel
from apps.alpha.infrastructure.qlib_builder import (
    TushareQlibBuilder,
    inspect_latest_trade_date,
)


def _build_qlib_blocker_message(
    latest_trade_date: date | None,
    *,
    target_date: date,
    has_tushare_token: bool,
    max_staleness_days: int = 10,
) -> str | None:
    """Return a user-facing blocker when local/public qlib data is still stale."""
    if latest_trade_date is not None and target_date <= latest_trade_date + timedelta(days=max_staleness_days):
        return None

    if latest_trade_date is None:
        base_reason = "本地 Qlib 数据目录为空。"
    else:
        base_reason = (
            f"本地或公开 Qlib 数据最新交易日为 {latest_trade_date.isoformat()}，"
            f"早于目标日期 {target_date.isoformat()}。"
        )

    if has_tushare_token:
        return (
            f"{base_reason} 已检测到 Tushare Token，可直接运行 "
            "`python manage.py build_qlib_data` 执行最近窗口自建更新。"
        )

    return (
        f"{base_reason} 当前未配置 Tushare Token，无法执行自建更新。"
        "请先在 Django Admin 数据源配置或环境变量 TUSHARE_TOKEN 中提供凭据。"
    )


def _resolve_tushare_token() -> str | None:
    try:
        from shared.config.secrets import get_tushare_token

        token = get_tushare_token()
    except Exception:
        return None
    return token or None


def _inspect_latest_trade_date(provider_uri: str, region: str) -> date | None:
    return inspect_latest_trade_date(provider_uri)


class Command(BaseCommand):
    help = "Diagnose or build recent qlib runtime data from Tushare"

    def add_arguments(self, parser):
        parser.add_argument(
            "--check-only",
            action="store_true",
            dest="check_only",
            help="Only inspect qlib data freshness and prerequisites.",
        )
        parser.add_argument(
            "--provider-uri",
            type=str,
            default=None,
            dest="provider_uri",
            help="Override qlib provider_uri; defaults to runtime setting.",
        )
        parser.add_argument(
            "--region",
            type=str,
            default=None,
            dest="region",
            help="Override qlib region; defaults to runtime setting.",
        )
        parser.add_argument(
            "--target-date",
            type=str,
            default=None,
            dest="target_date",
            help="Expected latest trade date; defaults to today.",
        )
        parser.add_argument(
            "--max-staleness-days",
            type=int,
            default=10,
            dest="max_staleness_days",
            help="Allowed staleness window before data is considered blocked.",
        )
        parser.add_argument(
            "--universes",
            type=str,
            default="csi300,csi500,sse50,csi1000",
            dest="universes",
            help="Comma-separated qlib universes to refresh.",
        )
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=400,
            dest="lookback_days",
            help="Recent lookback window to rebuild for active universes.",
        )

    def handle(self, *args, **options):
        runtime_config = SystemSettingsModel.get_runtime_qlib_config()
        provider_uri = options["provider_uri"] or runtime_config.get(
            "provider_uri",
            "~/.qlib/qlib_data/cn_data",
        )
        region = (options["region"] or runtime_config.get("region", "CN")).lower()
        target_date = (
            date.fromisoformat(options["target_date"])
            if options.get("target_date")
            else date.today()
        )
        max_staleness_days = int(options["max_staleness_days"])
        has_tushare_token = _resolve_tushare_token() is not None

        self.stdout.write(self.style.SUCCESS("Qlib 自建诊断"))
        self.stdout.write(f"  provider_uri: {provider_uri}")
        self.stdout.write(f"  region: {region}")
        self.stdout.write(f"  target_date: {target_date.isoformat()}")
        self.stdout.write(f"  tushare_token: {'configured' if has_tushare_token else 'missing'}")

        latest_trade_date = _inspect_latest_trade_date(provider_uri, region)
        self.stdout.write(
            f"  latest_trade_date: {latest_trade_date.isoformat() if latest_trade_date else 'None'}"
        )

        blocker = _build_qlib_blocker_message(
            latest_trade_date,
            target_date=target_date,
            has_tushare_token=has_tushare_token,
            max_staleness_days=max_staleness_days,
        )
        if options["check_only"]:
            if blocker:
                raise CommandError(blocker)
            self.stdout.write(self.style.SUCCESS("Qlib 数据新鲜度满足要求，无需自建更新。"))
            return

        if blocker and not has_tushare_token:
            raise CommandError(blocker)

        universes = [
            item.strip().lower()
            for item in str(options["universes"]).split(",")
            if item.strip()
        ]
        lookback_days = int(options["lookback_days"])
        if not universes:
            raise CommandError("至少需要一个 universe")

        builder = TushareQlibBuilder(provider_uri)
        summary = builder.build_recent_data(
            target_date=target_date,
            universes=universes,
            lookback_days=lookback_days,
        )

        self.stdout.write(self.style.SUCCESS("Qlib 自建完成"))
        self.stdout.write(f"  universes: {', '.join(universes)}")
        self.stdout.write(f"  latest_before: {summary.latest_local_date_before}")
        self.stdout.write(f"  latest_after: {summary.latest_local_date_after}")
        self.stdout.write(
            f"  effective_target_date: "
            f"{summary.effective_target_date.isoformat() if summary.effective_target_date else 'None'}"
        )
        self.stdout.write(f"  calendar_days_written: {summary.calendar_days_written}")
        self.stdout.write(f"  instrument_files_written: {summary.instrument_files_written}")
        self.stdout.write(f"  feature_series_written: {summary.feature_series_written}")
        self.stdout.write(f"  stock_count: {summary.stock_count}")

        if summary.warning_messages:
            for warning in summary.warning_messages:
                self.stdout.write(self.style.WARNING(f"  warning: {warning}"))
