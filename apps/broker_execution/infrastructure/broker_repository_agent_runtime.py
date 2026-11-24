"""Django repositories for broker execution."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar

from django.db import IntegrityError, transaction
from django.db.models import F, Model, Q, Sum
from django.utils import timezone

from apps.broker_execution.application.evidence_gate import (
    blocked_lease_result,
    broker_order_evidence_integrated,
    require_broker_order_evidence,
)
from apps.broker_execution.application.execution_contract_capabilities import (
    parse_agent_execution_contracts,
)
from apps.broker_execution.application.execution_price_guard import require_current_execution_price
from apps.broker_execution.application.ports import PartialBatchAlertHandler
from apps.broker_execution.application.use_case_errors import (
    BrokerAgentAuthenticationError,
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
    BrokerExecutionValidationError,
)
from apps.broker_execution.domain.connection_freshness import heartbeat_times_are_fresh
from apps.broker_execution.domain.entities import LiveOrderStatus
from apps.broker_execution.domain.rules import (
    is_trading_session_open,
    validate_order_transition,
)
from apps.broker_execution.domain.services import approval_digest_for_order
from apps.broker_execution.order_checkpoint_composition import verify_existing_order

from . import broker_agent_account_reports, broker_agent_commands, broker_agent_event_reports
from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerAgentNonceModel,
    BrokerExecutionAuditModel,
    BrokerPositionSnapshotModel,
    LiveOrderModel,
    OrderLeaseModel,
    TradingControlModel,
)

ModelT = TypeVar("ModelT", bound=Model)


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _require_agent_submission_contract(agent: BrokerAgentModel | None) -> None:
    """Block new submission on missing, malformed, or unsupported capability data."""

    if agent is None:
        raise BrokerExecutionConflictError("AGENT_EXECUTION_CONTRACT_UNSUPPORTED")
    snapshot: object = agent.health_snapshot
    if not isinstance(snapshot, dict):
        raise BrokerExecutionConflictError("AGENT_EXECUTION_CONTRACT_UNSUPPORTED")
    try:
        capabilities = parse_agent_execution_contracts(
            snapshot.get("execution_constraint_schemas", [])
        )
    except BrokerExecutionValidationError as error:
        raise BrokerExecutionConflictError("AGENT_EXECUTION_CONTRACT_UNSUPPORTED") from error
    if not capabilities.supports_submission_v2:
        raise BrokerExecutionConflictError("AGENT_EXECUTION_CONTRACT_UNSUPPORTED")


def _require_online_agent(agent: BrokerAgentModel, evaluated_at: datetime) -> None:
    _require_agent_submission_contract(agent)
    if (
        not agent.is_active
        or agent.status != BrokerAgentModel.STATUS_ONLINE
        or not agent.qmt_connected
    ):
        raise BrokerExecutionConflictError("Agent or QMT is not online")
    try:
        observed_at = datetime.fromisoformat(
            str((agent.health_snapshot or {}).get("source_observed_at") or "").replace(
                "Z", "+00:00"
            )
        )
    except ValueError:
        observed_at = None
    if not heartbeat_times_are_fresh(
        source_observed_at=observed_at,
        received_at=agent.last_heartbeat_at,
        evaluated_at=evaluated_at,
    ):
        raise BrokerExecutionConflictError("Agent heartbeat source or receipt is stale")


def _require_submitting_window(
    *,
    agent: BrokerAgentModel,
    binding: BrokerAccountBindingModel,
    order: LiveOrderModel,
    lease: OrderLeaseModel,
    evaluated_at: datetime,
) -> None:
    _require_online_agent(agent, evaluated_at)
    if lease.expires_at <= evaluated_at:
        raise BrokerExecutionConflictError("Order lease is invalid or expired")
    if order.expires_at is not None and order.expires_at <= evaluated_at:
        raise BrokerExecutionConflictError("Order expired before broker submission")
    if binding.enforce_trading_session and not is_trading_session_open(
        timezone.localtime(evaluated_at), binding.allowed_trading_windows or []
    ):
        raise BrokerExecutionConflictError("Trading session is closed")


def _record_agent_checkpoint(order: LiveOrderModel, action: str) -> None:
    """Archive one server transition without exposing the lease credential."""
    BrokerExecutionAuditModel._default_manager.create(
        user_id=order.user_id,
        actor_type="agent",
        action=action,
        account_id=order.account_id,
        resource_type="live_order",
        resource_id=str(order.client_order_id),
        request_id=f"{order.client_order_id}:{order.version}",
        after={
            "version": order.version,
            "status": order.status,
            "authority_pin": order.authority_pin,
            "agent_pk": order.agent_id,
            "clock_source": "server",
        },
    )


class BrokerExecutionAgentRuntimeMixin(BrokerExecutionRepositoryMixinSupport):
    """Broker Agent authentication, leasing, and runtime reporting."""

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

        return broker_agent_account_reports.heartbeat_agent(
            self, agent_pk=agent_pk, allowed_account_ids=allowed_account_ids, payload=payload
        )

    def lease_agent_orders(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        limit: int,
        lease_seconds: int,
    ) -> dict[str, Any]:
        """Lease READY orders only when connection, binding, and kill switches allow it."""

        if not broker_order_evidence_integrated():
            return blocked_lease_result()

        now = timezone.now()
        agent = BrokerAgentModel._default_manager.get(pk=agent_pk, is_active=True)
        _require_online_agent(agent, now)
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
        for candidate_binding in bindings:
            fresh_after = now - timedelta(seconds=candidate_binding.max_snapshot_age_seconds)
            if BrokerAccountSnapshotModel._default_manager.filter(
                agent=agent,
                account_id=candidate_binding.account_id,
                captured_at__gte=fresh_after,
                captured_at__lte=now,
            ).exists():
                fresh_account_ids.append(candidate_binding.account_id)
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
            agent = BrokerAgentModel._default_manager.select_for_update().get(pk=agent_pk)
            now = timezone.now()
            _require_online_agent(agent, now)
            stale_leases = list(
                OrderLeaseModel._default_manager.select_for_update()
                .select_related("order")
                .filter(
                    agent=agent,
                    order__account_id__in=account_ids,
                    released_at__isnull=True,
                    expires_at__lte=now,
                )
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
                LiveOrderModel._default_manager.select_for_update(of=("self",))
                .filter(
                    agent=agent,
                    account_id__in=account_ids,
                    status=LiveOrderStatus.READY.value,
                )
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
                .order_by("created_at")[:limit]
            )
            for order in candidates:
                # Serialize advancement with a disable or kill switch on this account.
                binding = (
                    BrokerAccountBindingModel._default_manager.select_for_update()
                    .filter(
                        agent=agent,
                        user_id=order.user_id,
                        account_id=order.account_id,
                        is_active=True,
                        auto_execution_enabled=True,
                    )
                    .first()
                )
                if binding is None:
                    continue
                if TradingControlModel._default_manager.filter(
                    user_id=order.user_id,
                    account_id__in=[0, order.account_id],
                    kill_switch_active=True,
                ).exists():
                    continue
                try:
                    checked = verify_existing_order(
                        client_order_id=order.client_order_id,
                        account_id=order.account_id,
                        owner_user_id=order.user_id,
                        authority_pin=order.authority_pin,
                        payload=self._order_payload(order),
                    )
                    if order.approval_digest != checked.intent.sources.order.approval_digest:
                        continue
                    quote_deadline = require_current_execution_price(
                        asset_code=order.asset_code,
                        limit_price=order.limit_price,
                        max_deviation=binding.price_deviation_limit_pct,
                    )
                except BrokerExecutionConflictError:
                    continue
                now = timezone.now()
                _require_online_agent(agent, now)
                if order.expires_at is not None and order.expires_at <= now:
                    continue
                if binding.enforce_trading_session and not is_trading_session_open(
                    timezone.localtime(now), binding.allowed_trading_windows or []
                ):
                    continue
                if not BrokerAccountSnapshotModel._default_manager.filter(
                    agent=agent,
                    account_id=order.account_id,
                    captured_at__lte=now,
                    captured_at__gte=now - timedelta(seconds=binding.max_snapshot_age_seconds),
                ).exists():
                    continue
                if timezone.now() >= min(checked.valid_until, quote_deadline):
                    continue
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
                _record_agent_checkpoint(order, "order_lease")
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

        if not broker_order_evidence_integrated():
            require_broker_order_evidence(checkpoint="submitting")

        digest_invalid = False
        result: dict[str, Any] | None = None
        with transaction.atomic():
            agent = BrokerAgentModel._default_manager.select_for_update().get(pk=agent_pk)
            order = (
                LiveOrderModel._default_manager.select_for_update(of=("self",))
                .select_related("lease", "agent")
                .filter(client_order_id=client_order_id, agent_id=agent_pk)
                .first()
            )
            if order is None:
                raise BrokerExecutionNotFoundError("Leased order does not exist")
            if order.account_id not in set(allowed_account_ids):
                raise BrokerAgentAuthenticationError("Order exceeds the credential account scope")
            _require_online_agent(agent, timezone.now())
            binding = (
                BrokerAccountBindingModel._default_manager.select_for_update()
                .filter(
                    agent_id=agent_pk,
                    user_id=order.user_id,
                    account_id=order.account_id,
                    is_active=True,
                    auto_execution_enabled=True,
                )
                .first()
            )
            if binding is None:
                raise BrokerExecutionConflictError("Live account binding is disabled")
            lease = getattr(order, "lease", None)
            token_hash = hashlib.sha256(lease_token.encode("utf-8")).hexdigest()
            if (
                lease is None
                or lease.agent_id != agent_pk
                or lease.released_at is not None
                or not hmac.compare_digest(lease.lease_token_hash, token_hash)
            ):
                raise BrokerExecutionConflictError("Order lease is invalid or expired")
            if TradingControlModel._default_manager.filter(
                user_id=order.user_id,
                account_id__in=[0, order.account_id],
                kill_switch_active=True,
            ).exists():
                raise BrokerExecutionConflictError("Trading is stopped")
            quote_deadline = require_current_execution_price(
                asset_code=order.asset_code,
                limit_price=order.limit_price,
                max_deviation=binding.price_deviation_limit_pct,
            )
            now = timezone.now()
            _require_submitting_window(
                agent=agent, binding=binding, order=order, lease=lease, evaluated_at=now
            )
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
            latest_snapshot = (
                BrokerAccountSnapshotModel._default_manager.filter(
                    agent_id=agent_pk,
                    account_id=order.account_id,
                    captured_at__lte=now,
                    captured_at__gte=now - timedelta(seconds=binding.max_snapshot_age_seconds),
                )
                .order_by("-captured_at")
                .first()
            )
            if latest_snapshot is None:
                raise BrokerExecutionConflictError(
                    "Broker account snapshot is stale or unavailable"
                )
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
                checked = verify_existing_order(
                    client_order_id=order.client_order_id,
                    account_id=order.account_id,
                    owner_user_id=order.user_id,
                    authority_pin=order.authority_pin,
                    payload=current,
                )
                write_at = timezone.now()
                checked.require_unexpired(write_at)
                _require_submitting_window(
                    agent=agent, binding=binding, order=order, lease=lease, evaluated_at=write_at
                )
                if write_at >= quote_deadline:
                    raise BrokerExecutionConflictError("execution_quote_stale")
                if (
                    not write_at - timedelta(seconds=binding.max_snapshot_age_seconds)
                    <= latest_snapshot.captured_at
                    <= write_at
                ):
                    raise BrokerExecutionConflictError(
                        "Broker account snapshot is stale or unavailable"
                    )
                order.status = LiveOrderStatus.SUBMITTING.value
                order.version += 1
                order.save(update_fields=["status", "version", "updated_at"])
                _record_agent_checkpoint(order, "order_submitting")
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
        on_partial_alerts: PartialBatchAlertHandler | None = None,
    ) -> dict[str, Any]:
        """Apply broker receipts and deliver earlier committed alerts if a later receipt fails."""

        alerts: list[dict[str, Any]] = []
        try:
            return self._apply_agent_event_batch(
                agent_pk=agent_pk,
                allowed_account_ids=allowed_account_ids,
                events=events,
                alerts=alerts,
            )
        except Exception:
            if alerts and on_partial_alerts is not None:

                def forward_committed_prefix() -> None:
                    on_partial_alerts(alerts)

                transaction.on_commit(forward_committed_prefix, robust=True)
            raise

    def _apply_agent_event_batch(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        events: list[dict[str, Any]],
        alerts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return broker_agent_event_reports.apply_agent_event_batch(
            self,
            agent_pk=agent_pk,
            allowed_account_ids=allowed_account_ids,
            events=events,
            alerts=alerts,
        )

    def sync_agent_snapshot(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one account snapshot and its normalized positions."""

        return broker_agent_account_reports.sync_agent_snapshot(
            self, agent_pk=agent_pk, allowed_account_ids=allowed_account_ids, payload=payload
        )

    def lease_agent_commands(
        self, *, agent_pk: int, allowed_account_ids: list[int], limit: int
    ) -> dict[str, Any]:
        """Lease pending commands for delivery to one Agent."""

        return broker_agent_commands.lease_agent_commands(
            agent_pk=agent_pk, allowed_account_ids=allowed_account_ids, limit=limit
        )

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

        return broker_agent_commands.complete_agent_command(
            agent_pk=agent_pk,
            allowed_account_ids=allowed_account_ids,
            command_id=command_id,
            success=success,
            result=result,
        )
