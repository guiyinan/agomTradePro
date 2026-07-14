#!/usr/bin/env python
"""Validate that governed MCP read capabilities have concrete migration evidence."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
for search_root in (REPO_ROOT, SDK_ROOT):
    if str(search_root) not in sys.path:
        sys.path.insert(0, str(search_root))

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

from scripts.check_mcp_write_evidence import (
    _load_raw_tool_source_index,
    _load_server_evidence_index,
    _unsupported_contract_keys,
    is_write_like_manifest,
)

CORE_REGISTRY_TEST_ROOT = REPO_ROOT / "sdk" / "tests" / "test_mcp"
AI_CAPABILITY_TEST_ROOT = REPO_ROOT / "tests" / "unit" / "test_ai_capability"
SDK_TEST_ROOT = REPO_ROOT / "sdk" / "tests" / "test_sdk"
SDK_CALL_RE = re.compile(
    r"client\.(?P<module>[a-zA-Z_][a-zA-Z0-9_]*)\." r"(?P<method>[a-zA-Z_][a-zA-Z0-9_]*)\s*\("
)


def collect_manifests(loader: CapabilityRegistryLoader | None = None):
    """Load all configured MCP capability manifests."""
    active_loader = loader or CapabilityRegistryLoader()
    return active_loader.load_manifests()


def _load_test_blocks(path: Path) -> list[str]:
    """Return complete test blocks, including decorators and class test methods."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text, filename=str(path))
    blocks: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_") or node.end_lineno is None:
            continue
        start_line = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
        blocks.append("\n".join(lines[start_line - 1 : node.end_lineno]))
    return blocks


def _load_sdk_test_blocks() -> list[str]:
    blocks: list[str] = []
    for path in sorted(SDK_TEST_ROOT.rglob("test_*.py")):
        blocks.extend(_load_test_blocks(path))
    return blocks


def _load_test_blocks_from_root(root: Path, pattern: str = "test_*.py") -> list[str]:
    """Return focused test blocks from controlled owner shards."""

    blocks: list[str] = []
    for path in sorted(root.glob(pattern)):
        blocks.extend(_load_test_blocks(path))
    return blocks


def _sdk_call_tokens(fallback_body: str) -> tuple[str, ...]:
    return tuple(
        f".{match.group('module')}.{match.group('method')}("
        for match in SDK_CALL_RE.finditer(fallback_body)
    )


def _has_core_only_test_evidence(
    manifest,
    *,
    test_blocks: list[str],
) -> bool:
    evidence_marker = (
        "INTERNAL_GOVERNED_HANDLERS"
        if manifest.executor_kind == "internal_handler"
        else "INTERNAL_LEGACY_TOOL_FALLBACKS"
    )
    return any(
        manifest.capability_key in block
        and "agom_capability_call" in block
        and evidence_marker in block
        and all(tool_name in block for tool_name in manifest.legacy_tool_names)
        for block in test_blocks
    )


def _has_catalog_replacement_test_evidence(
    manifest,
    *,
    test_blocks: list[str],
) -> bool:
    return any(
        manifest.capability_key in block
        and "replacement_capability_key" in block
        and all(tool_name in block for tool_name in manifest.legacy_tool_names)
        for block in test_blocks
    )


def validate_read_evidence_manifests(
    manifests,
    *,
    raw_tool_index: dict[str, str],
    server_evidence_index: dict[str, object],
    core_registry_test_blocks: list[str],
    ai_capability_test_blocks: list[str],
    sdk_test_blocks: list[str],
    unsupported_contract_keys: set[str],
) -> dict[str, int]:
    """Reject governed read manifests that lack execution and focused test evidence."""
    total = len(manifests)
    read_like = 0
    raw_tool_covered = 0
    fallback_covered = 0
    sdk_contract_covered = 0
    core_only_test_covered = 0
    catalog_test_covered = 0
    native_handler_covered = 0

    function_bodies = server_evidence_index["function_bodies"]
    legacy_fallbacks = server_evidence_index["legacy_fallbacks"]
    internal_handlers = server_evidence_index["internal_handlers"]

    for manifest in manifests:
        if is_write_like_manifest(manifest):
            continue

        read_like += 1
        if manifest.capability_key in unsupported_contract_keys:
            raise ValueError(
                "Unsupported legacy contract must not be registered as a governed read manifest: "
                f"{manifest.capability_key}"
            )
        is_native_handler = (
            manifest.executor_kind == "internal_handler"
            and not manifest.legacy_tool_names
            and "mcp:native" in manifest.audit_tags
        )
        if is_native_handler:
            handler_name = internal_handlers.get(manifest.executor_ref)
            if handler_name is None or not function_bodies.get(handler_name, ""):
                raise ValueError(
                    "Governed native MCP read manifest is missing internal handler evidence: "
                    f"{manifest.capability_key}"
                )
            if not _has_core_only_test_evidence(
                manifest,
                test_blocks=core_registry_test_blocks,
            ):
                raise ValueError(
                    "Governed native MCP read manifest is missing core-only evidence: "
                    f"{manifest.capability_key}"
                )
            if not any(
                manifest.capability_key in block for block in ai_capability_test_blocks
            ):
                raise ValueError(
                    "Governed native MCP read manifest is missing catalog projection evidence: "
                    f"{manifest.capability_key}"
                )
            native_handler_covered += 1
            core_only_test_covered += 1
            catalog_test_covered += 1
            continue

        if manifest.executor_kind != "legacy_tool":
            raise ValueError(
                "Governed MCP read evidence currently requires a controlled legacy_tool "
                f"fallback: {manifest.capability_key}"
            )
        if not manifest.legacy_tool_names:
            raise ValueError(
                "Governed MCP read manifest must declare legacy_tool_names for raw-tool evidence: "
                f"{manifest.capability_key}"
            )

        for tool_name in manifest.legacy_tool_names:
            if tool_name not in raw_tool_index:
                raise ValueError(
                    "Governed MCP read manifest is missing raw tool evidence for legacy tool "
                    f"{tool_name}: {manifest.capability_key}"
                )
        raw_tool_covered += 1

        fallback_name = legacy_fallbacks.get(manifest.executor_ref)
        if fallback_name is None:
            raise ValueError(
                "Governed MCP read manifest is missing server fallback evidence: "
                f"{manifest.capability_key}"
            )
        fallback_body = function_bodies.get(fallback_name, "")
        if "AgomTradeProClient" not in fallback_body:
            raise ValueError(
                "Governed MCP read fallback must show SDK transport evidence: "
                f"{manifest.capability_key}"
            )
        fallback_covered += 1

        sdk_call_tokens = _sdk_call_tokens(fallback_body)
        if not sdk_call_tokens:
            raise ValueError(
                "Governed MCP read fallback has no identifiable SDK method call: "
                f"{manifest.capability_key}"
            )
        for call_token in sdk_call_tokens:
            if not any(call_token in block and "assert" in block for block in sdk_test_blocks):
                raise ValueError(
                    "Governed MCP read manifest is missing focused SDK contract evidence "
                    f"for {call_token}: {manifest.capability_key}"
                )
        sdk_contract_covered += 1

        if not _has_core_only_test_evidence(
            manifest,
            test_blocks=core_registry_test_blocks,
        ):
            raise ValueError(
                "Governed MCP read manifest is missing core-only capability-call evidence: "
                f"{manifest.capability_key}"
            )
        core_only_test_covered += 1

        if not _has_catalog_replacement_test_evidence(
            manifest,
            test_blocks=ai_capability_test_blocks,
        ):
            raise ValueError(
                "Governed MCP read manifest is missing catalog replacement evidence: "
                f"{manifest.capability_key}"
            )
        catalog_test_covered += 1

    return {
        "total_manifests": total,
        "read_like_manifests": read_like,
        "raw_tool_evidence_manifests": raw_tool_covered,
        "fallback_evidence_manifests": fallback_covered,
        "sdk_contract_evidence_manifests": sdk_contract_covered,
        "core_only_test_evidence_manifests": core_only_test_covered,
        "catalog_test_evidence_manifests": catalog_test_covered,
        "native_handler_evidence_manifests": native_handler_covered,
    }


def main() -> int:
    """CLI entrypoint for MCP read-evidence validation."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate that governed MCP read capabilities have raw tool, fallback, SDK, "
            "core-only, and catalog replacement evidence before migration."
        ),
    )
    parser.parse_args()

    summary = validate_read_evidence_manifests(
        collect_manifests(),
        raw_tool_index=_load_raw_tool_source_index(),
        server_evidence_index=_load_server_evidence_index(),
        core_registry_test_blocks=_load_test_blocks_from_root(
            CORE_REGISTRY_TEST_ROOT, "test_*registry*.py"
        ),
        ai_capability_test_blocks=_load_test_blocks_from_root(AI_CAPABILITY_TEST_ROOT),
        sdk_test_blocks=_load_sdk_test_blocks(),
        unsupported_contract_keys=_unsupported_contract_keys(),
    )
    print("MCP read-evidence guard OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
