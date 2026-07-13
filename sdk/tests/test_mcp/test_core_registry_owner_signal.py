# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_signal."""

from .core_registry_support import *


@pytest.mark.parametrize(
    ("capability_key", "legacy_tool_name", "arguments", "payload", "expected"),
    [
        (
            "signal.read.list",
            "list_signals",
            {"status": "approved", "asset_code": "510300.SH", "limit": 10},
            {
                "signals": [
                    {
                        "id": 7,
                        "asset_code": "510300.SH",
                        "status": "approved",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "510300.SH",
        ),
        (
            "signal.read.detail",
            "get_signal",
            {"signal_id": 7},
            {
                "id": 7,
                "asset_code": "510300.SH",
                "logic_desc": "PMI recovery",
                "status": "approved",
                "invalidation_logic": "PMI falls below 50",
                "source": "core-only-fallback",
            },
            "PMI falls below 50",
        ),
        (
            "signal.check.eligibility",
            "check_signal_eligibility",
            {
                "asset_code": "510300.SH",
                "logic_desc": "PMI recovery supports equities",
            },
            {
                "is_eligible": True,
                "regime_match": True,
                "policy_match": True,
                "current_regime": "Recovery",
                "source": "core-only-fallback",
            },
            "Recovery",
        ),
    ],
)
def test_agom_capability_call_reads_signal_family_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    capability_key,
    legacy_tool_name,
    arguments,
    payload,
    expected,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        legacy_tool_name,
        lambda **kwargs: payload,
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": capability_key,
                "arguments": arguments,
            },
        )
    )

    rendered = str(result)
    assert capability_key in rendered
    assert expected in rendered
    assert "core-only-fallback" in rendered


def test_signal_create_capability_runs_eligibility_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeEligibility:
        is_eligible = True
        regime_match = True
        policy_match = True
        current_regime = "Recovery"
        policy_status = "stimulus"
        rejection_reason = None

    class _FakeSignalModule:
        @staticmethod
        def check_eligibility(**kwargs):
            return _FakeEligibility()

    class _FakeClient:
        signal = _FakeSignalModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_create_signal(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": 88,
            "asset_code": kwargs["asset_code"],
            "logic_desc": kwargs["logic_desc"],
            "status": "pending",
            "created_at": "2026-07-09T12:00:00+00:00",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "create_signal",
        fake_create_signal,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="signal.create.signal",
        arguments={
            "asset_code": "000001.SH",
            "logic_desc": "PMI recovering with policy support",
            "invalidation_logic": "PMI falls below 50",
            "invalidation_threshold": 49.5,
            "target_regime": "Recovery",
            "idempotency_key": "idem-signal-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["eligibility"]["is_eligible"] is True
    assert (
        preview_response["preview_result"]["signal_payload_summary"]["invalidation_threshold"]
        == 49.5
    )
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 88
    assert captured_calls[0]["asset_code"] == "000001.SH"
    assert captured_calls[0]["target_regime"] == "Recovery"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["asset_code"] == "000001.SH"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_signal_approve_capability_runs_status_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSignal:
        id = 51
        asset_code = "000001.SH"
        status = "pending"
        created_at = None

    class _FakeSignalModule:
        @staticmethod
        def get(signal_id):
            signal = _FakeSignal()
            signal.id = signal_id
            return signal

    class _FakeClient:
        signal = _FakeSignalModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_approve_signal(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": kwargs["signal_id"],
            "status": "approved",
            "approved_at": "2026-07-09T13:00:00+00:00",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "approve_signal",
        fake_approve_signal,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="signal.approve.signal",
        arguments={
            "signal_id": 51,
            "approver": "risk_admin",
            "idempotency_key": "idem-signal-approve",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["signal_status"] == "pending"
    assert preview_response["preview_result"]["target_status"] == "approved"
    assert preview_response["preview_result"]["approver"] == "risk_admin"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["status"] == "approved"
    assert captured_calls[0]["signal_id"] == 51
    assert captured_calls[0]["approver"] == "risk_admin"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["signal_id"] == 51
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_signal_reject_capability_runs_status_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSignal:
        id = 61
        asset_code = "000002.SZ"
        status = "pending"
        created_at = None

    class _FakeSignalModule:
        @staticmethod
        def get(signal_id):
            signal = _FakeSignal()
            signal.id = signal_id
            return signal

    class _FakeClient:
        signal = _FakeSignalModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_reject_signal(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": kwargs["signal_id"],
            "status": "rejected",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "reject_signal",
        fake_reject_signal,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="signal.reject.signal",
        arguments={
            "signal_id": 61,
            "reason": "Regime mismatch",
            "idempotency_key": "idem-signal-reject",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["signal_status"] == "pending"
    assert preview_response["preview_result"]["target_status"] == "rejected"
    assert preview_response["preview_result"]["reason"] == "Regime mismatch"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["status"] == "rejected"
    assert captured_calls[0]["signal_id"] == 61
    assert captured_calls[0]["reason"] == "Regime mismatch"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["signal_id"] == 61
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_signal_invalidate_capability_runs_status_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSignal:
        id = 71
        asset_code = "000003.SZ"
        status = "approved"
        created_at = None

    class _FakeSignalModule:
        @staticmethod
        def get(signal_id):
            signal = _FakeSignal()
            signal.id = signal_id
            return signal

    class _FakeClient:
        signal = _FakeSignalModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_invalidate_signal(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": kwargs["signal_id"],
            "status": "invalidated",
            "invalidated_at": "2026-07-09T14:00:00+00:00",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "invalidate_signal",
        fake_invalidate_signal,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="signal.invalidate.signal",
        arguments={
            "signal_id": 71,
            "reason": "PMI broke invalidation threshold",
            "idempotency_key": "idem-signal-invalidate",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["signal_status"] == "approved"
    assert preview_response["preview_result"]["target_status"] == "invalidated"
    assert preview_response["preview_result"]["reason"] == "PMI broke invalidation threshold"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["status"] == "invalidated"
    assert captured_calls[0]["signal_id"] == 71
    assert captured_calls[0]["reason"] == "PMI broke invalidation threshold"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["signal_id"] == 71
    assert audit_events[1]["event_type"] == "confirmation_completed"
