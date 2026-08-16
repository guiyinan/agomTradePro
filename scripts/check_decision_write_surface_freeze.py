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
INTERNAL_WRITER_OWNERSHIPS = frozenset({"decision_rhythm_legacy", "portfolio_canonical"})


class _CapabilityManifest(Protocol):
    tags: tuple[str, ...]
    risk_level: str


class _CapabilityRegistryLoader(Protocol):
    def build_registry(self) -> dict[str, _CapabilityManifest]: ...


@dataclass(frozen=True)
class TransitionPlanInternalWriter:
    """One classified internal transition-plan mutation boundary."""

    source_symbol: str
    ownership: str
    mutation_semantic: str
    enabled_by_default: bool
    replacement: str | None
    required_ast_calls: frozenset[str]


@dataclass(frozen=True)
class DecisionWriteSurfaceInventory:
    """Typed inventory consumed by the write-surface freeze guard."""

    transition_plan_internal_writer_scopes: tuple[str, ...]
    transition_plan_internal_writers: tuple[TransitionPlanInternalWriter, ...]
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
    raw_writer_scopes = _sorted_text_list(
        payload.get("transition_plan_internal_writer_scopes"),
        "transition_plan_internal_writer_scopes",
    )
    raw_writers = payload.get("transition_plan_internal_writers")
    if not isinstance(raw_writers, list) or not raw_writers:
        raise ValueError("transition_plan_internal_writers must be a non-empty list")
    writers: list[TransitionPlanInternalWriter] = []
    for raw_writer in raw_writers:
        if not isinstance(raw_writer, dict):
            raise ValueError("transition plan internal writer must be an object")
        ownership = _required_text(raw_writer, "ownership")
        if ownership not in INTERNAL_WRITER_OWNERSHIPS:
            raise ValueError(f"unknown transition plan writer ownership: {ownership}")
        enabled_by_default = raw_writer.get("enabled_by_default")
        if not isinstance(enabled_by_default, bool):
            raise ValueError("transition plan writer enabled_by_default must be boolean")
        replacement = raw_writer.get("replacement")
        if ownership == "decision_rhythm_legacy":
            if not isinstance(replacement, str) or not replacement.strip():
                raise ValueError("legacy transition plan writer replacement must be non-empty text")
        elif replacement is not None:
            raise ValueError("canonical transition plan writer replacement must be null")
        writers.append(
            TransitionPlanInternalWriter(
                source_symbol=_required_text(raw_writer, "source_symbol"),
                ownership=ownership,
                mutation_semantic=_required_text(raw_writer, "mutation_semantic"),
                enabled_by_default=enabled_by_default,
                replacement=replacement,
                required_ast_calls=frozenset(
                    _sorted_text_list(raw_writer.get("required_ast_calls"), "required_ast_calls")
                ),
            )
        )
    writer_symbols = tuple(writer.source_symbol for writer in writers)
    if writer_symbols != tuple(sorted(set(writer_symbols))):
        raise ValueError("transition_plan_internal_writers must be sorted and unique")
    inventory = DecisionWriteSurfaceInventory(
        transition_plan_internal_writer_scopes=raw_writer_scopes,
        transition_plan_internal_writers=tuple(writers),
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


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"decision write surface field {key} must be non-empty text")
    return value


def _sorted_text_list(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"decision write surface field {key} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"decision write surface field {key} contains an invalid item")
    items = tuple(value)
    if items != tuple(sorted(set(items))):
        raise ValueError(f"decision write surface field {key} must be sorted and unique")
    return items


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _call_name(node.value)
        return f"{owner}.{node.attr}" if owner else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return None


def _function_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    return frozenset(
        call_name
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and (call_name := _call_name(child.func)) is not None
    )


def _guarded_transition_plan_update(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Check that only plan-linked approval updates invoke the legacy guard."""

    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        if ast.unparse(node.test) != "model.transition_plan is not None":
            continue
        return any(
            isinstance(child, ast.Call)
            and _call_name(child.func) == "_ensure_legacy_transition_plan_write_enabled"
            for statement in node.body
            for child in ast.walk(statement)
        )
    return False


def _source_functions(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in _parse(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions[f"{node.name}.{member.name}"] = member
    return functions


def discover_transition_plan_internal_writers(
    scopes: tuple[str, ...],
) -> frozenset[str]:
    """Discover the two legacy and canonical internal writer families."""

    discovered: set[str] = set()
    for scope in scopes:
        path = REPO_ROOT / scope
        for qualname, function in _source_functions(path).items():
            calls = _function_calls(function)
            is_writer = False
            if scope.endswith("decision_rhythm/application/workspace_services.py"):
                is_writer = "get_portfolio_transition_plan_repository.save" in calls
            elif scope.endswith("decision_rhythm/infrastructure/recommendation_repositories.py"):
                if qualname.startswith("PortfolioTransitionPlanRepository."):
                    is_writer = bool(
                        {
                            "PortfolioTransitionPlanModel.objects.update_or_create",
                            "model.save",
                        }
                        & calls
                    )
                elif qualname.startswith("ExecutionApprovalRequestRepository."):
                    is_writer = bool(
                        {
                            "plan_model.save",
                            "model.transition_plan.save",
                        }
                        & calls
                    )
            elif scope.endswith("portfolio/application/use_cases.py"):
                is_writer = bool({"self._repository.save", "self._repository.approve"} & calls)
            elif scope.endswith("portfolio/infrastructure/repositories.py"):
                if qualname.startswith("PortfolioTransitionPlanRepository."):
                    is_writer = bool(
                        {
                            "PortfolioTransitionPlanModel._default_manager.create",
                            "row.save",
                        }
                        & calls
                    )
            if is_writer:
                discovered.add(f"{scope}::{qualname}")
    return frozenset(discovered)


def _validate_transition_plan_internal_writers(
    inventory: DecisionWriteSurfaceInventory,
) -> list[str]:
    errors: list[str] = []
    registered = {
        writer.source_symbol: writer for writer in inventory.transition_plan_internal_writers
    }
    discovered = discover_transition_plan_internal_writers(
        inventory.transition_plan_internal_writer_scopes
    )
    unregistered = sorted(discovered - registered.keys())
    stale = sorted(registered.keys() - discovered)
    if unregistered:
        errors.append(f"unregistered transition plan internal writers: {unregistered}")
    if stale:
        errors.append(f"stale transition plan internal writers: {stale}")
    for symbol, writer in registered.items():
        if symbol not in discovered:
            continue
        relative_path, qualname = symbol.split("::", maxsplit=1)
        function = _source_functions(REPO_ROOT / relative_path).get(qualname)
        if function is None:
            continue
        missing_calls = sorted(writer.required_ast_calls - _function_calls(function))
        if missing_calls:
            errors.append(
                f"transition plan internal writer AST calls changed for {symbol}: {missing_calls}"
            )
        if symbol.endswith("::ExecutionApprovalRequestRepository.update_status") and not (
            _guarded_transition_plan_update(function)
        ):
            errors.append(
                "transition plan approval status update lost its conditional canonical-mode guard"
            )
    return errors


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
    # Git checkouts may materialize this JSON with CRLF on Windows and LF on
    # Linux.  The governance hash is over the canonical LF representation so
    # the review gate is checkout-stable without weakening content checks.
    canonical_bytes = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    digest = hashlib.sha256(canonical_bytes).hexdigest()
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
    errors = _validate_transition_plan_internal_writers(inventory)
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
        "transition_plan_internal_writer_count": len(inventory.transition_plan_internal_writers),
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
