"""Run the opt-in TAR-06 staging staircase and record candidate-bound evidence.

The default mode is validation-only and performs no network I/O.  ``--execute``
requires an approved preflight, a non-production manifest, an explicit output
root, and twenty staging API credentials plus Prometheus credentials supplied
as bounded JSON on stdin.  Credentials, prompt text, and response bodies are
never written to evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ``core.exceptions`` is part of the repository exception contract and imports
# DRF settings.  Initialize Django for direct CLI use before importing the
# harness.  The SQLite development settings keep validation-only mode local;
# an explicitly supplied staging settings module remains authoritative.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite")
import django  # noqa: E402

django.setup()

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineReport,
    required_concurrency_levels,
)
from apps.agent_runtime.application.terminal_runtime_baseline_collector import (
    TerminalRuntimeBaselineCollectionRequest,
    TerminalRuntimeBaselineObservationRequest,
)
from apps.agent_runtime.application.terminal_runtime_baseline_evidence import (
    serialize_terminal_runtime_baseline_report,
    terminal_runtime_baseline_artifact_sha256,
)
from apps.agent_runtime.infrastructure.terminal_runtime_controlled_observer import (
    TerminalRuntimeBaselineControlledObserver,
)
from apps.agent_runtime.infrastructure.terminal_runtime_staging_harness import (
    RequestsTerminalRuntimePrometheusClient,
    RequestsTerminalRuntimeStagingHttpClient,
    TerminalRuntimePrometheusCredentials,
    TerminalRuntimeStagingActor,
    TerminalRuntimeStagingConfigurationError,
    TerminalRuntimeStagingHarness,
    TerminalRuntimeStagingSpecification,
    parse_terminal_runtime_staging_manifest,
)
from core.exceptions import AgomTradeProException

_MAX_CREDENTIAL_BYTES = 256 * 1024
_SOURCE_KIND = "staging_http_prometheus"


@dataclass(frozen=True, slots=True)
class TerminalRuntimeStagingCredentialBundle:
    """In-memory credentials consumed by one staging execution only."""

    actors: tuple[TerminalRuntimeStagingActor, ...]
    prometheus: TerminalRuntimePrometheusCredentials


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    """Narrow a decoded credential object without echoing its values."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TerminalRuntimeStagingConfigurationError(f"{field_name} must be an object")
    return cast(Mapping[str, object], value)


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], field_name: str) -> None:
    """Reject missing and unknown credential fields."""

    if set(value) != expected:
        raise TerminalRuntimeStagingConfigurationError(f"{field_name} has an invalid key set")


def parse_staging_credentials(payload: bytes) -> TerminalRuntimeStagingCredentialBundle:
    """Parse twenty API tokens and one Prometheus credential pair from stdin bytes."""

    if type(payload) is not bytes or not payload or len(payload) > _MAX_CREDENTIAL_BYTES:
        raise TerminalRuntimeStagingConfigurationError("credential payload is invalid")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerminalRuntimeStagingConfigurationError(
            "credential payload is not valid UTF-8 JSON"
        ) from exc
    top = _mapping(decoded, "credentials")
    _exact_keys(top, frozenset({"actors", "prometheus"}), "credentials")
    raw_actors = top["actors"]
    if not isinstance(raw_actors, list) or len(raw_actors) != 20:
        raise TerminalRuntimeStagingConfigurationError(
            "credentials must contain exactly twenty staging actors"
        )
    actors: list[TerminalRuntimeStagingActor] = []
    for raw_actor in raw_actors:
        actor = _mapping(raw_actor, "credentials.actors[]")
        _exact_keys(actor, frozenset({"alias", "api_token"}), "credentials.actors[]")
        alias = actor["alias"]
        api_token = actor["api_token"]
        if type(alias) is not str or type(api_token) is not str:
            raise TerminalRuntimeStagingConfigurationError(
                "staging actor credential types are invalid"
            )
        actors.append(TerminalRuntimeStagingActor(alias=alias, api_token=api_token))
    prometheus = _mapping(top["prometheus"], "credentials.prometheus")
    _exact_keys(
        prometheus,
        frozenset({"username", "password"}),
        "credentials.prometheus",
    )
    username = prometheus["username"]
    password = prometheus["password"]
    if type(username) is not str or type(password) is not str:
        raise TerminalRuntimeStagingConfigurationError("Prometheus credential types are invalid")
    return TerminalRuntimeStagingCredentialBundle(
        actors=tuple(actors),
        prometheus=TerminalRuntimePrometheusCredentials(
            username=username,
            password=password,
        ),
    )


def collect_staging_baseline_report(
    harness: TerminalRuntimeStagingHarness,
) -> TerminalRuntimeBaselineReport:
    """Run each exact level once through the controlled observer composition."""

    observer = TerminalRuntimeBaselineControlledObserver(harness, harness, harness)
    request = TerminalRuntimeBaselineCollectionRequest(
        environment=harness.specification.environment,
        candidate_identity=harness.specification.candidate_identity,
    )
    samples = tuple(
        observer.observe(
            TerminalRuntimeBaselineObservationRequest(
                environment=request.environment,
                candidate_identity=request.candidate_identity,
                concurrency=level,
            )
        )
        for level in sorted(required_concurrency_levels())
    )
    return TerminalRuntimeBaselineReport(
        samples=samples,
        slo_report=observer.observe_slo(request),
    )


def serialize_staging_snapshot(report: TerminalRuntimeBaselineReport) -> bytes:
    """Serialize a recorder-compatible v1 snapshot from one live staging report."""

    report.__post_init__()
    candidate = report.samples[0].candidate_identity
    if candidate is None or report.slo_report is None:
        raise TerminalRuntimeStagingConfigurationError(
            "staging report is not fully candidate-bound"
        )
    payload: dict[str, object] = {
        "format": "terminal-runtime-baseline-snapshot.v1",
        "environment": report.samples[0].environment,
        "candidate": {
            "candidate_commit": candidate.candidate_commit,
            "candidate_release": candidate.candidate_release,
            "oci_revision": candidate.oci_revision,
            "runtime_manifest_digest": candidate.runtime_manifest_digest,
            "test_matrix_digest": candidate.test_matrix_digest,
        },
        "samples": {
            str(sample.concurrency): {
                "sample_count": sample.sample_count,
                "captured_at": _utc_text(sample.captured_at),
                "metrics": [
                    {
                        "key": metric.key,
                        "status": metric.status.value,
                        "value": metric.value,
                        "reason": metric.reason,
                    }
                    for metric in sample.metrics
                ],
            }
            for sample in sorted(report.samples, key=lambda item: item.concurrency)
        },
        "slo_report": {
            "captured_at": _utc_text(report.slo_report.captured_at),
            "measurements": [
                {
                    "key": measurement.key,
                    "status": measurement.status.value,
                    "value": measurement.value,
                    "reason": measurement.reason,
                }
                for measurement in report.slo_report.measurements
            ],
        },
        "source": {"kind": _SOURCE_KIND},
    }
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _utc_text(value: datetime) -> str:
    """Serialize an aware timestamp as canonical UTC text."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise TerminalRuntimeStagingConfigurationError("staging report contains a naive timestamp")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _write_content_addressed(
    *,
    output_root: Path,
    category: str,
    payload: bytes,
) -> tuple[Path, str, bool]:
    """Append one content-addressed artifact and verified SHA-256 sidecar."""

    digest = hashlib.sha256(payload).hexdigest()
    resolved_root = output_root.resolve()
    artifact_dir = (resolved_root / category / digest[:2]).resolve()
    if resolved_root not in artifact_dir.parents:
        raise TerminalRuntimeStagingConfigurationError("output path escapes output root")
    artifact_path = artifact_dir / f"{digest}.json"
    digest_path = artifact_dir / f"{digest}.sha256"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    created = False
    if artifact_path.exists():
        if artifact_path.read_bytes() != payload:
            raise TerminalRuntimeStagingConfigurationError("content-addressed artifact collision")
    else:
        with artifact_path.open("xb") as artifact_file:
            artifact_file.write(payload)
        created = True
    expected_sidecar = f"{digest}\n".encode("ascii")
    if digest_path.exists():
        if digest_path.read_bytes() != expected_sidecar:
            raise TerminalRuntimeStagingConfigurationError("content-addressed sidecar collision")
    else:
        with digest_path.open("xb") as digest_file:
            digest_file.write(expected_sidecar)
    return artifact_path, digest, created


def _parser() -> argparse.ArgumentParser:
    """Build the fail-closed command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--approved-preflight", required=True, type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform staging network I/O; default is validation-only.",
    )
    parser.add_argument(
        "--credentials-stdin",
        action="store_true",
        help="Read bounded secret JSON from stdin; required with --execute.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Append-only evidence root; required with --execute.",
    )
    return parser


def _dry_run_output(specification: TerminalRuntimeStagingSpecification) -> dict[str, object]:
    """Build a secret-free, no-I/O validation summary."""

    missing_baseline = sum(
        query.expression is None for query in specification.baseline_metric_queries
    )
    missing_slo = sum(query.expression is None for query in specification.slo_queries)
    return {
        "mode": "validation_only",
        "network_io": False,
        "environment": specification.environment,
        "candidate_commit": specification.candidate_identity.candidate_commit,
        "manifest_sha256": specification.manifest_sha256,
        "approved_preflight_sha256": specification.approved_preflight_sha256,
        "levels": sorted(required_concurrency_levels()),
        "total_request_budget": specification.total_request_budget,
        "missing_baseline_queries": missing_baseline,
        "missing_slo_queries": missing_slo,
        "runtime_enablement": "not_authorized",
    }


def _execute(
    *,
    specification: TerminalRuntimeStagingSpecification,
    credentials: TerminalRuntimeStagingCredentialBundle,
    output_root: Path,
) -> tuple[dict[str, object], bool]:
    """Run the staging harness and append raw, snapshot, and canonical evidence."""

    harness = TerminalRuntimeStagingHarness(
        specification=specification,
        actors=credentials.actors,
        http_port=RequestsTerminalRuntimeStagingHttpClient(
            base_url=specification.base_url,
            timeout_seconds=specification.request_timeout_seconds,
        ),
        prometheus_port=RequestsTerminalRuntimePrometheusClient(
            prometheus_url=specification.prometheus_url,
            credentials=credentials.prometheus,
            timeout_seconds=specification.request_timeout_seconds,
        ),
    )
    report = collect_staging_baseline_report(harness)
    source_receipt = harness.serialize_source_receipt()
    snapshot = serialize_staging_snapshot(report)
    source_payload_sha256 = hashlib.sha256(source_receipt).hexdigest()
    evidence = serialize_terminal_runtime_baseline_report(
        report,
        source_kind=_SOURCE_KIND,
        source_payload_sha256=source_payload_sha256,
        evidence_scope="controlled_staging_observation",
    )
    source_path, source_digest, source_created = _write_content_addressed(
        output_root=output_root,
        category="terminal-agent-staging-source",
        payload=source_receipt,
    )
    snapshot_path, snapshot_digest, snapshot_created = _write_content_addressed(
        output_root=output_root,
        category="terminal-agent-baseline-snapshot",
        payload=snapshot,
    )
    evidence_path, evidence_digest, evidence_created = _write_content_addressed(
        output_root=output_root,
        category="terminal-agent-baseline",
        payload=evidence,
    )
    if evidence_digest != terminal_runtime_baseline_artifact_sha256(evidence):
        raise TerminalRuntimeStagingConfigurationError(
            "canonical evidence digest verification failed"
        )
    output: dict[str, object] = {
        "mode": "executed",
        "network_io": True,
        "environment": specification.environment,
        "candidate_commit": specification.candidate_identity.candidate_commit,
        "computed_ready_for_capacity_gate": report.ready_for_capacity_gate,
        "capacity_contract_result": ("PASS" if report.ready_for_capacity_gate else "DENY"),
        "tar05_acceptance": "not_granted",
        "production_claim": False,
        "runtime_enablement": "not_authorized",
        "source_receipt": {
            "path": str(source_path),
            "sha256": source_digest,
            "written": source_created,
        },
        "baseline_snapshot": {
            "path": str(snapshot_path),
            "sha256": snapshot_digest,
            "written": snapshot_created,
        },
        "canonical_evidence": {
            "path": str(evidence_path),
            "sha256": evidence_digest,
            "written": evidence_created,
        },
    }
    return output, report.ready_for_capacity_gate


def main() -> int:
    """Validate only by default, or execute one explicitly authorized staging run."""

    args = _parser().parse_args()
    try:
        manifest = args.manifest.read_bytes()
        approved_preflight = args.approved_preflight.read_bytes()
        specification = parse_terminal_runtime_staging_manifest(
            manifest,
            approved_preflight=approved_preflight,
        )
        if not args.execute:
            if args.credentials_stdin or args.output_root is not None:
                raise TerminalRuntimeStagingConfigurationError(
                    "credentials and output root are only valid with --execute"
                )
            print(json.dumps(_dry_run_output(specification), sort_keys=True))
            return 0
        if not args.credentials_stdin or args.output_root is None:
            raise TerminalRuntimeStagingConfigurationError(
                "--execute requires --credentials-stdin and --output-root"
            )
        credential_payload = sys.stdin.buffer.read(_MAX_CREDENTIAL_BYTES + 1)
        credentials = parse_staging_credentials(credential_payload)
        output, ready = _execute(
            specification=specification,
            credentials=credentials,
            output_root=args.output_root,
        )
        print(json.dumps(output, sort_keys=True))
        return 0 if ready else 2
    except (AgomTradeProException, OSError, ValueError) as exc:
        print(f"Terminal runtime staging baseline: FAIL - {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
