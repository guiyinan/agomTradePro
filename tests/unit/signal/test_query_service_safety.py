"""Safety boundaries for cross-app Signal query facades."""

from __future__ import annotations

from math import nan
from types import SimpleNamespace

import pytest

from apps.signal.application import query_services


def _fail_repository() -> None:
    raise AssertionError("repository must not be accessed")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 501},
        {"status_filter": "unknown"},
        {"direction": "BUY"},
        {"include_test": 1},
        {"search": "x" * 201},
    ],
)
def test_signal_list_rejects_invalid_filters_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
) -> None:
    monkeypatch.setattr(
        query_services,
        "DjangoSignalRepository",
        _fail_repository,
    )

    with pytest.raises(ValueError):
        query_services.list_investment_signal_payloads(**kwargs)


@pytest.mark.parametrize("signal_id", ["", "not-an-id", "0", "-1"])
def test_invalid_persisted_signal_id_never_reaches_repository(
    monkeypatch: pytest.MonkeyPatch,
    signal_id: str,
) -> None:
    monkeypatch.setattr(
        query_services,
        "DjangoSignalRepository",
        _fail_repository,
    )

    assert query_services.get_investment_signal_payload(signal_id) is None
    assert query_services.delete_investment_signal_record(signal_id) is None
    assert (
        query_services.update_investment_signal_status(
            signal_id=signal_id,
            status="approved",
        )
        is None
    )


def test_signal_update_requires_a_real_field_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query_services,
        "DjangoSignalRepository",
        _fail_repository,
    )

    with pytest.raises(ValueError, match="At least one"):
        query_services.update_investment_signal_payload("1")


@pytest.mark.parametrize(
    ("function_name", "kwargs"),
    [
        ("get_pending_unified_signals", {"min_priority": 0}),
        (
            "get_unified_signals_by_asset",
            {"asset_code": "510300.SH", "days": 3651},
        ),
        (
            "list_active_signal_payloads_by_asset",
            {"asset_code": "510300.SH", "limit": 101},
        ),
    ],
)
def test_unified_query_bounds_are_checked_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
    function_name: str,
    kwargs: dict[str, object],
) -> None:
    monkeypatch.setattr(
        query_services,
        "DjangoSignalRepository",
        _fail_repository,
    )
    monkeypatch.setattr(
        query_services,
        "UnifiedSignalRepository",
        _fail_repository,
    )

    with pytest.raises(ValueError):
        getattr(query_services, function_name)(**kwargs)


def test_mark_executed_normalizes_numeric_string_and_rejects_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[int] = []
    repository = SimpleNamespace(mark_executed=lambda signal_id: received.append(signal_id) or True)
    monkeypatch.setattr(
        query_services,
        "UnifiedSignalRepository",
        lambda: repository,
    )

    assert query_services.mark_unified_signal_executed("7") is True
    assert received == [7]
    assert query_services.mark_unified_signal_executed(True) is False
    assert received == [7]


def test_invalidation_ids_are_positive_deduplicated_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[list[int]] = []
    repository = SimpleNamespace(
        get_invalidation_payloads=lambda signal_ids: (received.append(signal_ids) or {})
    )
    monkeypatch.setattr(
        query_services,
        "DjangoSignalRepository",
        lambda: repository,
    )

    assert query_services.get_signal_invalidation_payloads([2, 1, 2]) == {}
    assert received == [[1, 2]]
    with pytest.raises(ValueError):
        query_services.get_signal_invalidation_payloads([1, 0])
    with pytest.raises(ValueError, match="Too many"):
        query_services.get_signal_invalidation_payloads(list(range(1, 502)))


def test_unknown_regime_publishes_no_recommended_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query_services,
        "get_eligibility_matrix",
        lambda: {"equity": {}, "bond": {}},
    )

    assert query_services.get_recommended_assets_payload("Unknown") == {
        "recommended": [],
        "neutral": [],
        "hostile": ["bond", "equity"],
    }


def test_create_record_rejects_non_finite_threshold_before_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query_services,
        "DjangoSignalRepository",
        _fail_repository,
    )

    with pytest.raises(ValueError, match="invalidation_threshold"):
        query_services.create_investment_signal_record(
            asset_code="510300.SH",
            asset_class="a_share_growth",
            direction="LONG",
            logic_desc="PMI 回升，看好宽基指数",
            invalidation_logic="PMI < 50",
            invalidation_threshold=nan,
            invalidation_rules=None,
            target_regime="Recovery",
            is_approved=True,
            rejection_reason="",
        )


def test_stats_reject_malformed_repository_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SimpleNamespace(get_signal_management_metadata=lambda: {"stats": {"total": True}})
    monkeypatch.setattr(
        query_services,
        "DjangoSignalRepository",
        lambda: repository,
    )

    with pytest.raises(ValueError, match="statistics"):
        query_services.get_signal_stats_payload()


def test_existing_signal_validation_rejects_malformed_persisted_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query_services,
        "get_investment_signal_payload",
        lambda _signal_id: {"asset_code": {"invalid": True}},
    )

    with pytest.raises(ValueError, match="Persisted signal"):
        query_services.validate_existing_signal_payload("1")
