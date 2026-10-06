"""S6 temporary artifact-root overrides remain isolated from normal runtime."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.data_center.infrastructure import s6_rehearsal_artifact_root
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
