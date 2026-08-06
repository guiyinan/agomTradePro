from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.alpha.infrastructure.qlib_builder import (
    TushareQlibBuilder,
    inspect_latest_trade_date,
)
from core.integration.runtime_settings import get_runtime_qlib_config

_DEFAULT_PROVIDER_URI = "~/.qlib/qlib_data/cn_data"
_DEFAULT_REGION = "cn"
_DEFAULT_UNIVERSES = "csi300,csi500,sse50,csi1000"
_UNIVERSE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_REGION_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,15}$")


@dataclass(frozen=True)
class _BuildQlibOptions:
    """Validated command inputs safe to pass into Qlib filesystem/data I/O."""

    check_only: bool
    provider_uri: str
    region: str
    target_date: date
    max_staleness_days: int
    universes: tuple[str, ...]
    lookback_days: int


def _build_qlib_blocker_message(
    latest_trade_date: date | None,
    *,
    target_date: date,
    has_tushare_token: bool,
    max_staleness_days: int = 5,
) -> str | None:
    """Return a user-facing blocker when local/public qlib data is still stale."""
    if latest_trade_date is not None and target_date <= latest_trade_date + timedelta(
        days=max_staleness_days
    ):
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
    if not isinstance(token, str):
        return None
    normalized = token.strip()
    return normalized or None


def _inspect_latest_trade_date(provider_uri: str, region: str) -> date | None:
    return inspect_latest_trade_date(provider_uri)


def _parse_command_options(
    raw_options: Mapping[str, object],
    runtime_config: Mapping[str, object],
) -> _BuildQlibOptions:
    """Validate every dynamic command/config value before external or filesystem I/O."""

    provider_override = raw_options.get("provider_uri")
    if provider_override is None and "provider_uri" in runtime_config:
        # Validate a malformed runtime value before the fail-closed status
        # check so callers receive the stable input-boundary error.
        _bounded_option_text(
            runtime_config.get("provider_uri"),
            label="provider_uri",
            max_length=4_096,
        )
    if provider_override is None and (
        runtime_config.get("enabled") is not True
        or runtime_config.get("must_not_use_for_decision", False)
    ):
        raise CommandError(
            str(runtime_config.get("blocked_reason") or "runtime_config_snapshot_unavailable")
        )
    provider_uri = _bounded_option_text(
        (
            provider_override
            if provider_override is not None
            else runtime_config.get("provider_uri")
        ),
        label="provider_uri",
        max_length=4_096,
    )

    region_override = raw_options.get("region")
    region = _bounded_option_text(
        (
            region_override
            if region_override is not None
            else runtime_config.get("region", _DEFAULT_REGION)
        ),
        label="region",
        max_length=16,
    ).lower()
    if _REGION_PATTERN.fullmatch(region) is None:
        raise CommandError("region 必须是 1-16 位小写字母、数字、下划线或连字符")

    raw_target_date = raw_options.get("target_date")
    if raw_target_date is None:
        target_date = date.today()
    elif isinstance(raw_target_date, str):
        try:
            target_date = date.fromisoformat(raw_target_date)
        except ValueError as exc:
            raise CommandError("target_date 必须是 YYYY-MM-DD 格式的有效日期") from exc
    else:
        raise CommandError("target_date 必须是 YYYY-MM-DD 格式的有效日期")

    max_staleness_days = _bounded_int_option(
        raw_options.get("max_staleness_days", 5),
        label="max_staleness_days",
        minimum=0,
        maximum=365,
    )
    lookback_days = _bounded_int_option(
        raw_options.get("lookback_days", 400),
        label="lookback_days",
        minimum=1,
        maximum=2_000,
    )

    raw_check_only = raw_options.get("check_only", False)
    if not isinstance(raw_check_only, bool):
        raise CommandError("check_only 必须是布尔值")

    raw_universes = raw_options.get("universes", _DEFAULT_UNIVERSES)
    if not isinstance(raw_universes, str):
        raise CommandError("universes 必须是逗号分隔字符串")
    universes: list[str] = []
    for item in raw_universes.split(","):
        normalized = item.strip().lower()
        if not normalized:
            continue
        if _UNIVERSE_PATTERN.fullmatch(normalized) is None:
            raise CommandError("universe 必须是 1-64 位小写字母、数字、下划线或连字符")
        if normalized not in universes:
            universes.append(normalized)
    if not universes:
        raise CommandError("至少需要一个 universe")
    if len(universes) > 32:
        raise CommandError("universes 最多允许 32 个")

    return _BuildQlibOptions(
        check_only=raw_check_only,
        provider_uri=provider_uri,
        region=region,
        target_date=target_date,
        max_staleness_days=max_staleness_days,
        universes=tuple(universes),
        lookback_days=lookback_days,
    )


def _bounded_option_text(raw_value: object, *, label: str, max_length: int) -> str:
    """Return one bounded control-character-free command/config string."""

    if not isinstance(raw_value, str):
        raise CommandError(f"{label} 必须是字符串")
    value = raw_value.strip()
    if not value or len(value) > max_length:
        raise CommandError(f"{label} 必须为 1-{max_length} 个字符")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CommandError(f"{label} 不能包含控制字符")
    return value


def _bounded_int_option(
    raw_value: object,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    """Return a strict bounded integer without accepting bool or numeric strings."""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise CommandError(f"{label} 必须是整数")
    if not minimum <= raw_value <= maximum:
        raise CommandError(f"{label} 必须位于 {minimum}-{maximum} 范围内")
    return raw_value


class Command(BaseCommand):
    help = "Diagnose or build recent qlib runtime data from Tushare"

    def add_arguments(self, parser: CommandParser) -> None:
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
            default=5,
            dest="max_staleness_days",
            help="Allowed staleness window before data is considered blocked.",
        )
        parser.add_argument(
            "--universes",
            type=str,
            default=_DEFAULT_UNIVERSES,
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

    def handle(self, *args: object, **options: object) -> None:
        runtime_config = get_runtime_qlib_config()
        command_options = _parse_command_options(options, runtime_config)
        has_tushare_token = _resolve_tushare_token() is not None

        self.stdout.write(self.style.SUCCESS("Qlib 自建诊断"))
        self.stdout.write(f"  provider_uri: {command_options.provider_uri}")
        self.stdout.write(f"  region: {command_options.region}")
        self.stdout.write(f"  target_date: {command_options.target_date.isoformat()}")
        self.stdout.write(f"  tushare_token: {'configured' if has_tushare_token else 'missing'}")

        latest_trade_date = _inspect_latest_trade_date(
            command_options.provider_uri,
            command_options.region,
        )
        self.stdout.write(
            f"  latest_trade_date: {latest_trade_date.isoformat() if latest_trade_date else 'None'}"
        )

        blocker = _build_qlib_blocker_message(
            latest_trade_date,
            target_date=command_options.target_date,
            has_tushare_token=has_tushare_token,
            max_staleness_days=command_options.max_staleness_days,
        )
        if command_options.check_only:
            if blocker:
                raise CommandError(blocker)
            self.stdout.write(self.style.SUCCESS("Qlib 数据新鲜度满足要求，无需自建更新。"))
            return

        if blocker and not has_tushare_token:
            raise CommandError(blocker)

        builder = TushareQlibBuilder(command_options.provider_uri)
        summary = builder.build_recent_data(
            target_date=command_options.target_date,
            universes=list(command_options.universes),
            lookback_days=command_options.lookback_days,
        )

        self.stdout.write(self.style.SUCCESS("Qlib 自建完成"))
        self.stdout.write(f"  universes: {', '.join(command_options.universes)}")
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
