"""Deterministic command contracts for Alpha cold-start and Qlib operations."""

from __future__ import annotations

from datetime import date
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError

from apps.alpha.management.commands import (
    bootstrap_alpha_cold_start,
    build_qlib_data,
    init_qlib_data,
)


class _CacheManager:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or set()
        self.current = ""
        self.saved: list[str] = []

    def filter(self, **kwargs: object) -> _CacheManager:
        self.current = str(kwargs.get("universe_id", ""))
        return self

    def exists(self) -> bool:
        return self.current in self.existing

    def update_or_create(self, **kwargs: object) -> tuple[object, bool]:
        universe = str(kwargs["universe_id"])
        self.saved.append(universe)
        return object(), universe != "updated"


def _bootstrap_options(**overrides: object) -> dict[str, object]:
    options: dict[str, object] = {
        "trade_date": "2026-07-24",
        "universes": "existing,success,empty,error,updated",
        "top_n": 10,
        "overwrite": False,
    }
    options.update(overrides)
    return options


def test_alpha_cold_start_handles_model_and_prediction_boundaries(monkeypatch) -> None:
    """Cold start distinguishes unavailable model, cache, empty, failure, and upsert paths."""
    command = bootstrap_alpha_cold_start.Command(stdout=StringIO())
    model_manager = SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(first=lambda: None))
    monkeypatch.setattr(
        bootstrap_alpha_cold_start,
        "QlibModelRegistryModel",
        SimpleNamespace(_default_manager=model_manager),
    )
    command.handle(**_bootstrap_options())
    assert "no active Qlib model" in command.stdout.getvalue()

    active = SimpleNamespace(
        model_path="",
        artifact_hash="hash",
        model_name="model",
        feature_set_id="features",
        label_id="label",
        data_version="v1",
    )
    model_manager.filter = lambda **kwargs: SimpleNamespace(first=lambda: active)
    command = bootstrap_alpha_cold_start.Command(stdout=StringIO())
    command.handle(**_bootstrap_options())
    assert "no model_path" in command.stdout.getvalue()

    active.model_path = "/model.pkl"
    cache_manager = _CacheManager(existing={"existing"})
    monkeypatch.setattr(
        bootstrap_alpha_cold_start,
        "AlphaScoreCacheModel",
        SimpleNamespace(
            _default_manager=cache_manager,
            PROVIDER_QLIB="qlib",
            STATUS_AVAILABLE="available",
        ),
    )

    def _predict(**kwargs: object) -> list[dict[str, object]]:
        universe = str(kwargs["universe_id"])
        if universe == "error":
            raise RuntimeError("offline")
        if universe == "empty":
            return []
        return [{"code": "000001.SZ", "score": 0.9}]

    monkeypatch.setattr(bootstrap_alpha_cold_start, "_execute_qlib_prediction", _predict)
    command = bootstrap_alpha_cold_start.Command(stdout=StringIO())
    command.handle(**_bootstrap_options())
    assert cache_manager.saved == ["success", "updated"]
    output = command.stdout.getvalue()
    assert "applied=2, skipped=3" in output
    assert "empty qlib result" in output
    assert "offline" in output


def test_build_qlib_data_helpers_and_command_modes(monkeypatch) -> None:
    """Build command reports actionable blockers and delegates a normalized build request."""
    target = date(2026, 7, 24)
    assert (
        build_qlib_data._build_qlib_blocker_message(
            date(2026, 7, 22), target_date=target, has_tushare_token=False
        )
        is None
    )
    assert "目录为空" in build_qlib_data._build_qlib_blocker_message(
        None, target_date=target, has_tushare_token=False
    )
    assert "可直接运行" in build_qlib_data._build_qlib_blocker_message(
        date(2026, 1, 1), target_date=target, has_tushare_token=True
    )

    monkeypatch.setattr(build_qlib_data, "get_runtime_qlib_config", lambda: {})
    monkeypatch.setattr(build_qlib_data, "_resolve_tushare_token", lambda: None)
    monkeypatch.setattr(build_qlib_data, "_inspect_latest_trade_date", lambda *args: None)
    options = {
        "provider_uri": "/qlib",
        "region": "CN",
        "target_date": "2026-07-24",
        "max_staleness_days": 5,
        "check_only": True,
        "universes": "csi300",
        "lookback_days": 100,
    }
    with pytest.raises(CommandError, match="目录为空"):
        build_qlib_data.Command(stdout=StringIO()).handle(**options)

    monkeypatch.setattr(build_qlib_data, "_resolve_tushare_token", lambda: "token")
    monkeypatch.setattr(
        build_qlib_data,
        "_inspect_latest_trade_date",
        lambda *args: date(2026, 7, 23),
    )
    check_command = build_qlib_data.Command(stdout=StringIO())
    check_command.handle(**options)
    assert "无需自建更新" in check_command.stdout.getvalue()

    summary = SimpleNamespace(
        latest_local_date_before=date(2026, 7, 20),
        latest_local_date_after=date(2026, 7, 24),
        effective_target_date=date(2026, 7, 24),
        calendar_days_written=4,
        instrument_files_written=2,
        feature_series_written=12,
        stock_count=300,
        warning_messages=["partial"],
    )
    calls: list[dict[str, object]] = []

    class _Builder:
        def __init__(self, provider_uri: str) -> None:
            self.provider_uri = provider_uri

        def build_recent_data(self, **kwargs: object):
            calls.append(kwargs)
            return summary

    monkeypatch.setattr(build_qlib_data, "TushareQlibBuilder", _Builder)
    build_options = dict(options)
    build_options.update(check_only=False, universes=" CSI300, SSE50 ")
    build_command = build_qlib_data.Command(stdout=StringIO())
    build_command.handle(**build_options)
    assert calls[0]["universes"] == ["csi300", "sse50"]
    assert "warning: partial" in build_command.stdout.getvalue()
    with pytest.raises(CommandError, match="至少需要"):
        build_command.handle(**(build_options | {"universes": " , "}))


def test_init_qlib_data_orchestration_and_integrity_boundaries(monkeypatch, tmp_path) -> None:
    """Legacy initializer checks installation, integrity, download, and preparation explicitly."""
    command = init_qlib_data.Command(stdout=StringIO())
    monkeypatch.setattr(
        "core.integration.runtime_settings.get_runtime_qlib_config",
        lambda: {
            "region": "CN",
            "provider_uri": str(tmp_path),
            "default_universe": "csi500",
        },
    )
    monkeypatch.setattr(command, "_check_qlib_installed", lambda: False)
    with pytest.raises(CommandError, match="Qlib 未安装"):
        command.handle(
            download=False,
            check=False,
            universe=None,
            days=30,
            region=None,
            provider_uri=None,
        )
    assert "Qlib 未安装" in command.stdout.getvalue()

    events: list[str] = []
    command = init_qlib_data.Command(stdout=StringIO())
    monkeypatch.setattr(command, "_check_qlib_installed", lambda: True)
    monkeypatch.setattr(
        command,
        "_download_data",
        lambda path, region: events.append(f"download:{region}"),
    )
    monkeypatch.setattr(
        command,
        "_prepare_universe_data",
        lambda path, universe, days, region: events.append(f"prepare:{universe}:{days}:{region}")
        or True,
    )
    command.handle(
        download=True,
        check=False,
        universe="csi500",
        days=20,
        region="CN",
        provider_uri=str(tmp_path),
    )
    assert events == ["download:CN", "prepare:csi500:20:CN"]
    assert "初始化完成" in command.stdout.getvalue()

    missing = init_qlib_data.Command(stdout=StringIO())
    assert missing._check_data_integrity(tmp_path / "missing", "csi300", "CN") is False

    command = init_qlib_data.Command(stdout=StringIO())
    monkeypatch.setattr(command, "_check_qlib_installed", lambda: True)
    monkeypatch.setattr(
        command,
        "_check_data_integrity",
        lambda path, universe, region: events.append(f"check:{universe}:{region}") or True,
    )
    command.handle(
        download=False,
        check=True,
        universe="sse50",
        days=10,
        region="CN",
        provider_uri=str(tmp_path),
    )
    assert events[-1] == "check:sse50:CN"

    command = init_qlib_data.Command(stdout=StringIO())
    monkeypatch.setattr(command, "_check_qlib_installed", lambda: True)
    monkeypatch.setattr(
        command,
        "_prepare_universe_data",
        lambda path, universe, days, region: events.append(f"runtime-default:{universe}:{region}")
        or True,
    )
    command.handle(
        download=False,
        check=False,
        universe=None,
        days=10,
        region=None,
        provider_uri=None,
    )
    assert events[-1] == "runtime-default:csi500:CN"

    for invalid_days in (0, -1, True, "30"):
        with pytest.raises(CommandError, match="days"):
            command.handle(
                download=False,
                check=False,
                universe="csi300",
                days=invalid_days,
                region="CN",
                provider_uri=str(tmp_path),
            )

    monkeypatch.setattr(
        "core.integration.runtime_settings.get_runtime_qlib_config",
        lambda: {"region": "CN", "provider_uri": {"unsafe": "path"}, "default_universe": "csi300"},
    )
    with pytest.raises(CommandError, match="provider_uri"):
        command.handle(
            download=False,
            check=False,
            universe=None,
            days=10,
            region=None,
            provider_uri=None,
        )

    monkeypatch.setattr(
        "core.integration.runtime_settings.get_runtime_qlib_config",
        lambda: {
            "region": "CN",
            "provider_uri": str(tmp_path),
            "default_universe": "csi300",
        },
    )
    failing_check = init_qlib_data.Command(stdout=StringIO())
    monkeypatch.setattr(failing_check, "_check_qlib_installed", lambda: True)
    monkeypatch.setattr(failing_check, "_check_data_integrity", lambda *_args: False)
    with pytest.raises(CommandError, match="完整性检查失败"):
        failing_check.handle(
            download=False,
            check=True,
            universe=None,
            days=10,
            region=None,
            provider_uri=None,
        )

    failing_prepare = init_qlib_data.Command(stdout=StringIO())
    monkeypatch.setattr(failing_prepare, "_check_qlib_installed", lambda: True)
    monkeypatch.setattr(failing_prepare, "_prepare_universe_data", lambda *_args: False)
    with pytest.raises(CommandError, match="数据准备失败"):
        failing_prepare.handle(
            download=False,
            check=False,
            universe=None,
            days=10,
            region=None,
            provider_uri=None,
        )
    assert "初始化完成" not in failing_prepare.stdout.getvalue()


def test_init_qlib_data_propagates_region_and_rejects_empty_features(
    monkeypatch,
    tmp_path,
) -> None:
    """Integrity and preparation use the requested region and fail on empty feature frames."""

    class _IndexValues:
        def min(self) -> str:
            return "2026-07-20"

        def max(self) -> str:
            return "2026-07-24"

    class _Index:
        def get_level_values(self, level: str) -> _IndexValues:
            assert level == "datetime"
            return _IndexValues()

    class _Frame:
        def __init__(self, *, empty: bool) -> None:
            self.empty = empty
            self.index = _Index()

        def __len__(self) -> int:
            return 0 if self.empty else 5

    class _Data:
        def __init__(self) -> None:
            self.empty = False

        def features(self, *_args: object, **_kwargs: object) -> _Frame:
            return _Frame(empty=self.empty)

    class _Runtime:
        __version__ = "test"

        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def init(self, **kwargs: str) -> None:
            self.calls.append(kwargs)

    runtime = _Runtime()
    data = _Data()
    command = init_qlib_data.Command(stdout=StringIO())
    monkeypatch.setattr(command, "_load_qlib_components", lambda: (runtime, data))
    monkeypatch.setattr(
        "apps.alpha.application.tasks._resolve_qlib_stock_list",
        lambda *_args, **_kwargs: ["000001.SZ"],
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._get_qlib_data_latest_date",
        lambda: date(2026, 7, 24),
    )

    assert command._check_data_integrity(tmp_path, "csi300", "US") is True
    assert runtime.calls[-1]["region"] == "us"

    data.empty = True
    assert command._prepare_universe_data(tmp_path, "csi300", 30, "US") is False
    assert runtime.calls[-1]["region"] == "us"
