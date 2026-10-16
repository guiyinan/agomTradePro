"""Generate the stdlib-only QMT projection of Risk's price-range algorithm."""

from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SCRIPT_PATH: Path = Path(__file__).resolve()
PRICE_DOMAIN_PATH: Path = (
    REPO_ROOT / "apps" / "risk_center" / "domain" / "price_submission_range.py"
)
EXECUTION_DOMAIN_PATH: Path = (
    REPO_ROOT / "apps" / "risk_center" / "domain" / "execution_trading_constraints.py"
)
GENERATED_MODULE_PATH: Path = REPO_ROOT / "qmt_agent" / "price_submission_range.py"
PRICE_DOMAIN_SOURCE: str = "apps/risk_center/domain/price_submission_range.py"
EXECUTION_SIDE_SOURCE: str = (
    "apps/risk_center/domain/execution_trading_constraints.py::ExecutionSide"
)
GENERATED_BY: str = "scripts/build_qmt_price_submission_projection.py"
PRICE_SIDE_IMPORT: str = (
    "from apps.risk_center.domain.execution_trading_constraints import ExecutionSide"
)
_ALLOWED_PRICE_IMPORTS: frozenset[tuple[str, tuple[str, ...]]] = frozenset(
    {
        ("__future__", ("annotations",)),
        ("dataclasses", ("dataclass",)),
        ("decimal", ("Decimal",)),
        ("enum", ("StrEnum",)),
        ("fractions", ("Fraction",)),
        ("apps.risk_center.domain.execution_trading_constraints", ("ExecutionSide",)),
    }
)
_ALLOWED_GENERATED_IMPORTS: frozenset[tuple[str, tuple[str, ...]]] = frozenset(
    {
        ("__future__", ("annotations",)),
        ("dataclasses", ("dataclass",)),
        ("decimal", ("Decimal",)),
        ("enum", ("StrEnum",)),
        ("fractions", ("Fraction",)),
    }
)


class ProjectionBuildError(ValueError):
    """Raised when the source contract changes outside the supported projection."""


def normalize_lf(source: str) -> str:
    """Normalize all line endings to LF for stable hashing and output bytes."""

    return source.replace("\r\n", "\n").replace("\r", "\n")


def _parse_module(source: str, source_label: str) -> ast.Module:
    """Parse source text with a stable build error for unsupported syntax."""

    try:
        return ast.parse(source, filename=source_label)
    except SyntaxError as error:
        raise ProjectionBuildError(f"cannot parse {source_label}: {error.msg}") from error


def _import_signature(node: ast.ImportFrom) -> tuple[str, tuple[str, ...]]:
    """Return a narrow import signature, rejecting relative or aliased imports."""

    if node.level != 0 or node.module is None:
        raise ProjectionBuildError("unexpected relative import in price-range source")
    imported_names: list[str] = []
    for alias in node.names:
        if alias.asname is not None:
            raise ProjectionBuildError("unexpected aliased import in price-range source")
        imported_names.append(alias.name)
    return node.module, tuple(imported_names)


def _validate_price_imports(tree: ast.Module) -> ast.ImportFrom:
    """Require the exact Risk imports and return its sole ExecutionSide import."""

    side_imports: list[ast.ImportFrom] = []
    module_import_nodes = {
        id(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in {
            "__import__",
            "import_module",
            "__builtins__",
        }:
            raise ProjectionBuildError("dynamic import references are unsupported")
        if isinstance(node, ast.Attribute) and node.attr == "import_module":
            raise ProjectionBuildError("dynamic import references are unsupported")
        if isinstance(node, ast.Import):
            if id(node) not in module_import_nodes:
                raise ProjectionBuildError("unexpected nested import in price-range source")
            raise ProjectionBuildError("unexpected import statement in price-range source")
        if not isinstance(node, ast.ImportFrom):
            continue
        if id(node) not in module_import_nodes:
            raise ProjectionBuildError("unexpected nested import in price-range source")
        signature = _import_signature(node)
        if signature not in _ALLOWED_PRICE_IMPORTS:
            raise ProjectionBuildError(f"unexpected import in price-range source: {signature[0]}")
        if signature == (
            "apps.risk_center.domain.execution_trading_constraints",
            ("ExecutionSide",),
        ):
            side_imports.append(node)
    if len(side_imports) != 1:
        raise ProjectionBuildError("price-range source must import ExecutionSide exactly once")
    side_import = side_imports[0]
    if side_import.end_lineno != side_import.lineno:
        raise ProjectionBuildError("ExecutionSide import must remain a single-line import")
    return side_import


def _validate_execution_side_import(tree: ast.Module) -> None:
    """Ensure the source ExecutionSide base is provided by enum.StrEnum."""

    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.module != "enum" or node.level != 0:
            continue
        for alias in node.names:
            if alias.name == "StrEnum" and alias.asname is None:
                return
    raise ProjectionBuildError("ExecutionSide source must import enum.StrEnum")


def _extract_execution_side(execution_source: str) -> str:
    """Extract a simple BUY/SELL StrEnum definition from the Risk owner."""

    tree = _parse_module(execution_source, "execution_trading_constraints.py")
    _validate_execution_side_import(tree)
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ExecutionSide"
    ]
    if len(matches) != 1:
        raise ProjectionBuildError("ExecutionSide source must define exactly one top-level class")
    definition = matches[0]
    if (
        len(definition.bases) != 1
        or not isinstance(definition.bases[0], ast.Name)
        or definition.bases[0].id != "StrEnum"
        or definition.keywords
        or definition.decorator_list
    ):
        raise ProjectionBuildError("ExecutionSide must remain a plain StrEnum declaration")

    body = list(definition.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body.pop(0)
    members: list[tuple[str, str]] = []
    for statement in body:
        if (
            not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or not isinstance(statement.targets[0], ast.Name)
            or not isinstance(statement.value, ast.Constant)
            or not isinstance(statement.value.value, str)
        ):
            raise ProjectionBuildError("ExecutionSide may contain only literal string members")
        members.append((statement.targets[0].id, statement.value.value))
    if members != [("BUY", "BUY"), ("SELL", "SELL")]:
        raise ProjectionBuildError("ExecutionSide members must remain BUY and SELL")

    source_segment = ast.get_source_segment(execution_source, definition)
    if source_segment is None:
        raise ProjectionBuildError("cannot extract ExecutionSide source text")
    return normalize_lf(source_segment)


def _insert_generated_header(source: str, digest: str) -> str:
    """Insert deterministic projection metadata after the module docstring."""

    tree = _parse_module(source, PRICE_DOMAIN_SOURCE)
    if not tree.body or not isinstance(tree.body[0], ast.Expr):
        raise ProjectionBuildError("price-range source must begin with its module docstring")
    docstring = tree.body[0]
    if not isinstance(docstring.value, ast.Constant) or not isinstance(docstring.value.value, str):
        raise ProjectionBuildError("price-range source must begin with its module docstring")
    if docstring.end_lineno is None:
        raise ProjectionBuildError("cannot locate the end of the price-range module docstring")

    lines = source.splitlines(keepends=True)
    insertion_index = docstring.end_lineno
    header_lines = [
        f"# Generated by {GENERATED_BY}",
        f"# Source: {PRICE_DOMAIN_SOURCE}",
        f"# Additional source: {EXECUTION_SIDE_SOURCE}",
        f"# Effective source SHA-256: {digest}",
    ]
    lines[insertion_index:insertion_index] = [
        "\n",
        *(line + "\n" for line in header_lines),
        "\n",
    ]
    return "".join(lines)


def _validate_generated_imports(source: str) -> None:
    """Reject any generated runtime import outside the declared stdlib set."""

    tree = _parse_module(source, GENERATED_MODULE_PATH.as_posix())
    found_strenum = False
    module_import_nodes = {id(node) for node in tree.body if isinstance(node, ast.ImportFrom)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            raise ProjectionBuildError("generated projection contains an unexpected import")
        if not isinstance(node, ast.ImportFrom):
            continue
        if id(node) not in module_import_nodes:
            raise ProjectionBuildError("generated projection contains a nested import")
        signature = _import_signature(node)
        if signature not in _ALLOWED_GENERATED_IMPORTS:
            raise ProjectionBuildError(
                f"generated projection contains an unexpected import: {signature[0]}"
            )
        if signature == ("enum", ("StrEnum",)):
            found_strenum = True
    if not found_strenum:
        raise ProjectionBuildError("generated projection must import enum.StrEnum")


def render_projection(price_source: str, execution_source: str) -> str:
    """Render the stdlib-only module from the two authoritative source files.

    The hash is SHA-256 over the complete LF-normalized price source followed
    by the LF-normalized extracted ExecutionSide class source segment.
    """

    normalized_price = normalize_lf(price_source)
    normalized_execution = normalize_lf(execution_source)
    price_tree = _parse_module(normalized_price, PRICE_DOMAIN_SOURCE)
    side_import = _validate_price_imports(price_tree)
    execution_side = _extract_execution_side(normalized_execution)
    lines = normalized_price.splitlines(keepends=True)
    import_line_index = side_import.lineno - 1
    if lines[import_line_index].rstrip("\n") != PRICE_SIDE_IMPORT:
        raise ProjectionBuildError("ExecutionSide import changed beyond the supported projection")
    lines[import_line_index] = "\n" + execution_side + "\n\n"
    replaced_source = "".join(lines)
    digest = hashlib.sha256((normalized_price + execution_side).encode("utf-8")).hexdigest()
    generated = _insert_generated_header(replaced_source, digest)
    _validate_generated_imports(generated)
    return generated


def render_default_projection() -> str:
    """Read the two Risk source files and render the fixed QMT projection."""

    try:
        price_source = PRICE_DOMAIN_PATH.read_bytes().decode("utf-8")
        execution_source = EXECUTION_DOMAIN_PATH.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ProjectionBuildError(f"cannot read Risk price-range sources: {error}") from error
    return render_projection(price_source, execution_source)


def check_projection(target: Path, expected: bytes) -> bool:
    """Return whether target bytes exactly match expected, without writing."""

    try:
        return target.read_bytes() == expected
    except FileNotFoundError:
        return False


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fixed-target projection generator or strict read-only check."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the generated projection is missing or differs byte-for-byte.",
    )
    args = parser.parse_args(argv)
    try:
        expected_text = render_default_projection()
    except ProjectionBuildError as error:
        print(f"Cannot build QMT price-range projection: {error}", file=sys.stderr)
        return 2

    expected_bytes = expected_text.encode("utf-8")
    if args.check:
        if not check_projection(GENERATED_MODULE_PATH, expected_bytes):
            print(f"Missing or stale projection: {GENERATED_MODULE_PATH}", file=sys.stderr)
            return 1
        print("QMT price-range projection is current.")
        return 0

    GENERATED_MODULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_MODULE_PATH.write_bytes(expected_bytes)
    print(f"Generated QMT price-range projection: {GENERATED_MODULE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
