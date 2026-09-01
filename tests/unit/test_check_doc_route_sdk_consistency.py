"""Regression tests for documentation route reference filtering."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_doc_route_sdk_consistency.py"


def _load_module() -> ModuleType:
    """Load the standalone consistency checker without relying on package imports."""

    spec = importlib.util.spec_from_file_location("check_doc_route_sdk_consistency", _SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("consistency checker cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_filesystem_paths_are_not_treated_as_routes() -> None:
    """Filesystem examples are ignored while the existing /opt contract remains intact."""

    parser = _load_module().DocumentationParser(_ROOT / "docs")

    assert parser._should_ignore_route("/etc/prometheus") is True
    assert parser._should_ignore_route("/var/lib/prometheus") is True
    assert parser._should_ignore_route("/opt/prometheus") is True
    assert parser._should_ignore_route("/api/account/") is False


def test_document_extraction_keeps_api_routes_and_drops_filesystem_paths(
    tmp_path: Path,
) -> None:
    """Temporary docs prove route extraction separates paths from API references."""

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "examples.md").write_text(
        "Filesystem: `/etc/prometheus`, `/var/lib/prometheus`, `/opt/prometheus`.\n"
        "API: `/api/account/`.\n",
        encoding="utf-8",
    )

    references = _load_module().DocumentationParser(docs_dir).extract_route_references()
    document_key = str(Path("docs") / "examples.md")

    assert list(references) == [document_key]
    assert references[document_key]
    assert all(route == "/api/account/" and line == 2 for route, line in references[document_key])
