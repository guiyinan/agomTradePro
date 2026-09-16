"""TUI-02 candidate and monitoring probe fail-closed regressions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from scripts import evid09_tui02_monitoring_probe as probe


def _monitoring_payload(route: str) -> dict[str, object]:
    if route.startswith("/api/v1/targets"):
        return {
            "activeTargets": [
                {
                    "labels": {"job": "agomtradepro", "instance": "web:8000"},
                    "health": "up",
                    "lastError": "",
                    "scrapeUrl": "http://web:8000/metrics/",
                }
            ]
        }
    if route == "/api/v1/rules":
        return {
            "groups": [
                {"rules": [{"name": name, "health": "ok"} for name in sorted(probe.M5_RULES)]},
                {"rules": [{"name": "OtherRule", "health": "ok"}]},
            ]
        }
    if route == "/api/v1/status/flags":
        return {
            "storage.tsdb.retention.time": "3w",
            "storage.tsdb.retention.size": "4GiB",
            "web.enable-admin-api": "false",
            "web.enable-remote-write-receiver": "false",
        }
    if route == "/api/v1/status/runtimeinfo":
        return {
            "reloadConfigSuccess": True,
            "corruptionCount": 0,
            "startTime": "2026-09-15T03:22:35Z",
        }
    raise AssertionError(route)


def test_exact_target_rules_retention_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "_api", lambda base, route: _monitoring_payload(route))

    report = probe._monitoring("http://172.20.0.2:9090")

    assert report["target_up"] is True
    assert report["rules_unhealthy_count"] == 0
    assert report["retention_time"] == "3w"
    assert report["admin_api_enabled"] is False


@pytest.mark.parametrize("drift", ["missing_rule", "short_retention", "admin_api"])
def test_monitoring_drift_denied(monkeypatch: pytest.MonkeyPatch, drift: str) -> None:
    def fake_api(base: str, route: str) -> dict[str, object]:
        result = _monitoring_payload(route)
        if drift == "missing_rule" and route == "/api/v1/rules":
            groups = cast(list[dict[str, object]], result["groups"])
            cast(list[dict[str, object]], groups[0]["rules"]).pop()
        if drift == "short_retention" and route == "/api/v1/status/flags":
            result["storage.tsdb.retention.time"] = "1w"
        if drift == "admin_api" and route == "/api/v1/status/flags":
            result["web.enable-admin-api"] = "true"
        return result

    monkeypatch.setattr(probe, "_api", fake_api)
    with pytest.raises(probe.MonitoringProbeError):
        probe._monitoring("http://172.20.0.2:9090")


def test_prometheus_last_start_after_first_sample_denied() -> None:
    restarted = (probe.FIRST_SAMPLE + timedelta(minutes=1)).isoformat()
    container = {
        "Image": probe.PROM_IMAGE,
        "Config": {"Image": probe.PROM_REFERENCE},
        "State": {"Status": "running", "Health": {"Status": "healthy"}, "StartedAt": restarted},
        "RestartCount": 1,
    }
    with pytest.raises(probe.MonitoringProbeError, match="restarted after first sample"):
        probe._prometheus(container)


def test_web_image_drift_denied_before_manifest_read() -> None:
    container = {
        "Image": "sha256:" + "0" * 64,
        "State": {
            "Status": "running",
            "Health": {"Status": "healthy"},
            "StartedAt": (probe.FIRST_SAMPLE - timedelta(hours=1)).isoformat(),
        },
        "RestartCount": 0,
    }
    with pytest.raises(probe.MonitoringProbeError, match="Web candidate changed"):
        probe._candidate(container)


def test_success_report_never_claims_final_authorization(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(probe, "_inspect", lambda name: {"Name": name})
    monkeypatch.setattr(
        probe,
        "_candidate",
        lambda web: {
            "commit": probe.COMMIT,
            "release_id": "20260915110952",
            "image_id": probe.IMAGE,
            "web_started_at_utc": "2026-09-15T03:22:24Z",
        },
    )
    monkeypatch.setattr(
        probe, "_prometheus", lambda prom: ("http://172.20.0.2:9090", {"restart_count": 0})
    )
    monkeypatch.setattr(
        probe, "_monitoring", lambda base: {"target_up": True, "rules_unhealthy_count": 0}
    )
    monkeypatch.setattr(
        probe, "_protected_query", lambda started: {"authenticated_https_status": 200}
    )

    assert probe.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["decision"] == "PASS_READ_ONLY_MONITORING_GATES"
    assert report["side_effects_performed"] is False
    assert "final_authorized" not in report
    assert datetime.fromisoformat(report["checked_at_utc"].replace("Z", "+00:00")).tzinfo == UTC
