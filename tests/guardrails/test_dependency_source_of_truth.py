"""Guard the canonical dependency source and its generated projections."""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from scripts.sync_dependency_projections import render_projection

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_requirements_files_are_exact_pyproject_projections() -> None:
    """Prevent manual requirements edits from creating a second dependency truth."""

    assert (REPO_ROOT / "requirements-prod.txt").read_text(
        encoding="utf-8"
    ) == render_projection()
    assert (REPO_ROOT / "requirements-dev.txt").read_text(
        encoding="utf-8"
    ) == render_projection("dev")


def test_production_lock_covers_every_canonical_runtime_dependency() -> None:
    """Require the checked-in lock to contain a compatible pin for every direct dependency."""

    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        dependencies = tomllib.load(handle)["project"]["dependencies"]

    locked_versions: dict[str, Version] = {}
    for line in (REPO_ROOT / "requirements-prod.lock").read_text(encoding="utf-8").splitlines():
        if not line or line[0].isspace() or line.startswith(("#", "-")):
            continue
        requirement = Requirement(line.rstrip(" \\"))
        exact_versions = [
            Version(specifier.version)
            for specifier in requirement.specifier
            if specifier.operator == "==" and "*" not in specifier.version
        ]
        if exact_versions:
            locked_versions[canonicalize_name(requirement.name)] = exact_versions[0]

    missing: list[str] = []
    incompatible: list[str] = []
    for raw_dependency in dependencies:
        dependency = Requirement(raw_dependency)
        name = canonicalize_name(dependency.name)
        locked_version = locked_versions.get(name)
        if locked_version is None:
            missing.append(dependency.name)
        elif dependency.specifier and locked_version not in dependency.specifier:
            incompatible.append(f"{raw_dependency} != {locked_version}")

    assert missing == []
    assert incompatible == []
