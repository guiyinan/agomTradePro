"""Retired destructive quote rebuild command safety contract."""

import pytest
from django.core.management import CommandError, call_command


def test_quote_snapshot_purge_is_always_retired() -> None:
    with pytest.raises(CommandError, match="no verified archive/restore evidence port"):
        call_command("purge_quote_snapshots_for_rebuild")

    with pytest.raises(CommandError, match="no verified archive/restore evidence port"):
        call_command(
            "purge_quote_snapshots_for_rebuild",
            confirm="DELETE_ALL_QUOTE_SNAPSHOTS",
        )
