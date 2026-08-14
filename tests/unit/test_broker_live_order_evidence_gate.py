"""Machine freeze for the Broker live-order Evidence hard gate."""

from __future__ import annotations

from scripts.check_broker_live_order_evidence_gate import validate_gate


def test_broker_live_order_evidence_gate_is_exact() -> None:
    assert validate_gate() == {
        "checkpoint_count": 4,
        "mcp_disabled_count": 1,
        "tui_commit_count": 0,
    }
