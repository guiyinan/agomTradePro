"""HTTP contract tests for the read-only holding-disclosure endpoint."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.simulated_trading.interface import holding_disclosure_views

_PATH = "/api/simulated-trading/accounts/17/holding-disclosures/"


def _payload() -> dict[str, object]:
    """Return one contract-shaped response while keeping source offsets visible."""

    return {
        "account_id": 17,
        "asset_code": "600000.SH",
        "as_of": "2026-11-10T01:00:00+00:00",
        "outcome": "partial",
        "scope": "simulation_only",
        "read_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "coverage_note": "Current published metrics only.",
        "blocked_reason": "",
        "freshness": "fresh",
        "reliability": "source_bound",
        "rows": [
            {
                "asset_code": "600000.SH",
                "metric_code": "net_profit",
                "value": 1.0,
                "unit": "CNY",
                "period_end": "2026-09-30",
                "period_type": "quarterly",
                "report_date": "2026-10-30",
                "announced_at": "2026-10-30T11:30:00+08:00",
                "available_at": "2026-10-30T12:00:00+08:00",
                "fetched_at": "2026-10-30T12:05:00+08:00",
                "source": "akshare",
                "source_record_id": "row-1",
                "raw_payload_hash": "a" * 64,
            }
        ],
    }


def test_unsupported_query_keys_are_rejected_before_application_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical cutoffs and refresh flags cannot silently become current reads."""

    def unexpected_read(**kwargs: object) -> dict[str, object]:
        pytest.fail(f"unexpected application call: {kwargs}")

    monkeypatch.setattr(
        holding_disclosure_views,
        "read_owned_holding_disclosures",
        unexpected_read,
    )
    view = holding_disclosure_views.HoldingDisclosureAPIView.as_view()
    for query in (
        "asset_code=600000.SH&as_of=2026-10-30",
        "asset_code=600000.SH&refresh=true",
    ):
        request = APIRequestFactory().get(f"{_PATH}?{query}")
        force_authenticate(request, user=SimpleNamespace(pk=23, is_authenticated=True))

        response = view(request, account_id=17)

        response.render()
        assert response.status_code == 400
        assert response["Content-Type"] == "application/json"


def test_padded_asset_code_uses_detail_shaped_400_before_application_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace is rejected at the HTTP boundary with the documented error shape."""

    def unexpected_read(**kwargs: object) -> dict[str, object]:
        pytest.fail(f"unexpected application call: {kwargs}")

    monkeypatch.setattr(
        holding_disclosure_views,
        "read_owned_holding_disclosures",
        unexpected_read,
    )
    view = holding_disclosure_views.HoldingDisclosureAPIView.as_view()
    request = APIRequestFactory().get(f"{_PATH}?asset_code=%20600000.SH%20")
    force_authenticate(request, user=SimpleNamespace(pk=23, is_authenticated=True))

    response = view(request, account_id=17)

    response.render()
    assert response.status_code == 400
    assert response["Content-Type"] == "application/json"
    assert response.data == {"detail": "The asset_code is invalid."}


def test_valid_read_returns_json_and_preserves_source_time_offsets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read-only response keeps original provider timestamp strings unchanged."""

    monkeypatch.setattr(
        holding_disclosure_views,
        "read_owned_holding_disclosures",
        lambda **kwargs: _payload(),
    )
    view = holding_disclosure_views.HoldingDisclosureAPIView.as_view()
    request = APIRequestFactory().get(f"{_PATH}?asset_code=600000.SH")
    force_authenticate(request, user=SimpleNamespace(pk=23, is_authenticated=True))

    response = view(request, account_id=17)

    response.render()
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    payload: dict[str, Any] = response.data
    rows = payload["rows"]
    assert isinstance(rows, list)
    assert rows[0]["announced_at"] == "2026-10-30T11:30:00+08:00"
    assert rows[0]["available_at"] == "2026-10-30T12:00:00+08:00"


def test_session_only_endpoint_rejects_anonymous_requests() -> None:
    """An account id and asset code never authorize an anonymous source read."""

    view = holding_disclosure_views.HoldingDisclosureAPIView.as_view()
    request = APIRequestFactory().get(f"{_PATH}?asset_code=600000.SH")

    response = view(request, account_id=17)

    assert response.status_code == 403
