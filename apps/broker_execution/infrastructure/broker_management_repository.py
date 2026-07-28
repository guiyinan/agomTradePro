"""Django repositories for broker execution."""

from __future__ import annotations

import hashlib
import secrets
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
    BrokerExecutionPermissionError,
)

from .models import (
    BrokerAccountAccessModel,
    BrokerAccountBindingModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerCommandModel,
    BrokerExecutionAlertModel,
    BrokerExecutionAuditModel,
    ReconciliationRunModel,
)

if TYPE_CHECKING:
    from datetime import datetime


class BrokerManagementRepositoryMixin:
    """Broker binding, access, credential, command, and settings persistence."""

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
        def _parse_agent_datetime(raw: Any) -> datetime: ...

        def has_account_access(
            self,
            *,
            user_id: int,
            is_admin: bool,
            account_id: int,
            action: str,
        ) -> bool: ...

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


__all__ = ["BrokerManagementRepositoryMixin"]
