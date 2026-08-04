"""Static guard for retired equity-side remote metadata bypasses."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_stock_info_repository_has_no_legacy_eastmoney_http_bypass() -> None:
    """Stock metadata must remain on the canonical Data Center ports."""

    source_path = REPO_ROOT / "apps/equity/infrastructure/stock_info_repository.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))

    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "requests" not in imported_modules
    assert "requests" not in imported_from
    assert "_get_stock_info_from_eastmoney" not in source
    assert "EASTMONEY_" not in source

    stock_repository_source = (
        REPO_ROOT / "apps/equity/infrastructure/stock_repository.py"
    ).read_text(encoding="utf-8")
    assert "_to_eastmoney_secid" not in stock_repository_source
    assert "EASTMONEY_" not in stock_repository_source
