"""Machine-check the TAR-01 ADR against the existing pure contracts."""

from __future__ import annotations

import json
from pathlib import Path

from apps.agent_runtime.application.terminal_agent_run_api_contract import (
    TerminalRunApiRoute,
)
from apps.agent_runtime.application.terminal_runtime_queue_policy import (
    LEGACY_INLINE_CONCURRENCY_CAP,
    LEGACY_INLINE_TIMEOUT_CAP_SECONDS,
    TERMINAL_AGENT_QUEUE_NAME,
    TERMINAL_AGENT_STREAM_NAMESPACE,
)
from apps.agent_runtime.application.terminal_runtime_slo import (
    terminal_runtime_slo_criteria,
)
from apps.agent_runtime.application.terminal_runtime_test_matrix import (
    canonical_terminal_runtime_test_matrix,
    canonical_terminal_runtime_test_matrix_digest,
    canonical_terminal_runtime_threat_ids,
)
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalRunStatus,
    TerminalRuntimeMode,
)

MANIFEST_PATH = Path("governance/terminal_agent_runtime_contracts.json")


def _manifest() -> dict[str, object]:
    """Load the repository-owned TAR-01 manifest."""

    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_reuses_the_pure_runtime_names_and_routes() -> None:
    """The machine ADR cannot silently drift from the existing contracts."""

    manifest = _manifest()
    status_contract = manifest["dispatch_status_contract"]
    assert isinstance(status_contract, dict)
    assert set(status_contract["values"]) == {status.value for status in TerminalRunStatus}

    compatibility = manifest["wire_compatibility"]
    assert isinstance(compatibility, dict)
    api = compatibility["api"]
    assert isinstance(api, dict)
    routes = api["routes"]
    assert isinstance(routes, dict)
    expected_routes = {
        "create": TerminalRunApiRoute.CREATE.value,
        "detail": TerminalRunApiRoute.DETAIL.value,
        "events": TerminalRunApiRoute.EVENTS.value,
        "cancel": TerminalRunApiRoute.CANCEL.value,
        "queue": TerminalRunApiRoute.QUEUE.value,
    }
    assert {name: route["path"] for name, route in routes.items()} == expected_routes

    queue_contract = manifest["worker_broker_queue_contract"]
    assert isinstance(queue_contract, dict)
    assert queue_contract["queue_name"] == TERMINAL_AGENT_QUEUE_NAME
    assert queue_contract["stream_namespace"] == TERMINAL_AGENT_STREAM_NAMESPACE
    assert queue_contract["broker_envelope"]["exact_fields"] == ["run_id", "task_id"]

    modes = manifest["responsibility_split"]["run_dispatch"]
    assert isinstance(modes, dict)
    assert set(manifest["wire_compatibility"]["api"]["routes"]) == {
        "create",
        "detail",
        "events",
        "cancel",
        "queue",
    }
    assert set(manifest["identity_and_idempotency"]["owner_selector"]["required_fields"]) == {
        "run_id",
        "task_id",
        "actor_user_id",
        "client_request_id",
    }
    assert set(manifest["implementation_boundary"]["implemented"]) >= {
        "durable PostgreSQL run admission with owner-scoped first-winner idempotency",
        "bounded queued intake with stable capacity rejection semantics",
        "dedicated Celery delivery and persisted terminal event/SSE negotiation",
        "server-side queued TUI CLI action with bounded status/event result projection",
        "browser workbench queued-run status and durable event replay UX with finite polling",
    }
    assert modes["canonical_type"].endswith("TerminalAgentRunContract")


def test_manifest_freezes_migration_flags_and_sensitive_transport_boundary() -> None:
    """The ADR keeps the current fail-closed defaults and ID-only transport."""

    manifest = _manifest()
    flags = manifest["feature_flags"]["fields"]
    assert flags == {
        "TERMINAL_QUEUED_INTAKE_ENABLED": False,
        "TERMINAL_QUEUED_WORKER_ENABLED": False,
        "TERMINAL_LEGACY_INLINE_ENABLED": True,
        "TERMINAL_EMERGENCY_STOP": False,
        "TERMINAL_PER_USER_QUEUED_LIMIT": 4,
        "TERMINAL_GLOBAL_QUEUED_LIMIT": 40,
        "TERMINAL_PER_USER_ACTIVE_LIMIT": 1,
        "TERMINAL_GLOBAL_ACTIVE_LIMIT": 4,
        "TERMINAL_LEGACY_INLINE_CONCURRENCY": LEGACY_INLINE_CONCURRENCY_CAP,
        "TERMINAL_LEGACY_INLINE_TIMEOUT_SECONDS": LEGACY_INLINE_TIMEOUT_CAP_SECONDS,
    }
    assert set(manifest["prompt_and_sensitive_data"]["broker_allowed_fields"]) == {
        "run_id",
        "task_id",
    }
    assert "prompt" in manifest["prompt_and_sensitive_data"]["forbidden_field_fragments"]
    assert manifest["prompt_and_sensitive_data"]["raw_prompt"]["run_dispatch_record"] == "forbidden"
    assert set(manifest["implementation_boundary"]["not_implemented"]) >= {
        "complete multi-user/global 1/5/10/20 capacity and hard-SLO evidence",
        "sustained chaos and 14-day telemetry",
    }
    assert manifest["implementation_boundary"]["remaining_work_assignment"] == {
        "complete multi-user/global 1/5/10/20 capacity and hard-SLO evidence": "TAR-05",
        "sustained chaos and 14-day telemetry": "TAR-05",
        "successful provider/MCP execution, restore/rollback, and role-based production UAT": (
            "TAR-05"
        ),
        "owner/reviewer sign-off": "TAR-05",
    }
    assert (
        "tests/component/agent_runtime/test_terminal_agent_run_events.py"
        in manifest["acceptance_and_next_gate"]["current_evidence"]
    )
    assert (
        "sdk/tests/test_sdk/test_server_agent_contract.py"
        in manifest["acceptance_and_next_gate"]["current_evidence"]
    )


def test_manifest_next_gate_is_candidate_bound_after_local_client_evidence() -> None:
    """Local queued UX evidence must not regress into a user-install gate."""

    acceptance = _manifest()["acceptance_and_next_gate"]
    next_gate = acceptance["next_gate"]
    assert "candidate-specific" in next_gate
    assert "Complete MCP/TUI queued client integration" not in next_gate
    assert "user-side Agent package" in next_gate
    assert (
        "frontend/tui-workbench/tests/workbench-browser.test.mjs" in acceptance["current_evidence"]
    )


def test_manifest_existing_error_codes_are_not_fabricated() -> None:
    """Codes marked existing must still be present in their cited source files."""

    manifest = _manifest()
    source_paths = (
        Path("core/exceptions.py"),
        Path("apps/agent_runtime/application/terminal_agent.py"),
        Path("apps/agent_runtime/application/terminal_agent_run_route_guard.py"),
        Path("apps/terminal/application/tui_workbench_result_models_specialized.py"),
        Path("apps/terminal/interface/api_views.py"),
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)
    existing_codes = manifest["error_codes"]["existing_codes"]
    assert all(item["code"] in source for item in existing_codes)

    reserved = manifest["error_codes"]["reserved_for_future_queued_runtime"]
    assert all(item["implementation_status"] == "not_runtime" for item in reserved)
    assert all(item["code"] not in {"AI_AGENT_BUSY", "AI_AGENT_TIMEOUT"} for item in reserved)


def test_manifest_mentions_all_runtime_modes_without_enabling_a_new_one() -> None:
    """The ADR must cover the existing mode enum and no invented mode."""

    manifest = _manifest()
    modes = manifest["responsibility_split"]["run_dispatch"]
    assert isinstance(modes, dict)
    mode_values = {
        TerminalRuntimeMode.WEB_QUEUED.value,
        TerminalRuntimeMode.LOCAL_CLI.value,
        TerminalRuntimeMode.LEGACY_INLINE.value,
        "server_side_only",
    }
    assert manifest["wire_compatibility"]["mcp"]["local_cli_mode"] in mode_values
    assert manifest["wire_compatibility"]["mcp"]["local_cli_mode"] == "server_side_only"
    assert manifest["wire_compatibility"]["mcp"]["local_cli_entrypoint"] is None
    assert manifest["wire_compatibility"]["mcp"]["local_cli_runtime_mode"] == "local_cli_disabled"
    assert (
        manifest["wire_compatibility"]["mcp"]["local_cli_execution"]
        == "thin_server_api_client_only"
    )
    assert (
        "server-owned prompt API submission with scoped token only"
        in manifest["wire_compatibility"]["mcp"]["local_cli_implemented"]
    )
    assert "legacy service" in manifest["wire_compatibility"]["legacy_http"]["policy"]
    assert modes["future_durable_type"] == "TerminalAgentRun"

    sdk_project = Path("sdk/pyproject.toml").read_text(encoding="utf-8")
    assert "agomtradepro-agent =" not in sdk_project
    assert "[agent]" not in sdk_project
    assert "openai-agents" not in sdk_project
    assert "OPENAI_API_KEY" not in sdk_project

    sdk_readme = Path("sdk/README.md").read_text(encoding="utf-8")
    assert "do **not** install this package" in sdk_readme
    assert "never install or run a provider-backed Agent locally" in sdk_readme


def test_manifest_freezes_complete_baseline_candidate_identity() -> None:
    """Capacity samples cannot be combined across images or snapshots."""

    manifest = _manifest()
    authority = manifest["authority"]
    assert isinstance(authority, dict)
    assert (
        "apps/agent_runtime/application/terminal_runtime_baseline.py"
        in authority["implementation_sources"]
    )
    assert (
        "apps/agent_runtime/application/terminal_runtime_baseline_collector.py"
        in authority["implementation_sources"]
    )
    acceptance = manifest["acceptance_and_next_gate"]
    assert isinstance(acceptance, dict)
    assert (
        "tests/unit/agent_runtime/test_terminal_runtime_baseline.py"
        in acceptance["current_evidence"]
    )
    assert (
        "tests/unit/agent_runtime/test_terminal_runtime_baseline_collector.py"
        in acceptance["current_evidence"]
    )
    baseline = manifest["baseline_evidence"]
    assert isinstance(baseline, dict)
    assert baseline["candidate_identity_type"] == "TerminalRuntimeBaselineCandidate"
    assert baseline["required_candidate_identity_fields"] == [
        "candidate_commit",
        "candidate_release",
        "oci_revision",
        "runtime_manifest_digest",
        "test_matrix_digest",
    ]
    assert baseline["required_concurrency_levels"] == [1, 5, 10, 20]
    assert baseline["samples_must_share_exact_candidate_identity"] is True
    assert baseline["capacity_ready_requires_complete_observed_metrics"] is True
    assert baseline["capacity_ready_requires_all_hard_slos"] is True
    assert baseline["canonical_test_matrix_digest"] == (
        canonical_terminal_runtime_test_matrix_digest()
    )
    assert baseline["production_evidence_status"] == "not_runtime"
    observation = manifest["runtime_observation"]
    assert observation["status"] == "short_window_observed"
    assert observation["capacity_ready"] is False
    assert observation["provider_execution"] == "failed_not_claimed"


def test_manifest_binds_hard_slos_threats_and_deterministic_matrix() -> None:
    """The machine ADR cannot claim protections absent from the pure contracts."""

    manifest = _manifest()
    slo_contract = manifest["slo_contract"]
    assert isinstance(slo_contract, dict)
    assert set(slo_contract["required_measurements"]) == {
        criterion.key for criterion in terminal_runtime_slo_criteria()
    }
    assert slo_contract["criteria"] == [
        {
            "key": criterion.key,
            "unit": criterion.unit,
            "comparator": criterion.comparator.value,
            "threshold": criterion.threshold,
        }
        for criterion in terminal_runtime_slo_criteria()
    ]
    assert slo_contract["unavailable_or_threshold_breach"] == "capacity_gate_blocked"

    threat_model = manifest["threat_model"]
    assert isinstance(threat_model, dict)
    assert set(threat_model["required_ids"]) == canonical_terminal_runtime_threat_ids()

    matrix = manifest["test_matrix"]
    assert isinstance(matrix, dict)
    assert set(matrix["required_layers"]) == {
        scenario.layer for scenario in canonical_terminal_runtime_test_matrix()
    }
    assert matrix["canonical_digest"] == canonical_terminal_runtime_test_matrix_digest()
    assert matrix["scenarios"] == [
        {
            "scenario_id": scenario.scenario_id,
            "layer": scenario.layer,
            "required_test_path": scenario.required_test_path,
            "threat_ids": list(scenario.threat_ids),
            "implementation_status": scenario.implementation_status,
        }
        for scenario in canonical_terminal_runtime_test_matrix()
    ]
