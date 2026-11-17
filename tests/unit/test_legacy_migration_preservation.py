"""Exercise bounded stream cleanup and original-schema preservation failures."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from scripts import check_legacy_migration_preservation as preservation


def test_copy_stream_timeout_kills_and_reaps_a_nonresponding_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def stalled(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = original_popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        children.append(process)
        return process

    monkeypatch.setattr(preservation.subprocess, "Popen", stalled)
    started = time.monotonic()
    with pytest.raises(preservation.LegacyBaselineBlocked, match="OBSERVED_DATABASE_READ_FAILED"):
        preservation._row_digest("unused", "table", ("id",), ("id",), timeout_seconds=0.1)
    assert time.monotonic() - started < 5
    assert len(children) == 1 and children[0].poll() is not None


def test_copy_stream_hashes_every_output_chunk_without_retaining_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_popen = subprocess.Popen

    def rows(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        return original_popen(
            [
                sys.executable,
                "-c",
                'import sys; sys.stdin.read(); print("row one"); print("row two")',
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    monkeypatch.setattr(preservation.subprocess, "Popen", rows)
    result = preservation._row_digest("unused", "table", ("id",), ("id",), timeout_seconds=5)
    assert result["rows"] == 2
    assert len(result["sha256"]) == 64
    assert "row one" not in str(result)


def test_changed_primary_key_is_rejected_even_when_original_rows_would_hash_equal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preservation, "_container", lambda *args, **kwargs: {"Id": "a" * 64})
    monkeypatch.setattr(preservation, "_psql", lambda *args: "agomtradepro")
    monkeypatch.setattr(
        preservation,
        "_catalog",
        lambda *args: {
            "data_center_financial_fact": preservation.TableColumns(("id", "other"), ("other",)),
        },
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("changed primary key must be rejected before comparing row content")

    monkeypatch.setattr(preservation, "_row_digest", forbidden)
    baseline = {
        "schema": preservation._SCHEMA,
        "postgres_container_id": "a" * 64,
        "database": "agomtradepro",
        "tables": {
            "data_center_financial_fact": {
                "fields": ["id", "other"],
                "order": ["id"],
                "rows": 1,
                "sha256": "b" * 64,
            }
        },
    }
    with pytest.raises(preservation.LegacyBaselineBlocked, match="OBSERVED_LEGACY_SCHEMA_CHANGED"):
        preservation.verify_preservation(baseline)
