"""Signal repository CRUD, filtering, and invalidation persistence contracts."""

from __future__ import annotations

import pytest

from apps.signal.domain.entities import SignalStatus
from apps.signal.infrastructure.repositories import DjangoSignalRepository


def _invalidation_rule(indicator_code: str, threshold: float) -> dict[str, object]:
    return {
        "logic": "AND",
        "conditions": [
            {
                "indicator_code": indicator_code,
                "indicator_type": "macro",
                "operator": "lt",
                "threshold": threshold,
            }
        ],
    }


@pytest.mark.django_db
def test_signal_repository_crud_filters_metadata_and_status_transitions() -> None:
    """Repository public CRUD methods preserve filters and invalidation timestamps."""
    repo = DjangoSignalRepository()
    created = repo.create_signal_record(
        asset_code="000001.SZ",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="PMI recovery",
        invalidation_logic="PMI below 50",
        invalidation_threshold=50.0,
        invalidation_rules=None,
        invalidation_rule_json=_invalidation_rule("PMI", 50.0),
        target_regime="Recovery",
        status="pending",
        rejection_reason="",
    )
    uat = repo.create_signal_record(
        asset_code="UATSIG001",
        asset_class="a_share_growth",
        direction="SHORT",
        logic_desc="test",
        invalidation_logic="manual",
        invalidation_threshold=None,
        invalidation_rules=None,
        target_regime="Deflation",
        status="approved",
        rejection_reason="",
    )
    assert repo.count_signal_records() == 2
    assert [row["asset_code"] for row in repo.list_signal_payloads()] == ["000001.SZ"]
    assert len(repo.list_signal_payloads(include_test=True)) == 2
    assert len(repo.list_signal_records(search="PMI")) == 1
    assert repo.get_signal_payload("invalid-id") is None
    assert repo.get_signal_payload(str(created["id"]))["logic_desc"] == "PMI recovery"

    updated = repo.update_signal_record_fields(
        str(created["id"]),
        logic_desc="updated thesis",
        direction="NEUTRAL",
    )
    assert updated is not None and updated["direction"] == "NEUTRAL"
    invalidated = repo.update_signal_record_status(
        signal_id=str(created["id"]),
        status="invalidated",
        rejection_reason="PMI below 50",
    )
    assert invalidated is not None and invalidated["status"] == "invalidated"

    metadata = repo.get_signal_management_metadata()
    assert metadata["stats"]["invalidated"] == 1
    assert set(metadata["directions"]) == {"NEUTRAL", "SHORT"}
    assert repo.get_signals_by_asset("000001.SZ")[0].status == SignalStatus.INVALIDATED
    assert repo.get_signals_by_status(SignalStatus.APPROVED)[0].asset_code == "UATSIG001"
    assert repo.get_active_signals()[0].asset_code == "UATSIG001"

    assert repo.delete_signal_record(str(uat["id"])) == "UATSIG001"
    assert repo.delete_signal_record(str(uat["id"])) is None


@pytest.mark.django_db
def test_signal_repository_invalidation_queries_and_outcomes() -> None:
    """Signals with proof rules are discoverable and state changes are idempotent."""
    repo = DjangoSignalRepository()
    first = repo.create_signal_record(
        asset_code="000002.SZ",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="credit improves",
        invalidation_logic="spread widens",
        invalidation_threshold=1.0,
        invalidation_rules=None,
        invalidation_rule_json=_invalidation_rule("SPREAD", 1.0),
        target_regime="Recovery",
        status="pending",
        rejection_reason="",
    )
    second = repo.create_signal_record(
        asset_code="000003.SZ",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="growth",
        invalidation_logic="PMI falls",
        invalidation_threshold=50.0,
        invalidation_rules=None,
        invalidation_rule_json=_invalidation_rule("PMI", 50.0),
        target_regime="Recovery",
        status="approved",
        rejection_reason="",
    )
    assert len(repo.find_signals_with_invalidation_rules(SignalStatus.PENDING)) == 1
    assert len(repo.find_signals_to_invalidate(__import__("datetime").date.today())) == 2
    assert repo.persist_invalidation_outcome(
        signal_id=str(first["id"]),
        current_status="pending",
        reason="spread widened",
        details={"checked": True},
    )
    assert repo.get_signal_payload(str(first["id"]))["status"] == "rejected"
    assert repo.mark_invalidated(
        str(second["id"]),
        "PMI fell",
        {"checked": True},
    )
    assert repo.get_signal_payload(str(second["id"]))["status"] == "invalidated"
    assert repo.mark_rejected("999999", "missing") is False
    assert repo.mark_invalidated("999999", "missing", {}) is False
