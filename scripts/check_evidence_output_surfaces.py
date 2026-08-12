#!/usr/bin/env python
"""Freeze the classified denominator of decision-facing output symbols."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "governance" / "evidence_output_surfaces.json"
CLAIM_KINDS = frozenset({"observation", "derived", "estimate", "forecast", "recommendation"})
METHOD_KINDS = frozenset(
    {"identity", "deterministic", "statistical", "simulation", "human_judgment"}
)
POSITION_IMPACTS = frozenset({"direct", "indirect"})
GATE_STATES = frozenset(
    {
        "not_evidence_integrated_legacy_boolean",
        "not_evidence_integrated_legacy_ungated",
        "not_evidence_integrated_governed_input",
        "not_evidence_integrated_research_only",
        "legacy_evidence_wrapped_display_only",
    }
)
OUTPUT_KINDS = frozenset(
    {
        "approval_snapshot",
        "current_state",
        "data_reliability",
        "execution_decision",
        "execution_feedback",
        "execution_preview",
        "invalidation_assessment",
        "market_observation",
        "monitoring_assessment",
        "order_intent",
        "recommendation",
        "research_assessment",
        "risk_gate_state",
        "scored_forecast",
        "transition_order",
        "transition_plan",
    }
)


@dataclass(frozen=True)
class DiscoveryRule:
    """One source file and the fields that identify high-risk output classes."""

    path: str
    marker_fields: frozenset[str]


@dataclass(frozen=True)
class EvidenceOutputSurface:
    """One explicitly classified decision-facing output symbol."""

    source_symbol: str
    owner_app: str
    output_kind: str
    claim_kind: str
    method_kind: str
    position_impact: str
    current_gate_state: str
    required_fields: frozenset[str]
    composite_fields: frozenset[str]


@dataclass(frozen=True)
class EvidenceOutputInventory:
    """Typed first-batch output inventory consumed by the freeze guard."""

    discovery_rules: tuple[DiscoveryRule, ...]
    surfaces: tuple[EvidenceOutputSurface, ...]
    dynamic_surfaces: frozenset[str]


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"evidence output surface field {key} must be non-empty text")
    return value


def _required_text_list(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"evidence output surface field {key} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"evidence output surface field {key} contains an invalid item")
    items = tuple(value)
    if items != tuple(sorted(set(items))):
        raise ValueError(f"evidence output surface field {key} must be sorted and unique")
    return items


def _optional_text_list(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"evidence output surface field {key} must be a list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"evidence output surface field {key} contains an invalid item")
    items = tuple(value)
    if items != tuple(sorted(set(items))):
        raise ValueError(f"evidence output surface field {key} must be sorted and unique")
    return items


def parse_inventory(payload: object) -> EvidenceOutputInventory:
    """Parse untrusted JSON and reject incomplete or unclassified entries."""

    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("evidence output surface inventory version must be 1")
    for key, canonical in (
        ("allowed_claim_kinds", CLAIM_KINDS),
        ("allowed_method_kinds", METHOD_KINDS),
        ("allowed_position_impacts", POSITION_IMPACTS),
        ("allowed_gate_states", GATE_STATES),
    ):
        declared = frozenset(_required_text_list(payload, key))
        if not declared or not declared <= canonical:
            raise ValueError(f"evidence output surface {key} differs from canonical values")

    raw_rules = payload.get("discovery_rules")
    raw_surfaces = payload.get("surfaces")
    raw_dynamic = payload.get("dynamic_surfaces")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ValueError("evidence output discovery_rules must be a non-empty list")
    if not isinstance(raw_surfaces, list) or not raw_surfaces:
        raise ValueError("evidence output surfaces must be a non-empty list")
    if not isinstance(raw_dynamic, list) or not raw_dynamic:
        raise ValueError("evidence output dynamic_surfaces must be a non-empty list")
    dynamic_surfaces = tuple(raw_dynamic)
    if any(not isinstance(item, str) or not item.strip() for item in dynamic_surfaces):
        raise ValueError("evidence output dynamic surface must be non-empty text")
    if dynamic_surfaces != tuple(sorted(set(dynamic_surfaces))):
        raise ValueError("evidence output dynamic surfaces must be sorted and unique")

    rules: list[DiscoveryRule] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise ValueError("evidence output discovery rule must be an object")
        rules.append(
            DiscoveryRule(
                path=_required_text(raw_rule, "path"),
                marker_fields=frozenset(_required_text_list(raw_rule, "marker_fields")),
            )
        )
    if tuple(rule.path for rule in rules) != tuple(sorted({rule.path for rule in rules})):
        raise ValueError("evidence output discovery rules must be sorted and unique")

    surfaces: list[EvidenceOutputSurface] = []
    for raw_surface in raw_surfaces:
        if not isinstance(raw_surface, dict):
            raise ValueError("evidence output surface must be an object")
        surface = EvidenceOutputSurface(
            source_symbol=_required_text(raw_surface, "source_symbol"),
            owner_app=_required_text(raw_surface, "owner_app"),
            output_kind=_required_text(raw_surface, "output_kind"),
            claim_kind=_required_text(raw_surface, "claim_kind"),
            method_kind=_required_text(raw_surface, "method_kind"),
            position_impact=_required_text(raw_surface, "position_impact"),
            current_gate_state=_required_text(raw_surface, "current_gate_state"),
            required_fields=frozenset(_required_text_list(raw_surface, "required_fields")),
            composite_fields=frozenset(_optional_text_list(raw_surface, "composite_fields")),
        )
        if "unclassified" in {
            surface.output_kind,
            surface.claim_kind,
            surface.method_kind,
            surface.position_impact,
            surface.current_gate_state,
        }:
            raise ValueError(f"unclassified evidence output surface: {surface.source_symbol}")
        if surface.output_kind not in OUTPUT_KINDS:
            raise ValueError(f"unknown output_kind for {surface.source_symbol}")
        if surface.claim_kind not in CLAIM_KINDS:
            raise ValueError(f"unknown claim_kind for {surface.source_symbol}")
        if surface.method_kind not in METHOD_KINDS:
            raise ValueError(f"unknown method_kind for {surface.source_symbol}")
        if surface.position_impact not in POSITION_IMPACTS:
            raise ValueError(f"unknown position_impact for {surface.source_symbol}")
        if surface.current_gate_state not in GATE_STATES:
            raise ValueError(f"unknown current_gate_state for {surface.source_symbol}")
        if not surface.composite_fields <= surface.required_fields:
            raise ValueError(
                f"composite_fields must be required fields for {surface.source_symbol}"
            )
        surfaces.append(surface)
    symbols = tuple(surface.source_symbol for surface in surfaces)
    if symbols != tuple(sorted(set(symbols))):
        raise ValueError("evidence output surfaces must be sorted and unique")
    return EvidenceOutputInventory(
        discovery_rules=tuple(rules),
        surfaces=tuple(surfaces),
        dynamic_surfaces=frozenset(dynamic_surfaces),
    )


def load_inventory(path: Path = DEFAULT_INVENTORY) -> EvidenceOutputInventory:
    """Load the repository output inventory without importing business modules."""

    return parse_inventory(json.loads(path.read_text(encoding="utf-8")))


def _parse_source(relative_path: str) -> ast.Module:
    path = REPO_ROOT / relative_path
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"evidence output source file is missing: {relative_path}") from exc
    if not resolved.is_relative_to(REPO_ROOT):
        raise ValueError(f"evidence output source escapes repository: {relative_path}")
    return ast.parse(resolved.read_text(encoding="utf-8"), filename=str(resolved))


def _module_classes(module: ast.Module) -> dict[str, ast.ClassDef]:
    return {node.name: node for node in module.body if isinstance(node, ast.ClassDef)}


def _class_fields(node: ast.ClassDef) -> frozenset[str]:
    fields = {
        child.target.id
        for child in node.body
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
    }
    fields.update(
        child.name
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(decorator, ast.Name) and decorator.id == "property"
            for decorator in child.decorator_list
        )
    )
    return frozenset(fields)


def _split_symbol(source_symbol: str) -> tuple[str, str]:
    parts = source_symbol.split("::")
    if len(parts) != 2 or not parts[0].endswith(".py") or not parts[1].isidentifier():
        raise ValueError(f"invalid evidence output source_symbol: {source_symbol}")
    return parts[0], parts[1]


def discover_marked_surfaces(
    rules: tuple[DiscoveryRule, ...],
) -> frozenset[str]:
    """Discover classes carrying configured high-risk output markers."""

    discovered: set[str] = set()
    for rule in rules:
        classes = _module_classes(_parse_source(rule.path))
        for class_name, node in classes.items():
            if _class_fields(node) & rule.marker_fields:
                discovered.add(f"{rule.path}::{class_name}")
    return frozenset(discovered)


def _qualified_functions(path: str) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in _parse_source(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions[f"{node.name}.{member.name}"] = member
    return functions


def discover_dynamic_surfaces() -> frozenset[str]:
    """Freeze Broker query publications and typed internal research presenters."""

    query_path = "apps/broker_execution/application/query_services.py"
    view_path = "apps/broker_execution/interface/api_views.py"
    query_methods = _qualified_functions(query_path)
    view_methods = _qualified_functions(view_path)
    discovered: set[str] = set()
    for qualname, node in query_methods.items():
        if not qualname.startswith("BrokerExecutionQueryService.") or qualname.endswith(
            ".__init__"
        ):
            continue
        returns = ast.unparse(node.returns) if node.returns is not None else ""
        if returns == "dict[str, Any]":
            discovered.add(f"{query_path}::{qualname}")
    query_names = {item.rsplit(".", 1)[-1] for item in discovered}
    for qualname, node in view_methods.items():
        if not qualname.endswith(".get"):
            continue
        calls = {
            child.func.attr
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr in query_names
        }
        if calls:
            discovered.add(f"{view_path}::{qualname}")
    for presenter_path, presenter_name in (
        (
            "apps/fixed_income/interface/presenters.py",
            "present_fixed_income_research_preview",
        ),
        (
            "apps/macro_factor/interface/presenters.py",
            "present_macro_factor_assessment",
        ),
    ):
        presenter = _qualified_functions(presenter_path).get(presenter_name)
        if presenter is None or presenter.returns is None:
            raise ValueError(f"evidence output presenter is missing: {presenter_path}")
        if ast.unparse(presenter.returns) != "dict[str, object]":
            raise ValueError(f"evidence output presenter contract changed: {presenter_path}")
        discovered.add(f"{presenter_path}::{presenter_name}")
    return frozenset(discovered)


def validate_inventory(inventory: EvidenceOutputInventory) -> dict[str, int]:
    """Require all registered symbols and marker-discovered surfaces to stay exact."""

    errors: list[str] = []
    registered = {surface.source_symbol: surface for surface in inventory.surfaces}
    modules: dict[str, dict[str, ast.ClassDef]] = {}
    for surface in inventory.surfaces:
        path, class_name = _split_symbol(surface.source_symbol)
        classes = modules.setdefault(path, _module_classes(_parse_source(path)))
        node = classes.get(class_name)
        if node is None:
            errors.append(f"stale evidence output symbol: {surface.source_symbol}")
            continue
        missing_fields = sorted(surface.required_fields - _class_fields(node))
        if missing_fields:
            errors.append(
                f"changed evidence output contract {surface.source_symbol}; "
                f"missing fields: {missing_fields}"
            )

    discovered = discover_marked_surfaces(inventory.discovery_rules)
    unclassified = sorted(discovered - registered.keys())
    if unclassified:
        errors.append(f"unclassified marked evidence output surfaces: {unclassified}")
    dynamic = discover_dynamic_surfaces()
    missing_dynamic = sorted(dynamic - inventory.dynamic_surfaces)
    stale_dynamic = sorted(inventory.dynamic_surfaces - dynamic)
    if missing_dynamic:
        errors.append(f"unclassified dynamic evidence output surfaces: {missing_dynamic}")
    if stale_dynamic:
        errors.append(f"stale dynamic evidence output surfaces: {stale_dynamic}")
    if errors:
        raise ValueError("Evidence output surface freeze failed:\n- " + "\n- ".join(errors))
    return {
        "surface_count": len(registered),
        "direct_position_surface_count": sum(
            surface.position_impact == "direct" for surface in inventory.surfaces
        ),
        "marked_surface_count": len(discovered),
        "dynamic_surface_count": len(dynamic),
    }


def main() -> int:
    """Run the first-batch decision-output inventory guard."""

    summary = validate_inventory(load_inventory())
    print("Evidence output surface freeze OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
