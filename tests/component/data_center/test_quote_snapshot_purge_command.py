"""Destructive quote rebuild command safety contract."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command


def test_quote_snapshot_purge_requires_exact_confirmation(mocker) -> None:
    purge = mocker.patch(
        "apps.data_center.management.commands.purge_quote_snapshots_for_rebuild."
        "purge_all_quote_snapshots_for_rebuild"
    )

    with pytest.raises(CommandError, match="Refusing purge"):
        call_command("purge_quote_snapshots_for_rebuild")

    purge.assert_not_called()


def test_quote_snapshot_purge_reports_deleted_count(mocker) -> None:
    purge = mocker.patch(
        "apps.data_center.management.commands.purge_quote_snapshots_for_rebuild."
        "purge_all_quote_snapshots_for_rebuild",
        return_value=325,
    )
    stdout = StringIO()

    call_command(
        "purge_quote_snapshots_for_rebuild",
        confirm="DELETE_ALL_QUOTE_SNAPSHOTS",
        stdout=stdout,
    )

    purge.assert_called_once_with()
    assert "Deleted 325 quote snapshots" in stdout.getvalue()
