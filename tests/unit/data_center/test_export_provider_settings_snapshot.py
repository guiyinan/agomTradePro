"""Unit tests for the provider settings snapshot export command."""

from __future__ import annotations

import hashlib
import io
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

PAYLOAD = {
    "status": "active",
    "default_source": "tushare",
    "enable_failover": True,
    "failover_tolerance": 0.01,
    "source": "config_center_runtime_profile",
}


def _export(monkeypatch: pytest.MonkeyPatch, *args: str, payload: dict | None = None):
    monkeypatch.setattr(
        "apps.data_center.management.commands.export_provider_settings_snapshot"
        ".load_provider_settings_payload",
        lambda: dict(PAYLOAD if payload is None else payload),
    )
    stdout, stderr = io.StringIO(), io.StringIO()
    call_command("export_provider_settings_snapshot", *args, stdout=stdout, stderr=stderr)
    return stdout.getvalue(), stderr.getvalue()


def test_stdout_is_the_exact_snapshot_file(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout, stderr = _export(monkeypatch)

    assert json.loads(stdout) == PAYLOAD
    summary = json.loads(stderr)
    assert summary["outcome"] == "exported"
    assert (
        summary["provider_settings_raw_file_sha256"] == hashlib.sha256(stdout.encode()).hexdigest()
    )
    canonical = json.dumps(
        PAYLOAD,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    assert (
        summary["provider_settings_canonical_payload_sha256"]
        == hashlib.sha256(canonical).hexdigest()
    )


def test_blocked_payload_is_exported_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = {
        "status": "blocked",
        "blocked_reason": "provider_runtime_default_source_missing",
        "default_source": None,
        "enable_failover": None,
        "failover_tolerance": None,
    }
    stdout, _ = _export(monkeypatch, payload=blocked)

    assert json.loads(stdout) == blocked


def test_output_path_is_created_exclusively(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    target = tmp_path / "provider-settings.json"
    stdout, stderr = _export(monkeypatch, f"--output={target}")

    assert stdout == ""
    assert json.loads(target.read_text(encoding="utf-8")) == PAYLOAD
    assert json.loads(stderr)["output"] == str(target)
    with pytest.raises(CommandError, match="already exists"):
        _export(monkeypatch, f"--output={target}")
