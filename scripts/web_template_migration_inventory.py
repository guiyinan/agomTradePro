#!/usr/bin/env python3
"""Build and validate the Web-to-TUI template migration inventory.

The inventory combines four evidence sources:

1. Filesystem discovery for the complete template population.
2. Django's URL resolver for the active route graph.
3. Django's template loader for the effective template origin.
4. Static AST/template parsing for dependencies and runtime features.

Static parsing is deliberately treated as supporting evidence. A template is
only classified as a shadow deletion candidate when Django resolves the same
logical template name to a different repository file.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import inspect
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence, cast
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_PATH = ROOT / "config" / "tui" / "migration" / "web_template_migration.v1.json"
DEFAULT_OUTPUT_PATH = ROOT / "docs" / "plans" / "web-to-tui-migration-matrix-2026-07-25.csv"
DEFAULT_PUBLISHED_GRAPH_PATH = (
    ROOT / "config" / "tui" / "published" / "tui_operation_graph.published.json"
)
FINAL_RETAINED_TEMPLATE_COUNT = 41
_PRODUCTION_TEXT_SUFFIXES = frozenset(
    {".css", ".html", ".js", ".json", ".py", ".ts", ".yaml", ".yml"}
)
_PRODUCTION_REFERENCE_ROOTS = (
    "apps",
    "core",
    "shared",
    "static",
    "packages",
    "sdk",
)

MATRIX_FIELDS = (
    "template_path",
    "template_name",
    "template_role",
    "owner_app",
    "content_hash",
    "url_name",
    "url_path_pattern",
    "view_callable",
    "http_methods",
    "resolved_template_origin",
    "extends",
    "includes",
    "consumers",
    "related_static_assets",
    "email_or_task_usage",
    "primary_task",
    "audience",
    "auth_required",
    "permission_rule",
    "write_effects",
    "current_api_endpoints",
    "inline_script",
    "upload_download",
    "streaming_or_polling",
    "api_gap",
    "destination_class",
    "destination_reason",
    "target_screen_key",
    "target_action_keys",
    "target_panel_keys",
    "wave",
    "legacy_url_policy",
    "redirect_target",
    "rollback_commit",
    "graph_hash",
    "compatibility_note",
    "unit_tests",
    "api_contract_tests",
    "playwright_uat",
    "task_parity_status",
    "observability_evidence",
    "status",
    "owner",
    "reviewer",
    "last_reviewed_at",
    "exception_expiry",
    "notes",
)

REFRESHED_FACT_FIELDS = (
    "template_name",
    "content_hash",
    "url_name",
    "url_path_pattern",
    "view_callable",
    "http_methods",
    "resolved_template_origin",
    "extends",
    "includes",
    "consumers",
    "related_static_assets",
    "email_or_task_usage",
    "current_api_endpoints",
    "inline_script",
    "upload_download",
    "streaming_or_polling",
    "graph_hash",
    "compatibility_note",
)

_EXTENDS_RE = re.compile(r"""{%\s*extends\s+["']([^"']+)["']\s*%}""")
_INCLUDE_RE = re.compile(r"""{%\s*include\s+["']([^"']+)["']""")
_STATIC_RE = re.compile(r"""{%\s*static\s+["']([^"']+)["']\s*%}""")
_API_RE = re.compile(r"""["'](/api/[A-Za-z0-9_./{}<>\-]+)["']""")
_INLINE_SCRIPT_RE = re.compile(
    r"<script\b(?:(?!\bsrc\s*=)[^>])*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_WRITE_METHOD_RE = re.compile(
    r"""request\.method\s*(?:==|in)\s*(?:["'](POST|PUT|PATCH|DELETE)["']|\(([^)]*)\))""",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class TemplateFacts:
    """Static facts extracted from one HTML template."""

    extends: tuple[str, ...]
    includes: tuple[str, ...]
    api_endpoints: tuple[str, ...]
    static_assets: tuple[str, ...]
    has_inline_script: bool
    is_chart_heavy: bool
    has_upload_download: bool
    has_streaming_or_polling: bool


@dataclass(frozen=True)
class SourceReference:
    """A literal Python reference to a Django template."""

    module: str
    symbol: str
    source_path: str
    line: int


@dataclass(frozen=True)
class RouteRecord:
    """A flattened Django URL pattern and its callable identity."""

    path: str
    name: str
    module: str
    symbol: str
    callable_name: str
    methods: tuple[str, ...]


class _TemplateReferenceVisitor(ast.NodeVisitor):
    """Collect literal ``*.html`` values with their owning symbol."""

    def __init__(self, module: str, source_path: str) -> None:
        self.module = module
        self.source_path = source_path
        self.symbol_stack: list[str] = []
        self.references: list[tuple[str, SourceReference]] = []
        self.calls: dict[str, set[str]] = defaultdict(set)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Treat templates inside methods as owned by the view class."""
        self.symbol_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self.symbol_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Treat module functions as route symbols and methods as class-owned."""
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Apply shared ownership traversal to synchronous and async functions."""

        pushed = not self.symbol_stack
        if pushed:
            self.symbol_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        if pushed:
            self.symbol_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Apply the same ownership rule to async views."""
        self._visit_function(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        """Record literal template names without guessing call semantics."""
        if isinstance(node.value, str) and node.value.strip().endswith(".html"):
            template_name = node.value.strip().replace("\\", "/")
            reference = SourceReference(
                module=self.module,
                symbol=self.symbol_stack[0] if self.symbol_stack else "",
                source_path=self.source_path,
                line=node.lineno,
            )
            self.references.append((template_name, reference))

    def visit_Call(self, node: ast.Call) -> None:
        """Record same-module helper/view calls for route-template propagation."""
        if self.symbol_stack:
            called_symbol = ""
            if isinstance(node.func, ast.Name):
                called_symbol = node.func.id
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "as_view"
                and isinstance(node.func.value, ast.Name)
            ):
                called_symbol = node.func.value.id
            if called_symbol:
                self.calls[self.symbol_stack[0]].add(called_symbol)
        self.generic_visit(node)


def load_rules(root: Path = ROOT, rules_path: Path | None = None) -> dict[str, Any]:
    """Load the versioned migration inventory rules."""
    path = rules_path or root / DEFAULT_RULES_PATH.relative_to(ROOT)
    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ValueError(f"Migration inventory rules must be a JSON object: {path}")
    return cast(dict[str, Any], payload)


def discover_template_paths(root: Path = ROOT) -> list[Path]:
    """Return every project-owned Django HTML template in stable order."""
    paths = list((root / "core" / "templates").rglob("*.html"))
    paths.extend(
        path
        for path in (root / "apps").rglob("*.html")
        if "templates" in path.relative_to(root).parts
    )
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def logical_template_name(root: Path, path: Path) -> str:
    """Return the Django loader name for a physical template path."""
    relative = path.relative_to(root)
    parts = relative.parts
    template_index = parts.index("templates")
    return Path(*parts[template_index + 1 :]).as_posix()


def owner_for_template(template_path: str) -> str:
    """Infer the app/domain owner from a repository-relative template path."""
    parts = Path(template_path).parts
    if parts[0] == "apps":
        return parts[1]
    if parts[:2] == ("core", "templates") and len(parts) > 3:
        return parts[2]
    return "core"


def classify_template_role(template_path: str) -> str:
    """Classify a template as a route page or supporting artifact."""
    normalized = template_path.replace("\\", "/")
    name = Path(normalized).name.lower()
    if name in {"404.html", "500.html"}:
        return "error"
    if (
        "/components/" in normalized
        or "/partials/" in normalized
        or "/steps/" in normalized
        or name.startswith("_")
        or name.endswith(("_panel.html", "_table.html", "_modal.html"))
    ):
        return "partial_component"
    if name in {"base.html", "base_auth.html"}:
        return "layout"
    return "route_page"


def parse_template_facts(
    path: Path,
    *,
    chart_markers: Sequence[str],
) -> TemplateFacts:
    """Extract dependencies and browser-runtime features from one template."""
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    markers = tuple(marker.lower() for marker in chart_markers)
    return TemplateFacts(
        extends=tuple(sorted(set(_EXTENDS_RE.findall(text)))),
        includes=tuple(sorted(set(_INCLUDE_RE.findall(text)))),
        api_endpoints=tuple(sorted(set(_API_RE.findall(text)))),
        static_assets=tuple(sorted(set(_STATIC_RE.findall(text)))),
        has_inline_script=bool(_INLINE_SCRIPT_RE.search(text)),
        is_chart_heavy=any(marker in lowered for marker in markers),
        has_upload_download=any(
            marker in lowered
            for marker in (
                'type="file"',
                "formdata(",
                "download",
                "export",
                "导入",
                "导出",
                "上传",
                "下载",
            )
        ),
        has_streaming_or_polling=any(
            marker in lowered
            for marker in ("eventsource(", "websocket(", "setinterval(", 'hx-trigger="every')
        ),
    )


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _iter_python_sources(root: Path) -> Iterable[Path]:
    for base_name in ("apps", "core", "shared"):
        for path in (root / base_name).rglob("*.py"):
            relative_parts = path.relative_to(root).parts
            if (
                "migrations" in relative_parts
                or "tests" in relative_parts
                or "__pycache__" in relative_parts
            ):
                continue
            yield path


def extract_python_template_references(
    root: Path = ROOT,
) -> dict[str, list[SourceReference]]:
    """Extract literal template references from project Python sources."""
    references: dict[str, list[SourceReference]] = defaultdict(list)
    for path in _iter_python_sources(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        visitor = _TemplateReferenceVisitor(
            module=_module_name(root, path),
            source_path=path.relative_to(root).as_posix(),
        )
        visitor.visit(tree)
        direct_by_symbol: dict[str, list[tuple[str, SourceReference]]] = defaultdict(list)
        for template_name, reference in visitor.references:
            direct_by_symbol[reference.symbol].append((template_name, reference))
            references[template_name].append(reference)

        for owner_symbol in visitor.calls:
            pending = list(visitor.calls[owner_symbol])
            visited: set[str] = set()
            while pending:
                called_symbol = pending.pop()
                if called_symbol in visited:
                    continue
                visited.add(called_symbol)
                pending.extend(visitor.calls.get(called_symbol, set()))
                for template_name, reference in direct_by_symbol.get(called_symbol, []):
                    references[template_name].append(
                        SourceReference(
                            module=reference.module,
                            symbol=owner_symbol,
                            source_path=reference.source_path,
                            line=reference.line,
                        )
                    )
    return dict(references)


def _callable_identity(callback: Any) -> tuple[str, str, str, tuple[str, ...]]:
    declared_target = getattr(callback, "view_class", None) or getattr(callback, "cls", None)
    target = declared_target
    callback_symbol = str(getattr(callback, "__name__", ""))
    if target is None:
        try:
            target = inspect.unwrap(callback)
        except (ValueError, TypeError):
            target = callback
    module = str(getattr(target, "__module__", getattr(callback, "__module__", "")))
    target_symbol = (
        str(getattr(target, "__name__", ""))
        or str(getattr(target, "__qualname__", "")).split(".")[0]
    )
    symbol = target_symbol if declared_target is not None else callback_symbol or target_symbol
    callable_name = f"{module}.{symbol}".strip(".")

    actions = getattr(callback, "actions", None)
    if isinstance(actions, dict):
        methods = tuple(sorted(str(method).upper() for method in actions))
    else:
        allowed_methods = getattr(callback, "allowed_methods", None)
        if allowed_methods:
            methods = tuple(sorted(str(method).upper() for method in allowed_methods))
        elif inspect.isclass(target):
            methods = tuple(
                method.upper()
                for method in ("get", "post", "put", "patch", "delete")
                if method in target.__dict__
            )
        else:
            methods = _methods_from_function(target)
    return module, symbol, callable_name, methods or ("GET",)


def _methods_from_function(target: Any) -> tuple[str, ...]:
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError):
        return ("GET",)
    methods = {"GET"}
    for match in _WRITE_METHOD_RE.finditer(source):
        direct_method = match.group(1)
        if direct_method:
            methods.add(direct_method.upper())
        for value in re.findall(r"""["'](POST|PUT|PATCH|DELETE)["']""", match.group(2) or ""):
            methods.add(value.upper())
    return tuple(sorted(methods))


def extract_django_routes() -> list[RouteRecord]:
    """Flatten the active Django URL resolver using production route semantics."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import django
    from django.urls import URLPattern, URLResolver, get_resolver

    django.setup()
    records: list[RouteRecord] = []

    def collect(
        patterns: Sequence[URLPattern | URLResolver],
        *,
        prefix: str = "",
        namespaces: tuple[str, ...] = (),
    ) -> None:
        for pattern in patterns:
            route_path = f"{prefix}{pattern.pattern}"
            if isinstance(pattern, URLResolver):
                namespace = pattern.namespace or ""
                next_namespaces = namespaces + ((namespace,) if namespace else ())
                collect(
                    pattern.url_patterns,
                    prefix=route_path,
                    namespaces=next_namespaces,
                )
                continue

            module, symbol, callable_name, methods = _callable_identity(pattern.callback)
            local_name = pattern.name or ""
            full_name = ":".join((*namespaces, local_name)) if local_name else ""
            normalized_path = route_path.replace("^", "").replace("$", "")
            records.append(
                RouteRecord(
                    path=f"/{normalized_path.lstrip('/')}",
                    name=full_name,
                    module=module,
                    symbol=symbol,
                    callable_name=callable_name,
                    methods=methods,
                )
            )

    collect(get_resolver().url_patterns)
    return records


def _retained_rule(
    template_path: str,
    rules: dict[str, Any],
) -> dict[str, Any] | None:
    for rule in rules["retained_rules"]:
        exact_paths = {str(value) for value in rule.get("exact_paths", [])}
        prefix = str(rule.get("path_prefix", ""))
        if template_path in exact_paths or (prefix and template_path.startswith(prefix)):
            return cast(dict[str, Any], rule)
    return None


def _normalize_origin(root: Path, origin: str) -> str:
    if not origin:
        return ""
    path = Path(origin).resolve()
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_template_origins(
    root: Path,
    template_names: Iterable[str],
) -> dict[str, str]:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    import django
    from django.template import engines

    django.setup()
    engine = engines["django"].engine
    origins: dict[str, str] = {}
    for template_name in sorted(set(template_names)):
        resolved_origin = ""
        for loader in engine.template_loaders:
            for origin in loader.get_template_sources(template_name):
                candidate = str(getattr(origin, "name", ""))
                if candidate and Path(candidate).is_file():
                    resolved_origin = _normalize_origin(root, candidate)
                    break
            if resolved_origin:
                break
        origins[template_name] = resolved_origin or f"unresolved:{template_name}"
    return origins


def _route_lookup(
    routes: Sequence[RouteRecord],
    references: dict[str, list[SourceReference]],
) -> dict[str, list[RouteRecord]]:
    routes_by_symbol: dict[tuple[str, str], list[RouteRecord]] = defaultdict(list)
    for route in routes:
        routes_by_symbol[(route.module, route.symbol)].append(route)

    result: dict[str, list[RouteRecord]] = defaultdict(list)
    for template_name, template_references in references.items():
        for reference in template_references:
            for route in routes_by_symbol.get((reference.module, reference.symbol), []):
                result[template_name].append(route)
    return {
        key: sorted(
            {route for route in values},
            key=lambda route: (route.path, route.name, route.callable_name),
        )
        for key, values in result.items()
    }


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _join(values: Iterable[str]) -> str:
    return ";".join(sorted({value for value in values if value}))


def _runtime_compatibility(root: Path) -> tuple[str, str]:
    graph_path = root / "config" / "tui" / "published" / "tui_operation_graph.published.json"
    manifest_path = root / "config" / "tui" / "agomtui-runtime.manifest.json"
    graph_payload = json.loads(graph_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    graph_hash = _hash_file(graph_path)
    compatibility = (
        f"schema={graph_payload.get('schema_version', '')};"
        f"runtime={manifest.get('build_id', '')};"
        f"ia={graph_payload.get('ia_version', '')}"
    )
    return graph_hash, compatibility


def build_inventory(
    root: Path = ROOT,
    *,
    rules: dict[str, Any] | None = None,
    resolve_django: bool = True,
) -> list[dict[str, str]]:
    """Build deterministic migration rows for all project templates."""
    active_rules = rules or load_rules(root)
    paths = discover_template_paths(root)
    chart_markers = tuple(str(value) for value in active_rules["chart_markers"])
    facts_by_path = {
        path: parse_template_facts(path, chart_markers=chart_markers) for path in paths
    }
    template_name_by_path = {path: logical_template_name(root, path) for path in paths}
    references = extract_python_template_references(root)
    routes = extract_django_routes() if resolve_django else []
    routes_by_template = _route_lookup(routes, references)
    origins = (
        _resolve_template_origins(root, template_name_by_path.values())
        if resolve_django
        else {
            name: template_path.relative_to(root).as_posix()
            for template_path, name in template_name_by_path.items()
        }
    )

    consumer_paths: dict[str, list[str]] = defaultdict(list)
    for path, facts in facts_by_path.items():
        consumer = path.relative_to(root).as_posix()
        for dependency in (*facts.extends, *facts.includes):
            consumer_paths[dependency].append(consumer)

    graph_hash, compatibility_note = _runtime_compatibility(root)
    screen_by_owner = {
        str(key): str(value) for key, value in active_rules["screen_by_owner"].items()
    }
    m2_owners = {str(value) for value in active_rules["m2_owners"]}
    admin_owners = {str(value) for value in active_rules["admin_owners"]}

    rows: list[dict[str, str]] = []
    for path in paths:
        template_path = path.relative_to(root).as_posix()
        template_name = template_name_by_path[path]
        facts = facts_by_path[path]
        retained_rule = _retained_rule(template_path, active_rules)
        owner = str(retained_rule["owner"]) if retained_rule else owner_for_template(template_path)
        role = (
            str(retained_rule["template_role"])
            if retained_rule
            else classify_template_role(template_path)
        )
        resolved_origin = origins[template_name]
        is_shadow = (
            not resolved_origin.startswith("unresolved:")
            and resolved_origin != template_path
            and resolved_origin.startswith(("core/", "apps/"))
        )
        if retained_rule:
            destination_class = "C"
            destination_reason = str(retained_rule["reason"])
        elif is_shadow:
            destination_class = "D"
            destination_reason = f"Django loader resolves to {resolved_origin}"
        elif facts.is_chart_heavy:
            destination_class = "B"
            destination_reason = "检测到生产图表/Canvas 标记，依赖 M1 renderer 契约。"
        else:
            destination_class = "A"
            destination_reason = "适合通过既有或补齐后的 JSON API 迁入 TUI。"

        target_screen = screen_by_owner.get(owner, "") if destination_class in {"A", "B"} else ""
        if destination_class == "C":
            wave = "retained"
        elif destination_class == "D":
            wave = "M0-D"
        elif destination_class == "B":
            wave = "M4"
        elif owner in m2_owners:
            wave = "M2"
        else:
            wave = "M3"

        template_routes = routes_by_template.get(template_name, [])
        methods = {method for route in template_routes for method in route.methods}
        write_effects = _join(method for method in methods if method != "GET") or "none_detected"
        source_references = references.get(template_name, [])
        email_or_task_usage = _join(
            f"{reference.source_path}:{reference.line}"
            for reference in source_references
            if any(
                marker in reference.source_path.lower()
                for marker in ("task", "email", "notification", "report")
            )
        )
        audience = "admin" if owner in admin_owners else "authenticated"
        if retained_rule and role == "external":
            audience = "external_or_mixed"

        if destination_class == "C":
            legacy_url_policy = "retain"
        elif destination_class == "D":
            legacy_url_policy = "remove_404"
        elif role == "route_page":
            legacy_url_policy = "redirect_to_tui"
        else:
            legacy_url_policy = "remove_with_consumer"

        redirect_target = (
            f"/tui/?screen={quote(target_screen)}"
            if legacy_url_policy == "redirect_to_tui" and target_screen
            else ""
        )
        primary_task = (
            f"{owner}: {Path(template_name).stem.replace('_', ' ').replace('-', ' ')}"
            if role == "route_page"
            else ""
        )
        api_gap = (
            "none_detected"
            if facts.api_endpoints
            else ("review_required" if destination_class in {"A", "B"} else "not_applicable")
        )
        status = (
            "retained"
            if destination_class == "C"
            else ("deletion_candidate" if destination_class == "D" else "inventory_review")
        )
        rows.append(
            {
                "template_path": template_path,
                "template_name": template_name,
                "template_role": role,
                "owner_app": owner,
                "content_hash": _hash_file(path),
                "url_name": _join(route.name for route in template_routes),
                "url_path_pattern": _join(route.path for route in template_routes),
                "view_callable": _join(route.callable_name for route in template_routes),
                "http_methods": _join(methods) or "unknown",
                "resolved_template_origin": resolved_origin,
                "extends": _join(facts.extends),
                "includes": _join(facts.includes),
                "consumers": _join(consumer_paths.get(template_name, [])),
                "related_static_assets": _join(facts.static_assets),
                "email_or_task_usage": email_or_task_usage,
                "primary_task": primary_task,
                "audience": audience,
                "auth_required": "unknown" if audience == "external_or_mixed" else "true",
                "permission_rule": f"{owner}.backend_authorization",
                "write_effects": write_effects,
                "current_api_endpoints": _join(facts.api_endpoints),
                "inline_script": str(facts.has_inline_script).lower(),
                "upload_download": str(facts.has_upload_download).lower(),
                "streaming_or_polling": str(facts.has_streaming_or_polling).lower(),
                "api_gap": api_gap,
                "destination_class": destination_class,
                "destination_reason": destination_reason,
                "target_screen_key": target_screen,
                "target_action_keys": "",
                "target_panel_keys": "",
                "wave": wave,
                "legacy_url_policy": legacy_url_policy,
                "redirect_target": redirect_target,
                "rollback_commit": "",
                "graph_hash": graph_hash,
                "compatibility_note": compatibility_note,
                "unit_tests": "",
                "api_contract_tests": "",
                "playwright_uat": "",
                "task_parity_status": "not_started",
                "observability_evidence": "",
                "status": status,
                "owner": owner,
                "reviewer": "",
                "last_reviewed_at": "",
                "exception_expiry": "",
                "notes": _join(
                    f"{reference.source_path}:{reference.line}" for reference in source_references
                ),
            }
        )
    return rows


def validate_inventory(
    rows: Sequence[dict[str, str]],
    *,
    rules: dict[str, Any],
) -> None:
    """Validate inventory completeness, retained counts, and target routing."""
    expected_count = int(rules["expected_template_count"])
    if len(rows) != expected_count:
        raise ValueError(f"Expected {expected_count} templates, found {len(rows)}")

    paths = [row["template_path"] for row in rows]
    if len(paths) != len(set(paths)):
        raise ValueError("Template inventory contains duplicate physical paths")

    destinations = {"A", "B", "C", "D"}
    unknown_destinations = {
        row["destination_class"] for row in rows if row["destination_class"] not in destinations
    }
    if unknown_destinations:
        raise ValueError(f"Unknown destination classes: {sorted(unknown_destinations)}")

    by_path = {row["template_path"]: row for row in rows}
    for rule in rules["retained_rules"]:
        matching_paths = [
            path
            for path in paths
            if path in {str(value) for value in rule.get("exact_paths", [])}
            or (str(rule.get("path_prefix", "")) and path.startswith(str(rule["path_prefix"])))
        ]
        expected_rule_count = int(rule["expected_count"])
        if len(matching_paths) != expected_rule_count:
            raise ValueError(
                f"Retained rule {rule['key']} expected {expected_rule_count}, "
                f"found {len(matching_paths)}"
            )
        if any(by_path[path]["destination_class"] != "C" for path in matching_paths):
            raise ValueError(f"Retained rule {rule['key']} contains a non-C row")

    for row in rows:
        if not row["content_hash"] or not row["resolved_template_origin"]:
            raise ValueError(f"Missing evidence for {row['template_path']}")
        if (
            row["template_role"] == "route_page"
            and row["destination_class"] in {"A", "B"}
            and not row["target_screen_key"]
        ):
            raise ValueError(f"Missing target screen for {row['template_path']}")


def write_inventory(rows: Sequence[dict[str, str]], output_path: Path) -> None:
    """Write inventory rows as deterministic UTF-8 CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MATRIX_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_inventory(path: Path) -> list[dict[str, str]]:
    """Read an existing migration CSV."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def check_inventory_file(
    root: Path,
    *,
    rules: dict[str, Any],
    inventory_path: Path,
) -> None:
    """Check that the reviewed matrix still covers the current template set."""
    reviewed_rows = read_inventory(inventory_path)
    validate_inventory(reviewed_rows, rules=rules)
    current_paths = {path.relative_to(root).as_posix() for path in discover_template_paths(root)}
    reviewed_paths = {row["template_path"] for row in reviewed_rows}
    active_reviewed_paths = {
        row["template_path"] for row in reviewed_rows if row["status"] != "deleted"
    }
    added = sorted(current_paths - reviewed_paths)
    removed_without_evidence = sorted(active_reviewed_paths - current_paths)
    undeleted_files = sorted(
        row["template_path"]
        for row in reviewed_rows
        if row["status"] == "deleted" and row["template_path"] in current_paths
    )
    if added or removed_without_evidence or undeleted_files:
        raise ValueError(
            "Template freeze violation. "
            f"Unreviewed additions={added}; "
            f"missing without deleted status={removed_without_evidence}; "
            f"deleted rows still on disk={undeleted_files}"
        )


def _split_values(value: str) -> set[str]:
    """Return normalized values from one semicolon-delimited matrix field."""

    return {item.strip() for item in value.split(";") if item.strip()}


def _production_text_paths(root: Path) -> list[Path]:
    """Return deterministic live source paths used for literal-consumer checks."""

    paths: set[Path] = set()
    for root_name in _PRODUCTION_REFERENCE_ROOTS:
        source_root = root / root_name
        if not source_root.is_dir():
            continue
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _PRODUCTION_TEXT_SUFFIXES:
                continue
            parts = path.relative_to(root).parts
            if any(part in {"__pycache__", "migrations", "tests"} for part in parts):
                continue
            paths.add(path)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def _literal_consumers(
    root: Path,
    values: set[str],
    *,
    excluded_paths: set[Path] | None = None,
) -> dict[str, set[str]]:
    """Find exact literal consumers of bounded identifiers in live source files."""

    consumers: dict[str, set[str]] = {value: set() for value in values}
    excluded = {path.resolve() for path in (excluded_paths or set())}
    for path in _production_text_paths(root):
        if path.resolve() in excluded:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(root).as_posix()
        for value in values:
            if value in text:
                consumers[value].add(relative)
    return consumers


def _static_asset_paths(root: Path, assets: set[str]) -> dict[str, set[Path]]:
    """Resolve matrix static names to physical files under supported static roots."""

    static_roots = [root / "static", root / "core" / "static"]
    apps_root = root / "apps"
    if apps_root.is_dir():
        static_roots.extend(path / "static" for path in apps_root.iterdir() if path.is_dir())
    resolved: dict[str, set[Path]] = {asset: set() for asset in assets}
    for static_root in static_roots:
        if not static_root.is_dir():
            continue
        for asset in assets:
            candidate = (static_root / asset).resolve()
            if candidate.is_relative_to(static_root.resolve()) and candidate.is_file():
                resolved[asset].add(candidate)
    return resolved


def _orphan_static_assets(root: Path, rows: Sequence[dict[str, str]]) -> list[str]:
    """Return physical static assets consumed only by finalized-away templates."""

    removed_assets = {
        asset
        for row in rows
        if row["destination_class"] != "C"
        for asset in _split_values(row["related_static_assets"])
    }
    physical = _static_asset_paths(root, removed_assets)
    existing_assets = {asset for asset, paths in physical.items() if paths}
    excluded = {path for paths in physical.values() for path in paths}
    consumers = _literal_consumers(root, existing_assets, excluded_paths=excluded)
    return sorted(asset for asset in existing_assets if not consumers[asset])


def _legacy_alias_violations(
    root: Path,
    *,
    graph_path: Path,
) -> tuple[list[str], list[str]]:
    """Return dangling and source-unreferenced published legacy screen aliases."""

    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Published TUI graph must be a JSON object")
    aliases_value = payload.get("legacy_screen_aliases")
    screens_value = payload.get("screens")
    if not isinstance(aliases_value, dict) or not isinstance(screens_value, list):
        raise ValueError("Published TUI graph lacks screens or legacy_screen_aliases")
    aliases = {
        str(source).strip(): str(target).strip()
        for source, target in aliases_value.items()
        if str(source).strip() and str(target).strip()
    }
    if len(aliases) != len(aliases_value):
        raise ValueError("Published legacy_screen_aliases contains blank keys or targets")
    screen_keys = {
        str(screen.get("key") or "").strip()
        for screen in screens_value
        if isinstance(screen, dict) and str(screen.get("key") or "").strip()
    }
    dangling = sorted(
        source
        for source, target in aliases.items()
        if source == target
        or source in screen_keys
        or target not in screen_keys
        or target in aliases
    )
    references = _literal_consumers(root, set(aliases), excluded_paths={graph_path})
    dead = sorted(source for source in aliases if not references[source])
    return dangling, dead


def validate_finalized_inventory(
    root: Path,
    rows: Sequence[dict[str, str]],
    *,
    rules: dict[str, Any],
    graph_path: Path,
    template_references: dict[str, list[SourceReference]] | None = None,
    routes: Sequence[RouteRecord] | None = None,
) -> None:
    """Require the exact M5-C physical inventory and absence of orphaned surfaces."""

    retained_count = sum(int(rule["expected_count"]) for rule in rules["retained_rules"])
    if retained_count != FINAL_RETAINED_TEMPLATE_COUNT:
        raise ValueError(
            "Final retained rules drifted from the approved 41-template scope: "
            f"configured={retained_count}"
        )
    retained_rows = [row for row in rows if row["destination_class"] == "C"]
    if len(retained_rows) != FINAL_RETAINED_TEMPLATE_COUNT:
        raise ValueError(
            "Final inventory must contain exactly 41 C rows: " f"found={len(retained_rows)}"
        )
    invalid_statuses = sorted(
        row["template_path"]
        for row in rows
        if (row["destination_class"] == "C" and row["status"] != "retained")
        or (row["destination_class"] != "C" and row["status"] != "deleted")
    )
    if invalid_statuses:
        raise ValueError(f"Final lifecycle statuses are incomplete: {invalid_statuses}")

    expected_physical = {row["template_path"] for row in retained_rows}
    current_physical = {path.relative_to(root).as_posix() for path in discover_template_paths(root)}
    missing_retained = sorted(expected_physical - current_physical)
    unexpected_physical = sorted(current_physical - expected_physical)
    if missing_retained or unexpected_physical or len(current_physical) != 41:
        raise ValueError(
            "Final physical template inventory is not the exact C scope. "
            f"physical={len(current_physical)}; missing_C={missing_retained}; "
            f"non_C_remaining={unexpected_physical}"
        )

    retained_names = {row["template_name"] for row in retained_rows}
    removed_names = {
        row["template_name"]
        for row in rows
        if row["destination_class"] != "C" and row["template_name"] not in retained_names
    }
    references = template_references or extract_python_template_references(root)
    orphan_references = sorted(
        f"{reference.source_path}:{reference.line}:{template_name}"
        for template_name in removed_names
        for reference in references.get(template_name, [])
    )
    active_routes = list(routes) if routes is not None else extract_django_routes()
    route_lookup = _route_lookup(active_routes, references)
    orphan_routes = sorted(
        f"{route.path}:{route.callable_name}:{template_name}"
        for template_name in removed_names
        for route in route_lookup.get(template_name, [])
    )
    orphan_static = _orphan_static_assets(root, rows)
    dangling_aliases, dead_aliases = _legacy_alias_violations(root, graph_path=graph_path)
    if orphan_references or orphan_routes or orphan_static or dangling_aliases or dead_aliases:
        raise ValueError(
            "Final orphan cleanup is incomplete. "
            f"template_references={orphan_references}; routes={orphan_routes}; "
            f"static_assets={orphan_static}; dangling_aliases={dangling_aliases}; "
            f"dead_aliases={dead_aliases}"
        )


def check_finalized_inventory_file(
    root: Path,
    *,
    rules: dict[str, Any],
    inventory_path: Path,
    graph_path: Path = DEFAULT_PUBLISHED_GRAPH_PATH,
) -> None:
    """Run the normal freeze check plus the stricter M5-C finalization gate."""

    check_inventory_file(root, rules=rules, inventory_path=inventory_path)
    validate_finalized_inventory(
        root,
        read_inventory(inventory_path),
        rules=rules,
        graph_path=graph_path,
    )


def refresh_inventory_file(
    root: Path,
    *,
    rules: dict[str, Any],
    inventory_path: Path,
) -> list[dict[str, str]]:
    """Refresh machine-derived facts while preserving reviewed lifecycle fields."""
    reviewed_rows = read_inventory(inventory_path)
    current_rows = build_inventory(root, rules=rules, resolve_django=True)
    reviewed_by_path = {row["template_path"]: row for row in reviewed_rows}
    current_paths = {row["template_path"] for row in current_rows}
    unreviewed_additions = sorted(current_paths - set(reviewed_by_path))
    if unreviewed_additions:
        raise ValueError(
            f"Cannot refresh with unreviewed template additions: {unreviewed_additions}"
        )

    for current_row in current_rows:
        reviewed_row = reviewed_by_path[current_row["template_path"]]
        for field_name in REFRESHED_FACT_FIELDS:
            reviewed_row[field_name] = current_row[field_name]
    validate_inventory(reviewed_rows, rules=rules)
    write_inventory(reviewed_rows, inventory_path)
    return reviewed_rows


def _summary(rows: Sequence[dict[str, str]]) -> str:
    destinations = {
        destination: sum(row["destination_class"] == destination for row in rows)
        for destination in ("A", "B", "C", "D")
    }
    route_count = sum(row["template_role"] == "route_page" for row in rows)
    return f"templates={len(rows)} route_pages={route_count} " + " ".join(
        f"{key}={value}" for key, value in destinations.items()
    )


def main() -> int:
    """CLI entry point for refreshing or checking the M0 inventory."""
    parser = argparse.ArgumentParser(
        description="Build or validate the Web-to-TUI migration inventory."
    )
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--graph", type=Path, default=DEFAULT_PUBLISHED_GRAPH_PATH)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Regenerate the inventory CSV")
    mode.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh machine facts while preserving reviewed lifecycle fields",
    )
    mode.add_argument("--check", action="store_true", help="Validate the reviewed inventory")
    mode.add_argument(
        "--require-finalized",
        action="store_true",
        help="Require the exact 41-template M5-C inventory and no orphaned surfaces",
    )
    args = parser.parse_args()

    rules = load_rules(ROOT, args.rules.resolve())
    output_path = args.output.resolve()
    try:
        if args.write:
            rows = build_inventory(ROOT, rules=rules, resolve_django=True)
            validate_inventory(rows, rules=rules)
            write_inventory(rows, output_path)
        elif args.refresh:
            rows = refresh_inventory_file(
                ROOT,
                rules=rules,
                inventory_path=output_path,
            )
        elif args.check:
            check_inventory_file(ROOT, rules=rules, inventory_path=output_path)
            rows = read_inventory(output_path)
        else:
            check_finalized_inventory_file(
                ROOT,
                rules=rules,
                inventory_path=output_path,
                graph_path=args.graph.resolve(),
            )
            rows = read_inventory(output_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Web-to-TUI inventory check failed: {exc}", file=sys.stderr)
        return 1

    print(f"Web-to-TUI inventory OK: {_summary(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
