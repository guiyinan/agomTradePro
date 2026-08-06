"""Enforce the single reliability status source and governed block reasons."""

from __future__ import annotations

import ast
import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "governance" / "reliability_contracts.json"
SOURCE_ROOTS = (
    ROOT / "apps",
    ROOT / "core",
    ROOT / "shared",
    ROOT / "sdk" / "agomtradepro",
    ROOT / "sdk" / "agomtradepro_mcp",
)
STATUS_SOURCE = "shared/domain/reliability.py"


def _iter_python_files() -> Iterable[Path]:
    """Yield production Python sources in stable order."""

    result = subprocess.run(
        ["git", "ls-files", "--cached", "--", "*.py"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "git ls-files failed")
    allowed_prefixes = tuple(
        f"{source_root.relative_to(ROOT).as_posix()}/" for source_root in SOURCE_ROOTS
    )
    for relative in sorted(set(result.stdout.splitlines())):
        normalized = relative.strip().replace("\\", "/")
        if not normalized.startswith(allowed_prefixes):
            continue
        if "/migrations/" in f"/{normalized}/" or "/tests/" in f"/{normalized}/":
            continue
        path = ROOT / normalized
        if path.is_file():
            yield path


def _target_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _literal_string(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip() or None
    return None


def _reliability_status_values(tree: ast.AST) -> tuple[list[str], int]:
    values: list[str] = []
    definitions = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "ReliabilityStatus":
            continue
        definitions += 1
        for item in node.body:
            if not isinstance(item, ast.Assign) or len(item.targets) != 1:
                continue
            value = _literal_string(item.value)
            if value is not None:
                values.append(value)
    return values, definitions


def _block_reason_occurrences(
    tree: ast.AST,
) -> tuple[set[str], list[int]]:
    literals: set[str] = set()
    dynamic_lines: list[int] = []
    for node in ast.walk(tree):
        value: ast.expr | None = None
        is_reason = False
        if isinstance(node, ast.Assign):
            is_reason = any(_target_name(target) == "block_reason_code" for target in node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            is_reason = _target_name(node.target) == "block_reason_code"
            value = node.value
        elif isinstance(node, ast.Dict):
            for key, candidate in zip(node.keys, node.values, strict=True):
                if _literal_string(key) == "block_reason_code":
                    literal = _literal_string(candidate)
                    if literal is not None:
                        literals.add(literal)
                    elif not (
                        isinstance(candidate, ast.Constant) and candidate.value in {None, ""}
                    ):
                        dynamic_lines.append(candidate.lineno)
            continue
        elif isinstance(node, ast.Call) and _call_name(node.func).endswith(
            "ReliabilityContract.blocked"
        ):
            for keyword in node.keywords:
                if keyword.arg == "reason_code":
                    is_reason = True
                    value = keyword.value
                    break
        if (
            is_reason
            and isinstance(value, ast.Call)
            and _call_name(value.func).startswith("serializers.")
        ):
            continue
        if not is_reason or value is None:
            continue
        literal = _literal_string(value)
        if literal is not None:
            literals.add(literal)
        elif not (isinstance(value, ast.Constant) and value.value in {None, ""}):
            dynamic_lines.append(value.lineno)
    return literals, sorted(set(dynamic_lines))


def validate() -> list[str]:
    """Return deterministic ownership and dictionary violations."""

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        return ["manifest_invalid"]
    violations: list[str] = []
    if payload.get("schema_version") != 1:
        violations.append("schema_version_invalid")
    if payload.get("owner") != "data_center":
        violations.append("owner_invalid")

    status_definitions: list[str] = []
    status_values: list[str] = []
    literal_codes: set[str] = set()
    dynamic_by_path: dict[str, list[int]] = {}
    for path in _iter_python_files():
        relative = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if not any(
            marker in source
            for marker in ("ReliabilityStatus", "block_reason_code", "ReliabilityContract.blocked")
        ):
            continue
        tree = ast.parse(source, filename=relative)
        values, count = _reliability_status_values(tree)
        status_definitions.extend([relative] * count)
        if relative == STATUS_SOURCE:
            status_values.extend(values)
        literals, dynamic_lines = _block_reason_occurrences(tree)
        literal_codes.update(literals)
        if dynamic_lines:
            dynamic_by_path[relative] = dynamic_lines

    if status_definitions != [STATUS_SOURCE]:
        violations.append(
            "reliability_status_definition_not_unique:" + ",".join(status_definitions)
        )
    manifest_statuses = payload.get("statuses")
    if not isinstance(manifest_statuses, list) or status_values != manifest_statuses:
        violations.append("reliability_status_manifest_mismatch")

    format_text = str(payload.get("block_reason_code_format") or "")
    try:
        code_pattern = re.compile(format_text)
    except re.error:
        violations.append("block_reason_code_format_invalid")
        code_pattern = re.compile(r"(?!)")
    raw_codes = payload.get("block_reason_codes")
    if not isinstance(raw_codes, list):
        violations.append("block_reason_codes_invalid")
        raw_codes = []
    registered_codes: set[str] = set()
    for item in raw_codes:
        if not isinstance(item, Mapping):
            violations.append("block_reason_code_entry_invalid")
            continue
        code = str(item.get("code") or "").strip()
        owner = str(item.get("owner") or "").strip()
        if not code or not owner or code in registered_codes or not code_pattern.fullmatch(code):
            violations.append(f"block_reason_code_entry_invalid:{code}")
            continue
        registered_codes.add(code)
    for code in sorted(literal_codes - registered_codes):
        violations.append(f"block_reason_code_unregistered:{code}")

    raw_boundaries = payload.get("dynamic_reason_boundaries")
    if not isinstance(raw_boundaries, list):
        violations.append("dynamic_reason_boundaries_invalid")
        raw_boundaries = []
    boundary_paths: set[str] = set()
    for item in raw_boundaries:
        if not isinstance(item, Mapping):
            violations.append("dynamic_reason_boundary_invalid")
            continue
        relative = str(item.get("path") or "").strip()
        symbol = str(item.get("symbol") or "").strip()
        pattern = str(item.get("pattern") or "").strip()
        source_path = ROOT / relative
        if (
            not relative
            or not symbol
            or not pattern
            or relative in boundary_paths
            or not source_path.is_file()
        ):
            violations.append(f"dynamic_reason_boundary_invalid:{relative}")
            continue
        try:
            re.compile(pattern)
        except re.error:
            violations.append(f"dynamic_reason_boundary_pattern_invalid:{relative}")
            continue
        if symbol not in source_path.read_text(encoding="utf-8"):
            violations.append(f"dynamic_reason_boundary_symbol_missing:{relative}:{symbol}")
        boundary_paths.add(relative)
    for relative, lines in sorted(dynamic_by_path.items()):
        if relative not in boundary_paths:
            violations.append(
                f"dynamic_reason_boundary_unregistered:{relative}:{','.join(map(str, lines))}"
            )
    return sorted(set(violations))


def main() -> int:
    """Run the reliability ownership guard."""

    try:
        violations = validate()
    except (OSError, SyntaxError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"reliability contract guard failed: {exc}") from exc
    if violations:
        raise SystemExit("Reliability contract violations: " + "; ".join(violations))
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    print(
        "Reliability contract owner: shared/domain/reliability.py; "
        f"statuses={len(payload['statuses'])}; reasons={len(payload['block_reason_codes'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
