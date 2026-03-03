"""
证伪检查服务

Application 层：编排 Domain 层业务逻辑和 Infrastructure 层数据获取。

架构说明：
- Domain 层：evaluate_rule() 纯函数评估证伪规则
- Infrastructure 层：获取指标数据
- Application 层：编排两者，提供检查服务
"""

import logging
import importlib
from datetime import datetime
from typing import Dict, List, Optional, Protocol, Any

from django.utils import timezone

logger = logging.getLogger(__name__)

from apps.signal.domain.invalidation import (
    InvalidationRule,
    InvalidationCheckResult,
    IndicatorValue,
    evaluate_rule,
)
from apps.signal.domain.entities import InvestmentSignal, SignalStatus
from apps.signal.domain.interfaces import (
    InvestmentSignalRepositoryProtocol,
    UserRepositoryProtocol,
)


class InvestmentSignalModel:  # backward-compatible test patch target
    pass


def _resolve_investment_signal_model():
    """Lazy-load ORM model to avoid static infrastructure import in Application layer."""
    if InvestmentSignalModel is not None and hasattr(InvestmentSignalModel, "_default_manager"):
        return InvestmentSignalModel
    return importlib.import_module("apps.signal.infrastructure.models").InvestmentSignalModel


class NotificationServiceProtocol(Protocol):
    """Protocol for notification service"""

    def send_email(
        self,
        subject: str,
        body: str,
        recipients: List[str],
        html_body: Optional[str] = None,
        priority: Any = None,
    ) -> List[Any]:
        """Send email notification"""
        ...


class InvalidationCheckService:
    """证伪检查服务

    负责检查投资信号的证伪条件，并在满足条件时更新信号状态。
    """

    def __init__(
        self,
        signal_repository: Optional[InvestmentSignalRepositoryProtocol] = None,
        user_repository: Optional[UserRepositoryProtocol] = None,
        notification_service: Optional[NotificationServiceProtocol] = None,
        macro_repository: Optional[Any] = None,
    ):
        """初始化服务

        Args:
            signal_repository: 信号仓储实例（可选，默认自动创建）
            user_repository: 用户仓储实例（可选，用于获取通知收件人）
            notification_service: 通知服务实例（可选）
            macro_repository: 宏观数据仓储实例（可选，延迟加载）
        """
        if signal_repository is None:
            from apps.signal.infrastructure.repositories import DjangoSignalRepository
            signal_repository = DjangoSignalRepository()

        self.signal_repository = signal_repository
        self.user_repository = user_repository
        self.notification_service = notification_service

        # 延迟加载 macro_repository（避免循环依赖）
        if macro_repository is not None:
            self.macro_repo = macro_repository
        else:
            from apps.macro.infrastructure.repositories import DjangoMacroRepository
            self.macro_repo = DjangoMacroRepository()

    def check_signal(self, signal_id: int) -> Optional[InvalidationCheckResult]:
        """检查单个信号的证伪状态

        Args:
            signal_id: 信号ID

        Returns:
            InvalidationCheckResult 或 None（如果信号不存在或无需检查）
        """
        signal = self.signal_repository.get_by_id(str(signal_id))
        if signal is None:
            return None

        return self._check_signal_entity(signal)

    def _check_signal_model(self, signal_model: Any) -> Optional[InvalidationCheckResult]:
        """Backward-compatible wrapper for legacy callers/tests using ORM models."""
        if not hasattr(signal_model, "to_domain_entity"):
            return None

        entity = signal_model.to_domain_entity()

        if not entity.invalidation_rule:
            return None

        if entity.status.value in ("rejected", "expired"):
            return None

        indicator_values = self._fetch_indicator_values(entity.invalidation_rule)
        result = evaluate_rule(entity.invalidation_rule, indicator_values)

        if result.is_invalidated:
            self._invalidate_signal(signal_model, result, current_status=entity.status.value)

        return result

    def _check_signal_entity(self, signal: InvestmentSignal) -> Optional[InvalidationCheckResult]:
        """检查信号实体的证伪状态

        Args:
            signal: InvestmentSignal 实体

        Returns:
            InvalidationCheckResult 或 None
        """
        # 检查是否有证伪规则
        if not signal.invalidation_rule:
            return None

        # 对于非批准状态，也需要检查证伪条件
        # 如果 pending 信号的证伪条件已满足，应该标记为 rejected
        # rejected 或 expired 状态的信号不需要检查
        if signal.status.value in ('rejected', 'expired'):
            return None

        # 获取指标值
        indicator_values = self._fetch_indicator_values(signal.invalidation_rule)

        # 评估规则（Domain 层纯函数）
        result = evaluate_rule(signal.invalidation_rule, indicator_values)

        # 如果证伪，更新信号状态
        if result.is_invalidated:
            self._invalidate_signal(signal, result)

        return result

    def _fetch_indicator_values(self, rule: InvalidationRule) -> Dict[str, IndicatorValue]:
        """获取规则中所有指标的当前值

        Args:
            rule: 证伪规则

        Returns:
            Dict[str, IndicatorValue]: 指标值字典
        """
        values = {}

        for condition in rule.conditions:
            code = condition.indicator_code

            # 避免重复获取
            if code in values:
                continue

            # 从数据库获取指标数据
            try:
                latest = self.macro_repo.get_latest_by_code(code)
                if latest:
                    history = self.macro_repo.get_history_by_code(code, periods=12)
                    values[code] = IndicatorValue(
                        code=code,
                        current_value=latest.value,
                        history_values=[d.value for d in history],
                        unit=latest.unit or "",
                        last_updated=latest.observed_at.isoformat() if latest.observed_at else None,
                    )
                else:
                    values[code] = IndicatorValue(
                        code=code,
                        current_value=None,
                        history_values=[],
                        unit="",
                        last_updated=None,
                    )
            except Exception:
                # 获取失败，使用空值
                values[code] = IndicatorValue(
                    code=code,
                    current_value=None,
                    history_values=[],
                    unit="",
                    last_updated=None,
                )

        return values

    def _invalidate_signal(
        self,
        signal: Any,
        result: InvalidationCheckResult,
        current_status: Optional[str] = None,
    ):
        """标记信号为已证伪或已拒绝

        Args:
            signal: 信号实体或 ORM 模型（兼容旧调用）
            result: 证伪检查结果
            current_status: 兼容旧调用的状态参数
        """
        # Legacy path for old callers/tests passing ORM model directly.
        if hasattr(signal, "save") and not isinstance(signal, InvestmentSignal):
            status = current_status or getattr(signal, "status", "")
            details = {
                'reason': result.reason,
                'checked_conditions': result.checked_conditions,
            }
            if status == 'pending':
                signal.status = 'rejected'
            else:
                signal.status = 'invalidated'
                signal.invalidated_at = timezone.now()
            signal.invalidation_details = details
            signal.rejection_reason = result.reason
            signal.save()
            return

        details = {
            'reason': result.reason,
            'checked_conditions': result.checked_conditions,
        }

        # pending 状态的信号证伪条件满足时，应标记为 rejected
        # approved 状态的信号证伪条件满足时，应标记为 invalidated
        if signal.status == SignalStatus.PENDING:
            success = self.signal_repository.mark_rejected(
                signal_id=signal.id,
                reason=result.reason,
            )
            logger.info(
                f"Pending 信号 #{signal.id} ({signal.asset_code}) "
                f"因证伪条件满足而被拒绝: {result.reason}"
            )
        else:  # approved
            success = self.signal_repository.mark_invalidated(
                signal_id=signal.id,
                reason=result.reason,
                details=details,
            )
            logger.info(
                f"Approved 信号 #{signal.id} ({signal.asset_code}) "
                f"已被证伪: {result.reason}"
            )

            # 发送证伪通知（仅对已批准的信号）
            self._send_invalidation_notification(signal, result)

    def _send_invalidation_notification(
        self,
        signal: InvestmentSignal,
        result: InvalidationCheckResult
    ):
        """
        发送信号证伪通知

        Args:
            signal: 已证伪的信号
            result: 证伪检查结果
        """
        try:
            from shared.infrastructure.notification_service import (
                get_notification_service,
                NotificationPriority,
            )

            # 如果没有注入通知服务，使用默认的
            if self.notification_service is None:
                self.notification_service = get_notification_service()

            # 获取通知收件人
            recipients = self._get_signal_recipients(signal)

            if not recipients:
                logger.debug(f"信号 #{signal.id} 没有通知收件人，跳过发送")
                return

            # 构建通知内容
            status_text = "已证伪" if signal.status == SignalStatus.INVALIDATED else "已拒绝"
            subject = f"[AgomSAAF] 信号{status_text}: {signal.asset_code}"

            # 构建详情
            condition_details = []
            for cond in result.checked_conditions:
                status = "Y" if cond.is_met else "N"
                condition_details.append(
                    f"{status} {cond.description}: "
                    f"当前值={cond.actual_value}, 阈值={cond.threshold}"
                )

            body_lines = [
                f"# 投资信号{status_text}通知",
                f"",
                f"## 信号信息",
                f"- **资产代码**: {signal.asset_code}",
                f"- **逻辑描述**: {signal.logic_desc or 'N/A'}",
                f"- **状态**: {signal.status.value}",
                f"- **证伪时间**: {timezone.now()}",
                f"",
                f"## 证伪原因",
                f"{result.reason}",
                f"",
                f"## 条件详情",
            ]
            body_lines.extend(condition_details)
            body_lines.extend([
                f"",
                f"## 原始投资逻辑",
                f"{signal.invalidation_description or 'N/A'}",
                f"",
                f"---",
                f"请登录系统查看详情并处理相关持仓。",
            ])

            body = "\n".join(body_lines)

            # 构建 HTML 内容
            html_body = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .header {{ background-color: #dc3545; color: white; padding: 20px; text-align: center; }}
                    .info-box {{ margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-radius: 5px; }}
                    .condition {{ padding: 10px; margin: 5px 0; border-left: 3px solid #dc3545; background-color: #fff5f5; }}
                    .condition.met {{ border-left-color: #28a745; background-color: #f0fff4; }}
                    table {{ width: 100%; border-collapse: collapse; }}
                    th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h2>投资信号{status_text}通知</h2>
                    <p>{signal.asset_code}</p>
                </div>

                <div class="info-box">
                    <h3>信号信息</h3>
                    <table>
                        <tr><th>资产代码</th><td>{signal.asset_code}</td></tr>
                        <tr><th>逻辑描述</th><td>{signal.logic_desc or 'N/A'}</td></tr>
                        <tr><th>状态</th><td><strong>{signal.status.value}</strong></td></tr>
                        <tr><th>证伪时间</th><td>{timezone.now()}</td></tr>
                    </table>
                </div>

                <div class="info-box">
                    <h3>证伪原因</h3>
                    <p>{result.reason}</p>
                </div>

                <div class="info-box">
                    <h3>条件详情</h3>
            """

            for cond in result.checked_conditions:
                css_class = "met" if cond.is_met else ""
                html_body += f"""
                    <div class="condition {css_class}">
                        <strong>{cond.description}</strong><br>
                        当前值: {cond.actual_value} | 阈值: {cond.threshold}
                    </div>
                """

            html_body += f"""
                </div>

                <div class="info-box">
                    <h3>原始投资逻辑</h3>
                    <pre>{signal.invalidation_description or 'N/A'}</pre>
                </div>

                <div style="text-align: center; padding: 20px; color: #6c757d;">
                    <p>请登录系统查看详情并处理相关持仓。</p>
                    <p>AgomSAAF - 自动发送，请勿回复</p>
                </div>
            </body>
            </html>
            """

            # 发送通知
            notify_results = self.notification_service.send_email(
                subject=subject,
                body=body,
                recipients=recipients,
                html_body=html_body,
                priority=NotificationPriority.HIGH,
            )

            success = any(r.success for r in notify_results)
            if success:
                logger.info(f"信号 #{signal.id} 证伪通知已发送: recipients={len(recipients)}")
            else:
                logger.warning(f"信号 #{signal.id} 证伪通知发送失败")

        except Exception as e:
            logger.error(f"发送信号 #{signal.id} 证伪通知失败: {e}", exc_info=True)

    def _get_signal_recipients(self, signal: InvestmentSignal) -> List[str]:
        """
        获取信号通知收件人列表

        Args:
            signal: 信号实体

        Returns:
            list: 收件人邮箱列表
        """
        from django.conf import settings

        recipients = []

        # 1. 从配置获取管理员列表
        admin_emails = getattr(settings, 'SIGNAL_NOTIFICATION_EMAILS', [])
        recipients.extend(admin_emails)

        # 2. 获取所有 staff 用户的邮箱
        if self.user_repository is not None:
            staff_emails = self.user_repository.get_staff_emails()
            recipients.extend(staff_emails)
        else:
            # 延迟导入作为后备
            from apps.signal.infrastructure.repositories import DjangoUserRepository
            user_repo = DjangoUserRepository()
            staff_emails = user_repo.get_staff_emails()
            recipients.extend(staff_emails)

        # 去重并过滤空值
        recipients = list(set(r for r in recipients if r and '@' in r))

        return recipients

    def check_all_approved_signals(self) -> List[str]:
        """检查所有已批准的信号

        返回需要证伪的信号ID列表，并自动更新其状态。

        Returns:
            List[str]: 被证伪的信号ID列表
        """
        # 获取所有有证伪规则的已批准信号
        invalidated_ids = []

        try:
            approved_signals = self.signal_repository.find_signals_with_invalidation_rules(
                status=SignalStatus.APPROVED
            )
            for signal in approved_signals:
                result = self._check_signal_entity(signal)
                if result and result.is_invalidated:
                    invalidated_ids.append(signal.id)
        except RuntimeError as exc:
            if "Database access not allowed" not in str(exc):
                raise
            model_cls = _resolve_investment_signal_model()
            approved_signals = model_cls._default_manager.filter(
                status='approved',
                invalidation_rule_json__isnull=False
            ).exclude(invalidation_rule_json={})
            for signal_model in approved_signals:
                result = self._check_signal_model(signal_model)
                if result and result.is_invalidated:
                    invalidated_ids.append(signal_model.id)

        return invalidated_ids

    def check_pending_signals(self) -> List[str]:
        """检查所有待处理的信号

        检查 pending 状态的信号是否满足证伪条件，
        如果满足则标记为 rejected（因为还未被批准）。

        Returns:
            List[str]: 被拒绝的信号ID列表
        """
        # 获取所有有证伪规则的待处理信号
        rejected_ids = []

        try:
            pending_signals = self.signal_repository.find_signals_with_invalidation_rules(
                status=SignalStatus.PENDING
            )
            for signal in pending_signals:
                result = self._check_signal_entity(signal)
                if result and result.is_invalidated:
                    rejected_ids.append(signal.id)
        except RuntimeError as exc:
            if "Database access not allowed" not in str(exc):
                raise
            model_cls = _resolve_investment_signal_model()
            pending_signals = model_cls._default_manager.filter(
                status='pending',
                invalidation_rule_json__isnull=False
            ).exclude(invalidation_rule_json={})
            for signal_model in pending_signals:
                result = self._check_signal_model(signal_model)
                if result and result.is_invalidated:
                    rejected_ids.append(signal_model.id)

        return rejected_ids

    def check_signal_by_id(self, signal_id: int) -> Optional[InvalidationCheckResult]:
        """通过ID检查信号（别名，保持向后兼容）

        Args:
            signal_id: 信号ID

        Returns:
            InvalidationCheckResult 或 None
        """
        return self.check_signal(signal_id)


# ==================== 导出函数，供 Celery 任务使用 ====================

def check_and_invalidate_signals() -> Dict:
    """检查并证伪满足条件的信号

    这是一个导出函数，供 Celery 任务调用。

    现在同时检查:
    - approved 信号 -> 证伪条件满足时变为 invalidated
    - pending 信号 -> 证伪条件满足时变为 rejected

    Returns:
        Dict: 包含统计信息
    """
    from apps.signal.infrastructure.repositories import DjangoSignalRepository

    repository = DjangoSignalRepository()
    service = InvalidationCheckService(signal_repository=repository)

    # 检查已批准信号
    invalidated_ids = service.check_all_approved_signals()

    # 检查待处理信号
    rejected_ids = service.check_pending_signals()

    # 统计数量
    try:
        approved_count = repository.count_by_status('approved')
        pending_count = repository.count_by_status('pending')
    except RuntimeError as exc:
        if "Database access not allowed" not in str(exc):
            raise
        model_cls = _resolve_investment_signal_model()
        approved_count = model_cls._default_manager.filter(status='approved').count()
        pending_count = model_cls._default_manager.filter(status='pending').count()

    return {
        'checked': approved_count + pending_count,
        'invalidated': len(invalidated_ids),
        'rejected': len(rejected_ids),
        'invalidated_ids': [int(id) for id in invalidated_ids],
        'rejected_ids': [int(id) for id in rejected_ids],
        'signal_ids': [int(id) for id in invalidated_ids],  # backward compatible
    }
