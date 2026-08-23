"""Guard production Research Evidence reads against composition bypasses.

The canonical Evidence repositories and scoped facades are infrastructure
participants.  Production callers must obtain them from the fail-closed
composition root so an authenticated route cannot accidentally become an
unscoped read.  This guard deliberately checks source shape only; it does not
create authority facts or connect to a database.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSITION_ROOT = "apps/research/evidence_composition.py"
API_VIEWS = "apps/research/interface/evidence_api_views.py"
FORBIDDEN_SYMBOLS = frozenset(
    {
        "DjangoEvidenceRepository",
        "DjangoEvidenceScopeSourceV1Repository",
        "EvidenceReadFacade",
        "ScopedEvidenceReadFacade",
    }
)
FORBIDDEN_MODULES = frozenset(
    {
        "apps.research.application.evidence_reads",
        "apps.research.infrastructure.evidence_repository",
        "apps.research.infrastructure.evidence_scope_source_v1_repository",
    }
)


@dataclass(frozen=True)
class CompositionGuardViolation:
    """One source-level composition bypass finding."""

    path: str
    line: int
    message: str

    def format(self) -> str:
        """Return a stable human-readable finding."""

        return f"{self.path}:{self.line}: {self.message}"


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def _symbol_name(node: ast.AST) -> str | None:
    dotted = _dotted_name(node)
    return None if dotted is None else dotted.rsplit(".", 1)[-1]


def _production_files(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for source_root_name in ("apps", "core", "shared"):
        source_root = root / source_root_name
        if not source_root.is_dir():
            continue
        paths.extend(
            path
            for path in source_root.rglob("*.py")
            if "migrations" not in path.parts and "tests" not in path.parts
        )
    return tuple(sorted(paths))


def _parse(
    path: Path, root: Path
) -> tuple[str, ast.Module | None, CompositionGuardViolation | None]:
    relative = _relative(root, path)
    try:
        return relative, ast.parse(path.read_text(encoding="utf-8"), filename=relative), None
    except (OSError, SyntaxError) as error:
        return (
            relative,
            None,
            CompositionGuardViolation(
                relative, 1, f"cannot parse production source: {type(error).__name__}"
            ),
        )


def _scan_production_file(root: Path, path: Path) -> tuple[CompositionGuardViolation, ...]:
    relative, tree, parse_error = _parse(path, root)
    if parse_error is not None:
        return (parse_error,)
    if relative == COMPOSITION_ROOT:
        return ()
    assert tree is not None
    violations: list[CompositionGuardViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported = tuple(alias.name.rsplit(".", 1)[-1] for alias in node.names)
            for symbol in imported:
                is_forbidden_symbol = symbol in FORBIDDEN_SYMBOLS
                is_forbidden_wildcard = symbol == "*" and node.module in FORBIDDEN_MODULES
                if is_forbidden_symbol or is_forbidden_wildcard:
                    dependency = "wildcard import" if is_forbidden_wildcard else symbol
                    violations.append(
                        CompositionGuardViolation(
                            relative,
                            node.lineno,
                            f"direct Evidence composition dependency {dependency}; use the composition root",
                        )
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_symbol = alias.name.rsplit(".", 1)[-1]
                if imported_symbol in FORBIDDEN_SYMBOLS:
                    violations.append(
                        CompositionGuardViolation(
                            relative,
                            node.lineno,
                            f"direct Evidence composition dependency {imported_symbol}; use the composition root",
                        )
                    )
        elif isinstance(node, ast.Call):
            called_symbol = _symbol_name(node.func)
            if called_symbol in FORBIDDEN_SYMBOLS:
                violations.append(
                    CompositionGuardViolation(
                        relative,
                        node.lineno,
                        f"direct Evidence composition call {called_symbol}; use the composition root",
                    )
                )
    return tuple(violations)


def _scan_api_views(root: Path) -> tuple[CompositionGuardViolation, ...]:
    path = root / API_VIEWS
    if not path.is_file():
        return (
            CompositionGuardViolation(API_VIEWS, 1, "canonical Evidence API views are missing"),
        )
    relative, tree, parse_error = _parse(path, root)
    if parse_error is not None:
        return (parse_error,)
    assert tree is not None
    violations: list[CompositionGuardViolation] = []
    has_factory_import = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "apps.research.evidence_composition"
        and any(alias.name == "make_evidence_read_facade" for alias in node.names)
        for node in tree.body
    )
    if not has_factory_import:
        violations.append(
            CompositionGuardViolation(
                relative,
                1,
                "canonical Evidence API views must import make_evidence_read_facade",
            )
        )
    scoped_view_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(_dotted_name(base) == "_StaffExactEvidenceReadView" for base in node.bases):
            continue
        scoped_view_count += 1
        has_factory_call = any(
            isinstance(child, ast.Call) and _symbol_name(child.func) == "make_evidence_read_facade"
            for child in ast.walk(node)
        )
        if not has_factory_call:
            violations.append(
                CompositionGuardViolation(
                    relative,
                    node.lineno,
                    f"{node.name} must call make_evidence_read_facade before an Evidence read",
                )
            )
    if scoped_view_count == 0:
        violations.append(
            CompositionGuardViolation(
                relative,
                1,
                "canonical Evidence API views must define staff-scoped detail views",
            )
        )
    return tuple(violations)


def scan_evidence_scope_composition(
    root: Path = ROOT,
) -> tuple[CompositionGuardViolation, ...]:
    """Return all production Evidence composition bypass findings."""

    violations: list[CompositionGuardViolation] = []
    for path in _production_files(root):
        violations.extend(_scan_production_file(root, path))
    violations.extend(_scan_api_views(root))
    return tuple(violations)


def main() -> int:
    """Run the production Evidence composition guard."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    violations = scan_evidence_scope_composition(root)
    if violations:
        for violation in violations:
            print(violation.format())
        return 1
    print(
        f"Evidence scope composition guard passed: {len(_production_files(root))} production files scanned"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
