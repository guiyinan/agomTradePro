"""Offline tests for collection of official candidate regression evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import types
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

import pytest

TEST_PATH = Path(__file__).resolve()
PROPOSAL_ROOT = TEST_PATH.parents[2]
COLLECTOR_SCRIPT = PROPOSAL_ROOT / "scripts/collect_release_regression_evidence.py"
SHARED_VALIDATOR = PROPOSAL_ROOT / "scripts/validate_release_rehearsal.py"
CANDIDATE_SHA = "a" * 40
UNIVERSE_SHA = "b" * 64
REPOSITORY = "agomtradepro/agomTradePro"
RUN_ID = 36069605796
IDENTITIES = [
    {
        "role": "quote",
        "provider_id": 11,
        "source": "test-provider",
        "version": "v1",
        "endpoint_id": "quotes",
    },
    {
        "role": "valuation",
        "provider_id": 12,
        "source": "test-provider",
        "version": "v1",
        "endpoint_id": "valuation",
    },
]


@dataclass(frozen=True)
class CollectorSandbox:
    """Isolated package copy and loaded modules for one test."""

    collector: types.ModuleType
    validator: types.ModuleType
    package_directory: Path
    sandbox_directory: Path


@dataclass
class GithubStub:
    """Mutable offline GitHub response contract used by collector tests."""

    validator: types.ModuleType
    candidate_sha: str = CANDIDATE_SHA
    run_id: int = RUN_ID
    conclusion: str = "success"
    run_head_sha: str = CANDIDATE_SHA
    run_id_response: int = RUN_ID
    run_updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    artifact_created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    artifact_expires_at: str = field(
        default_factory=lambda: (datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    junit_timestamp: datetime | None = None
    omit_required_test: str | None = None
    skip_required_test: str | None = None
    fail_digest: bool = False
    expired: bool = False
    transport_exception: str | None = None
    listings_seen: int = 0
    archive_reads: int = 0
    json_calls: list[str] | None = None
    archive: bytes = b""
    current_archive: bytes = b""
    junit_files: dict[str, bytes] = field(default_factory=dict)
    drift_listing: bool = False

    def __post_init__(self) -> None:
        self.json_calls = []
        timestamp = self.junit_timestamp or datetime.now(UTC)
        required = list(self.validator.REQUIRED_POSTGRESQL_TESTS)
        if self.omit_required_test is not None:
            required.remove(self.omit_required_test)
        backfill = [
            identity for identity in required if "test_core_data_backfill_control_plane" in identity
        ]
        publication = [identity for identity in required if identity not in backfill]
        self.junit_files = {
            "publication-postgres.xml": _junit_bytes(
                publication, timestamp, self.skip_required_test
            ),
            "backfill-control-plane-postgres.xml": _junit_bytes(
                backfill, timestamp, self.skip_required_test
            ),
        }
        self.archive = _zip_bytes(self.junit_files)
        self.current_archive = self.archive

    def load_json(self, url: str) -> dict[str, Any]:
        assert self.json_calls is not None
        self.json_calls.append(url)
        if self.transport_exception is not None:
            raise RuntimeError(self.transport_exception)
        if "/artifacts" in url:
            self.listings_seen += 1
            archive = self.archive
            if self.drift_listing and self.listings_seen >= 2:
                archive = _zip_bytes(
                    {
                        **self.junit_files,
                        "unrelated.txt": b"metadata changed while JUnit bytes remained the same",
                    }
                )
            self.current_archive = archive
            digest = hashlib.sha256(archive).hexdigest()
            if self.fail_digest:
                digest = "0" * 64
            return {
                "artifacts": [
                    {
                        "id": 777,
                        "name": self.validator.REQUIRED_GITHUB_ARTIFACT,
                        "expired": self.expired,
                        "digest": f"sha256:{digest}",
                        "size_in_bytes": len(archive),
                        "created_at": self.artifact_created_at,
                        "expires_at": self.artifact_expires_at,
                        "archive_download_url": "https://api.github.com/artifact.zip",
                        "workflow_run": {"id": self.run_id, "head_sha": self.candidate_sha},
                    }
                ]
            }
        return {
            "id": self.run_id_response,
            "name": self.validator.REQUIRED_GITHUB_WORKFLOW,
            "status": "completed",
            "conclusion": self.conclusion,
            "head_sha": self.run_head_sha,
            "updated_at": self.run_updated_at,
            "repository": {"full_name": REPOSITORY},
        }

    def request_bytes(self, url: str, *, require_token: bool, limit: int) -> bytes:
        assert require_token is True
        assert limit == 10_485_760
        assert url == "https://api.github.com/artifact.zip"
        self.archive_reads += 1
        return self.current_archive


def _junit_bytes(cases: list[str], timestamp: datetime, skipped_case: str | None = None) -> bytes:
    suites = ElementTree.Element("testsuites")
    root = ElementTree.SubElement(
        suites, "testsuite", {"name": "offline", "timestamp": timestamp.isoformat()}
    )
    for identity in cases:
        classname, name = identity.split("::", 1)
        case = ElementTree.SubElement(root, "testcase", {"classname": classname, "name": name})
        if identity == skipped_case:
            ElementTree.SubElement(case, "skipped")
    return ElementTree.tostring(suites, encoding="utf-8", xml_declaration=True)


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    memory = BytesIO()
    with zipfile.ZipFile(memory, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return memory.getvalue()


@pytest.fixture
def collector_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CollectorSandbox:
    """Copy the proposal and current validator into a fresh isolated package."""
    package_directory = tmp_path / "s6_regression_package"
    package_directory.mkdir()
    collector_path = package_directory / "collect_release_regression_evidence.py"
    validator_path = package_directory / "validate_release_rehearsal.py"
    shutil.copy2(COLLECTOR_SCRIPT, collector_path)
    shutil.copy2(SHARED_VALIDATOR, validator_path)
    package_name = f"s6_regression_{uuid4().hex}"
    package = types.ModuleType(package_name)
    package.__path__ = [str(package_directory)]
    package.__package__ = package_name
    monkeypatch.setitem(sys.modules, package_name, package)

    validator_name = f"{package_name}.validate_release_rehearsal"
    validator_spec = importlib.util.spec_from_file_location(validator_name, validator_path)
    assert validator_spec is not None and validator_spec.loader is not None
    validator_module = importlib.util.module_from_spec(validator_spec)
    monkeypatch.setitem(sys.modules, validator_name, validator_module)
    validator_spec.loader.exec_module(validator_module)

    collector_name = f"{package_name}.collect_release_regression_evidence"
    collector_spec = importlib.util.spec_from_file_location(collector_name, collector_path)
    assert collector_spec is not None and collector_spec.loader is not None
    collector_module = importlib.util.module_from_spec(collector_spec)
    monkeypatch.setitem(sys.modules, collector_name, collector_module)
    collector_spec.loader.exec_module(collector_module)
    return CollectorSandbox(
        collector=collector_module,
        validator=validator_module,
        package_directory=package_directory,
        sandbox_directory=tmp_path,
    )


def _arguments(tmp_path: Path, output_dir: Path) -> list[str]:
    identities_path = tmp_path / "provider-identities.json"
    identities_path.write_text(json.dumps(IDENTITIES), encoding="utf-8")
    return [
        "--candidate-sha",
        CANDIDATE_SHA,
        "--target-date",
        "2026-09-25",
        "--universe-sha256",
        UNIVERSE_SHA,
        "--provider-identities-json",
        str(identities_path),
        "--github-repository",
        REPOSITORY,
        "--github-run-id",
        str(RUN_ID),
        "--max-age-hours",
        "24",
        "--output-dir",
        str(output_dir),
    ]


def _install_github_stub(sandbox: CollectorSandbox, stub: GithubStub) -> None:
    sandbox.validator._load_github_json = stub.load_json
    sandbox.validator._github_request_bytes = stub.request_bytes


def _assert_blocked(output_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report_path = output_dir / "candidate-regression-evidence.json"
    assert not report_path.exists()
    blocked = json.loads((output_dir / "collection-blocked.json").read_text(encoding="utf-8"))
    assert blocked["outcome"] == "blocked"
    assert blocked["release_ready"] is False
    captured = capsys.readouterr()
    assert "Authorization" not in captured.err
    assert "secret-rehearsal-test" not in captured.err
    assert "secret-rehearsal-test" not in (output_dir / "collection-blocked.json").read_text(
        encoding="utf-8"
    )


def test_collects_validated_candidate_only_report_and_exact_junit_bytes(
    collector_sandbox: CollectorSandbox, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = GithubStub(collector_sandbox.validator)
    _install_github_stub(collector_sandbox, stub)
    output_dir = tmp_path / "fresh-output"

    exit_code = collector_sandbox.collector.main(_arguments(tmp_path, output_dir))

    assert exit_code == 0
    report = json.loads(
        (output_dir / "candidate-regression-evidence.json").read_text(encoding="utf-8")
    )
    assert report["kind"] == "candidate_regression_evidence"
    assert report["outcome"] == "success"
    assert report["release_ready"] is False
    assert set(report["remaining_release_gates"]) == {
        "real_response_unit_replay",
        "full_universe_capacity",
        "isolated_write_rehearsal",
    }
    assert len(report["required_tests"]) == 23
    assert report["github_source"]["source_snapshot_stable"] is True
    assert report["github_source"]["run"]["head_sha"] == CANDIDATE_SHA
    assert report["github_source"]["artifact"]["id"] == 777
    assert report["github_source"]["artifact"]["digest"].startswith("sha256:")
    assert "archive_download_url" not in json.dumps(report)
    assert "success" in capsys.readouterr().out
    assert stub.archive_reads == 2
    assert len([url for url in stub.json_calls or [] if "/artifacts" not in url]) == 3
    assert len([url for url in stub.json_calls or [] if "/artifacts" in url]) == 4


@pytest.mark.parametrize(
    ("fault", "expected_code"),
    [
        ("wrong_sha", "REHEARSAL_GITHUB_RUN_NOT_APPROVED"),
        ("wrong_run", "REHEARSAL_GITHUB_RUN_NOT_APPROVED"),
        ("failed", "REHEARSAL_GITHUB_RUN_NOT_APPROVED"),
        ("expired", "REHEARSAL_GITHUB_ARTIFACT_MISSING"),
        ("digest", "REHEARSAL_GITHUB_ARTIFACT_DIGEST_MISMATCH"),
        ("missing_test", "REHEARSAL_REQUIRED_TEST_MISSING"),
        ("skipped", "REHEARSAL_JUNIT_NOT_GREEN"),
        ("stale_time", "REHEARSAL_JUNIT_STALE"),
        ("future_time", "REHEARSAL_JUNIT_STALE"),
        ("drift", "REHEARSAL_GITHUB_EVIDENCE_DRIFT"),
        ("exception", "RELEASE_REGRESSION_COLLECTION_FAILED"),
    ],
)
def test_rejects_invalid_or_drifting_official_evidence(
    fault: str,
    expected_code: str,
    collector_sandbox: CollectorSandbox,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub = GithubStub(collector_sandbox.validator)
    if fault == "wrong_sha":
        stub.run_head_sha = "c" * 40
    elif fault == "wrong_run":
        stub.run_id_response = RUN_ID + 1
    elif fault == "failed":
        stub.conclusion = "failure"
    elif fault == "expired":
        stub.expired = True
    elif fault == "digest":
        stub.fail_digest = True
    elif fault == "missing_test":
        stub.omit_required_test = collector_sandbox.validator.REQUIRED_POSTGRESQL_TESTS[-1]
        stub.__post_init__()
    elif fault == "skipped":
        stub.skip_required_test = collector_sandbox.validator.REQUIRED_POSTGRESQL_TESTS[0]
        stub.__post_init__()
    elif fault == "stale_time":
        stub.junit_timestamp = datetime.now(UTC) - timedelta(days=2)
        stub.__post_init__()
    elif fault == "future_time":
        stub.junit_timestamp = datetime.now(UTC) + timedelta(days=2)
        stub.__post_init__()
    elif fault == "drift":
        stub.drift_listing = True
    elif fault == "exception":
        stub.transport_exception = "Authorization: Bearer secret-rehearsal-test"
    _install_github_stub(collector_sandbox, stub)
    output_dir = tmp_path / f"blocked-{fault}"

    exit_code = collector_sandbox.collector.main(_arguments(tmp_path, output_dir))

    assert exit_code == 2
    _assert_blocked(output_dir, capsys)
    blocked = json.loads((output_dir / "collection-blocked.json").read_text(encoding="utf-8"))
    assert blocked["error_code"] == expected_code


def test_existing_output_directory_is_rejected_without_network_reads(
    collector_sandbox: CollectorSandbox, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub = GithubStub(collector_sandbox.validator)
    _install_github_stub(collector_sandbox, stub)
    output_dir = tmp_path / "already-there"
    output_dir.mkdir()
    retained = output_dir / "operator-file.txt"
    retained.write_text("keep", encoding="utf-8")

    exit_code = collector_sandbox.collector.main(_arguments(tmp_path, output_dir))

    assert exit_code == 2
    assert retained.read_text(encoding="utf-8") == "keep"
    assert stub.json_calls == []
    assert stub.archive_reads == 0
    assert not (output_dir / "candidate-regression-evidence.json").exists()
    assert "REHEARSAL_OUTPUT_DIRECTORY_EXISTS" in capsys.readouterr().err


def test_cli_help_imports_sibling_validator_from_an_unrelated_working_directory(
    collector_sandbox: CollectorSandbox,
) -> None:
    script = collector_sandbox.package_directory / "collect_release_regression_evidence.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=collector_sandbox.sandbox_directory,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
    assert "--github-run-id" in result.stdout
    assert "--max-age-hours" in result.stdout
