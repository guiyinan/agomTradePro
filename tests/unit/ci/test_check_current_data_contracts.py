"""Unit coverage for the current-data freshness contract guard."""

import ast
import json
from pathlib import Path

from scripts.check_current_data_contracts import (
    find_timestamp_laundering,
    validate_current_data_contracts,
)


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    """Write a temporary manifest for focused guard tests."""

    path.write_text(json.dumps(payload), encoding="utf-8")


def test_repository_current_data_contract_manifest_is_valid() -> None:
    """Every published current-data surface keeps executable freshness evidence."""

    assert validate_current_data_contracts() == []


def test_guard_rejects_missing_required_marker_and_test_function(tmp_path: Path) -> None:
    """A declared surface cannot retain only documentation-level evidence."""

    (tmp_path / "apps").mkdir()
    source = tmp_path / "source.py"
    source.write_text("def current():\n    return {}\n", encoding="utf-8")
    tests = tmp_path / "test_source.py"
    tests.write_text("def test_something_else():\n    pass\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "contracts": [
                {
                    "id": "sample.current",
                    "source_files": ["source.py"],
                    "required_markers": {
                        "source.py": ["must_not_use_for_decision"],
                    },
                    "required_tests": [
                        {
                            "test_file": "test_source.py",
                            "test_function": "test_stale_is_blocked",
                            "case": "stale_blocked",
                        }
                    ],
                }
            ],
        },
    )

    violations = validate_current_data_contracts(manifest, repo_root=tmp_path)

    assert {item.code for item in violations} == {
        "required_marker_missing",
        "test_function_missing",
    }


def test_ast_guard_detects_historical_timestamp_laundering() -> None:
    """Historical bars cannot be re-labelled with the request timestamp."""

    source = """
def build(bar):
    return RealtimePrice(
        asset_code=bar.asset_code,
        price=bar.close,
        timestamp=timezone.now(),
        source=bar.source,
    )
"""

    violations = find_timestamp_laundering(
        ast.parse(source),
        relative_path="apps/example/infrastructure/provider.py",
    )

    assert [(item.code, item.line) for item in violations] == [
        ("historical_timestamp_laundering", 3),
    ]


def test_ast_guard_allows_live_quote_observation_timestamp() -> None:
    """A newly fetched spot quote may use the fetch observation timestamp."""

    source = """
def build(latest_price):
    return RealtimePrice(
        asset_code="000001.SH",
        price=latest_price,
        timestamp=timezone.now(),
        source="akshare",
    )
"""

    assert (
        find_timestamp_laundering(
            ast.parse(source),
            relative_path="apps/example/infrastructure/provider.py",
        )
        == []
    )


def test_ast_guard_detects_quote_snapshot_request_time_laundering() -> None:
    source = """
def build(snapshot):
    return DataCenterQuoteSnapshot(
        asset_code=snapshot.stock_code,
        current_price=snapshot.price,
        snapshot_at=timezone.now(),
        source=snapshot.source,
    )
"""

    violations = find_timestamp_laundering(
        ast.parse(source),
        relative_path="apps/realtime/infrastructure/repositories.py",
    )

    assert [(item.code, item.line) for item in violations] == [
        ("quote_snapshot_timestamp_laundering", 3),
    ]


def test_ast_guard_rejects_filling_missing_source_observation_with_today() -> None:
    """SDK and API parsers cannot turn missing provenance into today's date."""

    source = """
def parse(observed_at):
    if observed_at is None:
        observed_at = date.today()
    return observed_at
"""

    violations = find_timestamp_laundering(
        ast.parse(source),
        relative_path="sdk/agomtradepro/modules/example.py",
    )

    assert [(item.code, item.line) for item in violations] == [
        ("missing_observation_timestamp_laundering", 4),
    ]
