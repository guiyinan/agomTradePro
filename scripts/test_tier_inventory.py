#!/usr/bin/env python
"""Classify central pytest files and build the machine-readable test-tier inventory."""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT: Final[Path] = REPO_ROOT / "governance" / "test_tier_inventory.json"
TEST_ROOT: Final[Path] = REPO_ROOT / "tests"

DATABASE_FIXTURES: Final[frozenset[str]] = frozenset(
    {
        "admin_client",
        "admin_user",
        "authenticated_client",
        "async_client",
        "client",
        "db",
        "django_assert_num_queries",
        "django_db_blocker",
        "django_db_reset_sequences",
        "django_user_model",
        "live_server",
        "transactional_db",
    }
)
DATABASE_BASE_CLASSES: Final[frozenset[str]] = frozenset(
    {"APITestCase", "LiveServerTestCase", "TestCase", "TransactionTestCase"}
)
BOUNDARY_IMPORT_PARTS: Final[frozenset[str]] = frozenset(
    {
        ".infrastructure",
        ".interface",
        ".models",
        "django.test",
        "rest_framework.test",
    }
)


@dataclass(frozen=True)
class TestFileClassification:
    """A deterministic classification for one central pytest file."""

    path: str
    tier: str
    database_dependent: bool
    reasons: tuple[str, ...]


def _attribute_name(node: ast.AST) -> str:
    """Return the dotted name represented by an AST name or attribute."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attribute_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _iter_test_files(root: Path) -> Iterable[Path]:
    """Yield central pytest files in stable path order."""
    for path in sorted(root.rglob("test_*.py")):
        if "__pycache__" not in path.parts:
            yield path


def classify_test_file(path: Path, repo_root: Path = REPO_ROOT) -> TestFileClassification:
    """Classify one file as fast, unit, component, integration, e2e, or support."""
    relative = path.relative_to(repo_root).as_posix()
    parts = path.relative_to(repo_root).parts
    top_tier = parts[1] if len(parts) > 1 and parts[0] == "tests" else "support"
    if top_tier in {"api", "critical", "e2e", "integration", "migrations", "playwright"}:
        return TestFileClassification(relative, top_tier, True, (f"path:{top_tier}",))
    if top_tier != "unit":
        return TestFileClassification(relative, top_tier, False, (f"path:{top_tier}",))

    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(path))
    reasons: set[str] = set()
    imports: set[str] = set()
    uses_domain_or_application = False

    class_bases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fixture_names = {argument.arg for argument in node.args.args}
            used_fixtures = fixture_names & DATABASE_FIXTURES
            reasons.update(f"fixture:{name}" for name in used_fixtures)
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                class_bases.add(_attribute_name(base).split(".")[-1])
        elif isinstance(node, ast.Attribute):
            dotted = _attribute_name(node)
            if dotted.endswith(".objects") or ".objects." in dotted:
                reasons.add("orm:.objects")
            if dotted.endswith(".mark.django_db"):
                reasons.add("marker:django_db")
        elif isinstance(node, ast.Call):
            called = _attribute_name(node.func)
            if called.endswith(".mark.django_db"):
                reasons.add("marker:django_db")

    for imported in imports:
        if ".domain" in imported or ".application" in imported:
            uses_domain_or_application = True
        for boundary in BOUNDARY_IMPORT_PARTS:
            if boundary in imported:
                reasons.add(f"import:{boundary}")
    if any(imported.startswith(("django.test", "rest_framework.test")) for imported in imports):
        reasons.update(f"base:{name}" for name in class_bases & DATABASE_BASE_CLASSES)

    database_reasons = {
        reason
        for reason in reasons
        if reason.startswith(("base:", "fixture:", "marker:", "orm:"))
        or reason in {"import:django.test", "import:rest_framework.test"}
    }
    database_dependent = bool(database_reasons)
    has_boundary = any(reason.startswith(("import:", "orm:")) for reason in reasons)

    if not database_dependent and uses_domain_or_application and not has_boundary:
        tier = "fast"
    elif database_dependent or has_boundary:
        tier = "component"
    else:
        tier = "unit"
    return TestFileClassification(relative, tier, database_dependent, tuple(sorted(reasons)))


def build_inventory(test_root: Path = TEST_ROOT) -> dict[str, object]:
    """Build a stable test-tier inventory for all central pytest files."""
    files = [classify_test_file(path) for path in _iter_test_files(test_root)]
    unit_files = [item for item in files if item.path.startswith("tests/unit/")]
    database_files = [item for item in unit_files if item.database_dependent]
    fast_files = [item.path for item in unit_files if item.tier == "fast"]
    counts: dict[str, int] = {}
    for item in files:
        counts[item.tier] = counts.get(item.tier, 0) + 1

    return {
        "schema_version": 1,
        "counts": dict(sorted(counts.items())),
        "unit_database_file_count": len(database_files),
        "unit_file_count": len(unit_files),
        "unit_database_file_ratio": (
            round(len(database_files) / len(unit_files), 4) if unit_files else 0.0
        ),
        "fast_files": fast_files,
        "files": [asdict(item) for item in files],
    }


def write_inventory(payload: dict[str, object], output: Path = DEFAULT_OUTPUT) -> None:
    """Write an inventory as normalized UTF-8 JSON."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_maximum_ratio(path: Path) -> float:
    """Load the database-file ratio threshold from the quality baseline."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return float(payload["fast_suite"]["maximum_database_file_ratio"])


def check_inventory(
    payload: dict[str, object],
    *,
    maximum_database_file_ratio: float,
) -> list[str]:
    """Return actionable inventory violations."""
    violations: list[str] = []
    ratio = float(payload["unit_database_file_ratio"])
    if ratio > maximum_database_file_ratio:
        violations.append(
            "tests/unit database-dependent file ratio "
            f"{ratio:.1%} exceeds {maximum_database_file_ratio:.1%}"
        )
    if not payload["fast_files"]:
        violations.append("fast suite is empty")
    return violations


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="refresh the inventory JSON")
    parser.add_argument("--check", action="store_true", help="enforce the configured ratio")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=REPO_ROOT / "governance" / "testing_quality_baseline.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run inventory generation and optional quality checks."""
    args = parse_args(argv)
    payload = build_inventory()
    if args.write:
        write_inventory(payload, args.output)
    print(json.dumps({key: value for key, value in payload.items() if key != "files"}, indent=2))
    if not args.check:
        return 0
    violations = check_inventory(
        payload,
        maximum_database_file_ratio=_load_maximum_ratio(args.baseline),
    )
    for violation in violations:
        print(f"ERROR: {violation}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
