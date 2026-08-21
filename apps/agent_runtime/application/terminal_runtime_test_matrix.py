"""Canonical TAR-01 threat and verification matrix.

The matrix is deliberately pure and deterministic.  Capacity candidates bind
its SHA-256 digest so evidence collected against an older or substituted test
matrix cannot satisfy the current gate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final


class TerminalRuntimeTestMatrixError(ValueError):
    """Raised when the canonical runtime test matrix is malformed."""


def _require_token(value: object, field_name: str) -> str:
    """Require a stable non-empty token without surrounding whitespace."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise TerminalRuntimeTestMatrixError(f"{field_name} must be a stable token")
    return value


@dataclass(frozen=True, slots=True)
class TerminalRuntimeTestScenario:
    """One required scenario in the deterministic TAR-01 matrix."""

    scenario_id: str
    layer: str
    required_test_path: str
    threat_ids: tuple[str, ...]
    implementation_status: str

    def __post_init__(self) -> None:
        """Validate the scenario without importing test or runtime modules."""

        _require_token(self.scenario_id, "scenario_id")
        _require_token(self.layer, "layer")
        _require_token(self.required_test_path, "required_test_path")
        if not self.required_test_path.startswith(("tests/", "sdk/tests/")):
            raise TerminalRuntimeTestMatrixError("required_test_path must be repository-relative")
        if not self.threat_ids or len(set(self.threat_ids)) != len(self.threat_ids):
            raise TerminalRuntimeTestMatrixError("threat_ids must be non-empty and unique")
        for threat_id in self.threat_ids:
            _require_token(threat_id, "threat_id")
        if self.implementation_status not in {"implemented", "planned"}:
            raise TerminalRuntimeTestMatrixError(
                "implementation_status must be implemented or planned"
            )


_SCENARIOS: Final[tuple[TerminalRuntimeTestScenario, ...]] = (
    TerminalRuntimeTestScenario(
        "domain-state-machine",
        "domain",
        "tests/unit/agent_runtime/test_terminal_agent_run_contract.py",
        ("stale-worker-aba", "late-terminal-overwrite"),
        "implemented",
    ),
    TerminalRuntimeTestScenario(
        "application-owner-idempotency-quota",
        "application",
        "tests/unit/agent_runtime/test_terminal_agent_run_boundary.py",
        ("idor", "replay-idempotency", "queue-flood"),
        "implemented",
    ),
    TerminalRuntimeTestScenario(
        "repository-postgres-first-winner",
        "repository",
        "tests/component/agent_runtime/test_terminal_agent_run_repository.py",
        ("replay-idempotency", "stale-worker-aba"),
        "implemented",
    ),
    TerminalRuntimeTestScenario(
        "celery-delivery-outcomes",
        "celery",
        "tests/unit/agent_runtime/test_terminal_agent_run_tasks.py",
        ("replay-idempotency", "fallback-bypass"),
        "implemented",
    ),
    TerminalRuntimeTestScenario(
        "api-wire-and-request-bounds",
        "api",
        "tests/component/test_terminal_api.py",
        ("idor", "request-size", "fallback-bypass"),
        "implemented",
    ),
    TerminalRuntimeTestScenario(
        "events-reconnect-and-owner-scope",
        "events",
        "tests/component/agent_runtime/test_terminal_agent_run_events.py",
        ("sse-leak-replay", "sse-resource-exhaustion", "idor"),
        "planned",
    ),
    TerminalRuntimeTestScenario(
        "tui-run-lifecycle",
        "tui",
        "tests/unit/test_tui_workbench.py",
        ("fallback-bypass",),
        "implemented",
    ),
    TerminalRuntimeTestScenario(
        "sdk-reconnect-and-versioning",
        "sdk",
        "sdk/tests/test_sdk/test_client.py",
        ("sse-leak-replay", "fallback-bypass"),
        "implemented",
    ),
    TerminalRuntimeTestScenario(
        "local-cli-mcp-secret-boundary",
        "local-cli-mcp",
        "tests/unit/agent_runtime/test_terminal_agent_local_cli.py",
        ("secret-prompt-transport", "fallback-bypass"),
        "implemented",
    ),
    TerminalRuntimeTestScenario(
        "load-1-5-10-20",
        "load",
        "tests/load/agent_runtime/test_terminal_agent_capacity.py",
        ("queue-flood", "request-size", "sse-resource-exhaustion"),
        "planned",
    ),
    TerminalRuntimeTestScenario(
        "chaos-worker-stream-recovery",
        "chaos",
        "tests/chaos/agent_runtime/test_terminal_agent_recovery.py",
        ("stale-worker-aba", "sse-leak-replay"),
        "planned",
    ),
)


def canonical_terminal_runtime_test_matrix() -> tuple[TerminalRuntimeTestScenario, ...]:
    """Return the immutable ordered TAR-01 test matrix."""

    return _SCENARIOS


def canonical_terminal_runtime_threat_ids() -> frozenset[str]:
    """Return every threat that at least one matrix scenario must cover."""

    return frozenset(threat_id for scenario in _SCENARIOS for threat_id in scenario.threat_ids)


def canonical_terminal_runtime_test_matrix_digest() -> str:
    """Return the canonical SHA-256 digest for the ordered matrix."""

    payload = [
        {
            "implementation_status": scenario.implementation_status,
            "layer": scenario.layer,
            "required_test_path": scenario.required_test_path,
            "scenario_id": scenario.scenario_id,
            "threat_ids": list(scenario.threat_ids),
        }
        for scenario in _SCENARIOS
    ]
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
