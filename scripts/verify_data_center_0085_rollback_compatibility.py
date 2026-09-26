#!/usr/bin/env python3
"""Fail closed when a deployment's rollback release cannot write schema 0085."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

EXPECTED_NATURAL_KEYS: dict[str, tuple[str, ...]] = {
    "financialfactmodel": ("asset_code", "period_end", "period_type", "metric_code", "source"),
    "pricebarmodel": ("asset_code", "bar_date", "freq", "adjustment", "source"),
    "quotesnapshotmodel": ("asset_code", "snapshot_at", "source"),
    "valuationfactmodel": ("asset_code", "val_date", "source"),
}
MODEL_NAMES: dict[str, str] = {
    "financialfactmodel": "FinancialFactModel",
    "pricebarmodel": "PriceBarModel",
    "quotesnapshotmodel": "QuoteSnapshotModel",
    "valuationfactmodel": "ValuationFactModel",
}
MIGRATION_PATH = Path("apps/data_center/migrations/0085_published_market_fact_revisions.py")
MODELS_PATH = Path("apps/data_center/infrastructure/models.py")
OTHER_FACT_MODELS_PATH = Path("apps/data_center/infrastructure/fact_and_operational_models.py")
VERSION_WRITER_PATH = Path("apps/data_center/infrastructure/published_fact_versions.py")
FINANCIAL_WRITER_PATH = Path("apps/data_center/infrastructure/financial_fact_write_guard.py")
RELEASE_MANIFEST_PATH = Path(".agom-release-manifest.json")
DEPLOY_ENV_PATH = Path("deploy/.env")
MANIFEST_KEYS = {
    "version",
    "release_tag",
    "source_commit",
    "image_tag",
    "image_id",
    "build_started_at",
    "build_finished_at",
    "source_mode",
}
IMAGE_SOURCE_DIGEST_PROGRAM = """
import hashlib
from pathlib import Path
import sys

paths = tuple(sys.argv[1:])
if not paths:
    raise SystemExit(2)
digest = hashlib.sha256()
root = Path("/app")
for name in paths:
    data = (root / name).read_bytes()
    digest.update(name.encode("utf-8"))
    digest.update(b"\\0")
    digest.update(data)
    digest.update(b"\\0")
print(digest.hexdigest())
"""


@dataclass(frozen=True)
class ReleaseIdentity:
    """Validated release identity bound to its immutable image manifest."""

    release_tag: str
    source_commit: str
    image_tag: str
    image_id: str
    source_mode: str


def compatibility_source_digest(
    release_root: Path,
    source_paths: tuple[Path, ...] | None = None,
) -> str:
    """Hash the available source files used to identify the previous release."""
    digest = hashlib.sha256()
    candidate_paths = (
        MIGRATION_PATH,
        MODELS_PATH,
        OTHER_FACT_MODELS_PATH,
        VERSION_WRITER_PATH,
        FINANCIAL_WRITER_PATH,
    )
    paths = source_paths or tuple(
        relative_path
        for relative_path in candidate_paths
        if (release_root / relative_path).is_file()
    )
    for relative_path in paths:
        data = (release_root / relative_path).read_bytes()
        digest.update(relative_path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def _load_release_identity(release_root: Path, errors: list[str]) -> ReleaseIdentity | None:
    """Load and validate the read-only release manifest and its WEB_IMAGE binding."""
    manifest_path = release_root / RELEASE_MANIFEST_PATH
    try:
        manifest_stat = manifest_path.lstat()
        if not stat.S_ISREG(manifest_stat.st_mode) or stat.S_IMODE(manifest_stat.st_mode) != 0o444:
            errors.append("previous release manifest is not a regular read-only 0444 file")
            return None
        raw_manifest = manifest_path.read_text(encoding="utf-8")
        manifest: object = json.loads(raw_manifest)
    except (OSError, UnicodeError, json.JSONDecodeError):
        errors.append("previous release manifest is missing or invalid")
        return None
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_KEYS:
        errors.append("previous release manifest has an unsupported schema")
        return None
    if type(manifest.get("version")) is not int or manifest["version"] != 1:
        errors.append("previous release manifest version is unsupported")
        return None
    if any(type(manifest.get(key)) is not str for key in MANIFEST_KEYS - {"version"}):
        errors.append("previous release manifest identity fields are invalid")
        return None

    release_tag = manifest["release_tag"]
    source_commit = manifest["source_commit"]
    image_tag = manifest["image_tag"]
    image_id = manifest["image_id"]
    if re.fullmatch(r"[0-9]{14}", release_tag) is None:
        errors.append("previous release manifest tag is invalid")
        return None
    if release_root.name != f"source-{release_tag}":
        errors.append("previous release directory does not match its manifest tag")
        return None
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        errors.append("previous release source commit is invalid")
        return None
    if image_tag != f"agomtradepro-web:{release_tag}":
        errors.append("previous release manifest image tag is invalid")
        return None
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        errors.append("previous release manifest image ID is invalid")
        return None
    if manifest["source_mode"] not in {"source-upload", "git-clone"}:
        errors.append("previous release manifest source mode is invalid")
        return None

    env_path = release_root / DEPLOY_ENV_PATH
    try:
        web_image_values = [
            line.partition("=")[2].strip()
            for line in env_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("WEB_IMAGE=")
        ]
    except (OSError, UnicodeError):
        errors.append("previous release deployment image configuration is missing")
        return None
    if len(web_image_values) != 1 or web_image_values[0] != image_tag:
        errors.append("previous release WEB_IMAGE does not match its immutable manifest")
        return None

    return ReleaseIdentity(release_tag, source_commit, image_tag, image_id, manifest["source_mode"])


def _docker_output(arguments: tuple[str, ...], errors: list[str], identity: str) -> str | None:
    """Run one read-only Docker identity query without exposing raw command output."""
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        errors.append(f"previous release Docker {identity} check failed")
        return None
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        errors.append(f"previous release Docker {identity} check failed")
        return None
    return value


def _verify_image_identity(
    identity: ReleaseIdentity,
    release_root: Path,
    errors: list[str],
) -> None:
    """Bind manifest, configured tag, immutable Docker ID, OCI revision, and checked source."""
    actual_image_id = _docker_output(
        ("docker", "image", "inspect", identity.image_tag, "--format", "{{.Id}}"),
        errors,
        "ID",
    )
    if actual_image_id != identity.image_id:
        errors.append("previous release Docker image ID does not match its immutable manifest")
        return
    actual_revision = _docker_output(
        (
            "docker",
            "image",
            "inspect",
            identity.image_id,
            "--format",
            '{{index .Config.Labels "org.opencontainers.image.revision"}}',
        ),
        errors,
        "OCI revision",
    )
    if actual_revision != identity.source_commit:
        errors.append("previous release Docker OCI revision does not match its source commit")
        return
    source_paths = tuple(
        relative_path
        for relative_path in (
            MIGRATION_PATH,
            MODELS_PATH,
            OTHER_FACT_MODELS_PATH,
            VERSION_WRITER_PATH,
            FINANCIAL_WRITER_PATH,
        )
        if (release_root / relative_path).is_file()
    )
    if not source_paths:
        errors.append("previous release source identity files are missing")
        return
    image_source_digest = _docker_output(
        (
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--entrypoint",
            "python",
            identity.image_id,
            "-c",
            IMAGE_SOURCE_DIGEST_PROGRAM,
            *(relative_path.as_posix() for relative_path in source_paths),
        ),
        errors,
        "compatibility source",
    )
    try:
        release_source_digest = compatibility_source_digest(release_root, source_paths)
    except OSError:
        errors.append("previous release compatibility source is missing or unreadable")
        return
    if (
        image_source_digest is None
        or re.fullmatch(r"[0-9a-f]{64}", image_source_digest) is None
        or image_source_digest != release_source_digest
    ):
        errors.append("previous release checked source does not match the immutable Docker image")


def _read_module(release_root: Path, relative_path: Path, errors: list[str]) -> ast.Module | None:
    """Parse one previous-release Python module and collect stable diagnostics."""
    path = release_root / relative_path
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        errors.append(f"missing or unreadable {relative_path.as_posix()}")
        return None
    try:
        return ast.parse(source, filename=str(relative_path))
    except SyntaxError:
        errors.append(f"invalid Python syntax in {relative_path.as_posix()}")
        return None


def _find_class(module: ast.Module, name: str) -> ast.ClassDef | None:
    """Return a top-level class by name."""
    return next(
        (node for node in module.body if isinstance(node, ast.ClassDef) and node.name == name),
        None,
    )


def _find_function(module: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return a top-level function by name."""
    return next(
        (
            node
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )


def _literal_string_tuples(node: ast.AST) -> set[tuple[str, ...]]:
    """Extract literal string tuples from Django's unique_together declaration."""
    try:
        value: object = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return set()
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    return {
        tuple(item)
        for item in value
        if isinstance(item, (list, tuple)) and all(isinstance(field, str) for field in item)
    }


def _assigned_value(statements: list[ast.stmt], name: str) -> ast.AST | None:
    """Return the value assigned to a simple class/module-level name."""
    for statement in statements:
        if isinstance(statement, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == name for target in statement.targets
            ):
                return statement.value
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.target.id == name:
                return statement.value
    return None


def _check_migration(module: ast.Module, errors: list[str]) -> None:
    """Verify migration 0085 installs revision-aware keys for all published facts."""
    migration = _find_class(module, "Migration")
    if migration is None:
        errors.append("0085 migration has no Migration class")
        return
    dependencies = _assigned_value(migration.body, "dependencies")
    try:
        dependency_values: object = ast.literal_eval(dependencies) if dependencies else None
    except (ValueError, TypeError, SyntaxError):
        dependency_values = None
    expected_dependency = ("data_center", "0084_normalize_tushare_valuation_market_cap_units")
    if (
        not isinstance(dependency_values, (list, tuple))
        or expected_dependency not in dependency_values
    ):
        errors.append("0085 migration does not depend on data_center.0084")

    operations = _assigned_value(migration.body, "operations")
    operation_nodes = operations.elts if isinstance(operations, (ast.List, ast.Tuple)) else []
    altered_models: set[str] = set()
    has_member_index = False
    for operation in operation_nodes:
        if not isinstance(operation, ast.Call) or not isinstance(operation.func, ast.Attribute):
            continue
        if operation.func.attr == "AlterUniqueTogether":
            keywords = {item.arg: item.value for item in operation.keywords if item.arg is not None}
            model_name_node = keywords.get("name")
            unique_together_node = keywords.get("unique_together")
            if model_name_node is None or unique_together_node is None:
                continue
            try:
                model_name = ast.literal_eval(model_name_node)
            except (ValueError, TypeError, SyntaxError):
                continue
            if not isinstance(model_name, str) or model_name not in EXPECTED_NATURAL_KEYS:
                continue
            expected_key = (*EXPECTED_NATURAL_KEYS[model_name], "revision_number")
            if expected_key in _literal_string_tuples(unique_together_node):
                altered_models.add(model_name)
        elif operation.func.attr == "AddIndex":
            keywords = {item.arg: item.value for item in operation.keywords if item.arg is not None}
            index_node = keywords.get("index")
            if not isinstance(index_node, ast.Call):
                continue
            index_keywords = {
                item.arg: item.value for item in index_node.keywords if item.arg is not None
            }
            index_name_node = index_keywords.get("name")
            index_fields_node = index_keywords.get("fields")
            if index_name_node is None or index_fields_node is None:
                continue
            try:
                index_name = ast.literal_eval(index_name_node)
                index_fields = ast.literal_eval(index_fields_node)
            except (ValueError, TypeError, SyntaxError):
                continue
            if index_name == "dc_pub_member_fact_idx" and index_fields == ["fact_table", "fact_pk"]:
                has_member_index = True

    for model_name in EXPECTED_NATURAL_KEYS:
        if model_name not in altered_models:
            errors.append(f"0085 migration lacks revision_number unique key for {model_name}")
    if not has_member_index:
        errors.append("0085 migration lacks publication-member fact lookup index")


def _check_models(module: ast.Module, other_fact_models: ast.Module, errors: list[str]) -> None:
    """Verify the previous release model state matches the 0085 database schema."""
    for migration_model_name, model_name in MODEL_NAMES.items():
        model = _find_class(module, model_name) or _find_class(other_fact_models, model_name)
        if model is None:
            errors.append(f"models.py is missing {model_name}")
            continue
        revision_field = _assigned_value(model.body, "revision_number")
        if not isinstance(revision_field, ast.Call):
            errors.append(f"models.py {model_name} has no revision_number field")
            continue
        meta = next(
            (node for node in model.body if isinstance(node, ast.ClassDef) and node.name == "Meta"),
            None,
        )
        unique_together = _assigned_value(meta.body, "unique_together") if meta else None
        expected_key = (*EXPECTED_NATURAL_KEYS[migration_model_name], "revision_number")
        if unique_together is None or expected_key not in _literal_string_tuples(unique_together):
            errors.append(f"models.py {model_name} does not declare the 0085 revision-aware key")


def _is_revision_successor_assignment(node: ast.AST) -> bool:
    """Recognize incoming.revision_number = previous.revision_number + 1."""
    if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.BinOp):
        return False
    target_matches = any(
        isinstance(target, ast.Attribute)
        and target.attr == "revision_number"
        and isinstance(target.value, ast.Name)
        and target.value.id == "incoming"
        for target in node.targets
    )
    previous_revision = (
        isinstance(node.value.left, ast.Attribute)
        and node.value.left.attr == "revision_number"
        and isinstance(node.value.left.value, ast.Name)
        and node.value.left.value.id == "previous"
    )
    return (
        target_matches
        and previous_revision
        and isinstance(node.value.op, ast.Add)
        and isinstance(node.value.right, ast.Constant)
        and node.value.right.value == 1
    )


def _has_revision_conflict_key(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check that generic versioned fact upserts conflict on natural key plus revision."""
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "bulk_create":
            continue
        for keyword in node.keywords:
            if keyword.arg == "unique_fields" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                if any(
                    isinstance(item, ast.Constant) and item.value == "revision_number"
                    for item in keyword.value.elts
                ):
                    return True
    return False


def _check_version_writer(module: ast.Module, errors: list[str]) -> None:
    """Verify generic writers select and append revisions rather than using old keys."""
    latest = _find_function(module, "latest_fact_revisions")
    if latest is None or not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "order_by"
        and any(
            isinstance(arg, ast.Constant) and arg.value == "-revision_number" for arg in node.args
        )
        for node in ast.walk(latest)
    ):
        errors.append("published_fact_versions.py does not read the latest revision")
    upsert = _find_function(module, "_upsert_locked_facts")
    if upsert is None:
        errors.append("published_fact_versions.py is missing _upsert_locked_facts")
        return
    if not any(_is_revision_successor_assignment(node) for node in ast.walk(upsert)):
        errors.append("published_fact_versions.py does not append a successor revision")
    if not _has_revision_conflict_key(upsert):
        errors.append("published_fact_versions.py does not upsert on revision_number")


def _check_financial_writer(module: ast.Module, errors: list[str]) -> None:
    """Verify financial writes append a new row for a published revision."""
    upsert = _find_function(module, "bulk_upsert_financial_facts")
    if upsert is None:
        errors.append("financial_fact_write_guard.py is missing bulk_upsert_financial_facts")
        return
    has_revision_increment = any(
        isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Attribute)
        and node.target.attr == "revision_number"
        and isinstance(node.target.value, ast.Name)
        and node.target.value.id == "row"
        and isinstance(node.op, ast.Add)
        and isinstance(node.value, ast.Constant)
        and node.value.value == 1
        for node in ast.walk(upsert)
    )
    has_successor_insert = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "append"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "successors"
        for node in ast.walk(upsert)
    ) and any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "bulk_create"
        for node in ast.walk(upsert)
    )
    if not has_revision_increment or not has_successor_insert:
        errors.append("financial_fact_write_guard.py does not append successor revisions")
    if not any(
        isinstance(node, ast.Constant) and node.value == "-revision_number"
        for node in ast.walk(module)
    ):
        errors.append("financial_fact_write_guard.py does not select the latest revision")


def verify_previous_release(
    release_root: Path,
    database_migration_0085: str,
) -> tuple[str, ...]:
    """Validate the rollback source, manifest, Docker image, and migration state.

    The previous code is checked against the immutable image and source commit.
    The database migration state is supplied by a read-only query from the
    running PostgreSQL container. Revision-aware writer compatibility is
    required only when 0085 is already applied. Both states still require the
    previous source, release manifest, and immutable image identities to agree.
    """
    if not release_root.is_dir():
        return ("previous release directory is missing or unreadable",)
    if database_migration_0085 not in {"applied", "not_applied"}:
        return ("database data_center.0085 migration state is unknown",)
    errors: list[str] = []
    identity = _load_release_identity(release_root, errors)
    if identity is not None:
        _verify_image_identity(identity, release_root, errors)
        git_metadata = release_root / ".git"
        if identity.source_mode == "git-clone" and not git_metadata.exists():
            errors.append("previous release Git metadata is missing")
        if git_metadata.exists():
            try:
                git_result = subprocess.run(
                    ("git", "-C", str(release_root), "rev-parse", "--verify", "HEAD"),
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=15,
                )
            except (OSError, subprocess.TimeoutExpired):
                errors.append("previous release source commit could not be verified")
            else:
                if (
                    git_result.returncode != 0
                    or git_result.stdout.strip() != identity.source_commit
                ):
                    errors.append("previous release Git source commit does not match its manifest")
    if database_migration_0085 == "applied":
        migration = _read_module(release_root, MIGRATION_PATH, errors)
        models = _read_module(release_root, MODELS_PATH, errors)
        other_fact_models = _read_module(release_root, OTHER_FACT_MODELS_PATH, errors)
        version_writer = _read_module(release_root, VERSION_WRITER_PATH, errors)
        financial_writer = _read_module(release_root, FINANCIAL_WRITER_PATH, errors)
        if migration is not None:
            _check_migration(migration, errors)
        if models is not None and other_fact_models is not None:
            _check_models(models, other_fact_models, errors)
        if version_writer is not None:
            _check_version_writer(version_writer, errors)
        if financial_writer is not None:
            _check_financial_writer(financial_writer, errors)
    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    """Check previous-release rollback compatibility and print a safe result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-release", required=True, type=Path)
    parser.add_argument(
        "--database-migration-0085",
        required=True,
        choices=("applied", "not_applied"),
        help="Read-only migration state queried from the currently running PostgreSQL container",
    )
    args = parser.parse_args(argv)
    errors = verify_previous_release(args.previous_release, args.database_migration_0085)
    if errors:
        print("ROLLBACK_SCHEMA_INCOMPATIBLE: " + "; ".join(errors), file=sys.stderr)
        print(
            "Recovery: stop before database migration and keep current data intact. "
            "Deploy a release with a revision-aware rollback writer, or use a forward "
            "compatibility release; do not delete revisions or restore an older database.",
            file=sys.stderr,
        )
        return 42
    print(
        "PREVIOUS_RELEASE_0085_COMPATIBLE: "
        f"release={args.previous_release.name} database_migration={args.database_migration_0085}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
