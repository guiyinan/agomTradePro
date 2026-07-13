# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_filter."""

from .core_registry_support import *


def test_agom_capability_call_reads_filter_indicator_catalog_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "list_filters",
        lambda **kwargs: {
            "filters": [
                {"id": 1, "code": "PMI", "name": "PMI"},
                {"id": 2, "code": "CPI", "name": "CPI"},
            ],
            "total_count": 2,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "filter.read.indicator_catalog",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "filter.read.indicator_catalog" in rendered
    assert "PMI" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_filter_config_detail_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_filter",
        lambda **kwargs: {
            "indicator_code": "PMI",
            "hp_enabled": True,
            "hp_lambda": 129600.0,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "filter.read.config_detail",
                "arguments": {"indicator_code": "PMI"},
            },
        )
    )

    rendered = str(result)
    assert "filter.read.config_detail" in rendered
    assert "PMI" in rendered
    assert "core-only-fallback" in rendered


def test_filter_create_filter_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    preview_payloads = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeFilterModule:
        @staticmethod
        def create_filter(payload):
            preview_payloads.append(dict(payload))
            assert payload["indicator_code"] == "PMI"
            assert payload["filter_type"] == "HP"
            assert payload["limit"] == 120
            assert payload["save_results"] is False
            return {
                "success": True,
                "series": {
                    "indicator_code": "PMI",
                    "filter_type": "HP",
                    "dates": ["2026-01-01", "2026-02-01"],
                },
                "warnings": ["preview warning"],
            }

    class _FakeClient:
        filter = _FakeFilterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_create_filter(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "series": {
                "indicator_code": kwargs["payload"]["indicator_code"],
                "filter_type": kwargs["payload"]["filter_type"],
            },
            "warnings": [],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "create_filter",
        fake_create_filter,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="filter.create.filter",
        arguments={
            "indicator_code": "PMI",
            "filter_type": "HP",
            "limit": 120,
            "idempotency_key": "idem-filter-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["preview_run_summary"]["indicator_code"] == "PMI"
    assert preview_response["preview_result"]["preview_run_summary"]["point_count"] == 2
    assert preview_response["preview_result"]["preview_run_summary"]["warning_count"] == 1
    assert preview_payloads[0]["save_results"] is False
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["success"] is True
    assert resume_response["result"]["series"]["indicator_code"] == "PMI"
    assert captured_calls[0]["payload"]["indicator_code"] == "PMI"
    assert captured_calls[0]["payload"]["save_results"] is True
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["indicator_code"] == "PMI"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_filter_update_filter_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeFilterModule:
        @staticmethod
        def get_filter(filter_id=None, indicator_code=None):
            assert filter_id is None
            assert indicator_code == "PMI"
            return {
                "indicator_code": "PMI",
                "hp_enabled": True,
                "hp_lambda": 129600.0,
                "kalman_enabled": True,
                "kalman_level_variance": 0.05,
                "kalman_slope_variance": 0.005,
                "kalman_observation_variance": 0.5,
                "description": "",
            }

        @staticmethod
        def update_filter(filter_id=None, payload=None, indicator_code=None):
            captured_calls.append(
                {
                    "filter_id": filter_id,
                    "indicator_code": indicator_code,
                    "payload": dict(payload or {}),
                }
            )
            return {
                "indicator_code": indicator_code,
                **dict(payload or {}),
            }

    class _FakeClient:
        filter = _FakeFilterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="filter.update.filter",
        arguments={
            "indicator_code": "PMI",
            "hp_enabled": False,
            "hp_lambda": 6400.0,
            "description": "updated config",
            "idempotency_key": "idem-filter-update",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["filter_config_summary"]["hp_lambda"] == 129600.0
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 3
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["indicator_code"] == "PMI"
    assert captured_calls[0]["filter_id"] is None
    assert captured_calls[0]["indicator_code"] == "PMI"
    assert captured_calls[0]["payload"]["hp_lambda"] == 6400.0
    assert audit_events[0]["affected_objects"]["indicator_code"] == "PMI"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_filter_delete_filter_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeFilterModule:
        @staticmethod
        def get_filter(filter_id=None, indicator_code=None):
            assert filter_id is None
            assert indicator_code == "PMI"
            return {
                "indicator_code": "PMI",
                "hp_enabled": False,
                "hp_lambda": 6400.0,
                "kalman_enabled": True,
                "kalman_level_variance": 0.05,
                "kalman_slope_variance": 0.005,
                "kalman_observation_variance": 0.5,
                "description": "override",
            }

        @staticmethod
        def delete_filter(filter_id=None, indicator_code=None):
            captured_calls.append(
                {
                    "filter_id": filter_id,
                    "indicator_code": indicator_code,
                }
            )

    class _FakeClient:
        filter = _FakeFilterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="filter.delete.filter",
        arguments={
            "indicator_code": "PMI",
            "idempotency_key": "idem-filter-delete",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["filter_config_summary"]["description"] == "override"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["success"] is True
    assert captured_calls[0]["filter_id"] is None
    assert captured_calls[0]["indicator_code"] == "PMI"
    assert audit_events[0]["affected_objects"]["indicator_code"] == "PMI"
    assert audit_events[1]["event_type"] == "confirmation_completed"
