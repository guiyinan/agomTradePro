"""Django repositories for broker execution."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

from django.db import transaction
from django.db.models import F, Model
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
    BrokerExecutionPermissionError,
)
from apps.broker_execution.domain.entities import LiveOrderStatus

from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentModel,
    BrokerAgentNonceModel,
    BrokerExecutionAlertModel,
    BrokerExecutionAuditModel,
    BrokerExecutionDailyReportModel,
    BrokerFillModel,
    BrokerPositionSnapshotModel,
    LiveOrderModel,
    OrderLeaseModel,
    ReconciliationDifferenceModel,
    ReconciliationRunModel,
    TradingControlModel,
)

ModelT = TypeVar("ModelT", bound=Model)


class BrokerExecutionReconciliationMixin(BrokerExecutionRepositoryMixinSupport):
    """Account settings, maintenance, and reconciliation operations."""

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
