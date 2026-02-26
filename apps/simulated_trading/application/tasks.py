"""
模拟盘交易 Celery 任务

Application层异步任务：
- 每日自动交易执行
- 持仓价格更新
- 绩效定期重算
"""
import logging
from datetime import date, datetime
from typing import Dict, Any, Optional
from dataclasses import replace

from celery import shared_task
from celery.schedules import crontab
from django.conf import settings
from django.core.mail import send_mail

from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.performance_calculator import PerformanceCalculator
from apps.simulated_trading.application.use_cases import (
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
    GetAccountPerformanceUseCase,
)
from apps.simulated_trading.infrastructure.repositories import (
    DjangoSimulatedAccountRepository,
    DjangoPositionRepository,
    DjangoTradeRepository,
)
from apps.simulated_trading.infrastructure.market_data_provider import MarketDataProvider
from apps.simulated_trading.application.asset_pool_query_service import AssetPoolQueryService
from apps.simulated_trading.application.daily_inspection_service import DailyInspectionService
from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    DailyInspectionNotificationConfigModel,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 核心定时任务
# ============================================================================

@shared_task(bind=True, max_retries=3)
def daily_auto_trading_task(
    self,
    trade_date: Optional[str] = None,
    account_ids: Optional[list] = None,
) -> Dict[str, Any]:
    """
    每日自动交易任务

    Celery Beat 配置建议：
    - 执行时间：每个交易日 15:30（收盘后）
    - crontab: hour=15, minute=30, day_of_week='mon-fri'

    Args:
        trade_date: 交易日期（YYYY-MM-DD，默认今天）
        account_ids: 指定账户ID列表（None表示全部活跃账户）

    Returns:
        任务结果字典
    """
    # 1. 确定交易日期
    target_date = date.fromisoformat(trade_date) if trade_date else date.today()

    logger.info(f"=" * 60)
    logger.info(f"模拟盘自动交易任务开始: {target_date}")
    logger.info(f"=" * 60)

    try:
        # 2. 初始化依赖
        account_repo = DjangoSimulatedAccountRepository()
        position_repo = DjangoPositionRepository()
        trade_repo = DjangoTradeRepository()

        buy_use_case = ExecuteBuyOrderUseCase(account_repo, position_repo, trade_repo)
        sell_use_case = ExecuteSellOrderUseCase(account_repo, position_repo, trade_repo)
        performance_use_case = GetAccountPerformanceUseCase(account_repo, position_repo, trade_repo)

        market_data = MarketDataProvider(cache_ttl_minutes=60)  # 1小时缓存
        asset_pool_service = AssetPoolQueryService()

        # 3. 创建引擎
        engine = AutoTradingEngine(
            account_repo=account_repo,
            position_repo=position_repo,
            trade_repo=trade_repo,
            buy_use_case=buy_use_case,
            sell_use_case=sell_use_case,
            performance_use_case=performance_use_case,
            asset_pool_service=asset_pool_service,
            market_data_provider=market_data,
        )

        # 4. 执行交易
        results = engine.run_daily_trading(target_date)

        # 5. 汇总统计
        total_accounts = len(results)
        total_buy_count = sum(r['buy_count'] for r in results.values())
        total_sell_count = sum(r['sell_count'] for r in results.values())

        logger.info(f"=" * 60)
        logger.info(f"模拟盘自动交易任务完成")
        logger.info(f"  处理账户: {total_accounts} 个")
        logger.info(f"  总买入: {total_buy_count} 笔")
        logger.info(f"  总卖出: {total_sell_count} 笔")
        logger.info(f"=" * 60)

        return {
            'success': True,
            'trade_date': target_date.isoformat(),
            'total_accounts': total_accounts,
            'results': results,
            'summary': {
                'total_buy_count': total_buy_count,
                'total_sell_count': total_sell_count,
            }
        }

    except Exception as e:
        logger.exception(f"自动交易任务执行失败: {e}")

        # 重试逻辑
        if self.request.retries < self.max_retries:
            try:
                raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
            except Exception as retry_error:
                logger.warning(f"任务将在 {2 ** self.request.retries} 分钟后重试")

        return {
            'success': False,
            'trade_date': target_date.isoformat(),
            'error': str(e),
        }


@shared_task
def update_position_prices_task(account_id: Optional[int] = None) -> Dict[str, Any]:
    """
    更新持仓价格任务

    每日收盘后更新所有持仓的当前价格，用于计算浮盈浮亏。

    建议执行时间：每个交易日 16:00（收盘后30分钟）

    Args:
        account_id: 指定账户ID（None表示全部账户）

    Returns:
        更新结果
    """
    logger.info(f"开始更新持仓价格: account_id={account_id}")

    try:
        account_repo = DjangoSimulatedAccountRepository()
        position_repo = DjangoPositionRepository()
        market_data = MarketDataProvider()

        # 获取账户列表
        if account_id:
            accounts = [account_repo.get_by_id(account_id)]
            if not accounts[0]:
                return {'success': False, 'error': f'账户不存在: {account_id}'}
        else:
            accounts = account_repo.get_active_accounts()

        updated_count = 0
        error_count = 0

        for account in accounts:
            positions = position_repo.get_by_account(account.account_id)

            for position in positions:
                try:
                    # 获取最新价格
                    current_price = market_data.get_latest_price(position.asset_code)

                    if current_price is None:
                        logger.warning(f"无法获取 {position.asset_code} 价格，跳过")
                        error_count += 1
                        continue

                    # 更新持仓价格和市值
                    from apps.simulated_trading.domain.entities import Position
                    updated_position = Position(
                        position_id=position.position_id,
                        account_id=position.account_id,
                        asset_code=position.asset_code,
                        asset_name=position.asset_name,
                        asset_type=position.asset_type,
                        quantity=position.quantity,
                        available_quantity=position.available_quantity,
                        avg_cost=position.avg_cost,
                        total_cost=position.total_cost,
                        current_price=current_price,
                        market_value=position.quantity * current_price,
                        unrealized_pnl=(current_price - position.avg_cost) * position.quantity,
                        unrealized_pnl_pct=((current_price - position.avg_cost) / position.avg_cost) * 100
                        if position.avg_cost > 0 else 0.0,
                        first_buy_date=position.first_buy_date,
                        last_update_date=date.today(),
                        signal_id=position.signal_id,
                        entry_reason=position.entry_reason,
                    )
                    position_repo.save(updated_position)
                    updated_count += 1

                except Exception as e:
                    logger.error(f"更新持仓 {position.asset_code} 失败: {e}")
                    error_count += 1

            # 更新账户总市值
            positions = position_repo.get_by_account(account.account_id)
            total_market_value = sum(p.market_value for p in positions)
            updated_account = replace(
                account,
                current_market_value=total_market_value,
                total_value=account.current_cash + total_market_value
            )
            account_repo.save(updated_account)

        logger.info(f"持仓价格更新完成: {updated_count} 个成功, {error_count} 个失败")

        return {
            'success': True,
            'updated_count': updated_count,
            'error_count': error_count,
        }

    except Exception as e:
        logger.exception(f"更新持仓价格任务失败: {e}")
        return {
            'success': False,
            'error': str(e),
        }


@shared_task
def calculate_all_performance_task(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """
    全量绩效计算任务

    重新计算所有活跃账户的绩效指标。

    建议执行时间：每周日凌晨 2:00

    Args:
        trade_date: 计算日期（默认今天）

    Returns:
        计算结果
    """
    target_date = date.fromisoformat(trade_date) if trade_date else date.today()

    logger.info(f"开始全量绩效计算: {target_date}")

    try:
        calculator = PerformanceCalculator()
        account_repo = DjangoSimulatedAccountRepository()
        accounts = account_repo.get_active_accounts()

        results = []
        for account in accounts:
            try:
                metrics = calculator.calculate_and_update_performance(
                    account_id=account.account_id,
                    trade_date=target_date
                )
                results.append({
                    'account_id': account.account_id,
                    'account_name': account.account_name,
                    'total_return': metrics.get('total_return', 0.0),
                    'sharpe_ratio': metrics.get('sharpe_ratio', 0.0),
                    'max_drawdown': metrics.get('max_drawdown', 0.0),
                    'win_rate': metrics.get('win_rate', 0.0),
                })
            except Exception as e:
                logger.error(f"计算账户 {account.account_id} 绩效失败: {e}")

        logger.info(f"全量绩效计算完成: {len(results)} 个账户")

        return {
            'success': True,
            'trade_date': target_date.isoformat(),
            'account_count': len(results),
            'results': results,
        }

    except Exception as e:
        logger.exception(f"全量绩效计算任务失败: {e}")
        return {
            'success': False,
            'error': str(e),
        }


# ============================================================================
# 维护任务
# ============================================================================

@shared_task
def cleanup_inactive_accounts_task(inactive_days: int = 180) -> Dict[str, Any]:
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

    logger.info(f"开始清理不活跃账户: {inactive_days} 天无交易")

    try:
        account_repo = DjangoSimulatedAccountRepository()
        cutoff_date = date.today() - timedelta(days=inactive_days)

        accounts = account_repo.get_active_accounts()
        deactivated_count = 0

        for account in accounts:
            # 检查最后交易日期
            if account.last_trade_date and account.last_trade_date < cutoff_date:
                # 停用账户
                updated_account = replace(
                    account,
                    is_active=False,
                    auto_trading_enabled=False
                )
                account_repo.save(updated_account)
                deactivated_count += 1
                logger.info(f"停用不活跃账户: {account.account_name} (最后交易: {account.last_trade_date})")

        logger.info(f"清理完成: {deactivated_count} 个账户被停用")

        return {
            'success': True,
            'deactivated_count': deactivated_count,
        }

    except Exception as e:
        logger.exception(f"清理不活跃账户任务失败: {e}")
        return {
            'success': False,
            'error': str(e),
        }


@shared_task
def send_performance_summary_task(account_ids: Optional[list] = None) -> Dict[str, Any]:
    """
    发送绩效摘要任务

    生成并发送账户绩效摘要（可集成邮件/消息推送）。

    建议执行时间：每个交易日 17:00

    Args:
        account_ids: 指定账户ID列表（None表示全部活跃账户）

    Returns:
        发送结果
    """
    logger.info(f"开始生成绩效摘要")

    try:
        account_repo = DjangoSimulatedAccountRepository()
        position_repo = DjangoPositionRepository()
        trade_repo = DjangoTradeRepository()

        # 获取账户列表
        if account_ids:
            accounts = []
            for acc_id in account_ids:
                acc = account_repo.get_by_id(acc_id)
                if acc:
                    accounts.append(acc)
        else:
            accounts = account_repo.get_active_accounts()

        # 生成摘要
        use_case = GetAccountPerformanceUseCase(account_repo, position_repo, trade_repo)
        summaries = []

        for account in accounts:
            result = use_case.execute(account.account_id)
            summaries.append({
                'account_id': account.account_id,
                'account_name': account.account_name,
                'total_value': float(account.total_value),
                'total_return': result['performance'].get('total_return', 0.0),
                'max_drawdown': result['performance'].get('max_drawdown', 0.0),
                'sharpe_ratio': result['performance'].get('sharpe_ratio', 0.0),
                'win_rate': result['performance'].get('win_rate', 0.0),
                'total_trades': result['total_trades'],
                'total_positions': result['total_positions'],
            })

        logger.info(f"绩效摘要生成完成: {len(summaries)} 个账户")

        # TODO: 实现邮件/消息推送
        # 目前只记录日志，实际部署时需要集成邮件服务

        return {
            'success': True,
            'summaries': summaries,
        }

    except Exception as e:
        logger.exception(f"发送绩效摘要任务失败: {e}")
        return {
            'success': False,
            'error': str(e),
        }


@shared_task(name="simulated.daily_portfolio_inspection")
def daily_portfolio_inspection_task(
    account_id: int = 679,
    strategy_id: Optional[int] = 4,
    inspection_date: Optional[str] = None,
    auto_create_proposal: bool = True,
) -> Dict[str, Any]:
    """
    日更巡检任务（ETF稳健组合）

    默认巡检账户 679，自动读取策略 4 及其仓位规则。
    可选择是否自动创建再平衡建议草案。

    Args:
        account_id: 账户ID
        strategy_id: 策略ID
        inspection_date: 巡检日期
        auto_create_proposal: 是否自动创建再平衡建议
    """
    target_date = date.fromisoformat(inspection_date) if inspection_date else date.today()
    logger.info(
        "开始执行日更巡检: account_id=%s, strategy_id=%s, date=%s, auto_proposal=%s",
        account_id,
        strategy_id,
        target_date,
        auto_create_proposal,
    )
    try:
        # 使用新方法运行巡检并可能创建再平衡建议
        result = DailyInspectionService.run_and_create_proposal(
            account_id=account_id,
            inspection_date=target_date,
            strategy_id=strategy_id,
            auto_create_proposal=auto_create_proposal,
        )

        # 发送巡检邮件通知
        _send_daily_inspection_email(result=result)

        # 如果创建了再平衡建议，发送额外通知
        if result.get("proposal_created"):
            _send_rebalance_proposal_notification(result=result)
            logger.info(
                "已创建再平衡建议: account_id=%s, proposal_id=%s",
                account_id,
                result["proposal_id"],
            )

        logger.info(
            "日更巡检完成: account_id=%s, report_id=%s, status=%s, proposal_id=%s",
            account_id,
            result["report_id"],
            result["status"],
            result.get("proposal_id"),
        )
        return {"success": True, **result}
    except SimulatedAccountModel.DoesNotExist:
        return {
            "success": False,
            "error": f"账户不存在: {account_id}",
            "account_id": account_id,
            "inspection_date": target_date.isoformat(),
        }
    except Exception as exc:  # pragma: no cover - celery runtime guard
        logger.exception("日更巡检任务失败: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "account_id": account_id,
            "inspection_date": target_date.isoformat(),
        }


def _send_daily_inspection_email(result: Dict[str, Any]) -> None:
    """发送巡检邮件通知（配置来自数据库）。"""
    if not getattr(settings, "DAILY_INSPECTION_EMAIL_ENABLED", True):
        return

    account = SimulatedAccountModel._default_manager.filter(id=result["account_id"]).select_related("user").first()
    if not account:
        return

    config, _ = DailyInspectionNotificationConfigModel._default_manager.get_or_create(
        account=account
    )
    if not config.is_enabled:
        return

    status_value = str(result.get("status", "ok")).lower()
    notify_on = {"ok", "warning", "error"} if config.notify_on == "all" else {"warning", "error"}
    if status_value not in notify_on:
        return

    recipients: list[str] = []
    if config.include_owner_email and account.user and account.user.email:
        recipients.append(account.user.email)

    recipients.extend([str(x).strip() for x in (config.recipient_emails or []) if str(x).strip()])

    recipients = sorted(set(recipients))
    if not recipients:
        logger.warning("巡检邮件未发送：无收件人配置 account_id=%s", result.get("account_id"))
        return

    summary = result.get("summary", {})
    checks = result.get("checks", [])
    subject = (
        f"[AgomSAAF] 日更巡检 {status_value.upper()} "
        f"account={result.get('account_id')} date={result.get('inspection_date')}"
    )
    lines = [
        f"account_id: {result.get('account_id')}",
        f"inspection_date: {result.get('inspection_date')}",
        f"status: {result.get('status')}",
        f"macro_regime: {result.get('macro_regime')}",
        f"policy_gear: {result.get('policy_gear')}",
        f"strategy_id: {result.get('strategy_id')}",
        f"position_rule_id: {result.get('position_rule_id')}",
        "",
        "summary:",
        f"- positions_count: {summary.get('positions_count')}",
        f"- rebalance_required_count: {summary.get('rebalance_required_count')}",
        f"- rebalance_assets: {summary.get('rebalance_assets')}",
        f"- total_value: {summary.get('total_value')}",
        f"- current_cash: {summary.get('current_cash')}",
        "",
        "checks(top 10):",
    ]
    for item in checks[:10]:
        lines.append(
            f"- {item.get('asset_code')}: weight={item.get('weight')}, "
            f"target={item.get('target_weight')}, drift={item.get('drift')}, "
            f"action={item.get('rebalance_action')}, qty_suggest={item.get('rebalance_qty_suggest')}"
        )

    send_mail(
        subject=subject,
        message="\n".join(lines),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@agomsaaf.com"),
        recipient_list=recipients,
        fail_silently=True,
    )
    logger.info("巡检邮件已发送: account_id=%s recipients=%s", result.get("account_id"), recipients)


def _send_rebalance_proposal_notification(result: Dict[str, Any]) -> None:
    """发送再平衡建议通知（邮件 + 站内）。"""
    if not result.get("proposal_id"):
        return

    account_id = result.get("account_id")
    proposal_id = result["proposal_id"]
    summary = result.get("summary", {})

    account = SimulatedAccountModel._default_manager.filter(id=account_id).select_related("user").first()
    if not account:
        logger.warning("无法发送再平衡建议通知：账户不存在 account_id=%s", account_id)
        return

    # 获取再平衡建议详情
    from apps.simulated_trading.infrastructure.models import RebalanceProposalModel
    proposal = RebalanceProposalModel._default_manager.filter(id=proposal_id).first()
    if not proposal:
        logger.warning("无法发送再平衡建议通知：建议不存在 proposal_id=%s", proposal_id)
        return

    # 获取通知配置
    config, _ = DailyInspectionNotificationConfigModel._default_manager.get_or_create(
        account=account
    )

    if not config.is_enabled:
        return

    # 收集收件人邮箱
    recipients: list[str] = []
    if config.include_owner_email and account.user and account.user.email:
        recipients.append(account.user.email)

    recipients.extend([str(x).strip() for x in (config.recipient_emails or []) if str(x).strip()])
    recipients = sorted(set(recipients))

    # 发送邮件通知
    if recipients:
        subject = (
            f"[AgomSAAF] 再平衡建议待审核 "
            f"account={account.account_name} proposal_id={proposal_id}"
        )
        lines = [
            f"账户: {account.account_name} (ID: {account_id})",
            f"建议ID: {proposal_id}",
            f"巡检日期: {result.get('inspection_date')}",
            f"优先级: {proposal.get_priority_display()}",
            f"状态: {proposal.get_status_display()}",
            "",
            "再平衡摘要:",
            f"- 需要调整的资产数: {summary.get('rebalance_required_count', 0)}",
            f"- 买入操作: {len([p for p in proposal.proposals if p['action'] == 'buy'])}",
            f"- 卖出操作: {len([p for p in proposal.proposals if p['action'] == 'sell'])}",
            f"- 预计交易金额: {sum(p.get('estimated_amount', 0) for p in proposal.proposals):.2f} 元",
            "",
            "调整明细:",
        ]

        for item in proposal.proposals[:10]:
            action_emoji = "🔴" if item["action"] == "sell" else "🟢"
            lines.append(
                f"{action_emoji} {item['asset_code']} ({item['asset_name']}): "
                f"{item['action']} {item['suggested_quantity']} 股, "
                f"金额约 {item['estimated_amount']:.2f} 元"
            )

        if len(proposal.proposals) > 10:
            lines.append(f"... 还有 {len(proposal.proposals) - 10} 个资产")

        lines.extend([
            "",
            f"原因: {proposal.source_description}",
            "",
            "请登录系统审核并执行此再平衡建议。",
            "-" * 50,
        ])

        send_mail(
            subject=subject,
            message="\n".join(lines),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@agomsaaf.com"),
            recipient_list=recipients,
            fail_silently=True,
        )
        logger.info("再平衡建议邮件已发送: proposal_id=%s recipients=%s", proposal_id, recipients)

    # 创建站内通知（如果用户存在）
    if account.user:
        from shared.infrastructure.notification_service import (
            InAppNotificationChannel,
            NotificationMessage,
            NotificationRecipient,
            NotificationPriority,
        )

        try:
            channel = InAppNotificationChannel()
            message = NotificationMessage(
                subject="再平衡建议待审核",
                body=f"账户 {account.account_name} 的日更巡检发现了 {summary.get('rebalance_required_count', 0)} 个需要调整的资产，请审核再平衡建议 #{proposal_id}。",
                priority=NotificationPriority.HIGH,
                metadata={
                    "proposal_id": proposal_id,
                    "account_id": account_id,
                    "inspection_date": result.get("inspection_date"),
                },
                tags=["rebalance", "daily_inspection"],
            )

            recipient = NotificationRecipient(user_id=account.user.id)
            result_notify = channel.send(message, recipient, NotificationConfig())

            if result_notify.success:
                logger.info("站内通知已发送: user_id=%s proposal_id=%s", account.user.id, proposal_id)
            else:
                logger.warning("站内通知发送失败: %s", result_notify.error_message)

        except Exception as e:
            logger.warning("创建站内通知失败: %s", e)

    # 记录通知历史
    _record_notification_history(
        account=account,
        proposal=proposal,
        notification_type="rebalance_proposal",
        recipients=recipients,
        status="sent" if recipients else "skipped",
    )


def _record_notification_history(
    account: SimulatedAccountModel,
    proposal: Any,
    notification_type: str,
    recipients: list[str],
    status: str,
) -> None:
    """记录通知历史"""
    from apps.simulated_trading.infrastructure.models import NotificationHistoryModel

    try:
        # 为每个收件人创建记录
        for email in recipients:
            NotificationHistoryModel._default_manager.create(
                account=account,
                rebalance_proposal=proposal,
                notification_type=notification_type,
                channel="email",
                recipient_user_id=account.user.id if account.user else None,
                recipient_email=email,
                subject=f"再平衡建议待审核 #{proposal.id}",
                body=f"账户 {account.account_name} 的再平衡建议需要审核。",
                status=status,
            )

        logger.debug("通知历史已记录: account_id=%s type=%s", account.id, notification_type)

    except Exception as e:
        logger.warning("记录通知历史失败: %s", e)


class NotificationConfig:
    """通知配置（用于 notification_service）"""
    max_retries = 3
    initial_retry_delay = 1.0
    retry_backoff_factor = 2.0
    max_retry_delay = 60.0
    timeout_seconds = 30
    enable_retry = True
    enable_alert_on_failure = True
    alert_threshold = 3


# ============================================================================
# 持仓证伪检查任务
# ============================================================================

@shared_task
def check_position_invalidation_task() -> Dict[str, Any]:
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
            get_invalidated_positions_summary
        )

        # 检查并证伪满足条件的持仓
        result = check_and_invalidate_positions()

        logger.info(f"证伪检查完成:")
        logger.info(f"  检查持仓: {result['checked']} 个")
        logger.info(f"  证伪数量: {result['invalidated']} 个")

        # 如果有新的证伪持仓，记录详细信息
        if result['invalidated'] > 0:
            logger.warning(f"新证伪持仓列表:")
            for pos in result['positions']:
                logger.warning(
                    f"  - 账户 {pos['account_id']}: {pos['asset_code']} ({pos['asset_name']})"
                    f" | 原因: {pos['reason']}"
                )

        logger.info("=" * 60)

        return {
            'success': True,
            'checked': result['checked'],
            'invalidated': result['invalidated'],
            'positions': result['positions'],
        }

    except Exception as e:
        logger.exception(f"持仓证伪检查任务失败: {e}")
        return {
            'success': False,
            'error': str(e),
        }


@shared_task
def notify_invalidated_positions_task() -> Dict[str, Any]:
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
            get_invalidated_positions_summary
        )

        positions = get_invalidated_positions_summary()

        logger.info(f"已证伪持仓: {len(positions)} 个")

        for pos in positions:
            logger.info(
                f"  - {pos['account_name']}: {pos['asset_code']} ({pos['asset_name']})"
                f" | 数量: {pos['quantity']}"
                f" | 原因: {pos['invalidation_reason']}"
            )

        # TODO: 实现通知功能（邮件/消息推送）
        # 目前只记录日志

        return {
            'success': True,
            'count': len(positions),
            'positions': positions,
        }

    except Exception as e:
        logger.exception(f"获取证伪持仓摘要失败: {e}")
        return {
            'success': False,
            'error': str(e),
        }


# ============================================================================
# 实时价格监控任务（集成 realtime 模块）
# ============================================================================

@shared_task(bind=True, max_retries=3)
def update_all_prices_after_close(self, account_id: Optional[int] = None) -> Dict[str, Any]:
    """
    收盘后批量价格更新任务

    使用 realtime 模块的价格轮询服务，更新所有持仓资产的最新价格。
    建议执行时间：每个交易日 16:30（收盘后）

    Args:
        account_id: 指定账户ID（None表示全部账户）

    Returns:
        更新结果
    """
    logger.info("=" * 60)
    logger.info("开始收盘后批量价格更新")
    logger.info("=" * 60)

    try:
        from apps.realtime.application.price_polling_service import PricePollingUseCase

        # 创建价格轮询用例
        use_case = PricePollingUseCase()

        # 执行价格轮询
        snapshot = use_case.execute_price_polling()

        logger.info("=" * 60)
        logger.info("收盘后批量价格更新完成")
        logger.info(f"  总资产数: {snapshot['total_assets']}")
        logger.info(f"  成功: {snapshot['success_count']}")
        logger.info(f"  失败: {snapshot['failed_count']}")
        logger.info(f"  成功率: {snapshot.get('success_rate', 0) * 100:.2f}%")
        logger.info("=" * 60)

        return {
            'success': True,
            'snapshot': snapshot
        }

    except Exception as e:
        logger.exception(f"收盘后价格更新任务失败: {e}")

        # 重试逻辑
        if self.request.retries < self.max_retries:
            try:
                raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
            except Exception as retry_error:
                logger.warning(f"任务将在 {2 ** self.request.retries} 分钟后重试")

        return {
            'success': False,
            'error': str(e),
        }
