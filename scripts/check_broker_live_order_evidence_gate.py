#!/usr/bin/env python
"""Verify every live-order advancement remains behind the formal Evidence gate."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_MARKERS = {
    "apps/broker_execution/application/evidence_gate.py": (
        "def broker_order_evidence_integrated() -> bool:",
        "return False",
        'settings.SETTINGS_MODULE != "core.settings.critical_postgres_test"',
        'name.startswith("test_ash09_rehearsal_")',
        'name == db["TEST"]["NAME"]',
        "broker_order_evidence_receipt_not_integrated",
    ),
    "apps/broker_execution/application/use_cases.py": (
        "if not broker_order_evidence_integrated():",
        'require_broker_order_evidence(checkpoint="create")',
        'require_broker_order_evidence(checkpoint="approve")',
        '"commit_allowed": False',
    ),
    "apps/broker_execution/application/agent_use_cases.py": (
        "if not broker_order_evidence_integrated():",
        "return blocked_lease_result()",
        'require_broker_order_evidence(checkpoint="submitting")',
    ),
    "apps/broker_execution/infrastructure/repositories.py": (
        "checked = verify_order_checkpoint(",
        "authority_pin=checked.pin()",
        "checked.require_order(",
        "if not broker_order_evidence_integrated():",
        'require_broker_order_evidence(checkpoint="create")',
    ),
    "apps/broker_execution/infrastructure/broker_repository_order_control.py": (
        "checked = verify_existing_order(",
        'if action == "approve" and not broker_order_evidence_integrated():',
        'require_broker_order_evidence(checkpoint="approve")',
    ),
    "apps/broker_execution/infrastructure/broker_repository_agent_runtime.py": (
        "checked = verify_existing_order(",
        "if not broker_order_evidence_integrated():",
        "return blocked_lease_result()",
        'require_broker_order_evidence(checkpoint="submitting")',
    ),
    "apps/broker_execution/order_checkpoint_composition.py": (
        "broker_checkpoint_authority_changed",
        "broker_checkpoint_order_content_mismatch",
        "_lock_intent_ledgers(using)",
    ),
    "core/integration/broker_signed_order_checkpoint.py": (
        "read_current_order_execution_scope(",
        "read_current_signed_order_risk(",
        "read_locked_transition_order(",
        "sealed.execution_scope_hash",
        "require_signed_account_risk(",
    ),
    "sdk/agomtradepro_mcp/registry/modules/owners/broker_execution_write_capabilities.py": (
        'key="broker_execution.approve.order"',
        "enabled=False",
    ),
}


def validate_gate() -> dict[str, int]:
    """Raise when a mandatory checkpoint marker disappears or the gate opens."""

    for relative_path, markers in REQUIRED_MARKERS.items():
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in content]
        if missing:
            raise ValueError(f"{relative_path} is missing Evidence gate markers: {missing}")
    tui_content = (
        ROOT
        / "apps/terminal/infrastructure/tui_metadata_runtime_injection_broker_execution_actions.py"
    ).read_text(encoding="utf-8")
    if '"broker-execution.approve-order"' in tui_content:
        raise ValueError("TUI approve commit action must remain unpublished")
    if "commit_enabled=False" not in tui_content:
        raise ValueError("TUI advisor draft commit action must remain unpublished")
    for required_risk_reducing_action in (
        '"broker-execution.approval-preview"',
        '"broker-execution.reject-order"',
        '"broker-execution.request-cancel"',
        '"broker-execution.trigger-kill-switch"',
    ):
        if required_risk_reducing_action not in tui_content:
            raise ValueError(
                f"TUI risk-reducing action disappeared: {required_risk_reducing_action}"
            )
    return {"checkpoint_count": 4, "mcp_disabled_count": 1, "tui_commit_count": 0}


def main() -> int:
    """Run the gate check and print the frozen counts."""

    counts = validate_gate()
    print(
        "Broker live-order Evidence gate OK: "
        f"{counts['checkpoint_count']} checkpoints, "
        f"{counts['mcp_disabled_count']} MCP disabled, "
        f"{counts['tui_commit_count']} TUI commit actions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
