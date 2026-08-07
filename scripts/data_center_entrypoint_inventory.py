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
import fnmatch
import json
import re
from collections import Counter
from collections.abc import Iterable
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "governance" / "data_center_entrypoints.json"
STATUSES = frozenset(
    {
        "active_public",
        "compatibility",
        "adjacent_operational",
        "retired_blocked",
        "candidate-review",
    }
)
REQUIRED_CATEGORIES = frozenset(
    {
        "admin_surface",
        "application_consumer",
        "script",
        "management_command",
        "management_command_edge",
        "celery_task",
        "celery_dispatch_edge",
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
        "dynamic_import_edge",
        "system_settings_compatibility",
        "operational_script",
        "operational_dispatch_edge",
        "workflow_step",
        "test_evidence",
        "migration_evidence",
        "runbook",
        "agent_skill",
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
        "scripts/verify_postgres_backup_restore.py",
        "scripts/check_migration_graph.py",
    }
)

OPERATIONAL_TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("pg_dump", re.compile(r"\bpg_dump\b", re.IGNORECASE), "postgres:pg_dump"),
    ("pg_restore", re.compile(r"\bpg_restore\b", re.IGNORECASE), "postgres:pg_restore"),
    ("dropdb", re.compile(r"\bdropdb\b", re.IGNORECASE), "postgres:dropdb"),
    ("createdb", re.compile(r"\bcreatedb\b", re.IGNORECASE), "postgres:createdb"),
    (
        "manage.py migrate",
        re.compile(r"manage\.py[\s\"'`]+migrate\b", re.IGNORECASE),
        "django:migrate",
    ),
    (
        "manage.py backup_database",
        re.compile(r"manage\.py[\s\"'`]+backup_database\b", re.IGNORECASE),
        "django:backup_database",
    ),
    (
        "MigrationExecutor",
        re.compile(r"\bMigrationExecutor\b"),
        "django:MigrationExecutor",
    ),
    (
        "Register-ScheduledTask",
        re.compile(r"\bRegister-ScheduledTask\b", re.IGNORECASE),
        "windows:scheduled-task",
    ),
    (
        "backup_database_task",
        re.compile(r"\bbackup_database_task\b"),
        "apps.task_monitor.application.tasks.backup_database_task",
    ),
    (
        "plan_retention_task",
        re.compile(r"\bplan_retention_task\b"),
        "apps.data_center.application.tasks.plan_retention_task",
    ),
    (
        "enforce_retention_task",
        re.compile(r"\benforce_retention_task\b"),
        "apps.data_center.application.tasks.enforce_retention_task",
    ),
    (
        "cleanup_expired_raw_payloads_task",
        re.compile(r"\bcleanup_expired_raw_payloads_task\b"),
        "apps.data_center.application.tasks.cleanup_expired_raw_payloads_task",
    ),
    (
        "archive_raw_payloads_task",
        re.compile(r"\barchive_raw_payloads_task\b"),
        "apps.data_center.application.archive_tasks.archive_raw_payloads_task",
    ),
    (
        "verify_archive_manifest_task",
        re.compile(r"\bverify_archive_manifest_task\b"),
        "apps.data_center.application.tasks.verify_archive_manifest_task",
    ),
    (
        "audit_archive_restore_task",
        re.compile(r"\baudit_archive_restore_task\b"),
        "apps.data_center.application.archive_tasks.audit_archive_restore_task",
    ),
    (
        "send_database_backup_email_task",
        re.compile(r"\bsend_database_backup_email_task\b"),
        "apps.account.application.tasks.send_database_backup_email_task",
    ),
    (
        "initialize_storage_budget",
        re.compile(r"\binitialize_storage_budget\b"),
        "django:initialize_storage_budget",
    ),
    (
        "collect_storage_capacity_profile",
        re.compile(r"\bcollect_storage_capacity_profile\b"),
        "django:collect_storage_capacity_profile",
    ),
    (
        "storage_budget_control",
        re.compile(r"\b(?:StorageBudgetPolicy(?:Model)?|require_backup_capacity)\b"),
        "config_center:storage_budget",
    ),
    (
        "call_command dumpdata",
        re.compile(r"call_command\(\s*[\"']dumpdata[\"']", re.IGNORECASE),
        "django:dumpdata",
    ),
    (
        "call_command loaddata",
        re.compile(r"call_command\(\s*[\"']loaddata[\"']", re.IGNORECASE),
        "django:loaddata",
    ),
)

SCRIPT_DISPATCH_PATH_OVERRIDES = {
    "check_and_migrate.py": "scripts/debug/check_and_migrate.py",
    "direct_migrate.py": "scripts/migration/direct_migrate.py",
    "do_migrate.py": "scripts/migration/do_migrate.py",
    "migrate_data.py": "scripts/migration/migrate_data.py",
}
SCRIPT_DISPATCH_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (
        script_name,
        re.compile(re.escape(script_name), re.IGNORECASE),
        SCRIPT_DISPATCH_PATH_OVERRIDES.get(script_name, f"scripts/{script_name}"),
    )
    for script_name in (
        "auto-backup.ps1",
        "backup-vps-postgres.py",
        "backup-vps-postgres.ps1",
        "check_and_migrate.py",
        "check_migration_graph.py",
        "deploy-on-vps.sh",
        "deploy-vps.ps1",
        "direct_migrate.py",
        "do_migrate.py",
        "migrate_data.py",
        "migrate-to-postgres.ps1",
        "migrate-vps-sqlite-to-postgres.sh",
        "remote-build-deploy-vps.ps1",
        "remote_build_deploy_vps.py",
        "rollback.sh",
        "verify_postgres_backup_restore.py",
        "vps-backup.ps1",
        "vps-backup.sh",
        "vps-restore.ps1",
        "vps-restore.sh",
    )
)
OPERATIONAL_EVIDENCE_PATTERN = re.compile(
    r"\b(?:backup|restore|retention|archive|migration|postgres(?:ql)?)\b",
    re.IGNORECASE,
)
OPERATIONAL_SCRIPT_SUFFIXES = frozenset({".py", ".ps1", ".sh", ".bat"})
IGNORED_PATH_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "pytest-tmp",
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


def _resolved_string(node: ast.AST | None, constants: dict[str, str]) -> str | None:
    """Resolve one literal or statically bound string name."""

    literal = _literal_string(node)
    if literal is not None:
        return literal
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _imported_names(tree: ast.Module) -> dict[str, str]:
    """Map local import names to their canonical dotted object names."""

    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported[alias.asname or alias.name.split(".", 1)[0]] = alias.name
    return imported


def _resolved_dotted_name(node: ast.AST, imported: dict[str, str]) -> str | None:
    """Resolve a simple imported name/attribute expression to a dotted name."""

    dotted = _dotted_attribute(node)
    if dotted is None:
        return None
    head, separator, tail = dotted.partition(".")
    canonical_head = imported.get(head, head)
    return canonical_head + (separator + tail if separator else "")


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
            relative_parts = path.relative_to(ROOT).parts
            if any(part in IGNORED_PATH_PARTS | {"migrations", "tests"} for part in relative_parts):
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


def _operational_tokens(text: str) -> tuple[tuple[str, str], ...]:
    """Return stable operational token/target pairs found in ``text``."""

    matches: dict[str, str] = {}
    for label, pattern, target in (*OPERATIONAL_TOKEN_PATTERNS, *SCRIPT_DISPATCH_PATTERNS):
        if pattern.search(text):
            matches[label] = target
    return tuple(sorted(matches.items()))


def _operational_script_files() -> Iterable[Path]:
    """Yield executable repository files that can own operational dispatch."""

    candidates: set[Path] = set()
    scripts_root = ROOT / "scripts"
    if scripts_root.exists():
        candidates.update(path for path in scripts_root.rglob("*") if path.is_file())
    candidates.update(
        path
        for path in ROOT.iterdir()
        if path.is_file() and path.suffix.lower() in OPERATIONAL_SCRIPT_SUFFIXES
    )
    apps_root = ROOT / "apps"
    if apps_root.exists():
        candidates.update(
            path
            for path in apps_root.rglob("*.py")
            if "management" in path.parts and "commands" in path.parts
        )
    own_path = ROOT / "scripts" / "data_center_entrypoint_inventory.py"
    for path in sorted(candidates):
        if path == own_path or path.suffix.lower() not in OPERATIONAL_SCRIPT_SUFFIXES:
            continue
        relative_parts = path.relative_to(ROOT).parts
        if any(part in IGNORED_PATH_PARTS for part in relative_parts):
            continue
        yield path


def _discover_operational_scripts() -> list[dict[str, object]]:
    """Discover scripts/commands containing governed database operations."""

    results: list[dict[str, object]] = []
    for path in _operational_script_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        tokens = _operational_tokens(f"{path.name}\n{text}")
        if not tokens:
            continue
        targets = ",".join(target for _label, target in tokens)
        results.append(
            _entry(
                category="operational_script",
                path=_relative(path),
                symbol="__main__" if "management" not in path.parts else path.stem,
                target=targets,
                status="candidate-review",
                evidence="static operational command token discovery; governance review required",
            )
        )
    return results


def _discover_operational_dispatch_edges() -> list[dict[str, object]]:
    """Expand each script-level database operation into a reviewable edge."""

    results: list[dict[str, object]] = []
    for path in _operational_script_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, target in _operational_tokens(f"{path.name}\n{text}"):
            results.append(
                _entry(
                    category="operational_dispatch_edge",
                    path=_relative(path),
                    symbol=label,
                    locator=f"token:{label}",
                    target=target,
                    status="candidate-review",
                    evidence="static operational dispatch token discovery; governance review required",
                )
            )
    return results


def _discover_workflow_steps() -> list[dict[str, object]]:
    """Discover CI workflow steps that execute database operations."""

    results: list[dict[str, object]] = []
    workflow_root = ROOT / ".github" / "workflows"
    if not workflow_root.exists():
        return results
    step_pattern = re.compile(r"^\s*-\s+name:\s*(.+?)\s*$", re.MULTILINE)
    for path in sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml"))):
        text = path.read_text(encoding="utf-8", errors="ignore")
        matches = list(step_pattern.finditer(text))
        for index, match in enumerate(matches):
            block_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[match.start() : block_end]
            tokens = _operational_tokens(block)
            if not tokens:
                continue
            step_name = match.group(1).strip().strip("\"'")
            results.append(
                _entry(
                    category="workflow_step",
                    path=_relative(path),
                    symbol=step_name,
                    locator="tokens:" + ",".join(label for label, _target in tokens),
                    target=",".join(target for _label, target in tokens),
                    status="candidate-review",
                    evidence="workflow step contains an operational database dispatch",
                )
            )
    return results


def _evidence_files(root: Path, pattern: str) -> Iterable[Path]:
    if not root.exists():
        return ()
    return (
        path
        for path in sorted(root.rglob(pattern))
        if not any(part in IGNORED_PATH_PARTS for part in path.relative_to(ROOT).parts)
    )


def _discover_test_and_migration_evidence() -> list[dict[str, object]]:
    """Discover executable test and migration evidence for operational behavior."""

    results: list[dict[str, object]] = []
    candidates: set[tuple[Path, str]] = set()
    for path in _evidence_files(ROOT / "tests", "*.py"):
        category = (
            "migration_evidence"
            if "migrations" in path.relative_to(ROOT).parts
            else "test_evidence"
        )
        candidates.add((path, category))
    for path in _evidence_files(ROOT / "apps" / "data_center" / "migrations", "*.py"):
        candidates.add((path, "migration_evidence"))
    for path in _evidence_files(ROOT / "apps" / "config_center" / "migrations", "*.py"):
        candidates.add((path, "migration_evidence"))
    for path, category in sorted(candidates, key=lambda item: _relative(item[0])):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = _relative(path).lower()
        basename_is_evidence = bool(
            re.search(
                r"(?:backup|restore|retention|archive|postgres|migration_graph|storage_budget)",
                path.stem,
            )
        )
        is_owner_migration = relative.startswith(
            ("apps/data_center/migrations/", "apps/config_center/migrations/")
        )
        if is_owner_migration:
            relevant = basename_is_evidence or bool(_operational_tokens(text))
        elif category == "migration_evidence":
            relevant = "data_center" in relative and (
                basename_is_evidence or bool(_operational_tokens(text))
            )
        else:
            relevant = basename_is_evidence or bool(_operational_tokens(text))
        if not relevant:
            continue
        results.append(
            _entry(
                category=category,
                path=_relative(path),
                symbol=path.stem,
                status="candidate-review",
                evidence="executable operational test/migration evidence; governance review required",
            )
        )
    return results


def _discover_runbooks() -> list[dict[str, object]]:
    """Discover operational runbooks and the canonical refactor plan."""

    results: list[dict[str, object]] = []
    candidates: set[Path] = set()
    for relative_root in ("docs/operations", "docs/deployment"):
        candidates.update(_evidence_files(ROOT / relative_root, "*.md"))
    canonical_plan = (
        ROOT / "docs" / "plans" / "data-center-canonical-architecture-refactor-2026-08-02.md"
    )
    if canonical_plan.exists():
        candidates.add(canonical_plan)
    for path in sorted(candidates):
        path_is_operational = bool(
            re.search(
                r"(?:backup|restore|deploy|deployment|postgres|database)",
                path.stem,
                re.IGNORECASE,
            )
        )
        if path != canonical_plan and not path_is_operational:
            continue
        results.append(
            _entry(
                category="runbook",
                path=_relative(path),
                symbol=path.stem,
                status="candidate-review",
                evidence="operational runbook keyword discovery; governance review required",
            )
        )
    return results


def _discover_agent_skills() -> list[dict[str, object]]:
    """Discover agent skills that can dispatch database operations."""

    results: list[dict[str, object]] = []
    skills_root = ROOT / ".agents" / "skills"
    if not skills_root.exists():
        return results
    for path in sorted(skills_root.rglob("SKILL.md")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        skill_is_operational = bool(
            re.search(r"(?:backup|deploy|hot-update)", path.parent.name, re.IGNORECASE)
        )
        if not (skill_is_operational or _operational_tokens(text)):
            continue
        results.append(
            _entry(
                category="agent_skill",
                path=_relative(path),
                symbol=path.parent.name,
                target=",".join(target for _label, target in _operational_tokens(text)),
                status="candidate-review",
                evidence="agent skill contains operational database instructions",
            )
        )
    return results


def _apply_operational_governance(
    entries: list[dict[str, object]], governance: dict[str, Any]
) -> list[dict[str, object]]:
    """Overlay explicit lifecycle decisions without approving new discoveries."""

    rules = governance.get("entries", [])
    if not isinstance(rules, list):
        raise ValueError("operational governance entries must be a list")
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("operational governance rule must be an object")
        status = str(rule.get("status", ""))
        if status not in STATUSES - {"candidate-review"}:
            raise ValueError(f"invalid governed operational status: {status}")
        evidence = str(rule.get("evidence", "")).strip()
        if not evidence:
            raise ValueError("operational governance evidence is required")
        selectors: dict[str, tuple[str, ...]] = {}
        for key in ("category", "path", "symbol", "locator"):
            raw_selector = rule.get(key, "*")
            if isinstance(raw_selector, list):
                selectors[key] = tuple(str(item) for item in raw_selector)
            else:
                selectors[key] = (str(raw_selector),)
        matching_entries = [
            entry
            for entry in entries
            if all(
                any(fnmatch.fnmatchcase(str(entry.get(key, "")), pattern) for pattern in patterns)
                for key, patterns in selectors.items()
            )
        ]
        if not matching_entries:
            raise ValueError(f"operational governance rule matched no entry: {selectors}")
        for key, patterns in selectors.items():
            for pattern in patterns:
                if not any(
                    fnmatch.fnmatchcase(str(entry.get(key, "")), pattern)
                    for entry in matching_entries
                ):
                    raise ValueError(
                        f"operational governance selector matched no entry: {key}={pattern}"
                    )
        for entry in matching_entries:
            entry["status"] = status
            entry["evidence"] = evidence
            target = str(rule.get("target", "")).strip()
            if target:
                entry["target"] = target
    return entries


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
        if any(part in IGNORED_PATH_PARTS for part in path.relative_to(ROOT).parts):
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


def _management_dispatch_kind(node: ast.Call, imported: dict[str, str]) -> str:
    """Return the supported Django management dispatch primitive for one call."""

    resolved = _resolved_dotted_name(node.func, imported) or ""
    if resolved.endswith(".call_command") or _call_name(node) in {
        "call_command",
        "_run_command",
    }:
        return "call_command"
    if resolved.endswith(".execute_from_command_line") or _call_name(node) == (
        "execute_from_command_line"
    ):
        return "execute_from_command_line"
    return ""


def _command_from_argv(
    node: ast.AST | None,
    constants: dict[str, str],
) -> str | None:
    """Resolve the command slot from a literal ``manage.py`` argv expression."""

    if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) < 2:
        return None
    return _resolved_string(node.elts[1], constants)


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
        imported = _imported_names(tree)
        collections = _module_string_collections(tree)
        constants = _module_string_constants(tree)
        planned_commands = _dictionary_command_values(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            dispatch_kind = _management_dispatch_kind(node, imported)
            if not dispatch_kind:
                continue
            targets: tuple[str, ...] = ()
            if dispatch_kind == "execute_from_command_line":
                target = _command_from_argv(node.args[0] if node.args else None, constants)
                if target:
                    targets = (target,)
            else:
                command_argument = (
                    node.args[0]
                    if node.args
                    else next(
                        (
                            keyword.value
                            for keyword in node.keywords
                            if keyword.arg in {"command_name", "name"}
                        ),
                        None,
                    )
                )
                literal = _resolved_string(command_argument, constants)
                if literal is not None:
                    targets = (literal,)
                elif isinstance(command_argument, ast.Name):
                    targets = (
                        (constants[command_argument.id],)
                        if command_argument.id in constants
                        else _enclosing_loop_values(
                            tree,
                            node,
                            command_argument.id,
                            collections,
                        )
                    )
            if not targets:
                if (
                    dispatch_kind == "call_command"
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
                            f"{dispatch_kind} resolves to {target_path}"
                            if target_path
                            else f"{dispatch_kind} target is external or runtime-selected"
                        ),
                    )
                )
    return results


def _discover_application_consumers() -> list[dict[str, object]]:
    """Enumerate every production import of canonical Application public boundaries."""

    module_names = {
        "apps.data_center.application.public",
        "apps.data_center.application.public_protocols",
    }
    results: list[dict[str, object]] = []
    for path in _production_python_files("apps", "core", "shared", "scripts", "sdk"):
        path_text = _relative(path)
        if path_text.startswith("apps/data_center/"):
            continue
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and node.module in module_names:
                for alias in node.names:
                    evidence = (
                        "canonical Data Center Application Public Port import"
                        if node.module == "apps.data_center.application.public"
                        else "canonical Data Center Application public protocol import"
                    )
                    results.append(
                        _entry(
                            category="application_consumer",
                            path=path_text,
                            symbol=alias.name,
                            locator=f"line:{node.lineno}",
                            status="active_public",
                            evidence=evidence,
                        )
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in module_names:
                        continue
                    evidence = (
                        "canonical Data Center Application Public Port module import"
                        if alias.name == "apps.data_center.application.public"
                        else "canonical Data Center Application public protocol module import"
                    )
                    results.append(
                        _entry(
                            category="application_consumer",
                            path=path_text,
                            symbol=alias.asname or alias.name,
                            locator=f"line:{node.lineno}",
                            status="active_public",
                            evidence=evidence,
                        )
                    )
    return results


def _admin_registration_targets(decorator: ast.expr) -> tuple[str, ...]:
    """Return every model symbol registered by one Admin decorator."""

    if not isinstance(decorator, ast.Call) or not decorator.args:
        return ()
    function = decorator.func
    if not isinstance(function, ast.Attribute) or function.attr != "register":
        return ()
    dotted = _dotted_attribute(function.value)
    if dotted not in {"admin", "admin.site", "site"} and not str(dotted).endswith("site"):
        return ()
    return tuple(
        ast.unparse(target)
        for target in decorator.args
        if isinstance(target, (ast.Name, ast.Attribute))
    )


def _admin_call_targets(node: ast.Call) -> tuple[str, ...]:
    """Return model expressions from imperative AdminSite registration."""

    if not node.args:
        return ()
    first = node.args[0]
    values = first.elts if isinstance(first, (ast.List, ast.Set, ast.Tuple)) else [first]
    return tuple(
        ast.unparse(value) for value in values if isinstance(value, (ast.Name, ast.Attribute))
    )


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
                for model in _admin_registration_targets(decorator):
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
                            target=canonical_model,
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
            dotted = _dotted_attribute(node.func) or ""
            if not dotted.endswith(".register") or dotted == "admin.register":
                continue
            for model in _admin_call_targets(node):
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
                        symbol=dotted,
                        locator=canonical_model,
                        target=canonical_model,
                        status=status,
                        evidence="imperative Django Admin registration",
                    )
                )
    return results


def _assigned_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    """Return simple names assigned by an Assign/AnnAssign node."""

    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [target.id for target in targets if isinstance(target, ast.Name)]


def _periodic_task_aliases(tree: ast.Module) -> set[str]:
    """Resolve imported, annotated, and dynamically loaded PeriodicTask aliases."""

    aliases: set[str] = set()
    imported = _imported_names(tree)
    for local_name, canonical in imported.items():
        if canonical == "django_celery_beat.models.PeriodicTask":
            aliases.add(local_name)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            assigned = _assigned_names(node)
            if not assigned:
                continue
            value = node.value
            is_periodic_model = isinstance(value, ast.Attribute) and value.attr == "PeriodicTask"
            is_periodic_model = is_periodic_model or (
                isinstance(value, ast.Name) and value.id in aliases
            )
            is_periodic_model = is_periodic_model or (
                isinstance(value, ast.Call)
                and _call_name(value) == "get_model"
                and len(value.args) >= 2
                and _literal_string(value.args[0]) == "django_celery_beat"
                and _literal_string(value.args[1]) == "PeriodicTask"
            )
            if is_periodic_model:
                before = len(aliases)
                aliases.update(assigned)
                changed = changed or len(aliases) != before
    return aliases


def _keyword_node(call: ast.Call, name: str) -> ast.AST | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _dict_item_node(node: ast.AST | None, key: str) -> ast.AST | None:
    if not isinstance(node, ast.Dict):
        return None
    for key_node, value_node in zip(node.keys, node.values, strict=True):
        if _literal_string(key_node) == key:
            return value_node
    return None


def _periodic_writer_call(node: ast.Call, aliases: set[str]) -> bool:
    dotted = _dotted_attribute(node.func) or ""
    return any(
        dotted.startswith(f"{alias}.objects.") or dotted.startswith(f"{alias}._default_manager.")
        for alias in aliases
    ) and dotted.rsplit(".", 1)[-1] in {"create", "get_or_create", "update_or_create"}


def _scheduler_entry(
    *,
    path_text: str,
    schedule_name: str,
    task_path: str,
    line: int,
) -> dict[str, object]:
    owned_command = "/management/commands/" in f"/{path_text}"
    return _entry(
        category="scheduler_writer",
        path=path_text,
        symbol="PeriodicTask",
        locator=schedule_name or f"dynamic-schedule@{line}",
        target=task_path or "dynamic-task-path",
        status=(
            "active_public" if owned_command and schedule_name and task_path else "candidate-review"
        ),
        evidence=(
            f"database-backed Beat schedule writer at line {line}"
            if owned_command
            else f"ad-hoc database-backed Beat writer at line {line} must delegate to a command"
        ),
    )


def _enclosing_function(
    tree: ast.Module,
    target: ast.AST,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the smallest function that contains one AST node."""

    candidates = [
        node for node in _functions(tree) if any(child is target for child in ast.walk(node))
    ]
    return min(candidates, key=lambda node: len(tuple(ast.walk(node)))) if candidates else None


def _defaults_builder_task(
    tree: ast.Module,
    defaults: ast.AST | None,
    constants: dict[str, str],
) -> str:
    """Resolve a task path returned by a local defaults-builder function."""

    if not isinstance(defaults, ast.Call):
        return ""
    builder_name = _call_name(defaults)
    for function in _functions(tree):
        if function.name != builder_name:
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Return):
                continue
            direct = _resolved_string(_dict_item_node(node.value, "task"), constants)
            if direct:
                return direct
            if isinstance(node.value, ast.Name):
                for assignment in ast.walk(function):
                    if isinstance(assignment, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == node.value.id
                        for target in assignment.targets
                    ):
                        resolved = _resolved_string(
                            _dict_item_node(assignment.value, "task"), constants
                        )
                        if resolved:
                            return resolved
    return ""


def _wrapper_schedule_names(
    tree: ast.Module,
    writer: ast.Call,
    argument: ast.AST | None,
    constants: dict[str, str],
) -> tuple[tuple[str, int], ...]:
    """Expand a local PeriodicTask helper invoked with static schedule names."""

    if not isinstance(argument, ast.Name):
        return ()
    function = _enclosing_function(tree, writer)
    function_arguments = (
        (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
        if function is not None
        else ()
    )
    if function is None or argument.id not in {item.arg for item in function_arguments}:
        return ()
    results: list[tuple[str, int]] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or _call_name(call) != function.name:
            continue
        supplied = _keyword_node(call, argument.id)
        value = _resolved_string(supplied, constants)
        if value:
            results.append((value, call.lineno))
    return tuple(results)


def _discover_scheduler_writers() -> list[dict[str, object]]:
    """Enumerate each database-backed Beat schedule row and its task edge."""

    results: list[dict[str, object]] = []
    for path in _production_python_files("apps", "core", "scripts"):
        tree = _tree(path)
        aliases = _periodic_task_aliases(tree)
        if not aliases:
            continue
        constants = _module_string_constants(tree)
        path_text = _relative(path)
        pending_objects: dict[str, tuple[str, int]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            if not isinstance(node.value, ast.Call) or not _periodic_writer_call(
                node.value, aliases
            ):
                continue
            call = node.value
            if (_dotted_attribute(call.func) or "").rsplit(".", 1)[-1] != "get_or_create":
                continue
            schedule_name = _resolved_string(_keyword_node(call, "name"), constants) or ""
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                object_target = (
                    target.elts[0] if isinstance(target, (ast.Tuple, ast.List)) else target
                )
                if isinstance(object_target, ast.Name):
                    pending_objects[object_target.id] = (schedule_name, call.lineno)

        handled_get_or_create: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not (
                    isinstance(target, ast.Attribute)
                    and target.attr == "task"
                    and isinstance(target.value, ast.Name)
                    and target.value.id in pending_objects
                ):
                    continue
                schedule_name, call_line = pending_objects[target.value.id]
                task_path = _resolved_string(node.value, constants) or ""
                results.append(
                    _scheduler_entry(
                        path_text=path_text,
                        schedule_name=schedule_name,
                        task_path=task_path,
                        line=call_line,
                    )
                )
                handled_get_or_create.add(call_line)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _periodic_writer_call(node, aliases):
                continue
            method = (_dotted_attribute(node.func) or "").rsplit(".", 1)[-1]
            if method == "get_or_create" and node.lineno in handled_get_or_create:
                continue
            name_node = _keyword_node(node, "name")
            schedule_name = _resolved_string(name_node, constants) or ""
            defaults = _keyword_node(node, "defaults")
            task_path = _resolved_string(
                _dict_item_node(defaults, "task") or _keyword_node(node, "task"),
                constants,
            ) or _defaults_builder_task(tree, defaults, constants)
            expanded_names = _wrapper_schedule_names(tree, node, name_node, constants)
            if expanded_names:
                results.extend(
                    _scheduler_entry(
                        path_text=path_text,
                        schedule_name=expanded_name,
                        task_path=task_path,
                        line=call_line,
                    )
                    for expanded_name, call_line in expanded_names
                )
                continue
            results.append(
                _scheduler_entry(
                    path_text=path_text,
                    schedule_name=schedule_name,
                    task_path=task_path,
                    line=node.lineno,
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


def _discover_dynamic_import_edges() -> list[dict[str, object]]:
    """Enumerate Data Center-owned and MCP-registry dynamic import edges."""

    special_paths = {"sdk/agomtradepro_mcp/registry/loader.py"}
    results: list[dict[str, object]] = []
    for path in _production_python_files("apps", "core", "shared", "scripts", "sdk"):
        path_text = _relative(path)
        if not path_text.startswith("apps/data_center/") and path_text not in special_paths:
            continue
        tree = _tree(path)
        imported = _imported_names(tree)
        constants = _module_string_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            resolved_call = _resolved_dotted_name(node.func, imported) or ""
            if resolved_call not in {
                "importlib.import_module",
                "django.utils.module_loading.import_string",
                "__import__",
            } and _call_name(node) not in {"import_module", "import_string", "__import__"}:
                continue
            target = _resolved_string(node.args[0] if node.args else None, constants) or ""
            if path_text == "sdk/agomtradepro_mcp/registry/loader.py" and not target:
                owner_index = (
                    ROOT
                    / "sdk"
                    / "agomtradepro_mcp"
                    / "registry"
                    / "modules"
                    / "owners"
                    / "__init__.py"
                )
                registry_targets = sorted(
                    value.value
                    for value in ast.walk(_tree(owner_index))
                    if isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and ".owners.data_center_" in value.value
                )
                results.extend(
                    _entry(
                        category="dynamic_import_edge",
                        path=path_text,
                        symbol=_call_name(node) or "dynamic_import",
                        locator=f"line:{node.lineno}:{registry_target.rsplit('.', 1)[-1]}",
                        target=registry_target,
                        status="active_public",
                        evidence="runtime import is bounded by OWNER_MANIFEST_MODULES",
                    )
                    for registry_target in registry_targets
                )
                continue
            results.append(
                _entry(
                    category="dynamic_import_edge",
                    path=path_text,
                    symbol=_call_name(node) or "dynamic_import",
                    locator=f"line:{node.lineno}",
                    target=target or "dynamic-import",
                    status=(
                        "candidate-review"
                        if not target
                        else "active_public" if "data_center" in target else "adjacent_operational"
                    ),
                    evidence=(
                        "runtime-selected import target requires explicit registry review"
                        if not target
                        else "statically resolved dynamic import target"
                    ),
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


CELERY_TASK_DECORATOR_NAMES = frozenset(
    {
        "shared_task",
        "task",
        "typed_shared_task",
        "_typed_shared_task",
        "_celery_task",
    }
)


def _celery_decorator_names(tree: ast.Module) -> set[str]:
    """Return supported Celery decorator names, including import aliases."""

    names = set(CELERY_TASK_DECORATOR_NAMES)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name in CELERY_TASK_DECORATOR_NAMES:
                names.add(alias.asname or alias.name)
    return names


def _decorator_task_name(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    module_path: str,
    decorator_names: set[str],
) -> str:
    """Return Celery's explicit name or its default fully-qualified name."""

    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        decorator_name = (
            _call_name(call)
            if call is not None
            else (
                decorator.id
                if isinstance(decorator, ast.Name)
                else decorator.attr if isinstance(decorator, ast.Attribute) else ""
            )
        )
        if decorator_name not in decorator_names:
            continue
        if call is None:
            return f"{module_path}.{node.name}"
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
        decorator_names = _celery_decorator_names(tree)
        for node in _functions(tree):
            task_name = _decorator_task_name(
                node,
                module_path=module_path,
                decorator_names=decorator_names,
            )
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


def _defined_celery_tasks() -> dict[str, str]:
    """Return local function symbols mapped to their effective Celery task names."""

    tasks: dict[str, str] = {}
    for path in sorted((ROOT / "apps").glob("**/*.py")):
        if "migrations" in path.parts or "tests" in path.parts:
            continue
        path_text = _relative(path)
        module_path = path_text.removesuffix(".py").replace("/", ".")
        tree = _tree(path)
        decorator_names = _celery_decorator_names(tree)
        for node in _functions(tree):
            task_name = _decorator_task_name(
                node,
                module_path=module_path,
                decorator_names=decorator_names,
            )
            if task_name:
                tasks[f"{module_path}.{node.name}"] = task_name
    return tasks


def _resolve_task_receiver(
    receiver: ast.AST,
    *,
    module_path: str,
    imported: dict[str, str],
    defined_tasks: dict[str, str],
) -> str | None:
    """Resolve a direct task function receiver to its effective Celery name."""

    resolved = _resolved_dotted_name(receiver, imported)
    if resolved is None:
        return None
    if "." not in resolved:
        resolved = f"{module_path}.{resolved}"
    return defined_tasks.get(resolved, resolved if resolved in defined_tasks.values() else None)


def _discover_celery_dispatch_edges(celery: dict[str, Any]) -> list[dict[str, object]]:
    """Enumerate statically resolvable Celery enqueue and canvas dispatch edges."""

    governed = {
        str(item.get("task_path"))
        for item in celery.get("tasks", [])
        if isinstance(item, dict) and item.get("task_path")
    }
    defined_tasks = _defined_celery_tasks()
    results: list[dict[str, object]] = []
    for path in _production_python_files("apps", "core", "shared", "scripts"):
        path_text = _relative(path)
        module_path = path_text.removesuffix(".py").replace("/", ".")
        tree = _tree(path)
        imported = _imported_names(tree)
        constants = _module_string_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_name = _call_name(node)
            target = ""
            dispatch_kind = ""
            if call_name in {"send_task", "signature"}:
                dispatch_kind = call_name
                target = _resolved_string(node.args[0] if node.args else None, constants) or ""
            elif isinstance(node.func, ast.Attribute) and call_name in {
                "delay",
                "apply_async",
                "s",
                "si",
            }:
                dispatch_kind = call_name
                target = (
                    _resolve_task_receiver(
                        node.func.value,
                        module_path=module_path,
                        imported=imported,
                        defined_tasks=defined_tasks,
                    )
                    or ""
                )
            if not dispatch_kind or not target:
                continue
            results.append(
                _entry(
                    category="celery_dispatch_edge",
                    path=path_text,
                    symbol=dispatch_kind,
                    locator=f"line:{node.lineno}",
                    target=target,
                    status="active_public" if target in governed else "adjacent_operational",
                    evidence=(
                        "dispatch target is registered in governance/celery_task_contracts.json"
                        if target in governed
                        else "statically resolved Celery task dispatch"
                    ),
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


def _path_calls(path: Path) -> list[tuple[str, str, str, int]]:
    """Return literal Django URL patterns with their callback expressions."""

    results: list[tuple[str, str, str, int]] = []
    for node in ast.walk(_tree(path)):
        if (
            not isinstance(node, ast.Call)
            or _call_name(node) not in {"path", "re_path"}
            or len(node.args) < 2
        ):
            continue
        route = _literal_string(node.args[0])
        if route is None:
            continue
        name = ""
        for keyword in node.keywords:
            if keyword.arg == "name":
                name = _literal_string(keyword.value) or ""
        results.append((route, name, ast.unparse(node.args[1]), node.lineno))
    return results


def _action_metadata(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, str] | None:
    """Return DRF action URL path and methods for one decorated method."""

    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or _call_name(decorator) not in {
            "action",
            "typed_action",
        }:
            continue
        url_path = node.name.replace("_", "-")
        methods = "GET"
        for keyword in decorator.keywords:
            if keyword.arg == "url_path":
                url_path = _literal_string(keyword.value) or url_path
            elif keyword.arg == "methods" and isinstance(
                keyword.value, (ast.List, ast.Set, ast.Tuple)
            ):
                resolved = [
                    str(value).upper()
                    for item in keyword.value.elts
                    if (value := _literal_string(item)) is not None
                ]
                if resolved:
                    methods = ",".join(resolved)
        return url_path, methods
    return None


def _discover_cross_app_drf_actions() -> list[dict[str, object]]:
    """Keep cross-app HTTP consumers of Data Center visible as entrypoints."""

    results: list[dict[str, object]] = []
    for path in _production_python_files("apps"):
        path_text = _relative(path)
        if path_text.startswith("apps/data_center/"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "apps.data_center.application" not in text:
            continue
        tree = _tree(path)
        for node in _functions(tree):
            metadata = _action_metadata(node)
            if metadata is None:
                continue
            url_path, methods = metadata
            symbol = _function_symbol(node, tree)
            results.append(
                _entry(
                    category="rest_url",
                    path=path_text,
                    symbol=symbol,
                    locator=f"action:{url_path}:{methods}",
                    target=f"{path_text}::{symbol}",
                    status="adjacent_operational",
                    evidence="cross-app DRF action consumes the canonical Data Center port",
                )
            )
    return results


def _discover_rest_urls() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    owned_paths = (
        ROOT / "apps" / "data_center" / "interface" / "api_urls.py",
        ROOT / "apps" / "data_center" / "interface" / "urls.py",
    )
    for path in owned_paths:
        for route, name, callback, line in _path_calls(path):
            results.append(
                _entry(
                    category="rest_url",
                    path=_relative(path),
                    symbol=name or f"path@{line}",
                    locator=route,
                    target=callback,
                    status="active_public",
                    evidence="Data Center-owned URLconf",
                )
            )
    for path in sorted(ROOT.glob("**/urls.py")):
        if path in owned_paths or any(
            part in IGNORED_PATH_PARTS for part in path.relative_to(ROOT).parts
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "data-center" not in text and "apps.data_center" not in text:
            continue
        for route, name, callback, line in _path_calls(path):
            if "data-center" not in route:
                continue
            results.append(
                _entry(
                    category="rest_url",
                    path=_relative(path),
                    symbol=name or f"mount@{line}",
                    locator=route,
                    target=callback,
                    status="active_public",
                    evidence="project URL mount for Data Center",
                )
            )
    return results + _discover_cross_app_drf_actions()


def _sdk_http_target(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Resolve the first BaseModule HTTP call made by an SDK method."""

    methods = {
        "_get": "GET",
        "_post": "POST",
        "_put": "PUT",
        "_patch": "PATCH",
        "_delete": "DELETE",
    }
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not call.args:
            continue
        call_name = _call_name(call)
        if call_name not in methods:
            continue
        literal = _literal_string(call.args[0])
        route = literal if literal is not None else ast.unparse(call.args[0])
        return f"{methods[call_name]} /api/data-center/{route.lstrip('/')}"
    return "dynamic-sdk-http"


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
                    locator=_sdk_http_target(node).split(" ", 1)[0],
                    target=_sdk_http_target(node),
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
            delegated = re.search(r"\.data_center\.([A-Za-z_][A-Za-z0-9_]*)", body_text)
            results.append(
                _entry(
                    category="sdk",
                    path=_relative(path),
                    symbol=_function_symbol(node, tree),
                    locator=f"line:{node.lineno}",
                    target=(
                        f"DataCenterModule.{delegated.group(1)}"
                        if delegated
                        else "DataCenterModule.dynamic"
                    ),
                    status="compatibility",
                    evidence="SDK compatibility delegation to DataCenterModule",
                )
            )
    client_path = ROOT / "sdk" / "agomtradepro" / "client.py"
    for node in _functions(_tree(client_path)):
        if node.name != "data_center":
            continue
        results.append(
            _entry(
                category="sdk",
                path=_relative(client_path),
                symbol="AgomTradeProClient.data_center",
                locator=f"line:{node.lineno}",
                target="DataCenterModule",
                status="active_public",
                evidence="public SDK client property exposes the canonical Data Center module",
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
                    locator=f"line:{node.lineno}",
                    target=(
                        "register_data_center_tools"
                        if path.name == "data_center_tools.py"
                        else "AgomTradeProClient.data_center"
                    ),
                    status="compatibility",
                    evidence=(
                        "legacy Data Center tools are conditional on "
                        "AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS=false by default"
                        if path.name == "data_center_tools.py"
                        else "cross-owner MCP compatibility tool"
                    ),
                )
            )
    core_path = root / "core_tools.py"
    for node in _functions(_tree(core_path)):
        if not node.name.startswith("agom_"):
            continue
        results.append(
            _entry(
                category="mcp_tool",
                path=_relative(core_path),
                symbol=node.name,
                locator=f"line:{node.lineno}",
                target="CapabilityDispatcher:data_center",
                status="active_public",
                evidence="default-enabled core MCP ingress can dispatch Data Center capabilities",
            )
        )
    server_path = ROOT / "sdk" / "agomtradepro_mcp" / "server.py"
    results.extend(
        (
            _entry(
                category="mcp_tool",
                path=_relative(server_path),
                symbol="register_core_tools",
                locator="AGOMTRADEPRO_MCP_ENABLE_CORE_TOOLS=true",
                target="sdk/agomtradepro_mcp/tools/core_tools.py::register_core_tools",
                status="active_public",
                evidence="default-enabled MCP registrar edge",
            ),
            _entry(
                category="mcp_tool",
                path=_relative(server_path),
                symbol="register_data_center_tools",
                locator="AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS=false",
                target="sdk/agomtradepro_mcp/tools/data_center_tools.py::register_data_center_tools",
                status="compatibility",
                evidence="default-disabled legacy MCP registrar edge",
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
            or "data_task" in str(item.get("key", ""))
            or "market_thermometer" in str(item.get("key", ""))
        )
    }


def _tui_action_signature(item: dict[str, Any]) -> tuple[str, ...]:
    """Return the user-visible dispatch contract that generated/published must share."""

    return tuple(
        str(item.get(key, ""))
        for key in (
            "endpoint",
            "method",
            "intent",
            "request_schema_ref",
            "response_schema_ref",
        )
    )


def _nested_strings(value: object) -> set[str]:
    """Collect exact string values from one JSON-compatible object."""

    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set().union(*(_nested_strings(item) for item in value), set())
    if isinstance(value, dict):
        return set().union(*(_nested_strings(item) for item in value.values()), set())
    return set()


def _discover_terminal_tui() -> list[dict[str, object]]:
    published_path = ROOT / "config" / "tui" / "published" / "tui_operation_graph.published.json"
    generated_path = ROOT / "config" / "tui" / "generated" / "tui_operation_graph.generated.json"
    published = _load_json(published_path)
    generated = _load_json(generated_path)
    published_actions = _tui_actions(published)
    generated_actions = _tui_actions(generated)
    results: list[dict[str, object]] = []
    for key, item in sorted(generated_actions.items()):
        published_item = published_actions.get(key)
        is_published = published_item is not None
        contract_matches = is_published and _tui_action_signature(item) == _tui_action_signature(
            published_item
        )
        endpoint = str(item.get("endpoint", ""))
        results.append(
            _entry(
                category="terminal_tui",
                path=_relative(generated_path),
                symbol=key,
                locator=endpoint,
                target=endpoint or "dynamic-tui-endpoint",
                status="active_public" if contract_matches else "candidate-review",
                evidence=(
                    "published TUI operation graph with matching dispatch contract"
                    if contract_matches
                    else (
                        "generated/published TUI dispatch contracts differ"
                        if is_published
                        else "generated TUI action is not present in published graph"
                    )
                ),
            )
        )
    published_screens = {
        str(item.get("key")): item
        for item in published.get("screens", [])
        if isinstance(item, dict) and str(item.get("key", ""))
    }
    for screen in generated.get("screens", []):
        if not isinstance(screen, dict):
            continue
        screen_key = str(screen.get("key", ""))
        action_refs = sorted(_nested_strings(screen) & set(generated_actions))
        for action_key in action_refs:
            action = generated_actions[action_key]
            published_action = published_actions.get(action_key)
            contract_matches = published_action is not None and _tui_action_signature(
                action
            ) == _tui_action_signature(published_action)
            published_screen = published_screens.get(screen_key)
            published_refs = (
                _nested_strings(published_screen) if published_screen is not None else set()
            )
            active = contract_matches and action_key in published_refs
            endpoint = str(action.get("endpoint", ""))
            results.append(
                _entry(
                    category="terminal_tui",
                    path=_relative(generated_path),
                    symbol=screen_key,
                    locator=action_key,
                    target=endpoint or "dynamic-tui-endpoint",
                    status="active_public" if active else "candidate-review",
                    evidence=(
                        "published TUI screen-to-action dispatch edge"
                        if active
                        else "TUI screen/action edge is missing or differs in published graph"
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
    owner_index = (
        ROOT / "sdk" / "agomtradepro_mcp" / "registry" / "modules" / "owners" / "__init__.py"
    )
    loaded_modules = {
        node.value
        for node in ast.walk(_tree(owner_index))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("agomtradepro_mcp.registry.modules.owners.")
    }
    results: list[dict[str, object]] = []
    capability_root = ROOT / "sdk" / "agomtradepro_mcp" / "registry" / "modules" / "owners"
    for path in sorted(capability_root.glob("data_center_*_capabilities.py")):
        module_name = "agomtradepro_mcp.registry.modules.owners." + path.stem
        loaded = module_name in loaded_modules
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
                    target=handlers.get(executor_ref, executor_ref),
                    status="active_public" if wired and loaded else "candidate-review",
                    evidence=(
                        f"loaded owner shard and runtime handler registry: {handlers[executor_ref]}"
                        if wired and loaded
                        else (
                            "capability owner shard is absent from OWNER_MANIFEST_MODULES"
                            if not loaded
                            else "capability executor is absent from Data Center handler registries"
                        )
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
    _tree.cache_clear()
    try:
        legacy = _load_json(ROOT / "governance" / "data_center_legacy_entrypoints.json")
        celery = _load_json(ROOT / "governance" / "celery_task_contracts.json")
        current_data = _load_json(ROOT / "governance" / "current_data_contracts.json")
        runtime_config = _load_json(ROOT / "governance" / "runtime_config_contracts.json")
        operational = _load_json(ROOT / "governance" / "data_center_operational_entrypoints.json")
        entries = (
            _discover_scripts(legacy)
            + _discover_management_commands()
            + _discover_management_command_edges()
            + _discover_application_consumers()
            + _discover_admin_surfaces()
            + _discover_scheduler_writers()
            + _discover_orchestration_entries()
            + _discover_dynamic_import_edges()
            + _discover_celery_tasks(celery)
            + _discover_celery_dispatch_edges(celery)
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
            + _discover_operational_scripts()
            + _discover_operational_dispatch_edges()
            + _discover_workflow_steps()
            + _discover_test_and_migration_evidence()
            + _discover_runbooks()
            + _discover_agent_skills()
        )
        entries = _apply_operational_governance(entries, operational)
    finally:
        ROOT = previous_root
    ordered = sorted(
        entries,
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
            "retired_blocked": "known unsafe or obsolete operational path retained only as blocked evidence",
            "candidate-review": "discovered callable surface; discovery is not approval or completion",
        },
        "source_contracts": [
            "governance/celery_task_contracts.json",
            "governance/current_data_contracts.json",
            "governance/data_center_legacy_entrypoints.json",
            "governance/data_center_operational_entrypoints.json",
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
            "operational_governance_rules": len(operational.get("entries", [])),
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
        if category not in REQUIRED_CATEGORIES:
            violations.append(f"entry_category_invalid:{entry_id}:{category}")
        if not str(item.get("path", "")).strip():
            violations.append(f"entry_path_missing:{entry_id}")
        if not str(item.get("symbol", "")).strip():
            violations.append(f"entry_symbol_missing:{entry_id}")
        status = str(item.get("status", ""))
        if status not in STATUSES:
            violations.append(f"entry_status_invalid:{entry_id}:{status}")
        if not str(item.get("evidence", "")).strip():
            violations.append(f"entry_evidence_missing:{entry_id}")
        if (
            category
            in {
                "beat_schedule",
                "admin_surface",
                "capability_runtime",
                "celery_dispatch_edge",
                "celery_task",
                "dynamic_import_edge",
                "management_command_edge",
                "mcp_tool",
                "operational_dispatch_edge",
                "rest_url",
                "scheduler_writer",
                "sdk",
                "terminal_tui",
                "workflow_step",
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
