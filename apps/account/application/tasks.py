"""
Account Application - Celery Tasks

定时任务：自动止损止盈检查、波动率控制。
"""

from celery import shared_task
from celery.utils.log import get_task_logger
from django.core.mail import send_mail
from django.conf import settings
from typing import Dict, List

from apps.account.application.stop_loss_use_cases import (
    AutoStopLossUseCase,
    AutoTakeProfitUseCase,
)
from apps.account.application.volatility_use_cases import (
    VolatilityAnalysisUseCase,
    VolatilityAdjustmentUseCase,
)

logger = get_task_logger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5分钟后重试
)
def check_stop_loss_task(self, user_id: int = None):
    """
    定时检查止损任务

    使用方法：
    - 每小时执行一次：检查所有激活的止损配置
    - 指定用户：只检查该用户的止损配置

    Args:
        user_id: 用户ID，None表示检查所有用户
    """
    try:
        use_case = AutoStopLossUseCase()
        results = use_case.check_and_execute_stop_loss(user_id=user_id)

        if results:
            logger.info(f"止损检查完成，共检查 {len(results)} 个持仓")

            # 发送通知（针对触发的止损）
            triggered_results = [r for r in results if r.should_close]
            if triggered_results:
                _send_stop_loss_notifications(triggered_results, user_id)

        return {
            'status': 'success',
            'checked_count': len(results),
            'triggered_count': len([r for r in results if r.should_close]),
        }

    except Exception as exc:
        logger.error(f"止损检查任务失败: {exc}")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def check_take_profit_task(self, user_id: int = None):
    """
    定时检查止盈任务

    Args:
        user_id: 用户ID，None表示检查所有用户
    """
    try:
        use_case = AutoTakeProfitUseCase()
        results = use_case.check_and_execute_take_profit(user_id=user_id)

        if results:
            logger.info(f"止盈检查完成，共检查 {len(results)} 个持仓")

            # 发送通知
            triggered_results = [r for r in results if r.should_close]
            if triggered_results:
                _send_take_profit_notifications(triggered_results, user_id)

        return {
            'status': 'success',
            'checked_count': len(results),
            'triggered_count': len([r for r in results if r.should_close]),
        }

    except Exception as exc:
        logger.error(f"止盈检查任务失败: {exc}")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def check_stop_loss_and_take_profit_task(self, user_id: int = None):
    """
    同时检查止损和止盈任务

    用于一次性检查所有持仓的止损止盈状态。

    Args:
        user_id: 用户ID，None表示检查所有用户
    """
    try:
        # 检查止损
        stop_loss_use_case = AutoStopLossUseCase()
        stop_loss_results = stop_loss_use_case.check_and_execute_stop_loss(user_id=user_id)

        # 检查止盈
        take_profit_use_case = AutoTakeProfitUseCase()
        take_profit_results = take_profit_use_case.check_and_execute_take_profit(user_id=user_id)

        total_triggered = (
            len([r for r in stop_loss_results if r.should_close]) +
            len([r for r in take_profit_results if r.should_close])
        )

        logger.info(f"止损止盈检查完成，触发 {total_triggered} 个")

        # 发送通知
        if total_triggered > 0:
            _send_stop_loss_notifications(
                [r for r in stop_loss_results if r.should_close],
                user_id
            )
            _send_take_profit_notifications(
                [r for r in take_profit_results if r.should_close],
                user_id
            )

        return {
            'status': 'success',
            'stop_loss_checked': len(stop_loss_results),
            'stop_loss_triggered': len([r for r in stop_loss_results if r.should_close]),
            'take_profit_checked': len(take_profit_results),
            'take_profit_triggered': len([r for r in take_profit_results if r.should_close]),
        }

    except Exception as exc:
        logger.error(f"止损止盈检查任务失败: {exc}")
        raise self.retry(exc=exc)


def _send_stop_loss_notifications(results: List, user_id: int = None):
    """
    发送止损触发通知

    Args:
        results: 止损检查结果列表
        user_id: 用户ID
    """
    for result in results:
        try:
            # 构建通知内容
            subject = f"【止损触发】{result.asset_code}"
            message = f"""
持仓 {result.asset_code} 触发止损平仓

触发原因: {result.check_result.trigger_reason}
当前价格: {result.current_price:.2f}
止损价格: {result.check_result.stop_price:.2f}
盈亏: {result.unrealized_pnl_pct:.2%}

请及时查看。
            """.strip()

            # 获取用户邮箱
            from apps.account.infrastructure.models import PositionModel
            position = PositionModel._default_manager.get(id=result.position_id)
            user_email = position.portfolio.user.email

            if user_email:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@agomsaaf.com'),
                    recipient_list=[user_email],
                    fail_silently=True,
                )
                logger.info(f"止损通知已发送至 {user_email}")

        except Exception as e:
            logger.error(f"发送止损通知失败: {e}")


def _send_take_profit_notifications(results: List, user_id: int = None):
    """
    发送止盈触发通知

    Args:
        results: 止盈检查结果列表
        user_id: 用户ID
    """
    for result in results:
        try:
            subject = f"【止盈触发】{result.asset_code}"
            partial_info = f" (分批 {result.partial_level})" if result.partial_level else ""

            message = f"""
持仓 {result.asset_code} 触发止盈平仓{partial_info}

触发原因: {result.check_result.trigger_reason}
当前价格: {result.current_price:.2f}
盈亏: {result.unrealized_pnl_pct:.2%}

请及时查看。
            """.strip()

            # 获取用户邮箱
            from apps.account.infrastructure.models import PositionModel
            position = PositionModel._default_manager.get(id=result.position_id)
            user_email = position.portfolio.user.email

            if user_email:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@agomsaaf.com'),
                    recipient_list=[user_email],
                    fail_silently=True,
                )
                logger.info(f"止盈通知已发送至 {user_email}")

        except Exception as e:
            logger.error(f"发送止盈通知失败: {e}")


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

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
)
def check_volatility_and_adjust_task(self, user_id: int = None):
    """
    检查波动率并自动调整仓位

    使用方法：
    - 每日执行一次：检查所有用户的投资组合波动率
    - 指定用户：只检查该用户的投资组合

    Args:
        user_id: 用户ID，None表示检查所有用户
    """
    try:
        from apps.account.infrastructure.models import PortfolioModel, AccountProfileModel

        # 获取需要检查的投资组合
        if user_id:
            portfolios = PortfolioModel._default_manager.filter(user_id=user_id, is_active=True)
        else:
            portfolios = PortfolioModel._default_manager.filter(is_active=True)

        adjusted_count = 0
        warning_count = 0

        for portfolio in portfolios:
            try:
                # 分析波动率
                analysis_use_case = VolatilityAnalysisUseCase()
                analysis = analysis_use_case.analyze_portfolio_volatility(
                    portfolio_id=portfolio.id,
                    user_id=portfolio.user_id,
                )

                # 如果需要调整，执行降仓
                if analysis.adjustment_result.should_reduce:
                    adjustment_use_case = VolatilityAdjustmentUseCase()
                    result = adjustment_use_case.execute_volatility_adjustment(
                        portfolio_id=portfolio.id,
                        user_id=portfolio.user_id,
                    )

                    if result['status'] == 'executed':
                        adjusted_count += 1
                        _send_volatility_adjustment_notification(
                            portfolio_id=portfolio.id,
                            user_id=portfolio.user_id,
                            analysis=analysis,
                            result=result,
                        )
                    logger.info(
                        f"投资组合 {portfolio.id} 波动率调整完成: "
                        f"{result['status']}"
                    )

                # 发送警告（如果波动率接近上限）
                elif analysis.adjustment_result.volatility_ratio > 1.0:
                    warning_count += 1
                    _send_volatility_warning_notification(
                        portfolio_id=portfolio.id,
                        user_id=portfolio.user_id,
                        analysis=analysis,
                    )

            except Exception as e:
                logger.error(f"处理投资组合 {portfolio.id} 波动率检查失败: {e}")
                continue

        logger.info(
            f"波动率检查完成，共检查 {len(portfolios)} 个组合，"
            f"调整 {adjusted_count} 个，警告 {warning_count} 个"
        )

        return {
            'status': 'success',
            'checked_count': len(portfolios),
            'adjusted_count': adjusted_count,
            'warning_count': warning_count,
        }

    except Exception as exc:
        logger.error(f"波动率检查任务失败: {exc}")
        raise self.retry(exc=exc)


def _send_volatility_adjustment_notification(
    portfolio_id: int,
    user_id: int,
    analysis,
    result: Dict,
):
    """
    发送波动率调整通知

    Args:
        portfolio_id: 投资组合ID
        user_id: 用户ID
        analysis: 波动率分析结果
        result: 调整结果
    """
    try:
        from apps.account.infrastructure.models import PortfolioModel

        portfolio = PortfolioModel._default_manager.get(id=portfolio_id)

        subject = f"【波动率控制】投资组合 {portfolio.name} 已降仓"

        message = f"""
您的投资组合 "{portfolio.name}" 因波动率超标已自动降仓

当前波动率（30天）: {analysis.current_volatility_30d:.2%}
目标波动率: {analysis.target_volatility:.2%}
波动率比率: {analysis.adjustment_result.volatility_ratio:.2f}x

调整原因: {analysis.adjustment_result.reduction_reason}

调整后仓位乘数: {result['position_multiplier']:.1%}
减少持仓数量: {len(result['reduced_positions'])}

请及时查看投资组合详情。
        """.strip()

        # 获取用户邮箱
        user_email = portfolio.user.email

        if user_email:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@agomsaaf.com'),
                recipient_list=[user_email],
                fail_silently=True,
            )
            logger.info(f"波动率调整通知已发送至 {user_email}")

    except Exception as e:
        logger.error(f"发送波动率调整通知失败: {e}")


def _send_volatility_warning_notification(
    portfolio_id: int,
    user_id: int,
    analysis,
):
    """
    发送波动率警告通知

    Args:
        portfolio_id: 投资组合ID
        user_id: 用户ID
        analysis: 波动率分析结果
    """
    try:
        from apps.account.infrastructure.models import PortfolioModel

        portfolio = PortfolioModel._default_manager.get(id=portfolio_id)

        subject = f"【波动率警告】投资组合 {portfolio.name} 波动率偏高"

        message = f"""
您的投资组合 "{portfolio.name}" 当前波动率偏高，请关注

当前波动率（30天）: {analysis.current_volatility_30d:.2%}
当前波动率（60天）: {analysis.current_volatility_60d:.2%}
当前波动率（90天）: {analysis.current_volatility_90d:.2%}
目标波动率: {analysis.target_volatility:.2%}
波动率比率: {analysis.adjustment_result.volatility_ratio:.2f}x

当前未触发自动降仓（容忍度内），但建议关注市场波动情况。

如需调整目标波动率配置，请登录系统设置。
        """.strip()

        # 获取用户邮箱
        user_email = portfolio.user.email

        if user_email:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@agomsaaf.com'),
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


