"""Tests for the authenticated TAR-01 reserved-route evidence guard."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_runtime_reserved_route_evidence import (
    TerminalRuntimeReservedRouteEvidenceError,
    validate_terminal_runtime_reserved_route_evidence,
)
from scripts.validate_terminal_runtime_reserved_route_evidence import main as validate_main

EVIDENCE_PATH = Path(
    "docs/deployment/tar01-current-production-acceptance-2026-08-21-head-78966107d.json"
)


def _payload() -> dict[str, object]:
    """Load a fresh copy of the committed production observation."""

    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_committed_production_observation_is_valid() -> None:
    """The current candidate-bound artifact validates and stays capacity-denied."""

    report = validate_terminal_runtime_reserved_route_evidence(_payload())
    assert report.candidate_commit == "78966107d197003bb591662a3f6967a8fba83589"
    assert report.candidate_release == "20260821012122"
    assert report.level_count == 4
    assert report.health_stable is True
    assert report.side_effects_observed is False
    assert report.capacity_ready is False


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("levels", 0, "status_counts", "503"), 200),
        (("levels", 1, "reason_counts", "queued_runtime_not_wired"), 4),
        (("acceptance", "capacity_ready"), True),
        (("candidate", "runtime_match"), False),
    ],
)
def test_substituted_acceptance_facts_fail_closed(path: tuple[object, ...], value: object) -> None:
    """A response, candidate, or gate substitution cannot be self-reported."""

    payload = _payload()
    cursor: object = payload
    for key in path[:-1]:
        cursor = cursor[key]  # type: ignore[index]
    cursor[path[-1]] = value  # type: ignore[index]
    with pytest.raises(TerminalRuntimeReservedRouteEvidenceError):
        validate_terminal_runtime_reserved_route_evidence(payload)


def test_before_after_audit_drift_fails_closed() -> None:
    """A changed operation counter cannot be hidden behind side_effects_observed."""

    payload = _payload()
    payload["audit_after"] = copy.deepcopy(payload["audit_after"])
    payload["audit_after"]["total_operation_logs"] = 542  # type: ignore[index]
    with pytest.raises(TerminalRuntimeReservedRouteEvidenceError):
        validate_terminal_runtime_reserved_route_evidence(payload)


def test_script_is_read_only_and_reports_stable_summary(monkeypatch, capsys) -> None:
    """The CLI validates a file and never enables the queued runtime."""

    monkeypatch.setattr(
        "sys.argv",
        ["validate_terminal_runtime_reserved_route_evidence.py", str(EVIDENCE_PATH)],
    )
    assert validate_main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["runtime_enablement"] == "not_authorized"
    assert output["capacity_ready"] is False


def test_guard_has_no_network_or_runtime_imports() -> None:
    """The evidence guard is an offline application contract."""

    source = Path(
        "apps/agent_runtime/application/terminal_runtime_reserved_route_evidence.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(
        forbidden in name
        for name in imported
        for forbidden in ("django", "requests", "celery", "socket", "subprocess")
    )
    assert ".objects" not in source
