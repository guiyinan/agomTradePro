"""S6 temporary artifact-root overrides remain isolated from normal runtime."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.data_center.infrastructure import (
    isolated_write_rehearsal_runner,
    s6_rehearsal_artifact_root,
)
from core.exceptions import DataFetchError


def test_artifact_root_override_fails_closed_without_disposable_postgresql(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A temp path alone cannot redirect financial artifacts in a regular database."""

    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        s6_rehearsal_artifact_root,
        "connection",
        SimpleNamespace(
            settings_dict={
                "NAME": "agom_release_rehearsal_run01",
                "HOST": "agom-s6-postgres-run-01",
            },
            vendor="sqlite",
            in_atomic_block=False,
        ),
    )

    with pytest.raises(DataFetchError) as error:
        s6_rehearsal_artifact_root.validate_s6_rehearsal_artifact_root(
            tmp_path / "ephemeral",
            protected_root=tmp_path / "runtime",
        )

    assert error.value.code == "REHEARSAL_ARTIFACT_ROOT_DATABASE_INVALID"


def _configure_isolated_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        s6_rehearsal_artifact_root,
        "connection",
        SimpleNamespace(
            settings_dict={
                "NAME": "agom_release_rehearsal_run01",
                "HOST": "agom-s6-postgres-run-01",
            },
            vendor="postgresql",
            in_atomic_block=False,
        ),
    )
    monkeypatch.setattr(
        isolated_write_rehearsal_runner,
        "assert_isolated_rehearsal_database",
        lambda **kwargs: None,
    )


def test_artifact_root_override_accepts_child_of_container_temp_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dedicated S6 temp mount remains eligible for isolated artifact storage."""

    _configure_isolated_postgresql(monkeypatch)
    temporary_root = tmp_path / "container-temp"
    temporary_root.mkdir()
    artifact_root = temporary_root / f"agom-s6-financial-scope-{'a' * 32}"
    monkeypatch.setattr(
        s6_rehearsal_artifact_root.tempfile,
        "gettempdir",
        lambda: str(temporary_root),
    )

    assert (
        s6_rehearsal_artifact_root.validate_s6_rehearsal_artifact_root(
            artifact_root,
            protected_root=tmp_path / "protected-runtime",
        )
        == artifact_root.resolve()
    )


def test_artifact_root_override_rejects_path_outside_container_temp_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A writable stage mount outside the process temp root remains fail closed."""

    _configure_isolated_postgresql(monkeypatch)
    temporary_root = tmp_path / "container-temp"
    temporary_root.mkdir()
    artifact_root = tmp_path / "stage-output" / "agom-s6-financial-scope-" / ("b" * 32)
    monkeypatch.setattr(
        s6_rehearsal_artifact_root.tempfile,
        "gettempdir",
        lambda: str(temporary_root),
    )

    with pytest.raises(DataFetchError) as error:
        s6_rehearsal_artifact_root.validate_s6_rehearsal_artifact_root(
            artifact_root,
            protected_root=tmp_path / "protected-runtime",
        )

    assert error.value.code == "REHEARSAL_ARTIFACT_ROOT_PATH_INVALID"
