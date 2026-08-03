# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_equity."""

from .core_registry_support import *


def test_equity_valuation_config_read_manifests_require_staff_role():
    registry = CapabilityRegistryLoader().build_registry()
    capability_keys = {
        "equity.read.valuation_repair_config",
        "equity.read.valuation_repair_config_catalog",
    }

    assert {
        capability_key: registry[capability_key].required_roles
        for capability_key in capability_keys
    } == dict.fromkeys(capability_keys, ("staff",))


def test_equity_read_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _Equity:
        def get_stock_pool(self, *, sector, min_score, limit):
            calls.append(("get_stock_pool", (sector, min_score, limit)))
            return {
                "success": True,
                "regime": "Recovery",
                "update_time": "2026-07-11",
                "avg_roe": 12.5,
                "avg_pe": 18.0,
                "stocks": [{"code": "000001.SZ", "sector": "银行", "score": 70}],
                "total_count": 1,
                "query": {
                    "sector": sector,
                    "min_score": min_score,
                    "max_score": None,
                    "limit": limit,
                },
            }

        def get_valuation(
            self,
            stock_code,
            *,
            lookback_days,
            mode=None,
            publication_key=None,
        ):
            calls.append(
                (
                    "get_valuation",
                    (stock_code, lookback_days, mode, publication_key),
                )
            )
            return {
                "success": True,
                "stock_code": stock_code,
                "stock_name": "平安银行",
                "pe_percentile": 0.15,
            }

        def list_valuation_repairs(self, *, universe, phase, limit):
            calls.append(("list_valuation_repairs", (universe, phase, limit)))
            return {
                "success": True,
                "results": [
                    {
                        "stock_code": "000001.SZ",
                        "phase": "repairing",
                    }
                ],
            }

        def get_valuation_data_freshness(self):
            calls.append(("get_valuation_data_freshness", None))
            return {
                "latest_trade_date": "2026-07-10",
                "lag_days": 0,
                "freshness_status": "fresh",
                "coverage_ratio": 0.99,
                "is_gate_passed": True,
            }

        def get_valuation_data_quality_latest(self):
            calls.append(("get_valuation_data_quality_latest", None))
            return {
                "as_of_date": "2026-07-10",
                "coverage_ratio": 0.99,
                "valid_ratio": 0.98,
                "primary_source": "akshare",
                "is_gate_passed": True,
            }

    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(equity=_Equity()),
    )

    pool = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["equity_read_pool_catalog"](
        sector="银行",
        min_score=60,
        limit=20,
    )
    valuation = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["equity_read_valuation_analysis"](
        stock_code="000001.SZ",
        lookback_days=365,
    )
    repair_list = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["equity_read_valuation_repair_list"](
        universe="all_active",
        phase="repairing",
        limit=20,
    )
    freshness = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["equity_read_valuation_freshness"]()
    quality = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["equity_read_valuation_quality_latest"]()

    assert pool["stocks"][0]["code"] == "000001.SZ"
    assert valuation["pe_percentile"] == 0.15
    assert repair_list["repairs"][0]["stock_code"] == "000001.SZ"
    assert repair_list["query"] == {"phase": "repairing", "limit": 20}
    assert freshness["freshness_status"] == "fresh"
    assert quality["primary_source"] == "akshare"
    assert calls == [
        ("get_stock_pool", ("银行", 60, 20)),
        ("get_valuation", ("000001.SZ", 365, "published", None)),
        ("list_valuation_repairs", ("all_active", "repairing", 20)),
        ("get_valuation_data_freshness", None),
        ("get_valuation_data_quality_latest", None),
    ]


def test_equity_create_valuation_repair_config_previews_version_before_draft_create(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(
        monkeypatch,
        server_module.CORE_DISPATCHER,
    )

    class _FakeEquityModule:
        @staticmethod
        def list_valuation_repair_configs(*, limit=20):
            assert limit == 100
            return [
                {"id": 7, "version": 5, "is_active": False},
                {"id": 6, "version": 4, "is_active": True},
            ]

        @staticmethod
        def get_valuation_repair_config():
            return {
                "id": 6,
                "version": 4,
                "is_active": True,
                "min_history_points": 120,
                "default_lookback_days": 756,
                "confirm_window": 20,
                "min_rebound": 0.05,
                "stall_window": 40,
                "stall_min_progress": 0.02,
                "target_percentile": 0.50,
                "undervalued_threshold": 0.20,
                "near_target_threshold": 0.45,
                "overvalued_threshold": 0.80,
                "pe_weight": 0.6,
                "pb_weight": 0.4,
                "confidence_base": 0.4,
                "confidence_sample_threshold": 252,
                "confidence_sample_bonus": 0.2,
                "confidence_blend_bonus": 0.15,
                "confidence_repair_start_bonus": 0.15,
                "confidence_not_stalled_bonus": 0.1,
                "repairing_threshold": 0.10,
                "eta_max_days": 999,
            }

        @staticmethod
        def create_valuation_repair_config(**kwargs):
            captured_calls.append(dict(kwargs))
            return {
                "id": 8,
                "version": 6,
                "is_active": False,
                "created_by": "staff",
                **kwargs,
            }

    class _FakeClient:
        equity = _FakeEquityModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["equity.create.valuation_repair_config"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("create_valuation_repair_config",)

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="equity.create.valuation_repair_config",
        arguments={
            "change_reason": "Raise governed target percentile.",
            "target_percentile": 0.55,
            "idempotency_key": "idem-equity-valuation-config-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"] == {
        "current_active_version": 4,
        "latest_persisted_version": 5,
        "expected_next_version": 6,
        "changed_field_count": 1,
        "is_active_after_create": False,
    }
    assert preview["field_changes"] == {
        "target_percentile": {
            "current": 0.50,
            "requested": 0.55,
        }
    }
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["version"] == 6
    assert resume_response["result"]["is_active"] is False
    assert captured_calls[0]["change_reason"] == "Raise governed target percentile."
    assert captured_calls[0]["target_percentile"] == 0.55
    assert "idempotency_key" not in captured_calls[0]
    assert "preview_only" not in captured_calls[0]
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_equity_activate_valuation_repair_config_previews_switch_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(
        monkeypatch,
        server_module.CORE_DISPATCHER,
    )

    class _FakeEquityModule:
        @staticmethod
        def get_valuation_repair_config_by_id(config_id):
            assert config_id == 8
            return {
                "id": 8,
                "version": 6,
                "is_active": False,
                "change_reason": "Governed activation candidate.",
                "created_by": "staff",
            }

        @staticmethod
        def get_valuation_repair_config():
            return {
                "id": 6,
                "version": 4,
                "is_active": True,
            }

        @staticmethod
        def activate_valuation_repair_config(config_id):
            captured_calls.append(config_id)
            return {
                "success": True,
                "message": "配置 v6 已激活",
                "data": {
                    "id": config_id,
                    "version": 6,
                    "is_active": True,
                    "effective_from": "2026-07-12T00:00:00+08:00",
                },
            }

    class _FakeClient:
        equity = _FakeEquityModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()[
        "equity.activate.valuation_repair_config"
    ]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == (
        "activate_valuation_repair_config",
        "rollback_valuation_repair_config",
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="equity.activate.valuation_repair_config",
        arguments={
            "config_id": 8,
            "idempotency_key": "idem-equity-valuation-config-activate",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"] == {
        "target_config_id": 8,
        "target_version": 6,
        "current_active_config_id": 6,
        "current_active_version": 4,
        "will_deactivate_current": True,
        "will_activate_target": True,
        "will_update_effective_from": True,
        "will_clear_runtime_cache": True,
    }
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["data"]["id"] == 8
    assert resume_response["result"]["data"]["is_active"] is True
    assert captured_calls == [8]
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[1]["event_type"] == "confirmation_completed"
