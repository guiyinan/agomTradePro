"""Check whether a live EVID-09 Web exercise would invalidate TUI-02 raw observation.

Stream to the VPS as ``python3 -``. The root-only protected query credential
stays on the VPS and only the exact raw migration metric's vector length is
emitted; historical recording-rule values are not observation evidence.
"""

from __future__ import annotations

import base64
import json
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

SECRET = Path("/opt/agomtradepro/prometheus-query-client.secret")
RAW_METRIC = "web_to_tui_migration_events_total"
BASE = "https://demo.agomtrade.pro"
QUERY = "/internal/prometheus/api/v1/query?" + urllib.parse.urlencode({"query": RAW_METRIC})


class Tui02ObservationError(ValueError):
    """Deny unavailable, malformed or nonempty candidate observation source."""


def raw_vector_count(body: bytes) -> int:
    """Count only an instant-vector result for the exact raw metric name."""

    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise Tui02ObservationError("protected raw query is not JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise Tui02ObservationError("protected raw query not successful")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        raise Tui02ObservationError("protected raw query not an instant vector")
    result = data.get("result")
    if not isinstance(result, list):
        raise Tui02ObservationError("protected raw vector unavailable")
    for item in cast(list[object], result):
        if not isinstance(item, dict):
            raise Tui02ObservationError("protected raw vector item invalid")
        metric = item.get("metric")
        if not isinstance(metric, dict) or metric.get("__name__") != RAW_METRIC:
            raise Tui02ObservationError("protected query returned a different metric")
    return len(result)


def _credentials() -> tuple[str, str]:
    if SECRET.is_symlink():
        raise Tui02ObservationError("root-only credential symlink drift")
    metadata = SECRET.stat()
    if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise Tui02ObservationError("root-only credential owner or mode drift")
    fields = dict(line.split("=", 1) for line in SECRET.read_text(encoding="utf-8").splitlines())
    if set(fields) != {"PROMETHEUS_QUERY_USER", "PROMETHEUS_QUERY_PASSWORD"} or any(
        not value for value in fields.values()
    ):
        raise Tui02ObservationError("root-only credential shape drift")
    return fields["PROMETHEUS_QUERY_USER"], fields["PROMETHEUS_QUERY_PASSWORD"]


def _query(user: str, password: str) -> tuple[int, bytes]:
    credentials = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    request = urllib.request.Request(
        BASE + QUERY, headers={"Authorization": "Basic " + credentials}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(256_000)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read(256_000)


def build_report(status: int, body: bytes) -> dict[str, object]:
    """Return a fail-closed count without raw series labels or credentials."""

    count = raw_vector_count(body) if status == 200 else None
    return {
        "schema": "evid09.tui02-raw-observation-preflight.v1",
        "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "query_metric": RAW_METRIC,
        "query_kind": "exact raw instant vector; no recording rule",
        "authenticated_https_status": status,
        "raw_vector_count": count,
        "raw_series_values_or_labels_emitted": False,
        "secret_values_emitted": False,
        "first_retained_sample_inferred": False,
        "decision": "PASS_NO_RAW_SAMPLE" if count == 0 else "DENY_RAW_SAMPLE_OR_QUERY",
    }


def main() -> int:
    """Deny a live candidate-changing drill once a raw sample exists."""

    try:
        user, password = _credentials()
        report = build_report(*_query(user, password))
    except (OSError, ValueError, urllib.error.URLError, Tui02ObservationError) as exc:
        print(f"DENY: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["decision"] == "PASS_NO_RAW_SAMPLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
