"""Exercise the real calendar fixture's explicit opt-out branch."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(scope="module", autouse=True)
def _disable_calendar_fixture_opt_in(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[Path]:
    """Give this real fixture request an isolated no-opt-in environment."""

    runner_temp = tmp_path_factory.mktemp("m5-calendar-opt-out")
    artifact_dir = runner_temp / "agomtradepro-m5-calendar"
    with patch.dict(os.environ):
        os.environ.pop("AGOM_M5_SYNTHETIC_CALENDAR", None)
        os.environ["RUNNER_TEMP"] = str(runner_temp)
        os.environ["AGOM_M5_CALENDAR_ARTIFACT_DIR"] = str(artifact_dir)
        yield runner_temp


@pytest.mark.uat
def test_calendar_fixture_without_opt_in_yields_none_and_creates_no_artifact(
    m5_synthetic_calendar_transport: None,
) -> None:
    """Request the registered generator fixture and verify its no-op outcome."""

    artifact_dir = Path(os.environ["AGOM_M5_CALENDAR_ARTIFACT_DIR"])
    assert m5_synthetic_calendar_transport is None
    assert not artifact_dir.exists()
