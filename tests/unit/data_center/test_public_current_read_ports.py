"""Regression coverage for Data Center public current-read ports."""

from __future__ import annotations

import pytest

from apps.data_center.application.dtos import MacroSeriesRequest, MacroSeriesResponse
from apps.data_center.application.public import (
    get_market_breadth_snapshot,
    get_market_thermometer_payload,
    get_published_latest_quote_payload,
    get_published_macro_series_response,
    list_published_macro_indicator_summaries,
)


def test_market_thermometer_public_port_forwards_user_scope(monkeypatch) -> None:
    """User threshold scope must remain an explicit public-port parameter."""

    captured: dict[str, object] = {}

    def _fake_loader(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"status": "ok", "observed_at": "2026-08-05T08:00:00+00:00"}

    monkeypatch.setattr(
        "apps.data_center.application.interface_services.load_market_thermometer_payload",
        _fake_loader,
    )

    payload = get_market_thermometer_payload(user_id=7, use_personal_thresholds=True)

    assert payload["status"] == "ok"
    assert captured == {"user_id": 7, "use_personal_thresholds": True}


def test_market_breadth_public_port_delegates_to_governed_query(monkeypatch) -> None:
    """Realtime consumers must receive the Data Center breadth contract."""

    expected = {
        "status": "blocked",
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_publication_missing",
    }
    monkeypatch.setattr(
        "apps.data_center.application.public.query_published_a_share_behavior_payload",
        lambda: expected,
    )

    assert get_market_breadth_snapshot() == expected


def test_published_latest_quote_public_port_preserves_blocked_gate(monkeypatch) -> None:
    """Execution consumers must receive a stable blocked reason from the public port."""

    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_quote_payloads",
        lambda _codes, *, publication_key: {
            "rows": [],
            "publication_id": "pub-1",
            "dataset_key": "equity.quote.snapshot",
            "freshness_status": "stale",
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_stale",
        },
    )

    payload = get_published_latest_quote_payload(" 000001.sz ")

    assert payload == {
        "asset_code": "000001.SZ",
        "is_stale": True,
        "must_not_use_for_decision": True,
        "freshness_status": "stale",
        "blocked_reason": "canonical_publication_stale",
        "publication_id": "pub-1",
        "dataset_key": "equity.quote.snapshot",
    }


@pytest.mark.parametrize(
    ("include_flag", "flag_value"),
    [
        pytest.param(False, None, id="missing"),
        pytest.param(True, None, id="none"),
        pytest.param(True, 0, id="zero"),
        pytest.param(True, "", id="empty-string"),
        pytest.param(True, [], id="empty-list"),
        pytest.param(True, {}, id="empty-dict"),
    ],
)
def test_published_latest_quote_blocks_unverified_parent_eligibility(
    include_flag,
    flag_value,
    monkeypatch,
) -> None:
    """Missing or malformed parent eligibility is represented as an explicit block."""

    published = {
        "rows": [
            {
                "asset_code": "000001.SZ",
                "current_price": 12.3,
                "snapshot_at": "2026-08-05T07:00:00+00:00",
            }
        ],
        "publication_id": "pub-unverified",
        "dataset_key": "equity.quote.snapshot",
        "freshness_status": "fresh",
    }
    if include_flag:
        published["must_not_use_for_decision"] = flag_value
    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_quote_payloads",
        lambda _codes, *, publication_key: published,
    )

    payload = get_published_latest_quote_payload("000001.SZ")

    assert payload is not None
    assert payload["asset_code"] == "000001.SZ"
    assert payload["is_stale"] is False
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_reason"] == "publication_eligibility_unverified"
    assert "current_price" not in payload
    assert "snapshot_at" not in payload


def test_published_latest_quote_preserves_explicit_reason_for_unknown_parent(monkeypatch) -> None:
    """A known publication block reason wins over the generic unknown-eligibility reason."""

    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_quote_payloads",
        lambda _codes, *, publication_key: {
            "rows": [],
            "must_not_use_for_decision": None,
            "freshness_status": "stale",
            "blocked_reason": "canonical_publication_stale",
        },
    )

    payload = get_published_latest_quote_payload("000001.SZ")

    assert payload is not None
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_reason"] == "canonical_publication_stale"


@pytest.mark.parametrize(
    "include_row_flag", [False, True], ids=["row-flag-absent", "row-flag-false"]
)
def test_published_latest_quote_public_port_returns_member_row_with_gate_metadata(
    include_row_flag,
    monkeypatch,
) -> None:
    """Usable quote rows retain the publication identity and freshness evidence."""

    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_quote_payloads",
        lambda _codes, *, publication_key: {
            "rows": [
                {
                    "asset_code": "000001.SZ",
                    "current_price": 12.3,
                    "snapshot_at": "2026-08-05T07:00:00+00:00",
                    **({"must_not_use_for_decision": False} if include_row_flag else {}),
                }
            ],
            "publication_id": "pub-2",
            "dataset_key": "equity.quote.snapshot",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
            "blocked_reason": "",
        },
    )

    payload = get_published_latest_quote_payload("000001.SZ")

    assert payload is not None
    assert payload["current_price"] == 12.3
    assert payload["publication_id"] == "pub-2"
    assert payload["freshness_status"] == "fresh"
    assert payload["must_not_use_for_decision"] is False
    assert payload["is_stale"] is False


@pytest.mark.parametrize("row_flag", [True, None, 0, "", [], {}])
def test_published_latest_quote_blocks_present_non_false_row_eligibility(
    row_flag,
    monkeypatch,
) -> None:
    """A malformed row flag is promoted to a blocked result instead of defaulting false."""

    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_quote_payloads",
        lambda _codes, *, publication_key: {
            "rows": [
                {
                    "asset_code": "000001.SZ",
                    "current_price": 12.3,
                    "snapshot_at": "2026-08-05T07:00:00+00:00",
                    "must_not_use_for_decision": row_flag,
                }
            ],
            "publication_id": "pub-row-unverified",
            "dataset_key": "equity.quote.snapshot",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
            "blocked_reason": "",
        },
    )

    payload = get_published_latest_quote_payload("000001.SZ")

    assert payload is not None
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_reason"] == "publication_eligibility_unverified"
    assert "current_price" not in payload


def test_published_latest_quote_preserves_explicit_row_block_reason(monkeypatch) -> None:
    """An explicit member block reason survives wrapper normalization."""

    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_quote_payloads",
        lambda _codes, *, publication_key: {
            "rows": [
                {
                    "asset_code": "000001.SZ",
                    "current_price": 12.3,
                    "must_not_use_for_decision": True,
                    "blocked_reason": "quote_member_not_decision_safe",
                }
            ],
            "publication_id": "pub-row-blocked",
            "dataset_key": "equity.quote.snapshot",
            "must_not_use_for_decision": False,
        },
    )

    payload = get_published_latest_quote_payload("000001.SZ")

    assert payload is not None
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_reason"] == "quote_member_not_decision_safe"


def test_published_macro_series_public_port_binds_publication_members(monkeypatch) -> None:
    """Macro trend consumers must query only the selected publication members."""

    captured: list[MacroSeriesRequest] = []

    class _UseCase:
        def execute(self, request: MacroSeriesRequest) -> MacroSeriesResponse:
            captured.append(request)
            return MacroSeriesResponse(
                indicator_code=request.indicator_code,
                name_cn="M2",
                period_type="M",
                data_source="data_center_fact",
                freshness_status="fresh",
                decision_grade="decision_safe",
                must_not_use_for_decision=False,
            )

    monkeypatch.setattr(
        "apps.data_center.application.public.get_current_publication_freshness_gate",
        lambda _dataset_key, _publication_key: {
            "publication_id": "pub-m2",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
        },
    )
    monkeypatch.setattr(
        "apps.data_center.application.public.get_publication_member_fact_pks",
        lambda _publication_id, *, dataset_key, expected_fact_table: ["42"],
    )
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.make_query_macro_series_use_case",
        lambda: _UseCase(),
    )

    result = get_published_macro_series_response("CN_M2", limit=12)

    assert result.decision_grade == "decision_safe"
    assert captured[0].fact_pks == ["42"]
    assert captured[0].limit == 12


def test_published_macro_series_public_port_blocks_without_publication(monkeypatch) -> None:
    """Missing macro publication must not invoke the raw series use case."""

    called = False

    def _unexpected_use_case() -> object:
        nonlocal called
        called = True
        raise AssertionError("raw macro series use case must not run")

    monkeypatch.setattr(
        "apps.data_center.application.public.get_current_publication_freshness_gate",
        lambda _dataset_key, _publication_key: None,
    )
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.make_query_macro_series_use_case",
        _unexpected_use_case,
    )

    result = get_published_macro_series_response("CN_M2")

    assert result.data == []
    assert result.must_not_use_for_decision is True
    assert result.blocked_reason == "canonical_publication_missing"
    assert called is False


def test_published_macro_indicator_summaries_preserve_gate_and_source_observation(
    monkeypatch,
) -> None:
    """Current indicator discovery must expose only published source observations."""

    monkeypatch.setattr(
        "apps.data_center.application.public.get_macro_runtime_metadata",
        lambda: {"CN_PMI": {"name": "采购经理指数", "category": "growth", "unit": "指数"}},
    )
    monkeypatch.setattr(
        "apps.data_center.application.public.list_latest_published_macro_values",
        lambda *, limit: [
            {
                "indicator_code": "CN_PMI",
                "value": "50.4",
                "unit": "指数",
                "reporting_period": "2026-07-31",
                "source": "akshare",
                "publication_id": "pub-pmi",
                "freshness_status": "fresh",
                "must_not_use_for_decision": False,
                "blocked_reason": "",
            }
        ],
    )

    summaries = list_published_macro_indicator_summaries(limit=10)

    assert summaries == [
        {
            "code": "CN_PMI",
            "name": "采购经理指数",
            "category": "growth",
            "latest_value": 50.4,
            "unit": "指数",
            "latest_date": "2026-07-31",
            "observed_at": "2026-07-31",
            "source": "akshare",
            "publication_id": "pub-pmi",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
            "blocked_reason": "",
        }
    ]


@pytest.mark.parametrize(
    ("metadata", "expected_stale"),
    [
        pytest.param({"freshness_status": "fresh"}, False, id="fresh"),
        pytest.param({"freshness_status": "stale"}, True, id="stale"),
        pytest.param({"freshness_status": "blocked"}, None, id="unverified"),
        pytest.param({}, None, id="missing"),
        pytest.param({"is_stale": False}, False, id="explicit-not-stale"),
        pytest.param({"is_stale": True}, True, id="explicit-stale"),
    ],
)
def test_unknown_quote_eligibility_preserves_known_or_unknown_staleness(
    metadata,
    expected_stale,
    monkeypatch,
) -> None:
    """Decision qualification cannot manufacture a stale observation."""
    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_quote_payloads",
        lambda _codes, *, publication_key: {"rows": [], **metadata},
    )
    payload = get_published_latest_quote_payload("000001.SZ")
    assert payload is not None
    assert payload["must_not_use_for_decision"] is True
    assert payload["is_stale"] is expected_stale
    assert payload["blocked_reason"] == "publication_eligibility_unverified"


def test_blocked_quote_preserves_member_freshness_separately_from_parent(monkeypatch) -> None:
    """Member staleness remains available even when its parent publication is fresh."""
    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_quote_payloads",
        lambda _codes, *, publication_key: {
            "rows": [
                {
                    "asset_code": "000001.SZ",
                    "must_not_use_for_decision": True,
                    "freshness_status": "stale",
                    "is_stale": True,
                }
            ],
            "must_not_use_for_decision": False,
            "freshness_status": "fresh",
            "is_stale": False,
            "publication_id": "parent-publication",
            "dataset_key": "equity.quote.snapshot",
        },
    )
    payload = get_published_latest_quote_payload("000001.SZ")
    assert payload is not None
    assert payload["must_not_use_for_decision"] is True
    assert payload["is_stale"] is True
    assert payload["freshness_status"] == "stale"
    assert payload["publication_id"] == "parent-publication"
    assert "current_price" not in payload
