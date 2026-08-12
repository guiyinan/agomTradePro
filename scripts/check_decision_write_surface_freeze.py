#!/usr/bin/env python
"""Reject unclassified decision, portfolio, strategy, and execution writes."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "governance" / "decision_write_surfaces.json"
HTTP_MUTATION_METHODS = {"delete", "patch", "post", "put"}
SDK_MUTATION_CALLS = {"_delete", "_patch", "_post", "_put", "delete", "patch", "post", "put"}


class _CapabilityManifest(Protocol):
    tags: tuple[str, ...]
    risk_level: str


class _CapabilityRegistryLoader(Protocol):
    def build_registry(self) -> dict[str, _CapabilityManifest]: ...


@dataclass(frozen=True)
class DecisionWriteSurfaceInventory:
    """Typed inventory consumed by the write-surface freeze guard."""

    http_interface_scopes: tuple[str, ...]
    http_surfaces: frozenset[str]
    sdk_module_scopes: tuple[str, ...]
    sdk_mutation_surfaces: frozenset[str]
    tui_published_graph: str
    tui_published_graph_sha256: str
    tui_decision_screen: str
    tui_decision_actions: frozenset[str]
    tui_mutation_actions: frozenset[str]
    mcp_position_related_write_capabilities: frozenset[str]


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
        tui_published_graph=str(payload.get("tui_published_graph") or ""),
        tui_published_graph_sha256=str(payload.get("tui_published_graph_sha256") or ""),
        tui_decision_screen=str(payload.get("tui_decision_screen") or ""),
        tui_decision_actions=frozenset(payload.get("tui_decision_actions") or ()),
        tui_mutation_actions=frozenset(payload.get("tui_mutation_actions") or ()),
        mcp_position_related_write_capabilities=frozenset(
            payload.get("mcp_position_related_write_capabilities") or ()
        ),
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


def _published_tui_actions(inventory: DecisionWriteSurfaceInventory) -> list[dict[str, object]]:
    path = REPO_ROOT / inventory.tui_published_graph
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != inventory.tui_published_graph_sha256:
        raise ValueError("published TUI graph changed without decision inventory review")
    payload = json.loads(path.read_text(encoding="utf-8"))
    actions = payload.get("actions")
    if not isinstance(actions, list):
        raise ValueError("published TUI actions must be a list")
    return [item for item in actions if isinstance(item, dict)]


def discover_tui_decision_actions(
    inventory: DecisionWriteSurfaceInventory,
) -> frozenset[str]:
    """Discover all actions on the published decision-flow screen."""

    return frozenset(
        str(item.get("key") or "")
        for item in _published_tui_actions(inventory)
        if item.get("screen_key") == inventory.tui_decision_screen
    )


def discover_tui_mutation_actions(
    inventory: DecisionWriteSurfaceInventory,
) -> frozenset[str]:
    """Discover published actions with mutation, AI, or admin semantics."""

    mutation_methods = {"DELETE", "PATCH", "POST", "PUT"}
    mutation_risks = {"admin", "ai", "write"}
    return frozenset(
        str(item.get("key") or "")
        for item in _published_tui_actions(inventory)
        if str(item.get("method") or "").upper() in mutation_methods
        or item.get("risk") in mutation_risks
    )


def discover_mcp_position_write_capabilities() -> frozenset[str]:
    """Discover governed writes whose tags can affect decisions or positions."""

    sdk_root = REPO_ROOT / "sdk"
    for path in (str(REPO_ROOT), str(sdk_root)):
        if path not in sys.path:
            sys.path.insert(0, path)
    position_tags = {
        "broker",
        "decision",
        "execution",
        "order",
        "portfolio",
        "position",
        "recommendation",
        "trade",
        "trading",
    }
    loader_module = importlib.import_module("agomtradepro_mcp.registry.loader")
    loader_type = cast(
        type[_CapabilityRegistryLoader],
        getattr(loader_module, "CapabilityRegistryLoader"),
    )
    registry = loader_type().build_registry()
    return frozenset(
        key
        for key, manifest in registry.items()
        if ("write" in {item.lower() for item in manifest.tags} or manifest.risk_level == "high")
        and bool({item.lower() for item in manifest.tags} & position_tags)
    )


def validate_surface_freeze(inventory: DecisionWriteSurfaceInventory) -> dict[str, int]:
    """Require discovered surfaces to exactly match the frozen inventories."""

    actual_http = discover_http_surfaces(inventory.http_interface_scopes)
    actual_sdk = discover_sdk_surfaces(inventory.sdk_module_scopes)
    actual_tui_decision = discover_tui_decision_actions(inventory)
    actual_tui_mutations = discover_tui_mutation_actions(inventory)
    actual_mcp = discover_mcp_position_write_capabilities()
    errors: list[str] = []
    for label, actual, expected in (
        ("HTTP", actual_http, inventory.http_surfaces),
        ("SDK", actual_sdk, inventory.sdk_mutation_surfaces),
        ("TUI decision", actual_tui_decision, inventory.tui_decision_actions),
        ("TUI mutation", actual_tui_mutations, inventory.tui_mutation_actions),
        (
            "MCP position write",
            actual_mcp,
            inventory.mcp_position_related_write_capabilities,
        ),
    ):
        added = sorted(actual - expected)
        removed = sorted(expected - actual)
        if added:
            errors.append(f"unclassified {label} mutation surfaces: {added}")
        if removed:
            errors.append(f"stale {label} mutation surfaces: {removed}")
    if errors:
        raise ValueError("Decision write surface freeze failed:\n- " + "\n- ".join(errors))
    return {
        "http_surface_count": len(actual_http),
        "sdk_surface_count": len(actual_sdk),
        "tui_decision_action_count": len(actual_tui_decision),
        "tui_mutation_action_count": len(actual_tui_mutations),
        "mcp_position_write_count": len(actual_mcp),
    }


def main() -> int:
    """Run the repository decision-write freeze guard."""

    summary = validate_surface_freeze(load_inventory())
    print("Decision write surface freeze OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
