"""Administrative and reconciliation workflows for broker execution."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Protocol

from .authorization import require_action
from .ports import BrokerExecutionRepositoryProtocol
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


def _commit_idempotency_key(value: str | None) -> str:
    """Return a normalized non-empty commit idempotency key."""

    normalized = str(value or "").strip()
    if not normalized:
        raise BrokerExecutionValidationError("idempotency_key is required")
    return normalized


def _strict_bool(
    payload: dict[str, Any],
    key: str,
    *,
    default: bool,
) -> bool:
    """Read a boolean without treating non-empty strings as true."""

    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise BrokerExecutionValidationError(f"{key} must be boolean")
    return value


class AccountProjectionProviderProtocol(Protocol):
    """Load one account projection for binding ownership checks."""

    def __call__(
        self,
        *,
        user_id: int,
        account_id: int,
    ) -> dict[str, Any] | None: ...


class ManageAgentBindingUseCase:
    """Create or update an Agent/account binding after admin authorization."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
        *,
        account_projection_provider: AccountProjectionProviderProtocol | None = None,
    ) -> None:
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
        try:
            owner_id = int(payload["user_id"])
            account_id = int(payload["account_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerExecutionValidationError(
                "user_id and account_id must be positive integers"
            ) from exc
        if owner_id <= 0 or account_id <= 0:
            raise BrokerExecutionValidationError("user_id and account_id must be positive integers")
        agent_id = str(payload.get("agent_id") or "").strip()
        if re.fullmatch(r"[A-Za-z0-9._-]{3,64}", agent_id) is None:
            raise BrokerExecutionValidationError("agent_id is invalid")
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise BrokerExecutionValidationError("reason is required")
        normalized_payload = dict(payload)
        normalized_payload.update(
            {
                "user_id": owner_id,
                "account_id": account_id,
                "agent_id": agent_id,
                "reason": reason,
            }
        )
        normalized_payload["is_active"] = _strict_bool(
            payload,
            "is_active",
            default=True,
        )
        if (
            normalized_payload["is_active"]
            and not str(normalized_payload.get("broker_account_ref") or "").strip()
        ):
            raise BrokerExecutionValidationError(
                "broker_account_ref is required for an active binding"
            )
        if normalized_payload["is_active"]:
            projection = self.account_projection_provider(
                user_id=owner_id,
                account_id=account_id,
            )
            if not projection:
                raise BrokerExecutionValidationError(
                    "The account does not belong to the selected user"
                )
            if projection.get("account_type") != "real" or not projection.get("is_active"):
                raise BrokerExecutionValidationError(
                    "Only an active unified real account can be bound to QMT"
                )
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "actor_role": role,
            "binding": {
                key: value
                for key, value in normalized_payload.items()
                if key != "broker_account_ref"
            }
            | {"broker_account_ref_present": bool(normalized_payload.get("broker_account_ref"))},
        }
        if preview_only:
            return preview
        commit_key = _commit_idempotency_key(idempotency_key)
        return self.repository.upsert_agent_binding(
            actor_id=actor_id,
            payload=normalized_payload,
            idempotency_key=commit_key,
            request_digest=_digest(normalized_payload),
        )


class ManageAccountAccessUseCase:
    """Grant or revoke one user's scoped access to a bound live account."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
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
        if target_user_id <= 0 or account_id <= 0:
            raise BrokerExecutionValidationError("user_id and account_id must be positive integers")
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
            raise BrokerExecutionValidationError("The account owner already has implicit access")
        normalized = {
            "user_id": target_user_id,
            "account_id": account_id,
            "can_approve": _strict_bool(payload, "can_approve", default=False),
            "can_trade": _strict_bool(payload, "can_trade", default=False),
            "is_active": _strict_bool(payload, "is_active", default=True),
            "reason": str(payload.get("reason") or "").strip(),
        }
        if not normalized["reason"]:
            raise BrokerExecutionValidationError("reason is required")
        if normalized["is_active"] and not (normalized["can_approve"] or normalized["can_trade"]):
            raise BrokerExecutionValidationError("An active grant must allow approval or trading")
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
        commit_key = _commit_idempotency_key(idempotency_key)
        return self.repository.upsert_account_access(
            actor_id=actor_id,
            payload=normalized,
            idempotency_key=commit_key,
            request_digest=_digest(normalized),
        )


class RotateAgentCredentialUseCase:
    """Issue a one-time Agent secret; only its hash is persisted."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
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
        if not normalized_agent_id:
            raise BrokerExecutionValidationError("agent_id is required")
        normalized_account_ids = sorted({int(item) for item in account_ids})
        if not normalized_account_ids or normalized_account_ids[0] <= 0:
            raise BrokerExecutionValidationError(
                "At least one positive Agent account scope is required"
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
        commit_key = _commit_idempotency_key(idempotency_key)
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
            idempotency_key=commit_key,
            request_digest=_digest(payload),
        )


class RevokeAgentCredentialUseCase:
    """Immediately revoke an Agent credential."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
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
        normalized_credential_id = str(credential_id or "").strip()
        if not normalized_credential_id:
            raise BrokerExecutionValidationError("credential_id is required")
        if not str(reason).strip():
            raise BrokerExecutionValidationError("reason is required")
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "credential_id": normalized_credential_id,
            "reason": str(reason).strip(),
        }
        if preview_only:
            return preview
        commit_key = _commit_idempotency_key(idempotency_key)
        return self.repository.revoke_agent_credential(
            actor_id=actor_id,
            credential_id=normalized_credential_id,
            reason=str(reason).strip(),
            idempotency_key=commit_key,
            request_digest=_digest(preview),
        )


class RequestAgentSyncUseCase:
    """Preview and enqueue a full Agent/QMT connection snapshot refresh."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
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
        commit_key = _commit_idempotency_key(idempotency_key)
        return self.repository.enqueue_agent_sync_command(
            actor_id=actor_id,
            agent_id=normalized_agent_id,
            reason=normalized_reason,
            idempotency_key=commit_key,
            request_digest=_digest(preview),
        )


class UpdateExecutionSettingsUseCase:
    """Update limits and allow-list for one binding after admin authorization."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
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
        normalized_reason = str(payload.get("reason") or "").strip()
        if not normalized_reason:
            raise BrokerExecutionValidationError("reason is required")
        setting_fields = {
            "auto_execution_enabled",
            "max_single_order_amount",
            "daily_order_amount_limit",
            "max_position_count",
            "max_snapshot_age_seconds",
            "price_deviation_limit_pct",
            "allowed_trading_windows",
            "enforce_trading_session",
            "allowed_symbols",
        }
        if not setting_fields.intersection(payload):
            raise BrokerExecutionValidationError(
                "At least one execution setting change is required"
            )
        normalized_payload = dict(payload)
        normalized_payload["reason"] = normalized_reason
        preview = {
            "preview_only": True,
            "confirmation_required": True,
            "account_id": int(account_id),
            "changes": normalized_payload,
        }
        if preview_only:
            return preview
        commit_key = _commit_idempotency_key(idempotency_key)
        return self.repository.update_account_settings(
            actor_id=actor_id,
            account_id=int(account_id),
            payload=normalized_payload,
            idempotency_key=commit_key,
            request_digest=_digest({"account_id": int(account_id), **normalized_payload}),
        )


class PreviewOrResolveReconciliationUseCase:
    """Preview and commit a governed reconciliation resolution."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
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
        normalized_resolution = str(resolution or "").strip()
        if normalized_resolution not in {
            "accept_broker_fact",
            "manual_adjustment",
            "verified_no_change",
            "escalate",
        }:
            raise BrokerExecutionValidationError("resolution is invalid")
        payload = {
            "run_id": int(run_id),
            "resolution": normalized_resolution,
            "reason": normalized_reason,
        }
        if preview_only:
            return {
                "preview_only": True,
                "confirmation_required": True,
                "actor_role": role,
                "resolution": payload,
            }
        commit_key = _commit_idempotency_key(idempotency_key)
        return self.repository.resolve_reconciliation(
            actor_id=actor_id,
            is_admin=is_admin,
            run_id=int(run_id),
            resolution=normalized_resolution,
            reason=normalized_reason,
            idempotency_key=commit_key,
            request_digest=_digest(payload),
        )
