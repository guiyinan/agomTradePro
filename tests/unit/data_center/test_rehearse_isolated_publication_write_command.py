"""Command-level guards for isolated publication rehearsal catalog setup."""

from datetime import date
from pathlib import Path
from typing import cast

import pytest
from django.core.management.base import CommandError

from apps.data_center.management.commands import rehearse_isolated_publication_write as command
from core.exceptions import DataFetchError


def _options(tmp_path: Path, *, initialize: bool) -> dict[str, object]:
    """Build valid command options without touching a database."""
    return {
        "candidate_sha": "a" * 40,
        "target_trade_date": date(2026, 9, 24),
        "universe_sha256": "b" * 64,
        "provider_identities_sha256": "c" * 64,
        "expected_database_name": "agom_release_rehearsal_abcdefghij",
        "expected_database_host": "agom-s6-postgres-abcdefghij",
        "output_dir": tmp_path / "output",
        "initialize_reviewed_catalog": initialize,
    }


def test_reviewed_catalog_initializes_only_after_isolation_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        command,
        "preflight_isolated_write_rehearsal",
        lambda **kwargs: events.append("preflight"),
    )
    monkeypatch.setattr(
        command,
        "call_command",
        lambda *args, **kwargs: events.append(cast(str, args[0])),
    )
    monkeypatch.setattr(
        command,
        "collect_isolated_write_rehearsal",
        lambda **kwargs: events.append("collect") or {"outcome": "success"},
    )

    command.Command().handle(**_options(tmp_path, initialize=True))

    assert events == ["preflight", "initialize_data_center_catalog", "collect"]


@pytest.mark.parametrize(
    "code",
    [
        "REHEARSAL_WRITE_SCOPE_INVALID",
        "REHEARSAL_CANDIDATE_SOURCE_MISMATCH",
        "REHEARSAL_WRITE_MIGRATIONS_PENDING",
    ],
)
def test_preflight_failure_prevents_catalog_and_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    events: list[str] = []

    def reject_scope(**kwargs: object) -> None:
        raise DataFetchError("unsafe", code=code)

    monkeypatch.setattr(command, "preflight_isolated_write_rehearsal", reject_scope)
    monkeypatch.setattr(
        command,
        "call_command",
        lambda *args, **kwargs: events.append("initialize"),
    )
    monkeypatch.setattr(
        command,
        "collect_isolated_write_rehearsal",
        lambda **kwargs: events.append("collect") or {"outcome": "success"},
    )

    with pytest.raises(CommandError, match=code):
        command.Command().handle(**_options(tmp_path, initialize=True))

    assert events == []


def test_default_command_keeps_missing_catalog_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def reject_missing_catalog(**kwargs: object) -> dict[str, object]:
        events.append("collect")
        raise DataFetchError("missing", code="REHEARSAL_WRITE_CATALOG_UNAVAILABLE")

    monkeypatch.setattr(
        command,
        "preflight_isolated_write_rehearsal",
        lambda **kwargs: events.append("preflight"),
    )
    monkeypatch.setattr(
        command,
        "call_command",
        lambda *args, **kwargs: events.append("initialize"),
    )
    monkeypatch.setattr(
        command,
        "collect_isolated_write_rehearsal",
        reject_missing_catalog,
    )

    with pytest.raises(CommandError, match="REHEARSAL_WRITE_CATALOG_UNAVAILABLE"):
        command.Command().handle(**_options(tmp_path, initialize=False))

    assert events == ["collect"]
