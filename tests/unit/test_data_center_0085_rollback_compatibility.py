from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = REPOSITORY_ROOT / "scripts" / "verify_data_center_0085_rollback_compatibility.py"
QUOTE_SNAPSHOT_MODELS_PATH = Path("apps/data_center/infrastructure/quote_snapshot_models.py")
COMPATIBILITY_SOURCES = (
    Path("apps/data_center/migrations/0085_published_market_fact_revisions.py"),
    Path("apps/data_center/infrastructure/models.py"),
    QUOTE_SNAPSHOT_MODELS_PATH,
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
    database_migration_0086: str = "not_applied",
    database_scope_blocks_default: str = "not_checked",
    image_source_digest: str | None = None,
) -> tuple[int, str, str]:
    """Run the production checker entry point with only Docker reads mocked."""
    _install_fake_docker(
        monkeypatch,
        previous_release,
        image_source_digest=image_source_digest,
    )
    result = CHECKER.main(
        [
            "--previous-release",
            str(previous_release),
            "--database-migration-0085",
            database_state,
            "--database-migration-0086",
            database_migration_0086,
            "--database-scope-blocks-default",
            database_scope_blocks_default,
        ]
    )
    captured = capsys.readouterr()
    return result, captured.out, captured.err


def _move_quote_model_to_legacy_location(
    previous_release: Path,
    destination: Path = Path("apps/data_center/infrastructure/models.py"),
    *,
    remove_split_source: bool = False,
) -> None:
    """Place the quote class in a legacy module, optionally removing the split source."""
    quote_path = previous_release / QUOTE_SNAPSHOT_MODELS_PATH
    quote_source = quote_path.read_text(encoding="utf-8")
    quote_module = ast.parse(quote_source)
    quote_model = next(
        node
        for node in quote_module.body
        if isinstance(node, ast.ClassDef) and node.name == "QuoteSnapshotModel"
    )
    quote_class_source = ast.get_source_segment(quote_source, quote_model)
    assert quote_class_source is not None

    models_path = previous_release / CHECKER.MODELS_PATH
    models_source = models_path.read_text(encoding="utf-8")
    models_module = ast.parse(models_source)
    reexports = [
        node
        for node in models_module.body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "quote_snapshot_models"
        and any(alias.name == "QuoteSnapshotModel" for alias in node.names)
    ]
    assert len(reexports) == 1
    import_node = reexports[0]
    lines = models_source.splitlines(keepends=True)
    del lines[import_node.lineno - 1 : import_node.end_lineno]
    models_source_without_reexport = "".join(lines)
    legacy_path = previous_release / destination
    if destination == CHECKER.MODELS_PATH:
        legacy_source = models_source_without_reexport
    else:
        models_path.write_text(models_source_without_reexport, encoding="utf-8")
        legacy_source = legacy_path.read_text(encoding="utf-8")
    legacy_path.write_text(
        legacy_source.rstrip() + "\n\n" + quote_class_source + "\n",
        encoding="utf-8",
    )
    if remove_split_source:
        quote_path.unlink()


def _mutate_quote_reexport(previous_release: Path, defect: str) -> None:
    """Create one invalid module-level binding without executing release code."""
    models_path = previous_release / CHECKER.MODELS_PATH
    source = models_path.read_text(encoding="utf-8")
    module = ast.parse(source)
    imports = [
        node
        for node in module.body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "quote_snapshot_models"
        and any(alias.name == "QuoteSnapshotModel" for alias in node.names)
    ]
    assert len(imports) == 1
    import_node = imports[0]
    lines = source.splitlines(keepends=True)
    original_line = lines[import_node.lineno - 1]
    if defect == "commented":
        lines[import_node.lineno - 1] = "# " + original_line
    elif defect == "wrong_alias":
        assert "as QuoteSnapshotModel" in original_line
        lines[import_node.lineno - 1] = original_line.replace(
            "as QuoteSnapshotModel", "as QuoteSnapshotAlias"
        )
    elif defect == "later_assignment":
        lines.append("\nQuoteSnapshotModel = None\n")
    else:
        raise AssertionError(f"unsupported test defect: {defect}")
    models_path.write_text("".join(lines), encoding="utf-8")


def test_manifest_source_env_image_and_applied_schema_pass_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)

    return_code, stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 0, stderr
    assert "PREVIOUS_RELEASE_0085_COMPATIBLE" in stdout
    assert "database_migration_0085=applied" in stdout
    assert "database_migration_0086=not_applied" in stdout


def test_quote_snapshot_module_is_bound_to_the_immutable_image_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A changed split model must disagree with the image even for a legacy inline layout."""
    previous_release = _make_previous_release(tmp_path)
    _move_quote_model_to_legacy_location(previous_release)
    image_digest = CHECKER.compatibility_source_digest(previous_release)
    quote_path = previous_release / QUOTE_SNAPSHOT_MODELS_PATH
    quote_path.write_text(
        quote_path.read_text(encoding="utf-8") + "\n# source changed after image build\n",
        encoding="utf-8",
    )

    return_code, stdout, stderr = _run_checker(
        previous_release,
        monkeypatch,
        capsys,
        image_source_digest=image_digest,
    )

    assert return_code == 42
    assert not stdout
    assert "previous release checked source does not match the immutable Docker image" in stderr


def test_missing_quote_snapshot_reexport_target_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An explicit split-model import cannot pass when its target file is absent."""
    previous_release = _make_previous_release(tmp_path)
    (previous_release / QUOTE_SNAPSHOT_MODELS_PATH).unlink()

    return_code, stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 42
    assert not stdout
    assert (
        "missing or unreadable apps/data_center/infrastructure/quote_snapshot_models.py" in stderr
    )


@pytest.mark.parametrize("defect", ["commented", "wrong_alias", "later_assignment"])
def test_quote_snapshot_model_requires_an_exact_unshadowed_reexport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    defect: str,
) -> None:
    """Comments, aliases, and later module bindings cannot authorize another model source."""
    previous_release = _make_previous_release(tmp_path)
    _mutate_quote_reexport(previous_release, defect)

    return_code, stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 42
    assert not stdout
    assert "models.py is missing QuoteSnapshotModel" in stderr


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing_revision", "models.py QuoteSnapshotModel has no revision_number field"),
        (
            "wrong_natural_key",
            "models.py QuoteSnapshotModel does not declare the 0085 revision-aware key",
        ),
    ],
)
def test_split_quote_model_must_match_the_0085_revision_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
    expected_error: str,
) -> None:
    """The split class must retain both revision_number and its exact natural key."""
    previous_release = _make_previous_release(tmp_path)
    quote_path = previous_release / QUOTE_SNAPSHOT_MODELS_PATH
    source = quote_path.read_text(encoding="utf-8")
    if mutation == "missing_revision":
        revision_field = "    revision_number = models.PositiveSmallIntegerField(default=1)\n"
        assert revision_field in source
        source = source.replace(revision_field, "", 1)
    else:
        natural_key = (
            '        unique_together = [("asset_code", "snapshot_at", "source", "revision_number")]'
        )
        assert natural_key in source
        source = source.replace(
            natural_key,
            '        unique_together = [("asset_code", "snapshot_at", "revision_number")]',
            1,
        )
    quote_path.write_text(source, encoding="utf-8")

    return_code, stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 42
    assert not stdout
    assert expected_error in stderr


@pytest.mark.parametrize(
    "legacy_path",
    [
        Path("apps/data_center/infrastructure/models.py"),
        Path("apps/data_center/infrastructure/fact_and_operational_models.py"),
    ],
)
def test_previous_release_legacy_quote_model_locations_remain_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    legacy_path: Path,
) -> None:
    """Inline and other-fact layouts remain valid without the split module."""
    previous_release = _make_previous_release(tmp_path)
    _move_quote_model_to_legacy_location(
        previous_release,
        legacy_path,
        remove_split_source=True,
    )

    return_code, stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 0, stderr
    assert "PREVIOUS_RELEASE_0085_COMPATIBLE" in stdout


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
    assert "database_migration_0085=not_applied" in stdout
    assert "database_migration_0086=not_applied" in stdout


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
            "--database-migration-0086",
            "not_applied",
            "--database-scope-blocks-default",
            "not_checked",
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

    result = CHECKER.verify_previous_release(
        previous_release, DATABASE_STATE, "not_applied", "not_checked"
    )

    assert any(expected_error in error for error in result)


def test_missing_database_migration_state_fails_closed(tmp_path: Path) -> None:
    previous_release = _make_previous_release(tmp_path)

    result = CHECKER.verify_previous_release(
        previous_release, "unknown", "not_applied", "not_checked"
    )

    assert "database data_center.0085 migration state is unknown" in result


def test_unknown_0086_migration_state_fails_closed(tmp_path: Path) -> None:
    previous_release = _make_previous_release(tmp_path)

    result = CHECKER.verify_previous_release(previous_release, "applied", "unknown", "not_checked")

    assert "database data_center.0086 migration state is unknown" in result


def test_applied_0086_requires_a_non_null_empty_array_database_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)

    return_code, _stdout, stderr = _run_checker(
        previous_release,
        monkeypatch,
        capsys,
        database_migration_0086="applied",
        database_scope_blocks_default="incompatible",
    )

    assert return_code == 42
    assert "database CanonicalPublicationModel.scope_blocks" in stderr
    assert "JSON [] default" in stderr


def test_applied_0086_passes_when_database_default_is_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)

    return_code, stdout, stderr = _run_checker(
        previous_release,
        monkeypatch,
        capsys,
        database_migration_0086="applied",
        database_scope_blocks_default="empty_array",
    )

    assert return_code == 0, stderr
    assert "database_migration_0086=applied" in stdout
    assert "scope_blocks_default=empty_array" in stdout


def test_0086_applied_without_0085_fails_closed(tmp_path: Path) -> None:
    previous_release = _make_previous_release(tmp_path)

    result = CHECKER.verify_previous_release(
        previous_release, "not_applied", "applied", "empty_array"
    )

    assert "database data_center.0086 is applied while data_center.0085 is not" in result


def test_candidate_0086_migration_must_keep_database_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    previous_release = _make_previous_release(tmp_path)
    candidate_root = tmp_path / "candidate"
    migration_path = candidate_root / CHECKER.SCOPE_BLOCKS_MIGRATION_PATH
    model_path = candidate_root / CHECKER.SCOPE_BLOCKS_MODEL_PATH
    migration_path.parent.mkdir(parents=True)
    model_path.parent.mkdir(parents=True)
    migration_source = (REPOSITORY_ROOT / CHECKER.SCOPE_BLOCKS_MIGRATION_PATH).read_text(
        encoding="utf-8"
    )
    model_source = (REPOSITORY_ROOT / CHECKER.SCOPE_BLOCKS_MODEL_PATH).read_text(encoding="utf-8")
    migration_path.write_text(
        migration_source.replace("db_default=[]", "db_default=None"), encoding="utf-8"
    )
    model_path.write_text(model_source, encoding="utf-8")
    monkeypatch.setattr(CHECKER, "CURRENT_RELEASE_ROOT", candidate_root)

    return_code, _stdout, stderr = _run_checker(previous_release, monkeypatch, capsys)

    assert return_code == 42
    assert "0086 migration scope_blocks lacks its empty-array database default" in stderr


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
    assert "database_migration_0085=not_applied" in stdout


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
    assert "0086_canonical_publication_scope_blocks" in source
    assert "data_center.0086 migration state could not be read" in source
    assert "column_default" in source
    assert "is_nullable='NO'" in source
    assert '--database-migration-0086 "$DATABASE_MIGRATION_0086"' in source
    assert '--database-scope-blocks-default "$SCOPE_BLOCKS_DATABASE_DEFAULT"' in source
    assert "ROLLBACK_SCHEMA_INCOMPATIBLE" in source
    assert source.index(previous_release_assignment) < source.index(migration_probe)
    assert source.index(postgres_container_lookup) < source.index(migration_probe)
    assert source.index(migration_probe) < source.index(gate_call)
    # The deploy phase still gates before its own fallback backup invocation; the
    # build phase may additionally run a read-only pg_dump/BGSAVE backup earlier.
    deploy_section = source[source.index("def _build_remote_deploy_script()") :]
    assert deploy_section.index(gate_call) < deploy_section.index(
        'bash "$RELEASE_DIR/scripts/vps-backup.sh"'
    )
    assert source.index(gate_call) < source.index("sh scripts/migrate-vps-sqlite-to-postgres.sh")
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
