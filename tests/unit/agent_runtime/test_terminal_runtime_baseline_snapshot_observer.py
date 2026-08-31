"""Focused tests for the offline TAR-01 snapshot/evidence boundary."""

from __future__ import annotations

import ast
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_baseline import (
    TerminalRuntimeBaselineCandidate,
)
from apps.agent_runtime.application.terminal_runtime_baseline_collector import (
    TerminalRuntimeBaselineCollectionRequest,
    TerminalRuntimeBaselineCollector,
    TerminalRuntimeBaselineObservationRequest,
)
from apps.agent_runtime.application.terminal_runtime_baseline_evidence import (
    serialize_terminal_runtime_baseline_report,
    terminal_runtime_baseline_artifact_sha256,
)
from apps.agent_runtime.application.terminal_runtime_slo import terminal_runtime_slo_criteria
from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix_digest,
)
from apps.agent_runtime.infrastructure.terminal_runtime_baseline_snapshot_observer import (
    JsonSnapshotSource,
    TerminalRuntimeBaselineSnapshotObserver,
    TerminalRuntimeSnapshotError,
)
from scripts.record_terminal_runtime_baseline_evidence import _write_append_only
from scripts.record_terminal_runtime_baseline_evidence import main as record_main

_CANDIDATE = {
    "candidate_commit": "da04c053aa16bd940a45896a531ee567a8a2a892",
    "candidate_release": "20260819145227",
    "oci_revision": "sha256:" + "c" * 64,
    "runtime_manifest_digest": "a" * 64,
    "test_matrix_digest": canonical_terminal_runtime_test_matrix_digest(),
}
_CAPTURED_AT = "2026-08-19T07:00:00.000000Z"


def _snapshot() -> dict[str, object]:
    """Build one complete, deterministic valid bundle."""

    metric_keys = (
        "cpu_percent",
        "daphne_active_requests",
        "db_connections",
        "mcp_latency_ms",
        "model_latency_ms",
        "redis_connected_clients",
        "redis_memory_bytes",
        "rss_bytes",
        "web_p50_ms",
        "web_p95_ms",
        "web_p99_ms",
        "worker_heartbeat_age_seconds",
    )
    metrics = [
        {"key": key, "status": "observed", "value": 0, "reason": None} for key in metric_keys
    ]
    measurements = [
        {
            "key": criterion.key,
            "status": "observed",
            "value": criterion.threshold,
            "reason": None,
        }
        for criterion in terminal_runtime_slo_criteria()
    ]
    samples = {
        str(level): {
            "sample_count": 20,
            "captured_at": _CAPTURED_AT,
            "metrics": metrics,
        }
        for level in (1, 5, 10, 20)
    }
    return {
        "format": "terminal-runtime-baseline-snapshot.v1",
        "environment": "staging",
        "candidate": dict(_CANDIDATE),
        "samples": samples,
        "slo_report": {"captured_at": _CAPTURED_AT, "measurements": measurements},
        "source": {"kind": "controlled_fixture"},
    }


def _observer(payload: dict[str, object]) -> TerminalRuntimeBaselineSnapshotObserver:
    """Construct an observer from canonical JSON bytes."""

    return TerminalRuntimeBaselineSnapshotObserver(
        JsonSnapshotSource(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )


def test_valid_snapshot_collects_complete_report() -> None:
    """A complete candidate-bound bundle satisfies the pure collector."""

    observer = _observer(_snapshot())
    report = TerminalRuntimeBaselineCollector(observer).collect(
        TerminalRuntimeBaselineCollectionRequest(
            environment="staging", candidate_identity=observer.candidate
        )
    )

    assert report.ready_for_capacity_gate is True
    assert observer.environment == "staging"
    assert len(observer.source_payload_sha256) == 64


def test_unknown_top_level_key_is_rejected() -> None:
    """Unknown fields cannot be smuggled into evidence."""

    payload = _snapshot()
    payload["unexpected"] = "value"
    with pytest.raises(TerminalRuntimeSnapshotError, match="key set"):
        _observer(payload)


def test_secret_named_field_is_rejected_without_echoing_value() -> None:
    """Secret-bearing fields fail closed and are never included in errors."""

    payload = _snapshot()
    payload["source"] = {"kind": "controlled_fixture", "api_key": "never-print-me"}
    with pytest.raises(TerminalRuntimeSnapshotError) as caught:
        _observer(payload)
    assert "never-print-me" not in str(caught.value)


def test_candidate_mismatch_is_rejected_before_collection() -> None:
    """The observer cannot serve a different environment/candidate request."""

    observer = _observer(_snapshot())
    other = TerminalRuntimeBaselineCandidate(
        candidate_commit=_CANDIDATE["candidate_commit"],
        candidate_release="other-release",
        oci_revision=_CANDIDATE["oci_revision"],
        runtime_manifest_digest=_CANDIDATE["runtime_manifest_digest"],
        test_matrix_digest=_CANDIDATE["test_matrix_digest"],
    )
    with pytest.raises(TerminalRuntimeSnapshotError, match="identity"):
        observer.observe(
            TerminalRuntimeBaselineObservationRequest(
                environment="staging", candidate_identity=other, concurrency=1
            )
        )


def test_serializer_is_deterministic_and_non_enabling() -> None:
    """Serialized evidence binds the source digest but never enables runtime."""

    raw = json.dumps(_snapshot(), separators=(",", ":")).encode("utf-8")
    observer = TerminalRuntimeBaselineSnapshotObserver(JsonSnapshotSource(raw))
    report = TerminalRuntimeBaselineCollector(observer).collect(
        TerminalRuntimeBaselineCollectionRequest(
            environment="staging", candidate_identity=observer.candidate
        )
    )
    payload = serialize_terminal_runtime_baseline_report(
        report,
        source_kind="controlled_fixture",
        source_payload_sha256=hashlib.sha256(raw).hexdigest(),
    )
    assert payload == serialize_terminal_runtime_baseline_report(
        report,
        source_kind="controlled_fixture",
        source_payload_sha256=hashlib.sha256(raw).hexdigest(),
    )
    decoded = json.loads(payload)
    assert decoded["runtime_enablement"] == "not_authorized"
    assert decoded["evidence_scope"] == "offline_snapshot"
    assert decoded["computed_ready_for_capacity_gate"] is True
    assert "password" not in payload.decode("utf-8")
    assert terminal_runtime_baseline_artifact_sha256(payload) == hashlib.sha256(payload).hexdigest()

    staging_payload = serialize_terminal_runtime_baseline_report(
        report,
        source_kind="staging_http_prometheus",
        source_payload_sha256=hashlib.sha256(b"raw-staging-source").hexdigest(),
        evidence_scope="controlled_staging_observation",
    )
    assert json.loads(staging_payload)["evidence_scope"] == ("controlled_staging_observation")


def test_noncanonical_timestamp_is_rejected() -> None:
    """The parser requires explicit UTC-Z timestamps."""

    payload = _snapshot()
    payload["samples"]["1"]["captured_at"] = datetime.now(UTC).isoformat()
    with pytest.raises(TerminalRuntimeSnapshotError, match="sample 1"):
        _observer(payload)


def test_snapshot_module_has_no_runtime_or_network_imports() -> None:
    """The offline observer cannot accidentally become a load runner."""

    source = Path(
        "apps/agent_runtime/infrastructure/terminal_runtime_baseline_snapshot_observer.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(
        forbidden in name
        for name in imported
        for forbidden in ("requests", "celery", "django", "subprocess", "socket")
    )


def test_content_addressed_writer_is_idempotent_and_rejects_collision(tmp_path: Path) -> None:
    """Evidence writes never overwrite bytes at an existing digest path."""

    payload = b"canonical-evidence"
    digest = hashlib.sha256(payload).hexdigest()
    path, created = _write_append_only(tmp_path, digest, payload)
    assert created is True
    assert path.read_bytes() == payload
    same_path, created_again = _write_append_only(tmp_path, digest, payload)
    assert same_path == path
    assert created_again is False
    with pytest.raises(ValueError, match="collision"):
        _write_append_only(tmp_path, digest, b"different-bytes")


def test_record_cli_defaults_to_dry_run_and_supports_append(tmp_path: Path, monkeypatch) -> None:
    """The CLI is read-only by default and writes only when explicitly requested."""

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["record_terminal_runtime_baseline_evidence.py", "--input", str(snapshot_path)]
    )
    assert record_main() == 0
    assert not (tmp_path / "terminal-agent-baseline").exists()

    output_root = tmp_path / "evidence"
    monkeypatch.setattr(
        "sys.argv",
        [
            "record_terminal_runtime_baseline_evidence.py",
            "--input",
            str(snapshot_path),
            "--output-root",
            str(output_root),
            "--write",
        ],
    )
    assert record_main() == 0
    assert list((output_root / "terminal-agent-baseline").rglob("*.json"))
