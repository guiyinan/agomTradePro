"""Build the deterministic inventory of every Data Center invocation surface.

The scanner is deliberately static.  It parses Python/JSON sources and reuses
existing governance manifests without importing Django, opening a database, or
executing provider code.  Discovery and governance state are separate:
unrecognised surfaces are retained as ``candidate-review`` instead of being
silently treated as approved entrypoints.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from collections.abc import Iterable
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "governance" / "data_center_entrypoints.json"
STATUSES = frozenset({"active_public", "compatibility", "adjacent_operational", "candidate-review"})
REQUIRED_CATEGORIES = frozenset(
    {
        "admin_surface",
        "application_consumer",
        "script",
        "management_command",
        "management_command_edge",
        "celery_task",
        "beat_schedule",
        "current_data_surface",
        "rest_url",
        "sdk",
        "mcp_tool",
        "orchestration_entry",
        "terminal_tui",
        "capability_runtime",
        "public_port",
        "compatibility_facade",
        "runtime_config_key",
        "scheduler_writer",
        "system_settings_compatibility",
    }
)
COMPATIBILITY_FACADES = (
    "apps/data_center/application/interface_services.py",
    "apps/data_center/application/query_services.py",
    "apps/data_center/application/read_facade.py",
)
GOVERNANCE_SCRIPT_ENTRYPOINTS = frozenset(
    {
        "scripts/check_data_center_runtime_catalog.py",
        "scripts/measure_data_center_query_ports.py",
    }
)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {_relative(path)}")
    return payload


@cache
def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=_relative(path))


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _dotted_attribute(node: ast.AST) -> str | None:
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


def _function_symbol(node: ast.FunctionDef | ast.AsyncFunctionDef, tree: ast.Module) -> str:
    for parent in ast.walk(tree):
        if isinstance(parent, ast.ClassDef) and node in parent.body:
            return f"{parent.name}.{node.name}"
    return node.name


def _functions(tree: ast.Module) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
    return (
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _production_python_files(*roots: str) -> Iterable[Path]:
    """Yield production Python files below the requested repository roots."""

    for root_name in roots:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if any(part in {"migrations", "tests", "__pycache__"} for part in path.parts):
                continue
            yield path


def _entry(
    *,
    category: str,
    path: str,
    symbol: str,
    status: str,
    evidence: str,
    locator: str = "",
    target: str = "",
) -> dict[str, object]:
    if status not in STATUSES:
        raise ValueError(f"unsupported entrypoint status: {status}")
    return {
        "id": f"{category}:{path}:{symbol}:{locator}",
        "category": category,
        "path": path,
        "symbol": symbol,
        "locator": locator,
        "target": target,
        "status": status,
        "evidence": evidence,
    }


def _discover_scripts(legacy: dict[str, Any]) -> list[dict[str, object]]:
    entries = [
        *legacy.get("entrypoints", []),
        *legacy.get("wrappers", []),
    ]
    legacy_paths = {
        str(item.get("path")) for item in entries if isinstance(item, dict) and item.get("path")
    }
    results: list[dict[str, object]] = []
    own_path = "scripts/data_center_entrypoint_inventory.py"
    for path in sorted((ROOT / "scripts").rglob("*.py")):
        path_text = _relative(path)
        if path_text == own_path or "__pycache__" in path.parts:
            continue
        tree = _tree(path)
        imports_data_center = any(
            (
                isinstance(node, ast.Import)
                and any(alias.name.startswith("apps.data_center") for alias in node.names)
            )
            or (
                isinstance(node, ast.ImportFrom)
                and bool(node.module)
                and str(node.module).startswith("apps.data_center")
            )
            for node in ast.walk(tree)
        )
        invokes_data_center_http = any(
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "/api/data-center" in node.value
            for node in ast.walk(tree)
        )
        if (
            not imports_data_center
            and not invokes_data_center_http
            and path_text not in legacy_paths
        ):
            continue
        registered = path_text in legacy_paths
        governed_tool = path_text in GOVERNANCE_SCRIPT_ENTRYPOINTS
        results.append(
            _entry(
                category="script",
                path=path_text,
                symbol="__main__",
                status=(
                    "compatibility"
                    if registered
                    else "active_public" if governed_tool else "candidate-review"
                ),
                evidence=(
                    "governance/data_center_legacy_entrypoints.json"
                    if registered
                    else (
                        "Data Center governance/measurement tooling"
                        if governed_tool
                        else "static Data Center reference; explicit owner review required"
                    )
                ),
            )
        )
    return results


def _discover_management_commands() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for path in sorted(ROOT.rglob("*.py")):
        path_parts = path.relative_to(ROOT).parts
        if "management" not in path_parts or "commands" not in path_parts:
            continue
        if any(part in {".venv", "node_modules", "__pycache__"} for part in path.parts):
            continue
        if path.name == "__init__.py":
            continue
        path_text = _relative(path)
        text = path.read_text(encoding="utf-8", errors="ignore")
        owned = path_text.startswith("apps/data_center/")
        if not owned and "apps.data_center" not in text:
            continue
        internal = "apps.data_center.infrastructure" in text
        status = "active_public" if owned else "compatibility"
        if not owned and internal:
            status = "candidate-review"
        results.append(
            _entry(
                category="management_command",
                path=path_text,
                symbol=path.stem,
                status=status,
                evidence=(
                    "Data Center-owned Django command"
                    if owned
                    else "cross-app command consumer of Data Center"
                ),
            )
        )
    return results


def _module_string_collections(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """Return module-level string collections used by orchestration loops."""

    collections: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, (ast.List, ast.Set, ast.Tuple)):
            continue
        items = tuple(
            literal for item in value.elts if (literal := _literal_string(item)) is not None
        )
        if len(items) != len(value.elts):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                collections[target.id] = items
    return collections


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Return module-level scalar strings used by compatibility delegates."""

    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = _literal_string(node.value)
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value
    return constants


def _dictionary_command_values(tree: ast.Module) -> tuple[str, ...]:
    """Return literal ``command`` values from declarative orchestration plans."""

    values: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if _literal_string(key) != "command":
                continue
            literal = _literal_string(value)
            if literal is not None:
                values.add(literal)
    return tuple(sorted(values))


def _enclosing_function_name(tree: ast.Module, call: ast.Call) -> str:
    """Return the nearest function containing ``call`` for wrapper detection."""

    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(child is call for child in ast.walk(node))
    ]
    if not candidates:
        return ""
    return min(candidates, key=lambda node: len(tuple(ast.walk(node)))).name


def _enclosing_loop_values(
    tree: ast.Module,
    call: ast.Call,
    argument_name: str,
    collections: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """Resolve a call argument populated by a surrounding static ``for`` loop."""

    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != argument_name:
            continue
        if not any(child is call for child in ast.walk(node)):
            continue
        if isinstance(node.iter, ast.Name):
            return collections.get(node.iter.id, ())
        if isinstance(node.iter, (ast.List, ast.Set, ast.Tuple)):
            values = tuple(
                literal for item in node.iter.elts if (literal := _literal_string(item)) is not None
            )
            if len(values) == len(node.iter.elts):
                return values
    return ()


def _discover_management_command_edges() -> list[dict[str, object]]:
    """Enumerate direct and statically expanded ``call_command`` edges."""

    command_paths = {
        path.stem: _relative(path)
        for path in _production_python_files("apps", "core")
        if "/management/commands/" in f"/{_relative(path)}" and path.name != "__init__.py"
    }
    results: list[dict[str, object]] = []
    for path in _production_python_files("apps", "core", "scripts"):
        tree = _tree(path)
        collections = _module_string_collections(tree)
        constants = _module_string_constants(tree)
        planned_commands = _dictionary_command_values(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in {
                "call_command",
                "_run_command",
            }:
                continue
            targets: tuple[str, ...] = ()
            if node.args:
                literal = _literal_string(node.args[0])
                if literal is not None:
                    targets = (literal,)
                elif isinstance(node.args[0], ast.Name):
                    targets = (
                        (constants[node.args[0].id],)
                        if node.args[0].id in constants
                        else _enclosing_loop_values(
                            tree,
                            node,
                            node.args[0].id,
                            collections,
                        )
                    )
            if not targets:
                if (
                    _call_name(node) == "call_command"
                    and _enclosing_function_name(tree, node) == "_run_command"
                ):
                    continue
                targets = planned_commands or ("dynamic-command",)
            for target in targets:
                target_path = command_paths.get(target, "")
                status = (
                    "active_public"
                    if target_path.startswith("apps/data_center/")
                    or target == "init_scheduler_defaults"
                    else "adjacent_operational"
                )
                results.append(
                    _entry(
                        category="management_command_edge",
                        path=_relative(path),
                        symbol=target,
                        locator=f"line:{node.lineno}",
                        target=target_path or target,
                        status=status,
                        evidence=(
                            f"call_command resolves to {target_path}"
                            if target_path
                            else "call_command target is external or runtime-selected"
                        ),
                    )
                )
    return results


def _discover_application_consumers() -> list[dict[str, object]]:
    """Enumerate every production import of the canonical Application Public Port."""

    module_name = "apps.data_center.application.public"
    results: list[dict[str, object]] = []
    for path in _production_python_files("apps", "core", "shared", "scripts", "sdk"):
        path_text = _relative(path)
        if path_text.startswith("apps/data_center/"):
            continue
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and node.module == module_name:
                for alias in node.names:
                    results.append(
                        _entry(
                            category="application_consumer",
                            path=path_text,
                            symbol=alias.name,
                            locator=f"line:{node.lineno}",
                            status="active_public",
                            evidence="canonical Data Center Application Public Port import",
                        )
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name != module_name:
                        continue
                    results.append(
                        _entry(
                            category="application_consumer",
                            path=path_text,
                            symbol=alias.asname or module_name,
                            locator=f"line:{node.lineno}",
                            status="active_public",
                            evidence="canonical Data Center Application Public Port module import",
                        )
                    )
    return results


def _admin_registration_target(decorator: ast.expr) -> str:
    """Return the model symbol registered by one ``admin.register`` decorator."""

    if not isinstance(decorator, ast.Call) or not decorator.args:
        return ""
    function = decorator.func
    if not isinstance(function, ast.Attribute) or function.attr != "register":
        return ""
    dotted = _dotted_attribute(function.value)
    if dotted not in {"admin", "admin.site", "site"}:
        return ""
    target = decorator.args[0]
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return ast.unparse(target)
    return ""


def _discover_admin_surfaces() -> list[dict[str, object]]:
    """Enumerate human-operated Data/Config Center Django Admin surfaces."""

    legacy_models = {
        "StockInfoModel",
        "StockDailyModel",
        "FinancialDataModel",
        "ValuationModel",
        "FundNetValueModel",
        "SectorConstituentModel",
        "MacroIndicator",
    }
    results: list[dict[str, object]] = []
    for path in _production_python_files("apps", "core"):
        if path.name != "admin.py":
            continue
        path_text = _relative(path)
        tree = _tree(path)
        imported_aliases = {
            alias.asname or alias.name: alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for decorator in node.decorator_list:
                model = _admin_registration_target(decorator)
                if not model:
                    continue
                canonical_model = imported_aliases.get(model, model)
                if path_text.startswith(("apps/data_center/", "apps/config_center/")):
                    status = "active_public"
                elif canonical_model == "SystemSettingsModel":
                    status = "compatibility"
                elif canonical_model in legacy_models:
                    status = "candidate-review"
                else:
                    continue
                results.append(
                    _entry(
                        category="admin_surface",
                        path=path_text,
                        symbol=node.name,
                        locator=canonical_model,
                        status=status,
                        evidence=(
                            "Data/Config Center-owned Django Admin registration"
                            if status == "active_public"
                            else (
                                "legacy SystemSettings compatibility Admin"
                                if status == "compatibility"
                                else "legacy fact model Admin registration must be retired"
                            )
                        ),
                    )
                )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            dotted = _dotted_attribute(node.func)
            if dotted not in {"admin.site.register", "site.register"}:
                continue
            model = ast.unparse(node.args[0])
            canonical_model = imported_aliases.get(model, model)
            if path_text.startswith(("apps/data_center/", "apps/config_center/")):
                status = "active_public"
            elif canonical_model == "SystemSettingsModel":
                status = "compatibility"
            elif canonical_model in legacy_models:
                status = "candidate-review"
            else:
                continue
            results.append(
                _entry(
                    category="admin_surface",
                    path=path_text,
                    symbol="admin.site.register",
                    locator=canonical_model,
                    status=status,
                    evidence="imperative Django Admin registration",
                )
            )
    return results


def _discover_scheduler_writers() -> list[dict[str, object]]:
    """Enumerate every production writer of database-backed Beat schedules."""

    results: list[dict[str, object]] = []
    for path in _production_python_files("apps", "core", "scripts"):
        tree = _tree(path)
        periodic_task_imported = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "django_celery_beat.models"
            and any(alias.name == "PeriodicTask" for alias in node.names)
            for node in ast.walk(tree)
        )
        periodic_task_imported = periodic_task_imported or any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "PeriodicTask"
                for target in node.targets
            )
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "PeriodicTask"
            for node in ast.walk(tree)
        )
        if not periodic_task_imported:
            continue
        writes_periodic_task = any(
            isinstance(node, ast.Call)
            and (_dotted_attribute(node.func) or "").startswith(
                ("PeriodicTask.objects.", "PeriodicTask._default_manager.")
            )
            and (_dotted_attribute(node.func) or "").rsplit(".", 1)[-1]
            in {"bulk_create", "create", "delete", "get_or_create", "update", "update_or_create"}
            for node in ast.walk(tree)
        )
        if not writes_periodic_task:
            continue
        path_text = _relative(path)
        task_paths = sorted(
            {
                str(node.value)
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("apps.")
                and ".application." in node.value
            }
        )
        if not task_paths:
            task_paths = ["dynamic-task-path"]
        for task_path in task_paths:
            results.append(
                _entry(
                    category="scheduler_writer",
                    path=path_text,
                    symbol="PeriodicTask",
                    locator=task_path,
                    target=task_path,
                    status=(
                        "active_public"
                        if "/management/commands/" in f"/{path_text}"
                        else "candidate-review"
                    ),
                    evidence=(
                        "Django management command owns database-backed Beat schedule"
                        if "/management/commands/" in f"/{path_text}"
                        else "ad-hoc database-backed Beat writer must delegate to a command"
                    ),
                )
            )
    return results


def _discover_orchestration_entries() -> list[dict[str, object]]:
    """Enumerate scripts/workflows that invoke governed management commands."""

    data_center_commands = {
        path.stem
        for path in (ROOT / "apps" / "data_center" / "management" / "commands").glob("*.py")
        if path.name != "__init__.py"
    }
    governed_commands = data_center_commands | {"init_scheduler_defaults"}
    command_pattern = re.compile(
        r"manage\.py(?:[\"'`,\]()\s]+)([A-Za-z][A-Za-z0-9_]*)",
        re.IGNORECASE,
    )
    extensions = {".py", ".sh", ".ps1", ".bat", ".yml", ".yaml"}
    roots = (ROOT / "scripts", ROOT / "docker", ROOT / ".github")
    results: list[dict[str, object]] = []
    for source_root in roots:
        if not source_root.exists():
            continue
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in command_pattern.finditer(text):
                command = match.group(1)
                if command not in governed_commands:
                    continue
                line = text.count("\n", 0, match.start()) + 1
                results.append(
                    _entry(
                        category="orchestration_entry",
                        path=_relative(path),
                        symbol=command,
                        locator=f"line:{line}",
                        status="active_public",
                        evidence="script/workflow delegates to a governed Django command",
                    )
                )
    return results


def _discover_runtime_config_keys(runtime_config: dict[str, Any]) -> list[dict[str, object]]:
    """Publish every governed runtime key and its migration lifecycle."""

    active_states = {
        "canonical_only_fail_closed",
        "model-backed",
        "registered",
        "separate_model_active",
    }
    compatibility_states = {
        "consumer_cutover_in_progress",
        "config_center_secret_owner_with_legacy_migration",
    }
    results: list[dict[str, object]] = []
    for item in runtime_config.get("definitions", []):
        if not isinstance(item, dict):
            continue
        config_key = str(item.get("config_key") or "").strip()
        migration_status = str(item.get("migration_status") or "").strip()
        if not config_key:
            continue
        consumers = item.get("consumers")
        consumer_count = len(consumers) if isinstance(consumers, list) else 0
        if migration_status in active_states and consumer_count > 0:
            status = "active_public"
        elif migration_status in compatibility_states:
            status = "compatibility"
        else:
            status = "candidate-review"
        results.append(
            _entry(
                category="runtime_config_key",
                path="governance/runtime_config_contracts.json",
                symbol=config_key,
                locator=migration_status,
                status=status,
                evidence=(
                    f"runtime owner={item.get('owner')}; consumers={consumer_count}; "
                    f"migration_status={migration_status or 'missing'}"
                ),
            )
        )
    return results


def _references_system_settings(tree: ast.Module) -> tuple[int, ...]:
    """Return exact source lines that import or reference ``SystemSettingsModel``."""

    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "SystemSettingsModel":
            lines.add(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "SystemSettingsModel" for alias in node.names):
                lines.add(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == "SystemSettingsModel":
            lines.add(node.lineno)
    return tuple(sorted(lines))


def _discover_system_settings_compatibility() -> list[dict[str, object]]:
    """Enumerate all remaining production references to the legacy singleton."""

    owner_path = "apps/config_center/infrastructure/models.py"
    results: list[dict[str, object]] = []
    for path in _production_python_files("apps", "core", "shared", "scripts"):
        path_text = _relative(path)
        if path_text == owner_path:
            continue
        lines = _references_system_settings(_tree(path))
        if not lines:
            continue
        results.append(
            _entry(
                category="system_settings_compatibility",
                path=path_text,
                symbol="SystemSettingsModel",
                locator="lines:" + ",".join(str(line) for line in lines),
                status="compatibility",
                evidence="explicit legacy singleton reference pending M9 field retirement",
            )
        )
    return results


def _decorator_task_name(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    module_path: str,
) -> str:
    """Return Celery's explicit name or its default fully-qualified name."""

    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        if call is None or _call_name(call) not in {"shared_task", "task"}:
            continue
        for keyword in call.keywords:
            if keyword.arg == "name":
                return _literal_string(keyword.value) or f"{module_path}.{node.name}"
        return f"{module_path}.{node.name}"
    return ""


def _discover_celery_tasks(celery: dict[str, Any]) -> list[dict[str, object]]:
    governed = {
        str(item.get("task_path")): item
        for item in celery.get("tasks", [])
        if isinstance(item, dict) and item.get("task_path")
    }
    results: list[dict[str, object]] = []
    for path in sorted((ROOT / "apps").glob("**/*.py")):
        if "migrations" in path.parts or "tests" in path.parts:
            continue
        path_text = _relative(path)
        module_path = path_text.removesuffix(".py").replace("/", ".")
        tree = _tree(path)
        for node in _functions(tree):
            task_name = _decorator_task_name(node, module_path=module_path)
            if not task_name:
                continue
            record = governed.get(task_name)
            if record is None:
                record = next(
                    (
                        item
                        for governed_path, item in governed.items()
                        if str(item.get("source_file") or "") == path_text
                        and governed_path.rsplit(".", 1)[-1] == node.name
                    ),
                    None,
                )
            owned = path_text.startswith(("apps/data_center/", "apps/config_center/"))
            if record is not None:
                status = "active_public" if owned else "compatibility"
                evidence = "governance/celery_task_contracts.json"
            elif path_text == "apps/equity/application/tasks.py" and node.name.endswith("_alias"):
                status = "compatibility"
                evidence = "Celery compatibility alias delegates to a governed equity task"
            elif path_text.startswith(("apps/macro/", "apps/realtime/")):
                status = "candidate-review"
                evidence = "Data acquisition task lacks Celery task-contract registration"
            else:
                status = "adjacent_operational"
                evidence = "Adjacent app-owned operational task; not a Data Center owner task"
            results.append(
                _entry(
                    category="celery_task",
                    path=path_text,
                    symbol=node.name,
                    locator=task_name,
                    status=status,
                    evidence=evidence,
                    target=task_name,
                )
            )
    return results


def _discover_beat_schedule(celery: dict[str, Any]) -> list[dict[str, object]]:
    path = ROOT / "core" / "settings" / "base.py"
    governed = {
        str(item.get("task_path"))
        for item in celery.get("tasks", [])
        if isinstance(item, dict) and item.get("task_path")
    }
    results: list[dict[str, object]] = []
    tree = _tree(path)
    schedule: ast.Dict | None = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "CELERY_BEAT_SCHEDULE"
            for target in node.targets
        ) and isinstance(node.value, ast.Dict):
            schedule = node.value
            break
    if schedule is None:
        return results
    for schedule_key_node, config_node in zip(schedule.keys, schedule.values, strict=True):
        schedule_key = _literal_string(schedule_key_node)
        if schedule_key is None or not isinstance(config_node, ast.Dict):
            continue
        task_path = ""
        for key_node, value_node in zip(config_node.keys, config_node.values, strict=True):
            if _literal_string(key_node) == "task":
                task_path = _literal_string(value_node) or ""
                break
        if not task_path:
            continue
        results.append(
            _entry(
                category="beat_schedule",
                path=_relative(path),
                symbol=task_path.rsplit(".", 1)[-1],
                locator=schedule_key,
                target=task_path,
                status=(
                    "active_public"
                    if task_path in governed
                    else (
                        "candidate-review"
                        if task_path.startswith(
                            (
                                "apps.macro.application.tasks.",
                                "apps.realtime.application.tasks.",
                            )
                        )
                        else "adjacent_operational"
                    )
                ),
                evidence=(
                    "governance/celery_task_contracts.json"
                    if task_path in governed
                    else (
                        "scheduled data acquisition task lacks Celery task-contract registration"
                        if task_path.startswith(
                            (
                                "apps.macro.application.tasks.",
                                "apps.realtime.application.tasks.",
                            )
                        )
                        else "adjacent app-owned operational schedule"
                    )
                ),
            )
        )
    return results


def _discover_current_data_surfaces(current_data: dict[str, Any]) -> list[dict[str, object]]:
    """Publish every governed current/latest surface as an explicit entrypoint."""

    results: list[dict[str, object]] = []
    for item in current_data.get("contracts", []):
        if not isinstance(item, dict) or not str(item.get("id") or "").strip():
            continue
        source_files = item.get("source_files")
        source_count = len(source_files) if isinstance(source_files, list) else 0
        results.append(
            _entry(
                category="current_data_surface",
                path="governance/current_data_contracts.json",
                symbol=str(item["id"]),
                locator=str(item.get("surface") or ""),
                status="active_public",
                evidence=f"governed current-data contract; source_files={source_count}",
            )
        )
    return results


def _path_calls(path: Path) -> list[tuple[str, str, int]]:
    results: list[tuple[str, str, int]] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call) or _call_name(node) != "path" or not node.args:
            continue
        route = _literal_string(node.args[0])
        if route is None:
            continue
        name = ""
        for keyword in node.keywords:
            if keyword.arg == "name":
                name = _literal_string(keyword.value) or ""
        results.append((route, name, node.lineno))
    return results


def _discover_rest_urls() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    owned_paths = (
        ROOT / "apps" / "data_center" / "interface" / "api_urls.py",
        ROOT / "apps" / "data_center" / "interface" / "urls.py",
    )
    for path in owned_paths:
        for route, name, line in _path_calls(path):
            results.append(
                _entry(
                    category="rest_url",
                    path=_relative(path),
                    symbol=name or f"path@{line}",
                    locator=route,
                    status="active_public",
                    evidence="Data Center-owned URLconf",
                )
            )
    for path in sorted(ROOT.glob("**/urls.py")):
        if path in owned_paths or any(part in {".venv", "node_modules"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "data-center" not in text and "apps.data_center" not in text:
            continue
        for route, name, line in _path_calls(path):
            if "data-center" not in route:
                continue
            results.append(
                _entry(
                    category="rest_url",
                    path=_relative(path),
                    symbol=name or f"mount@{line}",
                    locator=route,
                    status="active_public",
                    evidence="project URL mount for Data Center",
                )
            )
    return results


def _discover_sdk() -> list[dict[str, object]]:
    owner = ROOT / "sdk" / "agomtradepro" / "modules" / "data_center.py"
    results: list[dict[str, object]] = []
    tree = _tree(owner)
    owner_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DataCenterModule"
    )
    for node in owner_class.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith(
            "_"
        ):
            results.append(
                _entry(
                    category="sdk",
                    path=_relative(owner),
                    symbol=f"DataCenterModule.{node.name}",
                    status="active_public",
                    evidence="canonical SDK DataCenterModule",
                )
            )
    modules_root = ROOT / "sdk" / "agomtradepro" / "modules"
    for path in sorted(modules_root.glob("*.py")):
        if path == owner:
            continue
        tree = _tree(path)
        for node in _functions(tree):
            body_text = ast.unparse(node)
            if ".data_center" not in body_text:
                continue
            results.append(
                _entry(
                    category="sdk",
                    path=_relative(path),
                    symbol=_function_symbol(node, tree),
                    status="compatibility",
                    evidence="SDK compatibility delegation to DataCenterModule",
                )
            )
    return results


def _discover_mcp_tools() -> list[dict[str, object]]:
    root = ROOT / "sdk" / "agomtradepro_mcp" / "tools"
    results: list[dict[str, object]] = []
    for path in sorted(root.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if ".data_center" not in text:
            continue
        tree = _tree(path)
        for node in _functions(tree):
            if node.name.startswith("register_") or ".data_center" not in ast.unparse(node):
                continue
            results.append(
                _entry(
                    category="mcp_tool",
                    path=_relative(path),
                    symbol=node.name,
                    status=(
                        "active_public" if path.name == "data_center_tools.py" else "compatibility"
                    ),
                    evidence=(
                        "Data Center-owned MCP tool registrar"
                        if path.name == "data_center_tools.py"
                        else "cross-owner MCP compatibility tool"
                    ),
                )
            )
    return results


def _tui_actions(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("key")): item
        for item in payload.get("actions", [])
        if isinstance(item, dict)
        and (
            str(item.get("endpoint", "")).startswith("/api/data-center")
            or str(item.get("key", "")).startswith(("data-center.", "data_center."))
        )
    }


def _discover_terminal_tui() -> list[dict[str, object]]:
    published_path = ROOT / "config" / "tui" / "published" / "tui_operation_graph.published.json"
    generated_path = ROOT / "config" / "tui" / "generated" / "tui_operation_graph.generated.json"
    published = _load_json(published_path)
    generated = _load_json(generated_path)
    published_actions = _tui_actions(published)
    generated_actions = _tui_actions(generated)
    results: list[dict[str, object]] = []
    for key, item in sorted(generated_actions.items()):
        is_published = key in published_actions
        results.append(
            _entry(
                category="terminal_tui",
                path=_relative(generated_path),
                symbol=key,
                locator=str(item.get("endpoint", "")),
                status="active_public" if is_published else "candidate-review",
                evidence=(
                    "published TUI operation graph"
                    if is_published
                    else "generated TUI action is not present in published graph"
                ),
            )
        )
    generated_screens = {
        str(item.get("key"))
        for item in generated.get("screens", [])
        if isinstance(item, dict) and str(item.get("key")) == "api-library.data-center"
    }
    published_screens = {
        str(item.get("key"))
        for item in published.get("screens", [])
        if isinstance(item, dict) and str(item.get("key")) == "api-library.data-center"
    }
    for key in sorted(generated_screens):
        results.append(
            _entry(
                category="terminal_tui",
                path=_relative(generated_path),
                symbol=key,
                status="active_public" if key in published_screens else "candidate-review",
                evidence=(
                    "published TUI screen" if key in published_screens else "unpublished TUI screen"
                ),
            )
        )
    return results


def _named_dict_keys(path: Path, names: set[str]) -> dict[str, str]:
    keys: dict[str, str] = {}
    for node in _tree(path).body:
        target_name = ""
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target_name = node.targets[0].id if isinstance(node.targets[0], ast.Name) else ""
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value
        if target_name not in names or not isinstance(value, ast.Dict):
            continue
        for key_node, value_node in zip(value.keys, value.values, strict=True):
            key = _literal_string(key_node)
            if key is None:
                continue
            if isinstance(value_node, ast.Name):
                keys[key] = value_node.id
    return keys


def _discover_capability_runtime() -> list[dict[str, object]]:
    handler_path = (
        ROOT
        / "sdk"
        / "agomtradepro_mcp"
        / "registry"
        / "runtime_handlers"
        / "owners"
        / "data_center.py"
    )
    handlers = _named_dict_keys(
        handler_path,
        {"LEGACY_TOOL_FALLBACKS", "GOVERNED_HANDLERS"},
    )
    results: list[dict[str, object]] = []
    capability_root = ROOT / "sdk" / "agomtradepro_mcp" / "registry" / "modules" / "owners"
    for path in sorted(capability_root.glob("data_center_*_capabilities.py")):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call) or _call_name(node) != "CapabilityManifest":
                continue
            values = {
                keyword.arg: _literal_string(keyword.value)
                for keyword in node.keywords
                if keyword.arg in {"capability_key", "executor_ref"}
            }
            capability_key = values.get("capability_key")
            executor_ref = values.get("executor_ref")
            if not capability_key or not executor_ref:
                continue
            wired = executor_ref in handlers
            results.append(
                _entry(
                    category="capability_runtime",
                    path=_relative(path),
                    symbol=capability_key,
                    locator=executor_ref,
                    status="active_public" if wired else "candidate-review",
                    evidence=(
                        f"runtime handler registry: {handlers[executor_ref]}"
                        if wired
                        else "capability executor is absent from Data Center handler registries"
                    ),
                )
            )
    return results


def _top_level_public_functions(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in _tree(path).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]


def _discover_ports_and_facades() -> list[dict[str, object]]:
    public_path = ROOT / "apps" / "data_center" / "application" / "public.py"
    results = [
        _entry(
            category="public_port",
            path=_relative(public_path),
            symbol=node.name,
            status="active_public",
            evidence="canonical Data Center Application public port",
        )
        for node in _top_level_public_functions(public_path)
    ]
    for path_text in COMPATIBILITY_FACADES:
        path = ROOT / path_text
        for node in _top_level_public_functions(path):
            results.append(
                _entry(
                    category="compatibility_facade",
                    path=path_text,
                    symbol=node.name,
                    status="compatibility",
                    evidence="registered legacy Application facade pending consumer cutover",
                )
            )
    return results


def build_inventory(repo_root: Path = ROOT) -> dict[str, object]:
    """Return the complete deterministic inventory for ``repo_root``."""

    global ROOT
    previous_root = ROOT
    ROOT = repo_root
    try:
        legacy = _load_json(ROOT / "governance" / "data_center_legacy_entrypoints.json")
        celery = _load_json(ROOT / "governance" / "celery_task_contracts.json")
        current_data = _load_json(ROOT / "governance" / "current_data_contracts.json")
        runtime_config = _load_json(ROOT / "governance" / "runtime_config_contracts.json")
        entries = (
            _discover_scripts(legacy)
            + _discover_management_commands()
            + _discover_management_command_edges()
            + _discover_application_consumers()
            + _discover_admin_surfaces()
            + _discover_scheduler_writers()
            + _discover_orchestration_entries()
            + _discover_celery_tasks(celery)
            + _discover_beat_schedule(celery)
            + _discover_current_data_surfaces(current_data)
            + _discover_rest_urls()
            + _discover_sdk()
            + _discover_mcp_tools()
            + _discover_terminal_tui()
            + _discover_capability_runtime()
            + _discover_ports_and_facades()
            + _discover_runtime_config_keys(runtime_config)
            + _discover_system_settings_compatibility()
        )
    finally:
        ROOT = previous_root
    unique = {str(item["id"]): item for item in entries}
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            str(item["category"]),
            str(item["path"]),
            str(item["symbol"]),
            str(item["locator"]),
        ),
    )
    category_counts = Counter(str(item["category"]) for item in ordered)
    status_counts = Counter(dict.fromkeys(STATUSES, 0))
    status_counts.update(str(item["status"]) for item in ordered)
    return {
        "schema_version": "1.1",
        "owner": "data_center",
        "semantics": {
            "active_public": "explicitly governed canonical external or cross-app port",
            "compatibility": "supported migration seam with a canonical Data Center replacement",
            "adjacent_operational": "enumerated app-owned operation outside the Data Center owner contract",
            "candidate-review": "discovered callable surface; discovery is not approval or completion",
        },
        "source_contracts": [
            "governance/celery_task_contracts.json",
            "governance/current_data_contracts.json",
            "governance/data_center_legacy_entrypoints.json",
            "governance/runtime_config_contracts.json",
            "config/tui/generated/tui_operation_graph.generated.json",
            "config/tui/published/tui_operation_graph.published.json",
        ],
        "source_contract_counts": {
            "celery_tasks": len(celery.get("tasks", [])),
            "current_data_contracts": len(current_data.get("contracts", [])),
            "legacy_entrypoints_and_wrappers": len(legacy.get("entrypoints", []))
            + len(legacy.get("wrappers", [])),
            "runtime_config_keys": len(runtime_config.get("definitions", [])),
        },
        "entries": ordered,
        "counts": {
            "total": len(ordered),
            "by_category": dict(sorted(category_counts.items())),
            "by_status": dict(sorted(status_counts.items())),
        },
    }


def validate_inventory(payload: dict[str, object]) -> list[str]:
    """Return stable structural violations for an inventory payload."""

    entries = payload.get("entries")
    if not isinstance(entries, list):
        return ["entries_invalid"]
    violations: list[str] = []
    ids: set[str] = set()
    categories: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            violations.append("entry_invalid")
            continue
        entry_id = str(item.get("id", ""))
        if not entry_id:
            violations.append("entry_id_missing")
        elif entry_id in ids:
            violations.append(f"entry_id_duplicate:{entry_id}")
        ids.add(entry_id)
        category = str(item.get("category", ""))
        categories.add(category)
        status = str(item.get("status", ""))
        if status not in STATUSES:
            violations.append(f"entry_status_invalid:{entry_id}:{status}")
        if not str(item.get("evidence", "")).strip():
            violations.append(f"entry_evidence_missing:{entry_id}")
        if (
            category
            in {
                "beat_schedule",
                "celery_task",
                "management_command_edge",
                "scheduler_writer",
            }
            and not str(item.get("target", "")).strip()
        ):
            violations.append(f"entry_target_missing:{entry_id}")
    for category in sorted(REQUIRED_CATEGORIES - categories):
        violations.append(f"required_category_empty:{category}")
    return sorted(violations)


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    """Write or stale-check the governed entrypoint inventory."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the generated inventory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_inventory()
    violations = validate_inventory(payload)
    if violations:
        raise SystemExit("Data Center entrypoint inventory violations: " + "; ".join(violations))
    rendered = _canonical_json(payload)
    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    elif not args.output.exists():
        raise SystemExit(f"inventory is missing: {args.output}")
    elif args.output.read_text(encoding="utf-8") != rendered:
        raise SystemExit(f"inventory is stale: {args.output}")
    print(json.dumps(payload["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
