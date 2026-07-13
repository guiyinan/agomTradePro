# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_data_center."""

from .core_registry_support import *


def test_data_center_capital_flows_fallback_uses_formal_sdk_contract(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls: list[dict] = []

    class _FakeDataCenterModule:
        @staticmethod
        def get_capital_flows(asset_code, *, start=None, end=None, limit=None):
            calls.append(
                {
                    "asset_code": asset_code,
                    "start": start,
                    "end": end,
                    "limit": limit,
                }
            )
            return {
                "asset_code": asset_code,
                "query": {"start": start, "end": end, "limit": limit},
                "total": 0,
                "data": [],
            }

    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(data_center=_FakeDataCenterModule()),
    )

    fallback = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["data_center_get_capital_flows"]
    result = fallback(
        asset_code="300502.SZ",
        start="2026-04-01",
        end="2026-04-10",
        limit=10,
    )

    assert result["query"]["limit"] == 10
    assert calls == [
        {
            "asset_code": "300502.SZ",
            "start": "2026-04-01",
            "end": "2026-04-10",
            "limit": 10,
        }
    ]


def test_agom_capability_call_reads_data_center_provider_catalog_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "list_data_center_providers",
        lambda **kwargs: {
            "providers": [
                {
                    "id": 7,
                    "name": "tushare-main",
                    "source_type": "tushare",
                    "priority": 10,
                    "is_active": True,
                }
            ],
            "total_count": 1,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "data_center.read.provider_catalog",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "data_center.read.provider_catalog" in rendered
    assert "tushare-main" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_data_center_provider_status_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_data_center_provider_status",
        lambda **kwargs: {
            "providers": [
                {
                    "provider_name": "tushare-main",
                    "status": "healthy",
                    "capability": "macro",
                }
            ],
            "total_count": 1,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "data_center.read.provider_status",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "data_center.read.provider_status" in rendered
    assert "tushare-main" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_data_center_macro_series_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_get_macro_series",
        lambda **kwargs: {
            "indicator_code": kwargs["indicator_code"],
            "observations": [
                {
                    "period": "2026-06",
                    "value": 50.2,
                    "unit": "指数",
                }
            ],
            "provenance_class": "official",
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "data_center.read.macro_series",
                "arguments": {"indicator_code": "CN_PMI", "limit": 1},
            },
        )
    )

    rendered = str(result)
    assert "data_center.read.macro_series" in rendered
    assert "CN_PMI" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_data_center_indicator_catalog_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_list_indicators",
        lambda **kwargs: {
            "indicators": [
                {
                    "code": "CN_PMI",
                    "name_cn": "制造业PMI",
                    "is_active": kwargs.get("active_only", False),
                }
            ],
            "total_count": 1,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "data_center.read.indicator_catalog",
                "arguments": {"active_only": True},
            },
        )
    )

    rendered = str(result)
    assert "data_center.read.indicator_catalog" in rendered
    assert "CN_PMI" in rendered
    assert "core-only-fallback" in rendered


def test_data_center_create_publisher_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_data_center_create_publisher(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "code": kwargs["code"],
            "canonical_name": kwargs["canonical_name"],
            "publisher_class": kwargs["publisher_class"],
            "aliases": kwargs["aliases"],
            "country_code": kwargs["country_code"],
            "website": kwargs["website"],
            "is_active": kwargs["is_active"],
            "description": kwargs["description"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_create_publisher",
        fake_data_center_create_publisher,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.create.publisher",
        arguments={
            "code": "TEST_PUBLISHER",
            "canonical_name": "测试 Publisher",
            "publisher_class": "other",
            "aliases": ["测试别名1", "测试别名2"],
            "country_code": "CN",
            "website": "https://example.com/publisher",
            "is_active": True,
            "description": "test publisher",
            "idempotency_key": "idem-data-center-publisher-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["create_summary"]["code"] == "TEST_PUBLISHER"
    assert (
        preview_response["preview_result"]["create_summary"]["canonical_name"] == "测试 Publisher"
    )
    assert preview_response["preview_result"]["create_summary"]["alias_count"] == 2
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["code"] == "TEST_PUBLISHER"
    assert resume_response["result"]["canonical_name"] == "测试 Publisher"
    assert captured_calls[0]["code"] == "TEST_PUBLISHER"
    assert captured_calls[0]["publisher_class"] == "other"
    assert captured_calls[0]["aliases"] == ["测试别名1", "测试别名2"]
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["code"] == "TEST_PUBLISHER"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_data_center_delete_publisher_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_publisher(publisher_code):
            assert publisher_code == "TEST_PUBLISHER"
            return {
                "code": publisher_code,
                "canonical_name": "测试 Publisher",
                "publisher_class": "other",
                "aliases": ["测试别名1", "测试别名2"],
                "country_code": "CN",
                "website": "https://example.com/publisher",
                "is_active": True,
                "description": "test publisher",
            }

    class _FakeClient:
        data_center = _FakeDataCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_data_center_delete_publisher(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "publisher_code": kwargs["publisher_code"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_delete_publisher",
        fake_data_center_delete_publisher,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.delete.publisher",
        arguments={
            "publisher_code": "TEST_PUBLISHER",
            "idempotency_key": "idem-data-center-publisher-delete",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert (
        preview_response["preview_result"]["publisher_summary"]["canonical_name"]
        == "测试 Publisher"
    )
    assert preview_response["preview_result"]["target_status"] == "deleted"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["success"] is True
    assert resume_response["result"]["publisher_code"] == "TEST_PUBLISHER"
    assert captured_calls[0]["publisher_code"] == "TEST_PUBLISHER"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["publisher_code"] == "TEST_PUBLISHER"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_data_center_create_indicator_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_data_center_create_indicator(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "code": kwargs["code"],
            "name_cn": kwargs["name_cn"],
            "category": kwargs["category"],
            "default_period_type": kwargs["default_period_type"],
            "is_active": kwargs["is_active"],
            "extra": kwargs["extra"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_create_indicator",
        fake_data_center_create_indicator,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.create.indicator",
        arguments={
            "code": "CN_TEST_LEVEL",
            "name_cn": "测试总量指标",
            "category": "growth",
            "default_period_type": "M",
            "is_active": True,
            "extra": {"publication_lag_days": 7},
            "idempotency_key": "idem-data-center-indicator-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["create_summary"]["code"] == "CN_TEST_LEVEL"
    assert preview_response["preview_result"]["create_summary"]["name_cn"] == "测试总量指标"
    assert preview_response["preview_result"]["create_summary"]["extra_keys"] == [
        "publication_lag_days"
    ]
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["code"] == "CN_TEST_LEVEL"
    assert resume_response["result"]["name_cn"] == "测试总量指标"
    assert captured_calls[0]["code"] == "CN_TEST_LEVEL"
    assert captured_calls[0]["category"] == "growth"
    assert captured_calls[0]["extra"] == {"publication_lag_days": 7}
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["code"] == "CN_TEST_LEVEL"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_data_center_delete_indicator_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_indicator(indicator_code):
            assert indicator_code == "CN_TEST_LEVEL"
            return {
                "code": indicator_code,
                "name_cn": "测试总量指标",
                "name_en": "Test Level Indicator",
                "description": "用于 CRUD 契约测试",
                "category": "growth",
                "default_period_type": "M",
                "is_active": True,
                "extra": {"publication_lag_days": 7},
            }

    class _FakeClient:
        data_center = _FakeDataCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_data_center_delete_indicator(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "indicator_code": kwargs["indicator_code"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_delete_indicator",
        fake_data_center_delete_indicator,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.delete.indicator",
        arguments={
            "indicator_code": "CN_TEST_LEVEL",
            "idempotency_key": "idem-data-center-indicator-delete",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["indicator_summary"]["name_cn"] == "测试总量指标"
    assert preview_response["preview_result"]["target_status"] == "deleted"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["success"] is True
    assert resume_response["result"]["indicator_code"] == "CN_TEST_LEVEL"
    assert captured_calls[0]["indicator_code"] == "CN_TEST_LEVEL"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["indicator_code"] == "CN_TEST_LEVEL"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_data_center_create_indicator_unit_rule_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_indicator(indicator_code):
            assert indicator_code == "CN_TEST_GDP"
            return {
                "code": indicator_code,
                "name_cn": "测试 GDP",
                "category": "growth",
                "default_period_type": "Q",
                "is_active": True,
            }

        @staticmethod
        def list_indicator_unit_rules(indicator_code):
            assert indicator_code == "CN_TEST_GDP"
            return [
                {
                    "id": 7,
                    "indicator_code": indicator_code,
                    "source_type": "akshare",
                    "original_unit": "万亿元",
                }
            ]

    class _FakeClient:
        data_center = _FakeDataCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_data_center_create_indicator_unit_rule(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": 9,
            "indicator_code": kwargs["indicator_code"],
            "source_type": kwargs["source_type"],
            "dimension_key": kwargs["dimension_key"],
            "original_unit": kwargs["original_unit"],
            "storage_unit": kwargs["storage_unit"],
            "display_unit": kwargs["display_unit"],
            "multiplier_to_storage": kwargs["multiplier_to_storage"],
            "is_active": kwargs["is_active"],
            "priority": kwargs["priority"],
            "description": kwargs["description"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_create_indicator_unit_rule",
        fake_data_center_create_indicator_unit_rule,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.create.indicator_unit_rule",
        arguments={
            "indicator_code": "CN_TEST_GDP",
            "source_type": "akshare",
            "dimension_key": "currency",
            "original_unit": "亿元",
            "storage_unit": "元",
            "display_unit": "亿元",
            "multiplier_to_storage": 100000000.0,
            "priority": 20,
            "description": "GDP 亿元转元",
            "idempotency_key": "idem-data-center-indicator-unit-rule-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["indicator_summary"]["name_cn"] == "测试 GDP"
    assert preview_response["preview_result"]["create_summary"]["dimension_key"] == "currency"
    assert preview_response["preview_result"]["existing_rule_summary"]["existing_rule_count"] == 1
    assert preview_response["preview_result"]["existing_rule_summary"]["matching_rule_count"] == 0
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 9
    assert resume_response["result"]["indicator_code"] == "CN_TEST_GDP"
    assert captured_calls[0]["indicator_code"] == "CN_TEST_GDP"
    assert captured_calls[0]["source_type"] == "akshare"
    assert captured_calls[0]["display_unit"] == "亿元"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["indicator_code"] == "CN_TEST_GDP"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_data_center_delete_indicator_unit_rule_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_indicator(indicator_code):
            assert indicator_code == "CN_TEST_GDP"
            return {
                "code": indicator_code,
                "name_cn": "测试 GDP",
                "category": "growth",
                "default_period_type": "Q",
                "is_active": True,
            }

        @staticmethod
        def get_indicator_unit_rule(indicator_code, rule_id):
            assert indicator_code == "CN_TEST_GDP"
            assert rule_id == 9
            return {
                "id": rule_id,
                "indicator_code": indicator_code,
                "source_type": "akshare",
                "dimension_key": "currency",
                "original_unit": "亿元",
                "storage_unit": "元",
                "display_unit": "亿元",
                "multiplier_to_storage": 100000000.0,
                "is_active": True,
                "priority": 20,
                "description": "GDP 亿元转元",
            }

    class _FakeClient:
        data_center = _FakeDataCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_data_center_delete_indicator_unit_rule(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "indicator_code": kwargs["indicator_code"],
            "rule_id": kwargs["rule_id"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_delete_indicator_unit_rule",
        fake_data_center_delete_indicator_unit_rule,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.delete.indicator_unit_rule",
        arguments={
            "indicator_code": "CN_TEST_GDP",
            "rule_id": 9,
            "idempotency_key": "idem-data-center-indicator-unit-rule-delete",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["indicator_summary"]["name_cn"] == "测试 GDP"
    assert preview_response["preview_result"]["rule_summary"]["dimension_key"] == "currency"
    assert preview_response["preview_result"]["target_status"] == "deleted"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["success"] is True
    assert resume_response["result"]["indicator_code"] == "CN_TEST_GDP"
    assert resume_response["result"]["rule_id"] == 9
    assert captured_calls[0]["indicator_code"] == "CN_TEST_GDP"
    assert captured_calls[0]["rule_id"] == 9
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["indicator_code"] == "CN_TEST_GDP"
    assert audit_events[0]["affected_objects"]["rule_id"] == 9
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_data_center_update_indicator_unit_rule_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_indicator(indicator_code):
            assert indicator_code == "CN_TEST_GDP"
            return {
                "code": indicator_code,
                "name_cn": "测试 GDP",
                "category": "growth",
                "default_period_type": "Q",
                "is_active": True,
            }

        @staticmethod
        def get_indicator_unit_rule(indicator_code, rule_id):
            assert indicator_code == "CN_TEST_GDP"
            assert rule_id == 9
            return {
                "id": rule_id,
                "indicator_code": indicator_code,
                "source_type": "akshare",
                "dimension_key": "currency",
                "original_unit": "亿元",
                "storage_unit": "元",
                "display_unit": "亿元",
                "multiplier_to_storage": 100000000.0,
                "is_active": True,
                "priority": 20,
                "description": "GDP 亿元转元",
            }

    class _FakeClient:
        data_center = _FakeDataCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_data_center_update_indicator_unit_rule(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "id": kwargs["rule_id"],
            "indicator_code": kwargs["indicator_code"],
            "source_type": kwargs.get("source_type", "akshare"),
            "dimension_key": kwargs.get("dimension_key", "currency"),
            "original_unit": kwargs.get("original_unit", "亿元"),
            "storage_unit": kwargs.get("storage_unit", "元"),
            "display_unit": kwargs.get("display_unit", "亿元"),
            "multiplier_to_storage": kwargs.get("multiplier_to_storage", 100000000.0),
            "is_active": kwargs.get("is_active", True),
            "priority": kwargs.get("priority", 20),
            "description": kwargs.get("description", "GDP 亿元转元"),
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_update_indicator_unit_rule",
        fake_data_center_update_indicator_unit_rule,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.update.indicator_unit_rule",
        arguments={
            "indicator_code": "CN_TEST_GDP",
            "rule_id": 9,
            "display_unit": "万亿元",
            "priority": 30,
            "description": "更新后的 GDP 展示单位规则",
            "idempotency_key": "idem-data-center-indicator-unit-rule-update",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["indicator_summary"]["name_cn"] == "测试 GDP"
    assert preview_response["preview_result"]["rule_summary"]["display_unit"] == "亿元"
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 3
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 9
    assert resume_response["result"]["indicator_code"] == "CN_TEST_GDP"
    assert resume_response["result"]["display_unit"] == "万亿元"
    assert captured_calls[0]["indicator_code"] == "CN_TEST_GDP"
    assert captured_calls[0]["rule_id"] == 9
    assert captured_calls[0]["priority"] == 30
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["indicator_code"] == "CN_TEST_GDP"
    assert audit_events[0]["affected_objects"]["rule_id"] == 9
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_data_center_start_sync_job_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_provider(provider_id):
            assert provider_id == 3
            return {
                "id": provider_id,
                "name": "akshare-macro",
                "source_type": "akshare",
                "is_active": True,
                "priority": 10,
            }

        @staticmethod
        def get_indicator(indicator_code):
            assert indicator_code == "CN_PMI"
            return {
                "code": indicator_code,
                "name_cn": "制造业PMI",
                "category": "macro",
                "default_period_type": "M",
                "is_active": True,
            }

    class _FakeClient:
        data_center = _FakeDataCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_data_center_sync_macro(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "domain": "macro",
            "provider_name": "akshare",
            "stored_count": 3,
            "status": "success",
            "error_message": "",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_sync_macro",
        fake_data_center_sync_macro,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.start.sync_job",
        arguments={
            "job_kind": "sync_macro",
            "provider_id": 3,
            "indicator_code": "CN_PMI",
            "start": "2026-01-01",
            "end": "2026-03-31",
            "idempotency_key": "idem-data-center-sync-macro",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["provider_summary"]["name"] == "akshare-macro"
    assert preview_response["preview_result"]["indicator_summary"]["name_cn"] == "制造业PMI"
    assert preview_response["preview_result"]["sync_job_summary"]["job_kind"] == "sync_macro"
    assert preview_response["preview_result"]["sync_job_summary"]["window_days"] == 90
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["domain"] == "macro"
    assert resume_response["result"]["provider_name"] == "akshare"
    assert resume_response["result"]["stored_count"] == 3
    assert captured_calls[0]["provider_id"] == 3
    assert captured_calls[0]["indicator_code"] == "CN_PMI"
    assert captured_calls[0]["start"] == "2026-01-01"
    assert captured_calls[0]["end"] == "2026-03-31"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["provider_id"] == 3
    assert audit_events[0]["affected_objects"]["indicator_code"] == "CN_PMI"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_data_center_start_sync_job_supports_sync_capital_flows_variant(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_provider(provider_id):
            assert provider_id == 5
            return {
                "id": provider_id,
                "name": "eastmoney-capital-flow",
                "source_type": "eastmoney",
                "is_active": True,
                "priority": 20,
            }

        @staticmethod
        def resolve_asset(code, source_type=None):
            assert code == "000001.SZ"
            assert source_type == "eastmoney"
            return {
                "code": code,
                "name": "Ping An Bank",
                "name_cn": "平安银行",
                "asset_type": "equity",
                "exchange": "SZ",
            }

    class _FakeClient:
        data_center = _FakeDataCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_data_center_sync_capital_flows(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "domain": "capital_flow",
            "provider_name": "eastmoney",
            "stored_count": 5,
            "status": "success",
            "error_message": "",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_sync_capital_flows",
        fake_data_center_sync_capital_flows,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.start.sync_job",
        arguments={
            "job_kind": "sync_capital_flows",
            "provider_id": 5,
            "asset_code": "000001.SZ",
            "period": "10d",
            "idempotency_key": "idem-data-center-sync-capital-flows",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert (
        preview_response["preview_result"]["provider_summary"]["name"] == "eastmoney-capital-flow"
    )
    assert preview_response["preview_result"]["asset_summary"]["name_cn"] == "平安银行"
    assert (
        preview_response["preview_result"]["sync_job_summary"]["job_kind"] == "sync_capital_flows"
    )
    assert preview_response["preview_result"]["sync_job_summary"]["period"] == "10d"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["domain"] == "capital_flow"
    assert resume_response["result"]["provider_name"] == "eastmoney"
    assert resume_response["result"]["stored_count"] == 5
    assert captured_calls[0]["provider_id"] == 5
    assert captured_calls[0]["asset_code"] == "000001.SZ"
    assert captured_calls[0]["period"] == "10d"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["provider_id"] == 5
    assert audit_events[0]["affected_objects"]["asset_code"] == "000001.SZ"
    assert audit_events[1]["event_type"] == "confirmation_completed"
