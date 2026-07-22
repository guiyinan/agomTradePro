"""Administrative and reconciliation workflows for broker execution."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .authorization import require_action
from .repository_provider import get_broker_execution_repository
from .use_case_errors import BrokerExecutionValidationError


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


class ManageAgentBindingUseCase:
    """Create or update an Agent/account binding after admin authorization."""

    def __init__(self, repository=None, *, account_projection_provider=None) -> None:
        self.repository = repository or get_broker_execution_repository()
        if account_projection_provider is None:
            from apps.simulated_trading.application.query_services import (
                get_account_execution_projection,
            )

            account_projection_provider = get_account_execution_projection
        self.account_projection_provider = account_projection_provider

    def execute(
        self,
        *,
        actor: Any,
        payload: dict[str, Any],
        preview_only: bool,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        actor_id, role, _is_admin = require_action(actor, "manage_binding")
        owner_id = int(payload["user_id"])
        account_id = int(payload["account_id"])
        if bool(payload.get("is_active", True)):
            projection = self.account_projection_provider(
                user_id=owner_id,
                account_id=account_id,
            )
            if not projection:
                raise BrokerExecutionValidationError(
                    "The account does not belong to the selected user"
                )
            if projection.get("account_type") != "real" or not projection.get(
                "is_active"
            ):
                raise BrokerExecutionValidationError(
                    "Only an active unified real account can be bound to QMT"
                )
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "actor_role": role,
            "binding": {
                key: value
                for key, value in payload.items()
                if key != "broker_account_ref"
            }
            | {"broker_account_ref_present": bool(payload.get("broker_account_ref"))},
        }
        if preview_only:
            return preview
        if not idempotency_key:
            raise BrokerExecutionValidationError("idempotency_key is required")
        return self.repository.upsert_agent_binding(
            actor_id=actor_id,
            payload=payload,
            idempotency_key=idempotency_key,
            request_digest=_digest(payload),
        )


class ManageAccountAccessUseCase:
    """Grant or revoke one user's scoped access to a bound live account."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        actor: Any,
        payload: dict[str, Any],
        preview_only: bool,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        actor_id, role, _is_admin = require_action(actor, "manage_access")
        target_user_id = int(payload["user_id"])
        account_id = int(payload["account_id"])
        target_user = self.repository.get_user_identity(user_id=target_user_id)
        if target_user is None:
            raise BrokerExecutionValidationError("The target user does not exist")
        if target_user["is_admin"]:
            raise BrokerExecutionValidationError(
                "Administrators already have global broker execution access"
            )
        owner_id = self.repository.get_bound_account_owner_id(account_id=account_id)
        if owner_id is None:
            raise BrokerExecutionValidationError(
                "The account does not have an active broker binding"
            )
        if target_user_id == owner_id:
            raise BrokerExecutionValidationError(
                "The account owner already has implicit access"
            )
        normalized = {
            "user_id": target_user_id,
            "account_id": account_id,
            "can_approve": bool(payload.get("can_approve", False)),
            "can_trade": bool(payload.get("can_trade", False)),
            "is_active": bool(payload.get("is_active", True)),
            "reason": str(payload.get("reason") or "").strip(),
        }
        if not normalized["reason"]:
            raise BrokerExecutionValidationError("reason is required")
        if normalized["is_active"] and not (
            normalized["can_approve"] or normalized["can_trade"]
        ):
            raise BrokerExecutionValidationError(
                "An active grant must allow approval or trading"
            )
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "actor_role": role,
            "account_owner_id": owner_id,
            "target_user": target_user,
            "access_grant": normalized,
        }
        if preview_only:
            return preview
        if not idempotency_key:
            raise BrokerExecutionValidationError("idempotency_key is required")
        return self.repository.upsert_account_access(
            actor_id=actor_id,
            payload=normalized,
            idempotency_key=idempotency_key,
            request_digest=_digest(normalized),
        )


class RotateAgentCredentialUseCase:
    """Issue a one-time Agent secret; only its hash is persisted."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        actor: Any,
        agent_id: str,
        scopes: list[str],
        account_ids: list[int],
        expires_at: str,
        preview_only: bool,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        actor_id, _role, _is_admin = require_action(actor, "manage_agent_credentials")
        allowed = {
            "agent.heartbeat.write",
            "agent.orders.lease",
            "agent.orders.submitting_ack",
            "agent.events.write",
            "agent.snapshots.write",
            "agent.commands.lease",
        }
        normalized = sorted({str(scope) for scope in scopes})
        if not normalized or not set(normalized).issubset(allowed):
            raise BrokerExecutionValidationError("Invalid Agent credential scopes")
        normalized_agent_id = str(agent_id).strip()
        normalized_account_ids = sorted({int(item) for item in account_ids})
        if not normalized_account_ids:
            raise BrokerExecutionValidationError(
                "At least one Agent account scope is required"
            )
        bound_account_ids = set(
            self.repository.list_agent_account_ids(agent_id=normalized_agent_id)
        )
        if not set(normalized_account_ids).issubset(bound_account_ids):
            raise BrokerExecutionValidationError(
                "Agent credential account scope contains an inactive or unbound account"
            )
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "agent_id": normalized_agent_id,
            "scopes": normalized,
            "allowed_account_ids": normalized_account_ids,
            "expires_at": expires_at,
            "secret_will_be_shown_once": True,
        }
        if preview_only:
            return preview
        if not idempotency_key:
            raise BrokerExecutionValidationError("idempotency_key is required")
        payload = {
            "agent_id": normalized_agent_id,
            "scopes": normalized,
            "allowed_account_ids": normalized_account_ids,
            "expires_at": expires_at,
        }
        return self.repository.rotate_agent_credential(
            actor_id=actor_id,
            agent_id=normalized_agent_id,
            scopes=normalized,
            allowed_account_ids=normalized_account_ids,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            request_digest=_digest(payload),
        )


class RevokeAgentCredentialUseCase:
    """Immediately revoke an Agent credential."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        actor: Any,
        credential_id: str,
        reason: str,
        preview_only: bool,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        actor_id, _role, _is_admin = require_action(actor, "manage_agent_credentials")
        if not str(reason).strip():
            raise BrokerExecutionValidationError("reason is required")
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "credential_id": str(credential_id),
            "reason": str(reason).strip(),
        }
        if preview_only:
            return preview
        if not idempotency_key:
            raise BrokerExecutionValidationError("idempotency_key is required")
        return self.repository.revoke_agent_credential(
            actor_id=actor_id,
            credential_id=credential_id,
            reason=str(reason).strip(),
            idempotency_key=idempotency_key,
            request_digest=_digest(preview),
        )


class RequestAgentSyncUseCase:
    """Preview and enqueue a full Agent/QMT connection snapshot refresh."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        actor: Any,
        agent_id: str,
        reason: str,
        preview_only: bool,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        actor_id, role, _is_admin = require_action(actor, "manage_binding")
        normalized_agent_id = str(agent_id or "").strip()
        normalized_reason = str(reason or "").strip()
        if not normalized_agent_id or not normalized_reason:
            raise BrokerExecutionValidationError("agent_id and reason are required")
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "actor_role": role,
            "agent_id": normalized_agent_id,
            "command_type": "full_sync",
            "reason": normalized_reason,
            "effect": "The Agent will reconnect, query QMT, and upload a fresh snapshot.",
        }
        if preview_only:
            return preview
        if not idempotency_key:
            raise BrokerExecutionValidationError("idempotency_key is required")
        return self.repository.enqueue_agent_sync_command(
            actor_id=actor_id,
            agent_id=normalized_agent_id,
            reason=normalized_reason,
            idempotency_key=str(idempotency_key),
            request_digest=_digest(preview),
        )


class UpdateExecutionSettingsUseCase:
    """Update limits and allow-list for one binding after admin authorization."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        actor: Any,
        account_id: int,
        payload: dict[str, Any],
        preview_only: bool,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        actor_id, _role, _is_admin = require_action(actor, "manage_limits")
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "account_id": int(account_id),
            "changes": payload,
        }
        if preview_only:
            return preview
        if not idempotency_key:
            raise BrokerExecutionValidationError("idempotency_key is required")
        return self.repository.update_account_settings(
            actor_id=actor_id,
            account_id=int(account_id),
            payload=payload,
            idempotency_key=idempotency_key,
            request_digest=_digest({"account_id": int(account_id), **payload}),
        )


class PreviewOrResolveReconciliationUseCase:
    """Preview and commit a governed reconciliation resolution."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        actor: Any,
        run_id: int,
        resolution: str,
        reason: str,
        preview_only: bool,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        actor_id, role, is_admin = require_action(actor, "resolve_reconciliation")
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise BrokerExecutionValidationError("reason is required")
        payload = {
            "run_id": int(run_id),
            "resolution": str(resolution or "").strip(),
            "reason": normalized_reason,
        }
        if preview_only:
            return {
                "preview_only": True,
                "confirmation_required": True,
                "actor_role": role,
                "resolution": payload,
            }
        if not idempotency_key:
            raise BrokerExecutionValidationError("idempotency_key is required")
        return self.repository.resolve_reconciliation(
            actor_id=actor_id,
            is_admin=is_admin,
            run_id=int(run_id),
            resolution=payload["resolution"],
            reason=normalized_reason,
            idempotency_key=str(idempotency_key),
            request_digest=_digest(payload),
        )
