"""Django repositories for broker execution."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Min, Model, Q, QuerySet, Sum
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerAgentAuthenticationError,
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
    BrokerExecutionPermissionError,
)
from apps.broker_execution.domain.entities import LiveOrderStatus
from apps.broker_execution.domain.rules import (
    is_trading_session_open,
    target_status_for_order_action,
    validate_order_transition,
)
from apps.broker_execution.domain.services import approval_digest_for_order

from .models import (
    BrokerAccountAccessModel,
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerAgentNonceModel,
    BrokerCommandModel,
    BrokerExecutionAlertModel,
    BrokerExecutionAuditModel,
    BrokerExecutionDailyReportModel,
    BrokerExecutionIdempotencyModel,
    BrokerFillModel,
    BrokerOrderEventModel,
    BrokerPositionSnapshotModel,
    LiveOrderModel,
    OrderLeaseModel,
    ReconciliationDifferenceModel,
    ReconciliationRunModel,
    TradingControlModel,
)

ModelT = TypeVar("ModelT", bound=Model)


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


class DjangoBrokerExecutionRepository:
    """ORM-backed broker execution repository with scoped reads and atomic writes."""

    @staticmethod
    def _authorized_account_ids(
        *, user_id: int, action: str = "view"
    ) -> QuerySet[BrokerAccountAccessModel, int]:
        grants = BrokerAccountAccessModel._default_manager.filter(
            user_id=user_id,
            is_active=True,
        )
        if action == "approve":
            grants = grants.filter(can_approve=True)
        elif action in {"cancel", "trade"}:
            grants = grants.filter(can_trade=True)
        return grants.values_list("account_id", flat=True)

    @staticmethod
    def _upsert_operational_alert(
        *,
        user_id: int,
        account_id: int,
        code: str,
        severity: str,
        title: str,
        message: str,
        resource_key: str,
        payload: dict[str, Any] | None = None,
        auto_stop: bool = False,
    ) -> dict[str, Any]:
        fingerprint = hashlib.sha256(
            f"{code}:{user_id}:{account_id}:{resource_key}".encode()
        ).hexdigest()
        alert, created = BrokerExecutionAlertModel._default_manager.get_or_create(
            fingerprint=fingerprint,
            defaults={
                "user_id": user_id,
                "account_id": account_id,
                "code": code,
                "severity": severity,
                "title": title,
                "message": message,
                "payload": payload or {},
                "auto_stop_applied": auto_stop,
            },
        )
        if not created:
            alert.status = "open"
            alert.severity = severity
            alert.title = title
            alert.message = message
            alert.payload = payload or {}
            alert.auto_stop_applied = alert.auto_stop_applied or auto_stop
            alert.occurrence_count += 1
            alert.save()
        if auto_stop:
            control, _ = TradingControlModel._default_manager.get_or_create(
                user_id=user_id,
                account_id=account_id,
            )
            control.kill_switch_active = True
            control.reason = f"{code}: {message}"
            control.changed_by_id = None
            control.save()
        return {
            "level": "critical" if severity == "P0" else "warning",
            "task_name": "broker_execution.operational_alert",
            "title": title,
            "message": message,
            "metadata": {
                "account_id": account_id,
                "code": code,
                **(payload or {}),
            },
        }

    @classmethod
    def _user_scope(
        cls,
        queryset: QuerySet[ModelT],
        *,
        user_id: int,
        is_admin: bool,
    ) -> QuerySet[ModelT]:
        if is_admin:
            return queryset
        if queryset.model is BrokerAgentModel:
            return queryset.filter(
                Q(user_id=user_id)
                | Q(account_bindings__account_id__in=cls._authorized_account_ids(user_id=user_id))
            ).distinct()
        field_names = {field.name for field in queryset.model._meta.fields}
        if "account_id" not in field_names:
            return queryset.filter(user_id=user_id)
        return queryset.filter(
            Q(user_id=user_id) | Q(account_id__in=cls._authorized_account_ids(user_id=user_id))
        )

    def has_account_access(
        self,
        *,
        user_id: int,
        is_admin: bool,
        account_id: int,
        action: str,
    ) -> bool:
        """Return whether the actor owns or has the required explicit account grant."""

        if is_admin:
            return True
        if BrokerAccountBindingModel._default_manager.filter(
            user_id=user_id, account_id=account_id, is_active=True
        ).exists():
            return True
        return BrokerAccountAccessModel._default_manager.filter(
            user_id=user_id,
            account_id=account_id,
            is_active=True,
            **(
                {"can_approve": True}
                if action == "approve"
                else {"can_trade": True} if action in {"cancel", "trade"} else {}
            ),
        ).exists()

    def list_kill_switch_targets(
        self,
        *,
        user_id: int,
        is_admin: bool,
        account_id: int,
    ) -> list[dict[str, int]]:
        """Return concrete owner/account controls affected by a stop or resume."""

        bindings = BrokerAccountBindingModel._default_manager.filter(is_active=True)
        if account_id > 0:
            bindings = bindings.filter(account_id=account_id)
        elif not is_admin:
            bindings = bindings.filter(
                Q(user_id=user_id)
                | Q(
                    account_id__in=self._authorized_account_ids(
                        user_id=user_id,
                        action="trade",
                    )
                )
            )
        rows = [
            {"user_id": int(owner_id), "account_id": int(target_account_id)}
            for owner_id, target_account_id in bindings.values_list(
                "user_id", "account_id"
            ).distinct()
        ]
        if rows:
            return rows
        if account_id == 0:
            return [{"user_id": int(user_id), "account_id": 0}]
        return []

    def get_bound_account_owner_id(self, *, account_id: int) -> int | None:
        """Return the authoritative owner of one active globally unique binding."""

        owner_id = (
            BrokerAccountBindingModel._default_manager.filter(
                account_id=account_id,
                is_active=True,
            )
            .values_list("user_id", flat=True)
            .first()
        )
        return int(owner_id) if owner_id is not None else None

    def get_user_identity(self, *, user_id: int) -> dict[str, Any] | None:
        """Return the minimal identity projection needed for access previews."""

        user_model = BrokerAccountAccessModel._meta.get_field("user").remote_field.model
        identity = (
            user_model._default_manager.filter(pk=user_id)
            .values("pk", "username", "is_superuser", "account_profile__rbac_role")
            .first()
        )
        if identity is None:
            return None
        role = str(identity["account_profile__rbac_role"] or "read_only")
        is_superuser = bool(identity["is_superuser"])
        return {
            "user_id": int(identity["pk"]),
            "username": str(identity["username"]),
            "role": "admin" if is_superuser else role,
            "is_admin": is_superuser or role == "admin",
        }

    def list_agent_account_ids(self, *, agent_id: str) -> list[int]:
        """Return active accounts bound to one active Agent."""

        return list(
            BrokerAccountBindingModel._default_manager.filter(
                agent__agent_id=agent_id,
                agent__is_active=True,
                is_active=True,
            )
            .order_by("account_id")
            .values_list("account_id", flat=True)
        )

    def record_permission_denial(
        self,
        *,
        user_id: int,
        action: str,
        role: str,
        request_context: dict[str, Any] | None = None,
    ) -> None:
        """Persist a scoped denial without exposing another user's resources."""

        BrokerExecutionAuditModel._default_manager.create(
            user_id=user_id,
            actor_id=user_id,
            action="permission_denied",
            account_id=0,
            resource_type="broker_execution_action",
            resource_id=action,
            after={
                "role": role,
                "result": "denied",
                "request_context": dict(request_context or {}),
            },
            reason="Action capability is not granted",
        )

    def record_agent_auth_failure(
        self,
        *,
        credential_id: str,
        agent_id: str,
        request_id: str,
        required_scope: str,
        source_ip: str,
        failure_code: str,
    ) -> None:
        """Persist machine authentication failures without credential material."""

        try:
            normalized_credential_id = str(UUID(str(credential_id)))
        except (ValueError, AttributeError):
            normalized_credential_id = ""
        credential = (
            BrokerAgentCredentialModel._default_manager.select_related("agent")
            .filter(credential_id=normalized_credential_id)
            .first()
            if normalized_credential_id
            else None
        )
        known_agent = credential.agent if credential is not None else None
        if known_agent is None and agent_id:
            known_agent = BrokerAgentModel._default_manager.filter(agent_id=agent_id).first()
        owner_id = known_agent.user_id if known_agent is not None else None
        safe_agent_id = str(agent_id or "unknown")[:64]
        safe_credential_id = str(credential_id or "unknown")[:64]
        BrokerExecutionAuditModel._default_manager.create(
            user_id=owner_id,
            actor=None,
            actor_type="agent",
            action="agent_auth_failed",
            account_id=0,
            resource_type="agent_authentication",
            resource_id=safe_agent_id,
            after={
                "agent_id": safe_agent_id,
                "credential_id": safe_credential_id,
                "required_scope": str(required_scope)[:128],
                "source_ip": str(source_ip or "")[:64],
                "failure_code": str(failure_code)[:64],
            },
            reason="Agent authentication failed",
            request_id=str(request_id or "")[:128],
        )

    @staticmethod
    def _order_payload(order: LiveOrderModel, *, include_events: bool = False) -> dict[str, Any]:
        action_availability: dict[str, bool] = {}
        for action in ("approve", "reject", "cancel"):
            try:
                target_status_for_order_action(order.status, action)
            except ValueError:
                action_availability[action] = False
            else:
                action_availability[action] = True
        agent = order.agent
        payload: dict[str, Any] = {
            "client_order_id": str(order.client_order_id),
            "account_id": order.account_id,
            "agent_id": agent.agent_id if agent is not None else None,
            "asset_code": order.asset_code,
            "market": order.market,
            "side": order.side,
            "order_type": order.order_type,
            "quantity": _decimal_text(order.quantity),
            "limit_price": _decimal_text(order.limit_price),
            "estimated_amount": _decimal_text(order.estimated_amount),
            "status": order.status,
            "source_recommendation_ids": order.source_recommendation_ids or [],
            "source_signal_ids": order.source_signal_ids or [],
            "risk_policy_version": order.risk_policy_version,
            "risk_snapshot": order.risk_snapshot or {},
            "approval_mode": order.approval_mode,
            "approval_digest": order.approval_digest,
            "approved_by": order.approved_by_id,
            "approved_at": order.approved_at.isoformat() if order.approved_at else None,
            "expires_at": order.expires_at.isoformat() if order.expires_at else None,
            "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
            "broker_order_id": order.broker_order_id,
            "filled_quantity": _decimal_text(order.filled_quantity),
            "average_fill_price": _decimal_text(order.average_fill_price),
            "failure_code": order.failure_code,
            "failure_message": order.failure_message,
            "version": order.version,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
            "action_availability": action_availability,
        }
        if include_events:
            payload["events"] = [
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "status": event.status,
                    "payload": event.payload or {},
                    "occurred_at": event.occurred_at.isoformat(),
                    "received_at": event.received_at.isoformat(),
                }
                for event in order.broker_events.all()
            ]
            payload["fills"] = [
                {
                    "broker_trade_id": fill.broker_trade_id,
                    "quantity": _decimal_text(fill.quantity),
                    "price": _decimal_text(fill.price),
                    "amount": _decimal_text(fill.amount),
                    "occurred_at": fill.occurred_at.isoformat(),
                }
                for fill in order.fills.all()
            ]
        return payload

    def build_overview(self, *, user_id: int, is_admin: bool) -> dict[str, Any]:
        orders = self._user_scope(
            LiveOrderModel._default_manager.all(), user_id=user_id, is_admin=is_admin
        )
        agents = self._user_scope(
            BrokerAgentModel._default_manager.all(), user_id=user_id, is_admin=is_admin
        )
        reconciliations = self._user_scope(
            ReconciliationRunModel._default_manager.all(), user_id=user_id, is_admin=is_admin
        )
        controls = self._user_scope(
            TradingControlModel._default_manager.all(), user_id=user_id, is_admin=is_admin
        )
        alerts = self._user_scope(
            BrokerExecutionAlertModel._default_manager.all(),
            user_id=user_id,
            is_admin=is_admin,
        )
        reports = self._user_scope(
            BrokerExecutionDailyReportModel._default_manager.all(),
            user_id=user_id,
            is_admin=is_admin,
        )
        order_counts = {
            row["status"]: row["count"]
            for row in orders.values("status").annotate(count=Count("id"))
        }
        pending_statuses = [LiveOrderStatus.WAITING_APPROVAL.value, LiveOrderStatus.READY.value]
        exception_statuses = [
            LiveOrderStatus.SUBMITTING.value,
            LiveOrderStatus.BROKER_REJECTED.value,
            LiveOrderStatus.RECONCILIATION_REQUIRED.value,
            LiveOrderStatus.FAILED.value,
        ]
        pending = orders.filter(status__in=pending_statuses).aggregate(
            count=Count("id"),
            amount=Sum("estimated_amount"),
            earliest_expiry=Min("expires_at"),
        )
        active_kill_switches = list(
            controls.filter(kill_switch_active=True).values("account_id", "reason", "changed_at")
        )
        any_online = agents.filter(
            status=BrokerAgentModel.STATUS_ONLINE, qmt_connected=True, is_active=True
        ).exists()
        unresolved = reconciliations.exclude(status__in=["resolved", "completed"]).aggregate(
            runs=Count("id"),
            order=Sum("order_difference_count"),
            fill=Sum("fill_difference_count"),
            cash=Sum("cash_difference_count"),
            position=Sum("position_difference_count"),
        )
        if active_kill_switches:
            readiness = "STOPPED"
        elif not any_online:
            readiness = "OFFLINE"
        elif (
            orders.filter(status__in=exception_statuses).exists()
            or int(unresolved["runs"] or 0) > 0
            or alerts.filter(status="open", severity__in=["P0", "P1"]).exists()
        ):
            readiness = "REVIEW"
        else:
            readiness = "READY"
        return {
            "today_readiness": readiness,
            "kill_switch": {
                "active": bool(active_kill_switches),
                "controls": [
                    {
                        "account_id": row["account_id"],
                        "reason": row["reason"],
                        "changed_at": row["changed_at"].isoformat(),
                    }
                    for row in active_kill_switches
                ],
            },
            "connections": {
                "total": agents.filter(is_active=True).count(),
                "online": agents.filter(
                    status="online", qmt_connected=True, is_active=True
                ).count(),
            },
            "pending_approvals": {
                "count": int(pending["count"] or 0),
                "estimated_amount": _decimal_text(pending["amount"] or Decimal("0")),
                "earliest_expiry": (
                    pending["earliest_expiry"].isoformat() if pending["earliest_expiry"] else None
                ),
            },
            "execution_exceptions": {
                "count": orders.filter(status__in=exception_statuses).count(),
                "statuses": {key: order_counts.get(key, 0) for key in exception_statuses},
            },
            "reconciliation_differences": {
                "runs": int(unresolved["runs"] or 0),
                "order": int(unresolved["order"] or 0),
                "fill": int(unresolved["fill"] or 0),
                "cash": int(unresolved["cash"] or 0),
                "position": int(unresolved["position"] or 0),
            },
            "order_status_counts": order_counts,
            "active_alerts": [
                {
                    "code": row.code,
                    "severity": row.severity,
                    "title": row.title,
                    "account_id": row.account_id,
                    "auto_stop_applied": row.auto_stop_applied,
                    "last_seen_at": row.last_seen_at.isoformat(),
                }
                for row in alerts.filter(status="open")[:20]
            ],
            "daily_reports": [
                {
                    "account_id": row.account_id,
                    "report_date": row.report_date.isoformat(),
                    "status": row.status,
                    "metrics": row.metrics or {},
                    "summary": row.summary or {},
                }
                for row in reports[:20]
            ],
            "generated_at": timezone.now().isoformat(),
        }

    def get_account_readiness_evidence(self, *, user_id: int, account_id: int) -> dict[str, Any]:
        """Return fail-closed live execution evidence for one unified account."""

        binding = (
            BrokerAccountBindingModel._default_manager.select_related("agent")
            .filter(user_id=user_id, account_id=account_id, is_active=True)
            .first()
        )
        if binding is None:
            return {
                "status": "skipped",
                "reason": "live_broker_binding_not_configured",
                "account_id": account_id,
            }
        now = timezone.now()
        snapshot = (
            BrokerAccountSnapshotModel._default_manager.filter(
                agent=binding.agent, account_id=account_id
            )
            .order_by("-captured_at")
            .first()
        )
        snapshot_fresh = bool(
            snapshot
            and snapshot.captured_at >= now - timedelta(seconds=binding.max_snapshot_age_seconds)
        )
        stopped = TradingControlModel._default_manager.filter(
            user_id=user_id,
            account_id__in=[0, account_id],
            kill_switch_active=True,
        ).exists()
        unresolved = ReconciliationRunModel._default_manager.filter(
            user_id=user_id, account_id=account_id
        ).exclude(status__in=["resolved", "completed"])
        latest_report = BrokerExecutionDailyReportModel._default_manager.filter(
            user_id=user_id, account_id=account_id
        ).first()
        ready = bool(
            binding.auto_execution_enabled
            and binding.agent.status == BrokerAgentModel.STATUS_ONLINE
            and binding.agent.qmt_connected
            and snapshot_fresh
            and not stopped
            and not unresolved.exists()
        )
        blockers = []
        if not binding.auto_execution_enabled:
            blockers.append("auto_execution_disabled")
        if (
            binding.agent.status != BrokerAgentModel.STATUS_ONLINE
            or not binding.agent.qmt_connected
        ):
            blockers.append("qmt_agent_offline")
        if not snapshot_fresh:
            blockers.append("broker_snapshot_stale_or_missing")
        if stopped:
            blockers.append("kill_switch_active")
        if unresolved.exists():
            blockers.append("reconciliation_unresolved")
        return {
            "status": "ok" if ready else "warning",
            "ready": ready,
            "account_id": account_id,
            "agent_id": binding.agent.agent_id,
            "qmt_connected": binding.agent.qmt_connected,
            "auto_execution_enabled": binding.auto_execution_enabled,
            "snapshot_fresh": snapshot_fresh,
            "snapshot_captured_at": snapshot.captured_at.isoformat() if snapshot else None,
            "kill_switch_active": stopped,
            "unresolved_reconciliation_runs": unresolved.count(),
            "blockers": blockers,
            "latest_daily_report": (
                {
                    "report_date": latest_report.report_date.isoformat(),
                    "status": latest_report.status,
                    "metrics": latest_report.metrics or {},
                }
                if latest_report
                else None
            ),
        }

    def list_orders(
        self,
        *,
        user_id: int,
        is_admin: bool,
        account_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        queryset = self._user_scope(
            LiveOrderModel._default_manager.select_related("approved_by", "agent"),
            user_id=user_id,
            is_admin=is_admin,
        )
        if account_id is not None:
            queryset = queryset.filter(account_id=account_id)
        if status:
            queryset = queryset.filter(status=status)
        return [self._order_payload(order) for order in queryset[: max(1, min(int(limit), 200))]]

    def get_order(
        self, *, user_id: int, is_admin: bool, client_order_id: str
    ) -> dict[str, Any] | None:
        queryset = self._user_scope(
            LiveOrderModel._default_manager.select_related("approved_by", "agent").prefetch_related(
                "broker_events", "fills"
            ),
            user_id=user_id,
            is_admin=is_admin,
        )
        order = queryset.filter(client_order_id=client_order_id).first()
        return self._order_payload(order, include_events=True) if order else None

    def list_connections(self, *, user_id: int, is_admin: bool) -> list[dict[str, Any]]:
        queryset = self._user_scope(
            BrokerAgentModel._default_manager.prefetch_related("account_bindings", "credentials"),
            user_id=user_id,
            is_admin=is_admin,
        )
        authorized_accounts = set(self._authorized_account_ids(user_id=user_id))
        rows: list[dict[str, Any]] = []
        for agent in queryset:
            row = {
                "agent_id": agent.agent_id,
                "user_id": agent.user_id,
                "display_name": agent.display_name,
                "status": agent.status,
                "qmt_connected": agent.qmt_connected,
                "agent_version": agent.agent_version,
                "last_heartbeat_at": (
                    agent.last_heartbeat_at.isoformat() if agent.last_heartbeat_at else None
                ),
                "is_active": agent.is_active,
                "bindings": [
                    {
                        "user_id": binding.user_id,
                        "agent_id": agent.agent_id,
                        "account_id": binding.account_id,
                        "broker_account_mask": binding.broker_account_mask,
                        "account_type": binding.account_type,
                        "auto_execution_enabled": binding.auto_execution_enabled,
                        "max_single_order_amount": _decimal_text(binding.max_single_order_amount),
                        "daily_order_amount_limit": _decimal_text(binding.daily_order_amount_limit),
                        "max_position_count": binding.max_position_count,
                        "max_snapshot_age_seconds": binding.max_snapshot_age_seconds,
                        "price_deviation_limit_pct": _decimal_text(
                            binding.price_deviation_limit_pct
                        ),
                        "allowed_trading_windows": binding.allowed_trading_windows or [],
                        "enforce_trading_session": binding.enforce_trading_session,
                        "allowed_symbols": binding.allowed_symbols or [],
                        "is_active": binding.is_active,
                    }
                    for binding in agent.account_bindings.all()
                    if is_admin
                    or binding.user_id == user_id
                    or binding.account_id in authorized_accounts
                ],
            }
            if is_admin:
                row["credentials"] = [
                    {
                        "credential_id": str(credential.credential_id),
                        "scopes": credential.scopes or [],
                        "allowed_account_ids": credential.allowed_account_ids or [],
                        "expires_at": credential.expires_at.isoformat(),
                        "revoked_at": (
                            credential.revoked_at.isoformat() if credential.revoked_at else None
                        ),
                    }
                    for credential in agent.credentials.all()
                ]
            rows.append(row)
        return rows

    def list_account_access_grants(self, *, actor_id: int) -> list[dict[str, Any]]:
        """Return account grants for the already-authorized administrator."""

        return [
            {
                "id": grant.pk,
                "user_id": grant.user_id,
                "username": grant.user.username,
                "account_id": grant.account_id,
                "can_approve": grant.can_approve,
                "can_trade": grant.can_trade,
                "is_active": grant.is_active,
                "granted_by": (grant.granted_by.username if grant.granted_by is not None else None),
                "updated_at": grant.updated_at.isoformat(),
            }
            for grant in BrokerAccountAccessModel._default_manager.select_related(
                "user", "granted_by"
            ).order_by("account_id", "user__username")
        ]

    def list_reconciliations(
        self, *, user_id: int, is_admin: bool, limit: int = 100
    ) -> list[dict[str, Any]]:
        queryset = self._user_scope(
            ReconciliationRunModel._default_manager.prefetch_related("differences"),
            user_id=user_id,
            is_admin=is_admin,
        )
        return [
            {
                "id": run.id,
                "account_id": run.account_id,
                "status": run.status,
                "order_difference_count": run.order_difference_count,
                "fill_difference_count": run.fill_difference_count,
                "cash_difference_count": run.cash_difference_count,
                "position_difference_count": run.position_difference_count,
                "summary": run.summary or {},
                "differences": [
                    {
                        "dimension": item.dimension,
                        "difference_key": item.difference_key,
                        "severity": item.severity,
                        "expected": item.expected or {},
                        "actual": item.actual or {},
                        "reason": item.reason,
                        "status": item.status,
                    }
                    for item in run.differences.all()
                ],
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            }
            for run in queryset[: max(1, min(int(limit), 200))]
        ]

    def list_audits(
        self, *, user_id: int, is_admin: bool, limit: int = 100
    ) -> list[dict[str, Any]]:
        queryset = self._user_scope(
            BrokerExecutionAuditModel._default_manager.select_related("actor"),
            user_id=user_id,
            is_admin=is_admin,
        )
        return [
            {
                "id": event.id,
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "actor_username": event.actor.username if event.actor else "",
                "action": event.action,
                "account_id": event.account_id,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "before": event.before or {},
                "after": event.after or {},
                "reason": event.reason,
                "request_id": event.request_id,
                "created_at": event.created_at.isoformat(),
            }
            for event in queryset[: max(1, min(int(limit), 200))]
        ]

    @staticmethod
    def _replay_or_conflict(
        *, user_id: int, action: str, idempotency_key: str, request_digest: str
    ) -> dict[str, Any] | None:
        existing = BrokerExecutionIdempotencyModel._default_manager.filter(
            user_id=user_id,
            action=action,
            idempotency_key=idempotency_key,
        ).first()
        if existing is None:
            return None
        if existing.request_digest != request_digest:
            raise BrokerExecutionConflictError("idempotency_key was reused with different input")
        return dict(existing.response_payload) | {"idempotent_replay": True}

    @staticmethod
    def _save_idempotent_result(
        *,
        user_id: int,
        action: str,
        idempotency_key: str,
        request_digest: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            BrokerExecutionIdempotencyModel._default_manager.create(
                user_id=user_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                response_payload=payload,
            )
        except IntegrityError as exc:
            raise BrokerExecutionConflictError("Concurrent idempotent write conflict") from exc

    def mutate_order(
        self,
        *,
        user_id: int,
        is_admin: bool,
        client_order_id: str,
        action: str,
        reason: str,
        expected_version: int,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        idempotency_action = f"order:{action}"
        replay = self._replay_or_conflict(
            user_id=user_id,
            action=idempotency_action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        with transaction.atomic():
            queryset = LiveOrderModel._default_manager.select_for_update()
            order = queryset.filter(client_order_id=client_order_id).first()
            if order is None:
                raise BrokerExecutionNotFoundError("Live order does not exist")
            if order.version != int(expected_version):
                raise BrokerExecutionConflictError(
                    "Order changed after preview; preview the current version again"
                )
            if not self.has_account_access(
                user_id=user_id,
                is_admin=is_admin,
                account_id=order.account_id,
                action=action,
            ):
                raise BrokerExecutionPermissionError("Account access is not authorized")
            before = self._order_payload(order)
            target_status = target_status_for_order_action(order.status, action)
            if action == "approve":
                if TradingControlModel._default_manager.filter(
                    user_id=order.user_id,
                    account_id__in=[0, order.account_id],
                    kill_switch_active=True,
                ).exists():
                    raise BrokerExecutionConflictError(
                        "Trading is stopped; the order cannot be approved"
                    )
                order.approval_digest = approval_digest_for_order(before)
                order.approved_by_id = user_id
                order.approved_at = timezone.now()
            target = target_status.value
            order.status = target
            order.version += 1
            order.save()
            if target == LiveOrderStatus.CANCEL_PENDING.value and order.agent_id is not None:
                BrokerCommandModel._default_manager.create(
                    agent_id=order.agent_id,
                    command_type="cancel",
                    account_id=order.account_id,
                    payload={
                        "client_order_id": str(order.client_order_id),
                        "broker_order_id": order.broker_order_id,
                    },
                )
            after = self._order_payload(order)
            BrokerExecutionAuditModel._default_manager.create(
                user=order.user,
                actor_id=user_id,
                action=f"order_{action}",
                account_id=order.account_id,
                resource_type="live_order",
                resource_id=str(order.client_order_id),
                before=before,
                after=after,
                reason=reason,
                request_id=idempotency_key,
            )
            result = {"success": True, "preview_only": False, "action": action, "order": after}
            self._save_idempotent_result(
                user_id=user_id,
                action=idempotency_action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                payload=result,
            )
            return result

    def set_kill_switch(
        self,
        *,
        user_id: int,
        is_admin: bool,
        account_id: int,
        active: bool,
        reason: str,
        idempotency_key: str,
        request_digest: str,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = "kill_switch_on" if active else "kill_switch_off"
        replay = self._replay_or_conflict(
            user_id=user_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        with transaction.atomic():
            target_rows = self.list_kill_switch_targets(
                user_id=user_id,
                is_admin=is_admin,
                account_id=account_id,
            )
            if not target_rows:
                raise BrokerExecutionNotFoundError("Active broker account binding does not exist")

            target_account_ids = sorted({int(target["account_id"]) for target in target_rows})
            locked_account_ids = set(
                BrokerAccountBindingModel._default_manager.select_for_update()
                .filter(account_id__in=target_account_ids, is_active=True)
                .order_by("account_id")
                .values_list("account_id", flat=True)
            )
            if locked_account_ids != set(target_account_ids):
                raise BrokerExecutionConflictError(
                    "Broker account bindings changed before the kill switch was applied"
                )
            replay = self._replay_or_conflict(
                user_id=user_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replay is not None:
                return replay

            controls: list[dict[str, Any]] = []
            for target in target_rows:
                owner_id = int(target["user_id"])
                target_account_id = int(target["account_id"])
                (
                    control,
                    _created,
                ) = TradingControlModel._default_manager.select_for_update().get_or_create(
                    user_id=owner_id,
                    account_id=target_account_id,
                    defaults={"changed_by_id": user_id},
                )
                before = {
                    "kill_switch_active": control.kill_switch_active,
                    "reason": control.reason,
                }
                control.kill_switch_active = active
                control.reason = reason
                control.changed_by_id = user_id
                control.save()
                after = {
                    "user_id": owner_id,
                    "account_id": target_account_id,
                    "kill_switch_active": control.kill_switch_active,
                    "reason": control.reason,
                    "changed_at": control.changed_at.isoformat(),
                }
                controls.append(after)
                BrokerExecutionAuditModel._default_manager.create(
                    user_id=owner_id,
                    actor_id=user_id,
                    action=action,
                    account_id=target_account_id,
                    resource_type="trading_control",
                    resource_id=f"{owner_id}:{target_account_id}",
                    before=before,
                    after=after | {"request_context": dict(request_context or {})},
                    reason=reason,
                    request_id=idempotency_key,
                )
            result = {
                "success": True,
                "preview_only": False,
                "action": action,
                "account_id": account_id,
                "affected_account_count": len(controls),
                "controls": controls,
                "control": (
                    controls[0]
                    if len(controls) == 1
                    else {
                        "kill_switch_active": active,
                        "affected_account_count": len(controls),
                    }
                ),
            }
            self._save_idempotent_result(
                user_id=user_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                payload=result,
            )
            return result

    def authenticate_agent(
        self,
        *,
        credential_id: str,
        secret_hash: str,
        agent_id: str,
        required_scope: str,
        nonce_hash: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Authenticate a scoped Agent credential and atomically consume its nonce."""

        with transaction.atomic():
            credential = (
                BrokerAgentCredentialModel._default_manager.select_for_update()
                .select_related("agent")
                .filter(credential_id=credential_id)
                .first()
            )
            if credential is None or not hmac.compare_digest(credential.secret_hash, secret_hash):
                raise BrokerAgentAuthenticationError("Invalid Agent credential")
            agent = credential.agent
            if agent.agent_id != agent_id or not agent.is_active:
                raise BrokerAgentAuthenticationError("Agent identity is not active")
            now = timezone.now()
            if credential.revoked_at is not None or credential.expires_at <= now:
                raise BrokerAgentAuthenticationError("Agent credential is expired or revoked")
            if required_scope not in (credential.scopes or []):
                raise BrokerAgentAuthenticationError("Agent credential scope is insufficient")
            allowed_account_ids = sorted(
                {int(item) for item in (credential.allowed_account_ids or [])}
            )
            if not allowed_account_ids:
                raise BrokerAgentAuthenticationError("Agent credential has no account scope")
            try:
                BrokerAgentNonceModel._default_manager.create(
                    credential=credential,
                    nonce_hash=nonce_hash,
                    request_id=request_id,
                )
            except IntegrityError as exc:
                raise BrokerAgentAuthenticationError("Agent request nonce was replayed") from exc
            return {
                "agent_pk": agent.pk,
                "agent_id": agent.agent_id,
                "user_id": agent.user_id,
                "credential_id": str(credential.credential_id),
                "scopes": list(credential.scopes or []),
                "allowed_account_ids": allowed_account_ids,
                "request_id": request_id,
            }

    def heartbeat_agent(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist Agent health without trusting account ownership from the payload."""

        agent = BrokerAgentModel._default_manager.get(pk=agent_pk, is_active=True)
        was_connected = agent.qmt_connected
        account_ids = [int(item) for item in payload.get("account_ids", [])]
        if not set(account_ids).issubset(set(allowed_account_ids)):
            raise BrokerAgentAuthenticationError("Heartbeat exceeds the credential account scope")
        allowed_ids = set(
            agent.account_bindings.filter(is_active=True).values_list("account_id", flat=True)
        )
        if not set(account_ids).issubset(allowed_ids):
            raise BrokerAgentAuthenticationError("Heartbeat contains an unbound account")
        agent.status = (
            BrokerAgentModel.STATUS_ONLINE
            if bool(payload.get("qmt_connected"))
            else BrokerAgentModel.STATUS_DEGRADED
        )
        agent.qmt_connected = bool(payload.get("qmt_connected"))
        agent.agent_version = str(payload.get("agent_version") or "")[:32]
        agent.last_heartbeat_at = timezone.now()
        agent.health_snapshot = {
            "account_ids": account_ids,
            "qmt_version": str(payload.get("qmt_version") or "")[:64],
            "dry_run": bool(payload.get("dry_run", True)),
            "message": str(payload.get("message") or "")[:500],
        }
        agent.save(
            update_fields=[
                "status",
                "qmt_connected",
                "agent_version",
                "last_heartbeat_at",
                "health_snapshot",
                "updated_at",
            ]
        )
        alerts = []
        if not agent.qmt_connected:
            for binding in agent.account_bindings.filter(is_active=True):
                already_open = BrokerExecutionAlertModel._default_manager.filter(
                    user_id=binding.user_id,
                    account_id=binding.account_id,
                    code="P1_QMT_DISCONNECTED",
                    status="open",
                ).exists()
                if already_open and not was_connected:
                    continue
                alerts.append(
                    self._upsert_operational_alert(
                        user_id=binding.user_id,
                        account_id=binding.account_id,
                        code="P1_QMT_DISCONNECTED",
                        severity="P1",
                        title="QMT 连接已断开",
                        message=f"Agent {agent.agent_id} 仍可通信，但 QMT 当前不可用。",
                        resource_key=agent.agent_id,
                        payload={"agent_id": agent.agent_id},
                    )
                )
        else:
            BrokerExecutionAlertModel._default_manager.filter(
                user_id=agent.user_id,
                account_id__in=allowed_ids,
                code__in=["P1_QMT_DISCONNECTED", "P1_QMT_AGENT_OFFLINE"],
                status="open",
            ).update(status="resolved")
        return {
            "accepted": True,
            "server_time": timezone.now().isoformat(),
            "kill_switch_active": TradingControlModel._default_manager.filter(
                user_id=agent.user_id, kill_switch_active=True
            ).exists(),
            "alerts": alerts,
        }

    def lease_agent_orders(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        limit: int,
        lease_seconds: int,
    ) -> dict[str, Any]:
        """Lease READY orders only when connection, binding, and kill switches allow it."""

        now = timezone.now()
        agent = BrokerAgentModel._default_manager.get(pk=agent_pk, is_active=True)
        if agent.status != BrokerAgentModel.STATUS_ONLINE or not agent.qmt_connected:
            raise BrokerExecutionConflictError("Agent or QMT is not online")
        bindings = list(
            agent.account_bindings.filter(
                account_id__in=allowed_account_ids,
                is_active=True,
                auto_execution_enabled=True,
            )
        )
        local_now = timezone.localtime(now)
        bindings = [
            binding
            for binding in bindings
            if not binding.enforce_trading_session
            or is_trading_session_open(local_now, binding.allowed_trading_windows or [])
        ]
        fresh_account_ids: list[int] = []
        for binding in bindings:
            fresh_after = now - timedelta(seconds=binding.max_snapshot_age_seconds)
            if BrokerAccountSnapshotModel._default_manager.filter(
                agent=agent,
                account_id=binding.account_id,
                captured_at__gte=fresh_after,
            ).exists():
                fresh_account_ids.append(binding.account_id)
        account_ids = fresh_account_ids
        blocked_accounts = set(
            TradingControlModel._default_manager.filter(
                user_id=agent.user_id,
                kill_switch_active=True,
            ).values_list("account_id", flat=True)
        )
        if 0 in blocked_accounts:
            return {"orders": [], "total_count": 0, "stopped": True}
        account_ids = [item for item in account_ids if item not in blocked_accounts]
        if not account_ids:
            return {"orders": [], "total_count": 0, "stopped": bool(blocked_accounts)}
        leased: list[dict[str, Any]] = []
        with transaction.atomic():
            stale_leases = list(
                OrderLeaseModel._default_manager.select_for_update()
                .select_related("order")
                .filter(agent=agent, released_at__isnull=True, expires_at__lte=now)
            )
            for stale in stale_leases:
                if stale.order.status == LiveOrderStatus.LEASED.value:
                    stale.order.status = (
                        LiveOrderStatus.EXPIRED.value
                        if stale.order.expires_at and stale.order.expires_at <= now
                        else LiveOrderStatus.READY.value
                    )
                    stale.order.version += 1
                    stale.order.save(update_fields=["status", "version", "updated_at"])
                stale.released_at = now
                stale.save(update_fields=["released_at"])
            expired = LiveOrderModel._default_manager.select_for_update().filter(
                agent=agent,
                account_id__in=account_ids,
                status=LiveOrderStatus.READY.value,
                expires_at__lte=now,
            )
            expired.update(status=LiveOrderStatus.EXPIRED.value, version=F("version") + 1)
            candidates = list(
                LiveOrderModel._default_manager.select_for_update()
                .filter(
                    agent=agent,
                    account_id__in=account_ids,
                    status=LiveOrderStatus.READY.value,
                )
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
                .order_by("created_at")[:limit]
            )
            for order in candidates:
                validate_order_transition(order.status, LiveOrderStatus.LEASED.value)
                raw_token = secrets.token_urlsafe(32)
                OrderLeaseModel._default_manager.update_or_create(
                    order=order,
                    defaults={
                        "agent": agent,
                        "lease_token_hash": hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
                        "leased_at": now,
                        "expires_at": now + timedelta(seconds=lease_seconds),
                        "released_at": None,
                    },
                )
                order.status = LiveOrderStatus.LEASED.value
                order.version += 1
                order.save(update_fields=["status", "version", "updated_at"])
                payload = self._order_payload(order)
                payload["lease_token"] = raw_token
                payload["lease_expires_at"] = (now + timedelta(seconds=lease_seconds)).isoformat()
                leased.append(payload)
        return {"orders": leased, "total_count": len(leased), "stopped": False}

    def acknowledge_submitting(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        client_order_id: str,
        lease_token: str,
    ) -> dict[str, Any]:
        """Verify the lease and enter SUBMITTING before calling the broker API."""

        now = timezone.now()
        digest_invalid = False
        result: dict[str, Any] | None = None
        with transaction.atomic():
            order = (
                LiveOrderModel._default_manager.select_for_update(of=("self",))
                .select_related("lease")
                .filter(client_order_id=client_order_id, agent_id=agent_pk)
                .first()
            )
            if order is None:
                raise BrokerExecutionNotFoundError("Leased order does not exist")
            if order.account_id not in set(allowed_account_ids):
                raise BrokerAgentAuthenticationError("Order exceeds the credential account scope")
            lease = getattr(order, "lease", None)
            token_hash = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
            if (
                lease is None
                or lease.agent_id != agent_pk
                or lease.released_at is not None
                or lease.expires_at <= now
                or lease.lease_token_hash != token_hash
            ):
                raise BrokerExecutionConflictError("Order lease is invalid or expired")
            if TradingControlModel._default_manager.filter(
                user_id=order.user_id,
                account_id__in=[0, order.account_id],
                kill_switch_active=True,
            ).exists():
                raise BrokerExecutionConflictError("Trading is stopped")
            binding = BrokerAccountBindingModel._default_manager.filter(
                agent_id=agent_pk,
                account_id=order.account_id,
                is_active=True,
                auto_execution_enabled=True,
            ).first()
            if binding is None:
                raise BrokerExecutionConflictError("Live account binding is disabled")
            if order.expires_at is not None and order.expires_at <= now:
                raise BrokerExecutionConflictError("Order expired before broker submission")
            if binding.enforce_trading_session and not is_trading_session_open(
                timezone.localtime(now), binding.allowed_trading_windows or []
            ):
                raise BrokerExecutionConflictError("Trading session is closed")
            if not binding.allowed_symbols or order.asset_code not in set(binding.allowed_symbols):
                raise BrokerExecutionConflictError(
                    "Asset is no longer on the live execution allow-list"
                )
            if (
                binding.max_single_order_amount <= 0
                or order.estimated_amount > binding.max_single_order_amount
            ):
                raise BrokerExecutionConflictError("Order exceeds the current single-order limit")
            today_amount = LiveOrderModel._default_manager.filter(
                user_id=order.user_id,
                account_id=order.account_id,
                created_at__date=timezone.localdate(now),
            ).exclude(
                status__in=[
                    LiveOrderStatus.RISK_REJECTED.value,
                    LiveOrderStatus.REJECTED.value,
                    LiveOrderStatus.EXPIRED.value,
                ]
            ).aggregate(
                total=Sum("estimated_amount")
            )[
                "total"
            ] or Decimal(
                "0"
            )
            if (
                binding.daily_order_amount_limit <= 0
                or today_amount > binding.daily_order_amount_limit
            ):
                raise BrokerExecutionConflictError(
                    "Current live orders exceed the configured daily limit"
                )
            if not BrokerAccountSnapshotModel._default_manager.filter(
                agent_id=agent_pk,
                account_id=order.account_id,
                captured_at__gte=now - timedelta(seconds=binding.max_snapshot_age_seconds),
            ).exists():
                raise BrokerExecutionConflictError("Broker account snapshot is stale")
            latest_snapshot = (
                BrokerAccountSnapshotModel._default_manager.filter(
                    agent_id=agent_pk, account_id=order.account_id
                )
                .order_by("-captured_at")
                .first()
            )
            if latest_snapshot is None:
                raise BrokerExecutionConflictError("Broker account snapshot is unavailable")
            latest_positions = BrokerPositionSnapshotModel._default_manager.filter(
                agent_id=agent_pk,
                account_id=order.account_id,
                captured_at=latest_snapshot.captured_at,
            )
            if order.side == "BUY":
                if order.quantity % Decimal("100") != 0:
                    raise BrokerExecutionConflictError(
                        "A-share buy quantity must use 100-share lots"
                    )
                if latest_snapshot.cash_available < order.estimated_amount:
                    raise BrokerExecutionConflictError("Broker available cash is insufficient")
                held_symbols = set(
                    latest_positions.filter(quantity__gt=0).values_list("asset_code", flat=True)
                )
                if (
                    order.asset_code not in held_symbols
                    and len(held_symbols) >= binding.max_position_count
                ):
                    raise BrokerExecutionConflictError("Maximum position count would be exceeded")
            else:
                available_quantity = latest_positions.filter(
                    asset_code=order.asset_code
                ).values_list("available_quantity", flat=True).first() or Decimal("0")
                if available_quantity < order.quantity:
                    raise BrokerExecutionConflictError("Broker available position is insufficient")
            current = self._order_payload(order)
            if order.approval_digest != approval_digest_for_order(current):
                order.status = LiveOrderStatus.WAITING_APPROVAL.value
                order.approval_digest = ""
                order.approved_by = None
                order.approved_at = None
                order.version += 1
                order.save()
                digest_invalid = True
            else:
                validate_order_transition(order.status, LiveOrderStatus.SUBMITTING.value)
                order.status = LiveOrderStatus.SUBMITTING.value
                order.version += 1
                order.save(update_fields=["status", "version", "updated_at"])
                result = {"accepted": True, "order": self._order_payload(order)}
        if digest_invalid:
            raise BrokerExecutionConflictError("Order approval digest is no longer valid")
        if result is None:
            raise BrokerExecutionConflictError("Order submission acknowledgement failed")
        return result

    @staticmethod
    def _parse_agent_datetime(raw: Any) -> datetime:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def report_agent_events(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply idempotent broker events and conservatively handle unknown outcomes."""

        accepted = 0
        duplicates = 0
        alerts: list[dict[str, Any]] = []
        for item in events:
            event_id = str(item.get("event_id") or "").strip()
            client_order_id = str(item.get("client_order_id") or "").strip()
            if not event_id or not client_order_id:
                raise BrokerExecutionConflictError("event_id and client_order_id are required")
            with transaction.atomic():
                order = (
                    LiveOrderModel._default_manager.select_for_update()
                    .filter(client_order_id=client_order_id, agent_id=agent_pk)
                    .first()
                )
                if order is None:
                    raise BrokerExecutionNotFoundError("Event order does not exist")
                if order.account_id not in set(allowed_account_ids):
                    raise BrokerAgentAuthenticationError(
                        "Event exceeds the credential account scope"
                    )
                if BrokerOrderEventModel._default_manager.filter(
                    agent_id=agent_pk,
                    event_id=event_id,
                ).exists():
                    duplicates += 1
                    continue
                target = str(item.get("status") or "").upper()
                if (
                    order.failure_code == "BROKER_OVERFILL"
                    and target
                    and target != LiveOrderStatus.RECONCILIATION_REQUIRED.value
                ):
                    target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                if target:
                    try:
                        validate_order_transition(order.status, target)
                    except ValueError:
                        if target not in LiveOrderStatus._value2member_map_:
                            target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                        elif order.status != target:
                            target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                        if (
                            order.status in {status.value for status in LiveOrderStatus}
                            and order.status != target
                        ):
                            try:
                                validate_order_transition(order.status, target)
                            except ValueError:
                                target = order.status
                BrokerOrderEventModel._default_manager.create(
                    agent_id=agent_pk,
                    order=order,
                    event_id=event_id,
                    event_type=str(item.get("event_type") or "UNKNOWN")[:64],
                    status=target,
                    payload=dict(item.get("payload") or {}),
                    occurred_at=self._parse_agent_datetime(item.get("occurred_at")),
                )
                if item.get("broker_order_id"):
                    order.broker_order_id = str(item["broker_order_id"])[:128]
                if target and target != order.status:
                    order.status = target
                if (
                    target
                    in {
                        LiveOrderStatus.SUBMITTED.value,
                        LiveOrderStatus.PARTIALLY_FILLED.value,
                        LiveOrderStatus.FILLED.value,
                        LiveOrderStatus.CANCEL_PENDING.value,
                        LiveOrderStatus.CANCELED.value,
                    }
                    and order.submitted_at is None
                ):
                    order.submitted_at = timezone.now()
                if (
                    target
                    in {
                        LiveOrderStatus.BROKER_REJECTED.value,
                        LiveOrderStatus.FAILED.value,
                        LiveOrderStatus.RECONCILIATION_REQUIRED.value,
                    }
                    and order.failure_code != "BROKER_OVERFILL"
                ):
                    event_payload = dict(item.get("payload") or {})
                    order.failure_code = str(item.get("event_type") or target)[:64]
                    order.failure_message = str(
                        event_payload.get("status_msg")
                        or event_payload.get("broker_message")
                        or event_payload.get("message")
                        or ""
                    )[:2000]
                fill = item.get("fill")
                if isinstance(fill, dict) and fill.get("broker_trade_id"):
                    quantity = Decimal(str(fill.get("quantity") or "0"))
                    price = Decimal(str(fill.get("price") or "0"))
                    if quantity <= 0 or price <= 0:
                        raise BrokerExecutionConflictError(
                            "Broker fill quantity and price must be positive"
                        )
                    binding = BrokerAccountBindingModel._default_manager.filter(
                        agent_id=agent_pk,
                        account_id=order.account_id,
                        is_active=True,
                    ).first()
                    if binding is None:
                        raise BrokerAgentAuthenticationError(
                            "Event account is not actively bound to this Agent"
                        )
                    persisted_fill, _created = BrokerFillModel._default_manager.get_or_create(
                        broker_account_ref=binding.broker_account_ref,
                        broker_trade_id=str(fill["broker_trade_id"])[:128],
                        defaults={
                            "order": order,
                            "agent_id": agent_pk,
                            "quantity": quantity,
                            "price": price,
                            "amount": quantity * price,
                            "occurred_at": self._parse_agent_datetime(
                                fill.get("occurred_at") or item.get("occurred_at")
                            ),
                            "payload": dict(fill.get("payload") or {}),
                        },
                    )
                    if persisted_fill.order_id != order.pk:
                        raise BrokerExecutionConflictError(
                            "Broker trade is already attached to another order"
                        )
                    totals = order.fills.aggregate(quantity=Sum("quantity"), amount=Sum("amount"))
                    order.filled_quantity = totals["quantity"] or Decimal("0")
                    if order.filled_quantity:
                        order.average_fill_price = (
                            totals["amount"] or Decimal("0")
                        ) / order.filled_quantity
                    if order.filled_quantity > order.quantity:
                        target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                        order.status = target
                        order.failure_code = "BROKER_OVERFILL"
                        order.failure_message = (
                            "Broker cumulative fill quantity exceeds the approved order quantity"
                        )
                order.version += 1
                order.save()
                if target == LiveOrderStatus.RECONCILIATION_REQUIRED.value:
                    is_overfill = order.failure_code == "BROKER_OVERFILL"
                    alerts.append(
                        self._upsert_operational_alert(
                            user_id=order.user_id,
                            account_id=order.account_id,
                            code=(
                                "P0_BROKER_OVERFILL" if is_overfill else "P0_ORDER_OUTCOME_UNKNOWN"
                            ),
                            severity="P0",
                            title=(
                                "券商累计成交超过批准数量，已自动停止新单"
                                if is_overfill
                                else "实盘订单结果未知，已自动停止新单"
                            ),
                            message=(
                                f"订单 {order.client_order_id} 出现超额成交，必须立即核验券商事实。"
                                if is_overfill
                                else f"订单 {order.client_order_id} 必须先查询券商事实并完成对账。"
                            ),
                            resource_key=str(order.client_order_id),
                            payload={"client_order_id": str(order.client_order_id)},
                            auto_stop=True,
                        )
                    )
                accepted += 1
        return {
            "accepted_count": accepted,
            "duplicate_count": duplicates,
            "alerts": alerts,
        }

    def sync_agent_snapshot(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one account snapshot and its normalized positions."""

        agent = BrokerAgentModel._default_manager.get(pk=agent_pk, is_active=True)
        account_id = int(payload.get("account_id") or 0)
        if account_id not in set(allowed_account_ids):
            raise BrokerAgentAuthenticationError("Snapshot exceeds the credential account scope")
        if not agent.account_bindings.filter(account_id=account_id, is_active=True).exists():
            raise BrokerAgentAuthenticationError("Snapshot account is not bound to this Agent")
        captured_at = self._parse_agent_datetime(payload.get("captured_at"))
        if captured_at > timezone.now() + timedelta(minutes=5):
            raise BrokerExecutionConflictError("Broker snapshot timestamp is too far in the future")
        with transaction.atomic():
            BrokerAccountSnapshotModel._default_manager.update_or_create(
                agent=agent,
                account_id=account_id,
                captured_at=captured_at,
                defaults={
                    "user_id": agent.user_id,
                    "cash_available": Decimal(str(payload.get("cash_available") or "0")),
                    "total_asset": Decimal(str(payload.get("total_asset") or "0")),
                    "payload": dict(payload.get("payload") or {})
                    | {
                        "orders": list(payload.get("orders") or []),
                        "trades": list(payload.get("trades") or []),
                    },
                },
            )
            for position in payload.get("positions", []):
                BrokerPositionSnapshotModel._default_manager.update_or_create(
                    agent=agent,
                    account_id=account_id,
                    asset_code=str(position.get("asset_code") or "")[:32],
                    captured_at=captured_at,
                    defaults={
                        "user_id": agent.user_id,
                        "quantity": Decimal(str(position.get("quantity") or "0")),
                        "available_quantity": Decimal(
                            str(position.get("available_quantity") or "0")
                        ),
                        "payload": dict(position.get("payload") or {}),
                    },
                )
        return {"accepted": True, "captured_at": captured_at.isoformat()}

    def lease_agent_commands(
        self, *, agent_pk: int, allowed_account_ids: list[int], limit: int
    ) -> dict[str, Any]:
        """Lease pending commands for delivery to one Agent."""

        rows: list[dict[str, Any]] = []
        now = timezone.now()
        with transaction.atomic():
            BrokerCommandModel._default_manager.filter(
                agent_id=agent_pk,
                status="leased",
                leased_at__lt=now - timedelta(minutes=2),
            ).update(status="pending", leased_at=None)
            commands = list(
                BrokerCommandModel._default_manager.select_for_update()
                .filter(agent_id=agent_pk, status="pending")
                .filter(Q(account_id=0) | Q(account_id__in=allowed_account_ids))
                .order_by("created_at")[:limit]
            )
            for command in commands:
                command.status = "leased"
                command.leased_at = now
                command.save(update_fields=["status", "leased_at"])
                rows.append(
                    {
                        "command_id": str(command.command_id),
                        "command_type": command.command_type,
                        "account_id": command.account_id,
                        "payload": command.payload or {},
                        "created_at": command.created_at.isoformat(),
                    }
                )
        return {"commands": rows, "total_count": len(rows)}

    def complete_agent_command(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        command_id: str,
        success: bool,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Complete one leased command and normalize cancel acknowledgement."""

        with transaction.atomic():
            command = (
                BrokerCommandModel._default_manager.select_for_update()
                .filter(command_id=command_id, agent_id=agent_pk)
                .first()
            )
            if command is None:
                raise BrokerExecutionNotFoundError("Agent command does not exist")
            if command.account_id and command.account_id not in set(allowed_account_ids):
                raise BrokerAgentAuthenticationError("Command exceeds the credential account scope")
            if command.status in {"completed", "failed"}:
                return {
                    "accepted": True,
                    "status": command.status,
                    "idempotent_replay": True,
                }
            if command.status != "leased":
                raise BrokerExecutionConflictError("Agent command is not leased")
            command.status = "completed" if success else "failed"
            command.completed_at = timezone.now()
            command.payload = dict(command.payload or {}) | {"result": result}
            command.save(update_fields=["status", "completed_at", "payload"])
            client_order_id = str(command.payload.get("client_order_id") or "")
            audit_account_id = command.account_id
            audit_resource_type = "broker_command"
            audit_resource_id = str(command.command_id)
            audit_before: dict[str, Any] = {"status": "leased"}
            audit_after: dict[str, Any] = {
                "status": command.status,
                "result": result,
            }
            if command.command_type == "cancel" and client_order_id:
                order = (
                    LiveOrderModel._default_manager.select_for_update()
                    .filter(client_order_id=client_order_id, agent_id=agent_pk)
                    .first()
                )
                if order is not None and order.status == LiveOrderStatus.CANCEL_PENDING.value:
                    audit_account_id = order.account_id
                    audit_resource_type = "live_order"
                    audit_resource_id = str(order.client_order_id)
                    audit_before = {"status": order.status}
                    if not success:
                        target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                        validate_order_transition(order.status, target)
                        order.status = target
                        order.version += 1
                        order.save(update_fields=["status", "version", "updated_at"])
                    audit_after = {
                        "status": order.status,
                        "command_status": command.status,
                        "awaiting_broker_final_status": success,
                        "result": result,
                    }
            BrokerExecutionAuditModel._default_manager.create(
                user_id=command.agent.user_id,
                actor=None,
                actor_type="agent",
                action=f"agent_command_{command.command_type}_{command.status}",
                account_id=audit_account_id,
                resource_type=audit_resource_type,
                resource_id=audit_resource_id,
                before=audit_before,
                after=audit_after,
                reason="Agent command completion",
                request_id=str(command.command_id),
            )
            return {"accepted": True, "status": command.status}

    def upsert_agent_binding(
        self,
        *,
        actor_id: int,
        payload: dict[str, Any],
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        """Create/update an Agent and account binding with a full audit record."""

        action = "binding_upserted"
        replay = self._replay_or_conflict(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        user_id = int(payload["user_id"])
        account_id = int(payload["account_id"])
        agent_id = str(payload["agent_id"]).strip()
        with transaction.atomic():
            conflicting_binding = (
                BrokerAccountBindingModel._default_manager.filter(
                    account_id=account_id,
                )
                .exclude(user_id=user_id)
                .first()
            )
            if conflicting_binding is not None:
                raise BrokerExecutionConflictError(
                    "The system account is already bound to another owner"
                )
            existing_binding = BrokerAccountBindingModel._default_manager.filter(
                user_id=user_id,
                account_id=account_id,
            ).first()
            if not bool(payload.get("is_active", True)) and existing_binding is None:
                raise BrokerExecutionNotFoundError("Broker account binding does not exist")
            agent, _created = BrokerAgentModel._default_manager.get_or_create(
                agent_id=agent_id,
                defaults={
                    "user_id": user_id,
                    "display_name": str(payload.get("display_name") or agent_id)[:100],
                },
            )
            if agent.user_id != user_id:
                raise BrokerExecutionConflictError("Agent is already owned by another user")
            binding, created = BrokerAccountBindingModel._default_manager.get_or_create(
                user_id=user_id,
                account_id=account_id,
                defaults={
                    "agent": agent,
                    "broker_account_ref": str(payload.get("broker_account_ref") or ""),
                },
            )
            before = (
                {}
                if created
                else {
                    "agent_id": binding.agent.agent_id,
                    "broker_account_mask": binding.broker_account_mask,
                    "account_type": binding.account_type,
                    "is_active": binding.is_active,
                }
            )
            binding.agent = agent
            if payload.get("broker_account_ref"):
                binding.broker_account_ref = str(payload["broker_account_ref"])[:128]
            if "broker_account_mask" in payload:
                binding.broker_account_mask = str(payload.get("broker_account_mask") or "")[:32]
            if "account_type" in payload:
                binding.account_type = str(payload.get("account_type") or "STOCK")[:32]
            binding.is_active = bool(payload.get("is_active", True))
            binding.save()
            after = {
                "agent_id": agent.agent_id,
                "account_id": account_id,
                "broker_account_mask": binding.broker_account_mask,
                "account_type": binding.account_type,
                "is_active": binding.is_active,
            }
            BrokerExecutionAuditModel._default_manager.create(
                user_id=user_id,
                actor_id=actor_id,
                action=action,
                account_id=account_id,
                resource_type="broker_account_binding",
                resource_id=str(binding.pk),
                before=before,
                after=after,
                reason=str(payload.get("reason") or ""),
            )
            result = {"success": True, "preview_only": False, "binding": after}
            self._save_idempotent_result(
                user_id=actor_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                payload=result,
            )
            return result

    @transaction.atomic
    def upsert_account_access(
        self,
        *,
        actor_id: int,
        payload: dict[str, Any],
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        """Create, update, or revoke an account grant with append-only audit."""

        action = "account_access_updated"
        replay = self._replay_or_conflict(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        target_user_id = int(payload["user_id"])
        account_id = int(payload["account_id"])
        user_model = BrokerAccountAccessModel._meta.get_field("user").remote_field.model
        if not user_model._default_manager.filter(pk=target_user_id).exists():
            raise BrokerExecutionNotFoundError("Target user does not exist")
        binding = BrokerAccountBindingModel._default_manager.filter(
            account_id=account_id,
            is_active=True,
        ).first()
        if binding is None:
            raise BrokerExecutionNotFoundError("Active broker account binding does not exist")
        grant = BrokerAccountAccessModel._default_manager.filter(
            user_id=target_user_id,
            account_id=account_id,
        ).first()
        if grant is None and not bool(payload.get("is_active", True)):
            raise BrokerExecutionNotFoundError("Account access grant does not exist")
        before = (
            {}
            if grant is None
            else {
                "can_approve": grant.can_approve,
                "can_trade": grant.can_trade,
                "is_active": grant.is_active,
                "granted_by_id": grant.granted_by_id,
            }
        )
        grant, _created = BrokerAccountAccessModel._default_manager.update_or_create(
            user_id=target_user_id,
            account_id=account_id,
            defaults={
                "can_approve": bool(payload.get("can_approve", False)),
                "can_trade": bool(payload.get("can_trade", False)),
                "is_active": bool(payload.get("is_active", True)),
                "granted_by_id": actor_id,
            },
        )
        after = {
            "user_id": grant.user_id,
            "account_id": grant.account_id,
            "can_approve": grant.can_approve,
            "can_trade": grant.can_trade,
            "is_active": grant.is_active,
            "granted_by_id": grant.granted_by_id,
        }
        BrokerExecutionAuditModel._default_manager.create(
            user_id=binding.user_id,
            actor_id=actor_id,
            action=action,
            account_id=account_id,
            resource_type="broker_account_access",
            resource_id=str(grant.pk),
            before=before,
            after=after,
            reason=str(payload.get("reason") or ""),
        )
        result = {
            "success": True,
            "preview_only": False,
            "access_grant": after,
        }
        self._save_idempotent_result(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            payload=result,
        )
        return result

    @transaction.atomic
    def rotate_agent_credential(
        self,
        *,
        actor_id: int,
        agent_id: str,
        scopes: list[str],
        allowed_account_ids: list[int],
        expires_at: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        """Issue a credential and return the raw token exactly once."""

        action = "agent_credential_rotated"
        replay = self._replay_or_conflict(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        agent = (
            BrokerAgentModel._default_manager.select_for_update()
            .filter(agent_id=agent_id, is_active=True)
            .first()
        )
        if agent is None:
            raise BrokerExecutionNotFoundError("Agent does not exist")
        active_account_ids = set(
            BrokerAccountBindingModel._default_manager.select_for_update()
            .filter(
                agent=agent,
                account_id__in=allowed_account_ids,
                is_active=True,
            )
            .order_by("account_id")
            .values_list("account_id", flat=True)
        )
        if active_account_ids != set(allowed_account_ids):
            raise BrokerExecutionConflictError(
                "Credential scope contains an inactive or unbound Agent account"
            )
        replay = self._replay_or_conflict(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        parsed_expiry = self._parse_agent_datetime(expires_at)
        if parsed_expiry <= timezone.now():
            raise BrokerExecutionConflictError("Credential expiry must be in the future")
        secret = secrets.token_urlsafe(32)
        credential = BrokerAgentCredentialModel._default_manager.create(
            agent=agent,
            secret_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            scopes=scopes,
            allowed_account_ids=allowed_account_ids,
            expires_at=parsed_expiry,
            created_by_id=actor_id,
        )
        BrokerExecutionAuditModel._default_manager.create(
            user_id=agent.user_id,
            actor_id=actor_id,
            action=action,
            resource_type="agent_credential",
            resource_id=str(credential.credential_id),
            after={
                "agent_id": agent.agent_id,
                "scopes": scopes,
                "allowed_account_ids": allowed_account_ids,
                "expires_at": expires_at,
            },
        )
        result = {
            "credential_id": str(credential.credential_id),
            "agent_id": agent.agent_id,
            "token": f"{credential.credential_id}.{secret}",
            "scopes": scopes,
            "allowed_account_ids": allowed_account_ids,
            "expires_at": credential.expires_at.isoformat(),
            "shown_once": True,
        }
        self._save_idempotent_result(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            payload={**result, "token": "", "shown_once": False},
        )
        return result

    @transaction.atomic
    def revoke_agent_credential(
        self,
        *,
        actor_id: int,
        credential_id: str,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        """Revoke a credential immediately and audit the action."""

        action = "agent_credential_revoked"
        replay = self._replay_or_conflict(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        credential = (
            BrokerAgentCredentialModel._default_manager.select_related("agent")
            .filter(credential_id=credential_id)
            .first()
        )
        if credential is None:
            raise BrokerExecutionNotFoundError("Agent credential does not exist")
        if credential.revoked_at is None:
            credential.revoked_at = timezone.now()
            credential.save(update_fields=["revoked_at"])
        BrokerExecutionAuditModel._default_manager.create(
            user_id=credential.agent.user_id,
            actor_id=actor_id,
            action=action,
            resource_type="agent_credential",
            resource_id=str(credential.credential_id),
            after={"revoked_at": credential.revoked_at.isoformat()},
            reason=reason,
        )
        result = {"credential_id": str(credential.credential_id), "revoked": True}
        self._save_idempotent_result(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            payload=result,
        )
        return result

    @transaction.atomic
    def enqueue_agent_sync_command(
        self,
        *,
        actor_id: int,
        agent_id: str,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        """Enqueue one idempotent full-sync command for an active bound Agent."""

        action = "agent_full_sync_requested"
        replay = self._replay_or_conflict(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        agent = (
            BrokerAgentModel._default_manager.filter(
                agent_id=agent_id,
                is_active=True,
                account_bindings__is_active=True,
            )
            .distinct()
            .first()
        )
        if agent is None:
            raise BrokerExecutionNotFoundError("Active bound Agent does not exist")
        command = BrokerCommandModel._default_manager.create(
            agent=agent,
            command_type="full_sync",
            account_id=0,
            payload={"reason": reason, "requested_by": actor_id},
        )
        BrokerExecutionAuditModel._default_manager.create(
            user_id=agent.user_id,
            actor_id=actor_id,
            action=action,
            account_id=0,
            resource_type="broker_agent",
            resource_id=agent.agent_id,
            after={
                "command_id": str(command.command_id),
                "command_type": command.command_type,
            },
            reason=reason,
            request_id=idempotency_key,
        )
        result = {
            "success": True,
            "preview_only": False,
            "agent_id": agent.agent_id,
            "command_id": str(command.command_id),
            "command_status": command.status,
        }
        self._save_idempotent_result(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            payload=result,
        )
        return result

    @transaction.atomic
    def update_account_settings(
        self,
        *,
        actor_id: int,
        account_id: int,
        payload: dict[str, Any],
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        """Update bounded execution settings for a single active binding."""

        action = "execution_settings_updated"
        replay = self._replay_or_conflict(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        binding = (
            BrokerAccountBindingModel._default_manager.select_for_update()
            .filter(account_id=account_id, is_active=True)
            .first()
        )
        if binding is None:
            raise BrokerExecutionNotFoundError("Broker account binding does not exist")
        replay = self._replay_or_conflict(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        before = {
            "auto_execution_enabled": binding.auto_execution_enabled,
            "max_single_order_amount": str(binding.max_single_order_amount),
            "daily_order_amount_limit": str(binding.daily_order_amount_limit),
            "allowed_symbols": binding.allowed_symbols or [],
            "max_position_count": binding.max_position_count,
            "max_snapshot_age_seconds": binding.max_snapshot_age_seconds,
            "price_deviation_limit_pct": str(binding.price_deviation_limit_pct),
            "allowed_trading_windows": binding.allowed_trading_windows or [],
            "enforce_trading_session": binding.enforce_trading_session,
        }
        for field in ("max_single_order_amount", "daily_order_amount_limit"):
            if field in payload:
                try:
                    value = Decimal(str(payload[field]))
                except (InvalidOperation, ValueError) as exc:
                    raise BrokerExecutionConflictError(f"{field} must be numeric") from exc
                if not value.is_finite() or value < 0:
                    raise BrokerExecutionConflictError(
                        f"{field} must be a non-negative finite number"
                    )
                setattr(binding, field, value)
        if "price_deviation_limit_pct" in payload:
            try:
                price_deviation = Decimal(str(payload["price_deviation_limit_pct"]))
            except (InvalidOperation, ValueError) as exc:
                raise BrokerExecutionConflictError(
                    "price_deviation_limit_pct must be numeric"
                ) from exc
            if not price_deviation.is_finite() or not 0 <= price_deviation <= 1:
                raise BrokerExecutionConflictError(
                    "price_deviation_limit_pct must be between 0 and 1"
                )
            binding.price_deviation_limit_pct = price_deviation
        for field in ("max_position_count", "max_snapshot_age_seconds"):
            if field in payload:
                try:
                    integer_value = int(payload[field])
                except (TypeError, ValueError, OverflowError) as exc:
                    raise BrokerExecutionConflictError(f"{field} must be an integer") from exc
                if integer_value <= 0:
                    raise BrokerExecutionConflictError(f"{field} must be positive")
                setattr(binding, field, integer_value)
        if "allowed_trading_windows" in payload:
            binding.allowed_trading_windows = list(payload["allowed_trading_windows"])
        if "enforce_trading_session" in payload:
            if not isinstance(payload["enforce_trading_session"], bool):
                raise BrokerExecutionConflictError("enforce_trading_session must be boolean")
            binding.enforce_trading_session = payload["enforce_trading_session"]
        if "allowed_symbols" in payload:
            binding.allowed_symbols = sorted(
                {
                    str(item).strip().upper()
                    for item in payload["allowed_symbols"]
                    if str(item).strip()
                }
            )
        if "auto_execution_enabled" in payload:
            if not isinstance(payload["auto_execution_enabled"], bool):
                raise BrokerExecutionConflictError("auto_execution_enabled must be boolean")
            binding.auto_execution_enabled = payload["auto_execution_enabled"]
        binding.save()
        after = {
            "account_id": account_id,
            "auto_execution_enabled": binding.auto_execution_enabled,
            "max_single_order_amount": str(binding.max_single_order_amount),
            "daily_order_amount_limit": str(binding.daily_order_amount_limit),
            "allowed_symbols": binding.allowed_symbols or [],
            "max_position_count": binding.max_position_count,
            "max_snapshot_age_seconds": binding.max_snapshot_age_seconds,
            "price_deviation_limit_pct": str(binding.price_deviation_limit_pct),
            "allowed_trading_windows": binding.allowed_trading_windows or [],
            "enforce_trading_session": binding.enforce_trading_session,
        }
        BrokerExecutionAuditModel._default_manager.create(
            user_id=binding.user_id,
            actor_id=actor_id,
            action=action,
            account_id=account_id,
            resource_type="broker_account_binding",
            resource_id=str(binding.pk),
            before=before,
            after=after,
            reason=str(payload.get("reason") or ""),
        )
        result = {"success": True, "preview_only": False, "settings": after}
        self._save_idempotent_result(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            payload=result,
        )
        return result

    def resolve_reconciliation(
        self,
        *,
        actor_id: int,
        is_admin: bool,
        run_id: int,
        resolution: str,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        """Resolve one reconciliation batch with idempotency and audit."""

        action = "resolve_reconciliation"
        replay = self._replay_or_conflict(
            user_id=actor_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        with transaction.atomic():
            run = (
                ReconciliationRunModel._default_manager.select_for_update()
                .filter(pk=run_id)
                .first()
            )
            if run is None:
                raise BrokerExecutionNotFoundError("Reconciliation run does not exist")
            if not self.has_account_access(
                user_id=actor_id,
                is_admin=is_admin,
                account_id=run.account_id,
                action="trade",
            ):
                raise BrokerExecutionPermissionError("Reconciliation account is not authorized")
            if run.status in {"resolved", "completed"}:
                raise BrokerExecutionConflictError("Reconciliation run is already closed")
            before = {"status": run.status, "summary": run.summary or {}}
            is_escalation = resolution == "escalate"
            run.status = "escalated" if is_escalation else "resolved"
            run.summary = dict(run.summary or {}) | {
                "resolution": resolution,
                "resolution_reason": reason,
                "resolved_by": actor_id,
            }
            run.completed_at = None if is_escalation else timezone.now()
            run.save(update_fields=["status", "summary", "completed_at"])
            run.differences.filter(status__in=["open", "escalated"]).update(
                status="escalated" if is_escalation else "resolved"
            )
            if not is_escalation:
                BrokerExecutionAlertModel._default_manager.filter(
                    user_id=run.user_id,
                    account_id=run.account_id,
                    code="P0_RECONCILIATION_DIFFERENCE",
                    status="open",
                    payload__run_id=run.pk,
                ).update(status="resolved")
            after = {"status": run.status, "summary": run.summary}
            BrokerExecutionAuditModel._default_manager.create(
                user_id=run.user_id,
                actor_id=actor_id,
                action=action,
                account_id=run.account_id,
                resource_type="reconciliation_run",
                resource_id=str(run.pk),
                before=before,
                after=after,
                reason=reason,
                request_id=idempotency_key,
            )
            result = {"success": True, "preview_only": False, "run_id": run.pk, **after}
            self._save_idempotent_result(
                user_id=actor_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                payload=result,
            )
            return result

    def run_maintenance(self) -> dict[str, Any]:
        """Expire stale orders/leases and mark missing heartbeats offline."""

        now = timezone.now()
        stale_before = now - timedelta(seconds=90)
        stale_agents = BrokerAgentModel._default_manager.filter(
            is_active=True,
            last_heartbeat_at__lt=stale_before,
        ).exclude(status=BrokerAgentModel.STATUS_OFFLINE)
        stale_agent_rows = list(stale_agents.prefetch_related("account_bindings"))
        stale_agent_count = stale_agents.update(
            status=BrokerAgentModel.STATUS_OFFLINE, qmt_connected=False
        )
        alerts = []
        for agent in stale_agent_rows:
            for binding in agent.account_bindings.all():
                if not binding.is_active:
                    continue
                alerts.append(
                    self._upsert_operational_alert(
                        user_id=binding.user_id,
                        account_id=binding.account_id,
                        code="P1_QMT_AGENT_OFFLINE",
                        severity="P1",
                        title="本地 QMT Agent 心跳超时",
                        message=f"Agent {agent.agent_id} 已超过 90 秒没有有效心跳。",
                        resource_key=agent.agent_id,
                        payload={"agent_id": agent.agent_id},
                    )
                )
        expired_orders = LiveOrderModel._default_manager.filter(
            status__in=[
                LiveOrderStatus.WAITING_APPROVAL.value,
                LiveOrderStatus.READY.value,
                LiveOrderStatus.LEASED.value,
            ],
            expires_at__lte=now,
        )
        expired_order_count = expired_orders.update(
            status=LiveOrderStatus.EXPIRED.value,
            version=F("version") + 1,
        )
        released_lease_count = OrderLeaseModel._default_manager.filter(
            released_at__isnull=True, expires_at__lte=now
        ).update(released_at=now)
        BrokerAgentNonceModel._default_manager.filter(seen_at__lt=now - timedelta(hours=1)).delete()
        return {
            "stale_agents": stale_agent_count,
            "expired_orders": expired_order_count,
            "released_leases": released_lease_count,
            "alerts": alerts,
            "completed_at": now.isoformat(),
        }

    def list_reconciliation_targets(self) -> list[dict[str, int]]:
        """Return active account owners for application-level ledger projection."""

        return [
            {"user_id": row["user_id"], "account_id": row["account_id"]}
            for row in BrokerAccountBindingModel._default_manager.filter(is_active=True)
            .values("user_id", "account_id")
            .order_by("user_id", "account_id")
        ]

    @staticmethod
    def _reconciliation_fingerprint(*, snapshot_id: int, projection: dict[str, Any] | None) -> str:
        projection_key = {
            "cash": str((projection or {}).get("cash_available") or ""),
            "total": str((projection or {}).get("total_asset") or ""),
            "positions": sorted(
                (
                    str(item.get("asset_code") or "").upper(),
                    str(item.get("quantity") or "0"),
                )
                for item in (projection or {}).get("positions", [])
            ),
        }
        digest = hashlib.sha256(repr(projection_key).encode("utf-8")).hexdigest()[:24]
        return f"snapshot:{snapshot_id}:{digest}"

    @staticmethod
    def _difference(
        dimension: str,
        difference_key: str,
        *,
        severity: str,
        expected: dict[str, Any],
        actual: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "dimension": dimension,
            "difference_key": difference_key[:160],
            "severity": severity,
            "expected": expected,
            "actual": actual,
            "reason": reason,
        }

    def _collect_reconciliation_differences(
        self,
        *,
        binding: BrokerAccountBindingModel,
        snapshot: BrokerAccountSnapshotModel,
        projection: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        differences: list[dict[str, Any]] = []
        snapshot_payload = snapshot.payload or {}
        broker_orders = list(snapshot_payload.get("orders") or [])
        broker_trades = list(snapshot_payload.get("trades") or [])
        server_orders = list(
            LiveOrderModel._default_manager.filter(
                user_id=binding.user_id,
                account_id=binding.account_id,
                created_at__date=timezone.localdate(snapshot.captured_at),
            ).exclude(
                status__in=[
                    LiveOrderStatus.WAITING_APPROVAL.value,
                    LiveOrderStatus.READY.value,
                    LiveOrderStatus.REJECTED.value,
                    LiveOrderStatus.RISK_REJECTED.value,
                    LiveOrderStatus.EXPIRED.value,
                ]
            )
        )
        by_broker_id = {
            str(row.get("broker_order_id") or ""): row
            for row in broker_orders
            if row.get("broker_order_id")
        }
        by_client_id = {
            str(row.get("client_order_id") or ""): row
            for row in broker_orders
            if row.get("client_order_id")
        }
        server_client_ids = {str(order.client_order_id) for order in server_orders}
        server_broker_ids = {
            order.broker_order_id for order in server_orders if order.broker_order_id
        }
        for order in server_orders:
            broker_order = by_broker_id.get(order.broker_order_id) or by_client_id.get(
                str(order.client_order_id)
            )
            if broker_order is None:
                differences.append(
                    self._difference(
                        "order",
                        str(order.client_order_id),
                        severity="P0",
                        expected={
                            "client_order_id": str(order.client_order_id),
                            "broker_order_id": order.broker_order_id,
                            "status": order.status,
                        },
                        actual={},
                        reason="VPS order is absent from the QMT current-day order snapshot",
                    )
                )
                continue
            broker_status = str(broker_order.get("status") or "")
            if broker_status and broker_status != order.status:
                differences.append(
                    self._difference(
                        "order",
                        str(order.client_order_id),
                        severity="P1",
                        expected={"status": order.status},
                        actual={"status": broker_status},
                        reason="VPS and QMT order statuses differ",
                    )
                )
        for row in broker_orders:
            client_id = str(row.get("client_order_id") or "")
            broker_id = str(row.get("broker_order_id") or "")
            if client_id not in server_client_ids and broker_id not in server_broker_ids:
                differences.append(
                    self._difference(
                        "order",
                        broker_id or client_id or "unidentified-order",
                        severity="P0",
                        expected={},
                        actual={"broker_order_id": broker_id, "client_order_id": client_id},
                        reason="QMT contains an order unknown to the VPS ledger",
                    )
                )

        server_trade_ids = set(
            BrokerFillModel._default_manager.filter(
                order__user_id=binding.user_id,
                order__account_id=binding.account_id,
                occurred_at__date=timezone.localdate(snapshot.captured_at),
            ).values_list("broker_trade_id", flat=True)
        )
        broker_trade_ids = {
            str(row.get("broker_trade_id") or "")
            for row in broker_trades
            if row.get("broker_trade_id")
        }
        for trade_id in sorted(broker_trade_ids - server_trade_ids):
            differences.append(
                self._difference(
                    "fill",
                    trade_id,
                    severity="P0",
                    expected={},
                    actual={"broker_trade_id": trade_id},
                    reason="QMT trade is missing from the VPS fill ledger",
                )
            )
        for trade_id in sorted(server_trade_ids - broker_trade_ids):
            differences.append(
                self._difference(
                    "fill",
                    trade_id,
                    severity="P1",
                    expected={"broker_trade_id": trade_id},
                    actual={},
                    reason="VPS fill is absent from the QMT current-day trade snapshot",
                )
            )

        if projection is None:
            differences.append(
                self._difference(
                    "cash",
                    "unified-ledger-missing",
                    severity="P0",
                    expected={"account_id": binding.account_id},
                    actual={},
                    reason="Unified real-account projection is unavailable",
                )
            )
            return differences
        expected_cash = Decimal(str(projection.get("cash_available") or "0"))
        if abs(expected_cash - snapshot.cash_available) > Decimal("0.01"):
            differences.append(
                self._difference(
                    "cash",
                    "cash_available",
                    severity="P0",
                    expected={"cash_available": str(expected_cash)},
                    actual={"cash_available": str(snapshot.cash_available)},
                    reason="Unified ledger and QMT available cash differ",
                )
            )
        broker_positions = {
            row.asset_code.upper(): row
            for row in BrokerPositionSnapshotModel._default_manager.filter(
                agent=binding.agent,
                account_id=binding.account_id,
                captured_at=snapshot.captured_at,
            )
        }
        ledger_positions = {
            str(row.get("asset_code") or "").upper(): Decimal(str(row.get("quantity") or "0"))
            for row in projection.get("positions", [])
        }
        for symbol in sorted(set(broker_positions) | set(ledger_positions)):
            broker_quantity = (
                broker_positions[symbol].quantity if symbol in broker_positions else Decimal("0")
            )
            ledger_quantity = ledger_positions.get(symbol, Decimal("0"))
            if abs(broker_quantity - ledger_quantity) > Decimal("0.0001"):
                differences.append(
                    self._difference(
                        "position",
                        symbol,
                        severity="P0",
                        expected={"quantity": str(ledger_quantity)},
                        actual={"quantity": str(broker_quantity)},
                        reason="Unified ledger and QMT position quantities differ",
                    )
                )
        return differences

    def generate_reconciliation_runs(
        self, *, account_projections: dict[int, dict[str, Any] | None] | None = None
    ) -> dict[str, Any]:
        """Persist idempotent order/fill/cash/position reconciliation evidence."""

        now = timezone.now()
        projections = account_projections or {}
        created = 0
        duplicate = 0
        alert_payloads: list[dict[str, Any]] = []
        for binding in BrokerAccountBindingModel._default_manager.select_related("agent").filter(
            is_active=True
        ):
            snapshot = (
                BrokerAccountSnapshotModel._default_manager.filter(
                    agent=binding.agent, account_id=binding.account_id
                )
                .order_by("-captured_at")
                .first()
            )
            if snapshot is None:
                continue
            projection = projections.get(binding.account_id)
            run_key = self._reconciliation_fingerprint(
                snapshot_id=snapshot.pk, projection=projection
            )
            if ReconciliationRunModel._default_manager.filter(run_key=run_key).exists():
                duplicate += 1
                continue
            differences = self._collect_reconciliation_differences(
                binding=binding,
                snapshot=snapshot,
                projection=projection,
            )
            counts = {
                dimension: sum(1 for row in differences if row["dimension"] == dimension)
                for dimension in ("order", "fill", "cash", "position")
            }
            has_p0 = any(row["severity"] == "P0" for row in differences)
            with transaction.atomic():
                run = ReconciliationRunModel._default_manager.create(
                    user_id=binding.user_id,
                    account_id=binding.account_id,
                    run_key=run_key,
                    status="review_required" if differences else "completed",
                    order_difference_count=counts["order"],
                    fill_difference_count=counts["fill"],
                    cash_difference_count=counts["cash"],
                    position_difference_count=counts["position"],
                    started_at=now,
                    completed_at=None if differences else now,
                    summary={
                        "source": "qmt_snapshot_reconciliation",
                        "snapshot_id": snapshot.pk,
                        "snapshot_captured_at": snapshot.captured_at.isoformat(),
                        "difference_count": len(differences),
                        "p0_auto_stop": has_p0,
                    },
                )
                ReconciliationDifferenceModel._default_manager.bulk_create(
                    [ReconciliationDifferenceModel(run=run, **row) for row in differences]
                )
                if has_p0:
                    control, _ = TradingControlModel._default_manager.get_or_create(
                        user_id=binding.user_id,
                        account_id=binding.account_id,
                        defaults={"changed_by_id": None},
                    )
                    control.kill_switch_active = True
                    control.reason = f"P0 reconciliation difference in run {run.pk}"
                    control.changed_by_id = None
                    control.save()
                    fingerprint = hashlib.sha256(
                        f"P0_RECON:{binding.user_id}:{binding.account_id}:{run_key}".encode()
                    ).hexdigest()
                    alert, alert_created = BrokerExecutionAlertModel._default_manager.get_or_create(
                        fingerprint=fingerprint,
                        defaults={
                            "user_id": binding.user_id,
                            "account_id": binding.account_id,
                            "code": "P0_RECONCILIATION_DIFFERENCE",
                            "severity": "P0",
                            "title": "实盘对账出现 P0 差异，已自动停止新单",
                            "message": f"对账批次 {run.pk} 发现 {len(differences)} 项差异。",
                            "payload": {"run_id": run.pk, "counts": counts},
                            "auto_stop_applied": True,
                        },
                    )
                    if not alert_created:
                        alert.occurrence_count = F("occurrence_count") + 1
                        alert.save(update_fields=["occurrence_count", "last_seen_at"])
                    alert_payloads.append(
                        {
                            "level": "critical",
                            "task_name": "broker_execution.generate_reconciliation_runs",
                            "title": alert.title,
                            "message": alert.message,
                            "metadata": {"run_id": run.pk, "account_id": binding.account_id},
                        }
                    )
                status = "critical" if has_p0 else "review" if differences else "ok"
                BrokerExecutionDailyReportModel._default_manager.update_or_create(
                    user_id=binding.user_id,
                    account_id=binding.account_id,
                    report_date=timezone.localdate(snapshot.captured_at),
                    defaults={
                        "status": status,
                        "metrics": {**counts, "difference_count": len(differences)},
                        "summary": {"latest_run_id": run.pk, "p0_auto_stop": has_p0},
                    },
                )
            created += 1
        return {
            "created_runs": created,
            "duplicate_runs": duplicate,
            "alerts": alert_payloads,
            "completed_at": now.isoformat(),
        }

    def create_live_order(
        self,
        *,
        user_id: int,
        is_admin: bool,
        payload: dict[str, Any],
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]:
        """Persist one bounded order intent assigned to the account's active Agent."""

        action = "create_live_order"
        replay = self._replay_or_conflict(
            user_id=user_id,
            action=action,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay is not None:
            return replay
        binding = (
            BrokerAccountBindingModel._default_manager.select_related("agent")
            .filter(account_id=int(payload["account_id"]), is_active=True, agent__is_active=True)
            .first()
        )
        if binding is None:
            raise BrokerExecutionConflictError("No active QMT Agent binding exists")
        if not is_admin and not self.has_account_access(
            user_id=user_id,
            is_admin=False,
            account_id=binding.account_id,
            action="trade",
        ):
            raise BrokerExecutionPermissionError("Account access is not authorized")
        symbol = str(payload["asset_code"]).strip().upper()
        if not binding.allowed_symbols or symbol not in set(binding.allowed_symbols):
            raise BrokerExecutionConflictError("Asset is not on the live execution allow-list")
        side = str(payload.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            raise BrokerExecutionConflictError("Order side must be BUY or SELL")
        source_recommendation_ids = [
            str(item)
            for item in (payload.get("source_recommendation_ids") or [])
            if str(item).strip()
        ]
        if not source_recommendation_ids:
            raise BrokerExecutionConflictError("Live order requires source recommendation evidence")
        expires_at = self._parse_agent_datetime(payload["expires_at"])
        if expires_at <= timezone.now():
            raise BrokerExecutionConflictError("Live order expiry must be in the future")
        quantity = Decimal(str(payload["quantity"]))
        price = Decimal(str(payload["limit_price"]))
        amount = (quantity * price).quantize(Decimal("0.01"))
        if quantity <= 0 or price <= 0 or quantity != quantity.to_integral_value():
            raise BrokerExecutionConflictError("Order quantity/price is invalid")
        if side == "BUY" and quantity % Decimal("100") != 0:
            raise BrokerExecutionConflictError("A-share buy quantity must use 100-share lots")
        market_snapshot = dict((payload.get("risk_snapshot") or {}).get("market_snapshot") or {})
        deviation = Decimal("0")
        if str(payload.get("initial_status")) != LiveOrderStatus.RISK_REJECTED.value:
            current_price = Decimal(str(market_snapshot.get("current_price") or "0"))
            if current_price <= 0 or market_snapshot.get("must_not_use_for_decision"):
                raise BrokerExecutionConflictError(
                    "A fresh positive server-side market quote is required"
                )
            if binding.price_deviation_limit_pct <= 0:
                raise BrokerExecutionConflictError(
                    "A positive price-deviation limit must be configured"
                )
            deviation = abs(price - current_price) / current_price
            if deviation > binding.price_deviation_limit_pct:
                raise BrokerExecutionConflictError(
                    "Order price exceeds the configured market-price deviation"
                )
        if binding.max_single_order_amount <= 0 or amount > binding.max_single_order_amount:
            raise BrokerExecutionConflictError("Order exceeds the configured single-order limit")
        with transaction.atomic():
            binding = (
                BrokerAccountBindingModel._default_manager.select_for_update()
                .select_related("agent")
                .filter(pk=binding.pk, is_active=True, agent__is_active=True)
                .first()
            )
            if binding is None:
                raise BrokerExecutionConflictError(
                    "The active QMT Agent binding changed before order creation"
                )
            replay = self._replay_or_conflict(
                user_id=user_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replay is not None:
                return replay
            if not is_admin and not self.has_account_access(
                user_id=user_id,
                is_admin=False,
                account_id=binding.account_id,
                action="trade",
            ):
                raise BrokerExecutionPermissionError("Account access changed before order creation")
            if not binding.allowed_symbols or symbol not in set(binding.allowed_symbols):
                raise BrokerExecutionConflictError("Asset is not on the live execution allow-list")
            if binding.max_single_order_amount <= 0 or amount > binding.max_single_order_amount:
                raise BrokerExecutionConflictError(
                    "Order exceeds the configured single-order limit"
                )
            if str(payload.get("initial_status")) != LiveOrderStatus.RISK_REJECTED.value:
                if binding.price_deviation_limit_pct <= 0:
                    raise BrokerExecutionConflictError(
                        "A positive price-deviation limit must be configured"
                    )
                if deviation > binding.price_deviation_limit_pct:
                    raise BrokerExecutionConflictError(
                        "Order price exceeds the configured market-price deviation"
                    )

            today_amount = LiveOrderModel._default_manager.filter(
                user_id=binding.user_id,
                account_id=binding.account_id,
                created_at__date=timezone.localdate(),
            ).exclude(
                status__in=[
                    LiveOrderStatus.RISK_REJECTED.value,
                    LiveOrderStatus.REJECTED.value,
                    LiveOrderStatus.EXPIRED.value,
                ]
            ).aggregate(
                total=Sum("estimated_amount")
            )[
                "total"
            ] or Decimal(
                "0"
            )
            if (
                binding.daily_order_amount_limit <= 0
                or today_amount + amount > binding.daily_order_amount_limit
            ):
                raise BrokerExecutionConflictError("Order exceeds the configured daily limit")
            if TradingControlModel._default_manager.filter(
                user_id=binding.user_id,
                account_id__in=[0, binding.account_id],
                kill_switch_active=True,
            ).exists():
                raise BrokerExecutionConflictError("Trading is stopped")

            final_status = str(
                payload.get("initial_status") or LiveOrderStatus.WAITING_APPROVAL.value
            )
            if final_status not in {
                LiveOrderStatus.WAITING_APPROVAL.value,
                LiveOrderStatus.RISK_REJECTED.value,
            }:
                raise BrokerExecutionConflictError("Invalid initial live-order status")
            order = LiveOrderModel._default_manager.create(
                user_id=binding.user_id,
                account_id=binding.account_id,
                agent=binding.agent,
                asset_code=symbol,
                market=str(payload.get("market") or "CN")[:16],
                side=side,
                order_type="LIMIT",
                quantity=quantity,
                limit_price=price,
                estimated_amount=amount,
                source_recommendation_ids=source_recommendation_ids,
                source_signal_ids=list(payload.get("source_signal_ids") or []),
                risk_policy_version=str(payload.get("risk_policy_version") or "")[:128],
                risk_snapshot=dict(payload["risk_snapshot"]),
                expires_at=expires_at,
                status=LiveOrderStatus.DRAFT.value,
            )
            validate_order_transition(order.status, final_status)
            order.status = final_status
            order.version += 1
            order.save(update_fields=["status", "version", "updated_at"])
            result = {"success": True, "order": self._order_payload(order)}
            BrokerExecutionAuditModel._default_manager.create(
                user_id=binding.user_id,
                actor_id=user_id,
                action=(
                    "order_risk_rejected"
                    if final_status == LiveOrderStatus.RISK_REJECTED.value
                    else action
                ),
                account_id=binding.account_id,
                resource_type="live_order",
                resource_id=str(order.client_order_id),
                after=result["order"],
                request_id=idempotency_key,
            )
            self._save_idempotent_result(
                user_id=user_id,
                action=action,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                payload=result,
            )
            return result
