"""Safe, scope-aware Alpha refresh diagnostics for user-facing views."""

from __future__ import annotations

import ast
import json
import logging
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import DatabaseError

from core.integration.task_monitor_runtime import (
    TaskExecutionRecord,
    TaskStatus,
    list_task_executions,
    project_task_business_result,
)

_PREDICT = "apps.alpha.application.tasks.qlib_predict_scores"
_MARKET_REFRESH = "data_center.refresh_full_market_publications"
_DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")
_OUTCOME_LABELS = {
    "success": "成功",
    "partial": "部分完成",
    "noop": "未执行",
    "blocked": "已阻断",
    "failed": "失败",
}
_STATUS_LABELS = {
    "pending": "排队中",
    "started": "运行中",
    "success": "已完成",
    "failure": "失败",
    "retry": "等待重试",
    "revoked": "已取消",
    "timeout": "超时",
}
_PHASE_LABELS = {
    "alpha_cache": "Alpha 缓存",
    "publication": "正式发布",
    "quote_prefetch": "行情预载",
    "quote": "行情更新",
    "valuation": "估值更新",
    "scope": "范围确认",
    "universe": "股票池确认",
    "pending": "排队中",
    "completed": "已完成",
    "sync": "同步推理",
    "async": "后台推理",
}
_COUNT_UNIT_LABELS = {
    "sync_operation": "同步步骤",
    "scope_validation": "范围校验",
    "valuation_asset": "估值证券",
    "provider_request": "数据请求",
    "quote_asset": "行情证券",
    "sampled_asset": "抽样证券",
    "registered_asset": "登记资产",
}
_STORED_COUNT_UNIT_LABELS = {
    "fact_row": "数据记录",
    "universe_asset": "股票池证券",
    "publication_member": "发布证券",
}
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
    "market_publication_failed": "全市场行情更新或正式发布未完成。现有已发布行情仍为上一版本；请重新读取状态后再试。",
    "market_publication_validation_failed": "全市场数据已经抓取，但发布证据未通过校验。系统已保留旧版本，请检查数据可用时间、质量状态和发布策略后重试。",
    "model_market_refresh_busy": "模型特征正在更新或被其他推理任务读取，本次更新已暂缓。后续定时任务会重试。",
    "inference_queue_failed": "后台暂时无法接收 Alpha 更新请求，请稍后重试；当前展示的仍是原有评分。",
    "model_market_unverified_failover": "备用行情缺少同口径原始数据用于校验，更新已阻断。请补齐可信原始行情后重试。",
    "model_market_unavailable": "行情数据源暂不可用，未能更新评分。请检查数据源连接后重试。",
    "model_market_stale": "行情数据仍未更新到目标交易日，暂不能生成当期评分。请补齐行情后重试。",
    "model_market_suspended": "本次股票池已核实为全天停牌，暂无可生成当期评分的股票。",
    "model_market_local_feature_invalid": "本地模型特征文件异常，更新已阻断。请修复特征数据后重新推理。",
    "model_market_scope_incomplete": "当前模型数据尚未覆盖完整组合股票池，推理已阻断。请补齐行情并核对停牌范围后重试。",
    "model_market_invalid": "行情数据未通过完整性校验，更新已阻断。请检查数据质量后重试。",
    "model_market_source_conflict": "行情来源的价格或复权口径不一致，更新已阻断。请修复行情后重新推理。",
    "market_calendar_unavailable": "交易日历暂不可用，Alpha 自动更新或账户推荐同步未能完整完成。评分日期仍以页面标注为准，请修复交易日历数据后重试。",
    "tushare_daily_quota_exhausted": "行情数据源的日额度已用尽，更新已阻断。额度恢复后会在后续定时任务中重试。",
    "tushare_quota_exhausted": "行情数据源额度不足，更新已阻断。请检查额度后重新推理。",
    "inference_timeout": "推理等待超过系统限制，未能确认本次完整结果。请重新读取状态，确认后再试。",
    "inference_failed": "本次推理未完成，未生成新的完整评分。请重新读取状态后再试。",
    "market_publication_in_progress": "全市场行情正在更新或发布，当前评分仍以页面标注的已完成日期为准。",
    "inference_in_progress": "Alpha 推理正在运行，当前评分仍以页面标注的已完成日期为准。",
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


def _localized_timestamp(value: datetime | None) -> str | None:
    """Return an aware timestamp in the user-facing Asia/Shanghai timezone."""

    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(_DISPLAY_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def _safe_attempt_summary(record: TaskExecutionRecord) -> dict[str, object]:
    """Return the non-sensitive attempt fields used by the Alpha summary."""

    projection = project_task_business_result(record.result)
    phase_results = (
        [
            {
                "phase": phase.phase,
                "requested": phase.requested,
                "succeeded": phase.succeeded,
                "failed": phase.failed,
                "stored": phase.stored,
            }
            for phase in projection.phase_results
        ]
        if projection.phase_results is not None
        else None
    )
    outcome = projection.outcome
    status = record.status.value
    return {
        "status": status,
        "status_label": _STATUS_LABELS.get(status, "状态待确认"),
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "started_at_local": _localized_timestamp(record.started_at),
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
        "finished_at_local": _localized_timestamp(record.finished_at),
        "retries": record.retries,
        "outcome": outcome,
        "outcome_label": _OUTCOME_LABELS.get(
            outcome or "",
            "进行中" if status in {"pending", "started", "retry"} else "结果待确认",
        ),
        "phase": projection.phase,
        "phase_label": _PHASE_LABELS.get(projection.phase or "", "处理中"),
        "count_unit": projection.count_unit,
        "count_unit_label": _COUNT_UNIT_LABELS.get(projection.count_unit or "", "记录"),
        "requested": projection.requested,
        "succeeded": projection.succeeded,
        "failed": projection.failed,
        "stored": projection.stored,
        "error_code": projection.error_code,
        "stable_error_code": projection.stable_error_code,
        "trace_id": projection.trace_id,
        "stored_count_unit": projection.stored_count_unit,
        "stored_count_unit_label": _STORED_COUNT_UNIT_LABELS.get(
            projection.stored_count_unit or "", "记录"
        ),
        "target_trade_date": projection.target_trade_date,
        "phase_results": phase_results,
        "business_success": projection.business_success,
    }


def _matches_alpha_scope(
    record: TaskExecutionRecord,
    *,
    result: dict[str, object],
    portfolio_id: int | None,
    universe_id: str,
) -> bool:
    """Keep task diagnostics bound to the already-authorized Alpha scope."""

    scope = record.kwargs.get("scope_payload")
    if scope is None and len(record.args) > 3:
        scope = record.args[3]
    scoped_batch = "daily_scoped" in record.task_name
    if scoped_batch:
        return portfolio_id is not None
    if isinstance(scope, dict):
        return portfolio_id is not None and scope.get("portfolio_id") == portfolio_id
    if portfolio_id is not None:
        return False
    if record.task_name == _PREDICT:
        task_universe = record.kwargs.get("universe_id") or (
            record.args[0] if record.args else result.get("universe_id")
        )
        return not task_universe or task_universe == universe_id
    return True


def _notice_for_active_attempt(
    record: TaskExecutionRecord,
    *,
    market_refresh: bool,
    last_completed: TaskExecutionRecord | None,
) -> dict[str, object]:
    """Build a progress notice without replacing it with an old failure."""

    return {
        "title": "行情自动更新中" if market_refresh else "Alpha 自动更新中",
        "code": "market_publication_in_progress" if market_refresh else "inference_in_progress",
        "message": _MESSAGES[
            "market_publication_in_progress" if market_refresh else "inference_in_progress"
        ],
        "attempted_at": (
            record.started_at.isoformat()
            if record.started_at
            else record.finished_at.isoformat() if record.finished_at else ""
        ),
        "level": "info",
        "current_attempt": _safe_attempt_summary(record),
        "last_completed": (
            _safe_attempt_summary(last_completed) if last_completed is not None else None
        ),
    }


def build_refresh_notice(
    records: Sequence[TaskExecutionRecord],
    *,
    portfolio_id: int | None,
    universe_id: str,
    market_recovered_at: datetime | None = None,
) -> dict[str, object]:
    """Describe current and completed attempts without exposing raw exceptions."""
    market_active: TaskExecutionRecord | None = None
    inference_active: TaskExecutionRecord | None = None
    market_completed: TaskExecutionRecord | None = None
    inference_completed: TaskExecutionRecord | None = None
    for record in records:
        market_refresh = record.task_name == _MARKET_REFRESH
        result = _payload(record.result)
        if not market_refresh and not _matches_alpha_scope(
            record,
            result=result,
            portfolio_id=portfolio_id,
            universe_id=universe_id,
        ):
            continue
        if record.status in {TaskStatus.PENDING, TaskStatus.STARTED, TaskStatus.RETRY}:
            if market_refresh and market_active is None:
                market_active = record
            elif not market_refresh and inference_active is None:
                inference_active = record
            continue
        if market_refresh and market_completed is None:
            market_completed = record
        elif not market_refresh and inference_completed is None:
            # Some Celery parent records are marked successful while carrying
            # no stored output.  They do not represent a completed inference
            # and must not hide the latest actionable failure below them.
            outcome = result.get("outcome") or result.get("status")
            if not (
                record.status == TaskStatus.SUCCESS
                and outcome == "success"
                and not result.get("stored")
            ):
                inference_completed = record

    if market_active is not None:
        return _notice_for_active_attempt(
            market_active,
            market_refresh=True,
            last_completed=market_completed,
        )

    def completed_notice(
        record: TaskExecutionRecord,
        *,
        market_refresh: bool,
    ) -> dict[str, object] | None:
        """Render a terminal business failure for one task family."""

        result = _payload(record.result)
        nested = result.get("refresh")
        refresh = nested if isinstance(nested, dict) else {}
        outcome = result.get("outcome") or result.get("status")
        failed = outcome in {"blocked", "failed", "partial", "error"} or record.status in {
            TaskStatus.FAILURE,
            TaskStatus.TIMEOUT,
            TaskStatus.REVOKED,
        }
        if (
            market_refresh
            and failed
            and market_recovered_at is not None
            and record.finished_at is not None
            and market_recovered_at >= record.finished_at
        ):
            return None
        if not failed:
            if record.task_name == _PREDICT and outcome == "success" and result.get("stored"):
                return None
            return None
        code = str(
            result.get("blocked_reason")
            or result.get("reason")
            or result.get("qlib_runtime_refresh_error_code")
            or result.get("workspace_recommendations_error_code")
            or result.get("error_code")
            or result.get("stable_error_code")
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
        scoped_batch = "daily_scoped" in record.task_name
        # Batch diagnostics are shared only for global data-source failures.
        if scoped_batch and not (code.startswith("model_market_") or "quota_exhausted" in code):
            return None
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
            "current_attempt": None,
            "last_completed": _safe_attempt_summary(record),
        }

    if market_completed is not None:
        market_notice = completed_notice(market_completed, market_refresh=True)
        if market_notice is not None:
            return market_notice
    if inference_active is not None:
        return _notice_for_active_attempt(
            inference_active,
            market_refresh=False,
            last_completed=inference_completed,
        )
    if inference_completed is not None:
        inference_notice = completed_notice(inference_completed, market_refresh=False)
        if inference_notice is not None:
            return inference_notice
    return {}


def get_refresh_notice(
    *, portfolio_id: int | None, universe_id: str, request_failed: bool = False
) -> dict[str, object]:
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
    market_recovered_at: datetime | None = None
    requires_recovery_proof = False
    for record in records:
        if record.task_name != _MARKET_REFRESH:
            continue
        if record.status in {TaskStatus.PENDING, TaskStatus.STARTED, TaskStatus.RETRY}:
            break
        projection = project_task_business_result(record.result)
        requires_recovery_proof = projection.outcome in {
            "blocked",
            "failed",
            "partial",
        } or record.status in {TaskStatus.FAILURE, TaskStatus.TIMEOUT, TaskStatus.REVOKED}
        break
    try:
        if not requires_recovery_proof:
            return build_refresh_notice(
                records,
                portfolio_id=portfolio_id,
                universe_id=universe_id,
            )
        from apps.data_center.application.public import get_decision_publication_gate

        publication_times: list[datetime] = []
        for dataset_key in (
            "equity.quote.snapshot",
            "equity.price.bar",
            "equity.valuation.fact",
        ):
            gate = get_decision_publication_gate(dataset_key)
            if gate is None or bool(gate.get("must_not_use_for_decision")):
                publication_times = []
                break
            raw_published_at = gate.get("published_at")
            if not isinstance(raw_published_at, str):
                publication_times = []
                break
            parsed = datetime.fromisoformat(raw_published_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                publication_times = []
                break
            publication_times.append(parsed)
        if len(publication_times) == 3:
            market_recovered_at = min(publication_times)
    except (DatabaseError, RuntimeError, TypeError, ValueError):
        logger.warning("Market publication recovery diagnostics unavailable", exc_info=True)
    return build_refresh_notice(
        records,
        portfolio_id=portfolio_id,
        universe_id=universe_id,
        market_recovered_at=market_recovered_at,
    )
