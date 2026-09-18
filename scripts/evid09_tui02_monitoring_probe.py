"""Read-only candidate-bound TUI-02 retained-monitoring gate on the VPS.

Stream over trusted SSH as ``python3 -``. This checks Docker identity,
Prometheus target/rules/retention/storage and protected HTTPS without
modifying the release, containers, TSDB, registry or business data.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

ROOT = Path("/opt/agomtradepro")
RELEASE = ROOT / "releases/source-20260915110952"
COMMIT = "891c40c5769897931b2b513e92df6f9ba72631ea"
IMAGE = "sha256:554f816b6dd2a7155742d3260f1df3eab94864de7aec47c0e67ad5d5738c164d"
PROM_IMAGE = "sha256:63805ebb8d2b3920190daf1cb14a60871b16fd38bed42b857a3182bc621f4996"
PROM_REFERENCE = (
    "prom/prometheus:v3.5.0@sha256:63805ebb8d2b3920190daf1cb14a60871b16fd38bed42b857a3182bc621f4996"
)
MANIFEST_SHA = "b0b58b749ef1488695bb32e158f5d2ead8d83c90d5c5050e1e69d3f5a88b6bb6"
FIRST_SAMPLE = datetime.fromisoformat("2026-09-15T15:21:04.672000+00:00")
SECRET = ROOT / "prometheus-query-client.secret"
ORIGIN = "https://demo.agomtrade.pro"
M5_RULES = frozenset(
    {
        "WebToTuiErrorRateRegression",
        "WebToTuiLegacyEntryRatioHigh",
        "web_to_tui:entry_samples_14d",
        "web_to_tui:execution_error_ratio_14d",
        "web_to_tui:legacy_entry_ratio_14d",
        "web_to_tui:task_request_error_ratio_14d",
        "web_to_tui:task_request_samples_14d",
    }
)


class MonitoringProbeError(ValueError):
    """Reject stale identity, unavailable monitoring or unsafe access."""


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise MonitoringProbeError("expected JSON object")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise MonitoringProbeError("expected JSON list")
    return cast(list[object], value)


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise MonitoringProbeError("UTC timestamp absent")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MonitoringProbeError("UTC timestamp invalid") from exc
    if parsed.tzinfo is None:
        raise MonitoringProbeError("naive timestamp")
    return parsed.astimezone(UTC)


def _docker(args: list[str]) -> str:
    completed = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=20, check=False
    )
    if completed.returncode != 0:
        raise MonitoringProbeError("read-only Docker inspect failed")
    return completed.stdout.strip()


def _inspect(name: str) -> dict[str, object]:
    items = _list(json.loads(_docker(["inspect", name])))
    if len(items) != 1:
        raise MonitoringProbeError("Docker inspect count drift")
    return _object(items[0])


def _state(container: dict[str, object]) -> dict[str, object]:
    state = _object(container.get("State"))
    health = _object(state.get("Health"))
    if state.get("Status") != "running" or health.get("Status") != "healthy":
        raise MonitoringProbeError("container not running healthy")
    return state


def _candidate(
    web: dict[str, object], *, first_sample: datetime = FIRST_SAMPLE
) -> dict[str, object]:
    state = _state(web)
    restart_count = web.get("RestartCount")
    if not isinstance(restart_count, int) or restart_count < 0:
        raise MonitoringProbeError("Web restart count unavailable")
    if web.get("Image") != IMAGE or _utc(state.get("StartedAt")) >= first_sample:
        raise MonitoringProbeError("Web candidate changed after first sample")
    config = _object(web.get("Config"))
    if config.get("Image") != "agomtradepro-web:20260915110952":
        raise MonitoringProbeError("Web configured image tag drift")
    image = _object(_list(json.loads(_docker(["image", "inspect", str(config["Image"])])))[0])
    labels = _object(_object(image.get("Config")).get("Labels"))
    if image.get("Id") != IMAGE or labels.get("org.opencontainers.image.revision") != COMMIT:
        raise MonitoringProbeError("Web immutable OCI revision drift")
    manifest = RELEASE / ".agom-release-manifest.json"
    if (
        ROOT.joinpath("current").resolve() != RELEASE
        or manifest.is_symlink()
        or not manifest.is_file()
        or stat.S_IMODE(manifest.stat().st_mode) != 0o444
        or hashlib.sha256(manifest.read_bytes()).hexdigest() != MANIFEST_SHA
    ):
        raise MonitoringProbeError("current release or manifest drift")
    payload = _object(json.loads(manifest.read_text(encoding="utf-8")))
    if (
        payload.get("source_commit") != COMMIT
        or payload.get("image_id") != IMAGE
        or payload.get("image_tag") != config.get("Image")
    ):
        raise MonitoringProbeError("release manifest identity drift")
    mounted_hash = _docker(
        ["exec", "agomtradepro-web-1", "sha256sum", "/run/agomtradepro/release-manifest.json"]
    ).split(" ", 1)[0]
    if mounted_hash != MANIFEST_SHA:
        raise MonitoringProbeError("mounted Web manifest drift")
    return {
        "commit": COMMIT,
        "release_id": "20260915110952",
        "image_id": IMAGE,
        "web_started_at_utc": _utc(state["StartedAt"]).isoformat(),
        "manifest_sha256": MANIFEST_SHA,
        "web_restart_count": restart_count,
    }


def _prometheus(
    prom: dict[str, object], *, first_sample: datetime = FIRST_SAMPLE
) -> tuple[str, dict[str, object]]:
    state = _state(prom)
    if (
        prom.get("Image") != PROM_IMAGE
        or _object(prom.get("Config")).get("Image") != PROM_REFERENCE
    ):
        raise MonitoringProbeError("Prometheus immutable image drift")
    restart_count = prom.get("RestartCount")
    if not isinstance(restart_count, int) or restart_count < 0:
        raise MonitoringProbeError("Prometheus restart count unavailable")
    if _utc(state.get("StartedAt")) >= first_sample:
        raise MonitoringProbeError("Prometheus restarted after first sample")
    mounts = _list(prom.get("Mounts"))
    volumes = [
        _object(item) for item in mounts if _object(item).get("Destination") == "/prometheus"
    ]
    if len(volumes) != 1 or volumes[0].get("Type") != "volume":
        raise MonitoringProbeError("Prometheus persistent mount absent")
    volume_name = volumes[0].get("Name")
    if volume_name != "agomtradepro_prometheus_data":
        raise MonitoringProbeError("Prometheus volume name drift")
    details = _object(_list(json.loads(_docker(["volume", "inspect", str(volume_name)])))[0])
    mountpoint = details.get("Mountpoint")
    if (
        details.get("Driver") != "local"
        or not isinstance(mountpoint, str)
        or not Path(mountpoint).is_dir()
    ):
        raise MonitoringProbeError("Prometheus local durable volume absent")
    network = _object(_object(prom.get("NetworkSettings")).get("Networks"))
    ips = [
        _object(item).get("IPAddress")
        for item in network.values()
        if _object(item).get("IPAddress")
    ]
    if len(ips) != 1 or not isinstance(ips[0], str):
        raise MonitoringProbeError("Prometheus bridge address ambiguous")
    parsed_ip = ipaddress.ip_address(ips[0])
    if not parsed_ip.is_private or parsed_ip.is_loopback:
        raise MonitoringProbeError("Prometheus bridge address unsafe")
    return f"http://{parsed_ip}:9090", {
        "started_at_utc": _utc(state["StartedAt"]).isoformat(),
        "restart_count": restart_count,
        "image_id": PROM_IMAGE,
        "volume_name": volume_name,
        "volume_driver": "local",
        "volume_mountpoint_present": True,
    }


def _get(url: str, *, authorization: str | None = None) -> tuple[int, bytes]:
    headers = {"Authorization": authorization} if authorization else {}
    request = urllib.request.Request(url, headers=headers)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        """Never forward a monitoring credential to another origin."""

        def redirect_request(
            self,
            request: urllib.request.Request,
            fp: object,
            code: int,
            msg: str,
            headers: object,
            newurl: str,
        ) -> None:
            raise MonitoringProbeError("monitoring HTTP redirect refused")

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, response.read(2_000_000)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read(2_000_000)


def _api(base: str, route: str, *, authorization: str | None = None) -> dict[str, object]:
    status, body = _get(base + route, authorization=authorization)
    if status != 200:
        raise MonitoringProbeError("Prometheus API HTTP status drift")
    payload = _object(json.loads(body))
    if payload.get("status") != "success":
        raise MonitoringProbeError("Prometheus API unsuccessful")
    return _object(payload.get("data"))


def _monitoring(base: str) -> dict[str, object]:
    targets = _list(_api(base, "/api/v1/targets?state=active").get("activeTargets"))
    if len(targets) != 1:
        raise MonitoringProbeError("Prometheus active target count drift")
    target = _object(targets[0])
    labels = _object(target.get("labels"))
    if (
        labels.get("job") != "agomtradepro"
        or labels.get("instance") != "web:8000"
        or target.get("health") != "up"
        or target.get("lastError") != ""
        or target.get("scrapeUrl") != "http://web:8000/metrics/"
    ):
        raise MonitoringProbeError("Prometheus Web target drift")
    groups = _list(_api(base, "/api/v1/rules").get("groups"))
    names: set[str] = set()
    unhealthy = 0
    for group in groups:
        for item in _list(_object(group).get("rules")):
            rule = _object(item)
            if rule.get("health") != "ok":
                unhealthy += 1
            name = rule.get("name")
            if isinstance(name, str):
                names.add(name)
    if len(groups) != 2 or not M5_RULES.issubset(names) or unhealthy:
        raise MonitoringProbeError("Prometheus M5 rules unhealthy or missing")
    flags = _api(base, "/api/v1/status/flags")
    if (
        flags.get("storage.tsdb.retention.time") != "3w"
        or flags.get("storage.tsdb.retention.size") != "4GiB"
        or flags.get("web.enable-admin-api") not in ("false", False)
        or flags.get("web.enable-remote-write-receiver") not in ("false", False)
    ):
        raise MonitoringProbeError("Prometheus retention or mutating API drift")
    runtime = _api(base, "/api/v1/status/runtimeinfo")
    if runtime.get("reloadConfigSuccess") is not True or runtime.get("corruptionCount") != 0:
        raise MonitoringProbeError("Prometheus runtime health drift")
    return {
        "target_count": 1,
        "target_up": True,
        "rules_group_count": len(groups),
        "rules_count": sum(len(_list(_object(group).get("rules"))) for group in groups),
        "rules_unhealthy_count": unhealthy,
        "m5_rule_names_present": sorted(M5_RULES),
        "retention_time": "3w",
        "retention_size": "4GiB",
        "admin_api_enabled": False,
        "remote_write_receiver_enabled": False,
        "runtime_start_time_utc": str(runtime.get("startTime")),
        "runtime_reload_success": True,
        "runtime_corruption_count": 0,
    }


def _protected_query(web_started: datetime) -> dict[str, object]:
    if SECRET.is_symlink():
        raise MonitoringProbeError("protected credential symlink drift")
    info = SECRET.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise MonitoringProbeError("protected credential owner/mode drift")
    fields = dict(line.split("=", 1) for line in SECRET.read_text(encoding="utf-8").splitlines())
    if set(fields) != {"PROMETHEUS_QUERY_USER", "PROMETHEUS_QUERY_PASSWORD"} or any(
        not value for value in fields.values()
    ):
        raise MonitoringProbeError("protected credential keys drift")
    query = "/internal/prometheus/api/v1/query?" + urllib.parse.urlencode({"query": "up"})
    status_without, _ = _get(ORIGIN + query)
    token = base64.b64encode(
        (fields["PROMETHEUS_QUERY_USER"] + ":" + fields["PROMETHEUS_QUERY_PASSWORD"]).encode()
    ).decode("ascii")
    status_with, body = _get(ORIGIN + query, authorization="Basic " + token)
    if status_without != 401 or status_with != 200:
        raise MonitoringProbeError("protected HTTPS query status drift")
    payload = _object(json.loads(body))
    if payload.get("status") != "success":
        raise MonitoringProbeError("protected up query unsuccessful")
    data = _object(payload.get("data"))
    if data.get("resultType") != "vector":
        raise MonitoringProbeError("protected up query not instant vector")
    series = _list(data.get("result"))
    matching = [
        _object(item)
        for item in series
        if _object(_object(item).get("metric")).get("job") == "agomtradepro"
        and _object(_object(item).get("metric")).get("instance") == "web:8000"
    ]
    if len(matching) != 1 or _list(matching[0].get("value"))[1] != "1":
        raise MonitoringProbeError("protected Web up query drift")
    sample_raw = _list(matching[0]["value"])[0]
    if not isinstance(sample_raw, (int, float)):
        raise MonitoringProbeError("protected Web up timestamp invalid")
    sample_at = datetime.fromtimestamp(sample_raw, UTC)
    if sample_at < web_started or abs((datetime.now(UTC) - sample_at).total_seconds()) > 120:
        raise MonitoringProbeError("protected Web up sample stale or pre-candidate")
    statuses = {
        route: _get(ORIGIN + route)[0]
        for route in ("/api/health/", "/api/ready/", "/api/decision-ready/")
    }
    if statuses != {"/api/health/": 200, "/api/ready/": 200, "/api/decision-ready/": 503}:
        raise MonitoringProbeError("TLS health/decision stopline drift")
    return {
        "authenticated_https_status": 200,
        "unauthenticated_https_status": 401,
        "authenticated_web_up": 1,
        "web_up_sample_at_utc": sample_at.isoformat().replace("+00:00", "Z"),
        "health_http_status": 200,
        "ready_http_status": 200,
        "decision_ready_http_status": 503,
        "credential_values_emitted": False,
    }


def main() -> int:
    """Publish only a read-only candidate-bound monitoring verdict."""

    try:
        raw_first_sample = os.environ.get("EVID09_TUI02_FIRST_SAMPLE_AT", "").strip()
        first_sample = _utc(raw_first_sample) if raw_first_sample else FIRST_SAMPLE
        web = _candidate(_inspect("agomtradepro-web-1"), first_sample=first_sample)
        prom_base, prom = _prometheus(
            _inspect("agomtradepro-prometheus-1"), first_sample=first_sample
        )
        monitoring = _monitoring(prom_base)
        protected = _protected_query(_utc(web["web_started_at_utc"]))
        report = {
            "schema": "evid09.tui02-monitoring-readonly.v1",
            "checked_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "candidate": web,
            "prometheus": prom,
            "monitoring": monitoring,
            "protected_query": protected,
            "first_retained_raw_sample_at_utc": first_sample.isoformat().replace("+00:00", "Z"),
            "candidate_drift": False,
            "prometheus_unexpected_restart": False,
            "side_effects_performed": False,
            "decision": "PASS_READ_ONLY_MONITORING_GATES",
        }
    except MonitoringProbeError as exc:
        print(f"DENY: {exc}", file=sys.stderr)
        return 1
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        subprocess.TimeoutExpired,
        urllib.error.URLError,
    ) as exc:
        print(f"DENY: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
