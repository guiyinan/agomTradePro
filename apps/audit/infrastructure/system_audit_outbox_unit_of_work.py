"""Reusable delegated unit-of-work boundary for system-audit outbox claims."""

from __future__ import annotations

from contextlib import AbstractContextManager
from types import TracebackType
from typing import Protocol, cast

from apps.audit.application.system_audit_outbox_dispatcher import (
    SystemAuditOutboxDispatchConflict,
    SystemAuditOutboxDispatchUnitOfWork,
)


class _Repository(Protocol):
    """Minimal alias-bound repository contract."""

    @property
    def database_alias(self) -> str: ...

    def atomic(self) -> AbstractContextManager[None]: ...


class DjangoSystemAuditOutboxUnitOfWork(SystemAuditOutboxDispatchUnitOfWork):
    """Delegate one repository transaction without creating a second one."""

    __slots__ = ("_repository", "_alias", "_context")

    def __init__(self, repository: _Repository) -> None:
        if not callable(getattr(repository, "atomic", None)):
            raise TypeError("repository atomic contract is unavailable")
        try:
            alias = repository.database_alias
        except AttributeError:
            raise TypeError("repository database alias contract is unavailable") from None
        if (
            type(alias) is not str
            or not alias
            or len(alias) > 64
            or alias.strip() != alias
            or any(c.isspace() for c in alias)
        ):
            raise ValueError("database alias must be bounded and whitespace-free")
        self._repository = repository
        self._alias = alias
        self._context: AbstractContextManager[None] | None = None

    @property
    def database_alias(self) -> str:
        """Return the delegated repository alias."""

        return self._alias

    def __enter__(self) -> None:
        """Enter exactly one delegated repository transaction."""

        if self._context is not None:
            raise SystemAuditOutboxDispatchConflict("system audit outbox UOW cannot be nested")
        context = self._repository.atomic()
        if not callable(getattr(context, "__enter__", None)) or not callable(
            getattr(context, "__exit__", None)
        ):
            raise SystemAuditOutboxDispatchConflict("repository atomic returned an invalid context")
        self._context = context
        try:
            context.__enter__()
        except BaseException:
            self._context = None
            raise

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Exit and reset the delegated transaction without swallowing errors."""

        context = self._context
        if context is None:
            raise SystemAuditOutboxDispatchConflict("system audit outbox UOW is not entered")
        try:
            context.__exit__(
                cast(type[BaseException] | None, exc_type),
                cast(BaseException | None, exc),
                cast(TracebackType | None, traceback),
            )
        finally:
            self._context = None


__all__ = ["DjangoSystemAuditOutboxUnitOfWork"]
