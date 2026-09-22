"""Contracts for the DATA-02 successor read-only checkpoint recorder."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.data_center.application.data02_successor_checkpoint import (
    Data02SuccessorCandidate,
    Data02SuccessorCheckpointError,
    Data02SuccessorUniverse,
    data02_successor_checkpoint_artifact_sha256,
    parse_data02_successor_checkpoint,
    serialize_data02_successor_checkpoint,
)
from scripts.record_data02_successor_checkpoint import record_data02_successor_checkpoint

CHECKPOINT_PATH = Path(
    "docs/deployment/data02-successor-production-readonly-checkpoint-2026-09-02-aa7127ff.json"
)
AS_OF = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
EXPECTED_CANDIDATE = Data02SuccessorCandidate(
    source_commit="aa7127ff4d9f71555b0d0486314da5518bd2ac20",
    release_id="20260901232812",
    image_id="sha256:55d2b1d8dd7078acc42aef72f0fa33e57035d30e5c2727b574dfd43aafd9519c",
)
UNIVERSE_HASH = "4b9bfd44941336ed45d302d4c0f1cb53b7bfce025cff377ffa14a5ae8f792c22"
EXPECTED_UNIVERSE = Data02SuccessorUniverse(
    denominator=5_565,
    schema="active-a-share-universe.v1",
    universe_hash=UNIVERSE_HASH,
)


def _payload(
    *,
    publication_id_prefix: str | None = "test-pub",
    denominator: int = 5_565,
    universe_hash: str = UNIVERSE_HASH,
) -> dict[str, object]:
    """Upgrade the historical snapshot into a synthetic v2 contract shape."""

    payload = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    payload["schema"] = "data02-successor-production-readonly-checkpoint.v2"
    payload["universe"] = {
        "denominator": denominator,
        "schema": "active-a-share-universe.v1",
        "universe_hash": universe_hash,
    }
    repair = payload["fact_repair_dry_run"]
    assert isinstance(repair, dict)
    repair["asset_count"] = denominator
    prices = repair["completed_session_prices"]
    assert isinstance(prices, dict)
    prices["requested_asset_count"] = denominator
    prices["invalid_asset_count"] = denominator

    if publication_id_prefix is None:
        return payload
    publication = payload["publication_rebuild_dry_run"]
    assert isinstance(publication, dict)
    publication["asset_count"] = denominator
    datasets = publication["datasets"]
    assert isinstance(datasets, dict)
    total_members = 0
    for index, dataset_key in enumerate(sorted(datasets)):
        dataset = datasets[dataset_key]
        assert isinstance(dataset, dict)
        if dataset["ready"]:
            dataset["covered_asset_count"] = denominator
            dataset["missing_asset_count"] = 0
            dataset["covered_asset_codes_hash"] = universe_hash
            dataset["member_count"] = denominator
        else:
            covered = int(dataset["covered_asset_count"])
            dataset["missing_asset_count"] = denominator - covered
            dataset["covered_asset_codes_hash"] = "e" * 64
            dataset["member_count"] = 19_197
        dataset["publication_id"] = f"{publication_id_prefix}-{index}"
        dataset["publication_hash"] = f"{index + 1:064x}"
        total_members += int(dataset["member_count"])
    publication["member_count"] = total_members
    return payload


def _bytes(payload: dict[str, object]) -> bytes:
    """Encode one deterministic JSON checkpoint envelope."""

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _understate_quote_member_count(payload: dict[str, object]) -> None:
    """Keep the top sum self-consistent while understating one dataset's members."""

    publication = payload["publication_rebuild_dry_run"]
    dataset = publication["datasets"]["equity.quote.snapshot"]
    dataset["member_count"] = int(dataset["covered_asset_count"]) - 1
    publication["member_count"] = sum(
        int(item["member_count"]) for item in publication["datasets"].values()
    )


def test_checked_in_v1_checkpoint_fails_closed_without_exact_universe_scope() -> None:
    """The superseded 5,533 snapshot cannot pass the v2 scope contract."""

    with pytest.raises(Data02SuccessorCheckpointError, match="checkpoint keys changed"):
        parse_data02_successor_checkpoint(
            CHECKPOINT_PATH.read_bytes(),
            expected_candidate=EXPECTED_CANDIDATE,
            expected_universe=EXPECTED_UNIVERSE,
            as_of=AS_OF,
        )


def test_valid_successor_checkpoint_is_candidate_bound_and_never_ready() -> None:
    """A complete synthetic shape retains all blockers and remains non-enabling."""

    report = parse_data02_successor_checkpoint(
        _bytes(_payload()),
        expected_candidate=EXPECTED_CANDIDATE,
        expected_universe=EXPECTED_UNIVERSE,
        as_of=AS_OF,
    )
    decoded = json.loads(serialize_data02_successor_checkpoint(report))

    assert decoded["schema_version"] == "data02-successor-checkpoint-readonly.v2"
    assert decoded["candidate"]["source_commit"] == "aa7127ff4d9f71555b0d0486314da5518bd2ac20"
    assert decoded["universe"] == {
        "denominator": 5_565,
        "schema": "active-a-share-universe.v1",
        "universe_hash": UNIVERSE_HASH,
    }
    assert decoded["public_probe_window"]["decision_must_not_use_for_decision"] is True
    assert decoded["publication_rebuild_dry_run"]["dataset_count"] == 4
    assert all(
        "publication_id" in dataset and "publication_hash" in dataset
        for dataset in decoded["publication_rebuild_dry_run"]["datasets"].values()
    )
    assert decoded["gate"]["data02_execution_ready"] is False
    assert decoded["gate"]["data02_exit_gate_complete"] is False
    assert decoded["production_claim"] is False
    assert decoded["production_ready"] is False
    assert decoded["runtime_enablement"] == "not_authorized"


def test_current_denominator_is_bound_by_universe_hash_instead_of_stale_constant() -> None:
    """The current 5,565 scope passes only when every full dataset binds its hash."""

    report = parse_data02_successor_checkpoint(
        _bytes(_payload(denominator=5_565, universe_hash="b" * 64)),
        expected_candidate=EXPECTED_CANDIDATE,
        expected_universe=Data02SuccessorUniverse(
            denominator=5_565,
            schema="active-a-share-universe.v1",
            universe_hash="b" * 64,
        ),
        as_of=AS_OF,
    )
    decoded = json.loads(serialize_data02_successor_checkpoint(report))

    assert decoded["universe"]["denominator"] == 5_565
    assert decoded["fact_repair_dry_run"]["asset_count"] == 5_565
    assert decoded["publication_rebuild_dry_run"]["asset_count"] == 5_565
    for dataset in decoded["publication_rebuild_dry_run"]["datasets"].values():
        if dataset["ready"]:
            assert dataset["covered_asset_codes_hash"] == "b" * 64


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_commit", "f" * 40),
        ("release_id", "20260901232813"),
        ("image_id", f"sha256:{'f' * 64}"),
    ],
)
def test_candidate_substitution_fails_against_caller_pinned_identity(
    field: str,
    replacement: str,
) -> None:
    """No syntactically valid candidate coordinate can replace the pinned identity."""

    payload = _payload()
    payload["candidate"][field] = replacement

    with pytest.raises(Data02SuccessorCheckpointError, match="expected candidate"):
        parse_data02_successor_checkpoint(
            _bytes(payload),
            expected_candidate=EXPECTED_CANDIDATE,
            expected_universe=EXPECTED_UNIVERSE,
            as_of=AS_OF,
        )


@pytest.mark.parametrize(
    ("denominator", "universe_hash"),
    [
        (5_533, UNIVERSE_HASH),
        (5_564, UNIVERSE_HASH),
        (5_566, UNIVERSE_HASH),
        (5_565, "f" * 64),
    ],
)
def test_universe_substitution_fails_against_caller_pinned_scope(
    denominator: int,
    universe_hash: str,
) -> None:
    """Internally consistent alternate scope cannot replace the canonical universe."""

    with pytest.raises(Data02SuccessorCheckpointError, match="expected universe"):
        parse_data02_successor_checkpoint(
            _bytes(_payload(denominator=denominator, universe_hash=universe_hash)),
            expected_candidate=EXPECTED_CANDIDATE,
            expected_universe=EXPECTED_UNIVERSE,
            as_of=AS_OF,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["fact_repair_dry_run"].__setitem__("asset_count", 5_532),
            "universe denominator",
        ),
        (
            lambda payload: payload["publication_rebuild_dry_run"]["datasets"][
                "equity.quote.snapshot"
            ].__setitem__("covered_asset_codes_hash", "c" * 64),
            "full coverage must match universe hash",
        ),
        (
            lambda payload: payload["publication_rebuild_dry_run"].__setitem__(
                "member_count",
                int(payload["publication_rebuild_dry_run"]["member_count"]) + 1,
            ),
            "member_count must equal dataset sum",
        ),
        (
            _understate_quote_member_count,
            "member_count cannot be smaller than covered assets",
        ),
    ],
)
def test_universe_and_publication_scope_substitution_fails_closed(mutate, message: str) -> None:
    """Counts alone cannot substitute the canonical universe or publication members."""

    payload = _payload()
    mutate(payload)

    with pytest.raises(Data02SuccessorCheckpointError, match=message):
        parse_data02_successor_checkpoint(
            _bytes(payload),
            expected_candidate=EXPECTED_CANDIDATE,
            expected_universe=EXPECTED_UNIVERSE,
            as_of=AS_OF,
        )


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda payload: payload["candidate"].__setitem__("candidate_drift", True), "drift"),
        (lambda payload: payload["fact_repair_dry_run"].__setitem__("exit_code", 1), "exit_code"),
        (
            lambda payload: payload["side_effects"].__setitem__("production_database_write", True),
            "side effects",
        ),
        (
            lambda payload: payload["connection_stability"].__setitem__("client_backend_growth", 1),
            "growth",
        ),
        (
            lambda payload: payload["public_probe_window"].__setitem__(
                "decision_ready_503_count", 2
            ),
            "decision probe",
        ),
    ],
)
def test_inconsistent_successor_checkpoint_fails_closed(mutate, message: str) -> None:
    """Candidate drift, writes, inconsistent samples and failed decision probes cannot pass."""

    payload = _payload()
    mutate(payload)
    with pytest.raises(Data02SuccessorCheckpointError, match=message):
        parse_data02_successor_checkpoint(
            _bytes(payload),
            expected_candidate=EXPECTED_CANDIDATE,
            expected_universe=EXPECTED_UNIVERSE,
            as_of=AS_OF,
        )


def test_publication_identity_collision_fails_closed() -> None:
    """Each core dataset must have a distinct immutable publication identity."""

    payload = _payload()
    datasets = payload["publication_rebuild_dry_run"]["datasets"]
    assert isinstance(datasets, dict)
    first_key, second_key = sorted(datasets)[:2]
    datasets[second_key]["publication_id"] = datasets[first_key]["publication_id"]
    with pytest.raises(Data02SuccessorCheckpointError, match="identities must be unique"):
        parse_data02_successor_checkpoint(
            _bytes(payload),
            expected_candidate=EXPECTED_CANDIDATE,
            expected_universe=EXPECTED_UNIVERSE,
            as_of=AS_OF,
        )


def test_recorder_is_deterministic_append_only_and_dry_run_by_default(tmp_path: Path) -> None:
    """The explicit writer is idempotent and never writes on a dry run."""

    input_path = tmp_path / "checkpoint.json"
    input_path.write_bytes(_bytes(_payload()))
    dry = record_data02_successor_checkpoint(
        input_path,
        expected_candidate=EXPECTED_CANDIDATE,
        expected_universe=EXPECTED_UNIVERSE,
    )
    assert dry.written is False
    assert dry.publication_identity_count == 4
    assert not (tmp_path / "data02-successor-checkpoint").exists()

    root = tmp_path / "evidence"
    first = record_data02_successor_checkpoint(
        input_path,
        expected_candidate=EXPECTED_CANDIDATE,
        expected_universe=EXPECTED_UNIVERSE,
        output_root=root,
        write=True,
    )
    second = record_data02_successor_checkpoint(
        input_path,
        expected_candidate=EXPECTED_CANDIDATE,
        expected_universe=EXPECTED_UNIVERSE,
        output_root=root,
        write=True,
    )
    assert first.written is True
    assert second.written is False
    assert first.path == second.path
    assert first.path is not None
    assert first.path.with_suffix(".sha256").read_text(encoding="ascii") == (
        f"{first.artifact_sha256}\n"
    )
    assert first.artifact_sha256 == data02_successor_checkpoint_artifact_sha256(
        first.path.read_bytes()
    )


def test_recorder_cli_runs_directly_from_repository_root() -> None:
    """The server-side recorder help is usable without installing a local package."""

    result = subprocess.run(
        [sys.executable, "scripts/record_data02_successor_checkpoint.py", "--help"],
        cwd=Path(__file__).resolve().parents[3],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "checkpoint JSON path" in result.stdout
    assert "--expected-universe-denominator" in result.stdout
    assert "--expected-universe-hash" in result.stdout


def test_recorder_cli_requires_independently_pinned_universe() -> None:
    """The CLI cannot derive its trusted universe identity from checkpoint input."""

    result = subprocess.run(
        [
            sys.executable,
            "scripts/record_data02_successor_checkpoint.py",
            "--input",
            str(CHECKPOINT_PATH),
            "--expected-source-commit",
            EXPECTED_CANDIDATE.source_commit,
            "--expected-release-id",
            EXPECTED_CANDIDATE.release_id,
            "--expected-image-id",
            EXPECTED_CANDIDATE.image_id,
        ],
        cwd=Path(__file__).resolve().parents[3],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--expected-universe-denominator" in result.stderr
    assert "--expected-universe-hash" in result.stderr


def test_recorder_cli_reports_invalid_checkpoint_as_stable_blocked_json() -> None:
    """Expected missing publication identities do not leak a traceback to operators."""

    result = subprocess.run(
        [
            sys.executable,
            "scripts/record_data02_successor_checkpoint.py",
            "--input",
            str(CHECKPOINT_PATH),
            "--expected-source-commit",
            EXPECTED_CANDIDATE.source_commit,
            "--expected-release-id",
            EXPECTED_CANDIDATE.release_id,
            "--expected-image-id",
            EXPECTED_CANDIDATE.image_id,
            "--expected-universe-denominator",
            str(EXPECTED_UNIVERSE.denominator),
            "--expected-universe-hash",
            EXPECTED_UNIVERSE.universe_hash,
        ],
        cwd=Path(__file__).resolve().parents[3],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload == {
        "error_type": "Data02SuccessorCheckpointError",
        "message": "checkpoint keys changed (missing=['universe'], extra=[])",
        "outcome": "blocked",
        "production_claim": False,
        "production_ready": False,
        "reason_code": "invalid_successor_checkpoint",
        "runtime_enablement": "not_authorized",
        "written": False,
    }
    assert result.stderr == ""


def test_recorder_modules_have_no_network_or_orm_imports() -> None:
    """The parser and CLI cannot silently become a production client."""

    for path in (
        Path("apps/data_center/application/data02_successor_checkpoint.py"),
        Path("scripts/record_data02_successor_checkpoint.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert imported.isdisjoint({"django", "psycopg", "paramiko", "requests", "redis"})
        assert ".objects" not in path.read_text(encoding="utf-8")
