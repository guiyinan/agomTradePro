"""Find the first retained TUI-02 raw source timestamp after the current Web start.

Runs on the production VPS via trusted SSH stdin. Prometheus credentials stay
root-only on the VPS. The query uses ``timestamp(raw_metric)`` so reported UTC
comes from retained scrape samples, not request/evaluation time or an old
14-day recording rule. No numeric counter values or credential bytes are
emitted by this collector.
"""

from __future__ import annotations

import base64
import json
import math
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

BASE = "https://demo.agomtrade.pro"
SECRET = Path("/opt/agomtradepro/prometheus-query-client.secret")
METRIC = "web_to_tui_migration_events_total"
CURRENT_IMAGE = "sha256:554f816b6dd2a7155742d3260f1df3eab94864de7aec47c0e67ad5d5738c164d"
CURRENT_COMMIT = "891c40c5769897931b2b513e92df6f9ba72631ea"
MINIMUM_OBSERVATION_SECONDS = 1_209_600


class RetainedSourceError(ValueError):
    """Reject a sample with unverified source, candidate, time or HTTPS."""


def _aware_utc(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetainedSourceError("Docker Web started_at invalid") from exc
    if value.tzinfo is None:
        raise RetainedSourceError("Docker Web started_at naive")
    return value.astimezone(UTC)


def _web_start() -> datetime:
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "agomtradepro-web-1",
            "--format",
            "{{.Image}}|{{.State.StartedAt}}|{{.State.Status}}|{{.State.Health.Status}}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    parts = result.stdout.strip().split("|")
    if (
        result.returncode != 0
        or len(parts) != 4
        or parts[0] != CURRENT_IMAGE
        or parts[2:] != ["running", "healthy"]
    ):
        raise RetainedSourceError("current Web image or health drift")
    return _aware_utc(parts[1])


def _credentials() -> tuple[str, str]:
    if SECRET.is_symlink():
        raise RetainedSourceError("root-only query credential symlink drift")
    metadata = SECRET.stat()
    if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise RetainedSourceError("root-only query credential owner or mode drift")
    lines = SECRET.read_text(encoding="utf-8").splitlines()
    if len(lines) != 2 or any("=" not in line for line in lines):
        raise RetainedSourceError("root-only query credential format drift")
    fields = dict(line.split("=", 1) for line in lines)
    if set(fields) != {"PROMETHEUS_QUERY_USER", "PROMETHEUS_QUERY_PASSWORD"} or any(
        not value for value in fields.values()
    ):
        raise RetainedSourceError("root-only query credential keys drift")
    return fields["PROMETHEUS_QUERY_USER"], fields["PROMETHEUS_QUERY_PASSWORD"]


def _range_query(
    user: str, password: str, *, web_start: datetime, observed_at: datetime
) -> tuple[int, bytes]:
    query = urllib.parse.urlencode(
        {
            "query": f"timestamp({METRIC})",
            "start": f"{web_start.timestamp():.3f}",
            "end": f"{observed_at.timestamp():.3f}",
            "step": "60s",
        }
    )
    credentials = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    request = urllib.request.Request(
        BASE + "/internal/prometheus/api/v1/query_range?" + query,
        headers={"Authorization": "Basic " + credentials},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.status, response.read(4_000_000)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read(4_000_000)


def parse_source_range(
    body: bytes, *, web_start: datetime, observed_at: datetime
) -> dict[str, object]:
    """Derive exact earliest raw scrape UTC, excluding pre-Web lookback points."""

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RetainedSourceError("protected source range JSON invalid") from exc
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise RetainedSourceError("protected source range not successful")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "matrix":
        raise RetainedSourceError("protected source range not a matrix")
    series = data.get("result")
    if not isinstance(series, list):
        raise RetainedSourceError("protected source range missing result")
    sources: list[datetime] = []
    task_keys: set[str] = set()
    bounded_series = 0
    for raw in cast(list[object], series):
        if not isinstance(raw, dict):
            raise RetainedSourceError("source range series invalid")
        metric = raw.get("metric")
        points = raw.get("values")
        if not isinstance(metric, dict) or not isinstance(points, list):
            raise RetainedSourceError("source range labels or values invalid")
        if metric.get("job") != "agomtradepro" or metric.get("instance") != "web:8000":
            continue
        task = metric.get("task_key")
        if isinstance(task, str) and task:
            task_keys.add(task)
        bounded_series += 1
        for point in cast(list[object], points):
            if not isinstance(point, list) or len(point) != 2:
                raise RetainedSourceError("source range point invalid")
            try:
                evaluation = float(point[0])
                source = float(point[1])
            except (TypeError, ValueError) as exc:
                raise RetainedSourceError("source range timestamp invalid") from exc
            if (
                not math.isfinite(evaluation)
                or not math.isfinite(source)
                or source > evaluation + 5
                or evaluation > observed_at.timestamp() + 5
            ):
                raise RetainedSourceError("source range time skew")
            moment = datetime.fromtimestamp(source, UTC)
            if moment >= web_start and moment <= observed_at:
                sources.append(moment)
    if not sources or bounded_series == 0:
        raise RetainedSourceError("no candidate-bound retained raw source sample")
    first = min(sources)
    last = max(sources)
    return {
        "source_series_count": bounded_series,
        "evaluations_with_candidate_source": len(sources),
        "task_keys": sorted(task_keys),
        "first_retained_raw_sample_at_utc": first.isoformat().replace("+00:00", "Z"),
        "last_retained_raw_sample_at_utc": last.isoformat().replace("+00:00", "Z"),
        "earliest_full_14d_telemetry_at_utc": (
            first + timedelta(seconds=MINIMUM_OBSERVATION_SECONDS)
        )
        .isoformat()
        .replace("+00:00", "Z"),
    }


def main() -> int:
    """Collect one candidate-bound raw source, but never bind or write it."""

    try:
        started = _web_start()
        observed = datetime.now(UTC)
        user, password = _credentials()
        status, body = _range_query(user, password, web_start=started, observed_at=observed)
        if status != 200:
            raise RetainedSourceError("protected source range HTTPS not 200")
        source = parse_source_range(body, web_start=started, observed_at=observed)
        report = {
            "schema": "evid09.tui02-retained-raw-source.v1",
            "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
            "candidate_commit": CURRENT_COMMIT,
            "candidate_web_image_id": CURRENT_IMAGE,
            "candidate_web_started_at_utc": started.isoformat().replace("+00:00", "Z"),
            "protected_query_https_status": status,
            "query": "timestamp(exact raw migration metric); range from current Web start; step 60s",
            **source,
            "raw_counter_values_or_secret_bytes_emitted": False,
            "business_write_performed": False,
            "observation_bound_to_cutover_evidence": False,
            "decision": "SOURCE_SAMPLE_READ_ONLY_PASS_BINDING_PENDING",
        }
    except (
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
        urllib.error.URLError,
        RetainedSourceError,
    ) as exc:
        print(f"DENY: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
