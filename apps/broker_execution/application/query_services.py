"""Strict persisted-only broker execution queries."""

from __future__ import annotations

from typing import Any

from .authorization import require_action
from .repository_provider import get_broker_execution_repository
from .use_case_errors import BrokerExecutionNotFoundError


class BrokerExecutionQueryService:
    """Expose user-scoped, side-effect-free execution projections."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def overview(self, *, actor: Any) -> dict[str, Any]:
        """Return the current user's execution readiness overview."""

        user_id, _role, is_admin = require_action(actor, "view")
        return self.repository.build_overview(user_id=user_id, is_admin=is_admin)

    def orders(
        self,
        *,
        actor: Any,
        account_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return a scoped order catalog."""

        user_id, _role, is_admin = require_action(actor, "view")
        rows = self.repository.list_orders(
            user_id=user_id,
            is_admin=is_admin,
            account_id=account_id,
            status=status,
            limit=limit,
        )
        return {"orders": rows, "total_count": len(rows)}

    def order_detail(self, *, actor: Any, client_order_id: str) -> dict[str, Any]:
        """Return one scoped order and its execution timeline."""

        user_id, _role, is_admin = require_action(actor, "view")
        order = self.repository.get_order(
            user_id=user_id,
            is_admin=is_admin,
            client_order_id=client_order_id,
        )
        if order is None:
            raise BrokerExecutionNotFoundError("Live order does not exist")
        return order

    def connections(self, *, actor: Any) -> dict[str, Any]:
        """Return persisted Agent/QMT connection snapshots."""

        user_id, _role, is_admin = require_action(actor, "view")
        rows = self.repository.list_connections(user_id=user_id, is_admin=is_admin)
        return {"connections": rows, "total_count": len(rows)}

    def account_access_grants(self, *, actor: Any) -> dict[str, Any]:
        """Return administrator-visible account grants."""

        actor_id, _role, _is_admin = require_action(actor, "manage_access")
        rows = self.repository.list_account_access_grants(actor_id=actor_id)
        return {"access_grants": rows, "access_grant_count": len(rows)}

    def reconciliations(self, *, actor: Any, limit: int = 100) -> dict[str, Any]:
        """Return persisted reconciliation runs."""

        user_id, _role, is_admin = require_action(actor, "view")
        rows = self.repository.list_reconciliations(
            user_id=user_id,
            is_admin=is_admin,
            limit=limit,
        )
        return {"runs": rows, "total_count": len(rows)}

    def audits(self, *, actor: Any, limit: int = 100) -> dict[str, Any]:
        """Return user-visible execution audit events."""

        user_id, _role, is_admin = require_action(actor, "view")
        rows = self.repository.list_audits(user_id=user_id, is_admin=is_admin, limit=limit)
        return {"events": rows, "total_count": len(rows)}
