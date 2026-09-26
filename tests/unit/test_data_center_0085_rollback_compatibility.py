from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = REPOSITORY_ROOT / "scripts" / "verify_data_center_0085_rollback_compatibility.py"
COMPATIBILITY_SOURCES = (
    Path("apps/data_center/migrations/0085_published_market_fact_revisions.py"),
    Path("apps/data_center/infrastructure/models.py"),
    Path("apps/data_center/infrastructure/fact_and_operational_models.py"),
    Path("apps/data_center/infrastructure/published_fact_versions.py"),
    Path("apps/data_center/infrastructure/financial_fact_write_guard.py"),
)
RELEASE_TAG = "20260925000000"
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
IMAGE_ID = "sha256:" + "a" * 64
IMAGE_TAG = f"agomtradepro-web:{RELEASE_TAG}"
DATABASE_STATE = "applied"

_SPEC = importlib.util.spec_from_file_location("rollback_0085_checker", CHECKER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
CHECKER: ModuleType = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = CHECKER
_SPEC.loader.exec_module(CHECKER)


def _make_previous_release(tmp_path: Path) -> Path:
    """Build a previous release fixture with immutable manifest and image config."""
    previous_release = tmp_path / f"source-{RELEASE_TAG}"
    for relative_path in COMPATIBILITY_SOURCES:
        target = previous_release / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPOSITORY_ROOT / relative_path).read_bytes())

    manifest = {
        "version": 1,
        "release_tag": RELEASE_TAG,
        "source_commit": SOURCE_COMMIT,
        "image_tag": IMAGE_TAG,
        "image_id": IMAGE_ID,
        "build_started_at": "2026-09-25T00:00:00Z",
        "build_finished_at": "2026-09-25T00:01:00Z",
        "source_mode": "source-upload",
    }
    manifest_path = previous_release / ".agom-release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o444)
    env_path = previous_release / "deploy/.env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(f"WEB_IMAGE={IMAGE_TAG}\n", encoding="utf-8")
    return previous_release


def _install_fake_docker(
    monkeypatch: pytest.MonkeyPatch,
    previous_release: Path,
    *,
    image_id: str = IMAGE_ID,
    image_revision: str = SOURCE_COMMIT,
    image_source_digest: str | None = None,
) -> None:
    """Supply deterministic Docker inspection results without starting containers."""
    if image_source_digest is None:
        try:
            image_source_digest = CHECKER.compatibility_source_digest(previous_release)
        except OSError:
            image_source_digest = "0" * 64

    def fake_run(
        args: tuple[str, ...] | list[str],
        *,
        capture_output: bool,
        check: bool,
        text: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        command = tuple(str(item) for item in args)
        if command[:3] == ("docker", "image", "inspect") and command[3] == IMAGE_TAG:
            output = image_id
        elif command[:3] == ("docker", "image", "inspect") and command[3] == IMAGE_ID:
            output = image_revision
        elif command[:2] == ("docker", "run"):
            output = image_source_digest
        else:
            raise AssertionError(f"unexpected external command: {command[:4]}")
        return subprocess.CompletedProcess(command, 0, output + "\n", "")

    monkeypatch.setattr(CHECKER.subprocess, "run", fake_run)


def _run_checker(
    previous_release: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    database_state: str = DATABASE_STATE,
) -> tuple[int, str, str]:
    """Run the production checker entry point with only Docker reads mocked."""
    _install_fake_docker(monkeypatch, previous_release)
    result = CHECKER.main(
        [
            "--previous-release",
            str(previous_release),
            "--database-migration-0085",
            database_state,
        ]
    )
    captured = capsys.readouterr()
    return result, captured.out, captured.err


def test_manifest_source_env_image_and_applied_schema_pass_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)

    return_code, stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 0, stderr
    assert "PREVIOUS_RELEASE_0085_COMPATIBLE" in stdout
    assert "database_migration=applied" in stdout


def test_non_applied_database_keeps_identity_gate_without_writer_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)
    writer = previous_release / "apps/data_center/infrastructure/published_fact_versions.py"
    source = writer.read_text(encoding="utf-8")
    old_revision_behavior = "incoming.revision_number = previous.revision_number + 1"
    assert old_revision_behavior in source
    writer.write_text(
        source.replace(old_revision_behavior, "incoming.revision_number = 1"), encoding="utf-8"
    )

    return_code, stdout, stderr = _run_checker(
        previous_release,
        monkeypatch,
        capsys,
        database_state="not_applied",
    )

    assert return_code == 0, stderr
    assert "PREVIOUS_RELEASE_0085_COMPATIBLE" in stdout
    assert "database_migration=not_applied" in stdout


def test_non_applied_database_still_checks_previous_image_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)
    _install_fake_docker(monkeypatch, previous_release, image_id="sha256:" + "b" * 64)

    return_code = CHECKER.main(
        [
            "--previous-release",
            str(previous_release),
            "--database-migration-0085",
            "not_applied",
        ]
    )
    captured = capsys.readouterr()

    assert return_code == 42
    assert not captured.out
    assert "image ID does not match" in captured.err


def test_previous_release_manifest_must_be_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)
    manifest = previous_release / ".agom-release-manifest.json"
    manifest.chmod(0o644)

    return_code, stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 42
    assert not stdout
    assert "read-only 0444" in stderr


def test_previous_release_web_image_must_match_immutable_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)
    env_path = previous_release / "deploy/.env"
    env_path.write_text(f"WEB_IMAGE=agomtradepro-web:{'9' * 14}\n", encoding="utf-8")

    return_code, stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 42
    assert not stdout
    assert "WEB_IMAGE does not match" in stderr


@pytest.mark.parametrize(
    ("image_id", "image_revision", "image_source_digest", "expected_error"),
    (
        ("sha256:" + "b" * 64, SOURCE_COMMIT, None, "image ID does not match"),
        (IMAGE_ID, "f" * 40, None, "OCI revision does not match"),
        (IMAGE_ID, SOURCE_COMMIT, "0" * 64, "checked source does not match"),
    ),
)
def test_actual_docker_id_oci_revision_and_checked_source_are_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    image_id: str,
    image_revision: str,
    image_source_digest: str | None,
    expected_error: str,
) -> None:
    previous_release = _make_previous_release(tmp_path)
    _install_fake_docker(
        monkeypatch,
        previous_release,
        image_id=image_id,
        image_revision=image_revision,
        image_source_digest=image_source_digest,
    )

    result = CHECKER.verify_previous_release(previous_release, DATABASE_STATE)

    assert any(expected_error in error for error in result)


def test_missing_database_migration_state_fails_closed(tmp_path: Path) -> None:
    previous_release = _make_previous_release(tmp_path)

    result = CHECKER.verify_previous_release(previous_release, "unknown")

    assert "database data_center.0085 migration state is unknown" in result


def test_missing_previous_release_0085_migration_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)
    (previous_release / COMPATIBILITY_SOURCES[0]).unlink()

    return_code, _stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 42
    assert "ROLLBACK_SCHEMA_INCOMPATIBLE" in stderr
    assert "0085_published_market_fact_revisions.py" in stderr


def test_unapplied_0085_does_not_require_a_legacy_migration_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)
    (previous_release / COMPATIBILITY_SOURCES[0]).unlink()

    return_code, stdout, stderr = _run_checker(
        previous_release,
        monkeypatch,
        capsys,
        database_state="not_applied",
    )

    assert return_code == 0, stderr
    assert "database_migration=not_applied" in stdout


def test_financial_writer_without_successor_revision_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)
    writer = previous_release / "apps/data_center/infrastructure/financial_fact_write_guard.py"
    source = writer.read_text(encoding="utf-8")
    revision_increment = "row.revision_number += 1"
    assert revision_increment in source
    writer.write_text(
        source.replace(revision_increment, "row.revision_number = 1"), encoding="utf-8"
    )

    return_code, _stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 42
    assert "ROLLBACK_SCHEMA_INCOMPATIBLE" in stderr
    assert "financial_fact_write_guard.py" in stderr
    assert "successor revisions" in stderr


def test_migration_without_revision_key_for_any_fact_table_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)
    migration = previous_release / COMPATIBILITY_SOURCES[0]
    source = migration.read_text(encoding="utf-8")
    price_bar_key = '("asset_code", "bar_date", "freq", "adjustment", "source", "revision_number")'
    assert price_bar_key in source
    migration.write_text(
        source.replace(price_bar_key, '("asset_code", "bar_date", "freq", "adjustment", "source")'),
        encoding="utf-8",
    )

    return_code, _stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 42
    assert "ROLLBACK_SCHEMA_INCOMPATIBLE" in stderr
    assert "revision_number unique key for pricebarmodel" in stderr


def test_remote_deploy_reads_db_and_gates_before_all_mutations() -> None:
    source = (REPOSITORY_ROOT / "scripts/remote_build_deploy_vps.py").read_text(encoding="utf-8")
    previous_release_assignment = 'PREVIOUS_RELEASE="$(readlink -f "$TARGET_DIR/current"'
    migration_probe = "SELECT EXISTS (SELECT 1 FROM public.django_migrations"
    postgres_container_lookup = "docker ps --filter 'label=com.docker.compose.project=agomtradepro'"
    gate_call = 'python3 "$RELEASE_DIR/scripts/verify_data_center_0085_rollback_compatibility.py"'

    assert migration_probe in source
    assert '--database-migration-0085 "$DATABASE_MIGRATION_0085"' in source
    assert "ROLLBACK_SCHEMA_INCOMPATIBLE" in source
    assert source.index(previous_release_assignment) < source.index(migration_probe)
    assert source.index(postgres_container_lookup) < source.index(migration_probe)
    assert source.index(migration_probe) < source.index(gate_call)
    assert source.index(gate_call) < source.index('bash "$RELEASE_DIR/scripts/vps-backup.sh"')
    assert source.index(gate_call) < source.index("bash scripts/migrate-vps-sqlite-to-postgres.sh")
    assert source.index(gate_call) < source.index(
        'ln -s "$PREVIOUS_RELEASE" "$TARGET_DIR/.previous-next"'
    )
    assert source.index(gate_call) < source.index(
        'ln -s "$RELEASE_DIR" "$TARGET_DIR/.current-next"'
    )
    assert source.index(gate_call) < source.index(
        'mv -Tf "$TARGET_DIR/.current-next" "$TARGET_DIR/current"'
    )
    assert source.index(gate_call) < source.index('if [ "$WIPE_DOCKER" = "1" ]')
    assert source.index(gate_call) < source.index("compose down --remove-orphans")
    assert source.index(gate_call) < source.index("compose up -d runtime_ns redis postgres")
    assert source.index(gate_call) < source.index("ROLLBACK_READY=1")
    assert 'echo "$POSTGRES_PASSWORD"' not in source
    assert "No current release exists; there is no automatic rollback target to validate" in source
