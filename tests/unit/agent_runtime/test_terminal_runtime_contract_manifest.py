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
    assert set(
        manifest["identity_and_idempotency"]["owner_selector"]["required_fields"]
    ) == {"run_id", "task_id", "actor_user_id", "client_request_id"}
    assert set(manifest["implementation_boundary"]["not_implemented"]) >= {
        "durable PostgreSQL run or dispatch record",
        "Celery task, broker publisher, or dispatcher",
        "dedicated Agent Worker or event stream",
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
    assert (
        manifest["prompt_and_sensitive_data"]["raw_prompt"]["run_dispatch_record"]
        == "forbidden"
    )
    assert set(manifest["implementation_boundary"]["not_implemented"]) >= {
        "SDK/MCP/TUI queued client implementation",
        "capacity, chaos, staging, or production UAT evidence",
    }


def test_manifest_existing_error_codes_are_not_fabricated() -> None:
    """Codes marked existing must still be present in their cited source files."""

    manifest = _manifest()
    source_paths = (
        Path("core/exceptions.py"),
        Path("apps/agent_runtime/application/terminal_agent.py"),
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
    }
    assert manifest["wire_compatibility"]["mcp"]["local_cli_mode"] in mode_values
    assert "legacy service" in manifest["wire_compatibility"]["legacy_http"]["policy"]
    assert modes["future_durable_type"] == "TerminalAgentRun"
