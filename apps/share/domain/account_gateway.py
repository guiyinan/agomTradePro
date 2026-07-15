"""Domain contract for resolving shareable account snapshots."""

from __future__ import annotations

from typing import Any, Protocol

from .interfaces import (
    ShareOwnedAccountSnapshot,
    ShareOwnedPositionSnapshot,
    ShareOwnedTradeSnapshot,
)


class ShareAccountGateway(Protocol):
    """Read account data owned by an external portfolio implementation."""

    def list_owner_accounts(self, owner_id: int) -> list[Any]: ...

    def get_owned_account(
        self, *, owner_id: int, account_id: int
    ) -> ShareOwnedAccountSnapshot | None: ...

    def list_owned_positions(
        self, *, owner_id: int, account_id: int
    ) -> list[ShareOwnedPositionSnapshot]: ...

    def list_owned_trades(
        self, *, owner_id: int, account_id: int, limit: int
    ) -> list[ShareOwnedTradeSnapshot]: ...

    def account_belongs_to_owner(self, *, owner_id: int, account_id: int) -> bool: ...


class EmptyShareAccountGateway:
    """Safe fallback when no account owner module is registered."""

    def list_owner_accounts(self, owner_id: int) -> list[Any]:
        del owner_id
        return []

    def get_owned_account(
        self, *, owner_id: int, account_id: int
    ) -> ShareOwnedAccountSnapshot | None:
        del owner_id, account_id
        return None

    def list_owned_positions(
        self, *, owner_id: int, account_id: int
    ) -> list[ShareOwnedPositionSnapshot]:
        del owner_id, account_id
        return []

    def list_owned_trades(
        self, *, owner_id: int, account_id: int, limit: int
    ) -> list[ShareOwnedTradeSnapshot]:
        del owner_id, account_id, limit
        return []

    def account_belongs_to_owner(self, *, owner_id: int, account_id: int) -> bool:
        del owner_id, account_id
        return False


__all__ = ["EmptyShareAccountGateway", "ShareAccountGateway"]
