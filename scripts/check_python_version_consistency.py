#!/usr/bin/env python3
"""
Check Python version consistency across project configuration files.

Validates:
1. pyproject.toml / setup.py version constraints
2. CI workflow Python versions
3. Dockerfile Python versions
4. .python-version file (if exists)

Reports inconsistencies and suggests fixes.

Usage:
    python scripts/check_python_version_consistency.py
"""
import re
import sys
from pathlib import Path
from typing import NamedTuple

# Supported Python versions for CI testing
CI_SUPPORTED_VERSIONS = {"3.11", "3.13"}

# Runtime deployment version (primary version)
RUNTIME_VERSION = "3.11"


class VersionSpec(NamedTuple):
    """Version specification from a configuration file."""
    file: str
    minimum: str
    maximum: str | None
    ci_versions: list[str]


def extract_python_requirement(text: str) -> tuple[str, str | None]:
    """
    Extract minimum and maximum Python versions from a requirement string.

    Args:
        text: Python version requirement string (e.g., ">=3.11,<4.0")

    Returns:
        Tuple of (minimum_version, maximum_version)
    """
    minimum = None
    maximum = None

    # Match >=3.11, >=3.11,<4.0, >=3.11, <4.0, etc.
    min_match = re.search(r">=(\d+\.\d+)", text)
    if min_match:
        minimum = min_match.group(1)

    max_match = re.search(r"<(\d+\.\d+)", text)
    if max_match:
        maximum = max_match.group(1)

    # Also match ~=3.11 (compatible release)
    tilde_match = re.search(r"~=(\d+\.\d+)", text)
    if tilde_match and not minimum:
        minimum = tilde_match.group(1)

    return minimum or "", maximum


def check_pyproject_toml(project_root: Path) -> VersionSpec | None:
    """Extract Python version from pyproject.toml."""
    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    content = pyproject_path.read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        return None

    requirement = match.group(1)
    minimum, maximum = extract_python_requirement(requirement)

    return VersionSpec(
        file=str(pyproject_path.relative_to(project_root)),
        minimum=minimum,
        maximum=maximum,
        ci_versions=[]
    )


def check_github_workflows(project_root: Path) -> list[str]:
    """Extract Python versions from GitHub workflows."""
    workflows_dir = project_root / ".github" / "workflows"
    if not workflows_dir.exists():
        return []

    versions = set()

    for workflow_file in workflows_dir.glob("*.yml"):
        content = workflow_file.read_text(encoding="utf-8")

        # Check for matrix strategy
        matrix_match = re.search(
            r'matrix:\s*\n\s*python-version:\s*\[([^\]]+)\]',
            content,
            re.MULTILINE
        )
        if matrix_match:
            matrix_versions = matrix_match.group(1)
            for v in re.findall(r'["\'](\d+\.\d+)["\']', matrix_versions):
                versions.add(v)

        # Check for individual python-version settings
        for match in re.finditer(r'python-version:\s*["\'](\d+\.\d+)["\']', content):
            versions.add(match.group(1))

    return sorted(versions)


def check_dockerfiles(project_root: Path) -> list[str]:
    """Extract Python versions from Dockerfiles."""
    versions = []

    # Check main Dockerfile
    dockerfile = project_root / "Dockerfile"
    if dockerfile.exists():
        content = dockerfile.read_text(encoding="utf-8")
        for match in re.finditer(r'FROM\s+python:(\d+\.\d+)', content):
            versions.append((str(dockerfile.relative_to(project_root)), match.group(1)))

    # Check docker directory
    docker_dir = project_root / "docker"
    if docker_dir.exists():
        for dockerfile in docker_dir.glob("Dockerfile*"):
            content = dockerfile.read_text(encoding="utf-8")
            for match in re.finditer(r'FROM\s+python:(\d+\.\d+)', content):
                versions.append((
                    str(dockerfile.relative_to(project_root)),
                    match.group(1)
                ))

    return versions


def check_python_version_file(project_root: Path) -> str | None:
    """Extract Python version from .python-version file."""
    version_file = project_root / ".python-version"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return None


def main() -> int:
    """Run all consistency checks."""
    project_root = Path.cwd()

    errors = []
    warnings = []

    print(f"Checking Python version consistency in {project_root}")
    print()

    # Check pyproject.toml
    pyproject_spec = check_pyproject_toml(project_root)
    if pyproject_spec:
        print(f"pyproject.toml: requires-python = {pyproject_spec.minimum or 'unspecified'}")
        if pyproject_spec.minimum:
            # Verify minimum matches runtime version
            if pyproject_spec.minimum != RUNTIME_VERSION:
                errors.append(
                    f"pyproject.toml minimum version ({pyproject_spec.minimum}) "
                    f"does not match runtime version ({RUNTIME_VERSION})"
                )
            # Verify minimum is in CI supported versions
            if pyproject_spec.minimum not in CI_SUPPORTED_VERSIONS:
                errors.append(
                    f"pyproject.toml minimum version ({pyproject_spec.minimum}) "
                    f"is not in CI supported versions {CI_SUPPORTED_VERSIONS}"
                )
    else:
        warnings.append("No pyproject.toml found or no requires-python specified")

    # Check CI workflows
    ci_versions = check_github_workflows(project_root)
    print(f"CI workflows: Python versions {ci_versions or 'none found'}")

    ci_versions_set = set(ci_versions)
    if ci_versions_set != CI_SUPPORTED_VERSIONS:
        errors.append(
            f"CI workflow versions {ci_versions_set} "
            f"do not match expected {CI_SUPPORTED_VERSIONS}"
        )

    # Check Dockerfiles
    docker_versions = check_dockerfiles(project_root)
    if docker_versions:
        print("Dockerfiles:")
        for dockerfile, version in docker_versions:
            print(f"  {dockerfile}: Python {version}")

            # Verify runtime Dockerfiles use runtime version
            is_runtime_dockerfile = any(
                x in dockerfile.lower()
                for x in ["dockerfile", "dockerfile.prod", "docker/base"]
            )
            if is_runtime_dockerfile and version != RUNTIME_VERSION:
                errors.append(
                    f"{dockerfile} uses Python {version}, "
                    f"but runtime version is {RUNTIME_VERSION}"
                )
    else:
        warnings.append("No Dockerfiles found")

    # Check .python-version
    python_version_file = check_python_version_file(project_root)
    if python_version_file:
        print(f".python-version: {python_version_file}")
        if python_version_file != RUNTIME_VERSION:
            errors.append(
                f".python-version ({python_version_file}) "
                f"does not match runtime version ({RUNTIME_VERSION})"
            )
    else:
        print(".python-version: not found (optional)")

    print()

    # Summary
    if errors:
        print("ERRORS:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print()
        print("Suggested fixes:", file=sys.stderr)
        print("  1. Update pyproject.toml: requires-python = '>=" + RUNTIME_VERSION + "'", file=sys.stderr)
        print(f"  2. Ensure CI workflows use matrix: {CI_SUPPORTED_VERSIONS}", file=sys.stderr)
        print(f"  3. Ensure Dockerfiles use Python {RUNTIME_VERSION}", file=sys.stderr)
        return 1

    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  - {w}")

    print("Python version consistency check: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
