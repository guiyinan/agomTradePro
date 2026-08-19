"""Pure deterministic TAR-01 test-matrix tests."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix,
    canonical_terminal_runtime_test_matrix_digest,
    canonical_terminal_runtime_threat_ids,
)

_DORMANT_CONTRACT_PATHS = frozenset(
    {"tests/component/agent_runtime/test_terminal_agent_run_repository.py"}
)


def test_matrix_is_deterministic_and_covers_required_layers_and_threats() -> None:
    matrix = canonical_terminal_runtime_test_matrix()

    assert {scenario.layer for scenario in matrix} == {
        "domain",
        "application",
        "repository",
        "celery",
        "api",
        "events",
        "tui",
        "sdk",
        "local-cli-mcp",
        "load",
        "chaos",
    }
    assert canonical_terminal_runtime_threat_ids() == {
        "idor",
        "replay-idempotency",
        "stale-worker-aba",
        "sse-leak-replay",
        "secret-prompt-transport",
        "queue-flood",
        "request-size",
        "sse-resource-exhaustion",
        "fallback-bypass",
        "late-terminal-overwrite",
    }
    assert len({scenario.scenario_id for scenario in matrix}) == len(matrix)
    assert re.fullmatch(r"[0-9a-f]{64}", canonical_terminal_runtime_test_matrix_digest())
    assert canonical_terminal_runtime_test_matrix_digest() == (
        canonical_terminal_runtime_test_matrix_digest()
    )
    for scenario in matrix:
        exists = Path(scenario.required_test_path).exists()
        expected_exists = scenario.implementation_status == "implemented" or (
            scenario.required_test_path in _DORMANT_CONTRACT_PATHS
        )
        assert exists is expected_exists
        if scenario.required_test_path in _DORMANT_CONTRACT_PATHS:
            assert scenario.implementation_status == "planned"


def test_matrix_module_is_stdlib_only_and_has_no_runtime_side_effects() -> None:
    source = Path("apps/agent_runtime/application/terminal_runtime_test_matrix.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert all(not name.startswith("django") for name in imported)
    assert all("infrastructure" not in name for name in imported)
    assert "requests" not in imported
    assert ".objects" not in source
