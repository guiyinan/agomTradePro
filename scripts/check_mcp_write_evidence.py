#!/usr/bin/env python
"""Validate that governed MCP write capabilities have concrete migration evidence."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

from agomtradepro.unsupported_legacy_contracts import list_unsupported_legacy_contracts
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

TOOLS_ROOT = REPO_ROOT / "sdk" / "agomtradepro_mcp" / "tools"
SERVER_PATH = REPO_ROOT / "sdk" / "agomtradepro_mcp" / "server.py"
INTERNAL_HANDLERS_ROOT = REPO_ROOT / "sdk" / "agomtradepro_mcp" / "registry" / "internal_handlers"
READ_HANDLERS_ROOT = REPO_ROOT / "sdk" / "agomtradepro_mcp" / "registry" / "read_handlers"
RUNTIME_HANDLERS_ROOT = REPO_ROOT / "sdk" / "agomtradepro_mcp" / "registry" / "runtime_handlers"
CORE_REGISTRY_TEST_ROOT = REPO_ROOT / "sdk" / "tests" / "test_mcp"
AI_CAPABILITY_TEST_ROOT = REPO_ROOT / "tests" / "unit" / "test_ai_capability"

WRITE_ACTIONS = frozenset(
    {
        "activate",
        "add",
        "apply",
        "approve",
        "backfill",
        "bind",
        "cancel",
        "clear",
        "close",
        "create",
        "deactivate",
        "delete",
        "disable",
        "enable",
        "execute",
        "generate",
        "import",
        "invalidate",
        "migrate",
        "override",
        "publish",
        "refresh",
        "reject",
        "request",
        "remove",
        "repair",
        "replay",
        "reset",
        "resolve",
        "resume",
        "revoke",
        "rollback",
        "run",
        "set",
        "start",
        "stop",
        "submit",
        "sync",
        "toggle",
        "trigger",
        "unbind",
        "update",
        "upload",
    }
)

FUNCTION_BODY_RE = re.compile(
    r"^def\s+(?P<name>[_a-zA-Z0-9]+)\s*\([^)]*\)\s*(?:->\s*[^:]+)?:(?P<body>.*?)(?=^def\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)
LEGACY_FALLBACK_REF_RE = re.compile(
    r"['\"](?P<tool>[^'\"]+)['\"]:\s*(?:\(\s*)?" r"(?P<func>_fallback_[a-zA-Z0-9_]+)"
)
INTERNAL_HANDLER_REF_RE = re.compile(
    r"['\"](?P<handler>[^'\"]+)['\"]:\s*(?:\(\s*)?" r"(?P<func>_internal_handler_[a-zA-Z0-9_]+)"
)
INTERNAL_HANDLER_IMPORT_RE = re.compile(
    r"(?P<func>[a-zA-Z_][a-zA-Z0-9_]*)\s+as\s+"
    r"(?P<alias>_(?:internal_handler|fallback)_[a-zA-Z0-9_]+)"
)
RAW_TOOL_DEF_RE_TEMPLATE = r"def\s+{tool_name}\s*\("
EXHAUSTIVE_CATALOG_PROJECTION_MARKERS = (
    "GOVERNED_MANIFESTS",
    "test_governed_manifest_legacy_projection_matrix_preserves_every_alias",
    "build_legacy_replacement_map",
    "for manifest in GOVERNED_MANIFESTS",
    "for legacy_tool_name in manifest.legacy_tool_names",
    "replacement_capability_key",
)


def collect_manifests(loader: CapabilityRegistryLoader | None = None):
    """Load all configured MCP capability manifests."""
    active_loader = loader or CapabilityRegistryLoader()
    return active_loader.load_manifests()


def _extract_action_token(capability_key: str) -> str:
    parts = [part.strip().lower() for part in capability_key.split(".") if part.strip()]
    if len(parts) >= 2:
        return parts[1]
    return ""


def is_write_like_manifest(manifest) -> bool:
    """Return True when a manifest looks like a write/side-effect capability."""

    if "mcp:write" in manifest.audit_tags or "write" in manifest.tags:
        return True
    action = _extract_action_token(manifest.capability_key)
    if action in WRITE_ACTIONS:
        return True
    return any(part in WRITE_ACTIONS for part in action.split("_") if part)


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_function_bodies(text: str) -> dict[str, str]:
    return {match.group("name"): match.group("body") for match in FUNCTION_BODY_RE.finditer(text)}


def _load_raw_tool_source_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for path in sorted(TOOLS_ROOT.glob("*_tools.py")):
        text = _load_text(path)
        for match in re.finditer(r"^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", text, re.MULTILINE):
            index[match.group(1)] = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    return index


def _load_server_evidence_index() -> dict[str, object]:
    text = _load_text(SERVER_PATH)
    function_bodies = _load_function_bodies(text)
    extracted_handler_bodies: dict[str, str] = {}
    runtime_texts: list[str] = []
    for root in (INTERNAL_HANDLERS_ROOT, READ_HANDLERS_ROOT, RUNTIME_HANDLERS_ROOT):
        for path in sorted(root.rglob("*.py")):
            handler_text = _load_text(path)
            runtime_texts.append(handler_text)
            extracted_handler_bodies.update(_load_function_bodies(handler_text))
    for match in INTERNAL_HANDLER_IMPORT_RE.finditer(text):
        body = extracted_handler_bodies.get(match.group("func"))
        if body is not None:
            function_bodies[match.group("alias")] = body
    evidence_text = "\n".join([text, *runtime_texts])
    function_bodies.update(extracted_handler_bodies)
    legacy_fallbacks = {
        match.group("tool"): match.group("func")
        for match in LEGACY_FALLBACK_REF_RE.finditer(evidence_text)
    }
    internal_handlers = {
        match.group("handler"): match.group("func")
        for match in INTERNAL_HANDLER_REF_RE.finditer(evidence_text)
    }
    return {
        "text": text,
        "function_bodies": function_bodies,
        "legacy_fallbacks": legacy_fallbacks,
        "internal_handlers": internal_handlers,
    }


def _load_test_text(root: Path, pattern: str) -> str:
    """Load focused evidence from all controlled test shards under one owner root."""

    return "\n".join(_load_text(path) for path in sorted(root.glob(pattern)))


def _unsupported_contract_keys() -> set[str]:
    return {contract.contract_key for contract in list_unsupported_legacy_contracts()}


def _has_exhaustive_catalog_projection_evidence(test_text: str) -> bool:
    """Return whether tests cover every loaded manifest and declared legacy alias."""

    return all(marker in test_text for marker in EXHAUSTIVE_CATALOG_PROJECTION_MARKERS)


def validate_write_evidence_manifests(
    manifests,
    *,
    raw_tool_index: dict[str, str],
    server_evidence_index: dict[str, object],
    core_registry_text: str,
    ai_capability_text: str,
    unsupported_contract_keys: set[str],
) -> dict[str, int]:
    """Reject governed write manifests that lack raw tool, execution, or test evidence."""
    total = len(manifests)
    write_like = 0
    legacy_executor = 0
    internal_handler_executor = 0
    raw_tool_covered = 0
    execution_evidence_covered = 0
    contract_test_covered = 0

    function_bodies = server_evidence_index["function_bodies"]
    legacy_fallbacks = server_evidence_index["legacy_fallbacks"]
    internal_handlers = server_evidence_index["internal_handlers"]
    has_exhaustive_catalog_evidence = _has_exhaustive_catalog_projection_evidence(
        ai_capability_text
    )

    for manifest in manifests:
        if not is_write_like_manifest(manifest):
            continue

        write_like += 1
        if manifest.capability_key in unsupported_contract_keys:
            raise ValueError(
                "Unsupported legacy contract must not be registered as a governed write manifest: "
                f"{manifest.capability_key}"
            )
        is_native_handler = (
            manifest.executor_kind == "internal_handler"
            and not manifest.legacy_tool_names
            and "mcp:native" in manifest.audit_tags
        )
        if not manifest.legacy_tool_names and not is_native_handler:
            raise ValueError(
                "Governed MCP write manifest must declare legacy_tool_names for raw-tool evidence: "
                f"{manifest.capability_key}"
            )

        if not is_native_handler:
            for tool_name in manifest.legacy_tool_names:
                if tool_name not in raw_tool_index:
                    raise ValueError(
                        "Governed MCP write manifest is missing raw tool evidence for legacy tool "
                        f"{tool_name}: {manifest.capability_key}"
                    )
                if tool_name not in ai_capability_text and not has_exhaustive_catalog_evidence:
                    raise ValueError(
                        "Governed MCP write manifest is missing AI capability replacement test evidence "
                        f"for legacy tool {tool_name}: {manifest.capability_key}"
                    )
            raw_tool_covered += 1

        if manifest.executor_kind == "legacy_tool":
            legacy_executor += 1
            fallback_name = legacy_fallbacks.get(manifest.executor_ref)
            if fallback_name is None:
                raise ValueError(
                    "Governed MCP write manifest is missing server fallback evidence: "
                    f"{manifest.capability_key}"
                )
            fallback_body = function_bodies.get(fallback_name, "")
            if "AgomTradeProClient" not in fallback_body:
                raise ValueError(
                    "Governed MCP write manifest fallback must show SDK transport evidence: "
                    f"{manifest.capability_key}"
                )
        elif manifest.executor_kind == "internal_handler":
            internal_handler_executor += 1
            handler_name = internal_handlers.get(manifest.executor_ref)
            if handler_name is None:
                raise ValueError(
                    "Governed MCP write manifest is missing internal handler evidence: "
                    f"{manifest.capability_key}"
                )
            handler_body = function_bodies.get(handler_name, "")
            if "preview_only" not in handler_body:
                raise ValueError(
                    "Governed MCP internal handler must expose preview/commit flow evidence: "
                    f"{manifest.capability_key}"
                )
        else:
            raise ValueError(
                f"Unsupported executor_kind for write evidence validation: {manifest.executor_kind}"
            )
        execution_evidence_covered += 1

        if manifest.capability_key not in core_registry_text:
            raise ValueError(
                "Governed MCP write manifest is missing core registry regression evidence: "
                f"{manifest.capability_key}"
            )
        if (
            manifest.capability_key not in ai_capability_text
            and not has_exhaustive_catalog_evidence
        ):
            raise ValueError(
                "Governed MCP write manifest is missing AI capability sync evidence: "
                f"{manifest.capability_key}"
            )
        contract_test_covered += 1

    return {
        "total_manifests": total,
        "write_like_manifests": write_like,
        "legacy_executor_manifests": legacy_executor,
        "internal_handler_manifests": internal_handler_executor,
        "raw_tool_evidence_manifests": raw_tool_covered,
        "execution_evidence_manifests": execution_evidence_covered,
        "contract_test_evidence_manifests": contract_test_covered,
    }


def main() -> int:
    """CLI entrypoint for MCP write-evidence validation."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate that governed MCP write capabilities have raw tool, execution, "
            "and contract-test evidence before migration."
        ),
    )
    parser.parse_args()

    manifests = collect_manifests()
    summary = validate_write_evidence_manifests(
        manifests,
        raw_tool_index=_load_raw_tool_source_index(),
        server_evidence_index=_load_server_evidence_index(),
        core_registry_text=_load_test_text(CORE_REGISTRY_TEST_ROOT, "test_*registry*.py"),
        ai_capability_text=_load_test_text(AI_CAPABILITY_TEST_ROOT, "test_*.py"),
        unsupported_contract_keys=_unsupported_contract_keys(),
    )
    print("MCP write-evidence guard OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
