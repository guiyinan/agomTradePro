"""Source-bound, fresh EVID-09 Web image exercise preflight.

This is an operator-side read-only gate, not a deployment entry. It streams
the exact checked repository collectors to the trusted VPS and checks their
new reports against pinned production News, business rowsets, image and HTTPS
stop lines. No caller-supplied "verified" booleans are accepted. A later live
action must invoke this gate again immediately before changing Web.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = (
    ROOT / "docs/deployment/evid09-fresh-readonly-transition-gates-2026-09-15-891c40c57.json"
)
NEWS_EVIDENCE = (
    ROOT
    / "docs/deployment/evid09-target-new-news-production-readonly-compatibility-2026-09-15-891c40c57.json"
)
CONTROL_SCRIPT = ROOT / "scripts/evid09-controlled-image-exercise.sh"
PROBE_SOURCES = {
    "preservation": ROOT / "scripts/evid09_production_preservation_probe.py",
    "https": ROOT / "scripts/evid09_protected_https_stop_probe.py",
    "compose": ROOT / "scripts/evid09_compose_web_transition_preflight.py",
    "target_runtime": ROOT / "scripts/evid09_target_current_db_readonly_runtime.py",
}
TARGET_TAG = "agomtradepro-web:20260914021633"
CONTROL_SOURCE_SHA256 = "e170839c122740b5442eaca6fa27eb9f46f0ed9a01ddd60cc9bee496533b4c83"
TARGET_RUNTIME_SOURCE_SHA256 = "1e09c73183dbc087762e572c2c383c3799df99c2a2bc2aae4c1d60989302040e"
TARGET_RUNTIME_COMMAND = (
    "docker run --rm -i --name evid09-target-current-db-readonly-preflight-891c40c57 "
    "--network container:agomtradepro-web-1 --read-only "
    "--tmpfs /tmp:rw,nosuid,size=64m,mode=1777 "
    "--tmpfs /app/logs:rw,nosuid,size=64m,uid=1000,gid=1000 "
    "--user 1000:1000 --security-opt no-new-privileges --cap-drop ALL "
    "--pids-limit 128 --memory 2g --cpus 1.5 "
    "--env-file /opt/agomtradepro/releases/source-20260914021633/deploy/.env "
    "--env PGOPTIONS='-c default_transaction_read_only=on' "
    "--env DJANGO_SETTINGS_MODULE=core.settings.production "
    "--env TUSHARE_TOKEN= --env FRED_API_KEY= --env OPENAI_API_KEY= "
    "--env DASHSCOPE_API_KEY= --env AGOMTRADEPRO_API_TOKEN= "
    "--entrypoint python " + TARGET_TAG + " -"
)
REQUIRED_HTTPS_STATUSES = {
    "/api/health/": 200,
    "/api/health/db/": 200,
    "/api/ready/": 200,
    "/api/decision-ready/": 503,
}


class LiveImagePreflightError(ValueError):
    """Deny a stale, source-drifted, incomplete or inconsistent action gate."""


@dataclass(frozen=True)
class RemoteResult:
    """One streamed remote command's bounded result."""

    exit_code: int
    stdout: str


class RemoteStreamer(Protocol):
    """Run exact source over SSH stdin, not as a VPS source-file install."""

    def stream(self, command: str, source: str, timeout: int = 120) -> RemoteResult:
        """Return only the natural exit code and stdout for an exact command."""


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise LiveImagePreflightError("evidence member is not an object")
    return cast(dict[str, object], value)


def _read_sealed_json(path: Path) -> dict[str, object]:
    """Verify the exact sidecar before reading one local evidence object."""

    raw = path.read_bytes()
    sidecar = (path.parent / (path.name + ".sha256")).read_text(encoding="ascii").strip()
    fields = sidecar.split()
    if (
        len(fields) != 2
        or fields[1] != path.name
        or fields[0].lower() != hashlib.sha256(raw).hexdigest()
    ):
        raise LiveImagePreflightError("evidence SHA sidecar mismatch")
    try:
        return _object(json.loads(raw))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LiveImagePreflightError("evidence JSON invalid") from exc


def _report(result: RemoteResult, name: str) -> dict[str, object]:
    if result.exit_code != 0:
        raise LiveImagePreflightError(f"{name} natural exit not zero")
    lines = result.stdout.strip().splitlines()
    if len(lines) != 1:
        raise LiveImagePreflightError(f"{name} report not exactly one line")
    try:
        return _object(json.loads(lines[0]))
    except json.JSONDecodeError as exc:
        raise LiveImagePreflightError(f"{name} report is not JSON") from exc


def _utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise LiveImagePreflightError(f"{label} time missing")
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveImagePreflightError(f"{label} time invalid") from exc
    if observed.tzinfo is None:
        raise LiveImagePreflightError(f"{label} time is naive")
    return observed.astimezone(UTC)


def _verify_source_hashes(checkpoint: dict[str, object]) -> None:
    collectors = _object(checkpoint.get("collectors"))
    for name, section_name in (
        ("preservation", "production_preservation"),
        ("https", "protected_https"),
        ("compose", "compose_web_semantics"),
    ):
        section = _object(collectors.get(section_name))
        actual = hashlib.sha256(PROBE_SOURCES[name].read_bytes()).hexdigest()
        if section.get("source_sha256") != actual:
            raise LiveImagePreflightError(f"{name} collector source hash drift")
    if hashlib.sha256(CONTROL_SCRIPT.read_bytes()).hexdigest() != CONTROL_SOURCE_SHA256:
        raise LiveImagePreflightError("exact image identity dry-run source hash drift")
    if (
        hashlib.sha256(PROBE_SOURCES["target_runtime"].read_bytes()).hexdigest()
        != TARGET_RUNTIME_SOURCE_SHA256
    ):
        raise LiveImagePreflightError("target OCI runtime source hash drift")


def validate_reports(
    checkpoint: dict[str, object],
    news_evidence: dict[str, object],
    reports: dict[str, dict[str, object]],
    *,
    now: datetime,
) -> dict[str, object]:
    """Require fresh, candidate-bound, mutually consistent real probe outputs."""

    if checkpoint.get("schema") != "evid09.fresh-readonly-transition-gates.v1":
        raise LiveImagePreflightError("checkpoint schema drift")
    news_binding = _object(
        _object(_object(checkpoint["collectors"])["production_preservation"])[
            "explicit_expected_news"
        ]
    )
    news_current = _object(news_evidence.get("new_current_news"))
    expected_news = {
        "publication_id": news_binding.get("publication_id"),
        "publication_hash": news_binding.get("publication_hash"),
        "member_count": news_binding.get("member_count"),
    }
    if expected_news != {
        "publication_id": news_current.get("publication_id"),
        "publication_hash": news_current.get("publication_hash"),
        "member_count": news_current.get("member_count"),
    }:
        raise LiveImagePreflightError("News evidence identity mismatch")
    production = _object(checkpoint.get("production_candidate"))
    target = _object(checkpoint.get("target"))
    preservation = _object(reports.get("preservation"))
    https = _object(reports.get("https"))
    compose = _object(reports.get("compose"))
    runtime = _object(reports.get("target_runtime"))
    observed_news = _object(preservation.get("news_current_identity"))
    expected_rows = _object(_object(news_evidence["read_only_preservation"])["rowsets"])
    actual_rows = _object(preservation.get("rows"))
    for label, raw in expected_rows.items():
        expected_row = _object(raw)
        actual_row = _object(actual_rows.get(label))
        if actual_row.get("count") != expected_row.get("count") or actual_row.get(
            "rowset_sha256"
        ) != expected_row.get("sha256"):
            raise LiveImagePreflightError(f"{label} rowset drift")
    if (
        preservation.get("decision") != "PASS_READ_ONLY"
        or preservation.get("candidate_commit") != production.get("commit")
        or preservation.get("target_commit") != target.get("commit")
        or preservation.get("expected_news_identity") != expected_news
        or observed_news.get("publication_id") != expected_news["publication_id"]
        or observed_news.get("publication_hash") != expected_news["publication_hash"]
        or observed_news.get("member_count") != expected_news["member_count"]
        or preservation.get("expected_counts_match") is not True
        or preservation.get("news_current_id_hash_and_member_count_match") is not True
        or preservation.get("four_immutable_authority_root_hashes_match") is not True
        or preservation.get("raw_row_values_emitted") is not False
        or preservation.get("business_dml_performed") is not False
    ):
        raise LiveImagePreflightError("production preservation identity or decision drift")
    up = _object(https.get("retained_up_target"))
    if (
        https.get("decision") != "PASS_READ_ONLY"
        or https.get("protected_query_unauthenticated_status") != 401
        or https.get("protected_query_authenticated_status") != 200
        or https.get("https_statuses") != REQUIRED_HTTPS_STATUSES
        or https.get("tls_default_trust_used") is not True
        or https.get("secret_values_emitted") is not False
        or https.get("decision_gate_cleared") is not False
        or up.get("job") != "agomtradepro"
        or up.get("instance") != "web:8000"
        or up.get("value") != 1
    ):
        raise LiveImagePreflightError("protected HTTPS stop-line drift")
    compose_gate = _object(_object(checkpoint["collectors"])["compose_web_semantics"])
    normalized = _object(compose.get("rendered_web_config_sha256"))
    if (
        compose.get("decision") != "PASS_READ_ONLY"
        or compose.get("normalized_difference_paths") != []
        or compose.get("all_startup_mutation_flags_disabled") is not True
        or compose.get("compose_or_secret_values_emitted") is not False
        or normalized.get("current")
        != compose_gate.get("normalized_current_and_target_web_config_sha256")
        or normalized.get("target") != normalized.get("current")
    ):
        raise LiveImagePreflightError("Web Compose semantic drift")
    if (
        runtime.get("decision") != "PASS_READ_ONLY"
        or runtime.get("target_source_commit") != target.get("commit")
        or runtime.get("news_current_publication_id") != expected_news["publication_id"]
        or runtime.get("news_current_publication_hash") != expected_news["publication_hash"]
        or runtime.get("news_current_selected_count") != expected_news["member_count"]
        or runtime.get("four_strict_policies_present") is not True
        or runtime.get("selected_rows_match_when_usable") is not True
        or runtime.get("business_dml_performed") is not False
    ):
        raise LiveImagePreflightError("target OCI Application compatibility drift")
    fresh_at = [
        _utc(reports[name].get("observed_at_utc"), name)
        for name in ("preservation", "https", "target_runtime")
    ]
    bounded_now = now.astimezone(UTC)
    up_sample_at = _utc(up.get("sample_at_utc"), "retained up target")
    if (
        any(moment > bounded_now + timedelta(seconds=10) for moment in fresh_at)
        or any(bounded_now - moment > timedelta(seconds=120) for moment in fresh_at)
        or max(fresh_at) - min(fresh_at) > timedelta(seconds=120)
        or _utc(https.get("observed_at_utc"), "https") - up_sample_at > timedelta(seconds=90)
        or up_sample_at > bounded_now + timedelta(seconds=10)
        or bounded_now - up_sample_at > timedelta(seconds=120)
    ):
        raise LiveImagePreflightError("action samples are not fresh together")
    return {
        "schema": "evid09.live-image-preflight.v1",
        "validated_at_utc": bounded_now.isoformat().replace("+00:00", "Z"),
        "production_commit": production["commit"],
        "target_commit": target["commit"],
        "news_identity": expected_news,
        "eight_business_rowset_sha256_match": True,
        "authenticated_protected_https_and_stop_lines": True,
        "web_compose_semantic_identity": True,
        "target_application_readonly_compatibility": True,
        "live_web_switch_performed": False,
        "tui02_observation_reset_performed": False,
        "decision": "PASS_PRE_ACTION_ONLY",
    }


def collect_preflight(streamer: RemoteStreamer) -> dict[str, object]:
    """Run the sealed exact diagnostic sources against the current VPS."""

    checkpoint = _read_sealed_json(CHECKPOINT)
    news_evidence = _read_sealed_json(NEWS_EVIDENCE)
    _verify_source_hashes(checkpoint)
    dry_run = streamer.stream("bash -s -- --dry-run", CONTROL_SCRIPT.read_text(encoding="utf-8"))
    if dry_run.exit_code != 0 or "DRY_RUN_ONLY" not in dry_run.stdout:
        raise LiveImagePreflightError("exact current/target/forward image dry-run denied")
    binding = _object(
        _object(_object(checkpoint["collectors"])["production_preservation"])[
            "explicit_expected_news"
        ]
    )
    command = (
        "python3 - --expected-news-id "
        + str(binding["publication_id"])
        + " --expected-news-hash "
        + str(binding["publication_hash"])
        + " --expected-news-member-count "
        + str(binding["member_count"])
    )
    commands = {
        "preservation": command,
        "https": "python3 -",
        "compose": "python3 -",
        "target_runtime": TARGET_RUNTIME_COMMAND,
    }
    reports = {
        name: _report(
            streamer.stream(
                commands[name], PROBE_SOURCES[name].read_text(encoding="utf-8"), timeout=180
            ),
            name,
        )
        for name in ("preservation", "https", "compose", "target_runtime")
    }
    return validate_reports(checkpoint, news_evidence, reports, now=datetime.now(UTC))


def main() -> int:
    """Perform only a source-sealed production read-only action preflight."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("--dry-run is required; live image switching is not enabled")
    try:
        paramiko = importlib.import_module("paramiko")
        client = paramiko.SSHClient()
        client.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            os.environ["AGOM_VPS_HOST"],
            port=int(os.environ["AGOM_VPS_PORT"]),
            username=os.environ["AGOM_VPS_USER"],
            password=os.environ["AGOM_VPS_PASS"],
            timeout=15,
            look_for_keys=False,
            allow_agent=False,
        )

        class Streamer:
            def stream(self, command: str, source: str, timeout: int = 120) -> RemoteResult:
                """Stream a checked source and discard remote error/body values."""

                stdin, stdout, _stderr = client.exec_command(command, timeout=timeout)
                stdin.write(source)
                stdin.channel.shutdown_write()
                output = stdout.read().decode("utf-8")
                status = stdout.channel.recv_exit_status()
                return RemoteResult(status, output)

        try:
            report = collect_preflight(Streamer())
        finally:
            client.close()
    except (OSError, KeyError, ValueError, LiveImagePreflightError) as exc:
        print(f"DENY: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
