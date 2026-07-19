"""Synchronize pip-compatible requirement projections from ``pyproject.toml``."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def _load_project_metadata() -> dict[str, Any]:
    with PYPROJECT_PATH.open("rb") as handle:
        document = tomllib.load(handle)
    project = document.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml must define a [project] table")
    return project


def _dependency_group(extra: str | None) -> list[str]:
    project = _load_project_metadata()
    if extra is None:
        raw_dependencies = project.get("dependencies")
    else:
        optional = project.get("optional-dependencies")
        if not isinstance(optional, dict):
            raise ValueError("pyproject.toml must define [project.optional-dependencies]")
        raw_dependencies = optional.get(extra)
    if not isinstance(raw_dependencies, list) or not all(
        isinstance(value, str) and value.strip() for value in raw_dependencies
    ):
        label = "project.dependencies" if extra is None else f"project.optional-dependencies.{extra}"
        raise ValueError(f"pyproject.toml {label} must be a non-empty string list")
    return list(raw_dependencies)


def render_projection(extra: str | None = None) -> str:
    """Render a deterministic requirements projection for one dependency group."""

    if extra is None:
        source = "[project].dependencies"
        prefix: list[str] = []
    else:
        source = f"[project.optional-dependencies].{extra}"
        prefix = ["-r requirements-prod.txt"]
    lines = [
        f"# Generated from pyproject.toml {source}; do not edit manually.",
        "# Regenerate with: python scripts/sync_dependency_projections.py",
        *prefix,
        *_dependency_group(extra),
    ]
    return "\n".join(lines) + "\n"


def synchronize(*, check: bool) -> list[str]:
    """Write projections, or return stale paths without modifying them in check mode."""

    projections = {
        REPO_ROOT / "requirements-prod.txt": render_projection(),
        REPO_ROOT / "requirements-dev.txt": render_projection("dev"),
    }
    stale: list[str] = []
    for path, expected in projections.items():
        actual = path.read_text(encoding="utf-8") if path.exists() else ""
        if actual == expected:
            continue
        stale.append(path.relative_to(REPO_ROOT).as_posix())
        if not check:
            path.write_text(expected, encoding="utf-8", newline="\n")
    return stale


def main() -> int:
    """Run the dependency projection synchronizer command."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when generated projections differ from pyproject.toml.",
    )
    args = parser.parse_args()
    stale = synchronize(check=args.check)
    if stale and args.check:
        print("Stale dependency projections: " + ", ".join(stale))
        return 1
    if stale:
        print("Updated dependency projections: " + ", ".join(stale))
    else:
        print("Dependency projections are current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
