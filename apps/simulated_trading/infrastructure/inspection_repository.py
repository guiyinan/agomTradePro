"""
模拟盘数据仓储实现

Infrastructure层:
- 实现Domain层定义的Repository Protocol接口
- 负责Domain实体与ORM模型之间的转换
- 封装数据库操作细节
"""

from datetime import date
from typing import Any

from apps.simulated_trading.infrastructure.models import (
    DailyInspectionNotificationConfigModel,
    DailyInspectionReportModel,
    NotificationHistoryModel,
    RebalanceProposalModel,
    SimulatedAccountModel,
)


class DjangoInspectionRepository:
    """日更巡检相关仓储。"""

    def get_notification_config(self, account_id: int) -> DailyInspectionNotificationConfigModel:
        """Return the stored settings or the model defaults without persisting them."""

        config = DailyInspectionNotificationConfigModel._default_manager.filter(
            account_id=account_id
        ).first()
        if config is not None:
            return config
        return DailyInspectionNotificationConfigModel(account_id=account_id)

    def update_notification_config(
        self,
        account_id: int,
        *,
        is_enabled: bool,
        include_owner_email: bool,
        notify_on: str,
        recipient_emails: list[str],
    ) -> DailyInspectionNotificationConfigModel | None:
        """Persist notification settings for one account."""

        if not SimulatedAccountModel._default_manager.filter(pk=account_id).exists():
            return None
        config, _ = DailyInspectionNotificationConfigModel._default_manager.update_or_create(
            account_id=account_id,
            defaults={
                "is_enabled": is_enabled,
                "include_owner_email": include_owner_email,
                "notify_on": notify_on,
                "recipient_emails": sorted(set(recipient_emails)),
            },
        )
        return config

    def list_report_payloads(
        self,
        account_id: int,
        *,
        limit: int,
        inspection_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Return serialized daily inspection reports for API responses."""

        queryset = DailyInspectionReportModel._default_manager.filter(
            account_id=account_id
        ).order_by(
            "-inspection_date",
            "-updated_at",
        )
        if inspection_date:
            queryset = queryset.filter(inspection_date=inspection_date)

        return [
            {
                "report_id": report.id,
                "account_id": report.account_id,
                "inspection_date": report.inspection_date.isoformat(),
                "status": report.status,
                "macro_regime": report.macro_regime,
                "policy_gear": report.policy_gear,
                "strategy_id": report.strategy_id,
                "position_rule_id": report.position_rule_id,
                "summary": report.summary,
                "checks": report.checks,
            }
            for report in queryset[:limit]
        ]

    def upsert_report(
        self,
        account_id: int,
        inspection_date: date,
        defaults: dict[str, Any],
    ) -> dict[str, Any]:
        report, _ = DailyInspectionReportModel._default_manager.update_or_create(
            account_id=account_id,
            inspection_date=inspection_date,
            defaults=defaults,
        )
        return {
            "report_id": report.id,
            "status": report.status,
            "macro_regime": report.macro_regime,
            "policy_gear": report.policy_gear,
        }

    def create_rebalance_proposal(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        proposal = RebalanceProposalModel._default_manager.create(**payload)
        return {
            "proposal_id": proposal.id,
            "account_id": proposal.account_id,
            "inspection_report_id": proposal.inspection_report_id,
            "strategy_id": proposal.strategy_id,
            "source": proposal.source,
            "source_description": proposal.source_description,
            "priority": proposal.priority,
            "status": proposal.status,
            "proposals": list(proposal.proposals or []),
            "summary": dict(proposal.summary or {}),
            "metadata": dict(proposal.metadata or {}),
            "proposed_by": proposal.proposed_by,
        }

    def get_account_notification_context(
        self,
        account_id: int,
    ) -> dict[str, Any] | None:
        account = (
            SimulatedAccountModel._default_manager.filter(id=account_id)
            .select_related("user")
            .first()
        )
        if not account:
            return None
        config = self.get_notification_config(account_id)
        return {
            "account_id": account.id,
            "account_name": account.account_name,
            "user_id": account.user.id if account.user else None,
            "user_email": account.user.email if account.user else "",
            "config": {
                "is_enabled": config.is_enabled,
                "include_owner_email": config.include_owner_email,
                "notify_on": config.notify_on,
                "recipient_emails": list(config.recipient_emails or []),
            },
        }

    def get_rebalance_proposal_detail(
        self,
        proposal_id: int,
    ) -> dict[str, Any] | None:
        proposal = RebalanceProposalModel._default_manager.filter(id=proposal_id).first()
        if not proposal:
            return None
        return {
            "proposal_id": proposal.id,
            "priority": proposal.priority,
            "priority_display": proposal.get_priority_display(),
            "status": proposal.status,
            "status_display": proposal.get_status_display(),
            "proposals": list(proposal.proposals or []),
            "source_description": proposal.source_description,
        }

    def record_notification_history(
        self,
        account_id: int,
        proposal_id: int | None,
        notification_type: str,
        recipients: list[str],
        status: str,
        subject: str,
        body: str,
        recipient_user_id: int | None = None,
    ) -> None:
        for email in recipients:
            NotificationHistoryModel._default_manager.create(
                account_id=account_id,
                rebalance_proposal_id=proposal_id,
                notification_type=notification_type,
                channel="email",
                recipient_user_id=recipient_user_id,
                recipient_email=email,
                subject=subject,
                body=body,
                status=status,
            )


__all__ = ["DjangoInspectionRepository"]
