"""Runtime connectivity probes for configurable macro datasources."""

from __future__ import annotations

import queue
import threading
from datetime import date, timedelta
from typing import Any

from apps.macro.infrastructure.models import DataSourceConfig

_TEST_TIMEOUT_SECONDS = 15


def _log(logs: list[str], message: str) -> None:
    logs.append(message)


def _build_result(
    *,
    success: bool,
    summary: str,
    logs: list[str],
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "success": success,
        "status": status or ("success" if success else "error"),
        "summary": summary,
        "logs": logs,
    }


def _run_probe_with_timeout(
    *,
    config: DataSourceConfig,
    logs: list[str],
    probe,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Run a potentially blocking probe with a hard timeout."""
    timeout_seconds = timeout_seconds or _TEST_TIMEOUT_SECONDS
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    probe_logs: list[str] = []

    def _worker() -> None:
        try:
            result_queue.put(("result", probe(config, probe_logs)))
        except Exception as exc:  # pragma: no cover - defensive wrapper
            result_queue.put(("error", exc))

    thread = threading.Thread(
        target=_worker,
        name=f"datasource-test-{config.source_type}",
        daemon=True,
    )
    thread.start()

    try:
        status, payload = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        logs.extend(probe_logs)
        _log(
            logs,
            f"[ERROR] 连接测试超时：{timeout_seconds} 秒内未收到 {config.source_type} 探针返回。",
        )
        return _build_result(
            success=False,
            summary=f"连接测试超时（>{timeout_seconds} 秒）",
            logs=logs,
        )

    logs.extend(probe_logs)
    if status == "error":
        raise payload
    return payload


def _test_tushare(config: DataSourceConfig, logs: list[str]) -> dict[str, Any]:
    from apps.macro.infrastructure.adapters.tushare_adapter import TushareAdapter

    token = (config.api_key or "").strip()
    http_url = (config.http_url or "").strip() or None
    if not token:
        _log(logs, "[ERROR] 未配置 Tushare Token，无法发起连接测试。")
        return _build_result(
            success=False,
            summary="未配置 Tushare Token",
            logs=logs,
        )

    _log(logs, "[INFO] 检测到 Tushare Token，开始初始化客户端。")
    if http_url:
        _log(logs, f"[INFO] 将使用自定义 HTTP URL: {http_url}")

    adapter = TushareAdapter(token=token, http_url=http_url)
    probe_end = date.today()
    probe_start = probe_end - timedelta(days=7)
    _log(logs, f"[INFO] 使用 SHIBOR 探针窗口: {probe_start} -> {probe_end}")

    frame = adapter.pro.shibor(
        start_date=probe_start.strftime("%Y%m%d"),
        end_date=probe_end.strftime("%Y%m%d"),
    )
    row_count = 0 if frame is None else len(frame.index)
    _log(logs, f"[SUCCESS] Tushare API 调用成功，返回 {row_count} 行。")
    return _build_result(
        success=True,
        summary=f"Tushare 连接正常，SHIBOR 探针返回 {row_count} 行",
        logs=logs,
    )


def _test_akshare(config: DataSourceConfig, logs: list[str]) -> dict[str, Any]:
    from apps.macro.infrastructure.adapters.akshare_adapter import AKShareAdapter

    _log(logs, "[INFO] AKShare 为公开数据源，无需 Token。")
    adapter = AKShareAdapter()
    probe_end = date.today()
    probe_start = probe_end - timedelta(days=400)
    _log(logs, f"[INFO] 使用 CN_PMI 探针窗口: {probe_start} -> {probe_end}")
    data = adapter.fetch("CN_PMI", probe_start, probe_end)
    _log(logs, f"[SUCCESS] AKShare 探针成功，返回 {len(data)} 条记录。")
    return _build_result(
        success=True,
        summary=f"AKShare 连接正常，PMI 探针返回 {len(data)} 条记录",
        logs=logs,
    )


def _test_qmt(config: DataSourceConfig, logs: list[str]) -> dict[str, Any]:
    from apps.market_data.infrastructure.gateways.qmt_gateway import QMTGateway

    extra_config = config.extra_config or {}
    _log(logs, "[INFO] 开始初始化 QMT / XtQuant 网关。")
    if extra_config.get("client_path"):
        _log(logs, f"[INFO] client_path={extra_config['client_path']}")
    if extra_config.get("data_dir"):
        _log(logs, f"[INFO] data_dir={extra_config['data_dir']}")

    gateway = QMTGateway(source_name=config.name, extra_config=extra_config)
    gateway._load_xtdata()
    _log(logs, "[SUCCESS] QMT 本地终端连接成功。")
    return _build_result(
        success=True,
        summary="QMT 本地终端连接成功",
        logs=logs,
    )


def _test_credential_only(config: DataSourceConfig, logs: list[str]) -> dict[str, Any]:
    api_key = (config.api_key or "").strip()
    if not api_key:
        _log(logs, "[ERROR] 当前配置缺少 API Key / 授权参数。")
        return _build_result(
            success=False,
            summary="缺少授权参数，无法测试连接",
            logs=logs,
        )

    _log(logs, "[WARN] 当前版本尚未实现该数据源的在线探针。")
    _log(logs, "[INFO] 已校验存在 API Key，可继续保存配置并结合运行状态区域观察实际效果。")
    return _build_result(
        success=False,
        summary="已校验授权参数，但在线探针暂未实现",
        logs=logs,
        status="warning",
    )


def run_datasource_connection_test(config: DataSourceConfig) -> dict[str, Any]:
    """Run a datasource-specific connectivity test and return display-friendly logs."""
    logs: list[str] = []
    _log(logs, f"[INFO] 开始测试数据源: {config.name} ({config.source_type})")
    if not config.is_active:
        _log(logs, "[WARN] 当前配置处于停用状态，本次仅测试连接能力。")

    try:
        if config.source_type == "tushare":
            return _run_probe_with_timeout(config=config, logs=logs, probe=_test_tushare)
        if config.source_type == "akshare":
            return _run_probe_with_timeout(config=config, logs=logs, probe=_test_akshare)
        if config.source_type == "qmt":
            return _run_probe_with_timeout(config=config, logs=logs, probe=_test_qmt)
        if config.source_type in {"fred", "wind", "choice"}:
            return _test_credential_only(config, logs)

        _log(logs, f"[ERROR] 不支持的数据源类型: {config.source_type}")
        return _build_result(
            success=False,
            summary=f"不支持测试的数据源类型: {config.source_type}",
            logs=logs,
        )
    except Exception as exc:
        _log(logs, f"[ERROR] 连接测试失败: {exc}")
        return _build_result(
            success=False,
            summary=f"连接测试失败: {exc}",
            logs=logs,
        )
