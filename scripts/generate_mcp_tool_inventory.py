#!/usr/bin/env python
"""Generate a static inventory of MCP tool registrations."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPO_ROOT / "sdk" / "agomtradepro_mcp" / "server.py"
TOOLS_DIR = REPO_ROOT / "sdk" / "agomtradepro_mcp" / "tools"
REPORTS_DIR = REPO_ROOT / "reports" / "mcp"
UNSUPPORTED_LEGACY_CONTRACTS_PATH = (
    REPO_ROOT / "sdk" / "agomtradepro" / "unsupported_legacy_contracts.py"
)

REGISTER_DEF_RE = re.compile(
    r"^def\s+(?P<register_name>register_[a-z0-9_]+)\s*\(\s*server(?:\s*:[^)]+)?\)",
    re.MULTILINE,
)
REGISTER_CALL_RE = re.compile(
    r"^\s*(?P<register_name>register_[a-z0-9_]+)\s*\(\s*server\s*\)",
    re.MULTILINE,
)
LEGACY_TOOL_REGISTRARS_BLOCK_RE = re.compile(
    r"LEGACY_TOOL_REGISTRARS\s*=\s*\((?P<body>.*?)\)\s*",
    re.DOTALL,
)
LEGACY_TOOL_REGISTRAR_ENTRY_RE = re.compile(r"\b(register_[a-z0-9_]+)\b")
TOOL_DEF_RE = re.compile(
    r"^\s*@server\.tool\(\)\s*\n\s*def\s+(?P<tool_name>[a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
    re.MULTILINE,
)

READ_KEYWORDS = {
    "get",
    "list",
    "query",
    "search",
    "read",
    "fetch",
    "inspect",
    "show",
    "calculate",
    "rank",
    "screen",
    "summary",
    "status",
    "history",
    "detail",
    "distribution",
}
WRITE_KEYWORDS = {
    "create",
    "update",
    "delete",
    "remove",
    "set",
    "toggle",
    "enable",
    "disable",
    "submit",
    "approve",
    "reject",
    "invalidate",
    "close",
    "revoke",
    "sync",
    "refresh",
    "start",
    "stop",
    "run",
    "trigger",
    "import",
    "upload",
    "publish",
    "repair",
    "reset",
    "migrate",
}
ADMIN_KEYWORDS = {
    "admin",
    "token",
    "secret",
    "permission",
    "role",
    "governance",
    "config",
    "runtime",
}


@dataclass(frozen=True)
class ToolRecord:
    """Static metadata for one MCP tool registration."""

    tool_name: str
    module: str
    tool_file: str
    register_name: str
    registered_in_server: bool
    operation_type: str
    risk_hint: str
    disposition_hint: str
    unsupported_contract_key: str | None = None


def _load_unsupported_legacy_contracts_module():
    spec = importlib.util.spec_from_file_location(
        "agomtradepro_unsupported_legacy_contracts",
        UNSUPPORTED_LEGACY_CONTRACTS_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load unsupported legacy contracts module.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _registered_functions(server_text: str) -> set[str]:
    registered = {match.group("register_name") for match in REGISTER_CALL_RE.finditer(server_text)}
    registrars_block = LEGACY_TOOL_REGISTRARS_BLOCK_RE.search(server_text)
    if registrars_block is not None:
        registered.update(
            LEGACY_TOOL_REGISTRAR_ENTRY_RE.findall(registrars_block.group("body"))
        )
    return registered


def _infer_operation_type(tool_name: str) -> str:
    tokens = set(tool_name.lower().split("_"))
    if tokens & WRITE_KEYWORDS:
        return "write"
    if tokens & READ_KEYWORDS:
        return "read"
    return "unknown"


def _infer_risk_hint(tool_name: str, operation_type: str) -> str:
    tokens = set(tool_name.lower().split("_"))
    if tokens & ADMIN_KEYWORDS:
        return "admin"
    if operation_type == "write":
        return "write_high"
    if operation_type == "read":
        return "read"
    return "review_required"


def _infer_disposition_hint(
    tool_name: str,
    operation_type: str,
    risk_hint: str,
    *,
    unsupported_contract_key: str | None = None,
) -> str:
    if unsupported_contract_key is not None:
        return "unsupported_legacy_contract"
    tokens = set(tool_name.lower().split("_"))
    if {"dashboard", "page", "widget", "panel"} & tokens:
        return "internal_only"
    if risk_hint == "admin":
        return "legacy_compat_or_governed"
    if operation_type == "read":
        return "candidate_keep_task"
    if operation_type == "write":
        return "candidate_aggregate_or_governed"
    return "review_required"


def _parse_tool_file(
    path: Path,
    registered_calls: set[str],
    *,
    unsupported_tool_to_contract: dict[str, str],
) -> Iterable[ToolRecord]:
    text = _load_text(path)
    register_match = REGISTER_DEF_RE.search(text)
    if register_match is None:
        return ()

    register_name = register_match.group("register_name")
    module = path.stem.removesuffix("_tools")
    records: list[ToolRecord] = []

    for tool_match in TOOL_DEF_RE.finditer(text):
        tool_name = tool_match.group("tool_name")
        operation_type = _infer_operation_type(tool_name)
        risk_hint = _infer_risk_hint(tool_name, operation_type)
        unsupported_contract_key = unsupported_tool_to_contract.get(tool_name)
        records.append(
            ToolRecord(
                tool_name=tool_name,
                module=module,
                tool_file=str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                register_name=register_name,
                registered_in_server=register_name in registered_calls,
                operation_type=operation_type,
                risk_hint=risk_hint,
                disposition_hint=_infer_disposition_hint(
                    tool_name,
                    operation_type,
                    risk_hint,
                    unsupported_contract_key=unsupported_contract_key,
                ),
                unsupported_contract_key=unsupported_contract_key,
            )
        )

    return records


def build_inventory() -> dict[str, object]:
    """Build a static tool inventory from the MCP source tree."""

    server_text = _load_text(SERVER_PATH)
    registered_calls = _registered_functions(server_text)
    unsupported_module = _load_unsupported_legacy_contracts_module()
    unsupported_contracts = unsupported_module.list_unsupported_legacy_contracts()
    unsupported_tool_to_contract = {
        tool_name: contract.contract_key
        for contract in unsupported_contracts
        for tool_name in contract.legacy_tool_names
    }

    records: list[ToolRecord] = []
    missing_register_files: list[str] = []
    for path in sorted(TOOLS_DIR.glob("*_tools.py")):
        parsed = list(
            _parse_tool_file(
                path,
                registered_calls,
                unsupported_tool_to_contract=unsupported_tool_to_contract,
            )
        )
        if not parsed:
            missing_register_files.append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
            continue
        records.extend(parsed)

    by_module: dict[str, int] = {}
    by_operation: dict[str, int] = {}
    by_risk_hint: dict[str, int] = {}
    by_disposition_hint: dict[str, int] = {}
    unregistered_tools: list[str] = []

    for record in records:
        by_module[record.module] = by_module.get(record.module, 0) + 1
        by_operation[record.operation_type] = by_operation.get(record.operation_type, 0) + 1
        by_risk_hint[record.risk_hint] = by_risk_hint.get(record.risk_hint, 0) + 1
        by_disposition_hint[record.disposition_hint] = (
            by_disposition_hint.get(record.disposition_hint, 0) + 1
        )
        if not record.registered_in_server:
            unregistered_tools.append(record.tool_name)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "server_path": str(SERVER_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
        "tools_dir": str(TOOLS_DIR.relative_to(REPO_ROOT)).replace("\\", "/"),
        "summary": {
            "total_tools": len(records),
            "registered_modules": len(registered_calls),
            "tool_files_scanned": len(list(TOOLS_DIR.glob("*_tools.py"))),
            "tool_files_without_register_function": len(missing_register_files),
            "unregistered_tool_count": len(unregistered_tools),
            "unsupported_legacy_contract_count": len(unsupported_contracts),
            "by_module": dict(sorted(by_module.items())),
            "by_operation": dict(sorted(by_operation.items())),
            "by_risk_hint": dict(sorted(by_risk_hint.items())),
            "by_disposition_hint": dict(sorted(by_disposition_hint.items())),
        },
        "missing_register_files": missing_register_files,
        "unregistered_tools": sorted(unregistered_tools),
        "unsupported_legacy_contracts": [
            contract.to_dict() for contract in unsupported_contracts
        ],
        "tools": [asdict(record) for record in records],
    }


def _default_report_paths(timestamp: str) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return (
        REPORTS_DIR / f"mcp-tool-inventory-{timestamp}.json",
        REPORTS_DIR / f"mcp-tool-classification-{timestamp}.md",
    )


def _render_markdown(payload: dict[str, object]) -> str:
    summary = payload["summary"]
    lines = [
        "# MCP Tool Inventory",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Total tools: `{summary['total_tools']}`",
        f"- Registered modules: `{summary['registered_modules']}`",
        f"- Tool files scanned: `{summary['tool_files_scanned']}`",
        f"- Tool files without register function: `{summary['tool_files_without_register_function']}`",
        f"- Unregistered tools: `{summary['unregistered_tool_count']}`",
        f"- Unsupported legacy contracts: `{summary['unsupported_legacy_contract_count']}`",
        "",
        "## By Operation",
        "",
    ]

    for key, value in summary["by_operation"].items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(
        [
            "",
            "## Unsupported Legacy Contracts",
            "",
        ]
    )

    for contract in payload["unsupported_legacy_contracts"]:
        lines.append(
            f"- `{contract['contract_key']}`: {contract['title']} "
            f"({', '.join(contract['legacy_tool_names'])})"
        )

    lines.extend(
        [
            "",
            "## By Risk Hint",
            "",
        ]
    )
    for key, value in summary["by_risk_hint"].items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(
        [
            "",
            "## By Disposition Hint",
            "",
        ]
    )
    for key, value in summary["by_disposition_hint"].items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(
        [
            "",
            "## Top-Level Modules",
            "",
        ]
    )
    for key, value in summary["by_module"].items():
        lines.append(f"- `{key}`: {value}")

    unregistered_tools = payload["unregistered_tools"]
    if unregistered_tools:
        lines.extend(
            [
                "",
                "## Unregistered Tools",
                "",
            ]
        )
        for tool_name in unregistered_tools:
            lines.append(f"- `{tool_name}`")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a static MCP tool inventory.")
    parser.add_argument("--output-json", type=Path, default=None, help="Path to write the JSON report.")
    parser.add_argument("--output-md", type=Path, default=None, help="Path to write the Markdown report.")
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    default_json_path, default_md_path = _default_report_paths(timestamp)
    output_json = args.output_json or default_json_path
    output_md = args.output_md or default_md_path

    payload = build_inventory()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output_md.write_text(_render_markdown(payload), encoding="utf-8")
    print(f"Wrote {output_json}")
    print(f"Wrote {output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
