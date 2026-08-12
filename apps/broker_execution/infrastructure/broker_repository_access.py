"""Django repositories for broker execution."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID

from django.db.models import Count, Min, Model, Q, QuerySet, Sum
from django.utils import timezone

from apps.broker_execution.domain.entities import LiveOrderStatus
from apps.broker_execution.domain.rules import (
    target_status_for_order_action,
)

from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .models import (
    BrokerAccountAccessModel,
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerExecutionAlertModel,
    BrokerExecutionAuditModel,
    BrokerExecutionDailyReportModel,
    LiveOrderModel,
    ReconciliationRunModel,
    TradingControlModel,
)

ModelT = TypeVar("ModelT", bound=Model)


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


class BrokerExecutionAccessMixin(BrokerExecutionRepositoryMixinSupport):
    """Scoped access checks and read-model projections."""

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
                "display_name": agent.display_name,
                "status": agent.status,
                "qmt_connected": agent.qmt_connected,
                "reported_qmt_connected": (
                    bool(agent.health_snapshot.get("reported_qmt_connected"))
                    if isinstance(agent.health_snapshot, dict)
                    else agent.qmt_connected
                ),
                "agent_version": agent.agent_version,
                "last_heartbeat_at": (
                    agent.last_heartbeat_at.isoformat() if agent.last_heartbeat_at else None
                ),
                "received_at": (
                    agent.last_heartbeat_at.isoformat() if agent.last_heartbeat_at else None
                ),
                "source_observed_at": (
                    agent.health_snapshot.get("source_observed_at")
                    if isinstance(agent.health_snapshot, dict)
                    else None
                ),
                "is_active": agent.is_active,
                "bindings": [
                    {
                        **({"user_id": binding.user_id} if is_admin else {}),
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
                row["user_id"] = agent.user_id
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
