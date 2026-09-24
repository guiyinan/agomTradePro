"""Safe, scope-aware Alpha refresh diagnostics for user-facing views."""

from __future__ import annotations

import ast
import json
import logging
from collections.abc import Sequence

from django.db import DatabaseError

from apps.task_monitor.application.query_services import list_task_executions
from apps.task_monitor.domain.entities import TaskExecutionRecord, TaskStatus

_PREDICT = "apps.alpha.application.tasks.qlib_predict_scores"
_MARKET_REFRESH = "data_center.refresh_full_market_publications"
logger = logging.getLogger(__name__)
_TASK_NAMES = (
    _PREDICT,
    _MARKET_REFRESH,
    "alpha.qlib_daily_inference",
    "alpha.qlib_daily_scoped_inference",
    "apps.alpha.application.tasks.qlib_daily_inference",
    "apps.alpha.application.tasks.qlib_daily_scoped_inference",
)
_MESSAGES = {
    "system_audit_unavailable": "全市场行情自动发布被审计配置或服务身份阻断。请修复审计配置并绑定有效的任务身份；现有行情日期仍以页面标注为准。",
    "market_publication_failed": "全市场行情更新或发布未完成。请在任务监控中检查原因；现有行情不能视为已更新。",
    "market_publication_validation_failed": "全市场数据已经抓取，但发布证据未通过校验。系统已保留旧版本，请检查数据可用时间、质量状态和发布策略后重试。",
    "model_market_refresh_busy": "模型特征正在更新或被其他推理任务读取，本次更新已暂缓。后续定时任务会重试。",
    "inference_queue_failed": "自动推理未能提交到后台。请检查任务服务连接后重试；当前展示的仍是原有评分。",
    "model_market_unverified_failover": "备用行情缺少同口径原始数据用于校验，更新已阻断。请补齐可信原始行情后重试。",
    "model_market_unavailable": "行情数据源暂不可用，未能更新评分。请检查数据源连接后重试。",
    "model_market_stale": "行情数据仍未更新到目标交易日，暂不能生成当期评分。请补齐行情后重试。",
    "model_market_suspended": "本次股票池已核实为全天停牌，暂无可生成当期评分的股票。",
    "model_market_local_feature_invalid": "本地模型特征文件异常，更新已阻断。请修复特征数据后重新推理。",
    "model_market_scope_incomplete": "当前模型数据尚未覆盖完整组合股票池，推理已阻断。请补齐行情并核对停牌范围后重试。",
    "model_market_invalid": "行情数据未通过完整性校验，更新已阻断。请检查数据质量后重试。",
    "model_market_source_conflict": "行情来源的价格或复权口径不一致，更新已阻断。请修复行情后重新推理。",
    "tushare_daily_quota_exhausted": "行情数据源的日额度已用尽，更新已阻断。额度恢复后会在后续定时任务中重试。",
    "tushare_quota_exhausted": "行情数据源额度不足，更新已阻断。请检查额度后重新推理。",
    "inference_timeout": "推理任务执行超时。请检查任务记录并重试。",
    "inference_failed": "推理未完成，未生成新的完整评分。请在任务监控中检查原因后重试。",
    "diagnostics_unavailable": "暂时无法读取推理任务状态，请稍后刷新；当前评分日期仍以下方标注为准。",
}


def _payload(value: str | None) -> dict[str, object]:
    if not value or len(value) > 100_000:
        return {}
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError, RecursionError):
            return {}
    return {str(key): item for key, item in parsed.items()} if isinstance(parsed, dict) else {}


def build_refresh_notice(
    records: Sequence[TaskExecutionRecord], *, portfolio_id: int | None, universe_id: str
) -> dict[str, str]:
    """Describe the latest relevant completed attempt without exposing raw exceptions."""
    market_seen = False
    inference_complete = False
    for record in records:
        if record.status in {TaskStatus.PENDING, TaskStatus.STARTED, TaskStatus.RETRY}:
            continue
        market_refresh = record.task_name == _MARKET_REFRESH
        if market_refresh:
            if market_seen:
                continue
            market_seen = True
        elif inference_complete:
            continue
        scope = record.kwargs.get("scope_payload")
        if scope is None and len(record.args) > 3:
            scope = record.args[3]
        result = _payload(record.result)
        scoped_batch = "daily_scoped" in record.task_name
        if market_refresh:
            pass
        elif scoped_batch:
            if portfolio_id is None:
                continue
        elif isinstance(scope, dict):
            if portfolio_id is None or scope.get("portfolio_id") != portfolio_id:
                continue
        elif portfolio_id is not None:
            continue
        elif record.task_name == _PREDICT:
            task_universe = record.kwargs.get("universe_id") or (
                record.args[0] if record.args else result.get("universe_id")
            )
            if task_universe and task_universe != universe_id:
                continue
        nested = result.get("refresh")
        refresh = nested if isinstance(nested, dict) else {}
        outcome = result.get("outcome") or result.get("status")
        failed = outcome in {"blocked", "failed", "partial", "error"} or record.status in {
            TaskStatus.FAILURE,
            TaskStatus.TIMEOUT,
            TaskStatus.REVOKED,
        }
        if not failed:
            if record.task_name == _PREDICT and outcome == "success" and result.get("stored"):
                inference_complete = True
            continue
        code = str(
            result.get("blocked_reason")
            or result.get("reason")
            or result.get("qlib_runtime_refresh_error_code")
            or refresh.get("error_code")
            or ""
        ).lower()
        if market_refresh:
            code = (
                "system_audit_unavailable"
                if code.startswith("system_audit_")
                else (
                    code
                    if code in {"market_publication_validation_failed"}
                    else "market_publication_failed"
                )
            )
        # Batch diagnostics are shared only for global data-source failures.
        if scoped_batch and not (code.startswith("model_market_") or "quota_exhausted" in code):
            continue
        if code not in _MESSAGES:
            code = (
                "inference_timeout" if record.status == TaskStatus.TIMEOUT else "inference_failed"
            )
        return {
            "title": "行情自动发布异常" if market_refresh else "Alpha 自动更新异常",
            "code": code,
            "message": _MESSAGES[code],
            "attempted_at": record.finished_at.isoformat() if record.finished_at else "",
            "level": "warning",
        }
    return {}


def get_refresh_notice(
    *, portfolio_id: int | None, universe_id: str, request_failed: bool = False
) -> dict[str, str]:
    """Read persisted inference outcomes for an already-authorized Alpha scope."""
    if request_failed:
        return {
            "title": "Alpha 自动更新异常",
            "code": "inference_queue_failed",
            "message": _MESSAGES["inference_queue_failed"],
            "level": "warning",
            "attempted_at": "",
        }
    try:
        records = list_task_executions(_TASK_NAMES, limit=100)
    except DatabaseError:
        logger.warning("Alpha task diagnostics unavailable", exc_info=True)
        return {
            "title": "Alpha 更新状态暂不可用",
            "code": "diagnostics_unavailable",
            "message": _MESSAGES["diagnostics_unavailable"],
            "level": "warning",
            "attempted_at": "",
        }
    return build_refresh_notice(
        records,
        portfolio_id=portfolio_id,
        universe_id=universe_id,
    )
