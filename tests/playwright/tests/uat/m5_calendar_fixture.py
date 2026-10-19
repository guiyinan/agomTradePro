"""Opt-in synthetic calendar input for the selected managed M5 journeys."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


def _select_synthetic_sample_session(coverage_start: date, coverage_end: date) -> date:
    """Pick a weekday-shaped sample only for synthetic fixture bytes.

    This is not a China exchange calendar, holiday check, or production
    session-resolution rule. The real loader still consumes explicit raw dates.
    """

    if coverage_start >= coverage_end:
        raise ValueError("synthetic calendar coverage window must be nonempty")
    candidate = coverage_end - timedelta(days=1)
    while candidate >= coverage_start and candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    if candidate < coverage_start:
        raise ValueError("synthetic calendar window has no weekday-shaped sample")
    return candidate


@pytest.fixture(scope="module")
def m5_synthetic_calendar_transport(base_url: str) -> Iterator[None]:
    """Write one bounded synthetic input and remove only its unchanged artifacts."""

    if os.environ.get("AGOM_M5_SYNTHETIC_CALENDAR") != "1":
        yield None
        return
    if base_url.rstrip("/") != os.environ.get("AGOM_M5_CALENDAR_BASE_URL", "").strip():
        pytest.fail("M5 calendar fixture base URL differs from its guarded server URL")

    runner_temp_raw = os.environ.get("RUNNER_TEMP", "").strip()
    if not runner_temp_raw or not Path(runner_temp_raw).is_absolute():
        pytest.fail("M5 calendar fixture requires an absolute RUNNER_TEMP")
    artifact_root = Path(runner_temp_raw).resolve() / "agomtradepro-m5-calendar"
    if Path(os.environ.get("AGOM_M5_CALENDAR_ARTIFACT_DIR", "")).resolve() != artifact_root:
        pytest.fail("M5 calendar fixture artifact directory differs from RUNNER_TEMP")
    artifact_root.mkdir(parents=True, exist_ok=False)

    from tests.support.tui_research.calendar_transport import write_synthetic_calendar_raw

    observed_at = datetime.now(UTC)
    coverage_end = observed_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    coverage_start = coverage_end - timedelta(days=45)
    open_sessions = (_select_synthetic_sample_session(coverage_start, coverage_end),)
    raw_json = json.dumps(
        {
            "coverage_start": coverage_start.isoformat(),
            "coverage_end": coverage_end.isoformat(),
            "open_sessions": [session.isoformat() for session in open_sessions],
            "observed_at": observed_at.isoformat(),
            "source": "synthetic fixture",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected_digest = sha256(raw_json).hexdigest()
    artifacts_written = False
    try:
        write_synthetic_calendar_raw(
            raw_json,
            tmp_path=artifact_root,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            open_sessions=open_sessions,
            observed_at=observed_at,
        )
        artifacts_written = True
        yield
    finally:
        raw_path = artifact_root / "synthetic-calendar.json"
        sha256_path = artifact_root / "synthetic-calendar.json.sha256"
        if not artifacts_written:
            if raw_path.exists() or sha256_path.exists():
                pytest.fail("M5 calendar fixture write was partial; preserving artifacts")
            try:
                artifact_root.rmdir()
            except OSError as exc:
                pytest.fail(f"M5 calendar artifact directory contains unexpected files: {exc}")
        else:
            expected_sidecar = f"{expected_digest}  {raw_path.name}\n"
            if not raw_path.is_file() or not sha256_path.is_file():
                pytest.fail(
                    "M5 calendar fixture artifacts are incomplete; preserving the directory"
                )
            if raw_path.read_bytes() != raw_json:
                pytest.fail("M5 calendar raw artifact changed; preserving it for diagnosis")
            if sha256_path.read_text(encoding="ascii") != expected_sidecar:
                pytest.fail("M5 calendar SHA sidecar changed; preserving it for diagnosis")
            raw_path.unlink()
            sha256_path.unlink()
            try:
                artifact_root.rmdir()
            except OSError as exc:
                pytest.fail(f"M5 calendar artifact directory contains unexpected files: {exc}")
