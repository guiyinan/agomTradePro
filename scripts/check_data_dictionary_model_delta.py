#!/usr/bin/env python
"""Validate exact Git-range model deltas from the generated AST projection."""

from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, get_args

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_data_dictionary import (  # noqa: E402
    _canonical_json,
    _extract_model,
    build_data_dictionary,
    render_markdown,
)

REF01_HEADER = (
    "base_sha",
    "identity",
    "change_kind",
    "rationale",
    "consumer_audit",
    "compatibility_or_rollback",
)
DeltaKind = Literal[
    "added_concrete",
    "added_abstract",
    "new_version",
    "deleted_concrete",
    "deleted_abstract",
    "file_move",
    "model_change",
]
EXPLANATION_KINDS: frozenset[str] = frozenset(get_args(DeltaKind)) - {"file_move"}
UNKNOWN_AUDIT_VALUES = frozenset(
    {"", "unknown", "unverified", "not assessed", "not-assessed", "tbd"}
)
_VERSION_NAME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("v_model", re.compile(r"^(?P<stem>.+)V(?P<version>[1-9][0-9]*)Model$")),
    ("model_v", re.compile(r"^(?P<stem>.+Model)V(?P<version>[1-9][0-9]*)$")),
    ("version", re.compile(r"^(?P<stem>.+)Version(?P<version>[1-9][0-9]*)$")),
    ("v", re.compile(r"^(?P<stem>.+)V(?P<version>[1-9][0-9]*)$")),
)
_FULL_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_ANY_HEADING = re.compile(r"^#{1,6}\s+")


@dataclass(frozen=True, slots=True)
class ModelDelta:
    """One deterministic change to a projected model identity."""

    app_name: str
    class_name: str
    kind: DeltaKind
    before: dict[str, object] | None
    after: dict[str, object] | None
    facets: tuple[str, ...]

    @property
    def identity(self) -> str:
        """Return the stable ``app.Class`` identity used by the delta gate."""

        return f"{self.app_name}.{self.class_name}"


@dataclass(frozen=True, slots=True)
class Ref01ExplanationRow:
    """One structured REF-01 explanation row from an existing plan file."""

    base_sha: str
    identity: str
    change_kind: str
    rationale: str
    consumer_audit: str
    compatibility_or_rollback: str


def _identity_index(payload: dict[str, object]) -> dict[tuple[str, str], dict[str, object]]:
    apps = payload.get("apps")
    if not isinstance(apps, dict):
        raise ValueError("data dictionary apps must be a JSON object")
    index: dict[tuple[str, str], dict[str, object]] = {}
    for raw_app_name, raw_app in apps.items():
        if not isinstance(raw_app_name, str) or not raw_app_name:
            raise ValueError("data dictionary contains an invalid app identity")
        if not isinstance(raw_app, dict):
            raise ValueError(f"app record is not an object: {raw_app_name}")
        raw_models = raw_app.get("models")
        if not isinstance(raw_models, list):
            raise ValueError(f"app models must be a list: {raw_app_name}")
        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                raise ValueError(f"model record is not an object: {raw_app_name}")
            raw_class_name = raw_model.get("class_name")
            raw_source_file = raw_model.get("source_file")
            if not isinstance(raw_class_name, str) or not raw_class_name:
                raise ValueError(f"model class_name is missing: {raw_app_name}")
            if not isinstance(raw_source_file, str) or not raw_source_file:
                raise ValueError(f"model source_file is missing: {raw_app_name}.{raw_class_name}")
            abstract = raw_model.get("abstract", False)
            if not isinstance(abstract, bool):
                raise ValueError(
                    f"model abstract marker is invalid: {raw_app_name}.{raw_class_name}"
                )
            identity = (raw_app_name, raw_class_name)
            if identity in index:
                raise ValueError(
                    "ambiguous projected model identity: " f"{raw_app_name}.{raw_class_name}"
                )
            index[identity] = raw_model
    return index


def _ast_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _ast_name(node.value)
        return f"{parent}.{node.attr}" if parent is not None else None
    return None


def _django_model_imports(tree: ast.Module) -> tuple[set[str], set[str]]:
    model_names: set[str] = set()
    model_modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local_name = alias.asname or alias.name
                if (
                    module in {"django.db.models", "django.db.models.base"}
                    and alias.name == "Model"
                ):
                    model_names.add(local_name)
                if module == "django.db" and alias.name == "models":
                    model_modules.add(local_name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                if alias.name == "django.db.models":
                    model_modules.add(local_name)
                elif alias.name == "django.db":
                    model_modules.add(f"{local_name}.models")
    return model_names, model_modules


def _known_model_import_aliases(tree: ast.Module, known_model_names: frozenset[str]) -> set[str]:
    aliases: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if not module.startswith("apps.") and node.level == 0:
                continue
            for alias in node.names:
                if alias.name in known_model_names:
                    aliases.add(alias.asname or alias.name)
    return aliases


def _class_model_lineage(
    tree: ast.Module,
    known_model_names: frozenset[str],
    same_app_model_names: frozenset[str],
) -> dict[str, ast.ClassDef]:
    """Find module-level classes directly based on Django or known models."""

    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    direct_model_names, model_modules = _django_model_imports(tree)
    imported_model_aliases = _known_model_import_aliases(tree, known_model_names)
    local_model_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for candidate in classes:
            if candidate.name in local_model_names:
                continue
            if any(
                _base_is_model(
                    base,
                    direct_model_names=direct_model_names,
                    model_modules=model_modules,
                    known_model_names=known_model_names,
                    same_app_model_names=same_app_model_names,
                    imported_model_aliases=imported_model_aliases,
                    local_model_names=local_model_names,
                )
                for base in candidate.bases
            ):
                local_model_names.add(candidate.name)
                changed = True
    return {node.name: node for node in classes if node.name in local_model_names}


def _base_is_model(
    base: ast.expr,
    *,
    direct_model_names: set[str],
    model_modules: set[str],
    known_model_names: frozenset[str],
    same_app_model_names: frozenset[str],
    imported_model_aliases: set[str],
    local_model_names: set[str],
) -> bool:
    """Check a base expression against direct Django and known model identities."""

    dotted = _ast_name(base)
    if dotted is None:
        return False
    terminal = dotted.rsplit(".", 1)[-1]
    if terminal in direct_model_names:
        return True
    if terminal == "Model":
        if dotted in {"django.db.models.Model", "django.db.models.base.Model"}:
            return True
        return any(dotted == f"{module}.Model" for module in model_modules)
    return (
        terminal in same_app_model_names
        or terminal in imported_model_aliases
        or terminal in local_model_names
        or (dotted.startswith("apps.") and terminal in known_model_names)
    )


def _class_semantics(node: ast.ClassDef) -> str:
    """Return the same declared schema facets the dictionary builder observes."""

    record = _extract_model(node, "unprojected.py")
    record.pop("docstring", None)
    record.pop("source_file", None)
    return _canonical_json(record)


def _projection_source_index(
    payload: dict[str, object],
) -> dict[tuple[str, str], str]:
    """Map projected model identities to their source-relative file paths."""

    return {
        identity: str(model["source_file"]) for identity, model in _identity_index(payload).items()
    }


def validate_unprojected_new_model_declarations(
    base_payload: dict[str, object],
    head_payload: dict[str, object],
    *,
    git_executable: str,
    repository_root: Path,
    base_sha: str,
    head_sha: str,
) -> list[str]:
    """Fail if changed app Python adds or edits model lineage outside the projection."""

    changed = subprocess.run(
        [
            git_executable,
            "-C",
            str(repository_root),
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            base_sha,
            head_sha,
            "--",
            "apps",
        ],
        capture_output=True,
        check=False,
    )
    if changed.returncode != 0:
        stderr = changed.stderr.decode("utf-8", errors="replace").strip()
        return [f"could not inspect changed app Python files: {stderr}"]
    base_sources = _projection_source_index(base_payload)
    head_sources = _projection_source_index(head_payload)
    known_names = frozenset(
        class_name for _, class_name in base_sources.keys() | head_sources.keys()
    )
    problems: list[str] = []
    changed_paths = changed.stdout.decode("utf-8", errors="strict").split("\x00")
    for path in sorted(
        candidate
        for candidate in changed_paths
        if candidate.startswith("apps/")
        and candidate.endswith(".py")
        and not _is_migration_path(candidate)
    ):
        path_parts = PurePosixPath(path).parts
        if len(path_parts) < 3:
            continue
        app_name = path_parts[1]
        source_file = PurePosixPath(*path_parts[2:]).as_posix()
        try:
            base_bytes = _git_show(repository_root, base_sha, path)
        except ValueError:
            base_bytes = None
        try:
            head_bytes = _git_show(repository_root, head_sha, path)
        except ValueError:
            head_bytes = None
        if base_bytes is None:
            base_tree = ast.Module(body=[], type_ignores=[])
        else:
            try:
                base_tree = ast.parse(base_bytes.decode("utf-8", errors="strict"), filename=path)
            except (UnicodeDecodeError, SyntaxError) as exc:
                problems.append(f"cannot classify changed base source {path}: {exc}")
                continue
        if head_bytes is None:
            head_tree = ast.Module(body=[], type_ignores=[])
        else:
            try:
                head_tree = ast.parse(head_bytes.decode("utf-8", errors="strict"), filename=path)
            except (UnicodeDecodeError, SyntaxError) as exc:
                problems.append(f"cannot classify changed head source {path}: {exc}")
                continue
        base_same_app_names = frozenset(
            class_name for candidate_app, class_name in base_sources if candidate_app == app_name
        )
        head_same_app_names = frozenset(
            class_name for candidate_app, class_name in head_sources if candidate_app == app_name
        )
        base_lineage = _class_model_lineage(base_tree, known_names, base_same_app_names)
        head_lineage = _class_model_lineage(head_tree, known_names, head_same_app_names)
        class_names = base_lineage.keys() | head_lineage.keys()
        for class_name in sorted(class_names):
            identity = (app_name, class_name)
            base_node = base_lineage.get(class_name)
            head_node = head_lineage.get(class_name)
            base_projected_here = base_sources.get(identity) == source_file
            head_projected_here = head_sources.get(identity) == source_file
            if base_node is not None and not base_projected_here:
                if head_node is None or _class_semantics(base_node) != _class_semantics(head_node):
                    problems.append(
                        "unprojected model-like declaration changed or removed: "
                        f"{app_name}.{class_name} at {path}"
                    )
            if head_node is not None and not head_projected_here:
                if base_node is None or _class_semantics(base_node) != _class_semantics(head_node):
                    problems.append(
                        "unprojected model-like declaration added or changed: "
                        f"{app_name}.{class_name} at {path}"
                    )
    return problems


def _semantic_model(model: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in model.items() if key not in {"docstring", "source_file"}}


def _versioned_name(class_name: str) -> tuple[str, str, int] | None:
    for layout, pattern in _VERSION_NAME_PATTERNS:
        match = pattern.fullmatch(class_name)
        if match is not None:
            return layout, match.group("stem"), int(match.group("version"))
    return None


def _is_new_version(
    app_name: str,
    class_name: str,
    base_models: Mapping[tuple[str, str], dict[str, object]],
) -> bool:
    candidate = _versioned_name(class_name)
    if candidate is None:
        return False
    layout, stem, version = candidate
    for candidate_app, candidate_name in base_models:
        if candidate_app != app_name:
            continue
        prior = _versioned_name(candidate_name)
        if prior is not None and prior[0] == layout and prior[1] == stem:
            if prior[2] < version:
                return True
    return False


def _declared_table(model: dict[str, object] | None) -> str | None:
    if model is None:
        return None
    meta = model.get("meta")
    if not isinstance(meta, dict):
        return None
    table_name = meta.get("db_table")
    return table_name if isinstance(table_name, str) and table_name else None


def _changed_facets(before: dict[str, object], after: dict[str, object]) -> tuple[str, ...]:
    facets: set[str] = set()
    if before.get("source_file") != after.get("source_file"):
        facets.add("source_file")
    if before.get("bases") != after.get("bases"):
        facets.add("bases")
    if before.get("fields") != after.get("fields"):
        facets.add("declared_fields")
    if before.get("choices_classes") != after.get("choices_classes"):
        facets.add("choice_members")
    if before.get("abstract", False) != after.get("abstract", False):
        facets.add("abstractness")

    before_meta = before.get("meta")
    after_meta = after.get("meta")
    if before_meta != after_meta:
        before_meta_dict = before_meta if isinstance(before_meta, dict) else {}
        after_meta_dict = after_meta if isinstance(after_meta, dict) else {}
        if before_meta_dict.get("db_table") != after_meta_dict.get("db_table"):
            facets.add("declared_db_table")
        remaining_before = {
            key: value for key, value in before_meta_dict.items() if key != "db_table"
        }
        remaining_after = {
            key: value for key, value in after_meta_dict.items() if key != "db_table"
        }
        if remaining_before != remaining_after:
            facets.add("model_meta")

    recognized = {
        "class_name",
        "source_file",
        "bases",
        "fields",
        "choices_classes",
        "abstract",
        "meta",
        "docstring",
    }
    if any(
        before.get(key) != after.get(key) for key in (before.keys() | after.keys()) - recognized
    ):
        facets.add("other_projection_data")
    return tuple(sorted(facets))


def compare_model_projections(
    base_payload: dict[str, object], head_payload: dict[str, object]
) -> tuple[ModelDelta, ...]:
    """Compare direct AST model identities, ignoring docs and file location."""

    base_models = _identity_index(base_payload)
    head_models = _identity_index(head_payload)
    deltas: list[ModelDelta] = []
    for identity in sorted(base_models.keys() | head_models.keys()):
        app_name, class_name = identity
        before = base_models.get(identity)
        after = head_models.get(identity)
        if before is None and after is not None:
            kind: DeltaKind = (
                "new_version"
                if _is_new_version(app_name, class_name, base_models)
                else ("added_abstract" if after.get("abstract") is True else "added_concrete")
            )
            deltas.append(
                ModelDelta(
                    app_name=app_name,
                    class_name=class_name,
                    kind=kind,
                    before=None,
                    after=dict(after),
                    facets=("model_identity",),
                )
            )
            continue
        if before is not None and after is None:
            kind = "deleted_abstract" if before.get("abstract") is True else "deleted_concrete"
            deltas.append(
                ModelDelta(
                    app_name=app_name,
                    class_name=class_name,
                    kind=kind,
                    before=dict(before),
                    after=None,
                    facets=("model_identity",),
                )
            )
            continue
        if before is None or after is None:
            continue
        facets = _changed_facets(before, after)
        semantic_changed = _semantic_model(before) != _semantic_model(after)
        if not semantic_changed:
            if before.get("source_file") != after.get("source_file"):
                deltas.append(
                    ModelDelta(
                        app_name=app_name,
                        class_name=class_name,
                        kind="file_move",
                        before=dict(before),
                        after=dict(after),
                        facets=("source_file",),
                    )
                )
            continue
        deltas.append(
            ModelDelta(
                app_name=app_name,
                class_name=class_name,
                kind="model_change",
                before=dict(before),
                after=dict(after),
                facets=facets,
            )
        )
    return tuple(deltas)


def _pipe_cells(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return tuple(cell.strip() for cell in stripped[1:-1].split("|"))


def _is_table_separator(cells: tuple[str, ...]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def parse_ref01_explanation_rows(markdown: str) -> tuple[Ref01ExplanationRow, ...]:
    """Parse strict REF-01 explanation tables from one plan document."""

    rows: list[Ref01ExplanationRow] = []
    table_active = False
    separator_seen = False
    fence: str | None = None
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.lstrip()
        fence_match = re.match(r"(`{3,}|~{3,})", stripped)
        if fence is not None:
            if fence_match is not None and fence_match.group(1)[0] == fence[0]:
                if len(fence_match.group(1)) >= len(fence):
                    fence = None
            continue
        if fence_match is not None:
            fence = fence_match.group(1)
            continue
        if _ANY_HEADING.match(line):
            table_active = False
            separator_seen = False
            continue
        cells = _pipe_cells(line)
        if not table_active:
            if cells == REF01_HEADER:
                table_active = True
                separator_seen = False
            continue
        if cells is None:
            if not separator_seen or line.lstrip().startswith("|"):
                raise ValueError(f"REF-01 explanation table is malformed at line {line_number}")
            table_active = False
            separator_seen = False
            continue
        if not separator_seen:
            if len(cells) != len(REF01_HEADER) or not _is_table_separator(cells):
                raise ValueError(
                    f"REF-01 explanation table has an invalid separator at line {line_number}"
                )
            separator_seen = True
            continue
        if len(cells) != len(REF01_HEADER):
            raise ValueError(
                f"REF-01 explanation row has {len(cells)} columns at line {line_number}"
            )
        if not all(cell for cell in cells):
            raise ValueError(f"REF-01 explanation row has a blank cell at line {line_number}")
        base_sha, identity, change_kind, rationale, consumer_audit, rollback = cells
        if not _FULL_OBJECT_ID.fullmatch(base_sha):
            raise ValueError(
                f"REF-01 explanation base_sha is not a full object id at line {line_number}"
            )
        if change_kind not in EXPLANATION_KINDS:
            raise ValueError(
                f"REF-01 explanation has an unsupported change_kind at line {line_number}"
            )
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", identity):
            raise ValueError(f"REF-01 explanation identity is invalid at line {line_number}")
        rows.append(
            Ref01ExplanationRow(
                base_sha=base_sha,
                identity=identity,
                change_kind=change_kind,
                rationale=rationale,
                consumer_audit=consumer_audit,
                compatibility_or_rollback=rollback,
            )
        )
    return tuple(rows)


def validate_delta_explanations(
    deltas: tuple[ModelDelta, ...],
    *,
    base_sha: str,
    markdown_by_path: Mapping[str, str],
    changed_plan_paths: frozenset[str],
) -> list[str]:
    """Require one exact REF-01 plan explanation for every semantic delta."""

    problems: list[str] = []
    expected = {
        (base_sha, delta.identity, delta.kind)
        for delta in deltas
        if delta.kind in EXPLANATION_KINDS
    }
    found: dict[tuple[str, str, str], Ref01ExplanationRow] = {}
    for path in sorted(changed_plan_paths):
        if not path.startswith("docs/plans/") or not path.endswith(".md"):
            problems.append(f"explanation source is outside docs/plans: {path}")
            continue
        markdown = markdown_by_path.get(path)
        if markdown is None:
            problems.append(f"changed plan document is unavailable at HEAD: {path}")
            continue
        try:
            rows = parse_ref01_explanation_rows(markdown)
        except ValueError as exc:
            problems.append(f"invalid REF-01 explanations in {path}: {exc}")
            continue
        for row in rows:
            if row.base_sha != base_sha:
                continue
            key = (row.base_sha, row.identity, row.change_kind)
            if key in found:
                problems.append(
                    f"duplicate current-base explanation: {row.identity} {row.change_kind}"
                )
                continue
            found[key] = row
            if key not in expected:
                problems.append(
                    f"unused current-base explanation: {row.identity} {row.change_kind}"
                )
            audit_text = row.consumer_audit.casefold()
            if row.change_kind.startswith("deleted_") and (
                not audit_text
                or any(
                    re.search(rf"\b{re.escape(marker)}\b", audit_text)
                    for marker in UNKNOWN_AUDIT_VALUES - {""}
                )
            ):
                problems.append(f"deleted model has unknown consumer audit: {row.identity}")
    for key in sorted(expected - found.keys()):
        _, identity, change_kind = key
        problems.append(f"missing REF-01 explanation: {identity} {change_kind}")
    return problems


def _is_migration_path(path: str) -> bool:
    return "migrations" in PurePosixPath(path).parts


def _tracked_text_reference_matches(
    *,
    git_executable: str,
    repository_root: Path,
    head_sha: str,
    pattern: str,
) -> tuple[str, ...]:

    pathspecs = [
        ":(glob)**/*.py",
        ":(glob)**/*.sql",
        ":(glob)**/*.json",
        ":(glob)**/*.yaml",
        ":(glob)**/*.yml",
        ":(glob)**/*.toml",
        ":(glob)**/*.js",
        ":(glob)**/*.ts",
        ":(glob)**/*.tsx",
        ":(glob)**/*.html",
    ]
    result = subprocess.run(
        [
            git_executable,
            "-C",
            str(repository_root),
            "grep",
            "--fixed-strings",
            "--word-regexp",
            "--line-number",
            "--no-color",
            "-e",
            pattern,
            head_sha,
            "--",
            *pathspecs,
            ":(exclude,glob)**/migrations/**",
            ":(exclude)governance/data_dictionary.json",
            ":(exclude)docs/architecture/DATA_DICTIONARY.md",
            ":(exclude,glob)docs/plans/**",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode == 1:
        return ()
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git grep failed while checking deleted-model consumers: {stderr}")
    lines = result.stdout.decode("utf-8", errors="replace").splitlines()
    matches: list[str] = []
    for line in lines:
        # A revision-scoped grep emits OID:path:line:content. Retain locations
        # only: matched SQL/config lines may contain unrelated sensitive data.
        parts = line.split(":", 3)
        if len(parts) < 3:
            continue
        _, path, line_number = parts[:3]
        if (
            _is_migration_path(path)
            or path
            in {
                "governance/data_dictionary.json",
                "docs/architecture/DATA_DICTIONARY.md",
            }
            or path.startswith("docs/plans/")
        ):
            continue
        matches.append(f"{path}:{line_number}")
    return tuple(matches)


def validate_deleted_model_consumers(
    deltas: tuple[ModelDelta, ...],
    *,
    git_executable: str,
    repository_root: Path,
    head_sha: str,
) -> list[str]:
    """Block deleted declarations still referenced by tracked non-migration code."""

    problems: list[str] = []
    for delta in deltas:
        if delta.kind not in {"deleted_concrete", "deleted_abstract"}:
            continue
        before_table = _declared_table(delta.before)
        patterns = [delta.class_name]
        if before_table is not None:
            patterns.append(before_table)
        for pattern in patterns:
            try:
                matches = _tracked_text_reference_matches(
                    git_executable=git_executable,
                    repository_root=repository_root,
                    head_sha=head_sha,
                    pattern=pattern,
                )
            except ValueError as exc:
                problems.append(f"{delta.identity}: {exc}")
                continue
            if matches:
                problems.append(
                    f"deleted model {delta.identity} still has tracked references "
                    f"for {pattern!r}: " + "; ".join(matches[:5])
                )
    return problems


def _run_git(repository_root: Path, arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        capture_output=True,
        check=False,
    )


def _resolve_exact_commit(repository_root: Path, supplied: str) -> str:
    if not _FULL_OBJECT_ID.fullmatch(supplied):
        raise ValueError("base/head refs must be full lowercase Git object ids")
    result = _run_git(
        repository_root,
        ["rev-parse", "--verify", "--end-of-options", f"{supplied}^{{commit}}"],
    )
    if result.returncode != 0:
        raise ValueError(f"Git object is not an available commit: {supplied}")
    resolved = result.stdout.decode("ascii", errors="strict").strip()
    if resolved != supplied:
        raise ValueError(f"Git ref did not resolve to the exact supplied object id: {supplied}")
    return resolved


def _repository_relative_path(path: Path, repository_root: Path) -> str:
    try:
        relative = path.resolve().relative_to(repository_root.resolve())
    except ValueError as exc:
        raise ValueError(f"path is outside repository: {path}") from exc
    return relative.as_posix()


def _git_show(repository_root: Path, revision: str, path: str) -> bytes:
    result = _run_git(repository_root, ["show", f"{revision}:{path}"])
    if result.returncode != 0:
        raise ValueError(f"required file is missing from {revision}: {path}")
    return result.stdout


def _materialize_apps_tree(repository_root: Path, revision: str, destination: Path) -> Path:
    result = _run_git(repository_root, ["archive", "--format=tar", revision, "apps"])
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"could not archive apps/ from {revision}: {stderr}")
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
            for member in archive:
                raw_parts = member.name.rstrip("/").split("/")
                member_path = PurePosixPath(member.name)
                if (
                    member.name.startswith("/")
                    or "\\" in member.name
                    or member_path.is_absolute()
                    or not member_path.parts
                    or member_path.parts[0] != "apps"
                    or any(part in {"", ".", ".."} for part in member_path.parts)
                    or any(part in {"", ".", ".."} for part in raw_parts)
                ):
                    raise ValueError(f"unsafe path in Git archive: {member.name}")
                if member_path.suffix != ".py":
                    continue
                if not member.isfile():
                    raise ValueError(f"non-regular Python file in model tree: {member.name}")
                target = destination.joinpath(*member_path.parts)
                resolved_target = target.resolve()
                try:
                    resolved_target.relative_to(root)
                except ValueError as exc:
                    raise ValueError(f"unsafe path in Git archive: {member.name}") from exc
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"could not read Python file from Git archive: {member.name}")
                target.write_bytes(source.read())
    except tarfile.TarError as exc:
        raise ValueError(f"invalid Git archive for {revision}: {exc}") from exc
    apps_root = destination / "apps"
    if not apps_root.is_dir():
        raise ValueError(f"apps/ is missing from commit {revision}")
    return apps_root


def _verify_commit_projection(
    repository_root: Path,
    revision: str,
    json_path: str,
    markdown_path: str,
    temporary_root: Path,
) -> dict[str, object]:

    stored_json = _git_show(repository_root, revision, json_path)
    stored_markdown_bytes = _git_show(repository_root, revision, markdown_path)
    try:
        stored_markdown = stored_markdown_bytes.decode("utf-8", errors="strict")
        stored_json_text = stored_json.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid data-dictionary projection in {revision}: {exc}") from exc

    apps_root = _materialize_apps_tree(
        repository_root,
        revision,
        temporary_root / revision,
    )
    rebuilt = build_data_dictionary(apps_root=apps_root)
    expected_json = _canonical_json(rebuilt)
    expected_markdown = render_markdown(rebuilt)
    if stored_json_text != expected_json:
        raise ValueError(f"data-dictionary JSON projection is stale in {revision}: {json_path}")
    if stored_markdown != expected_markdown:
        raise ValueError(
            f"data-dictionary Markdown projection is stale in {revision}: {markdown_path}"
        )
    return rebuilt


def _changed_existing_plan_docs(
    repository_root: Path, base_sha: str, head_sha: str
) -> tuple[str, ...]:
    result = _run_git(
        repository_root,
        [
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            "--diff-filter=M",
            base_sha,
            head_sha,
            "--",
            "docs/plans",
        ],
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"could not identify changed plan documents: {stderr}")
    paths = result.stdout.decode("utf-8", errors="strict").split("\x00")
    existing: list[str] = []
    for path in paths:
        if not path or not path.endswith(".md") or not path.startswith("docs/plans/"):
            continue
        try:
            _git_show(repository_root, base_sha, path)
            _git_show(repository_root, head_sha, path)
        except ValueError:
            continue
        existing.append(path)
    return tuple(sorted(set(existing)))


def _validate_delta_refs(repository_root: Path, base_ref: str, head_ref: str) -> tuple[str, str]:
    base_sha = _resolve_exact_commit(repository_root, base_ref)
    head_sha = _resolve_exact_commit(repository_root, head_ref)
    if base_sha == head_sha:
        raise ValueError("base-ref and head-ref must name distinct commits")
    current = _run_git(repository_root, ["rev-parse", "--verify", "HEAD^{commit}"])
    if current.returncode != 0:
        raise ValueError("could not resolve the checked-out HEAD commit")
    current_sha = current.stdout.decode("ascii", errors="strict").strip()
    if current_sha != head_sha:
        raise ValueError("head-ref must equal the checked-out HEAD commit")
    return base_sha, head_sha


def run_model_delta_check(
    *,
    repository_root: Path,
    base_ref: str,
    head_ref: str,
    json_path: Path,
    markdown_path: Path,
    plan_file: Path | None,
) -> int:
    """Validate exact commit projections, model deltas and plan explanations."""

    try:
        base_sha, head_sha = _validate_delta_refs(repository_root, base_ref, head_ref)
        json_relative = _repository_relative_path(json_path, repository_root)
        markdown_relative = _repository_relative_path(markdown_path, repository_root)
        plan_relative: str | None = None
        if plan_file is not None:
            plan_relative = plan_file.as_posix()
            if plan_file.is_absolute() or ".." in plan_file.parts:
                raise ValueError("--plan-file must be a repository-relative path without '..'")
            if not plan_relative.startswith("docs/plans/") or not plan_relative.endswith(".md"):
                raise ValueError("--plan-file must point to an existing docs/plans/*.md file")
            _git_show(repository_root, base_sha, plan_relative)
            _git_show(repository_root, head_sha, plan_relative)
        head_builder = _git_show(repository_root, head_sha, "scripts/build_data_dictionary.py")
        checked_out_builder_path = Path(__file__).resolve().parent / "build_data_dictionary.py"
        try:
            checked_out_builder = checked_out_builder_path.read_bytes()
        except OSError as exc:
            raise ValueError(
                "could not read the checked-out data-dictionary builder: "
                f"{checked_out_builder_path} ({exc})"
            ) from exc
        # Git text checkouts may use CRLF on Windows while commit blobs use LF.
        # Ignore only that checkout conversion; local code shadows still fail.
        if head_builder.replace(b"\r\n", b"\n") != checked_out_builder.replace(b"\r\n", b"\n"):
            raise ValueError("checked-out data-dictionary builder does not match the head ref")

        with tempfile.TemporaryDirectory(prefix="data-dictionary-delta-") as temp_name:
            temporary_root = Path(temp_name)
            base_payload = _verify_commit_projection(
                repository_root,
                base_sha,
                json_relative,
                markdown_relative,
                temporary_root,
            )
            head_payload = _verify_commit_projection(
                repository_root,
                head_sha,
                json_relative,
                markdown_relative,
                temporary_root,
            )
        deltas = compare_model_projections(base_payload, head_payload)
        changed_plan_paths = _changed_existing_plan_docs(repository_root, base_sha, head_sha)
        if plan_relative is not None:
            changed_plan_paths = tuple(path for path in changed_plan_paths if path == plan_relative)
        markdown_by_path: dict[str, str] = {}
        for path in changed_plan_paths:
            try:
                markdown_by_path[path] = _git_show(repository_root, head_sha, path).decode(
                    "utf-8", errors="strict"
                )
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError(f"could not read changed plan file {path}: {exc}") from exc
        explanation_problems = validate_delta_explanations(
            deltas,
            base_sha=base_sha,
            markdown_by_path=markdown_by_path,
            changed_plan_paths=frozenset(changed_plan_paths),
        )
        deletion_problems = validate_deleted_model_consumers(
            deltas,
            git_executable="git",
            repository_root=repository_root,
            head_sha=head_sha,
        )
        unprojected_problems = validate_unprojected_new_model_declarations(
            base_payload,
            head_payload,
            git_executable="git",
            repository_root=repository_root,
            base_sha=base_sha,
            head_sha=head_sha,
        )
        problems = explanation_problems + deletion_problems + unprojected_problems
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"model delta check failed: {exc}")
        return 1

    if problems:
        for problem in problems:
            print(f"INVALID {problem}")
        return 1
    semantic_deltas = [delta for delta in deltas if delta.kind != "file_move"]
    print(
        "model delta OK: "
        f"base={base_sha} head={head_sha} total={len(deltas)} "
        f"semantic={len(semantic_deltas)} file_moves={len(deltas) - len(semantic_deltas)}; "
        "direct AST declarations only (inherited fields and physical database state unknown)"
    )
    for delta in deltas:
        facets = ",".join(delta.facets) or "none"
        table = _declared_table(delta.after or delta.before)
        table_state = (
            f"declared_db_table={table}" if table is not None else "declared_db_table=unknown"
        )
        print(f"- {delta.identity} {delta.kind} facets={facets} {table_state}")
    return 0
