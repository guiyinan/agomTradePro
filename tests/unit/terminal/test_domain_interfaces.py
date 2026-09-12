"""Execution contracts for Terminal Domain repository protocols."""

from __future__ import annotations

from apps.terminal.domain.interfaces import (
    TerminalAuditRepository,
    TerminalCommandRepository,
    TuiActionExecutor,
    TuiMetadataRepository,
)


def test_command_repository_protocol_methods_have_inert_runtime_bodies() -> None:
    repository = object()

    assert TerminalCommandRepository.get_by_id(repository, "command-1") is None
    assert TerminalCommandRepository.get_by_name(repository, "status") is None
    assert TerminalCommandRepository.get_all_active(repository) is None
    assert TerminalCommandRepository.get_all(repository) is None
    assert TerminalCommandRepository.get_by_category(repository, "system") is None
    assert TerminalCommandRepository.save(repository, object()) is None
    assert TerminalCommandRepository.delete(repository, "command-1") is None
    assert TerminalCommandRepository.exists_by_name(repository, "status") is None


def test_audit_and_tui_protocol_methods_have_inert_runtime_bodies() -> None:
    repository = object()

    assert TerminalAuditRepository.save(repository, object()) is None
    assert TerminalAuditRepository.get_recent(repository) is None
    assert TuiMetadataRepository.load_published(repository) is None
    assert (
        TuiActionExecutor.execute(
            repository,
            method="GET",
            endpoint="/api/terminal/status/",
            params={},
            body={},
            user=object(),
        )
        is None
    )
