"""
模拟盘交易 Celery 任务

Application层异步任务：
- 每日自动交易执行
- 持仓价格更新
- 绩效定期重算
"""

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from typing import Any, cast
from uuid import UUID

from celery import shared_task
from celery.exceptions import Retry
from django.conf import settings

from apps.data_center.application.price_service import UnifiedPriceService
from apps.realtime.application.price_polling_service import PricePollingUseCase
from apps.simulated_trading.application.auto_trading_outcome_reporting import (
    auto_trading_count_units as auto_trading_count_units,
)
from apps.simulated_trading.application.auto_trading_outcome_reporting import (
    serialize_auto_trading_batch_outcome,
)
from apps.simulated_trading.application.automatic_invocation import (
    AutomaticInvocationEngine,
    AutoTradingInvocationConflict,
    AutoTradingInvocationRequest,
    ExecuteAutomaticInvocation,
    FrozenAutoTradingScope,
    get_auto_invocation_repository,
    validate_auto_invocation_key,
)
from apps.simulated_trading.application.automatic_invocation_task import (
    DailyAutoTradingInvocationTask,
)
from apps.simulated_trading.application.daily_inspection_service import DailyInspectionService
from apps.simulated_trading.application.interface_services import build_auto_trading_engine
from apps.simulated_trading.application.performance_calculator import PerformanceCalculator
from apps.simulated_trading.application.repository_provider import (
    get_simulated_account_repository,
    get_simulated_position_repository,
    get_simulated_trade_repository,
)
from apps.simulated_trading.application.task_contract_support import (
    _MAX_TASK_BATCH_SIZE as _MAX_TASK_BATCH_SIZE,
)
from apps.simulated_trading.application.task_contract_support import (
    _TASK_OUTCOMES as _TASK_OUTCOMES,
)
from apps.simulated_trading.application.task_contract_support import (
    DecoratedResult as DecoratedResult,
)
from apps.simulated_trading.application.task_contract_support import TaskResult as TaskResult
from apps.simulated_trading.application.task_contract_support import (
    _auto_trading_unavailable_scope_result as _auto_trading_unavailable_scope_result,
)
from apps.simulated_trading.application.task_contract_support import (
    _BoundTaskProtocol as _BoundTaskProtocol,
)
from apps.simulated_trading.application.task_contract_support import (
    _build_pre_execution_failure_batch as _build_pre_execution_failure_batch,
)
from apps.simulated_trading.application.task_contract_support import (
    _failed_task_result as _failed_task_result,
)
from apps.simulated_trading.application.task_contract_support import (
    _parse_task_date as _parse_task_date,
)
from apps.simulated_trading.application.task_contract_support import (
    _require_non_negative_count as _require_non_negative_count,
)
from apps.simulated_trading.application.task_contract_support import _task_result as _task_result
from apps.simulated_trading.application.task_contract_support import (
    _TaskRequestProtocol as _TaskRequestProtocol,
)
from apps.simulated_trading.application.task_contract_support import _TypedTask as _TypedTask
from apps.simulated_trading.application.task_contract_support import (
    _validate_optional_id as _validate_optional_id,
)
from apps.simulated_trading.application.task_contract_support import (
    _validate_optional_ids as _validate_optional_ids,
)
from apps.simulated_trading.application.task_contract_support import (
    select_default_auto_trading_account_ids as select_default_auto_trading_account_ids,
)
from apps.simulated_trading.application.task_notifications import (
    PerformanceSummary as PerformanceSummary,
)
from apps.simulated_trading.application.task_notifications import (
    PerformanceSummaryEntry as PerformanceSummaryEntry,
)
from apps.simulated_trading.application.task_notifications import (
    _record_notification_history as _record_notification_history,
)
from apps.simulated_trading.application.task_notifications import (
    _require_int_field as _require_int_field,
)
from apps.simulated_trading.application.task_notifications import (
    _send_daily_inspection_email,
    _send_rebalance_proposal_notification,
    build_performance_summary_email,
    build_performance_summary_entry,
)
from apps.simulated_trading.application.use_cases import (
    GetAccountPerformanceUseCase,
    SimulatedAccountRepositoryProtocol,
)
from core.exceptions import DataFetchError, InvalidInputError

logger = logging.getLogger(__name__)

_MAX_INACTIVE_DAYS = 3_650


def typed_shared_task(
    *decorator_args: object,
    **decorator_kwargs: object,
) -> Callable[[Callable[..., DecoratedResult]], _TypedTask[DecoratedResult]]:
    """Narrow Celery's untyped decorator while preserving task return types."""

    decorator = shared_task(*decorator_args, **decorator_kwargs)
    return cast(
        Callable[[Callable[..., DecoratedResult]], _TypedTask[DecoratedResult]],
        decorator,
    )


def execute_realtime_price_polling() -> dict[str, Any]:
    """Execute one realtime polling cycle through the owning realtime app."""

    polling_factory = cast(Callable[[], PricePollingUseCase], PricePollingUseCase)
    return polling_factory().execute_price_polling()


def _resolve_default_auto_trading_account_ids(
    account_repository: SimulatedAccountRepositoryProtocol,
) -> list[int]:
    """Freeze only active, enabled accounts explicitly typed as simulated."""
    return select_default_auto_trading_account_ids(account_repository.get_active_accounts())


def _handle_pre_execution_failure(
    task: _BoundTaskProtocol,
    error: Exception,
    *,
    target_date: date,
    account_ids: tuple[int, ...] | None,
) -> dict[str, Any]:
    """Retry only setup failures and return a safe result after exhaustion."""
    logger.exception("模拟自动交易任务执行前准备失败", exc_info=error)
    retries = task.request.retries
    max_retries = task.max_retries
    if type(retries) is int and type(max_retries) is int and retries < max_retries:
        try:
            raise task.retry(exc=error, countdown=60 * (2**retries))
        except Retry:
            raise
        except Exception:
            logger.exception("无法安排模拟自动交易任务准备重试")
    if account_ids is None:
        return _auto_trading_unavailable_scope_result(target_date=target_date)
    return serialize_auto_trading_batch_outcome(
        _build_pre_execution_failure_batch(account_ids),
        trade_date=target_date,
    )


# ============================================================================
# 核心定时任务
# ============================================================================


@typed_shared_task(
    bind=True,
    base=DailyAutoTradingInvocationTask,
    max_retries=3,
    default_retry_delay=300,
    time_limit=900,
    soft_time_limit=850,
)
def daily_auto_trading_task(
    self: _BoundTaskProtocol,
    trade_date: str | None = None,
    account_ids: list[int] | None = None,
    *,
    invocation_key: str | None = None,
) -> dict[str, Any]:
    """
    每日自动交易任务

    Celery Beat 配置建议：
    - 执行时间：每个交易日 15:30（收盘后）
    - crontab: hour=15, minute=30, day_of_week='mon-fri'

    Args:
        trade_date: 交易日期（YYYY-MM-DD，默认今天）
        account_ids: 指定账户ID列表（None表示全部活跃且启用的模拟账户）
        invocation_key: 调用方提供或由 Celery 发布器生成的业务执行身份

    Returns:
        任务结果字典
    """
    # 1. Validate Celery input before touching repositories or external services.
    try:
        validate_auto_invocation_key(invocation_key)
        target_date = _parse_task_date(trade_date, "trade_date")
        validated_account_ids = _validate_optional_ids(account_ids, "account_ids")
    except (InvalidInputError, TypeError, ValueError) as exc:
        return _failed_task_result(exc)

    resolved_account_ids: tuple[int, ...] | None = (
        tuple(validated_account_ids) if validated_account_ids is not None else None
    )
    request = AutoTradingInvocationRequest(
        namespace="celery:daily-simulated-auto",
        invocation_key=validate_auto_invocation_key(invocation_key),
        trade_date=target_date if trade_date is not None else None,
        requested_account_ids=resolved_account_ids,
    )

    def resolve_scope() -> FrozenAutoTradingScope:
        nonlocal resolved_account_ids
        if resolved_account_ids is None:
            account_repo = get_simulated_account_repository()
            resolved_account_ids = tuple(_resolve_default_auto_trading_account_ids(account_repo))
        return FrozenAutoTradingScope(target_date, resolved_account_ids)

    def authorize_scope(scope: FrozenAutoTradingScope) -> None:
        # Celery is a trusted internal producer. Engine and UoW still validate each account.
        if (
            request.requested_account_ids is not None
            and scope.account_ids != request.requested_account_ids
        ):
            raise AutoTradingInvocationConflict(
                "task account scope differs from its original request"
            )

    def build_engine(invocation_id: UUID) -> AutomaticInvocationEngine:
        return build_auto_trading_engine(invocation_id=invocation_id)

    try:
        result = ExecuteAutomaticInvocation(get_auto_invocation_repository()).execute(
            request,
            resolve_scope=resolve_scope,
            authorize_scope=authorize_scope,
            build_engine=build_engine,
        )
    except AutoTradingInvocationConflict as error:
        return _failed_task_result(error)
    except Exception as error:
        # Guarded execution consumes started-run errors and never re-enters Engine.
        return _handle_pre_execution_failure(
            self, error, target_date=target_date, account_ids=resolved_account_ids
        )
    logger.info(
        "模拟自动交易完成 requested=%s buy=%s sell=%s replayed=%s",
        result.outcome.requested,
        result.outcome.buy_count,
        result.outcome.sell_count,
        result.replayed,
    )
    return serialize_auto_trading_batch_outcome(result.outcome, trade_date=result.scope.trade_date)


@typed_shared_task(
    name="simulated.update_position_prices",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def update_position_prices_task(
    self: _BoundTaskProtocol,
    account_id: int | None = None,
) -> dict[str, Any]:
    """
    更新持仓价格任务

    每日收盘后更新所有持仓的当前价格，用于计算浮盈浮亏。

    建议执行时间：每个交易日 16:00（收盘后30分钟）

    Args:
        account_id: 指定账户ID（None表示全部账户）

    Returns:
        更新结果
    """
    try:
        validated_account_id = _validate_optional_id(account_id, "account_id")
    except (TypeError, ValueError) as exc:
        return _failed_task_result(exc)

    logger.info(f"开始更新持仓价格: account_id={validated_account_id}")

    try:
        account_repo = get_simulated_account_repository()
        position_repo = get_simulated_position_repository()
        price_provider = UnifiedPriceService()

        # 获取账户列表
        if validated_account_id is not None:
            account = account_repo.get_by_id(validated_account_id)
            if account is None:
                return _task_result(
                    outcome="failed",
                    requested=1,
                    succeeded=0,
                    failed=1,
                    stored=0,
                    error=f"账户不存在: {validated_account_id}",
                )
            accounts = [account]
        else:
            accounts = account_repo.get_active_accounts()

        updated_count = 0
        error_count = 0
        errors: list[dict[str, Any]] = []
        warning_count = 0
        warnings: list[dict[str, Any]] = []
        successful_account_count = 0
        stored_account_count = 0

        for account in accounts:
            positions = position_repo.get_by_account(account.account_id)
            account_has_errors = False

            for position in positions:
                try:
                    # 获取最新价格
                    current_price = price_provider.require_latest_price(
                        position.asset_code,
                        asset_type=position.asset_type,
                    )

                    # 更新持仓价格和市值
                    updated_position = replace(
                        position,
                        current_price=current_price,
                        market_value=position.quantity * current_price,
                        unrealized_pnl=(current_price - position.avg_cost) * position.quantity,
                        unrealized_pnl_pct=(
                            ((current_price - position.avg_cost) / position.avg_cost) * 100
                            if position.avg_cost > 0
                            else 0.0
                        ),
                        last_update_date=date.today(),
                    )
                    position_repo.save(updated_position)
                    updated_count += 1

                except DataFetchError as e:
                    if position.current_price > 0:
                        logger.warning(
                            "更新持仓 %s 失败，沿用库内价格: %s",
                            position.asset_code,
                            e,
                        )
                        warning_count += 1
                        warnings.append(
                            {
                                "account_id": account.account_id,
                                "asset_code": position.asset_code,
                                "warning": str(e),
                                "fallback": "cached_position_price",
                                "details": e.details,
                            }
                        )
                        continue
                    logger.error(f"更新持仓 {position.asset_code} 失败: {e}")
                    account_has_errors = True
                    error_count += 1
                    errors.append(
                        {
                            "account_id": account.account_id,
                            "asset_code": position.asset_code,
                            "error": str(e),
                            "details": e.details,
                        }
                    )
                except Exception as e:
                    logger.error(f"更新持仓 {position.asset_code} 失败: {e}")
                    account_has_errors = True
                    error_count += 1
                    errors.append(
                        {
                            "account_id": account.account_id,
                            "asset_code": position.asset_code,
                            "error": str(e),
                        }
                    )

            # 更新账户总市值
            if account_has_errors:
                logger.error(
                    "账户 %s 存在持仓价格缺失，跳过账户总市值刷新",
                    account.account_id,
                )
                continue

            positions = position_repo.get_by_account(account.account_id)
            total_market_value = sum(p.market_value for p in positions)
            updated_account = replace(
                account,
                current_market_value=total_market_value,
                total_value=account.current_cash + total_market_value,
            )
            account_repo.save(updated_account)
            successful_account_count += 1
            stored_account_count += 1

        logger.info(f"持仓价格更新完成: {updated_count} 个成功, {error_count} 个失败")

        failed_account_count = len(accounts) - successful_account_count
        if not accounts:
            outcome = "noop"
        elif failed_account_count and successful_account_count:
            outcome = "partial"
        elif failed_account_count:
            outcome = "failed"
        else:
            outcome = "success"
        return _task_result(
            outcome=outcome,
            requested=len(accounts),
            succeeded=successful_account_count,
            failed=failed_account_count,
            stored=updated_count + stored_account_count,
            updated_count=updated_count,
            warning_count=warning_count,
            warnings=warnings,
            error_count=error_count,
            errors=errors,
        )

    except Exception as e:
        logger.exception(f"更新持仓价格任务失败: {e}")
        return _failed_task_result(e)


@typed_shared_task(
    name="simulated.calculate_all_performance",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def calculate_all_performance_task(
    self: _BoundTaskProtocol,
    trade_date: str | None = None,
) -> dict[str, Any]:
    """
    全量绩效计算任务

    重新计算所有活跃账户的绩效指标。

    建议执行时间：每周日凌晨 2:00

    Args:
        trade_date: 计算日期（默认今天）

    Returns:
        计算结果
    """
    try:
        target_date = _parse_task_date(trade_date, "trade_date")
    except (TypeError, ValueError) as exc:
        return _failed_task_result(exc)

    logger.info(f"开始全量绩效计算: {target_date}")

    try:
        calculator_factory = cast(Callable[[], PerformanceCalculator], PerformanceCalculator)
        calculator = calculator_factory()
        account_repo = get_simulated_account_repository()
        accounts = account_repo.get_active_accounts()

        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for account in accounts:
            try:
                metrics = calculator.calculate_and_update_performance(
                    account_id=account.account_id, trade_date=target_date
                )
                results.append(
                    {
                        "account_id": account.account_id,
                        "account_name": account.account_name,
                        "total_return": metrics.get("total_return", 0.0),
                        "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
                        "max_drawdown": metrics.get("max_drawdown", 0.0),
                        "win_rate": metrics.get("win_rate", 0.0),
                    }
                )
            except Exception as e:
                logger.error(f"计算账户 {account.account_id} 绩效失败: {e}")
                errors.append({"account_id": account.account_id, "error": str(e)})

        logger.info(f"全量绩效计算完成: {len(results)} 个账户")

        succeeded_count = len(results)
        failed_count = len(errors)
        if not accounts:
            outcome = "noop"
        elif succeeded_count and failed_count:
            outcome = "partial"
        elif failed_count:
            outcome = "failed"
        else:
            outcome = "success"
        return _task_result(
            outcome=outcome,
            requested=len(accounts),
            succeeded=succeeded_count,
            failed=failed_count,
            stored=succeeded_count,
            trade_date=target_date.isoformat(),
            account_count=succeeded_count,
            results=results,
            errors=errors,
        )

    except Exception as e:
        logger.exception(f"全量绩效计算任务失败: {e}")
        return _failed_task_result(e)


# ============================================================================
# 维护任务
# ============================================================================


@typed_shared_task(
    name="simulated.cleanup_inactive_accounts",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def cleanup_inactive_accounts_task(
    self: _BoundTaskProtocol,
    inactive_days: int = 180,
) -> dict[str, Any]:
    """
    清理不活跃账户任务

    停用长期无交易的模拟账户。

    建议执行时间：每周日凌晨 3:00

    Args:
        inactive_days: 不活跃天数阈值

    Returns:
        清理结果
    """
    from datetime import timedelta

    if type(inactive_days) is not int or not 1 <= inactive_days <= _MAX_INACTIVE_DAYS:
        return _failed_task_result(
            ValueError(f"inactive_days must be between 1 and {_MAX_INACTIVE_DAYS}")
        )

    logger.info(f"开始清理不活跃账户: {inactive_days} 天无交易")

    try:
        account_repo = get_simulated_account_repository()
        cutoff_date = date.today() - timedelta(days=inactive_days)

        accounts = account_repo.get_active_accounts()
        deactivated_count = 0

        for account in accounts:
            # 检查最后交易日期
            if account.last_trade_date and account.last_trade_date < cutoff_date:
                # 停用账户
                updated_account = replace(account, is_active=False, auto_trading_enabled=False)
                account_repo.save(updated_account)
                deactivated_count += 1
                logger.info(
                    f"停用不活跃账户: {account.account_name} (最后交易: {account.last_trade_date})"
                )

        logger.info(f"清理完成: {deactivated_count} 个账户被停用")

        return _task_result(
            outcome="success" if deactivated_count else "noop",
            requested=len(accounts),
            succeeded=len(accounts),
            failed=0,
            stored=deactivated_count,
            deactivated_count=deactivated_count,
        )

    except Exception as e:
        logger.exception(f"清理不活跃账户任务失败: {e}")
        return _failed_task_result(e)


@typed_shared_task(
    name="simulated.send_performance_summary",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def send_performance_summary_task(
    self: _BoundTaskProtocol,
    account_ids: list[int] | None = None,
) -> dict[str, Any]:
    """
    发送绩效摘要任务

    生成并发送账户绩效摘要（可集成邮件/消息推送）。

    建议执行时间：每个交易日 17:00

    Args:
        account_ids: 指定账户ID列表（None表示全部活跃账户）

    Returns:
        发送结果
    """
    try:
        validated_account_ids = _validate_optional_ids(account_ids, "account_ids")
    except (TypeError, ValueError) as exc:
        return _failed_task_result(exc)

    logger.info("开始生成绩效摘要")

    try:
        account_repo = get_simulated_account_repository()
        position_repo = get_simulated_position_repository()
        trade_repo = get_simulated_trade_repository()

        # 获取账户列表
        missing_account_count = 0
        if validated_account_ids is not None:
            accounts = []
            for acc_id in validated_account_ids:
                acc = account_repo.get_by_id(acc_id)
                if acc:
                    accounts.append(acc)
                else:
                    missing_account_count += 1
        else:
            accounts = account_repo.get_active_accounts()

        # 生成摘要
        use_case = GetAccountPerformanceUseCase(account_repo, position_repo, trade_repo)
        summary_entries: list[PerformanceSummaryEntry] = []
        summary_errors: list[dict[str, Any]] = []

        for account in accounts:
            try:
                result = use_case.execute(account.account_id)
                summary_entries.append(build_performance_summary_entry(result))
            except Exception as account_error:
                summary_errors.append(
                    {"account_id": account.account_id, "error": str(account_error)}
                )

        summaries = [entry["summary"] for entry in summary_entries]
        logger.info(f"绩效摘要生成完成: {len(summaries)} 个账户")

        # 邮件推送绩效摘要
        notification_results: list[dict[str, Any]] = []
        notification_error: str | None = None
        notification_requested_count = 0
        try:
            from shared.infrastructure.notification_service import (
                NotificationPriority,
                get_notification_service,
            )

            subject, body = build_performance_summary_email(
                summary_entries,
                date.today(),
            )

            # 从 settings 获取收件人列表
            recipients = getattr(settings, "PERFORMANCE_SUMMARY_RECIPIENTS", [])
            if type(recipients) is not list or any(
                type(recipient) is not str or not recipient for recipient in recipients
            ):
                raise ValueError("performance summary recipients are malformed")
            if recipients and summaries:
                notification_requested_count = len(recipients)
                results = get_notification_service().send_email(
                    subject=subject,
                    body=body,
                    recipients=recipients,
                    priority=NotificationPriority.NORMAL,
                )
                if type(results) is not list or len(results) != len(recipients):
                    raise ValueError("performance notification evidence count mismatch")
                notification_results = [
                    {"email": r.recipient.email, "success": r.success} for r in results
                ]
                if any(type(result["success"]) is not bool for result in notification_results):
                    raise ValueError("performance notification evidence is malformed")
                logger.info(
                    f"绩效摘要邮件发送完成: "
                    f"{sum(1 for r in results if r.success)}/{len(results)} 成功"
                )
            else:
                logger.info("未配置 PERFORMANCE_SUMMARY_RECIPIENTS，跳过邮件推送")

        except Exception as notify_err:
            logger.warning(f"绩效摘要邮件推送失败（不影响主流程）: {notify_err}")
            notification_error = str(notify_err)
            configured_recipients = getattr(settings, "PERFORMANCE_SUMMARY_RECIPIENTS", [])
            notification_requested_count = (
                len(configured_recipients) if type(configured_recipients) is list else 0
            )

        requested_account_count = (
            len(validated_account_ids) if validated_account_ids is not None else len(accounts)
        )
        failed_account_count = missing_account_count + len(summary_errors)
        succeeded_notification_count = sum(
            1 for result in notification_results if result["success"]
        )
        failed_notification_count = notification_requested_count - succeeded_notification_count
        if requested_account_count == 0:
            outcome = "noop"
        elif len(summaries) and (
            failed_account_count or failed_notification_count or notification_error is not None
        ):
            outcome = "partial"
        elif failed_account_count:
            outcome = "failed"
        else:
            outcome = "success"
        return _task_result(
            outcome=outcome,
            requested=requested_account_count,
            succeeded=len(summaries),
            failed=failed_account_count,
            stored=0,
            summaries=summaries,
            summary_errors=summary_errors,
            notifications=notification_results,
            notification_error=notification_error,
            requested_recipient_count=notification_requested_count,
            succeeded_recipient_count=succeeded_notification_count,
            failed_recipient_count=failed_notification_count,
        )

    except Exception as e:
        logger.exception(f"发送绩效摘要任务失败: {e}")
        requested_count = len(validated_account_ids) if validated_account_ids else 1
        return _failed_task_result(e, requested=requested_count)


@typed_shared_task(
    name="simulated.daily_portfolio_inspection",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def daily_portfolio_inspection_task(
    self: _BoundTaskProtocol,
    account_id: int | None = None,
    strategy_id: int | None = None,
    inspection_date: str | None = None,
    auto_create_proposal: bool = True,
) -> dict[str, Any]:
    """
    日更巡检任务（ETF稳健组合）

    该任务必须由 beat/调度器显式提供 account_id 和 strategy_id。
    未配置时直接跳过，避免历史脏配置持续刷错。

    Args:
        account_id: 账户ID
        strategy_id: 策略ID
        inspection_date: 巡检日期
        auto_create_proposal: 是否自动创建再平衡建议
    """
    try:
        validated_account_id = _validate_optional_id(account_id, "account_id")
        validated_strategy_id = _validate_optional_id(strategy_id, "strategy_id")
        target_date = _parse_task_date(inspection_date, "inspection_date")
        if type(auto_create_proposal) is not bool:
            raise ValueError("auto_create_proposal must be a boolean")
    except (TypeError, ValueError) as exc:
        return _failed_task_result(exc)
    logger.info(
        "开始执行日更巡检: account_id=%s, strategy_id=%s, date=%s, auto_proposal=%s",
        validated_account_id,
        validated_strategy_id,
        target_date,
        auto_create_proposal,
    )
    if validated_account_id is None or validated_strategy_id is None:
        logger.warning(
            "跳过日更巡检：缺少必要配置 account_id=%s strategy_id=%s",
            validated_account_id,
            validated_strategy_id,
        )
        return _task_result(
            outcome="blocked",
            requested=1,
            succeeded=0,
            failed=0,
            stored=0,
            compatible_success=True,
            status="skipped",
            reason="missing_task_configuration",
            account_id=validated_account_id,
            strategy_id=validated_strategy_id,
            inspection_date=target_date.isoformat(),
        )
    try:
        account_repo = get_simulated_account_repository()
        account = account_repo.get_by_id(validated_account_id)
        if account is None:
            logger.warning("跳过日更巡检：账户不存在 account_id=%s", validated_account_id)
            return _task_result(
                outcome="blocked",
                requested=1,
                succeeded=0,
                failed=0,
                stored=0,
                compatible_success=True,
                status="skipped",
                reason="account_not_found",
                account_id=validated_account_id,
                strategy_id=validated_strategy_id,
                inspection_date=target_date.isoformat(),
            )

        # 使用新方法运行巡检并可能创建再平衡建议
        result = DailyInspectionService.run_and_create_proposal(
            account_id=validated_account_id,
            inspection_date=target_date,
            strategy_id=validated_strategy_id,
            auto_create_proposal=auto_create_proposal,
        )

        # 发送巡检邮件通知
        _send_daily_inspection_email(result=result)

        # 如果创建了再平衡建议，发送额外通知
        if result.get("proposal_created"):
            _send_rebalance_proposal_notification(result=result)
            logger.info(
                "已创建再平衡建议: account_id=%s, proposal_id=%s",
                validated_account_id,
                result["proposal_id"],
            )

        logger.info(
            "日更巡检完成: account_id=%s, report_id=%s, status=%s, proposal_id=%s",
            validated_account_id,
            result["report_id"],
            result["status"],
            result.get("proposal_id"),
        )
        stored_count = 1 + int(result.get("proposal_created") is True)
        return _task_result(
            outcome="success",
            requested=1,
            succeeded=1,
            failed=0,
            stored=stored_count,
            **result,
        )
    except ValueError as exc:
        return _task_result(
            outcome="failed",
            requested=1,
            succeeded=0,
            failed=1,
            stored=0,
            error=str(exc),
            account_id=validated_account_id,
            inspection_date=target_date.isoformat(),
        )
    except Exception as exc:  # pragma: no cover - celery runtime guard
        logger.exception("日更巡检任务失败: %s", exc)
        return _task_result(
            outcome="failed",
            requested=1,
            succeeded=0,
            failed=1,
            stored=0,
            error=str(exc),
            account_id=validated_account_id,
            inspection_date=target_date.isoformat(),
        )


# ============================================================================
# 持仓证伪检查任务
# ============================================================================


@typed_shared_task(
    name="simulated.check_position_invalidation",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def check_position_invalidation_task(
    self: _BoundTaskProtocol,
) -> dict[str, Any]:
    """
    持仓证伪检查任务

    定期检查所有持仓的证伪条件是否满足，满足时标记并提示平仓。

    建议执行时间：每个交易日 10:00, 14:00（盘中检查）

    Returns:
        检查结果
    """
    logger.info("=" * 60)
    logger.info("开始持仓证伪检查")
    logger.info("=" * 60)

    try:
        from apps.simulated_trading.application.position_invalidation_checker import (
            check_and_invalidate_positions,
        )

        # 检查并证伪满足条件的持仓
        result = check_and_invalidate_positions()
        if type(result) is not dict:
            raise ValueError("invalidation checker returned malformed evidence")
        checked_count = _require_non_negative_count(result, "checked")
        invalidated_count = _require_non_negative_count(result, "invalidated")
        positions = result.get("positions")
        if type(positions) is not list or invalidated_count > checked_count:
            raise ValueError("invalidation checker returned inconsistent evidence")
        if len(positions) != invalidated_count:
            raise ValueError("invalidation position count does not match evidence")

        logger.info("证伪检查完成:")
        logger.info(f"  检查持仓: {checked_count} 个")
        logger.info(f"  证伪数量: {invalidated_count} 个")

        # 如果有新的证伪持仓，记录详细信息
        if invalidated_count > 0:
            logger.warning("新证伪持仓列表:")
            for pos in positions:
                logger.warning(
                    f"  - 账户 {pos['account_id']}: {pos['asset_code']} ({pos['asset_name']})"
                    f" | 原因: {pos['reason']}"
                )

        logger.info("=" * 60)

        return _task_result(
            outcome="success" if checked_count else "noop",
            requested=checked_count,
            succeeded=checked_count,
            failed=0,
            stored=invalidated_count,
            checked=checked_count,
            invalidated=invalidated_count,
            positions=positions,
        )

    except Exception as e:
        logger.exception(f"持仓证伪检查任务失败: {e}")
        return _failed_task_result(e)


@typed_shared_task(
    name="simulated.notify_invalidated_positions",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def notify_invalidated_positions_task(
    self: _BoundTaskProtocol,
) -> dict[str, Any]:
    """
    证伪持仓通知任务

    获取所有已证伪持仓的摘要，可用于通知或生成报告。

    建议执行时间：每个交易日 10:05（证伪检查后5分钟）

    Returns:
        证伪持仓摘要
    """
    logger.info("开始获取证伪持仓摘要")

    try:
        from apps.simulated_trading.application.position_invalidation_checker import (
            get_invalidated_positions_summary,
        )

        positions = get_invalidated_positions_summary()
        if type(positions) is not list:
            raise ValueError("invalidation summary returned malformed evidence")

        logger.info(f"已证伪持仓: {len(positions)} 个")

        for pos in positions:
            logger.info(
                f"  - {pos['account_name']}: {pos['asset_code']} ({pos['asset_name']})"
                f" | 数量: {pos['quantity']}"
                f" | 原因: {pos['invalidation_reason']}"
            )

        if not positions:
            return _task_result(
                outcome="noop",
                requested=0,
                succeeded=0,
                failed=0,
                stored=0,
                count=0,
                positions=[],
                notifications=[],
            )

        recipients = getattr(
            settings,
            "INVALIDATION_ALERT_RECIPIENTS",
            getattr(settings, "PERFORMANCE_SUMMARY_RECIPIENTS", []),
        )
        if type(recipients) is not list or any(
            type(recipient) is not str or not recipient for recipient in recipients
        ):
            raise ValueError("invalidation notification recipients are malformed")
        if not recipients:
            logger.info("未配置通知收件人，跳过邮件推送")
            return _task_result(
                outcome="blocked",
                requested=0,
                succeeded=0,
                failed=0,
                stored=0,
                compatible_success=True,
                count=len(positions),
                positions=positions,
                notifications=[],
                reason="notification_recipients_not_configured",
            )

        try:
            from shared.infrastructure.notification_service import (
                NotificationPriority,
                get_notification_service,
            )

            lines = [f"证伪持仓通知 ({date.today().isoformat()})", "=" * 40]
            for pos in positions:
                lines.append(
                    f"\n账户: {pos['account_name']}"
                    f"\n  标的: {pos['asset_code']} ({pos['asset_name']})"
                    f"\n  数量: {pos['quantity']}"
                    f"\n  原因: {pos['invalidation_reason']}"
                )
            results = get_notification_service().send_email(
                subject=f"[重要] 证伪持仓通知 - {len(positions)} 个持仓",
                body="\n".join(lines),
                recipients=recipients,
                priority=NotificationPriority.HIGH,
            )
            if type(results) is not list or len(results) != len(recipients):
                raise ValueError("invalidation notification evidence count mismatch")
            notification_results = [
                {"email": result.recipient.email, "success": result.success} for result in results
            ]
            if any(type(result["success"]) is not bool for result in notification_results):
                raise ValueError("invalidation notification evidence is malformed")
        except Exception as notify_err:
            logger.warning(f"证伪持仓邮件推送失败: {notify_err}")
            return _task_result(
                outcome="failed",
                requested=len(recipients),
                succeeded=0,
                failed=len(recipients),
                stored=0,
                count=len(positions),
                positions=positions,
                notifications=[],
                error=str(notify_err),
            )

        succeeded_count = sum(1 for result in notification_results if result["success"])
        failed_count = len(notification_results) - succeeded_count
        if succeeded_count and failed_count:
            outcome = "partial"
        elif failed_count:
            outcome = "failed"
        else:
            outcome = "success"
        return _task_result(
            outcome=outcome,
            requested=len(notification_results),
            succeeded=succeeded_count,
            failed=failed_count,
            stored=0,
            count=len(positions),
            positions=positions,
            notifications=notification_results,
        )

    except Exception as e:
        logger.exception(f"获取证伪持仓摘要失败: {e}")
        return _failed_task_result(e)


# ============================================================================
# 实时价格监控任务（集成 realtime 模块）
# ============================================================================


@typed_shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=600,
    soft_time_limit=570,
)
def update_all_prices_after_close(
    self: _BoundTaskProtocol,
    account_id: int | None = None,
) -> dict[str, Any]:
    """
    收盘后批量价格更新任务

    使用 realtime 模块的价格轮询服务，更新所有持仓资产的最新价格。
    建议执行时间：每个交易日 16:30（收盘后）

    Args:
        account_id: 指定账户ID（None表示全部账户）

    Returns:
        更新结果
    """
    try:
        validated_account_id = _validate_optional_id(account_id, "account_id")
    except (TypeError, ValueError) as exc:
        return _failed_task_result(exc)
    if validated_account_id is not None:
        return _task_result(
            outcome="blocked",
            requested=1,
            succeeded=0,
            failed=0,
            stored=0,
            account_id=validated_account_id,
            reason="account_scoped_realtime_polling_unavailable",
        )

    logger.info("=" * 60)
    logger.info("开始收盘后批量价格更新")
    logger.info("=" * 60)

    try:
        snapshot = execute_realtime_price_polling()
        if type(snapshot) is not dict:
            raise ValueError("realtime polling returned malformed evidence")
        total_assets = _require_non_negative_count(snapshot, "total_assets")
        success_count = _require_non_negative_count(snapshot, "success_count")
        failed_count = _require_non_negative_count(snapshot, "failed_count")
        if success_count + failed_count != total_assets:
            raise ValueError("realtime polling counters are inconsistent")

        logger.info("=" * 60)
        logger.info("收盘后批量价格更新完成")
        logger.info(f"  总资产数: {total_assets}")
        logger.info(f"  成功: {success_count}")
        logger.info(f"  失败: {failed_count}")
        logger.info(f"  成功率: {snapshot.get('success_rate', 0) * 100:.2f}%")
        logger.info("=" * 60)

        if total_assets == 0:
            outcome = "noop"
        elif success_count and failed_count:
            outcome = "partial"
        elif failed_count:
            outcome = "failed"
        else:
            outcome = "success"
        return _task_result(
            outcome=outcome,
            requested=total_assets,
            succeeded=success_count,
            failed=failed_count,
            stored=success_count,
            account_id=validated_account_id,
            snapshot=snapshot,
        )

    except Exception as e:
        logger.exception(f"收盘后价格更新任务失败: {e}")

        # 重试逻辑
        if self.request.retries < self.max_retries:
            try:
                raise self.retry(exc=e, countdown=60 * (2**self.request.retries))
            except Exception:
                logger.warning(f"任务将在 {2 ** self.request.retries} 分钟后重试")

        return _failed_task_result(e)


@typed_shared_task(name="apps.simulated_trading.application.tasks.update_position_prices_task")
def update_position_prices_task_alias(account_id: int | None = None) -> dict[str, Any]:
    """Backwards-compatible alias for beat entries using dotted task paths."""
    return update_position_prices_task.run(account_id=account_id)


@typed_shared_task(name="apps.simulated_trading.application.tasks.calculate_all_performance_task")
def calculate_all_performance_task_alias(trade_date: str | None = None) -> dict[str, Any]:
    """Backwards-compatible alias for beat entries using dotted task paths."""
    return calculate_all_performance_task.run(trade_date=trade_date)


@typed_shared_task(name="apps.simulated_trading.application.tasks.cleanup_inactive_accounts_task")
def cleanup_inactive_accounts_task_alias(inactive_days: int = 180) -> dict[str, Any]:
    """Backwards-compatible alias for beat entries using dotted task paths."""
    return cleanup_inactive_accounts_task.run(inactive_days=inactive_days)


@typed_shared_task(name="apps.simulated_trading.application.tasks.send_performance_summary_task")
def send_performance_summary_task_alias(
    account_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Backwards-compatible alias for beat entries using dotted task paths."""
    return send_performance_summary_task.run(account_ids=account_ids)


@typed_shared_task(name="apps.simulated_trading.application.tasks.check_position_invalidation_task")
def check_position_invalidation_task_alias() -> dict[str, Any]:
    """Backwards-compatible alias for beat entries using dotted task paths."""
    return check_position_invalidation_task.run()


@typed_shared_task(
    name="apps.simulated_trading.application.tasks.notify_invalidated_positions_task"
)
def notify_invalidated_positions_task_alias() -> dict[str, Any]:
    """Backwards-compatible alias for beat entries using dotted task paths."""
    return notify_invalidated_positions_task.run()
