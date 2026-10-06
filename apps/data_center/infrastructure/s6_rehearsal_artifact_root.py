"""Fail-closed validation for S6-only temporary financial artifact storage."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from django.db import connection

from core.exceptions import DataFetchError

_DATABASE_HOST = re.compile(r"^agom-s6-postgres-[a-z0-9-]+$")
_DATABASE_NAME = re.compile(r"^agom_release_rehearsal_[a-z0-9_]+$")


def validate_s6_rehearsal_artifact_root(
    artifact_storage_root: Path,
    *,
    protected_root: Path,
) -> Path:
    """Allow artifact-root overrides only in a verified disposable S6 database."""

    database_name = str(connection.settings_dict.get("NAME") or "")
    database_host = str(connection.settings_dict.get("HOST") or "")
    if (
        os.environ.get("AGOM_RELEASE_REHEARSAL_DATABASE") != "1"
        or connection.vendor != "postgresql"
        or connection.in_atomic_block
        or _DATABASE_NAME.fullmatch(database_name) is None
        or _DATABASE_HOST.fullmatch(database_host) is None
    ):
        raise DataFetchError(
            "Temporary financial artifact storage requires an isolated S6 PostgreSQL database",
            code="REHEARSAL_ARTIFACT_ROOT_DATABASE_INVALID",
        )
    from apps.data_center.infrastructure.isolated_write_rehearsal_runner import (
        assert_isolated_rehearsal_database,
    )

    assert_isolated_rehearsal_database(
        expected_database_name=database_name,
        expected_database_host=database_host,
        require_ephemeral_host=True,
    )

    temporary_root = Path(tempfile.gettempdir()).resolve()
    resolved_root = artifact_storage_root.resolve()
    if (
        not artifact_storage_root.is_absolute()
        or artifact_storage_root.is_symlink()
        or resolved_root == protected_root.resolve()
        or not resolved_root.is_relative_to(temporary_root)
    ):
        raise DataFetchError(
            "Temporary financial artifact root is outside the S6 temp area",
            code="REHEARSAL_ARTIFACT_ROOT_PATH_INVALID",
        )
    return resolved_root


__all__ = ["validate_s6_rehearsal_artifact_root"]
