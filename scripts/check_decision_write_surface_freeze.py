#!/usr/bin/env python
"""Reject unclassified decision, portfolio, strategy, and execution writes."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "governance" / "decision_write_surfaces.json"
HTTP_MUTATION_METHODS = {"delete", "patch", "post", "put"}
SDK_MUTATION_CALLS = {"_delete", "_patch", "_post", "_put", "delete", "patch", "post", "put"}


@dataclass(frozen=True)
class DecisionWriteSurfaceInventory:
    """Typed inventory consumed by the write-surface freeze guard."""

    http_interface_scopes: tuple[str, ...]
    http_surfaces: frozenset[str]
    sdk_module_scopes: tuple[str, ...]
    sdk_mutation_surfaces: frozenset[str]


def load_inventory(path: Path = DEFAULT_INVENTORY) -> DecisionWriteSurfaceInventory:
    """Load and validate the machine inventory."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("decision write surface inventory version must be 1")
    inventory = DecisionWriteSurfaceInventory(
        http_interface_scopes=tuple(payload.get("http_interface_scopes") or ()),
        http_surfaces=frozenset(payload.get("http_surfaces") or ()),
        sdk_module_scopes=tuple(payload.get("sdk_module_scopes") or ()),
        sdk_mutation_surfaces=frozenset(payload.get("sdk_mutation_surfaces") or ()),
    )
    if not inventory.http_interface_scopes or not inventory.sdk_module_scopes:
        raise ValueError("decision write surface scopes must not be empty")
    return inventory


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def discover_http_surfaces(scopes: tuple[str, ...]) -> frozenset[str]:
    """Discover class-based HTTP mutation handlers in governed scopes."""

    surfaces: set[str] = set()
    for scope in scopes:
        for path in sorted((REPO_ROOT / scope).rglob("*.py")):
            for node in _parse(path).body:
                if not isinstance(node, ast.ClassDef):
                    continue
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                        member.name in HTTP_MUTATION_METHODS
                    ):
                        surfaces.add(f"{_relative(path)}::{node.name}.{member.name}")
    return frozenset(surfaces)


def _calls_sdk_mutation(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in SDK_MUTATION_CALLS
        for node in ast.walk(function)
    )


def discover_sdk_surfaces(scopes: tuple[str, ...]) -> frozenset[str]:
    """Discover public SDK methods that delegate to HTTP mutations."""

    surfaces: set[str] = set()
    for scope in scopes:
        path = REPO_ROOT / scope
        for node in _parse(path).body:
            if not isinstance(node, ast.ClassDef):
                continue
            for member in node.body:
                if (
                    isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not member.name.startswith("_")
                    and _calls_sdk_mutation(member)
                ):
                    surfaces.add(f"{_relative(path)}::{node.name}.{member.name}")
    return frozenset(surfaces)


def validate_surface_freeze(inventory: DecisionWriteSurfaceInventory) -> dict[str, int]:
    """Require discovered surfaces to exactly match the frozen inventories."""

    actual_http = discover_http_surfaces(inventory.http_interface_scopes)
    actual_sdk = discover_sdk_surfaces(inventory.sdk_module_scopes)
    errors: list[str] = []
    for label, actual, expected in (
        ("HTTP", actual_http, inventory.http_surfaces),
        ("SDK", actual_sdk, inventory.sdk_mutation_surfaces),
    ):
        added = sorted(actual - expected)
        removed = sorted(expected - actual)
        if added:
            errors.append(f"unclassified {label} mutation surfaces: {added}")
        if removed:
            errors.append(f"stale {label} mutation surfaces: {removed}")
    if errors:
        raise ValueError("Decision write surface freeze failed:\n- " + "\n- ".join(errors))
    return {"http_surface_count": len(actual_http), "sdk_surface_count": len(actual_sdk)}


def main() -> int:
    """Run the repository decision-write freeze guard."""

    summary = validate_surface_freeze(load_inventory())
    print("Decision write surface freeze OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
