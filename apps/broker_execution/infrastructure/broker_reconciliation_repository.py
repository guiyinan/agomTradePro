"""Django repositories for broker execution."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionPermissionError,
)
from apps.broker_execution.domain.entities import LiveOrderStatus
from apps.broker_execution.domain.rules import (
    validate_order_transition,
)

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

if TYPE_CHECKING:
    from datetime import datetime


class BrokerReconciliationRepositoryMixin:
    """Broker maintenance, reconciliation, and live-order creation persistence."""

    if TYPE_CHECKING:

        @staticmethod
        def _replay_or_conflict(
            *,
            user_id: int,
            action: str,
            idempotency_key: str,
            request_digest: str,
        ) -> dict[str, Any] | None: ...

        @staticmethod
        def _save_idempotent_result(
            *,
            user_id: int,
            action: str,
            idempotency_key: str,
            request_digest: str,
            payload: dict[str, Any],
        ) -> None: ...

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
        ) -> dict[str, Any]: ...

        @staticmethod
        def _order_payload(
            order: LiveOrderModel,
            *,
            include_events: bool = False,
        ) -> dict[str, Any]: ...

        @staticmethod
        def _parse_agent_datetime(raw: Any) -> datetime: ...

        def has_account_access(
            self,
            *,
            user_id: int,
            is_admin: bool,
            account_id: int,
            action: str,
        ) -> bool: ...

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


__all__ = ["BrokerReconciliationRepositoryMixin"]
