#!/usr/bin/env python
"""Build the immutable source identity used by Web-to-TUI M5 evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TypedDict, cast

BINDING_VERSION = "web-to-tui-candidate-binding.v1"


class CandidateBinding(TypedDict):
    """Exact repository and runtime identity for one cutover candidate."""

    version: str
    candidate_version: str
    candidate_commit: str
    matrix_sha256: str
    graph_sha256: str
    schema_version: str
    runtime_version: str
    runtime_build_id: str
    runtime_manifest_sha256: str


def normalized_source_bytes(path: Path) -> bytes:
    """Return UTF-8 text bytes with Git-compatible LF line endings."""

    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def source_sha256(path: Path) -> str:
    """Return a platform-independent SHA-256 for one checked-in text source."""

    return hashlib.sha256(normalized_source_bytes(path)).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object used to derive runtime identity."""

    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def build_candidate_binding(
    *,
    stable_version: str,
    candidate_commit: str,
    matrix_path: Path,
    graph_path: Path,
    runtime_manifest_path: Path,
) -> CandidateBinding:
    """Build the exact source/runtime binding required by candidate evidence."""

    graph = _load_object(graph_path)
    runtime_manifest = _load_object(runtime_manifest_path)
    schema_version = str(graph.get("schema_version") or "").strip()
    runtime_version = str(runtime_manifest.get("version") or "").strip()
    runtime_build_id = str(runtime_manifest.get("build_id") or "").strip()
    if not schema_version:
        raise ValueError("Published TUI graph is missing schema_version")
    if not runtime_version or not runtime_build_id:
        raise ValueError("TUI runtime manifest is missing version/build_id")
    return {
        "version": BINDING_VERSION,
        "candidate_version": stable_version,
        "candidate_commit": candidate_commit,
        "matrix_sha256": source_sha256(matrix_path),
        "graph_sha256": source_sha256(graph_path),
        "schema_version": schema_version,
        "runtime_version": runtime_version,
        "runtime_build_id": runtime_build_id,
        "runtime_manifest_sha256": source_sha256(runtime_manifest_path),
    }


def binding_matches(value: object, expected: CandidateBinding) -> bool:
    """Return whether dynamic evidence carries exactly the expected binding."""

    return isinstance(value, dict) and value == expected
