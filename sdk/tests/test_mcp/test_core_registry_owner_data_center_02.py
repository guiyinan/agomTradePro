# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_data_center."""

from .core_registry_support import *


def test_data_center_start_sync_job_supports_sync_news_variant(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_provider(provider_id):
            assert provider_id == 8
            return {
                "id": provider_id,
                "name": "eastmoney-news",
                "source_type": "eastmoney",
                "is_active": True,
                "priority": 30,
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

    def fake_data_center_sync_news(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "domain": "news",
            "provider_name": "eastmoney",
            "stored_count": 7,
            "status": "success",
            "error_message": "",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_sync_news",
        fake_data_center_sync_news,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.start.sync_job",
        arguments={
            "job_kind": "sync_news",
            "provider_id": 8,
            "asset_code": "000001.SZ",
            "limit": 5,
            "idempotency_key": "idem-data-center-sync-news",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["provider_summary"]["name"] == "eastmoney-news"
    assert preview_response["preview_result"]["asset_summary"]["name_cn"] == "平安银行"
    assert preview_response["preview_result"]["sync_job_summary"]["job_kind"] == "sync_news"
    assert preview_response["preview_result"]["sync_job_summary"]["limit"] == 5
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["domain"] == "news"
    assert resume_response["result"]["provider_name"] == "eastmoney"
    assert resume_response["result"]["stored_count"] == 7
    assert captured_calls[0]["provider_id"] == 8
    assert captured_calls[0]["asset_code"] == "000001.SZ"
    assert captured_calls[0]["limit"] == 5
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["provider_id"] == 8
    assert audit_events[0]["affected_objects"]["asset_code"] == "000001.SZ"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_data_center_update_publisher_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_publisher(publisher_code):
            assert publisher_code == "PBOC"
            return {
                "code": publisher_code,
                "canonical_name": "中国人民银行",
                "publisher_class": "government",
                "aliases": ["人民银行", "中国人行"],
                "country_code": "CN",
                "website": "https://www.pbc.gov.cn",
                "is_active": True,
                "description": "央行 publisher",
            }

    class _FakeClient:
        data_center = _FakeDataCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_data_center_update_publisher(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "code": kwargs["publisher_code"],
            "canonical_name": kwargs["canonical_name"],
            "publisher_class": kwargs["publisher_class"],
            "aliases": kwargs["aliases"],
            "description": kwargs["description"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_update_publisher",
        fake_data_center_update_publisher,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.update.publisher",
        arguments={
            "publisher_code": "PBOC",
            "canonical_name": "中国人民银行（更新）",
            "publisher_class": "government",
            "aliases": ["人民银行", "中国人行", "央行"],
            "description": "updated publisher",
            "idempotency_key": "idem-data-center-publisher-update",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert (
        preview_response["preview_result"]["publisher_summary"]["canonical_name"] == "中国人民银行"
    )
    assert preview_response["preview_result"]["publisher_summary"]["alias_count"] == 2
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 4
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["code"] == "PBOC"
    assert resume_response["result"]["canonical_name"] == "中国人民银行（更新）"
    assert captured_calls[0]["publisher_code"] == "PBOC"
    assert captured_calls[0]["aliases"] == ["人民银行", "中国人行", "央行"]
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["publisher_code"] == "PBOC"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_data_center_update_indicator_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDataCenterModule:
        @staticmethod
        def get_indicator(indicator_code):
            assert indicator_code == "CN_PMI"
            return {
                "code": indicator_code,
                "name_cn": "制造业PMI",
                "name_en": "Manufacturing PMI",
                "description": "采购经理指数",
                "category": "macro",
                "default_period_type": "M",
                "is_active": True,
                "extra": {"paired_indicator_code": "CN_PMI_YOY", "source": "nbs"},
            }

    class _FakeClient:
        data_center = _FakeDataCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_data_center_update_indicator(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "code": kwargs["indicator_code"],
            "name_cn": kwargs["name_cn"],
            "category": kwargs["category"],
            "default_period_type": kwargs["default_period_type"],
            "is_active": kwargs["is_active"],
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "data_center_update_indicator",
        fake_data_center_update_indicator,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="data_center.update.indicator",
        arguments={
            "indicator_code": "CN_PMI",
            "name_cn": "制造业 PMI（更新）",
            "category": "macro_core",
            "default_period_type": "Q",
            "is_active": False,
            "idempotency_key": "idem-data-center-indicator-update",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["indicator_summary"]["name_cn"] == "制造业PMI"
    assert preview_response["preview_result"]["indicator_summary"]["extra_keys"] == [
        "paired_indicator_code",
        "source",
    ]
    assert preview_response["preview_result"]["update_summary"]["field_count"] == 4
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["code"] == "CN_PMI"
    assert resume_response["result"]["name_cn"] == "制造业 PMI（更新）"
    assert captured_calls[0]["indicator_code"] == "CN_PMI"
    assert captured_calls[0]["default_period_type"] == "Q"
    assert captured_calls[0]["is_active"] is False
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["indicator_code"] == "CN_PMI"
    assert audit_events[1]["event_type"] == "confirmation_completed"
