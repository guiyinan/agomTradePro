"""Django repositories for broker execution."""

from __future__ import annotations

import hashlib
import secrets
from decimal import Decimal
from typing import Any, TypeVar

from django.db import transaction
from django.db.models import Model
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
)

from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .models import (
    BrokerAccountAccessModel,
    BrokerAccountBindingModel,
    BrokerAgentCredentialModel,
    BrokerAgentModel,
    BrokerCommandModel,
    BrokerExecutionAuditModel,
)

ModelT = TypeVar("ModelT", bound=Model)


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


class BrokerExecutionAgentAdministrationMixin(BrokerExecutionRepositoryMixinSupport):
    """Broker Agent binding, access, credential, and command administration."""

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
