"""Fail-closed contracts for Web-to-TUI Classic cleanup waves."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from scripts import check_web_to_tui_cleanup_guard as cleanup_guard
from scripts.web_to_tui_candidate_binding import BINDING_VERSION, CandidateBinding

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "docs/plans/web-to-tui-migration-matrix-2026-07-25.csv"
CATALOG_PATH = ROOT / "config/tui/migration/web_to_tui_telemetry.v1.json"
EVIDENCE_PATH = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
TARGET = "core/templates/sentiment/analyze.html"
BASE_COMMIT = "a" * 40
CLEANUP_COMMIT = "b" * 40


@dataclass
class CleanupFixture:
    """Paths and mutable proof used by one isolated cleanup decision."""

    repository_root: Path
    matrix_path: Path
    catalog_path: Path
    evidence_path: Path
    graph_path: Path
    runtime_manifest_path: Path
    evidence: dict[str, Any]
    blobs: dict[tuple[str, str], bytes]


def _matrix_rows() -> tuple[list[str], list[dict[str, str]]]:
    """Read the checked-in matrix with its deterministic field order."""

    with MATRIX_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames is not None
        return list(reader.fieldnames), list(reader)


def _matrix_bytes(
    *,
    transform: Callable[[dict[str, str]], dict[str, str]],
) -> bytes:
    """Serialize one deterministic migration matrix after a focused transform."""

    fieldnames, rows = _matrix_rows()
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(transform(dict(row)) for row in rows)
    return handle.getvalue().encode("utf-8")


def _write(path: Path, value: bytes) -> None:
    """Write a fixture artifact after creating its isolated parent."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _json_bytes(value: dict[str, Any]) -> bytes:
    """Serialize a deterministic JSON fixture."""

    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _digest(value: bytes) -> str:
    """Return one SHA-256 fixture digest."""

    return hashlib.sha256(value).hexdigest()


def _binding(
    *,
    version: str,
    commit: str,
    matrix: bytes,
    graph: bytes,
    runtime: bytes,
) -> CandidateBinding:
    """Build a candidate binding from synthetic immutable Git blobs."""

    graph_payload = json.loads(graph)
    runtime_payload = json.loads(runtime)
    return {
        "version": BINDING_VERSION,
        "candidate_version": version,
        "candidate_commit": commit,
        "matrix_sha256": _digest(matrix),
        "graph_sha256": _digest(graph),
        "schema_version": str(graph_payload["schema_version"]),
        "runtime_version": str(runtime_payload["version"]),
        "runtime_build_id": str(runtime_payload["build_id"]),
        "runtime_manifest_sha256": _digest(runtime),
    }


def _catalog(matrix: bytes) -> bytes:
    """Build one bounded telemetry catalog for a matrix snapshot."""

    return _json_bytes(
        {
            "source_sha256": _digest(matrix),
            "classic_routes": [{"task_key": "sentiment.external-ai-analysis"}],
        }
    )


def _repository_path(root: Path, relative: str) -> Path:
    """Return one isolated source path using repository layout semantics."""

    return root / relative


def _build_authorized_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> CleanupFixture:
    """Build final authorization plus one exact post-deletion cleanup wave."""

    repository_root = tmp_path / "repo"
    matrix_path = _repository_path(repository_root, "docs/plans/matrix.csv")
    catalog_path = _repository_path(repository_root, "config/tui/catalog.json")
    evidence_path = _repository_path(repository_root, "config/tui/evidence.json")
    graph_path = _repository_path(repository_root, "config/tui/graph.json")
    runtime_path = _repository_path(repository_root, "config/tui/runtime.json")

    base_matrix = _matrix_bytes(transform=lambda row: row)

    def delete_target(row: dict[str, str]) -> dict[str, str]:
        if row["template_path"] == TARGET:
            row["status"] = "deleted"
            row["wave"] = "M5-B-W1"
        return row

    cleanup_matrix = _matrix_bytes(transform=delete_target)
    graph = _json_bytes({"schema_version": "tui-operation-graph.v1"})
    runtime = _json_bytes({"version": "0.9.0", "build_id": "fixture-build"})
    base_catalog = _catalog(base_matrix)
    cleanup_catalog = _catalog(cleanup_matrix)
    base_binding = _binding(
        version="0.9.0-rc1",
        commit=BASE_COMMIT,
        matrix=base_matrix,
        graph=graph,
        runtime=runtime,
    )
    cleanup_binding = _binding(
        version="0.9.0-m5-b-w1",
        commit=CLEANUP_COMMIT,
        matrix=cleanup_matrix,
        graph=graph,
        runtime=runtime,
    )

    review = {
        "version": cleanup_guard.REVIEW_SNAPSHOT_VERSION,
        "candidate_version": base_binding["candidate_version"],
        "candidate_commit": base_binding["candidate_commit"],
        "source_sha256": base_binding["matrix_sha256"],
        "reviewed_at": "2026-08-01",
        "as_of": "2026-08-01",
        "required_route_pages": cleanup_guard._required_route_count(
            cleanup_guard._matrix_rows_from_bytes(base_matrix)
        ),
        "required_tasks": 1,
        "gates": [
            {"key": key, "passed": True, "detail": "fixture"}
            for key in sorted(cleanup_guard.REQUIRED_PRE_APPROVAL_GATES)
        ],
    }
    review_bytes = _json_bytes(review)
    review_reference = "evidence/review.json"
    review_sha = _digest(review_bytes)
    review_path = repository_root / review_reference
    _write(review_path, review_bytes)

    approvals: dict[str, Any] = {}
    approval_paths: list[tuple[Path, bytes]] = []
    for role, name, approved_at in (
        ("owner", "release-owner", "2026-08-02"),
        ("reviewer", "independent-reviewer", "2026-08-03"),
    ):
        attestation = {
            "version": cleanup_guard.APPROVAL_ATTESTATION_VERSION,
            "role": role,
            "name": name,
            "decision": "approve",
            "approved_at": approved_at,
            "candidate_version": base_binding["candidate_version"],
            "candidate_commit": base_binding["candidate_commit"],
            "source_sha256": base_binding["matrix_sha256"],
            "review_snapshot": review_reference,
            "evidence_snapshot_sha256": review_sha,
        }
        attestation_bytes = _json_bytes(attestation)
        reference = f"evidence/{role}.json"
        path = repository_root / reference
        _write(path, attestation_bytes)
        projection = dict(attestation)
        projection.pop("version")
        projection["evidence"] = reference
        projection["evidence_sha256"] = _digest(attestation_bytes)
        approvals[role] = projection
        approval_paths.append((path, attestation_bytes))

    _, current_rows = _matrix_rows()
    target_row = next(row for row in current_rows if row["template_path"] == TARGET)
    rollback_manifest = {
        "version": cleanup_guard.CLEANUP_ROLLBACK_VERSION,
        "wave": "M5-B-W1",
        "authorized_candidate_commit": BASE_COMMIT,
        "cleanup_candidate_commit": CLEANUP_COMMIT,
        "deleted_paths": [TARGET],
        "route_rollback_commits": {TARGET: target_row["rollback_commit"]},
    }
    rollback_bytes = _json_bytes(rollback_manifest)
    rollback_reference = "evidence/wave-w1-rollback.json"
    _write(repository_root / rollback_reference, rollback_bytes)
    wave_report = b"M5-B-W1 targeted cleanup checks passed\n"
    wave_report_reference = "evidence/wave-w1.md"
    _write(repository_root / wave_report_reference, wave_report)
    observation = {
        "version": cleanup_guard.CLEANUP_OBSERVATION_VERSION,
        "wave": "M5-B-W1",
        "candidate_binding": cleanup_binding,
        "observed_from": "2026-08-04T00:00:00+08:00",
        "observed_until": "2026-08-06T00:00:00+08:00",
        "scheduled_cycles": [
            {
                "task_key": "sentiment.external-ai-analysis",
                "observed_at": "2026-08-05T00:00:00+08:00",
                "outcome": "success",
            }
        ],
        "defects": {"new_p0": 0, "new_p1": 0, "open_p0": 0, "open_p1": 0},
        "error_metrics": [
            {
                "task_key": "sentiment.external-ai-analysis",
                "baseline_requests": 100,
                "baseline_errors": 1,
                "candidate_requests": 100,
                "candidate_errors": 1,
            }
        ],
    }
    observation_bytes = _json_bytes(observation)
    observation_reference = "evidence/wave-w1-observation.json"
    _write(repository_root / observation_reference, observation_bytes)

    evidence = {
        "version": "web-to-tui-cutover-evidence.v1",
        "source_sha256": base_binding["matrix_sha256"],
        "candidate": {
            "stable_version": base_binding["candidate_version"],
            "candidate_commit": base_binding["candidate_commit"],
            "released_at": "2026-07-10",
            "observation_end": "2026-07-25",
            "binding": base_binding,
        },
        "review_snapshot": {"evidence": review_reference, "sha256": review_sha},
        "approvals": approvals,
        "cleanup": {
            "waves": [
                {
                    "version": cleanup_guard.CLEANUP_WAVE_VERSION,
                    "wave": "M5-B-W1",
                    "authorized_candidate_binding": base_binding,
                    "candidate_binding": cleanup_binding,
                    "catalog_sha256": _digest(cleanup_catalog),
                    "deleted_paths": [TARGET],
                    "owner": "cleanup-owner",
                    "reviewer": "cleanup-reviewer",
                    "verified_at": "2026-08-06",
                    "evidence": wave_report_reference,
                    "evidence_sha256": _digest(wave_report),
                    "rollback_manifest": rollback_reference,
                    "rollback_manifest_sha256": _digest(rollback_bytes),
                    "observation_ledger": observation_reference,
                    "observation_ledger_sha256": _digest(observation_bytes),
                }
            ]
        },
    }
    _write(matrix_path, cleanup_matrix)
    _write(catalog_path, cleanup_catalog)
    _write(graph_path, graph)
    _write(runtime_path, runtime)
    _write(evidence_path, _json_bytes(evidence))

    def relative(path: Path) -> str:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()

    blobs: dict[tuple[str, str], bytes] = {}
    for commit, matrix, catalog in (
        (BASE_COMMIT, base_matrix, base_catalog),
        (CLEANUP_COMMIT, cleanup_matrix, cleanup_catalog),
    ):
        blobs[(commit, relative(matrix_path))] = matrix
        blobs[(commit, relative(catalog_path))] = catalog
        blobs[(commit, relative(graph_path))] = graph
        blobs[(commit, relative(runtime_path))] = runtime
    for path, value in [(review_path, review_bytes), *approval_paths]:
        blobs[(CLEANUP_COMMIT, relative(path))] = value

    def fake_source_bytes(commit: str, path: Path, *, root: Path) -> bytes | None:
        assert root == repository_root
        return blobs.get((commit, relative(path)))

    def fake_ancestor(
        commit: str,
        *,
        root: Path,
        descendant: str = "HEAD",
    ) -> bool:
        assert root == repository_root
        valid = {BASE_COMMIT, CLEANUP_COMMIT, target_row["rollback_commit"]}
        return commit in valid and descendant in {"HEAD", CLEANUP_COMMIT}

    monkeypatch.setattr(cleanup_guard, "_git_source_bytes", fake_source_bytes)
    monkeypatch.setattr(cleanup_guard, "_git_commit_is_ancestor", fake_ancestor)
    return CleanupFixture(
        repository_root=repository_root,
        matrix_path=matrix_path,
        catalog_path=catalog_path,
        evidence_path=evidence_path,
        graph_path=graph_path,
        runtime_manifest_path=runtime_path,
        evidence=evidence,
        blobs=blobs,
    )


def _evaluate(fixture: CleanupFixture) -> cleanup_guard.CleanupGuardResult:
    """Evaluate one isolated matrix/evidence repository."""

    return cleanup_guard.evaluate_cleanup_guard(
        matrix_path=fixture.matrix_path,
        catalog_path=fixture.catalog_path,
        evidence_path=fixture.evidence_path,
        graph_path=fixture.graph_path,
        runtime_manifest_path=fixture.runtime_manifest_path,
        as_of=date(2026, 8, 13),
        evidence_root=fixture.repository_root,
        repository_root=fixture.repository_root,
    )


def test_checked_in_m0_d_baseline_does_not_require_m5_authorization() -> None:
    """The seven reviewed shadow deletions remain valid while M5 is DENY."""

    result = cleanup_guard.evaluate_cleanup_guard(
        matrix_path=MATRIX_PATH,
        catalog_path=CATALOG_PATH,
        evidence_path=EVIDENCE_PATH,
        as_of=date(2026, 8, 13),
    )

    assert result.allowed is True
    assert result.new_deleted_paths == ()


def test_new_deletion_without_m5_b_lifecycle_is_rejected(tmp_path: Path) -> None:
    """A new deleted row cannot disguise itself as another M0-D deletion."""

    matrix_path = tmp_path / "matrix.csv"

    def transform(row: dict[str, str]) -> dict[str, str]:
        if row["template_path"] == TARGET:
            row["status"] = "deleted"
            row["wave"] = "M0-D"
        return row

    matrix_path.write_bytes(_matrix_bytes(transform=transform))
    result = cleanup_guard.evaluate_cleanup_guard(
        matrix_path=matrix_path,
        catalog_path=CATALOG_PATH,
        evidence_path=EVIDENCE_PATH,
        as_of=date(2026, 8, 13),
    )

    assert result.allowed is False
    assert result.new_deleted_paths == (TARGET,)
    assert "require A/B M5-B lifecycle" in result.detail


def test_new_m5_b_deletion_requires_final_candidate_authorization(tmp_path: Path) -> None:
    """Old unbound evidence cannot authorize a post-deletion source snapshot."""

    matrix_path = tmp_path / "matrix.csv"

    def transform(row: dict[str, str]) -> dict[str, str]:
        if row["template_path"] == TARGET:
            row["status"] = "deleted"
            row["wave"] = "M5-B-W1"
        return row

    matrix_path.write_bytes(_matrix_bytes(transform=transform))
    result = cleanup_guard.evaluate_cleanup_guard(
        matrix_path=matrix_path,
        catalog_path=CATALOG_PATH,
        evidence_path=EVIDENCE_PATH,
        as_of=date(2026, 8, 13),
        repository_root=tmp_path,
    )

    assert result.allowed is False
    assert result.new_deleted_paths == (TARGET,)
    assert "final cutover authorization is missing or invalid" in result.detail


def test_authorized_post_deletion_candidate_and_wave_are_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cleanup wave can follow immutable final approval without a SHA loop."""

    fixture = _build_authorized_fixture(tmp_path, monkeypatch)

    result = _evaluate(fixture)

    assert result.allowed is True
    assert result.new_deleted_paths == (TARGET,)
    assert "final_authorization=true" in result.detail
    assert "current_snapshot=true" in result.detail


def test_tampered_final_approval_cannot_authorize_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard verifies the external approval, not a mutable ALLOW flag."""

    fixture = _build_authorized_fixture(tmp_path, monkeypatch)
    fixture.evidence["approvals"]["owner"]["name"] = "forged-owner"
    _write(fixture.evidence_path, _json_bytes(fixture.evidence))

    result = _evaluate(fixture)

    assert result.allowed is False
    assert "final cutover authorization is missing or invalid" in result.detail


def test_cleanup_wave_must_cover_exact_matrix_deletion_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An approved candidate cannot be stretched to an undeclared deletion."""

    fixture = _build_authorized_fixture(tmp_path, monkeypatch)
    fixture.evidence["cleanup"]["waves"][0]["deleted_paths"] = []
    _write(fixture.evidence_path, _json_bytes(fixture.evidence))

    result = _evaluate(fixture)

    assert result.allowed is False
    assert "wave paths do not match matrix" in result.detail


def test_cleanup_wave_cannot_self_assert_passed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller-authored passed flags are outside the exact wave evidence schema."""

    fixture = _build_authorized_fixture(tmp_path, monkeypatch)
    fixture.evidence["cleanup"]["waves"][0]["passed"] = True
    _write(fixture.evidence_path, _json_bytes(fixture.evidence))

    result = _evaluate(fixture)

    assert result.allowed is False
    assert "wave schema or authorization binding is invalid" in result.detail


def test_cleanup_wave_rollback_manifest_is_recomputed_from_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid digest cannot conceal a route rollback mapping that differs from the matrix."""

    fixture = _build_authorized_fixture(tmp_path, monkeypatch)
    record = fixture.evidence["cleanup"]["waves"][0]
    manifest_path = fixture.repository_root / record["rollback_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["route_rollback_commits"][TARGET] = "c" * 40
    manifest_bytes = _json_bytes(manifest)
    _write(manifest_path, manifest_bytes)
    record["rollback_manifest_sha256"] = _digest(manifest_bytes)
    _write(fixture.evidence_path, _json_bytes(fixture.evidence))

    result = _evaluate(fixture)

    assert result.allowed is False
    assert "rollback manifest is invalid" in result.detail


def test_cleanup_wave_recomputes_ten_route_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The matrix-derived route count, not a wave summary, enforces the <=10 limit."""

    fixture = _build_authorized_fixture(tmp_path, monkeypatch)
    paths = tuple(f"core/templates/example/route-{index}.html" for index in range(11))
    rows_by_path = {
        path: {
            "template_path": path,
            "template_role": "route_page",
            "destination_class": "A",
            "status": "deleted",
            "wave": "M5-B-W1",
            "rollback_commit": BASE_COMMIT,
        }
        for path in paths
    }
    authorization = cleanup_guard.FinalAuthorization(
        binding=fixture.evidence["candidate"]["binding"],
        approved_at=date(2026, 8, 3),
        artifact_digests=(),
    )

    ready, detail = cleanup_guard._cleanup_waves_are_ready(
        {"cleanup": {"waves": []}},
        rows_by_path=rows_by_path,
        new_deleted_paths=paths,
        authorization=authorization,
        matrix_path=fixture.matrix_path,
        catalog_path=fixture.catalog_path,
        graph_path=fixture.graph_path,
        runtime_manifest_path=fixture.runtime_manifest_path,
        as_of=date(2026, 8, 13),
        evidence_root=fixture.repository_root,
        repository_root=fixture.repository_root,
    )

    assert ready is False
    assert "exceeds 10 pages" in detail


@pytest.mark.parametrize(
    ("mutation", "detail"),
    [
        (
            lambda ledger: ledger.__setitem__("observed_until", "2026-08-05T23:59:59+08:00"),
            "observation ledger is invalid or incomplete",
        ),
        (
            lambda ledger: ledger["scheduled_cycles"].clear(),
            "observation ledger is invalid or incomplete",
        ),
        (
            lambda ledger: ledger["defects"].__setitem__("new_p1", 1),
            "observation ledger is invalid or incomplete",
        ),
        (
            lambda ledger: ledger["error_metrics"][0].__setitem__("candidate_errors", 2),
            "observation ledger is invalid or incomplete",
        ),
    ],
)
def test_cleanup_wave_observation_is_recomputed_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Callable[[dict[str, Any]], None],
    detail: str,
) -> None:
    """Duration, scheduled cycle, defects, and error regression are machine gates."""

    fixture = _build_authorized_fixture(tmp_path, monkeypatch)
    record = fixture.evidence["cleanup"]["waves"][0]
    ledger_path = fixture.repository_root / record["observation_ledger"]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    mutation(ledger)
    ledger_bytes = _json_bytes(ledger)
    _write(ledger_path, ledger_bytes)
    record["observation_ledger_sha256"] = _digest(ledger_bytes)
    _write(fixture.evidence_path, _json_bytes(fixture.evidence))

    result = _evaluate(fixture)

    assert result.allowed is False
    assert detail in result.detail


def test_cleanup_wave_candidate_must_contain_final_authorization_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deletion commit that predates approval cannot reuse later attestations."""

    fixture = _build_authorized_fixture(tmp_path, monkeypatch)
    owner_path = fixture.repository_root / "evidence/owner.json"
    relative = owner_path.relative_to(fixture.repository_root).as_posix()
    fixture.blobs.pop((CLEANUP_COMMIT, relative))

    result = _evaluate(fixture)

    assert result.allowed is False
    assert "predates final authorization" in result.detail


def test_cleanup_wave_requires_a_candidate_bound_to_current_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A historical wave proof cannot cover later unbound matrix drift."""

    fixture = _build_authorized_fixture(tmp_path, monkeypatch)
    matrix_text = fixture.matrix_path.read_text(encoding="utf-8")
    fixture.matrix_path.write_text(matrix_text + "\n", encoding="utf-8")
    current_matrix = cleanup_guard.normalized_source_bytes(fixture.matrix_path)
    _write(fixture.catalog_path, _catalog(current_matrix))

    result = _evaluate(fixture)

    assert result.allowed is False
    assert "no cleanup wave is bound to the current post-deletion snapshot" in result.detail
