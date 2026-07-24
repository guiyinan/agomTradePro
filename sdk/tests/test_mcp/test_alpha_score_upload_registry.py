from types import SimpleNamespace

import pytest

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def test_alpha_score_import_previews_before_staff_only_idempotent_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = []

    class _AlphaModule:
        @staticmethod
        def preview_score_upload(**payload):
            calls.append(("preview", dict(payload)))
            return {
                "success": True,
                "preview": {
                    "operation": "create",
                    "scope": payload["scope"],
                    "universe_id": payload["universe_id"],
                    "intended_trade_date": payload["intended_trade_date"],
                    "incoming_score_count": len(payload["scores"]),
                    "existing": None,
                    "writes": ["alpha_score_cache"],
                },
            }

        @staticmethod
        def upload_scores(**payload):
            calls.append(("commit", dict(payload)))
            return {"success": True, "id": 8, "count": len(payload["scores"])}

    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(alpha=_AlphaModule()),
    )
    monkeypatch.setattr(
        server_module.CORE_DISPATCHER,
        "_audit_logger",
        SimpleNamespace(
            log_governed_capability_event=lambda **kwargs: audit_events.append(dict(kwargs))
            or "audit-alpha-1"
        ),
    )
    monkeypatch.setattr(
        server_module.CORE_DISPATCHER,
        "_role_provider",
        lambda: "staff",
    )
    manifest = CapabilityRegistryLoader().build_registry()["alpha.import.score_cache"]
    assert manifest.required_roles == ("staff",)
    assert manifest.idempotency == "required"
    assert manifest.legacy_tool_names == ("upload_alpha_scores",)

    arguments = {
        "universe_id": " csi300 ",
        "asof_date": "2026-07-11",
        "intended_trade_date": "2026-07-12",
        "scores": [{"code": "000001.sz", "score": 0.9, "rank": 1}],
        "scope": "system",
        "idempotency_key": "idem-alpha-upload",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="alpha.import.score_cache", arguments=arguments
    )
    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["summary"]["incoming_score_count"] == 1
    preview_payload = calls[0][1]
    assert preview_payload["universe_id"] == "csi300"
    assert preview_payload["scores"][0]["code"] == "000001.SZ"
    assert "preview_only" not in preview_payload
    assert "idempotency_key" not in preview_payload

    resumed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"], approve=True
    )
    assert resumed["status"] == "completed"
    assert resumed["result"]["id"] == 8
    assert calls[1][0] == "commit"
    assert "preview_only" not in calls[1][1]
    assert "idempotency_key" not in calls[1][1]

    replay = server_module.CORE_DISPATCHER.call(
        capability_key="alpha.import.score_cache", arguments=arguments
    )
    assert replay["status"] == "idempotent_replay"
    assert len(calls) == 2
    assert audit_events[0]["affected_objects"]["preview_summary"]["writes"] == ["alpha_score_cache"]
