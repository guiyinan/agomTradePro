"""Operator-side EVID-09 Web-only target interval and forward recovery.

The default is a source-bound read-only dry-run. An explicitly selected live
exercise runs the fresh diagnostic gate immediately before a Web-only target
interval; the VPS script has an EXIT recovery trap and a separate manual
forward-recovery mode. It never restores PostgreSQL, publishes TUI registry,
changes the current symlink or touches another Compose service.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shlex
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from scripts import evid09_live_image_preflight as gate

SCRIPT = gate.ROOT / "scripts/evid09_web_only_image_exercise.sh"
SCRIPT_SHA256 = "b34780230e8f984ea0a9644e332c3edefe95c8352e90a01f5b7c669d6a3705d6"
RAW_PROBE = gate.ROOT / "scripts/evid09_tui02_raw_observation_preflight.py"
RAW_PROBE_SHA256 = "878206cf3b9882db695a4cbb3f76ba3b5e8430feb9184b448d352e8ca1ef15af"
INTERVAL_IDENTITY_PROBE = gate.ROOT / "scripts/evid09_web_interval_identity_probe.py"
INTERVAL_IDENTITY_PROBE_SHA256 = "c1b102bfe4155b26e6dc752dc958fb6520c849b02ac062a28e58a6e4371c56b2"
MANIFEST_SHA256_BY_PERIOD = {
    "target-period": "b5fcfa71f5635fa95e8d24b4822894e5f4ce4bf0b4c99ee8e3fa5be5cd154167",
    "post-recovery": "b0b58b749ef1488695bb32e158f5d2ead8d83c90d5c5050e1e69d3f5a88b6bb6",
}
OWNER_TOKEN = "EVID09-891c40c57-6760c9aa-20260915"
TARGET_READY = re.compile(
    r"^TARGET_READY image=(sha256:[0-9a-f]{64}) started_at=(\S+) health=healthy fifo=(/tmp/evid09-web-recovery-[A-Za-z0-9]{6}/recovery\.fifo)$"
)
FORWARD_RECOVERED = re.compile(
    r"^FORWARD_RECOVERED image=(sha256:[0-9a-f]{64}) started_at=(\S+) health=healthy(?: already_current=true)?$"
)


class WebOnlyActionError(ValueError):
    """Deny an unbounded or unverified Web-only target interval."""


class RecoveredIntervalDenied(WebOnlyActionError):
    """Carry a verified forward-recovery checkpoint for a denied target."""

    def __init__(self, report: dict[str, object]) -> None:
        super().__init__("target-period denied after verified forward recovery")
        self.report = report


@dataclass(frozen=True)
class WebIdentity:
    """One real Docker Web image and start event."""

    image_id: str
    started_at_utc: datetime


class IntervalHandle(Protocol):
    """Recovery-capable SSH command controlled through a separate FIFO."""

    def first_line(self) -> str:
        """Read the target-ready event, or the first failure event."""

    def request_recovery(self) -> gate.RemoteResult:
        """Send the exact forward-recovery instruction and wait for exit."""


class ActionSession(gate.RemoteStreamer, Protocol):
    """Expose only bounded source-streaming and the recovery-capable interval."""

    def begin_interval(self, source: str, preflight_digest: str) -> IntervalHandle:
        """Start the exact Web-only remote target/forward shell entry."""

    def manual_recover(self, source: str) -> gate.RemoteResult:
        """Run the independently callable original-image forward recovery."""


def _source() -> str:
    """Reject action shell source drift from the reviewed dry-run version."""

    raw = SCRIPT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SCRIPT_SHA256:
        raise WebOnlyActionError("Web-only action source hash drift")
    return raw.decode("utf-8")


def _deny_active_tui_observation(session: ActionSession) -> None:
    """Protect a genuine raw TUI-02 sample before any candidate-changing action."""

    raw = RAW_PROBE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RAW_PROBE_SHA256:
        raise WebOnlyActionError("TUI-02 raw-observation probe source hash drift")
    result = session.stream("python3 -", raw.decode("utf-8"), timeout=45)
    report = gate._report(result, "TUI-02 raw observation")
    if (
        report.get("decision") != "PASS_NO_RAW_SAMPLE"
        or report.get("authenticated_https_status") != 200
        or report.get("raw_vector_count") != 0
    ):
        raise WebOnlyActionError("active TUI-02 raw observation protects the current Web image")


def _identity(line: str, pattern: re.Pattern[str], expected_image: str) -> WebIdentity:
    match = pattern.fullmatch(line.strip())
    if match is None or match.group(1) != expected_image:
        raise WebOnlyActionError("Web image/health event did not match the exact action")
    return WebIdentity(match.group(1), gate._utc(match.group(2), "Docker Web started_at"))


def _verified_forward_recovery(result: gate.RemoteResult, expected_image: str) -> WebIdentity:
    """Accept only one exact healthy current-Web event from an exited path."""

    if result.exit_code != 0:
        raise WebOnlyActionError("original-image forward recovery did not exit zero")
    lines = [line for line in result.stdout.splitlines() if line.startswith("FORWARD_RECOVERED ")]
    if len(lines) != 1:
        raise WebOnlyActionError("forward-recovered Docker event missing")
    return _identity(lines[0], FORWARD_RECOVERED, expected_image)


def _sample_interval_identity(session: ActionSession, web: WebIdentity, *, period: str) -> datetime:
    """Prove the exact Docker Web remains in this interval during collection."""

    raw = INTERVAL_IDENTITY_PROBE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INTERVAL_IDENTITY_PROBE_SHA256:
        raise WebOnlyActionError("Web interval identity probe source hash drift")
    report = gate._report(session.stream("python3 -", raw.decode("utf-8"), timeout=30), period)
    reported_start = gate._utc(report.get("started_at_utc"), f"{period} Docker Web")
    observed = gate._utc(report.get("observed_at_utc"), f"{period} Docker identity")
    if (
        report.get("schema") != "evid09.web-interval-identity.v1"
        or report.get("decision") != "PASS_READ_ONLY"
        or report.get("image_id") != web.image_id
        or reported_start != web.started_at_utc
        or report.get("release_manifest_sha256") != MANIFEST_SHA256_BY_PERIOD[period]
        or report.get("status") != "running"
        or report.get("health") != "healthy"
        or report.get("business_dml_performed") is not False
        or observed < web.started_at_utc
        or observed > datetime.now(UTC) + timedelta(seconds=10)
    ):
        raise WebOnlyActionError(f"{period} Docker Web identity drift")
    return observed


def _target_business_stop_lines(
    session: ActionSession,
    web: WebIdentity,
    checkpoint: dict[str, object],
    news_evidence: dict[str, object],
    *,
    period: str,
) -> dict[str, object]:
    """Bind read-only preservation and a new HTTPS scrape to one Web start."""

    binding = gate._object(news_evidence["new_current_news"])
    identity_before = _sample_interval_identity(session, web, period=period)
    command = (
        "python3 - --expected-news-id "
        + str(binding["publication_id"])
        + " --expected-news-hash "
        + str(binding["publication_hash"])
        + " --expected-news-member-count "
        + str(binding["member_count"])
    )
    preservation = gate._report(
        session.stream(
            command,
            gate.PROBE_SOURCES["preservation"].read_text(encoding="utf-8"),
            timeout=90,
        ),
        "target interval preservation",
    )
    expected_rows = gate._object(gate._object(news_evidence["read_only_preservation"])["rowsets"])
    actual_rows = gate._object(preservation.get("rows"))
    if set(actual_rows) != set(expected_rows):
        raise WebOnlyActionError(f"{period} preservation rowset labels drift")
    for label, raw in expected_rows.items():
        expected = gate._object(raw)
        actual = gate._object(actual_rows.get(label))
        if actual.get("count") != expected.get("count") or actual.get(
            "rowset_sha256"
        ) != expected.get("sha256"):
            raise WebOnlyActionError(f"{period} {label} rowset drift")
    expected_news = {
        "publication_id": binding.get("publication_id"),
        "publication_hash": binding.get("publication_hash"),
        "member_count": binding.get("member_count"),
    }
    reported_news = gate._object(preservation.get("news_current_identity"))
    specified_news = gate._object(preservation.get("expected_news_identity"))
    preservation_at = gate._utc(preservation.get("observed_at_utc"), f"{period} preservation")
    current_commit = gate._object(checkpoint["production_candidate"])["commit"]
    target_commit = gate._object(checkpoint["target"])["commit"]
    if (
        preservation.get("decision") != "PASS_READ_ONLY"
        or preservation.get("transaction") != "REPEATABLE READ READ ONLY; ROLLBACK"
        or preservation.get("candidate_commit") != current_commit
        or preservation.get("target_commit") != target_commit
        or preservation.get("expected_counts_match") is not True
        or preservation.get("four_immutable_authority_root_hashes_match") is not True
        or preservation.get("news_current_id_hash_and_member_count_match") is not True
        or any(specified_news.get(key) != value for key, value in expected_news.items())
        or any(reported_news.get(key) != value for key, value in expected_news.items())
        or preservation.get("raw_row_values_emitted") is not False
        or preservation.get("business_dml_performed") is not False
        or preservation_at < web.started_at_utc
        or preservation_at < identity_before
    ):
        raise WebOnlyActionError(f"{period} preservation identity, time or decision drift")
    https = gate._report(
        session.stream(
            "python3 -", gate.PROBE_SOURCES["https"].read_text(encoding="utf-8"), timeout=90
        ),
        "target interval HTTPS",
    )
    up = gate._object(https.get("retained_up_target"))
    up_at = gate._utc(up.get("sample_at_utc"), f"{period} up")
    https_at = gate._utc(https.get("observed_at_utc"), f"{period} HTTPS")
    if (
        https.get("decision") != "PASS_READ_ONLY"
        or https.get("base_url") != "https://demo.agomtrade.pro"
        or https.get("tls_default_trust_used") is not True
        or https.get("secret_values_emitted") is not False
        or https.get("decision_gate_cleared") is not False
        or https.get("https_statuses") != gate.REQUIRED_HTTPS_STATUSES
        or https.get("protected_query_authenticated_status") != 200
        or https.get("protected_query_unauthenticated_status") != 401
        or up.get("job") != "agomtradepro"
        or up.get("instance") != "web:8000"
        or up.get("value") != 1
        or preservation_at > https_at
        or https_at - preservation_at > timedelta(seconds=180)
        or https_at < web.started_at_utc
        or up_at < web.started_at_utc
        or up_at > https_at + timedelta(seconds=10)
        or https_at - up_at > timedelta(seconds=90)
    ):
        raise WebOnlyActionError(f"{period} protected HTTPS or new scrape stop line drift")
    identity_after = _sample_interval_identity(session, web, period=period)
    if identity_after < https_at or identity_after - identity_before > timedelta(seconds=180):
        raise WebOnlyActionError(f"{period} Docker Web identity bracket drift")
    return {
        "period": period,
        "web_started_at_utc": web.started_at_utc.isoformat(),
        "preservation_observed_at_utc": preservation["observed_at_utc"],
        "protected_https_observed_at_utc": https["observed_at_utc"],
        "retained_web_up_sample_at_utc": up["sample_at_utc"],
        "web_identity_before_observed_at_utc": identity_before.isoformat(),
        "web_identity_after_observed_at_utc": identity_after.isoformat(),
        "all_eight_rowset_sha256_match": True,
        "decision_gate_still_blocked": True,
    }


def exercise_once(
    session: ActionSession, *, accept_interruption: bool, accept_tui_reset: bool
) -> dict[str, object]:
    """Run one bounded target interval, always recovering the current Web."""

    if not accept_interruption or not accept_tui_reset:
        raise WebOnlyActionError("bounded interruption and TUI-02 reset must be accepted")
    source = _source()
    pre = gate.collect_preflight(session)
    _deny_active_tui_observation(session)
    digest = hashlib.sha256(
        json.dumps(pre, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    checkpoint = gate._read_sealed_json(gate.CHECKPOINT)
    target_image = str(gate._object(checkpoint["target"])["web_image_id"])
    current_image = str(gate._object(checkpoint["production_candidate"])["web_image_id"])
    news_evidence = gate._read_sealed_json(gate.NEWS_EVIDENCE)
    handle = session.begin_interval(source, digest)
    target: WebIdentity | None = None
    target_stops: dict[str, object] | None = None
    target_failure: OSError | ValueError | None = None
    recovery_path: str
    recovered: WebIdentity
    try:
        target = _identity(
            handle.first_line(),
            TARGET_READY,
            target_image,
        )
        target_stops = _target_business_stop_lines(
            session, target, checkpoint, news_evidence, period="target-period"
        )
    except (OSError, ValueError) as exc:
        target_failure = exc
    finally:
        try:
            recovered = _verified_forward_recovery(handle.request_recovery(), current_image)
            recovery_path = "interactive"
        except (OSError, ValueError):
            try:
                recovered = _verified_forward_recovery(
                    session.manual_recover(source), current_image
                )
            except (OSError, ValueError) as exc:
                raise WebOnlyActionError(
                    "original-image forward recovery unverified after both paths"
                ) from exc
            recovery_path = "independent_manual"
    if target is not None and recovered.started_at_utc <= target.started_at_utc:
        raise WebOnlyActionError("forward recovery did not start after the target Web")
    post_recovery_stops = _target_business_stop_lines(
        session, recovered, checkpoint, news_evidence, period="post-recovery"
    )
    post = gate.collect_preflight(session)
    if target_failure is not None:
        raise RecoveredIntervalDenied(
            {
                "schema": "evid09.web-only-live-image-exercise.v1",
                "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "target_web": (
                    {
                        "image_id": target.image_id,
                        "started_at_utc": target.started_at_utc.isoformat(),
                    }
                    if target is not None
                    else None
                ),
                "target_stop_lines_verified": False,
                "forward_recovered_web": {
                    "image_id": recovered.image_id,
                    "started_at_utc": recovered.started_at_utc.isoformat(),
                },
                "recovery_path": recovery_path,
                "post_recovery_stop_lines": post_recovery_stops,
                "post_action_gate": post,
                "tui02_candidate_reset_required": True,
                "tui02_candidate_reset_performed": False,
                "decision": "DENY_TARGET_PERIOD_RECOVERED_CURRENT",
            }
        ) from target_failure
    if target is None or target_stops is None:
        raise WebOnlyActionError("target or recovery started_at ordering unavailable")
    return {
        "schema": "evid09.web-only-live-image-exercise.v1",
        "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "pre_action_gate": pre,
        "target_web": {
            "image_id": target.image_id,
            "started_at_utc": target.started_at_utc.isoformat(),
        },
        "target_stop_lines": target_stops,
        "forward_recovered_web": {
            "image_id": recovered.image_id,
            "started_at_utc": recovered.started_at_utc.isoformat(),
        },
        "recovery_path": recovery_path,
        "post_action_gate": post,
        "post_recovery_stop_lines": post_recovery_stops,
        "current_symlink_changed": False,
        "database_restore_performed": False,
        "other_compose_services_recreated": False,
        "tui02_candidate_reset_required": True,
        "tui02_candidate_reset_performed": False,
        "decision": "LIVE_WEB_ONLY_RECOVERED_TUI_RESET_PENDING",
    }


def main() -> int:
    """Run source-bound dry-run or an explicitly accepted Web-only interval."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exercise", action="store_true")
    parser.add_argument("--accept-web-interruption", action="store_true")
    parser.add_argument("--accept-tui-reset", action="store_true")
    args = parser.parse_args()
    if not args.exercise and (args.accept_web_interruption or args.accept_tui_reset):
        parser.error("acceptance flags apply only to --exercise")
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

        class Session:
            def stream(self, command: str, source: str, timeout: int = 120) -> gate.RemoteResult:
                """Stream exact source and retain no remote stderr/credentials."""

                stdin, stdout, _stderr = client.exec_command(command, timeout=timeout)
                stdin.write(source)
                stdin.flush()
                stdin.channel.shutdown_write()
                output = stdout.read().decode("utf-8")
                status = stdout.channel.recv_exit_status()
                return gate.RemoteResult(status, output)

            def begin_interval(self, source: str, preflight_digest: str) -> IntervalHandle:
                """End source stdin before awaiting a separate FIFO instruction."""

                command = (
                    f"EVID09_OWNER_ACTION_TOKEN={OWNER_TOKEN} "
                    f"EVID09_INTERNAL_GATE_SHA256={preflight_digest} "
                    "EVID09_TUI_RESET_ACCEPTED=true EVID09_DOWNTIME_ACCEPTED=true "
                    "bash -s -- --internal-exercise"
                )
                stdin, stdout, _stderr = client.exec_command(command, timeout=200)
                stdin.write(source)
                stdin.flush()
                stdin.channel.shutdown_write()

                class Handle:
                    fifo_path: str | None = None

                    def first_line(self) -> str:
                        """Wait for the exact target-ready line."""

                        line = str(stdout.readline())
                        match = TARGET_READY.fullmatch(line.strip())
                        if match is not None:
                            self.fifo_path = match.group(3)
                        return line

                    def request_recovery(self) -> gate.RemoteResult:
                        """Write one exact instruction to the root-only FIFO."""

                        if self.fifo_path is None:
                            raise WebOnlyActionError("target-ready control FIFO unavailable")
                        writer_command = r"printf '%s\n' FORWARD_RECOVER > " + shlex.quote(
                            self.fifo_path
                        )
                        writer_stdin, writer_stdout, _writer_stderr = client.exec_command(
                            writer_command, timeout=15
                        )
                        writer_stdin.channel.shutdown_write()
                        writer_stdout.read()
                        if writer_stdout.channel.recv_exit_status() != 0:
                            raise WebOnlyActionError("separate FIFO recovery writer denied")
                        output = stdout.read().decode("utf-8")
                        status = stdout.channel.recv_exit_status()
                        return gate.RemoteResult(status, output)

                return Handle()

            def manual_recover(self, source: str) -> gate.RemoteResult:
                """Use the independent manual entry if the interactive channel fails."""

                # Let the remote EXIT trap finish first; the shell mode is a
                # no-op when the original image is already healthy again.
                time.sleep(5)
                return self.stream(
                    f"EVID09_OWNER_ACTION_TOKEN={OWNER_TOKEN} bash -s -- --forward-recover",
                    source,
                    timeout=240,
                )

        try:
            session = Session()
            report = (
                exercise_once(
                    session,
                    accept_interruption=args.accept_web_interruption,
                    accept_tui_reset=args.accept_tui_reset,
                )
                if args.exercise
                else gate.collect_preflight(session)
            )
        finally:
            client.close()
    except RecoveredIntervalDenied as exc:
        print(json.dumps(exc.report, sort_keys=True, separators=(",", ":")))
        return 1
    except (OSError, KeyError, ValueError, WebOnlyActionError, gate.LiveImagePreflightError) as exc:
        print(f"DENY: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
