"""
Account Application - Celery Tasks

定时任务：自动止损止盈检查、波动率控制。
"""

from __future__ import annotations

from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.core.mail import EmailMessage, send_mail
from django.utils import timezone

from apps.account.application.repository_provider import (
    PortfolioRepository,
    PositionRepository,
    SystemSettingsRepository,
    build_backup_download_url,
    describe_backup_package,
    generate_download_token,
    get_backup_email_connection,
    mark_backup_delivery_sent,
)
from apps.account.application.risk_exit_task_contracts import (
    RiskStageSnapshot,
    invalid_risk_input,
    merge_risk_snapshots,
    risk_task_result,
    summarize_risk_results,
    unknown_stage_snapshot,
)
from apps.account.application.stop_loss_use_cases import (
    AutoStopLossUseCase,
    AutoTakeProfitUseCase,
    StopLossCheckOutput,
    TakeProfitCheckOutput,
    is_valid_exit_user_id,
)
from apps.account.application.volatility_use_cases import (
    VolatilityAdjustmentOutput,
    VolatilityAdjustmentUseCase,
    VolatilityAnalysisOutput,
    VolatilityAnalysisUseCase,
)
from core.metrics import record_exception

logger = get_task_logger(__name__)

system_settings_repo = SystemSettingsRepository()
position_repo = PositionRepository()
portfolio_repo = PortfolioRepository()


def _task_outcome_fields(
    *,
    outcome: str,
    requested: int,
    succeeded: int,
    failed: int,
    stored: int,
) -> dict[str, object]:
    """Build the normalized business-outcome projection shared by Account tasks."""

    return {
        "outcome": outcome,
        "success": outcome in {"success", "partial", "noop"},
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "stored": stored,
    }


@shared_task(  # type: ignore[misc]
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    time_limit=300,
    soft_time_limit=270,
)
def send_database_backup_email_task(self: Any) -> dict[str, object]:
    """按系统配置发送加密逻辑数据导出链接；该工件不是灾备恢复点。"""
    try:
        config = system_settings_repo.get_settings()
        if not config.is_backup_due():
            return {
                "status": "skipped",
                "reason": "not_due",
                **_task_outcome_fields(
                    outcome="noop",
                    requested=1,
                    succeeded=0,
                    failed=0,
                    stored=0,
                ),
            }

        token = generate_download_token(config)
        download_url = build_backup_download_url(token)
        package_meta = describe_backup_package()

        subject = "【AgomTradePro】数据库逻辑导出下载链接"
        message = f"""
管理员您好：

数据库逻辑导出已准备好，请在链接有效期内下载。

下载链接：
{download_url}

备份周期：每 {config.backup_interval_days} 天
链接有效期：{config.backup_link_ttl_days} 天
文件格式：{package_meta['extension']} ({package_meta['format']})
密码提示：{config.backup_password_hint or '未设置提示'}

说明：
1. 下载得到的是压缩后并加密的备份文件。
2. SQLite 环境导出原始数据库快照；其他数据库环境导出 Django 全量 JSON 数据。
3. 该下载用于用户数据携带，不能替代 PostgreSQL custom-format 灾备和恢复演练。
4. 如非本人操作，请立即检查系统后台配置。
        """.strip()

        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=config.backup_mail_from_email
            or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@agomtradepro.com"),
            to=[config.backup_email],
            connection=get_backup_email_connection(config),
        )
        email.send(fail_silently=False)

        sent_at = timezone.now()
        if getattr(config, "pk", None):
            mark_backup_delivery_sent(sent_at)
        else:
            config.backup_last_sent_at = sent_at
            config.save(update_fields=["backup_last_sent_at", "updated_at"])
        logger.info("数据库备份下载链接已发送至 %s", config.backup_email)
        return {
            "status": "sent",
            "email": config.backup_email,
            **_task_outcome_fields(
                outcome="success",
                requested=1,
                succeeded=1,
                failed=0,
                stored=1,
            ),
        }
    except Exception as exc:
        logger.error(
            "Database backup email task failed: error_type=%s",
            exc.__class__.__name__,
        )
        raise self.retry(exc=exc) from exc


@shared_task(  # type: ignore[misc]
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=600,
    soft_time_limit=570,
)
def check_stop_loss_task(
    self: Any,
    user_id: int | None = None,
) -> dict[str, object]:
    """Check legacy stop rules and publish observations separately from execution."""

    if not is_valid_exit_user_id(user_id):
        return risk_task_result(
            invalid_risk_input(),
            status="error",
            reason_code="invalid_user_id",
            count_unit="task_invocation",
        )
    try:
        use_case = AutoStopLossUseCase()
    except Exception as exc:
        logger.warning("Stop-loss use-case setup failed: error_type=%s", type(exc).__name__)
        raise self.retry(exc=exc) from exc
    try:
        results = use_case.check_and_execute_stop_loss(user_id=user_id)
    except Exception as exc:
        logger.error("Stop-loss stage outcome unknown: error_type=%s", type(exc).__name__)
        record_exception(exc, module="account", is_handled=True)
        return risk_task_result(unknown_stage_snapshot(), status="error")

    if any(result.triggered for result in results):
        _send_stop_loss_notifications(results, user_id)
    return risk_task_result(summarize_risk_results(results))


@shared_task(  # type: ignore[misc]
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=600,
    soft_time_limit=570,
)
def check_take_profit_task(
    self: Any,
    user_id: int | None = None,
) -> dict[str, object]:
    """Check legacy take-profit rules without changing levels or selling positions."""

    if not is_valid_exit_user_id(user_id):
        return risk_task_result(
            invalid_risk_input(),
            status="error",
            reason_code="invalid_user_id",
            count_unit="task_invocation",
        )
    try:
        use_case = AutoTakeProfitUseCase()
    except Exception as exc:
        logger.warning("Take-profit use-case setup failed: error_type=%s", type(exc).__name__)
        raise self.retry(exc=exc) from exc
    try:
        results = use_case.check_and_execute_take_profit(user_id=user_id)
    except Exception as exc:
        logger.error("Take-profit stage outcome unknown: error_type=%s", type(exc).__name__)
        record_exception(exc, module="account", is_handled=True)
        return risk_task_result(unknown_stage_snapshot(), status="error")

    if any(result.triggered for result in results):
        _send_take_profit_notifications(results, user_id)
    return risk_task_result(summarize_risk_results(results))


@shared_task(  # type: ignore[misc]
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=600,
    soft_time_limit=570,
)
def check_stop_loss_and_take_profit_task(
    self: Any,
    user_id: int | None = None,
    checkpoint: object | None = None,
) -> dict[str, object]:
    """Run both observation stages without replayable checkpoint authority."""

    if not is_valid_exit_user_id(user_id):
        return risk_task_result(
            invalid_risk_input(),
            status="error",
            reason_code="invalid_user_id",
            count_unit="task_invocation",
        )
    if checkpoint is not None and not (type(checkpoint) is dict and not checkpoint):
        return risk_task_result(
            invalid_risk_input(),
            status="error",
            reason_code="invalid_checkpoint",
            count_unit="task_invocation",
        )

    try:
        stop_loss_use_case = AutoStopLossUseCase()
        take_profit_use_case = AutoTakeProfitUseCase()
    except Exception as exc:
        logger.warning("Combined risk setup failed: error_type=%s", type(exc).__name__)
        raise self.retry(
            exc=exc,
            kwargs={"user_id": user_id, "checkpoint": None},
        ) from exc

    try:
        stop_results = stop_loss_use_case.check_and_execute_stop_loss(user_id=user_id)
    except Exception as exc:
        logger.error("Combined stop-loss stage outcome unknown: error_type=%s", type(exc).__name__)
        record_exception(exc, module="account", is_handled=True)
        return _combined_risk_task_result(
            unknown_stage_snapshot(),
            None,
            status="error",
        )

    stop_snapshot = summarize_risk_results(stop_results)
    if any(result.triggered for result in stop_results):
        _send_stop_loss_notifications(stop_results, user_id)
    if stop_snapshot["stage_unknown_count"] or stop_snapshot["execution_unknown_count"]:
        return _combined_risk_task_result(stop_snapshot, None, status="error")

    try:
        take_results = take_profit_use_case.check_and_execute_take_profit(user_id=user_id)
    except Exception as exc:
        logger.error(
            "Combined take-profit stage outcome unknown: error_type=%s", type(exc).__name__
        )
        record_exception(exc, module="account", is_handled=True)
        return _combined_risk_task_result(
            stop_snapshot,
            unknown_stage_snapshot(),
            status="error",
        )

    take_snapshot = summarize_risk_results(take_results)
    if any(result.triggered for result in take_results):
        _send_take_profit_notifications(take_results, user_id)
    return _combined_risk_task_result(stop_snapshot, take_snapshot)


def _combined_risk_task_result(
    stop_snapshot: RiskStageSnapshot,
    take_snapshot: RiskStageSnapshot | None,
    *,
    status: str | None = None,
) -> dict[str, object]:
    """Project both stage counts without treating diagnostic snapshots as checkpoints."""

    snapshots = [stop_snapshot] + ([take_snapshot] if take_snapshot is not None else [])
    result = risk_task_result(merge_risk_snapshots(snapshots), status=status)
    result["stop_loss_checked"] = stop_snapshot["requested"]
    result["stop_loss_triggered"] = stop_snapshot["triggered_count"]
    result["stop_loss_executed"] = stop_snapshot["executed_count"]
    result["stop_loss_blocked"] = stop_snapshot["blocked_count"]
    result["stop_loss_check_unavailable"] = stop_snapshot["check_unavailable_count"]
    result["stop_loss_execution_unknown"] = stop_snapshot["execution_unknown_count"]
    result["stop_loss_stage_unknown"] = stop_snapshot["stage_unknown_count"]
    result["stop_loss_stored"] = stop_snapshot["stored"]
    result["take_profit_checked"] = take_snapshot["requested"] if take_snapshot else None
    result["take_profit_triggered"] = take_snapshot["triggered_count"] if take_snapshot else None
    result["take_profit_executed"] = take_snapshot["executed_count"] if take_snapshot else None
    result["take_profit_blocked"] = take_snapshot["blocked_count"] if take_snapshot else None
    result["take_profit_check_unavailable"] = (
        take_snapshot["check_unavailable_count"] if take_snapshot else None
    )
    result["take_profit_execution_unknown"] = (
        take_snapshot["execution_unknown_count"] if take_snapshot else None
    )
    result["take_profit_stage_unknown"] = (
        take_snapshot["stage_unknown_count"] if take_snapshot else None
    )
    result["take_profit_stored"] = take_snapshot["stored"] if take_snapshot else None
    result["stage_snapshots"] = {"stop_loss": stop_snapshot, "take_profit": take_snapshot}
    return result


def _send_stop_loss_notifications(
    results: list[StopLossCheckOutput],
    user_id: int | None = None,
) -> None:
    """Send owner diagnostics that explicitly say no automatic SELL was confirmed."""

    for result in results:
        if (
            not result.triggered
            or type(result.position_id) is not int
            or result.position_id <= 0
            or not isinstance(result.asset_code, str)
            or not result.asset_code.strip()
            or result.check_result is None
            or result.current_price is None
            or not isinstance(result.price_source, str)
            or not result.price_source.strip()
            or result.price_freshness != "realtime"
            or result.price_observed_at is None
            or result.price_observed_at.tzinfo is None
            or result.price_observed_at.utcoffset() is None
            or not result.must_not_use_for_decision
            or not result.must_not_execute
            or result.unrealized_pnl_pct is None
        ):
            continue
        try:
            subject = f"【止损条件观察】{result.asset_code}"
            trigger_reason = result.check_result.trigger_reason.replace(
                "当前价格", "观测价格"
            ).replace("当前价", "观测价格")
            message = f"""
持仓 {result.asset_code} 达到止损观察条件。旧自动卖出路径未通过资格校验，系统未提交自动卖出，也未确认成交或平仓。

触发原因: {trigger_reason}
价格观察: {result.current_price:.2f}
来源: {result.price_source}
源观测时间: {result.price_observed_at.isoformat()}
盈亏: {result.unrealized_pnl_pct:.2%}

请核对账户与可卖状态后使用受支持的操作路径。
            """.strip()
            position = position_repo.get_position_notification_context(result.position_id)
            if not isinstance(position, dict):
                continue
            owner_id = position.get("user_id")
            if (
                type(owner_id) is not int
                or owner_id <= 0
                or (user_id is not None and owner_id != user_id)
            ):
                continue
            email_value = position.get("user_email")
            if not isinstance(email_value, str) or not email_value.strip():
                continue
            user_email = email_value
            if user_email:
                sent_count = send_mail(
                    subject=subject,
                    message=message,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@agomtradepro.com"),
                    recipient_list=[user_email],
                    fail_silently=False,
                )
                if sent_count != 1:
                    logger.warning(
                        "Stop-loss observation notice delivery failed: "
                        "reason_code=notification_delivery_failed position_id=%s send_count=%s",
                        result.position_id,
                        sent_count,
                    )
        except Exception as exc:
            logger.error(
                "Stop-loss observation notice failed: "
                "reason_code=notification_delivery_failed position_id=%s error_type=%s",
                result.position_id,
                type(exc).__name__,
            )


def _send_take_profit_notifications(
    results: list[TakeProfitCheckOutput],
    user_id: int | None = None,
) -> None:
    """Send owner diagnostics that distinguish a take trigger from a filled trade."""

    for result in results:
        if (
            not result.triggered
            or type(result.position_id) is not int
            or result.position_id <= 0
            or not isinstance(result.asset_code, str)
            or not result.asset_code.strip()
            or result.check_result is None
            or result.current_price is None
            or not isinstance(result.price_source, str)
            or not result.price_source.strip()
            or result.price_freshness != "realtime"
            or result.price_observed_at is None
            or result.price_observed_at.tzinfo is None
            or result.price_observed_at.utcoffset() is None
            or not result.must_not_use_for_decision
            or not result.must_not_execute
            or result.unrealized_pnl_pct is None
        ):
            continue
        try:
            partial_info = f" (分批 {result.partial_level})" if result.partial_level else ""
            subject = f"【止盈条件观察】{result.asset_code}"
            trigger_reason = result.check_result.trigger_reason.replace(
                "当前价格", "观测价格"
            ).replace("当前价", "观测价格")
            message = f"""
持仓 {result.asset_code} 达到止盈观察条件{partial_info}。旧自动卖出路径未通过资格校验，系统未提交自动卖出，也未确认成交或平仓。

触发原因: {trigger_reason}
价格观察: {result.current_price:.2f}
来源: {result.price_source}
源观测时间: {result.price_observed_at.isoformat()}
盈亏: {result.unrealized_pnl_pct:.2%}

请核对账户与可卖状态后使用受支持的操作路径。
            """.strip()
            position = position_repo.get_position_notification_context(result.position_id)
            if not isinstance(position, dict):
                continue
            owner_id = position.get("user_id")
            if (
                type(owner_id) is not int
                or owner_id <= 0
                or (user_id is not None and owner_id != user_id)
            ):
                continue
            email_value = position.get("user_email")
            if not isinstance(email_value, str) or not email_value.strip():
                continue
            user_email = email_value
            if user_email:
                sent_count = send_mail(
                    subject=subject,
                    message=message,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@agomtradepro.com"),
                    recipient_list=[user_email],
                    fail_silently=False,
                )
                if sent_count != 1:
                    logger.warning(
                        "Take-profit observation notice delivery failed: "
                        "reason_code=notification_delivery_failed position_id=%s send_count=%s",
                        result.position_id,
                        sent_count,
                    )
        except Exception as exc:
            logger.error(
                "Take-profit observation notice failed: "
                "reason_code=notification_delivery_failed position_id=%s error_type=%s",
                result.position_id,
                type(exc).__name__,
            )


# ============================================================
# Celery Beat 配置建议
# ============================================================#
# 在 core/settings/base.py 中添加：
#
# CELERY_BEAT_SCHEDULE = {
#     'check-stop-loss-hourly': {
#         'task': 'apps.account.application.tasks.check_stop_loss_task',
#         'schedule': crontab(minute=0),  # 每小时执行
#         'options': {
#             'expires': 3600,  # 任务1小时后过期
#         },
#     },
#     'check-take-profit-hourly': {
#         'task': 'apps.account.application.tasks.check_take_profit_task',
#         'schedule': crontab(minute=5),  # 每小时第5分钟执行
#     },
# }
# 或者使用 combined 任务：
#     'check-stop-loss-take-profit': {
#         'task': 'apps.account.application.tasks.check_stop_loss_and_take_profit_task',
#         'schedule': crontab(minute=0),  # 每小时执行
#     },
# }


# ============================================================
# 波动率控制任务
# ============================================================


@shared_task(  # type: ignore[misc]
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=600,
    soft_time_limit=570,
)
def check_volatility_and_adjust_task(
    self: Any,
    user_id: int | None = None,
) -> dict[str, object]:
    """
    检查波动率并自动调整仓位

    使用方法：
    - 每日执行一次：检查所有用户的投资组合波动率
    - 指定用户：只检查该用户的投资组合

    Args:
        user_id: 用户ID，None表示检查所有用户
    """
    try:
        # 获取需要检查的投资组合
        portfolios = portfolio_repo.list_active_portfolios(user_id=user_id)

        adjusted_count = 0
        warning_count = 0
        failed_count = 0

        for portfolio in portfolios:
            try:
                # 分析波动率
                analysis_use_case = VolatilityAnalysisUseCase()
                analysis = analysis_use_case.analyze_portfolio_volatility(
                    portfolio_id=portfolio["id"],
                    user_id=portfolio["user_id"],
                )

                # 如果需要调整，执行降仓
                if analysis.adjustment_result.should_reduce:
                    adjustment_use_case = VolatilityAdjustmentUseCase()
                    result = adjustment_use_case.execute_volatility_adjustment(
                        portfolio_id=portfolio["id"],
                        user_id=portfolio["user_id"],
                    )

                    if result["status"] == "executed":
                        adjusted_count += 1
                        _send_volatility_adjustment_notification(
                            portfolio_id=portfolio["id"],
                            user_id=portfolio["user_id"],
                            analysis=analysis,
                            result=result,
                        )
                    logger.info(
                        f"投资组合 {portfolio['id']} 波动率调整完成: " f"{result['status']}"
                    )

                # 发送警告（如果波动率接近上限）
                elif analysis.adjustment_result.volatility_ratio > 1.0:
                    warning_count += 1
                    _send_volatility_warning_notification(
                        portfolio_id=portfolio["id"],
                        user_id=portfolio["user_id"],
                        analysis=analysis,
                    )

            except Exception as exc:
                failed_count += 1
                logger.error(
                    "Portfolio volatility check failed: portfolio_id=%s error_type=%s",
                    portfolio["id"],
                    exc.__class__.__name__,
                )
                continue

        logger.info(
            f"波动率检查完成，共检查 {len(portfolios)} 个组合，"
            f"调整 {adjusted_count} 个，警告 {warning_count} 个"
        )

        succeeded_count = len(portfolios) - failed_count
        if not portfolios:
            outcome = "noop"
        elif failed_count == len(portfolios):
            outcome = "failed"
        elif failed_count:
            outcome = "partial"
        else:
            outcome = "success"
        return {
            "status": "success",
            "checked_count": len(portfolios),
            "adjusted_count": adjusted_count,
            "warning_count": warning_count,
            "failed_count": failed_count,
            **_task_outcome_fields(
                outcome=outcome,
                requested=len(portfolios),
                succeeded=succeeded_count,
                failed=failed_count,
                stored=adjusted_count,
            ),
        }

    except Exception as exc:
        logger.error(
            "Volatility check task failed: error_type=%s",
            exc.__class__.__name__,
        )
        raise self.retry(exc=exc) from exc


def _send_volatility_adjustment_notification(
    portfolio_id: int,
    user_id: int,
    analysis: VolatilityAnalysisOutput,
    result: VolatilityAdjustmentOutput,
) -> None:
    """
    发送波动率调整通知

    Args:
        portfolio_id: 投资组合ID
        user_id: 用户ID
        analysis: 波动率分析结果
        result: 调整结果
    """
    try:
        portfolio = portfolio_repo.get_portfolio_notification_context(portfolio_id)
        if not portfolio:
            raise ValueError(f"投资组合 {portfolio_id} 不存在")

        subject = f"【波动率控制】投资组合 {portfolio['name']} 已降仓"

        message = f"""
您的投资组合 "{portfolio['name']}" 因波动率超标已自动降仓

当前波动率（30天）: {analysis.current_volatility_30d:.2%}
目标波动率: {analysis.target_volatility:.2%}
波动率比率: {analysis.adjustment_result.volatility_ratio:.2f}x

调整原因: {analysis.adjustment_result.reduction_reason}

调整后仓位乘数: {result['position_multiplier']:.1%}
减少持仓数量: {len(result['reduced_positions'])}

请及时查看投资组合详情。
        """.strip()

        # 获取用户邮箱
        user_email = portfolio["user_email"]

        if user_email:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(
                    settings,
                    "DEFAULT_FROM_EMAIL",
                    "noreply@agomtradepro.com",
                ),
                recipient_list=[user_email],
                fail_silently=True,
            )
            logger.info(f"波动率调整通知已发送至 {user_email}")

    except Exception as exc:
        logger.error(
            "Volatility adjustment notification failed: portfolio_id=%s error_type=%s",
            portfolio_id,
            exc.__class__.__name__,
        )


def _send_volatility_warning_notification(
    portfolio_id: int,
    user_id: int,
    analysis: VolatilityAnalysisOutput,
) -> None:
    """
    发送波动率警告通知

    Args:
        portfolio_id: 投资组合ID
        user_id: 用户ID
        analysis: 波动率分析结果
    """
    try:
        portfolio = portfolio_repo.get_portfolio_notification_context(portfolio_id)
        if not portfolio:
            raise ValueError(f"投资组合 {portfolio_id} 不存在")

        subject = f"【波动率警告】投资组合 {portfolio['name']} 波动率偏高"

        message = f"""
您的投资组合 "{portfolio['name']}" 当前波动率偏高，请关注

当前波动率（30天）: {analysis.current_volatility_30d:.2%}
当前波动率（60天）: {analysis.current_volatility_60d:.2%}
当前波动率（90天）: {analysis.current_volatility_90d:.2%}
目标波动率: {analysis.target_volatility:.2%}
波动率比率: {analysis.adjustment_result.volatility_ratio:.2f}x

当前未触发自动降仓（容忍度内），但建议关注市场波动情况。

如需调整目标波动率配置，请登录系统设置。
        """.strip()

        # 获取用户邮箱
        user_email = portfolio["user_email"]

        if user_email:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(
                    settings,
                    "DEFAULT_FROM_EMAIL",
                    "noreply@agomtradepro.com",
                ),
                recipient_list=[user_email],
                fail_silently=True,
            )
            logger.info(f"波动率警告通知已发送至 {user_email}")

    except Exception as e:
        logger.error(f"发送波动率警告通知失败: {e}")


# 更新 Celery Beat 配置建议：
#
# CELERY_BEAT_SCHEDULE = {
#     'check-stop-loss-hourly': {
#         'task': 'apps.account.application.tasks.check_stop_loss_task',
#         'schedule': crontab(minute=0),
#     },
#     'check-take-profit-hourly': {
#         'task': 'apps.account.application.tasks.check_take_profit_task',
#         'schedule': crontab(minute=5),
#     },
#     'check-volatility-daily': {
#         'task': 'apps.account.application.tasks.check_volatility_and_adjust_task',
#         'schedule': crontab(hour=0, minute=0),  # 每日00:00执行
#         'options': {
#             'expires': 7200,  # 任务2小时后过期
#         },
#     },
# }
