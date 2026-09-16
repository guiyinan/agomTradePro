"""Secret-safe EVID-09 protected HTTPS stop-line contract tests."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scripts import evid09_protected_https_stop_probe as probe


def test_root_only_secret_requires_exact_keys() -> None:
    assert probe.parse_client_secret(
        "PROMETHEUS_QUERY_USER=reader\nPROMETHEUS_QUERY_PASSWORD=not-emitted\n"
    ) == ("reader", "not-emitted")
    with pytest.raises(probe.ProtectedQueryProbeError, match="key drift"):
        probe.parse_client_secret("WRONG_KEY=reader\nPROMETHEUS_QUERY_PASSWORD=not-emitted\n")


def test_secret_mode_drift_denies(tmp_path: Path) -> None:
    path = tmp_path / "client.secret"
    path.write_text("PROMETHEUS_QUERY_USER=u\nPROMETHEUS_QUERY_PASSWORD=p\n")
    path.chmod(0o644)
    assert stat.S_IMODE(path.stat().st_mode) != 0o600
    with pytest.raises(probe.ProtectedQueryProbeError, match="owner or mode"):
        probe.read_root_only_credentials(path)


def test_exact_https_stop_lines_pass_without_emitting_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps(
        {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"job": "agomtradepro", "instance": "web:8000"},
                        "value": [1789488000, "1"],
                    }
                ],
            },
        }
    ).encode()
    statuses = {
        "/api/health/": 200,
        "/api/health/db/": 200,
        "/api/ready/": 200,
        "/api/decision-ready/": 503,
    }

    def fake_request(path: str, authorization: str | None = None) -> tuple[int, bytes]:
        if path == probe.QUERY_PATH:
            return (200, body) if authorization else (401, b"blocked")
        return statuses[path], b"ok"

    monkeypatch.setattr(probe, "_request", fake_request)
    marker = "TOKEN_DO_NOT_EMIT_84213"
    report = probe.build_report("reader", marker)
    assert report["decision"] == "PASS_READ_ONLY"
    assert report["retained_up_target"]["value"] == 1
    assert marker not in json.dumps(report)
    assert "Basic " not in json.dumps(report)


def test_https_stop_line_drift_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(path: str, authorization: str | None = None) -> tuple[int, bytes]:
        if path == probe.QUERY_PATH:
            return (401, b"blocked") if authorization else (401, b"blocked")
        return (503, b"blocked") if path == "/api/ready/" else (200, b"ok")

    monkeypatch.setattr(probe, "_request", fake_request)
    assert probe.build_report("reader", "secret")["decision"] == "DENY_STOP_LINES"
