"""Typed collaboration contract shared by broker repository mixins."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import LiveOrderModel


class BrokerExecutionRepositoryMixinSupport:
    """Declare methods supplied by sibling mixins in the composed repository."""

    @staticmethod
    def _replay_or_conflict(
        *,
        user_id: int,
        action: str,
        idempotency_key: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        """Return a prior idempotent result or raise on a digest conflict."""

        raise NotImplementedError

    @staticmethod
    def _save_idempotent_result(
        *,
        user_id: int,
        action: str,
        idempotency_key: str,
        request_digest: str,
        payload: dict[str, Any],
    ) -> None:
        """Persist an idempotent repository result."""

        raise NotImplementedError

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
        """Create or update one operational alert."""

        raise NotImplementedError

    @staticmethod
    def _order_payload(
        order: LiveOrderModel,
        *,
        include_events: bool = False,
    ) -> dict[str, Any]:
        """Serialize one live order."""

        raise NotImplementedError

    @staticmethod
    def _parse_agent_datetime(raw: Any) -> datetime:
        """Parse an Agent timestamp."""

        raise NotImplementedError

    def has_account_access(
        self,
        *,
        user_id: int,
        is_admin: bool,
        account_id: int,
        action: str,
    ) -> bool:
        """Return whether an actor can perform an account action."""

        raise NotImplementedError

    def list_kill_switch_targets(
        self,
        *,
        user_id: int,
        is_admin: bool,
        account_id: int,
    ) -> list[dict[str, int]]:
        """Return accounts affected by a kill-switch request."""

        raise NotImplementedError
