"""Application ports for governed broker execution."""

from __future__ import annotations

from typing import Any, Protocol


class BrokerExecutionRepositoryProtocol(Protocol):
    """Persistence boundary used by broker-execution use cases."""

    def build_overview(self, *, user_id: int, is_admin: bool) -> dict[str, Any]: ...

    def get_account_readiness_evidence(
        self, *, user_id: int, account_id: int
    ) -> dict[str, Any]: ...

    def record_permission_denial(
        self,
        *,
        user_id: int,
        action: str,
        role: str,
        request_context: dict[str, Any] | None = None,
    ) -> None: ...

    def record_agent_auth_failure(
        self,
        *,
        credential_id: str,
        agent_id: str,
        request_id: str,
        required_scope: str,
        source_ip: str,
        failure_code: str,
    ) -> None: ...

    def list_orders(
        self,
        *,
        user_id: int,
        is_admin: bool,
        account_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    def get_order(
        self, *, user_id: int, is_admin: bool, client_order_id: str
    ) -> dict[str, Any] | None: ...

    def list_connections(self, *, user_id: int, is_admin: bool) -> list[dict[str, Any]]: ...

    def list_account_access_grants(self, *, actor_id: int) -> list[dict[str, Any]]: ...

    def list_reconciliations(
        self, *, user_id: int, is_admin: bool, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    def list_audits(
        self, *, user_id: int, is_admin: bool, limit: int = 100
    ) -> list[dict[str, Any]]: ...

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
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

    def has_account_access(
        self,
        *,
        user_id: int,
        is_admin: bool,
        account_id: int,
        action: str,
    ) -> bool: ...

    def list_kill_switch_targets(
        self,
        *,
        user_id: int,
        is_admin: bool,
        account_id: int,
    ) -> list[dict[str, int]]: ...

    def get_bound_account_owner_id(self, *, account_id: int) -> int | None: ...

    def get_user_identity(self, *, user_id: int) -> dict[str, Any] | None: ...

    def list_agent_account_ids(self, *, agent_id: str) -> list[int]: ...

    def authenticate_agent(
        self,
        *,
        credential_id: str,
        secret_hash: str,
        agent_id: str,
        required_scope: str,
        nonce_hash: str,
        request_id: str,
    ) -> dict[str, Any]: ...

    def heartbeat_agent(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def lease_agent_orders(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        limit: int,
        lease_seconds: int,
    ) -> dict[str, Any]: ...

    def acknowledge_submitting(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        client_order_id: str,
        lease_token: str,
    ) -> dict[str, Any]: ...

    def report_agent_events(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]: ...

    def sync_agent_snapshot(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def lease_agent_commands(
        self, *, agent_pk: int, allowed_account_ids: list[int], limit: int
    ) -> dict[str, Any]: ...

    def complete_agent_command(
        self,
        *,
        agent_pk: int,
        allowed_account_ids: list[int],
        command_id: str,
        success: bool,
        result: dict[str, Any],
    ) -> dict[str, Any]: ...

    def upsert_agent_binding(
        self,
        *,
        actor_id: int,
        payload: dict[str, Any],
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]: ...

    def upsert_account_access(
        self,
        *,
        actor_id: int,
        payload: dict[str, Any],
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

    def revoke_agent_credential(
        self,
        *,
        actor_id: int,
        credential_id: str,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]: ...

    def enqueue_agent_sync_command(
        self,
        *,
        actor_id: int,
        agent_id: str,
        reason: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]: ...

    def update_account_settings(
        self,
        *,
        actor_id: int,
        account_id: int,
        payload: dict[str, Any],
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

    def run_maintenance(self) -> dict[str, Any]: ...

    def list_reconciliation_targets(self) -> list[dict[str, int]]: ...

    def generate_reconciliation_runs(
        self, *, account_projections: dict[int, dict[str, Any] | None] | None = None
    ) -> dict[str, Any]: ...

    def create_live_order(
        self,
        *,
        user_id: int,
        is_admin: bool,
        payload: dict[str, Any],
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any]: ...
