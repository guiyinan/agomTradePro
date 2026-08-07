"""Tests for the MCP write-evidence validation script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from agomtradepro_mcp.registry.manifest import CapabilityManifest


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "check_mcp_write_evidence.py"
    spec = importlib.util.spec_from_file_location("check_mcp_write_evidence", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest(
    capability_key: str,
    *,
    executor_kind: str = "legacy_tool",
    executor_ref: str = "approve_workbench_event",
    legacy_tool_names: tuple[str, ...] = ("approve_workbench_event",),
):
    return CapabilityManifest(
        capability_key=capability_key,
        title="Test",
        summary="Test",
        description="Test",
        owner_app="policy",
        risk_level="high",
        executor_kind=executor_kind,
        executor_ref=executor_ref,
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
        requires_confirmation=True,
        idempotency="required",
        audit_tags=("policy:write", "mcp:write"),
        legacy_tool_names=legacy_tool_names,
    )


@pytest.mark.parametrize(
    "capability_key",
    [
        "agent_task.resume.task",
        "dashboard.refresh.alpha",
        "equity.create.valuation_quality_snapshot",
        "events.replay.events",
        "risk_center.stress_scenario.propose_revision",
    ],
)
def test_is_write_like_manifest_covers_governed_workflow_actions(capability_key):
    module = _load_module()

    assert module.is_write_like_manifest(_manifest(capability_key)) is True


def test_validate_write_evidence_accepts_legacy_tool_write():
    module = _load_module()
    manifest = _manifest("policy.approve.workbench_event")
    multiline_match = module.LEGACY_FALLBACK_REF_RE.search(
        '"tool_name": (\n    _fallback_tool_name\n),'
    )
    assert multiline_match is not None
    assert multiline_match.group("tool") == "tool_name"
    assert multiline_match.group("func") == "_fallback_tool_name"

    summary = module.validate_write_evidence_manifests(
        [manifest],
        raw_tool_index={"approve_workbench_event": "sdk/agomtradepro_mcp/tools/policy_tools.py"},
        server_evidence_index={
            "function_bodies": {
                "_fallback_approve_workbench_event": "AgomTradeProClient\nclient.policy.approve_event"
            },
            "legacy_fallbacks": {"approve_workbench_event": "_fallback_approve_workbench_event"},
            "internal_handlers": {},
        },
        core_registry_text="policy.approve.workbench_event",
        ai_capability_text="policy.approve.workbench_event approve_workbench_event",
        unsupported_contract_keys=set(),
    )

    assert summary["write_like_manifests"] == 1
    assert summary["legacy_executor_manifests"] == 1
    assert summary["internal_handler_manifests"] == 0
    assert summary["raw_tool_evidence_manifests"] == 1
    assert summary["execution_evidence_manifests"] == 1
    assert summary["contract_test_evidence_manifests"] == 1


def test_validate_write_evidence_accepts_internal_handler_write():
    module = _load_module()
    manifest = _manifest(
        "agent_proposal.create.proposal",
        executor_kind="internal_handler",
        executor_ref="agent_proposal_create_proposal",
        legacy_tool_names=("create_agent_proposal",),
    )
    multiline_match = module.INTERNAL_HANDLER_REF_RE.search(
        '"agent_proposal_create_proposal": (\n'
        "    _internal_handler_agent_proposal_create_proposal\n"
        "),"
    )
    assert multiline_match is not None
    assert multiline_match.group("handler") == "agent_proposal_create_proposal"
    assert multiline_match.group("func") == "_internal_handler_agent_proposal_create_proposal"

    summary = module.validate_write_evidence_manifests(
        [manifest],
        raw_tool_index={
            "create_agent_proposal": "sdk/agomtradepro_mcp/tools/agent_proposal_tools.py"
        },
        server_evidence_index={
            "function_bodies": {
                "_internal_handler_agent_proposal_create_proposal": "preview_only = False"
            },
            "legacy_fallbacks": {},
            "internal_handlers": {
                "agent_proposal_create_proposal": "_internal_handler_agent_proposal_create_proposal"
            },
        },
        core_registry_text="agent_proposal.create.proposal",
        ai_capability_text="agent_proposal.create.proposal create_agent_proposal",
        unsupported_contract_keys=set(),
    )

    assert summary["write_like_manifests"] == 1
    assert summary["legacy_executor_manifests"] == 0
    assert summary["internal_handler_manifests"] == 1


def test_validate_write_evidence_accepts_exhaustive_catalog_projection_matrix():
    """A registry-wide alias matrix is evidence without per-manifest string duplication."""

    module = _load_module()
    manifest = _manifest(
        "account.import.positions",
        executor_ref="import_positions_json",
        legacy_tool_names=("import_positions_json",),
    )
    matrix_test_text = """
GOVERNED_MANIFESTS = load_manifests()
def test_governed_manifest_legacy_projection_matrix_preserves_every_alias():
    build_legacy_replacement_map(GOVERNED_MANIFESTS)
    for manifest in GOVERNED_MANIFESTS:
        for legacy_tool_name in manifest.legacy_tool_names:
            legacy.execution_target["replacement_capability_key"] == manifest.capability_key
"""

    summary = module.validate_write_evidence_manifests(
        [manifest],
        raw_tool_index={"import_positions_json": "sdk/agomtradepro_mcp/tools/account_tools.py"},
        server_evidence_index={
            "function_bodies": {
                "_fallback_import_positions_json": "AgomTradeProClient\nclient.account.import_positions"
            },
            "legacy_fallbacks": {"import_positions_json": "_fallback_import_positions_json"},
            "internal_handlers": {},
        },
        core_registry_text="account.import.positions",
        ai_capability_text=matrix_test_text,
        unsupported_contract_keys=set(),
    )

    assert summary["contract_test_evidence_manifests"] == 1


def test_server_evidence_loads_handlers_split_from_server_module():
    module = _load_module()

    evidence = module._load_server_evidence_index()

    handler_name = evidence["internal_handlers"]["audit_update_threshold_levels"]
    assert handler_name == "_internal_handler_audit_update_threshold_levels"
    assert "preview_only" in evidence["function_bodies"][handler_name]


def test_generate_action_is_classified_as_write_like():
    module = _load_module()

    assert module.is_write_like_manifest(_manifest("risk_center.generate.daily_report")) is True


def test_validate_write_evidence_rejects_missing_raw_tool_evidence():
    module = _load_module()
    manifest = _manifest("policy.approve.workbench_event")

    with pytest.raises(ValueError, match="missing raw tool evidence"):
        module.validate_write_evidence_manifests(
            [manifest],
            raw_tool_index={},
            server_evidence_index={
                "function_bodies": {
                    "_fallback_approve_workbench_event": "AgomTradeProClient\nclient.policy.approve_event"
                },
                "legacy_fallbacks": {
                    "approve_workbench_event": "_fallback_approve_workbench_event"
                },
                "internal_handlers": {},
            },
            core_registry_text="policy.approve.workbench_event",
            ai_capability_text="policy.approve.workbench_event approve_workbench_event",
            unsupported_contract_keys=set(),
        )


def test_validate_write_evidence_rejects_missing_execution_evidence():
    module = _load_module()
    manifest = _manifest("policy.approve.workbench_event")

    with pytest.raises(ValueError, match="missing server fallback evidence"):
        module.validate_write_evidence_manifests(
            [manifest],
            raw_tool_index={
                "approve_workbench_event": "sdk/agomtradepro_mcp/tools/policy_tools.py"
            },
            server_evidence_index={
                "function_bodies": {},
                "legacy_fallbacks": {},
                "internal_handlers": {},
            },
            core_registry_text="policy.approve.workbench_event",
            ai_capability_text="policy.approve.workbench_event approve_workbench_event",
            unsupported_contract_keys=set(),
        )


def test_validate_write_evidence_rejects_missing_contract_test_evidence():
    module = _load_module()
    manifest = _manifest("policy.approve.workbench_event")

    with pytest.raises(ValueError, match="missing core registry regression evidence"):
        module.validate_write_evidence_manifests(
            [manifest],
            raw_tool_index={
                "approve_workbench_event": "sdk/agomtradepro_mcp/tools/policy_tools.py"
            },
            server_evidence_index={
                "function_bodies": {
                    "_fallback_approve_workbench_event": "AgomTradeProClient\nclient.policy.approve_event"
                },
                "legacy_fallbacks": {
                    "approve_workbench_event": "_fallback_approve_workbench_event"
                },
                "internal_handlers": {},
            },
            core_registry_text="",
            ai_capability_text="policy.approve.workbench_event approve_workbench_event",
            unsupported_contract_keys=set(),
        )


def test_validate_write_evidence_rejects_unsupported_legacy_overlap():
    module = _load_module()
    manifest = _manifest("realtime.delete.price_alert", legacy_tool_names=("delete_price_alert",))

    with pytest.raises(ValueError, match="Unsupported legacy contract must not be registered"):
        module.validate_write_evidence_manifests(
            [manifest],
            raw_tool_index={"delete_price_alert": "sdk/agomtradepro_mcp/tools/realtime_tools.py"},
            server_evidence_index={
                "function_bodies": {
                    "_fallback_delete_price_alert": "AgomTradeProClient\nclient.realtime.delete_alert"
                },
                "legacy_fallbacks": {"delete_price_alert": "_fallback_delete_price_alert"},
                "internal_handlers": {},
            },
            core_registry_text="realtime.delete.price_alert",
            ai_capability_text="realtime.delete.price_alert delete_price_alert",
            unsupported_contract_keys={"realtime.delete.price_alert"},
        )
