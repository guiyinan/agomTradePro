#!/usr/bin/env python
"""Build a generated, machine-readable ORM data dictionary.

The data dictionary is a *projection* of the Django model layer: it is fully
derived by static AST scanning (stdlib ``ast`` only, no Django import, no
database) and must never be edited by hand.  Regenerate with::

    python scripts/build_data_dictionary.py

Determinism contract: the output contains no timestamps and no git hashes,
all keys are sorted by ``json.dumps(..., indent=2, sort_keys=True)`` plus a
trailing newline, and field lists follow source order, so byte-identical
regeneration is expected on an unchanged tree.

Scope and extraction semantics:

- Only first-level module directories under ``apps/`` are scanned (same
  heuristic as ``scripts/build_module_map.py``).  ``__pycache__`` and
  ``migrations`` are excluded everywhere.
- Model source files are ``infrastructure/models.py``, any ``*.py`` inside an
  ``infrastructure/models/`` package, and ``infrastructure/*_models.py``
  (this repository splits large model layers into per-topic ``*_models.py``
  files re-exported by ``models.py``).
- Model classes are module-level ``ClassDef`` nodes whose bases look like
  Django models (final identifier exactly ``"Model"`` or ending with
  ``"Model"``, excluding the non-model base names used by the module map).
- Fields are class-level assignments whose right-hand side is a call whose
  function's final identifier ends with ``"Field"`` or is ``"ForeignKey"``.
  ``positional_args`` keep the ``ast.unparse`` source text (a ForeignKey's
  first argument is its target model); ``kwargs`` values use the Python
  literal when ``ast.literal_eval`` succeeds, otherwise the ``ast.unparse``
  source text (covers ``default=timezone.now`` and ``_(...)`` wrapping).
  ``null``/``unique``/``db_index`` convenience flags appear only when the
  keyword is written explicitly.
- An inner ``class Meta`` contributes the ``meta`` mapping (literal values
  when possible, source text otherwise); ``abstract = True`` additionally
  sets the model-level ``abstract`` flag.
- Inner ``TextChoices``/``IntegerChoices`` classes are recorded under
  ``choices_classes`` as member-name -> value mappings.

Known limitations (deliberate, keep the scanner stdlib-only):

- Inherited fields are not expanded: each model lists only the fields
  assigned in its own class body; mixins and abstract base classes appear as
  their own entries.
- Dynamically contributed fields (``add_to_class``, ``contribute_to_class``,
  metaclass injection) and Django's implicit auto primary key are invisible
  to AST scanning and therefore absent.
- Apps without any extracted model are omitted from the projection.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS_ROOT = ROOT / "apps"
DEFAULT_OUTPUT = ROOT / "governance" / "data_dictionary.json"
DEFAULT_MARKDOWN_OUTPUT = ROOT / "docs" / "architecture" / "DATA_DICTIONARY.md"
SCHEMA_VERSION = "1.0"
GENERATED_BY = "scripts/build_data_dictionary.py"
PROJECTION_NOTICE = (
    "GENERATED PROJECTION of the Django ORM model layer. "
    "Do not edit by hand; run: python scripts/build_data_dictionary.py"
)
EXCLUDED_PARTS = frozenset({"__pycache__", "migrations"})
NON_MODEL_BASE_NAMES = frozenset({"ABC", "ABCMeta", "Protocol", "Generic", "TypedDict"})
RELATION_FIELD_TYPES = frozenset({"ForeignKey", "OneToOneField", "ManyToManyField"})
BOOLEAN_FLAG_KWARGS = ("null", "unique", "db_index")

ModelRecord = dict[str, object]
FieldRecord = dict[str, object]
AppRecord = dict[str, object]


def _iter_module_dirs(apps_root: Path) -> list[Path]:
    """Return immediate subdirectories of ``apps/`` that contain Python files."""

    modules: list[Path] = []
    for candidate in sorted(apps_root.iterdir()):
        if not candidate.is_dir() or candidate.name == "__pycache__":
            continue
        if any(True for _ in _iter_python_files(candidate)):
            modules.append(candidate)
    return modules


def _iter_python_files(module_dir: Path) -> Iterable[Path]:
    """Yield deterministic Python files under a module, excluding caches."""

    yield from sorted(
        path
        for path in module_dir.rglob("*.py")
        if not EXCLUDED_PARTS.intersection(path.relative_to(module_dir).parts)
    )


def _parse_tree(path: Path, relative: str) -> ast.Module | None:
    """Parse a Python file, returning ``None`` on syntax errors."""

    text = path.read_text(encoding="utf-8", errors="ignore")
    try:
        return ast.parse(text, filename=relative)
    except SyntaxError:
        return None


def _dotted_name(node: ast.AST) -> str | None:
    """Return a dotted name for a simple Name/Attribute expression."""

    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _is_model_base(base: ast.AST) -> bool:
    """Heuristic: base expression looks like a Django model base class."""

    dotted = _dotted_name(base)
    if dotted is None:
        return False
    final = dotted.rsplit(".", 1)[-1]
    if final in NON_MODEL_BASE_NAMES:
        return False
    return final == "Model" or final.endswith("Model")


def _is_choices_base(base: ast.AST) -> bool:
    """Heuristic: base expression looks like a Django choices enumeration."""

    dotted = _dotted_name(base)
    if dotted is None:
        return False
    return dotted.rsplit(".", 1)[-1] in {"TextChoices", "IntegerChoices"}


def _is_model_file(relative: str) -> bool:
    """Return whether an app-relative path is a model source file."""

    parts = Path(relative).parts
    if len(parts) < 2 or parts[0] != "infrastructure":
        return False
    filename = parts[-1]
    if len(parts) == 2:
        return filename == "models.py" or filename.endswith("_models.py")
    return len(parts) == 3 and parts[1] == "models"


def _json_safe(value: object) -> object:
    """Normalize a literal value into JSON-stable containers (tuples to lists)."""

    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _value_repr(node: ast.AST) -> object:
    """Return the literal value when possible, else the ``ast.unparse`` text."""

    try:
        return _json_safe(ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return ast.unparse(node)


def _extract_field(name: str, call: ast.Call) -> FieldRecord | None:
    """Build a field record from a ``name = <Field>(...)`` assignment."""

    dotted = _dotted_name(call.func)
    if dotted is None:
        return None
    field_type = dotted.rsplit(".", 1)[-1]
    if not (field_type.endswith("Field") or field_type == "ForeignKey"):
        return None
    kwargs: dict[str, object] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            kwargs["**"] = ast.unparse(keyword.value)
        else:
            kwargs[keyword.arg] = _value_repr(keyword.value)
    record: FieldRecord = {
        "name": name,
        "field_type": field_type,
        "positional_args": [ast.unparse(arg) for arg in call.args],
    }
    if kwargs:
        record["kwargs"] = kwargs
        for flag in BOOLEAN_FLAG_KWARGS:
            if flag in kwargs:
                record[flag] = kwargs[flag]
    return record


def _extract_meta(meta_class: ast.ClassDef) -> dict[str, object]:
    """Build the ``meta`` mapping from an inner ``class Meta`` body."""

    meta: dict[str, object] = {}
    for statement in meta_class.body:
        target: str | None = None
        value_node: ast.AST | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target_node = statement.targets[0]
            if isinstance(target_node, ast.Name):
                target = target_node.id
                value_node = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            target = statement.target.id
            value_node = statement.value
        if target is not None and value_node is not None:
            meta[target] = _value_repr(value_node)
    return meta


def _extract_choices(choices_class: ast.ClassDef) -> dict[str, object]:
    """Build the member mapping of an inner TextChoices/IntegerChoices class."""

    members: dict[str, object] = {}
    for statement in choices_class.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            members[statement.targets[0].id] = _value_repr(statement.value)
    return members


def _extract_model(node: ast.ClassDef, source_file: str) -> ModelRecord:
    """Build a model record from a module-level model ``ClassDef``."""

    record: ModelRecord = {
        "class_name": node.name,
        "source_file": source_file,
        "bases": [dotted for base in node.bases if (dotted := _dotted_name(base)) is not None],
    }
    docstring = ast.get_docstring(node)
    if docstring:
        record["docstring"] = docstring.splitlines()[0]

    fields: list[FieldRecord] = []
    choices_classes: dict[str, dict[str, object]] = {}
    for statement in node.body:
        if isinstance(statement, ast.ClassDef):
            if statement.name == "Meta":
                meta = _extract_meta(statement)
                if meta:
                    record["meta"] = meta
                if meta.get("abstract") is True:
                    record["abstract"] = True
            elif any(_is_choices_base(base) for base in statement.bases):
                members = _extract_choices(statement)
                if members:
                    choices_classes[statement.name] = members
            continue
        target: str | None = None
        value_node: ast.AST | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target_node = statement.targets[0]
            if isinstance(target_node, ast.Name):
                target = target_node.id
                value_node = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            target = statement.target.id
            value_node = statement.value
        if target is None or not isinstance(value_node, ast.Call):
            continue
        field = _extract_field(target, value_node)
        if field is not None:
            fields.append(field)

    if fields:
        record["fields"] = fields
    if choices_classes:
        record["choices_classes"] = choices_classes
    return record


def build_data_dictionary(apps_root: Path = APPS_ROOT) -> dict[str, object]:
    """Scan ``apps/`` and return the deterministic data dictionary payload."""

    apps: dict[str, AppRecord] = {}
    for module_dir in _iter_module_dirs(apps_root):
        models: list[ModelRecord] = []
        for path in _iter_python_files(module_dir):
            relative = path.relative_to(module_dir).as_posix()
            if not _is_model_file(relative):
                continue
            tree = _parse_tree(path, relative)
            if tree is None:
                continue
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and any(
                    _is_model_base(base) for base in node.bases
                ):
                    models.append(_extract_model(node, relative))
        if models:
            models.sort(key=lambda item: (str(item["source_file"]), str(item["class_name"])))
            apps[module_dir.name] = {"models": models}

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATED_BY,
        "projection_notice": PROJECTION_NOTICE,
        "apps": apps,
    }


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _cell(text: object) -> str:
    """Render a markdown table cell, escaping pipes and collapsing newlines."""

    return str(text).replace("|", "\\|").replace("\n", " ")


def _display_text(value: object) -> str:
    """Render a kwargs value for display, unquoting plain string literals."""

    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        try:
            evaluated = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return value
        if isinstance(evaluated, str):
            return evaluated
    return str(value)


def _field_description(field: FieldRecord) -> str:
    """Return the human-facing description of a field (help_text preferred)."""

    kwargs = field.get("kwargs", {})
    if not isinstance(kwargs, dict):
        return ""
    for key in ("help_text", "verbose_name"):
        if key in kwargs:
            return _display_text(kwargs[key])
    positional = field.get("positional_args", [])
    if isinstance(positional, list) and positional:
        first = positional[0]
        if isinstance(first, str) and len(first) >= 2 and first[0] in "'\"":
            try:
                evaluated = ast.literal_eval(first)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                return ""
            if isinstance(evaluated, str):
                return evaluated
    return ""


def _field_relation_target(field: FieldRecord) -> str:
    """Return the relation target model for relationship fields, else empty."""

    if field.get("field_type") not in RELATION_FIELD_TYPES:
        return ""
    positional = field.get("positional_args", [])
    if isinstance(positional, list) and positional:
        return _display_text(positional[0])
    return ""


def _field_default(field: FieldRecord) -> str:
    """Return the rendered default value of a field, else empty."""

    kwargs = field.get("kwargs", {})
    if isinstance(kwargs, dict) and "default" in kwargs:
        return str(kwargs["default"])
    return ""


def render_markdown(payload: dict[str, object]) -> str:
    """Render the human-readable data dictionary markdown from the payload."""

    apps = payload.get("apps", {})
    if not isinstance(apps, dict):
        apps = {}
    app_count = len(apps)
    model_count = 0
    field_count = 0
    for app_record in apps.values():
        if not isinstance(app_record, dict):
            continue
        models = app_record.get("models", [])
        if not isinstance(models, list):
            continue
        model_count += len(models)
        for model in models:
            if isinstance(model, dict) and isinstance(model.get("fields"), list):
                field_count += len(model["fields"])

    lines = [
        "# 数据字典（Data Dictionary）",
        "",
        (
            f"> 本文件由 `python {GENERATED_BY}` 自动生成，禁止手工编辑。"
            " 模型变更后请重新运行该命令，并通过 `python scripts/check_data_dictionary.py` 校验。"
        ),
        "",
        "本文档是 `governance/data_dictionary.json` 的人读渲染，"
        "两者由同一份扫描数据生成，禁止单独维护。",
        "",
        "## 概览",
        "",
        f"- App 数：{app_count}",
        f"- 模型数：{model_count}",
        f"- 字段数：{field_count}",
        "",
        "口径说明：仅覆盖 `apps/*/infrastructure/` 下的 `models.py`、`models/` 包与 "
        "`*_models.py`；字段为类体内显式赋值的 Django 字段，继承字段不展开，"
        "动态字段与隐式自增主键不在投影内。",
    ]

    for app_name in sorted(apps):
        app_record = apps[app_name]
        if not isinstance(app_record, dict):
            continue
        models = app_record.get("models", [])
        if not isinstance(models, list):
            continue
        lines.extend(["", f"## {app_name}", ""])
        for model in models:
            if not isinstance(model, dict):
                continue
            class_name = str(model.get("class_name", ""))
            lines.append(f"### {class_name}")
            lines.append("")
            lines.append(f"- 来源文件：`apps/{app_name}/{model.get('source_file', '')}`")
            meta = model.get("meta", {})
            if isinstance(meta, dict) and "db_table" in meta:
                lines.append(f"- 数据表：`{meta['db_table']}`")
            if model.get("abstract") is True:
                lines.append("- 抽象模型：是")
            docstring = model.get("docstring")
            if isinstance(docstring, str) and docstring:
                lines.append(f"- 说明：{docstring}")
            lines.append("")
            fields = model.get("fields", [])
            if isinstance(fields, list) and fields:
                lines.append("| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |")
                lines.append("| --- | --- | --- | --- | --- | --- | --- |")
                for field in fields:
                    if not isinstance(field, dict):
                        continue
                    null_flag = "是" if field.get("null") is True else ""
                    unique_flag = "是" if field.get("unique") is True else ""
                    lines.append(
                        "| "
                        + " | ".join(
                            [
                                f"`{_cell(field.get('name', ''))}`",
                                f"`{_cell(field.get('field_type', ''))}`",
                                null_flag,
                                unique_flag,
                                _cell(_field_default(field)),
                                _cell(_field_description(field)),
                                _cell(_field_relation_target(field)),
                            ]
                        )
                        + " |"
                    )
                lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main() -> int:
    """Build the data dictionary, write JSON and Markdown, print a summary."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="data dictionary JSON output path",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_OUTPUT,
        help="data dictionary Markdown output path",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print the rendered JSON to stdout instead of writing files",
    )
    args = parser.parse_args()

    payload = build_data_dictionary()
    rendered = _canonical_json(payload)
    if args.stdout:
        sys.stdout.write(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(payload), encoding="utf-8", newline="\n")
    apps = payload["apps"]
    app_count = len(apps) if isinstance(apps, dict) else 0
    model_count = 0
    field_count = 0
    if isinstance(apps, dict):
        for app_record in apps.values():
            if not isinstance(app_record, dict):
                continue
            models = app_record.get("models", [])
            if not isinstance(models, list):
                continue
            model_count += len(models)
            for model in models:
                if isinstance(model, dict) and isinstance(model.get("fields"), list):
                    field_count += len(model["fields"])
    print(f"data dictionary OK: apps={app_count} models={model_count} fields={field_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
