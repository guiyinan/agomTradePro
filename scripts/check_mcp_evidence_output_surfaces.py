#!/usr/bin/env python
"""Freeze the first P0 MCP Evidence publication denominator."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for search_root in (REPO_ROOT, REPO_ROOT / "sdk"):
    if str(search_root) not in sys.path:
        sys.path.insert(0, str(search_root))

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from apps.terminal.application.tui_metadata import validate_tui_metadata

DEFAULT_INVENTORY = REPO_ROOT / "governance" / "mcp_evidence_output_surfaces.json"
TAGGED_READ_MARKERS = frozenset({"mcp:research_read", "mcp:decision_read", "mcp:decision_evidence"})
ALLOWED_STATES = frozenset(
    {
        "not_evidence_integrated_tagged_read",
        "not_evidence_integrated_native_dynamic",
        "not_evidence_integrated_dynamic_passthrough",
        "semantic_tag_overclaims_contract",
    }
)


@dataclass(frozen=True)
class McpEvidenceSurface:
    """One MCP output whose Evidence semantics remain explicitly unresolved."""

    capability_key: str
    executor_kind: str
    executor_ref: str
    raw_aliases: tuple[str, ...]
    output_schema_sha256: str
    publication_semantic: str
    current_gate_state: str


def _text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"MCP Evidence surface {key} must be non-empty text")
    return value


def _sha256_json(payload: object) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_inventory(
    path: Path = DEFAULT_INVENTORY,
) -> tuple[dict[str, object], tuple[McpEvidenceSurface, ...]]:
    """Load and strictly parse the machine-owned semantic freeze."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("MCP Evidence output inventory version must be 1")
    raw_surfaces = payload.get("surfaces")
    closure = payload.get("tui_action_closure")
    if not isinstance(raw_surfaces, list) or not raw_surfaces:
        raise ValueError("MCP Evidence output surfaces must be a non-empty list")
    if not isinstance(closure, dict):
        raise ValueError("MCP Evidence TUI action closure must be an object")
    surfaces: list[McpEvidenceSurface] = []
    for raw in raw_surfaces:
        if not isinstance(raw, dict):
            raise ValueError("MCP Evidence surface must be an object")
        aliases = raw.get("raw_aliases")
        if not isinstance(aliases, list) or any(not isinstance(item, str) for item in aliases):
            raise ValueError("MCP Evidence raw_aliases must be a text list")
        alias_tuple = tuple(aliases)
        if alias_tuple != tuple(sorted(set(alias_tuple))):
            raise ValueError("MCP Evidence raw_aliases must be sorted and unique")
        surface = McpEvidenceSurface(
            capability_key=_text(raw, "capability_key"),
            executor_kind=_text(raw, "executor_kind"),
            executor_ref=_text(raw, "executor_ref"),
            raw_aliases=alias_tuple,
            output_schema_sha256=_text(raw, "output_schema_sha256"),
            publication_semantic=_text(raw, "publication_semantic"),
            current_gate_state=_text(raw, "current_gate_state"),
        )
        if surface.current_gate_state not in ALLOWED_STATES:
            raise ValueError(f"unsupported MCP Evidence gate state: {surface.capability_key}")
        surfaces.append(surface)
    keys = tuple(surface.capability_key for surface in surfaces)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("MCP Evidence capability keys must be sorted and unique")
    return closure, tuple(surfaces)


def _is_p0_surface(manifest: Any) -> bool:
    tags = frozenset(manifest.audit_tags)
    return (
        bool(tags & TAGGED_READ_MARKERS)
        or (manifest.owner_app == "broker_execution" and "broker_execution:read" in tags)
        or manifest.capability_key == "terminal.read.user_action_result"
    )


def _validate_tui_closure(expected: dict[str, object]) -> None:
    path_value = _text(expected, "published_path")
    path = (REPO_ROOT / path_value).resolve(strict=True)
    if not path.is_relative_to(REPO_ROOT):
        raise ValueError("MCP Evidence TUI closure path escapes repository")
    raw = path.read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    normalized = validate_tui_metadata(copy.deepcopy(json.loads(raw.decode("utf-8"))))
    actions = normalized["actions"]
    read_keys = sorted(action["key"] for action in actions if action["risk"] == "read")
    actual: dict[str, object] = {
        "published_path": path_value,
        "published_sha256": raw_sha,
        "normalized_action_count": len(actions),
        "normalized_read_action_count": len(read_keys),
        "normalized_read_key_sha256": hashlib.sha256(
            "\n".join(read_keys).encode("utf-8")
        ).hexdigest(),
        "raw_debug_true_count": sum(action["raw_debug"] is True for action in actions),
        "evidence_binding_count": sum("evidence_binding" in action for action in actions),
    }
    if actual != expected:
        raise ValueError(f"MCP terminal read-action closure changed: {actual!r}")


def validate_inventory(
    closure: dict[str, object], surfaces: tuple[McpEvidenceSurface, ...]
) -> dict[str, int]:
    """Reject capability, schema, alias, semantic-state, or TUI closure drift."""

    manifests = CapabilityRegistryLoader().load_manifests()
    discovered = {
        manifest.capability_key: manifest for manifest in manifests if _is_p0_surface(manifest)
    }
    registered = {surface.capability_key: surface for surface in surfaces}
    if missing := sorted(discovered.keys() - registered.keys()):
        raise ValueError(f"unclassified P0 MCP Evidence outputs: {missing}")
    if stale := sorted(registered.keys() - discovered.keys()):
        raise ValueError(f"stale P0 MCP Evidence outputs: {stale}")
    for key, surface in registered.items():
        manifest = discovered[key]
        actual = (
            manifest.executor_kind,
            manifest.executor_ref,
            tuple(sorted(manifest.legacy_tool_names)),
            _sha256_json(manifest.output_schema),
        )
        expected = (
            surface.executor_kind,
            surface.executor_ref,
            surface.raw_aliases,
            surface.output_schema_sha256,
        )
        if actual != expected:
            raise ValueError(f"MCP Evidence output contract changed: {key}")
        if "mcp:decision_evidence" in manifest.audit_tags and (
            surface.current_gate_state != "semantic_tag_overclaims_contract"
        ):
            raise ValueError(f"MCP decision_evidence tag lacks explicit overclaim state: {key}")
    if any("evidence_integrated" == surface.current_gate_state for surface in surfaces):
        raise ValueError("semantic freeze must not claim MCP Evidence integration")
    _validate_tui_closure(closure)
    return {
        "surface_count": len(surfaces),
        "tagged_read_count": sum(
            bool(frozenset(discovered[s.capability_key].audit_tags) & TAGGED_READ_MARKERS)
            for s in surfaces
        ),
        "broker_native_count": sum(
            s.publication_semantic == "broker_execution_projection" for s in surfaces
        ),
        "integrated_count": 0,
    }


def main() -> int:
    """CLI entrypoint."""

    summary = validate_inventory(*load_inventory())
    print("MCP Evidence output semantic freeze OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
