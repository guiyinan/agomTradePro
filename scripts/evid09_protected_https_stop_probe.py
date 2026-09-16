"""Probe EVID-09 protected production HTTPS stop lines without emitting secrets.

Stream this script to the production VPS as ``python3 -`` under the root-only
operator account. The query client secret stays in VPS process memory and is
never placed on a subprocess command line, disk copy, or probe output.
"""

from __future__ import annotations

import base64
import json
import stat
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

BASE_URL = "https://demo.agomtrade.pro"
SECRET_PATH = Path("/opt/agomtradepro/prometheus-query-client.secret")
QUERY_PATH = "/internal/prometheus/api/v1/query?query=up"


class ProtectedQueryProbeError(ValueError):
    """Fail closed when HTTPS or root-only query credentials are unverified."""


def parse_client_secret(text: str) -> tuple[str, str]:
    """Parse only the exact query-user/password shape; do not log values."""

    lines = text.splitlines()
    if len(lines) != 2 or any("=" not in line for line in lines):
        raise ProtectedQueryProbeError("query client secret format drift")
    fields = dict(line.split("=", 1) for line in lines)
    if set(fields) != {"PROMETHEUS_QUERY_USER", "PROMETHEUS_QUERY_PASSWORD"}:
        raise ProtectedQueryProbeError("query client secret key drift")
    user, password = fields["PROMETHEUS_QUERY_USER"], fields["PROMETHEUS_QUERY_PASSWORD"]
    if not user or not password or "\n" in user or "\n" in password:
        raise ProtectedQueryProbeError("query client secret value invalid")
    return user, password


def read_root_only_credentials(path: Path = SECRET_PATH) -> tuple[str, str]:
    """Read exactly two root-only KEY=value lines without exposing the values."""

    if path.is_symlink():
        raise ProtectedQueryProbeError("query client secret is a symlink")
    mode = path.stat()
    if mode.st_uid != 0 or stat.S_IMODE(mode.st_mode) != 0o600:
        raise ProtectedQueryProbeError("query client secret owner or mode drift")
    return parse_client_secret(path.read_text(encoding="utf-8"))


def _request(path: str, authorization: str | None = None) -> tuple[int, bytes]:
    headers = {"Authorization": authorization} if authorization is not None else {}
    request = urllib.request.Request(BASE_URL + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(256_000)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read(256_000)


def _up_target(body: bytes) -> dict[str, object]:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtectedQueryProbeError("protected query body is not JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ProtectedQueryProbeError("protected query not successful")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        raise ProtectedQueryProbeError("protected query not a vector")
    results = data.get("result")
    if not isinstance(results, list):
        raise ProtectedQueryProbeError("protected query result missing")
    for raw in cast(list[object], results):
        if not isinstance(raw, dict):
            continue
        metric = raw.get("metric")
        value = raw.get("value")
        if (
            isinstance(metric, dict)
            and metric.get("job") == "agomtradepro"
            and metric.get("instance") == "web:8000"
            and isinstance(value, list)
            and len(value) == 2
            and str(value[1]) == "1"
        ):
            return {
                "job": "agomtradepro",
                "instance": "web:8000",
                "sample_at_utc": datetime.fromtimestamp(float(value[0]), UTC).isoformat(),
                "value": 1,
            }
    raise ProtectedQueryProbeError("retained agomtradepro up target not 1")


def build_report(user: str, password: str) -> dict[str, object]:
    """Query authenticated/unauthenticated HTTPS and public stop lines."""

    plain = f"{user}:{password}".encode()
    authorization = "Basic " + base64.b64encode(plain).decode("ascii")
    unauthenticated, _ = _request(QUERY_PATH)
    authenticated, query_body = _request(QUERY_PATH, authorization)
    statuses: dict[str, int] = {}
    for path in ("/api/health/", "/api/health/db/", "/api/ready/", "/api/decision-ready/"):
        statuses[path] = _request(path)[0]
    up_target = _up_target(query_body) if authenticated == 200 else None
    stop_lines_pass = (
        unauthenticated == 401
        and authenticated == 200
        and up_target is not None
        and statuses
        == {
            "/api/health/": 200,
            "/api/health/db/": 200,
            "/api/ready/": 200,
            "/api/decision-ready/": 503,
        }
    )
    return {
        "schema": "evid09.protected-https-stop-lines.v1",
        "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "base_url": BASE_URL,
        "tls_default_trust_used": True,
        "root_only_secret_path": str(SECRET_PATH),
        "secret_values_emitted": False,
        "protected_query_unauthenticated_status": unauthenticated,
        "protected_query_authenticated_status": authenticated,
        "retained_up_target": up_target,
        "https_statuses": statuses,
        "decision_gate_cleared": False,
        "decision": "PASS_READ_ONLY" if stop_lines_pass else "DENY_STOP_LINES",
    }


def main() -> int:
    """Exit nonzero on credential, TLS, HTTPS, or target drift."""

    try:
        user, password = read_root_only_credentials()
        report = build_report(user, password)
    except (OSError, ValueError, urllib.error.URLError, ProtectedQueryProbeError) as exc:
        print(f"DENY: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["decision"] == "PASS_READ_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
