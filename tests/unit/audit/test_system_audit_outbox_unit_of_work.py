from contextlib import AbstractContextManager
from types import TracebackType
from typing import cast

import pytest

from apps.audit.application.system_audit_outbox_dispatcher import SystemAuditOutboxDispatchConflict
from apps.audit.infrastructure.system_audit_outbox_unit_of_work import (
    DjangoSystemAuditOutboxUnitOfWork,
)


class Context(AbstractContextManager[None]):
    def __init__(
        self,
        fail_enter: bool = False,
        fail_exit: bool = False,
        *,
        suppress: bool = False,
    ) -> None:
        self.fail_enter, self.fail_exit = fail_enter, fail_exit
        self.suppress = suppress
        self.calls: list[str] = []
        self.exit_triples: list[
            tuple[type[BaseException] | None, BaseException | None, TracebackType | None]
        ] = []

    def __enter__(self) -> None:
        self.calls.append("enter")
        if self.fail_enter:
            raise ValueError("enter")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.calls.append("exit")
        self.exit_triples.append((exc_type, exc, traceback))
        if self.fail_exit:
            raise ValueError("exit")
        return self.suppress


class Repo:
    def __init__(
        self,
        context: Context | object | None = None,
        alias: object = "default",
        *,
        fail_atomic: bool = False,
    ) -> None:
        self.database_alias = alias
        self.context = context or Context()
        self.fail_atomic = fail_atomic
        self.calls = 0

    def atomic(self) -> AbstractContextManager[None]:
        self.calls += 1
        if self.fail_atomic:
            raise ValueError("atomic")
        return cast(AbstractContextManager[None], self.context)


def test_delegates_and_reuses_sequentially() -> None:
    repo = Repo()
    uow = DjangoSystemAuditOutboxUnitOfWork(repo)
    assert uow.database_alias == "default"
    repo.database_alias = "other"
    assert uow.database_alias == "default"
    with uow:
        pass
    with uow:
        pass
    assert repo.calls == 2
    assert repo.context.calls == ["enter", "exit", "enter", "exit"]


def test_nested_and_exit_without_enter_fail_closed() -> None:
    uow = DjangoSystemAuditOutboxUnitOfWork(Repo())
    with pytest.raises(SystemAuditOutboxDispatchConflict):
        uow.__exit__(None, None, None)
    uow.__enter__()
    with pytest.raises(SystemAuditOutboxDispatchConflict):
        uow.__enter__()
    uow.__exit__(None, None, None)


def test_exception_triple_is_delegated_and_not_swallowed() -> None:
    repo = Repo()
    uow = DjangoSystemAuditOutboxUnitOfWork(repo)
    with pytest.raises(KeyError) as exc_info:
        with uow:
            raise KeyError("x")
    assert repo.context.calls == ["enter", "exit"]
    exc_type, exc, traceback = repo.context.exit_triples[0]
    assert exc_type is KeyError
    assert exc is exc_info.value
    assert traceback is exc_info.value.__traceback__


def test_delegate_cannot_suppress_body_exception() -> None:
    uow = DjangoSystemAuditOutboxUnitOfWork(Repo(Context(suppress=True)))

    with pytest.raises(KeyError, match="x"):
        with uow:
            raise KeyError("x")


@pytest.mark.parametrize("alias", ["", " bad ", "a b", "a" * 65])
def test_malformed_alias_rejected(alias: str) -> None:
    with pytest.raises(ValueError):
        DjangoSystemAuditOutboxUnitOfWork(Repo(alias=alias))


def test_non_string_alias_and_missing_atomic_rejected() -> None:
    with pytest.raises(ValueError):
        DjangoSystemAuditOutboxUnitOfWork(Repo(alias=7))
    with pytest.raises(TypeError):
        DjangoSystemAuditOutboxUnitOfWork(cast(Repo, object()))


def test_missing_alias_is_rejected_as_a_contract_error() -> None:
    class NoAlias:
        def atomic(self) -> AbstractContextManager[None]:
            return Context()

    with pytest.raises(TypeError, match="alias contract"):
        DjangoSystemAuditOutboxUnitOfWork(cast(Repo, NoAlias()))


def test_atomic_failure_and_non_context_result_leave_uow_reusable() -> None:
    failing_repo = Repo(fail_atomic=True)
    failing_uow = DjangoSystemAuditOutboxUnitOfWork(failing_repo)
    with pytest.raises(ValueError, match="atomic"):
        failing_uow.__enter__()
    failing_repo.fail_atomic = False
    with failing_uow:
        pass

    invalid_repo = Repo(context=object())
    invalid_uow = DjangoSystemAuditOutboxUnitOfWork(invalid_repo)
    with pytest.raises(SystemAuditOutboxDispatchConflict, match="invalid context"):
        invalid_uow.__enter__()
    invalid_repo.context = Context()
    with invalid_uow:
        pass


def test_enter_and_exit_failures_reset_state() -> None:
    enter_repo = Repo(Context(fail_enter=True))
    enter_uow = DjangoSystemAuditOutboxUnitOfWork(enter_repo)
    with pytest.raises(ValueError):
        enter_uow.__enter__()
    enter_repo.context.fail_enter = False
    with enter_uow:
        pass

    exit_repo = Repo(Context(fail_exit=True))
    exit_uow = DjangoSystemAuditOutboxUnitOfWork(exit_repo)
    exit_uow.__enter__()
    with pytest.raises(ValueError):
        exit_uow.__exit__(None, None, None)
    exit_repo.context.fail_exit = False
    with exit_uow:
        pass
