"""Signal application query-service delegation and eligibility contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.signal.application import query_services


class _SignalRepo:
    def list_signal_payloads(self, **kwargs: object) -> list[dict[str, object]]:
        return [{"id": "1", "asset_code": "000001.SZ"}]

    def get_signal_payload(self, signal_id: str) -> dict[str, object] | None:
        return {"id": signal_id, "asset_code": "000001.SZ"}

    def create_signal_record(self, **kwargs: object) -> dict[str, object]:
        return {"created": True, **kwargs}

    def update_signal_record_fields(
        self,
        signal_id: str,
        **kwargs: object,
    ) -> dict[str, object]:
        return {"id": signal_id, **kwargs}

    def get_signal_management_metadata(self) -> dict[str, object]:
        return {"stats": {"total": 2}}

    def count_signal_records(self) -> int:
        return 2

    def update_signal_record_status(self, **kwargs: object) -> dict[str, object]:
        return kwargs

    def delete_signal_record(self, signal_id: str) -> str:
        return "000001.SZ"

    def get_invalidation_payloads(
        self,
        signal_ids: list[int],
    ) -> dict[str, dict[str, object]]:
        return {str(signal_id): {"id": signal_id} for signal_id in signal_ids}


class _UnifiedRepo:
    def get_pending_signals(self, **kwargs: object) -> list[dict[str, object]]:
        return [{"pending": True, **kwargs}]

    def get_signals_by_asset(
        self,
        asset_code: str,
        **kwargs: object,
    ) -> list[dict[str, object]]:
        return [{"asset_code": asset_code, **kwargs}]

    def mark_executed(self, signal_id: int | str) -> bool:
        return True


def test_signal_query_services_delegate_filters_status_and_diagnostics(monkeypatch) -> None:
    """Thin application services forward exact filters and normalize health payloads."""
    monkeypatch.setattr(query_services, "DjangoSignalRepository", _SignalRepo)
    monkeypatch.setattr(query_services, "UnifiedSignalRepository", _UnifiedRepo)
    diagnostic = SimpleNamespace(
        get_signal_count=lambda: 3,
        get_signal_summary=lambda: {"approved": 2},
        list_distinct_asset_codes=lambda: ["000001.SZ"],
    )
    monkeypatch.setattr(
        query_services,
        "get_signal_diagnostic_repository",
        lambda: diagnostic,
    )

    assert query_services._infer_asset_class("511010.SH") == "china_bond"
    assert query_services._infer_asset_class("518880.SH") == "gold"
    assert query_services._infer_asset_class("159985.SZ") == "commodity"
    assert query_services._infer_asset_class("000001.SZ") == "a_share_growth"
    assert query_services.list_investment_signal_payloads(limit=1)[0]["id"] == "1"
    assert query_services.get_investment_signal_payload("1")["id"] == "1"
    updated = query_services.update_investment_signal_payload(
        "1",
        asset_code="000002.SZ",
        direction="SHORT",
        logic_desc="updated",
        target_regime="Deflation",
    )
    assert updated["asset_code"] == "000002.SZ"
    assert query_services.get_signal_stats_payload() == {"total": 2}
    assert query_services.get_signal_health_payload()["records_count"] == 2
    assert query_services.get_signal_diagnostic_count() == 3
    assert query_services.get_signal_diagnostic_summary() == {"approved": 2}
    assert query_services.list_signal_diagnostic_asset_codes() == ["000001.SZ"]
    assert (
        query_services.update_investment_signal_status(
            signal_id="1",
            status="approved",
        )["status"]
        == "approved"
    )
    assert query_services.delete_investment_signal_record("1") == "000001.SZ"
    assert query_services.get_pending_unified_signals(min_priority=3)[0]["pending"] is True
    assert (
        query_services.get_unified_signals_by_asset(
            asset_code="000001.SZ",
            days=30,
        )[
            0
        ]["days"]
        == 30
    )
    assert query_services.mark_unified_signal_executed(1) is True
    assert query_services.get_signal_invalidation_payloads([]) == {}
    assert query_services.get_signal_invalidation_payloads([1, 2])["2"]["id"] == 2


def test_signal_eligibility_exposes_regime_rejection_and_missing_regime(monkeypatch) -> None:
    """Eligibility fails explicitly without regime data and explains hostile matches."""
    monkeypatch.setattr(
        query_services,
        "resolve_current_regime",
        lambda: SimpleNamespace(dominant_regime="Unknown"),
    )
    with pytest.raises(LookupError, match="No regime"):
        query_services.validate_signal_eligibility_payload({"asset_code": "000001.SZ"})

    monkeypatch.setattr(
        query_services,
        "resolve_current_regime",
        lambda: SimpleNamespace(dominant_regime="Deflation"),
    )
    payload = query_services.validate_signal_eligibility_payload({"asset_code": "000001.SZ"})
    assert payload["success"] is True
    assert payload["current_regime"] == "Deflation"
    assert payload["policy_match"] is True
